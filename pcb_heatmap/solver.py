"""Original local DC / steady-state thermal finite-volume solver.

The grid is a 2.5-D engineering approximation, not a component/package or CFD
model. There is no network access and no modification of board input arrays.
Only NumPy is required. Electrical current and edge Joule energy are conserved.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable
import numpy as np

try:
    from .model import AnalysisError, RasterBoard, Scenario, Result
    from .materials import substrate_conductivities
except ImportError:  # KiCad can launch the worker as a standalone script.
    from model import AnalysisError, RasterBoard, Scenario, Result
    from materials import substrate_conductivities


_EPS = 1e-12


def _check_cancel(cancel):
    if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):
        raise AnalysisError('Analysis cancelled.')


def _progress(callback, text, fraction):
    if callback:
        callback(text, float(fraction))


def _positive(value, name, allow_zero=False):
    if not np.isfinite(value) or (value < 0 if allow_zero else value <= 0):
        raise AnalysisError(f'{name} must be finite and ' + ('nonnegative.' if allow_zero else 'positive.'))


def _harmonic(a, b):
    return np.divide(2 * a * b, a + b, out=np.zeros_like(a + b, dtype=float), where=(a + b) > 0)


class _BlockMultiply:
    """Exact graph multiply with batched complete-bipartite via-ring blocks.

    Distributed annuli can have hundreds of cells per side. Scattering each
    individual ring-to-ring edge at every PCG step is much more expensive than
    their equivalent small block products. Thermal constant-G blocks further
    reduce exactly to sums of the two ring potentials. No contact is removed.
    """

    def __init__(self, diagonal, left, right, conductance, blocks):
        self.diagonal, self.left, self.right, self.g = diagonal, left, right, conductance
        self.n = len(diagonal)
        grouped = {}
        for a, b, g in blocks:
            if not len(a) or not len(b):
                continue
            key = (len(a), len(b), np.ndim(g) == 0)
            grouped.setdefault(key, []).append((a, b, g))
        self.groups = []
        nodes = []
        for (na, nb, constant), records in grouped.items():
            a = np.stack([record[0] for record in records])
            b = np.stack([record[1] for record in records])
            g = np.asarray([record[2] for record in records])
            self.groups.append((a, b, g, constant))
            nodes.extend((a.ravel(), b.ravel()))
        self.nodes = np.concatenate(nodes) if nodes else np.empty(0, dtype=np.int64)

    def __call__(self, x):
        answer = self.diagonal * x
        answer -= np.bincount(self.left, weights=self.g * x[self.right], minlength=self.n)
        answer -= np.bincount(self.right, weights=self.g * x[self.left], minlength=self.n)
        weights = []
        for a, b, g, constant in self.groups:
            if constant:
                ga = g * x[b].sum(axis=1)
                gb = g * x[a].sum(axis=1)
                weights.extend((np.broadcast_to(ga[:, None], a.shape).ravel(),
                                np.broadcast_to(gb[:, None], b.shape).ravel()))
            else:
                weights.extend((np.einsum('bij,bj->bi', g, x[b]).ravel(),
                                np.einsum('bij,bi->bj', g, x[a]).ravel()))
        if weights:
            answer -= np.bincount(self.nodes, weights=np.concatenate(weights), minlength=self.n)
        return answer


class _RecycledGuesses:
    """Energy-orthogonal previous solutions for a fixed thermal matrix.

    Joule heating changes smoothly during temperature feedback. Projecting
    each new right-hand side onto prior exact solutions avoids resolving its
    dominant common spatial pattern. The full fine-grid residual still has to
    converge. Storage is bounded to about 64 MB, including A-times-basis.
    """

    def __init__(self, size):
        self.limit = min(10, 4_000_000 // max(size, 1))
        self.basis = []
        self.products = []

    def guess(self, rhs, fallback):
        if not self.basis:
            return fallback
        answer = np.zeros_like(rhs)
        for vector in self.basis:
            answer += vector * np.dot(vector, rhs)
        return answer

    def add(self, solution, multiply):
        if len(self.basis) >= self.limit:
            return
        vector = solution.copy()
        product = multiply(vector)
        initial_energy = float(np.dot(vector, product))
        if initial_energy <= 0:
            return
        # Reorthogonalize because feedback solutions can be nearly parallel.
        for _ in range(2):
            for old, old_product in zip(self.basis, self.products):
                weight = float(np.dot(old, product))
                vector -= weight * old
                product -= weight * old_product
        energy = float(np.dot(vector, product))
        if energy <= initial_energy * 1e-14:
            return
        scale = math.sqrt(energy)
        self.basis.append(vector / scale)
        self.products.append(product / scale)


class _GraphLevel:
    """Symmetric aggregation V-cycle, used only as a PCG preconditioner.

    The coarse matrices are P.T @ A @ P for piecewise constant aggregates.
    This does NOT replace the fine electrical/thermal mesh: PCG still checks
    its residual on every original cell, face and via edge.  One damped Jacobi
    step before and after coarse correction makes the V-cycle symmetric and
    positive definite for a grounded positive-conductance graph.
    """

    def __init__(self, diagonal, left, right, conductance, coordinates,
                 cancel=None, boundary=None, depth=0, matvec=None):
        _check_cancel(cancel)
        self.diagonal, self.left, self.right, self.g = diagonal, left, right, conductance
        self.n = len(diagonal)
        self.smoother = (2. / 3.) / diagonal
        self.child = None
        self.inverse = None
        self.matvec = matvec
        if self.n <= 96:
            matrix = np.diag(diagonal)
            np.add.at(matrix, (left, right), -conductance)
            np.add.at(matrix, (right, left), -conductance)
            # Factor once, never once per PCG iteration. Symmetrization avoids
            # a roundoff asymmetry in the cached dense coarse inverse.
            factor = np.linalg.cholesky(matrix)
            inverse_factor = np.linalg.solve(factor, np.eye(self.n))
            self.inverse = inverse_factor.T @ inverse_factor
            return
        if depth >= 24:
            raise np.linalg.LinAlgError('Aggregation did not reduce the conduction graph.')

        coarse_coordinates = coordinates.copy()
        # Keep the physical layers separate while aggregating 2x2 XY cells.
        coarse_coordinates[:, 1:] //= 2
        unique, mapping = np.unique(coarse_coordinates, axis=0, return_inverse=True)
        if len(unique) >= self.n * .9:
            # Sparse slender paths can have little XY reduction; then also
            # aggregate adjacent layer coordinates. This remains only P.T A P.
            unique, mapping = np.unique(coordinates // 2, axis=0, return_inverse=True)
        if len(unique) >= self.n:
            raise np.linalg.LinAlgError('Aggregation did not reduce the conduction graph.')
        self.mapping = mapping
        coarse_n = len(unique)
        a, b = mapping[left], mapping[right]
        outside = a != b
        a, b = a[outside], b[outside]
        # Coalesce parallel coarse edges, including all physical via edges.
        encoded = np.minimum(a, b) * coarse_n + np.maximum(a, b)
        if len(encoded):
            order = np.argsort(encoded)
            encoded = encoded[order]
            starts = np.r_[0, 1 + np.flatnonzero(encoded[1:] != encoded[:-1])]
            coarse_g = np.add.reduceat(conductance[outside][order], starts)
            keys = encoded[starts]
            coarse_left, coarse_right = keys // coarse_n, keys % coarse_n
        else:
            coarse_g = np.empty(0)
            coarse_left = coarse_right = np.empty(0, dtype=np.int64)
        if boundary is None:
            boundary = diagonal - np.bincount(left, weights=conductance, minlength=self.n)
            boundary -= np.bincount(right, weights=conductance, minlength=self.n)
            # Roundoff in diagonal minus incident edges can be slightly below
            # zero. Only the preconditioner is affected by this numerical clip.
            boundary = np.maximum(boundary, 0.)
        coarse_boundary = np.bincount(mapping, weights=boundary, minlength=coarse_n)
        coarse_diagonal = coarse_boundary + np.bincount(coarse_left, weights=coarse_g, minlength=coarse_n)
        coarse_diagonal += np.bincount(coarse_right, weights=coarse_g, minlength=coarse_n)
        self.child = _GraphLevel(coarse_diagonal, coarse_left, coarse_right,
                                 coarse_g, unique, cancel, coarse_boundary, depth + 1)

    def multiply(self, x):
        if self.matvec is not None:
            return self.matvec(x)
        answer = self.diagonal * x
        answer -= np.bincount(self.left, weights=self.g * x[self.right], minlength=self.n)
        answer -= np.bincount(self.right, weights=self.g * x[self.left], minlength=self.n)
        return answer

    def __call__(self, rhs):
        if self.inverse is not None:
            return self.inverse @ rhs
        x = self.smoother * rhs
        residual = rhs - self.multiply(x)
        coarse_rhs = np.bincount(self.mapping, weights=residual, minlength=self.child.n)
        x += self.child(coarse_rhs)[self.mapping]
        x += self.smoother * (rhs - self.multiply(x))
        return x


def _preconditioner(diagonal, left, right, conductance, flat, shape,
                    cancel=None, boundary=None, matvec=None):
    # Small systems are cheaper with plain Jacobi. A coarse factorization
    # failure falls back to it; fine-grid convergence checks are unchanged.
    if len(diagonal) < 1024:
        return None
    coordinates = np.asarray(np.unravel_index(flat, shape)).T
    try:
        return _GraphLevel(diagonal, left, right, conductance, coordinates,
                           cancel, boundary, matvec=matvec)
    except np.linalg.LinAlgError:
        return None


def _pcg(diagonal, left, right, conductance, rhs, tolerance, cancel=None, guess=None,
         preconditioner=None, matvec=None, progress=None):
    """Graph PCG with a symmetric V-cycle or Jacobi preconditioner."""
    n = len(rhs)
    if not n:
        return np.empty(0), 0, 0.0
    if np.any(diagonal <= 0) or not np.all(np.isfinite(diagonal)):
        raise AnalysisError('Singular or invalid conduction system; check sources and thermal boundary conditions.')

    def multiply(x):
        if matvec is not None:
            return matvec(x)
        answer = diagonal * x
        if len(left):
            answer -= np.bincount(left, weights=conductance * x[right], minlength=n)
            answer -= np.bincount(right, weights=conductance * x[left], minlength=n)
        return answer

    x = np.zeros(n) if guess is None else np.asarray(guess, dtype=float).copy()
    r = rhs - multiply(x)
    scale = max(float(np.linalg.norm(rhs)), 1e-15)
    target = max(tolerance * scale, 1e-14)
    residual = float(np.linalg.norm(r))
    if residual <= target:
        return x, 0, residual / scale
    z = r / diagonal if preconditioner is None else preconditioner(r)
    direction = z.copy()
    rz = float(np.dot(r, z))
    limit = min(20000, max(300, int(30 * math.sqrt(n))))
    last_progress = time.monotonic()
    for iteration in range(1, limit + 1):
        if iteration % 16 == 0:
            _check_cancel(cancel)
        product = multiply(direction)
        denom = float(np.dot(direction, product))
        if denom <= 0 or not np.isfinite(denom) or not np.isfinite(rz):
            raise AnalysisError('Conduction solve lost positive definiteness; input or numerical model is invalid.')
        step = rz / denom
        x += step * direction
        r -= step * product
        residual = float(np.linalg.norm(r))
        if progress and iteration % 8 == 0 and time.monotonic() - last_progress >= 1.:
            progress(iteration, residual / scale)
            last_progress = time.monotonic()
        if residual <= target:
            # Recheck the true residual to avoid a misleading recurrence result.
            true_r = rhs - multiply(x)
            true_residual = float(np.linalg.norm(true_r))
            if true_residual <= max(target * 5, 1e-12 * scale):
                return x, iteration, true_residual / scale
            r = true_r
        z = r / diagonal if preconditioner is None else preconditioner(r)
        next_rz = float(np.dot(r, z))
        direction = z + (next_rz / rz) * direction
        rz = next_rz
    raise AnalysisError(f'Conduction solver did not converge after {limit} iterations (relative residual {residual / scale:.3g}).')


def _components(n, left, right, cancel=None):
    """Parallel minimum-root hooking and pointer jumping, NumPy only.

    Native annulus contacts can generate millions of graph edges. Iterating
    those edges in Python dominated preparation on via-dense boards. Hooks
    always lower a root ID, so they cannot introduce cycles or bridge a gap.
    Convergence is exact: every actual edge must have equal endpoint roots.
    """
    parent = np.arange(n, dtype=np.int64)
    while len(left):
        _check_cancel(cancel)
        a, b = parent[left], parent[right]
        different = a != b
        if not np.any(different):
            break
        a, b = a[different], b[different]
        np.minimum.at(parent, np.maximum(a, b), np.minimum(a, b))
        while True:
            jumped = parent[parent]
            if np.array_equal(jumped, parent):
                break
            parent = jumped
    return parent


def _faces(board, net, coverage):
    data = board.metadata.get('net_edges', {}).get(net, {}) if net is not None else board.metadata.get('copper_edges', {})
    result = []
    for key, a, b in [('x', coverage[:, :, :-1], coverage[:, :, 1:]),
                      ('y', coverage[:, :-1, :], coverage[:, 1:, :])]:
        if key in data:
            face = np.asarray(data[key], dtype=float)
            if face.shape != a.shape or not np.all(np.isfinite(face)) or np.any((face < 0) | (face > 1)):
                raise AnalysisError(f'Invalid {key} face geometry for net {net or "all copper"}.')
            face = np.where((a > 0) & (b > 0), face, 0)
        else:
            face = _harmonic(a, b)
        result.append(face)
    return result


def _via_area(via):
    # Finished hole plus plated wall; pad diameter is not barrel diameter.
    _positive(via.drill_mm, 'Via finished hole')
    _positive(via.plating_um, 'Via wall plating')
    _positive(via.diameter_mm, 'Via pad diameter')
    plating_mm = via.plating_um / 1000
    if via.diameter_mm + 1e-10 < via.drill_mm + 2 * plating_mm:
        raise AnalysisError(f'Via {via.identifier!r} pad is smaller than its plated barrel.')
    return math.pi * ((via.drill_mm + 2 * plating_mm) ** 2 - via.drill_mm ** 2) / 4 * 1e-6


def _via_cell(board, via):
    r = int(math.floor((via.y_mm - board.origin_y_mm) / board.cell_mm))
    c = int(math.floor((via.x_mm - board.origin_x_mm) / board.cell_mm))
    if not (0 <= r < board.board_mask.shape[0] and 0 <= c < board.board_mask.shape[1]) or not board.board_mask[r, c]:
        raise AnalysisError(f'Via {via.identifier!r} is outside the thermal mesh; refine the grid or board outline.')
    return r, c


def _via_contacts(board, via_index, layer, index=None):
    """Actual annulus contacts, with legacy center-cell fallback for test grids."""
    via = board.vias[via_index]
    if not np.isfinite(via.x_mm) or not np.isfinite(via.y_mm):
        raise AnalysisError(f'Via {via.identifier or via_index} has nonfinite coordinates.')
    all_contacts = board.metadata.get('via_cells', [])
    if via_index < len(all_contacts):
        item = all_contacts[via_index]
        cells = item.get(layer, item.get(str(layer), []))
    else:
        cells = [_via_cell(board, via)]
    result = set()
    for r, c in cells:
        r, c = int(r), int(c)
        if not (0 <= r < board.board_mask.shape[0] and 0 <= c < board.board_mask.shape[1]) or not board.board_mask[r, c]:
            raise AnalysisError(f'Via {via.identifier or via_index} has an invalid ring contact cell.')
        if index is None or index[layer, r, c] >= 0:
            result.add((r, c))
    return sorted(result)


def _pad_nodes(board, pad_ids, net=None):
    if not pad_ids:
        raise AnalysisError('A terminal/heater has no selected pads.')
    cells = set()
    nets = set()
    for identifier in pad_ids:
        if identifier not in board.pads:
            raise AnalysisError(f'Unknown pad {identifier!r}.')
        pad = board.pads[identifier]
        nets.add(pad.net)
        found = board.pad_cells.get(identifier, [])
        if not found:
            raise AnalysisError(f'Pad {pad.label or identifier} has no mesh cells; use a finer mesh.')
        for cell in found:
            if len(cell) != 3 or any(i < 0 or i >= size for i, size in zip(cell, board.copper.shape)):
                raise AnalysisError(f'Pad {pad.label or identifier} has invalid mesh cells.')
            cell = tuple(int(i) for i in cell)
            if not board.board_mask[cell[1], cell[2]]:
                raise AnalysisError(f'Pad {pad.label or identifier} is outside the board mesh.')
            if net is not None and board.net_copper[net][cell] <= 0:
                raise AnalysisError(f'Pad {pad.label or identifier} is not resolved in its copper net; use a finer mesh.')
            cells.add(cell)
    if net is not None and nets != {net}:
        raise AnalysisError('A source or load group must contain pads on one net only.')
    return sorted(cells)


@dataclass
class _Electrical:
    net: str
    coverage: np.ndarray
    flat: np.ndarray
    index: np.ndarray
    left: np.ndarray
    right: np.ndarray
    base: np.ndarray  # geometry A / length in metres, multiply by conductivity
    via_indices: np.ndarray  # -1 for planar edge, otherwise physical via index
    fixed: np.ndarray
    fixed_voltage: np.ndarray
    sinks: np.ndarray
    energized: np.ndarray
    via_segments: list
    floating_nodes: int
    planar_count: int
    guess: np.ndarray | None = None
    preconditioner: object = None
    preconditioner_built: bool = False


def _make_electrical(board, scenario, net, z, cancel):
    coverage = np.asarray(board.net_copper[net], dtype=float)
    shape = coverage.shape
    flat = np.flatnonzero((coverage > 0) & board.board_mask[None, :, :])
    if not len(flat):
        raise AnalysisError(f'Net {net!r} has no copper in the mesh.')
    index = np.full(np.prod(shape), -1, dtype=np.int64)
    index[flat] = np.arange(len(flat))
    index = index.reshape(shape)
    left, right, base, via_ids = [], [], [], []
    fx, fy = _faces(board, net, coverage)
    thickness = np.asarray([layer.thickness_mm * 1e-3 for layer in board.layers])[:, None, None]
    for a, b, face in [(index[:, :, :-1], index[:, :, 1:], fx),
                       (index[:, :-1, :], index[:, 1:, :], fy)]:
        good = (a >= 0) & (b >= 0) & (face > _EPS)
        left.append(a[good]); right.append(b[good])
        base.append((face * thickness)[good])
        via_ids.append(np.full(int(good.sum()), -1, dtype=np.int64))
    edge_count = sum(map(len, left))
    via_segments = []
    for vi, via in enumerate(board.vias):
        if via.net != net:
            continue
        area = _via_area(via)
        low, high = sorted((via.start_layer, via.end_layer))
        ring = {layer: _via_contacts(board, vi, layer, index) for layer in range(low, high + 1)}
        contacts = [layer for layer in range(low, high + 1) if ring[layer]]
        if low not in contacts or high not in contacts:
            raise AnalysisError(f'Via {via.identifier or vi} on {net} has an unresolved endpoint; use a finer mesh.')
        for l1, l2 in zip(contacts[:-1], contacts[1:]):
            # Distributed annulus coupling; total G is exactly sigma*A/span.
            share = area / (z[l2] - z[l1]) / (len(ring[l1]) * len(ring[l2]))
            a = np.asarray([index[l1, r, c] for r, c in ring[l1]])
            b = np.asarray([index[l2, r, c] for r, c in ring[l2]])
            count = len(a) * len(b)
            left.append(np.repeat(a, len(b))); right.append(np.tile(b, len(a)))
            base.append(np.full(count, share))
            via_ids.append(np.full(count, vi, dtype=np.int64))
            # One range per physical barrel segment, not one Python tuple per
            # distributed ring-to-ring edge. Every fine edge is still present.
            via_segments.append((edge_count, edge_count + count, vi, l1, l2, a, b))
            edge_count += count
    left, right = np.concatenate(left), np.concatenate(right)
    base, via_ids = np.concatenate(base), np.concatenate(via_ids)
    labels = _components(len(flat), left, right, cancel)
    _check_cancel(cancel)
    fixed = np.zeros(len(flat), dtype=bool)
    fixed_voltage = np.zeros(len(flat))
    sinks = np.zeros(len(flat))
    for source in scenario.sources:
        if board.pads[source.pad_ids[0]].net != net:
            continue
        for cell in _pad_nodes(board, source.pad_ids, net):
            node = index[cell]
            if fixed[node] and abs(fixed_voltage[node] - source.voltage_v) > 1e-9:
                raise AnalysisError('Contacting source terminals have incompatible voltages.')
            fixed[node], fixed_voltage[node] = True, source.voltage_v
    for load in scenario.loads:
        if board.pads[load.pad_ids[0]].net != net:
            continue
        cells = _pad_nodes(board, load.pad_ids, net)
        nodes = np.asarray([index[cell] for cell in cells])
        if np.any(fixed[nodes]):
            raise AnalysisError('Source and load terminal cells overlap; refine the grid or choose separate pads.')
        # Load current belongs to the whole group, never to every selected pad.
        np.add.at(sinks, nodes, load.current_a / len(nodes))
    source_components = np.unique(labels[fixed])
    energized = np.isin(labels, source_components)
    if np.any((sinks != 0) & ~energized):
        raise AnalysisError(f'A load on net {net!r} has no physical connection to a source. Check layer/via connectivity and mesh size.')
    return _Electrical(net, coverage, flat, index, left, right, base, via_ids,
                       fixed, fixed_voltage, sinks, energized, via_segments,
                       int((~energized).sum()), int(np.count_nonzero(via_ids < 0)))


def _solve_electrical(graph, temperature, settings, cancel, progress=None):
    t = temperature.ravel()[graph.flat]
    rho = settings.rho20 * (1 + settings.alpha * (t - 20))
    if not np.all(np.isfinite(rho)) or np.any(rho <= 0):
        raise AnalysisError('Temperature-dependent copper resistivity is nonphysical.')
    full_g = graph.base / ((rho[graph.left] + rho[graph.right]) / 2)
    energized_edges = graph.energized[graph.left] & graph.energized[graph.right]
    left, right, g = graph.left[energized_edges], graph.right[energized_edges], full_g[energized_edges]
    nodes = np.flatnonzero(graph.energized & ~graph.fixed)
    mapping = np.full(len(graph.flat), -1, dtype=np.int64)
    mapping[nodes] = np.arange(len(nodes))
    diagonal_all = np.bincount(left, weights=g, minlength=len(graph.flat)) + np.bincount(right, weights=g, minlength=len(graph.flat))
    offset = float(graph.fixed_voltage[graph.fixed][0]) if np.any(graph.fixed) else 0.0
    vfixed = graph.fixed_voltage - offset
    rhs = -graph.sinks[nodes].copy()
    lf, rf = graph.fixed[left], graph.fixed[right]
    select = ~lf & rf
    rhs += np.bincount(mapping[left[select]], weights=g[select] * vfixed[right[select]], minlength=len(nodes))
    select = lf & ~rf
    rhs += np.bincount(mapping[right[select]], weights=g[select] * vfixed[left[select]], minlength=len(nodes))
    uu = ~lf & ~rf
    diagonal, ul, ur, ug = diagonal_all[nodes], mapping[left[uu]], mapping[right[uu]], g[uu]
    planar = (graph.via_indices[energized_edges] < 0) & uu
    blocks = []
    for start, end, _, _, _, a, b in graph.via_segments:
        ma, mb = mapping[a], mapping[b]
        keep_a, keep_b = ma >= 0, mb >= 0
        if np.any(keep_a) and np.any(keep_b):
            block = full_g[start:end].reshape(len(a), len(b))[keep_a][:, keep_b]
            blocks.append((ma[keep_a], mb[keep_b], block))
    matvec = _BlockMultiply(diagonal, mapping[left[planar]], mapping[right[planar]], g[planar], blocks)
    if not graph.preconditioner_built:
        graph.preconditioner = _preconditioner(diagonal, ul, ur, ug, graph.flat[nodes],
                                               graph.coverage.shape, cancel, matvec=matvec)
        graph.preconditioner_built = True
    # Reuse both the hierarchy and last voltage during resistivity feedback.
    # A fixed SPD preconditioner remains valid when positive resistances vary.
    solution, iterations, residual = _pcg(diagonal, ul, ur, ug, rhs,
                                          settings.solver_tolerance, cancel,
                                          graph.guess, graph.preconditioner, matvec, progress)
    graph.guess = solution
    voltage = np.full(len(graph.flat), np.nan)
    voltage[graph.fixed] = vfixed[graph.fixed]
    voltage[nodes] = solution
    # All edge differences use shifted voltage to preserve small voltage drops.
    current = g * (voltage[left] - voltage[right])
    power = current * current / g
    heat = np.bincount(left, weights=power / 2, minlength=len(graph.flat)) + np.bincount(right, weights=power / 2, minlength=len(graph.flat))
    balance = np.bincount(left, weights=current, minlength=len(graph.flat)) - np.bincount(right, weights=current, minlength=len(graph.flat))
    source_current = float(balance[graph.fixed].sum())
    specified_current = float(graph.sinks.sum())
    abs_voltage = voltage + offset
    electrical_power = float(np.dot(abs_voltage[graph.fixed], balance[graph.fixed]) - np.nansum(abs_voltage * graph.sinks))
    if abs(source_current - specified_current) > max(1e-6, float(np.abs(graph.sinks).sum()) * 1e-6):
        raise AnalysisError(f'Electrical current balance failed on {graph.net}; use a finer mesh or tighter solver tolerance.')
    # Cell current density is an average of magnitudes on the opposing planar faces.
    edge_current = np.zeros(len(graph.left))
    edge_current[energized_edges] = current
    edge_j = np.zeros(len(graph.left))
    planar = graph.via_indices < 0
    cell_m = float(settings._cell_m)  # internal validated setting copy, never user's object
    edge_j[planar] = np.abs(edge_current[planar]) / (graph.base[planar] * cell_m) / 1e6
    weighted_j2 = np.zeros(len(graph.flat))
    width = graph.coverage.shape[2]
    height = graph.coverage.shape[1]
    row_left = (graph.flat[graph.left] // width) % height
    row_right = (graph.flat[graph.right] // width) % height
    for axis_kind in ['x', 'y']:
        axis = planar & ((row_left == row_right) if axis_kind == 'x' else (row_right == row_left + 1))
        face_j = np.bincount(graph.left[axis], weights=edge_j[axis], minlength=len(graph.flat)) + np.bincount(graph.right[axis], weights=edge_j[axis], minlength=len(graph.flat))
        count = np.bincount(graph.left[axis], minlength=len(graph.flat)) + np.bincount(graph.right[axis], minlength=len(graph.flat))
        face_j = np.divide(face_j, count, out=np.zeros(len(graph.flat), dtype=float), where=count > 0)
        weighted_j2 += face_j * face_j
    density = np.sqrt(weighted_j2)
    density[~graph.energized] = np.nan
    edge_power = np.zeros(len(graph.left))
    edge_power[energized_edges] = power
    via_output = [{'via_index': int(vi), 'from_layer': int(first), 'to_layer': int(last),
                   'current_a': float(edge_current[start:end].sum()),
                   'loss_w': float(edge_power[start:end].sum())}
                  for start, end, vi, first, last, _, _ in graph.via_segments]
    finite_v = abs_voltage[np.isfinite(abs_voltage)]
    summary = {'source_current_a': source_current, 'load_current_a': specified_current,
               'joule_w': float(power.sum()), 'electrical_power_balance_w': electrical_power,
               'energy_error_w': electrical_power - float(power.sum()),
               'voltage_min_v': float(finite_v.min()) if len(finite_v) else None,
               'voltage_max_v': float(finite_v.max()) if len(finite_v) else None,
               'max_delta_v': float(finite_v.max() - finite_v.min()) if len(finite_v) else 0,
               'max_current_density_a_mm2': float(np.nanmax(density)) if np.any(np.isfinite(density)) else 0,
               'floating_copper_cells': graph.floating_nodes, 'pcg_iterations': iterations, 'relative_residual': residual}
    return abs_voltage, density, heat, via_output, summary


def _solve_electrical_maps(graphs, shape, temperature, settings, cancel, progress=None, phase_progress=.08):
    """One unchanged DC solve, shared by thermal feedback and DC-only views."""
    joule = np.zeros(shape)
    voltages, densities, summaries, via_segments = {}, {}, {}, []
    for graph in graphs:
        voltage, density, heat, via_output, summary = _solve_electrical(
            graph, temperature, settings, cancel,
            lambda step, residual, net=graph.net: _progress(
                progress, f'DC {net}: {step} iterations, relative residual {residual:.2g}', phase_progress))
        v = np.full(shape, np.nan); v.ravel()[graph.flat] = voltage
        j = np.full(shape, np.nan); j.ravel()[graph.flat] = density
        voltages[graph.net], densities[graph.net], summaries[graph.net] = v, j, summary
        joule.ravel()[graph.flat] += heat
        via_segments.extend(via_output)
    return voltages, densities, summaries, joule, via_segments


def _reference_dc_result(settings, voltages, densities, summaries, joule, via_segments):
    """Contains no temperature field or inferred thermal peak."""
    return dict(reference_temperature_c=float(settings.ambient_c),
                voltage_v=voltages, current_density_a_mm2=densities, joule_w=joule,
                summaries=dict(nets=summaries, joule_w=float(joule.sum())),
                via_segments=via_segments)


def _thermal_system(board, settings, z, board_thickness_m):
    k_xy, k_z = substrate_conductivities(settings)
    shape = board.copper.shape
    flat = np.flatnonzero(np.broadcast_to(board.board_mask, shape))
    index = np.full(np.prod(shape), -1, dtype=np.int64)
    index[flat] = np.arange(len(flat))
    index = index.reshape(shape)
    boundaries = np.r_[0., (z[:-1] + z[1:]) / 2, board_thickness_m]
    slices = np.diff(boundaries)
    copper_t = np.asarray([layer.thickness_mm for layer in board.layers]) * 1e-3
    if np.any(slices <= 0) or np.any(copper_t > slices + 1e-12):
        raise AnalysisError('Copper layer centers/thicknesses do not fit inside the board thickness.')
    left, right, conductance = [], [], []
    fx, fy = _faces(board, None, np.asarray(board.copper))
    for a, b, face in [(index[:, :, :-1], index[:, :, 1:], fx),
                       (index[:, :-1, :], index[:, 1:, :], fy)]:
        good = (a >= 0) & (b >= 0)
        # Insulating substrate carries heat across gaps between electrical nets.
        sheet = k_xy * slices[:, None, None] + (settings.copper_k - k_xy) * copper_t[:, None, None] * face
        left.append(a[good]); right.append(b[good]); conductance.append(sheet[good])
    area = (board.cell_mm * 1e-3) ** 2
    for layer in range(len(z) - 1):
        a, b = index[layer], index[layer + 1]
        good = (a >= 0) & (b >= 0)
        cu_half = (copper_t[layer] * board.copper[layer] + copper_t[layer + 1] * board.copper[layer + 1]) / 2
        spacing = z[layer + 1] - z[layer]
        if np.any(cu_half[good] > spacing + 1e-12):
            raise AnalysisError('Overlapping copper layers in the physical stackup.')
        resistance_area = np.maximum(spacing - cu_half, 0) / k_z + cu_half / settings.copper_k
        left.append(a[good]); right.append(b[good]); conductance.append(area / resistance_area[good])
    base_left, base_right, base_g = np.concatenate(left), np.concatenate(right), np.concatenate(conductance)
    blocks = []
    for vi, via in enumerate(board.vias):
        low, high = sorted((via.start_layer, via.end_layer))
        metal_area = _via_area(via)
        for layer in range(low, high):
            ring1 = _via_contacts(board, vi, layer)
            ring2 = _via_contacts(board, vi, layer + 1)
            # A barrel conducts heat through layers even without same-net foil.
            if not ring1 or not ring2:
                center = _via_cell(board, via)
                ring1 = ring1 or [center]
                ring2 = ring2 or [center]
            share = (settings.copper_k - k_z) * metal_area / (z[layer + 1] - z[layer]) / (len(ring1) * len(ring2))
            a = np.asarray([index[layer, r, c] for r, c in ring1])
            b = np.asarray([index[layer + 1, r, c] for r, c in ring2])
            left.append(np.repeat(a, len(b))); right.append(np.tile(b, len(a)))
            conductance.append(np.full(len(a) * len(b), share))
            blocks.append((a, b, share))
    left, right, conductance = np.concatenate(left), np.concatenate(right), np.concatenate(conductance)
    boundary = np.zeros(len(flat))
    for layer, h, depth in [(0, settings.convection_top, max(z[0], 0)),
                             (len(z) - 1, settings.convection_bottom, max(board_thickness_m - z[-1], 0))]:
        if h > 0:
            nodes = index[layer][board.board_mask]
            # Surface-center drop is normally negligible next to convection.
            k_surface = k_z + (settings.copper_k - k_z) * board.copper[layer][board.board_mask]
            boundary[nodes] += area / (1 / h + depth / k_surface)
    diagonal = boundary + np.bincount(left, weights=conductance, minlength=len(flat)) + np.bincount(right, weights=conductance, minlength=len(flat))
    # Every occupied XY cell exists on every thermal layer and has a strictly
    # positive substrate edge to the next layer. At least one whole outer surface has
    # positive convection (validated in analyze). Thus even separate outline
    # islands/cutouts each have a vertical path to a boundary. A second full
    # 3-D union-find here only repeated a guaranteed connectivity property.
    matvec = _BlockMultiply(diagonal, base_left, base_right, base_g, blocks)
    return flat, left, right, conductance, diagonal, boundary, matvec


def analyze(board: RasterBoard, scenario: Scenario, progress: Callable | None = None, cancel=None) -> Result:
    """Solve coupled DC distribution and steady-state temperature, read-only.

    Loads specify the total amperes of each selected pad *group*. Thermal
    boundaries are top/bottom convection; edge convection, radiation, packages,
    AC skin/proximity effects and PWM switching physics are not modeled.
    """
    from copy import copy
    settings = copy(scenario.settings)
    _check_cancel(cancel)
    mask = np.asarray(board.board_mask)
    if mask.dtype != bool or mask.ndim != 2 or not mask.any():
        raise AnalysisError('Board mask must be a nonempty two-dimensional boolean array.')
    shape = (len(board.layers), *mask.shape)
    if not board.layers or board.copper.shape != shape:
        raise AnalysisError('Copper array and physical layers have incompatible shapes.')
    _positive(board.cell_mm, 'Mesh cell size')
    k_xy, k_z = substrate_conductivities(settings, require_thermal=False)
    for name in ['rho20', 'copper_k', 'tolerance_c', 'solver_tolerance', 'via_plating_um', 'max_delta_v']:
        _positive(getattr(settings, name), name)
    if board.vias and k_z > settings.copper_k and settings.substrate_material != 'metal_core':
        raise AnalysisError('This via model requires through-plane substrate conductivity no greater than copper conductivity.',
                            code='unsupported_via_substrate_conductivity')
    for name in ['alpha', 'convection_top', 'convection_bottom']:
        _positive(getattr(settings, name), name, allow_zero=True)
    if settings.convection_top + settings.convection_bottom <= 0:
        raise AnalysisError('At least one convection coefficient must be positive for a steady-state thermal solution.')
    if not np.isfinite(settings.ambient_c) or 1 + settings.alpha * (settings.ambient_c - 20) <= 0:
        raise AnalysisError('Ambient temperature makes the copper resistivity invalid.')
    if not np.isfinite(settings.max_temperature_c):
        raise AnalysisError('Temperature warning limit must be finite.')
    if not isinstance(settings.max_iterations, (int, np.integer)) or settings.max_iterations < 1:
        raise AnalysisError('Thermal max_iterations must be a positive integer.')
    for net, coverage in [(None, board.copper), *board.net_copper.items()]:
        a = np.asarray(coverage)
        if a.shape != shape or not np.all(np.isfinite(a)) or np.any((a < 0) | (a > 1)):
            raise AnalysisError(f'Invalid copper coverage for {net or "all layers"}.')
    z = np.asarray([layer.z_mm for layer in board.layers], dtype=float) * 1e-3
    copper_t = np.asarray([layer.thickness_mm for layer in board.layers]) * 1e-3
    if not np.all(np.isfinite(z)) or not np.all(np.isfinite(copper_t)) or np.any(np.diff(z) <= 0) or np.any(copper_t <= 0):
        raise AnalysisError('Physical layer centers must increase and copper thicknesses must be positive.')
    thickness = float(board.metadata.get('board_thickness_mm', max(1.6, (z[-1] + copper_t[-1] / 2) * 1000))) * 1e-3
    if z[0] < 0 or z[-1] > thickness or thickness <= 0:
        raise AnalysisError('Copper layer positions lie outside the physical board thickness.')
    for vi, via in enumerate(board.vias):
        if not (0 <= via.start_layer < len(z) and 0 <= via.end_layer < len(z)):
            raise AnalysisError('Via has a nonexistent start or end layer.')
        _via_area(via)
        # Annulus-contact meshes legitimately have no metal at the hole center.
        for layer in range(min(via.start_layer, via.end_layer), max(via.start_layer, via.end_layer) + 1):
            _via_contacts(board, vi, layer)
    settings._cell_m = board.cell_mm * 1e-3
    for source in scenario.sources:
        _pad_nodes(board, source.pad_ids)
        if not np.isfinite(source.voltage_v):
            raise AnalysisError('Source voltage must be finite.')
    for load in scenario.loads:
        _pad_nodes(board, load.pad_ids)
        if not np.isfinite(load.current_a):
            raise AnalysisError('Load current must be finite (positive draws, negative injects into a return net).')
    if scenario.loads and not scenario.sources:
        raise AnalysisError('Current loads require at least one source.')
    if not scenario.sources and not scenario.heaters:
        raise AnalysisError('Select a source/load circuit or a component heater before analysis.')
    active_nets = set()
    for terminal in [*scenario.sources, *scenario.loads]:
        nets = {board.pads[identifier].net for identifier in terminal.pad_ids}
        if len(nets) != 1 or '' in nets:
            raise AnalysisError('Each electrical terminal group must contain pads of one named net.')
        net = next(iter(nets))
        if net not in board.net_copper:
            raise AnalysisError(f'Net {net!r} is absent from the copper mesh.')
        active_nets.add(net)
    _progress(progress, 'Building physical conduction graph', 0.03)
    graphs = [_make_electrical(board, scenario, net, z, cancel) for net in sorted(active_nets)]
    if settings.substrate_material == 'metal_core':
        diagnostic = None
        if graphs:
            reference = np.full(shape, np.nan)
            reference[:, mask] = settings.ambient_c
            maps = _solve_electrical_maps(graphs, shape, reference, settings, cancel, progress)
            diagnostic = _reference_dc_result(settings, *maps)
        try:
            # Preserve the single authoritative construction explanation and
            # explicit unsupported status; no thermal matrix is constructed.
            substrate_conductivities(settings)
        except AnalysisError as exc:
            raise AnalysisError(str(exc), code=exc.code, details=exc.details, diagnostic=diagnostic) from exc
    thermal = _thermal_system(board, settings, z, thickness)
    tflat, tl, tr, tg, td, boundary, thermal_matvec = thermal
    _progress(progress, 'Preparing multilevel conduction solver', 0.07)
    thermal_preconditioner = _preconditioner(td, tl, tr, tg, tflat, shape, cancel, boundary, thermal_matvec)
    thermal_guesses = _RecycledGuesses(len(tflat))
    heater_w = np.zeros(shape)
    for heater in scenario.heaters:
        _positive(heater.power_w, 'Component heat', allow_zero=True)
        cells = _pad_nodes(board, heater.pad_ids)
        for cell in cells:
            heater_w[cell] += heater.power_w / len(cells)
    temperature = np.full(shape, np.nan)
    temperature[:, mask] = settings.ambient_c
    iteration_history = []
    first_dc = None

    def thermal_failure_details(iteration, candidate, *, max_change_c=None):
        """Diagnose rejected candidates without presenting a valid temperature map.

        Positive and negative load totals are separate: a return-net injection
        must not cancel or double the forward-current amount in the UI. Values
        remain the user's explicit group totals; no load is normalized here.
        """
        net_loads = []
        for net in sorted(active_nets):
            values = [float(load.current_a) for load in scenario.loads
                      if board.pads[load.pad_ids[0]].net == net]
            net_loads.append(dict(net=net, draw_a=sum(max(value, 0.) for value in values),
                                  injection_a=sum(max(-value, 0.) for value in values),
                                  signed_a=sum(values), group_count=len(values)))
        finite = candidate is not None and bool(np.all(np.isfinite(candidate)))
        details = dict(iteration=int(iteration), model_limit_c=1500.,
                       total_draw_a=sum(item['draw_a'] for item in net_loads),
                       total_injection_a=sum(item['injection_a'] for item in net_loads),
                       net_loads=net_loads,
                       computed_peak_c=float(np.max(candidate)) if finite else None,
                       previous_peak_c=previous_peak_c,
                       previous_iteration=int(iteration - 1),
                       mesh_cell_mm=float(board.cell_mm),
                       reference_joule_w=(first_dc['summaries']['joule_w'] if first_dc else None),
                       exposed_board_area_mm2=float(mask.sum() * board.cell_mm ** 2),
                       cooling_conductance_w_k=float(boundary.sum()),
                       convection_top=float(settings.convection_top),
                       convection_bottom=float(settings.convection_bottom))
        if max_change_c is not None and np.isfinite(max_change_c):
            details['max_change_c'] = float(max_change_c)
        if finite:
            hot = np.unravel_index(int(tflat[np.argmax(candidate)]), shape)
            details['hotspot'] = dict(layer=board.layers[hot[0]].name,
                                      layer_index=int(hot[0]), row=int(hot[1]), column=int(hot[2]),
                                      x_mm=float(board.origin_x_mm + (hot[2] + .5) * board.cell_mm),
                                      y_mm=float(board.origin_y_mm + (hot[1] + .5) * board.cell_mm))
        return details

    for iteration in range(1, settings.max_iterations + 1):
        _check_cancel(cancel)
        previous_peak_c = float(np.max(temperature.ravel()[tflat]))
        _progress(progress, f'Solving DC and temperature: iteration {iteration}', 0.08 + 0.85 * iteration / settings.max_iterations)
        voltages, densities, summaries, joule, via_segments = _solve_electrical_maps(
            graphs, shape, temperature, settings, cancel, progress, .08 + .85 * iteration / settings.max_iterations)
        if iteration == 1 and graphs:
            # These maps use the initial, uniform reference temperature. Later
            # feedback iterations allocate fresh arrays and cannot overwrite
            # this independently valid electrical result. No temperature map
            # is retained as a diagnostic when the thermal solve is rejected.
            first_dc = _reference_dc_result(settings, voltages, densities, summaries, joule, via_segments)
        power = (joule + heater_w).ravel()[tflat]
        initial_rise = thermal_guesses.guess(power, temperature.ravel()[tflat] - settings.ambient_c)
        try:
            rise, thermal_iterations, residual = _pcg(td, tl, tr, tg, power, settings.solver_tolerance,
                                                       cancel, initial_rise,
                                                       thermal_preconditioner, thermal_matvec,
                                                       lambda step, residual: _progress(
                                                           progress, f'Thermal solve: {step} iterations, relative residual {residual:.2g}',
                                                           .08 + .85 * iteration / settings.max_iterations))
        except AnalysisError as exc:
            # Only a thermal iterative-convergence failure may expose a cold
            # DC diagnostic. Cancellation and electrical/connectivity errors
            # retain their original meaning and never become partial success.
            if str(exc).startswith('Conduction solver did not converge after '):
                raise AnalysisError(str(exc), code='electrothermal_nonconvergence',
                                    details=thermal_failure_details(iteration, None),
                                    diagnostic=first_dc) from exc
            raise
        next_t = settings.ambient_c + rise
        if not np.all(np.isfinite(next_t)):
            raise AnalysisError('The electrothermal calculation produced nonfinite temperatures; '
                                'no valid temperature result is available.',
                                code='electrothermal_nonfinite',
                                details=thermal_failure_details(iteration, next_t), diagnostic=first_dc)
        if np.max(next_t) > 1500:
            raise AnalysisError('Electrothermal model is unstable or outside physical validity; '
                                'no safe temperature result is available.',
                                code='electrothermal_outside_validity',
                                details=thermal_failure_details(iteration, next_t), diagnostic=first_dc)
        thermal_guesses.add(rise, thermal_matvec)
        delta = float(np.max(np.abs(next_t - temperature.ravel()[tflat])))
        temperature.ravel()[tflat] = next_t
        iteration_history.append({'iteration': iteration, 'max_change_c': delta, 'max_temperature_c': float(next_t.max()),
                                  'joule_w': float(joule.sum()), 'thermal_pcg_iterations': thermal_iterations,
                                  'thermal_relative_residual': residual})
        if delta <= settings.tolerance_c:
            break
    else:
        raise AnalysisError(f'Electrothermal feedback did not converge after {settings.max_iterations} iterations '
                            f'(last change {delta:.3g} C). Possible thermal runaway or insufficient iteration limit; no converged result.',
                            code='electrothermal_nonconvergence',
                            details=thermal_failure_details(iteration, next_t, max_change_c=delta), diagnostic=first_dc)
    convection_w = float(np.dot(boundary, temperature.ravel()[tflat] - settings.ambient_c))
    total_w = float(joule.sum() + heater_w.sum())
    via_current = []
    segments_by_via = {}
    for record in via_segments:
        segments_by_via.setdefault(record['via_index'], []).append(record)
    for vi, via in enumerate(board.vias):
        records = segments_by_via.get(vi, [])
        via_current.append({'via_index': vi, 'identifier': via.identifier, 'net': via.net,
                            'x_mm': via.x_mm, 'y_mm': via.y_mm, 'start_layer': via.start_layer,
                            'end_layer': via.end_layer, 'max_current_a': max((abs(r['current_a']) for r in records), default=0.0),
                            'max_current_density_a_mm2': max((abs(r['current_a']) for r in records), default=0.0) / (_via_area(via) * 1e6),
                            'loss_w': sum(r['loss_w'] for r in records), 'segments': records})
    flat_hot = int(tflat[np.argmax(temperature.ravel()[tflat])])
    hot = np.unravel_index(flat_hot, shape)
    warnings = list(board.warnings)
    if temperature[hot] > settings.max_temperature_c:
        warnings.append(f'Peak temperature exceeds the configured {settings.max_temperature_c:g} C limit.')
    if any(s['max_delta_v'] > settings.max_delta_v for s in summaries.values()):
        warnings.append(f'Voltage variation exceeds the configured {settings.max_delta_v:g} V limit.')
    if any(g.floating_nodes for g in graphs):
        warnings.append('Unpowered disconnected copper islands are excluded from the electrical solve; their thermal mass/conduction remains included.')
    diagnostics = {'converged': True, 'iterations': iteration_history, 'warnings': warnings,
                   'thermal_energy_error_w': convection_w - total_w,
                   'mesh_cell_mm': board.cell_mm, 'thermal_cells': len(tflat),
                   'exact_electrical_faces': all(g.net in board.metadata.get('net_edges', {}) for g in graphs),
                   'preconditioner': 'multilevel' if thermal_preconditioner is not None else 'jacobi',
                   'thermal_recycled_vectors': len(thermal_guesses.basis),
                   'substrate': {'material': settings.substrate_material, 'k_xy_w_mk': k_xy,
                                 'k_z_w_mk': k_z, 'construction': 'homogeneous_insulating_substrate'},
                   'approximations': ['Steady DC, constant-current pad groups; loads return through an implicit ideal external circuit.',
                                      '2.5-D finite-volume copper/insulating-substrate heat conduction; uniform top and bottom convection.',
                                      'One homogeneous substrate with constant in-plane and through-plane conductivities; separate metal cores are not modeled.',
                                      'No radiation, sidewall convection, component package thermal network, transient PWM or AC skin/proximity effects.',
                                      'Each cell has one potential per net; mesh refinement and physical validation are required.',
                                      'Via plating is independent of the copper layer foil thickness; annulus contacts use distributed barrel conductance.',
                                      'Constant-current load groups distribute their total amperes over resolved pad cells; component internal current spreading is not modeled.']}
    result_summary = {'nets': summaries, 'joule_w': float(joule.sum()), 'component_heat_w': float(heater_w.sum()),
                      'total_heat_w': total_w, 'convection_w': convection_w,
                      'max_temperature_c': float(temperature[hot]), 'ambient_c': settings.ambient_c,
                      'max_rise_c': float(temperature[hot] - settings.ambient_c),
                      'hotspot': {'layer': board.layers[hot[0]].name, 'layer_index': int(hot[0]),
                                  'row': int(hot[1]), 'column': int(hot[2]),
                                  'x_mm': board.origin_x_mm + (hot[2] + 0.5) * board.cell_mm,
                                  'y_mm': board.origin_y_mm + (hot[1] + 0.5) * board.cell_mm},
                      'mesh_cell_mm': board.cell_mm}
    _progress(progress, 'Analysis complete', 1.0)
    return Result(temperature, voltages, densities, joule, via_current, result_summary, diagnostics)
