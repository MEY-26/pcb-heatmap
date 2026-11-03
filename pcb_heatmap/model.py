"""Public data contract for the local, read-only PCB Heatmap prototype.

Geometry is millimetres. Conductivity/resistivity are SI. Copper arrays have
shape (copper_layer, row, column); coverage values lie in [0, 1].
No module in this package downloads or runs third-party plugin code.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable
import numpy as np

VERSION = '0.3.4'


def conflicting_terminal_ids(rows):
    """Source and load contacts must be physically distinct; heat may overlap.

    This cheap UUID check runs before rasterisation. The solver separately
    rejects different contacts that overlap on an under-resolved mesh.
    """
    source = {identifier for row in rows if row['kind'] == 'source' for identifier in row['pad_ids']}
    load = {identifier for row in rows if row['kind'] == 'load' for identifier in row['pad_ids']}
    return source & load


class AnalysisError(ValueError):
    """An input, discretization, connectivity or convergence error."""

    def __init__(self, message, *, code=None, details=None, diagnostic=None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})
        self.diagnostic = diagnostic


def duplicate_terminal_groups(rows):
    """Find repeated explicit pad sets without modifying the user's scenario."""
    first, duplicates = {}, []
    for index, row in enumerate(rows):
        key = (row['kind'], frozenset(row['pad_ids']))
        if key in first:
            duplicates.append(dict(first_index=first[key], duplicate_index=index,
                                   kind=row['kind'], pad_ids=list(row['pad_ids'])))
        else:
            first[key] = index
    return duplicates


def load_totals(rows, pad_metadata):
    """Per-net group totals. Pad count never multiplies a group's amperes."""
    totals = {}
    for row in rows:
        if row['kind'] != 'load':
            continue
        net = pad_metadata[row['pad_ids'][0]].get('net', '')
        total = totals.setdefault(net, dict(net=net, draw_a=0., injection_a=0., signed_a=0., group_count=0))
        current = float(row['value'])
        total['draw_a'] += max(current, 0.)
        total['injection_a'] += max(-current, 0.)
        total['signed_a'] += current
        total['group_count'] += 1
    return list(totals.values())


@dataclass
class Layer:
    name: str
    thickness_mm: float
    z_mm: float


@dataclass
class Via:
    x_mm: float
    y_mm: float
    drill_mm: float
    diameter_mm: float
    start_layer: int
    end_layer: int
    net: str
    plating_um: float = 25.0
    identifier: str = ''


@dataclass
class Pad:
    identifier: str
    label: str
    net: str
    x_mm: float
    y_mm: float
    layers: tuple[int, ...]


@dataclass
class RasterBoard:
    origin_x_mm: float
    origin_y_mm: float
    cell_mm: float
    board_mask: np.ndarray
    copper: np.ndarray
    net_copper: dict[str, np.ndarray]
    layers: list[Layer]
    vias: list[Via]
    pads: dict[str, Pad]
    pad_cells: dict[str, list[tuple[int, int, int]]]
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Source:
    pad_ids: list[str]
    voltage_v: float


@dataclass
class Load:
    pad_ids: list[str]
    current_a: float


@dataclass
class ComponentHeat:
    pad_ids: list[str]
    power_w: float


@dataclass
class AnalysisSettings:
    ambient_c: float = 25.0
    convection_top: float = 10.0
    convection_bottom: float = 10.0
    # Historical JSON key retained for existing scenarios. This is now the
    # generic electrically insulating substrate's in-plane conductivity.
    fr4_k: float = 0.30
    copper_k: float = 400.0
    rho20: float = 1.724e-8
    alpha: float = 0.00393
    via_plating_um: float = 25.0
    max_temperature_c: float = 100.0
    max_delta_v: float = 0.50
    max_iterations: int = 20
    tolerance_c: float = 0.05
    solver_tolerance: float = 1e-8
    substrate_k_z: float | None = None
    substrate_material: str = 'custom'


@dataclass
class Scenario:
    sources: list[Source]
    loads: list[Load]
    heaters: list[ComponentHeat] = field(default_factory=list)
    settings: AnalysisSettings = field(default_factory=AnalysisSettings)


@dataclass
class Result:
    temperature_c: np.ndarray
    voltage_v: dict[str, np.ndarray]
    current_density_a_mm2: dict[str, np.ndarray]
    joule_w: np.ndarray
    via_current_a: list[dict[str, Any]]
    summaries: dict[str, Any]
    diagnostics: dict[str, Any]


Progress = Callable[[str, float], None]
