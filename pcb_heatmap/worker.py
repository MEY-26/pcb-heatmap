"""Isolated, read-only KiCad geometry and numerical worker. No network access.

Run with KiCad's bundled Python; stdout is a JSON-lines progress protocol.
Only explicitly selected output files are created; the input PCB is never saved.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict, fields
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback

os.environ['PCB_HEATMAP_HEADLESS'] = '1'
PACKAGE_DIR = Path(__file__).resolve().parent
# PCM gives the installed directory its package identifier. Relative source
# imports still need a stable package name when this file is a CLI entrypoint.
if 'pcb_heatmap' not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        'pcb_heatmap', PACKAGE_DIR / '__init__.py',
        submodule_search_locations=[str(PACKAGE_DIR)])
    _package = importlib.util.module_from_spec(_spec)
    sys.modules['pcb_heatmap'] = _package
    _spec.loader.exec_module(_package)


def clean(value):
    """Convert numpy scalars without accidentally serializing large arrays."""
    import numpy as np
    if isinstance(value, np.ndarray):
        if value.size > 1000:
            return {'shape': list(value.shape), 'stored_in_arrays': True}
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def emit(kind, **values):
    print(json.dumps(clean({'type': kind, **values}), ensure_ascii=False, allow_nan=False), flush=True)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    # Output paths are user-selectable in the CLI. Never allow a mistyped
    # output argument to replace a KiCad design, including through a symlink.
    if path.resolve().suffix.lower() in {'.kicad_pcb', '.kicad_sch', '.kicad_pro'}:
        raise ValueError('Analysis output cannot overwrite a KiCad design file.')
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + '.pending')
    # A leftover or redirected temporary path is not ours to overwrite.
    with pending.open('x', encoding='utf8') as stream:
        stream.write(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False))
    os.replace(pending, path)


def write_npz_exclusive(path, arrays):
    """Never follow or replace a pre-existing output path, including symlinks."""
    import numpy as np
    path = Path(path)
    if path.suffix.lower() != '.npz':
        raise ValueError('Numerical output must be an .npz file.')
    with path.open('xb') as stream:
        np.savez_compressed(stream, **arrays)


def read_scenario(path):
    from pcb_heatmap.model import AnalysisError, AnalysisSettings, ComponentHeat, Load, Scenario, Source
    data = json.loads(Path(path).read_text(encoding='utf8'))
    if not isinstance(data, dict):
        raise AnalysisError('Scenario must be a JSON object.')
    allowed = {f.name for f in fields(AnalysisSettings)}
    settings_data = data.get('settings', {})
    if not isinstance(settings_data, dict):
        raise AnalysisError('Analysis settings must be a JSON object.')
    if set(settings_data) - allowed:
        raise AnalysisError('Unknown analysis setting: ' + ', '.join(sorted(set(settings_data) - allowed)))

    def terminals(key, cls, value_name):
        items = data.get(key, [])
        if not isinstance(items, list) or len(items) > 512:
            raise AnalysisError('Invalid terminal list: ' + key)
        result = []
        for item in items:
            ids = item.get('pad_ids') if isinstance(item, dict) else None
            if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i for i in ids):
                raise AnalysisError('A terminal group needs explicit pad identifiers: ' + key)
            ids = list(dict.fromkeys(ids))
            val = float(item[value_name])
            if not math.isfinite(val):
                raise AnalysisError('Terminal values must be finite.')
            result.append(cls(pad_ids=ids, **{value_name: val}))
        return result

    scenario = Scenario(sources=terminals('sources', Source, 'voltage_v'),
                        loads=terminals('loads', Load, 'current_a'),
                        heaters=terminals('heaters', ComponentHeat, 'power_w'),
                        settings=AnalysisSettings(**settings_data))
    # Validate construction before the potentially expensive geometry read.
    from pcb_heatmap.materials import substrate_conductivities
    # Unsupported thermal constructions can still yield explicitly labeled,
    # independently valid reference-temperature DC maps.
    substrate_conductivities(scenario.settings, require_thermal=False)
    return scenario, data


def run(args):
    import numpy as np
    from pcb_heatmap.extractor import inspect_board, rasterize
    from pcb_heatmap.model import AnalysisError, VERSION

    board_path = Path(args.board).resolve(strict=True)
    if board_path.suffix.lower() != '.kicad_pcb':
        raise AnalysisError('Select a saved .kicad_pcb file.')
    initial_hash = sha(board_path)
    started = time.monotonic()
    if args.command in ('inspect', 'layout'):
        if args.command == 'layout':
            from pcb_heatmap.layout_export import export_layout
            info = export_layout(str(board_path), progress=lambda message, fraction:
                                 emit('progress', message=message, progress=fraction))
        else:
            info = inspect_board(str(board_path))
        if sha(board_path) != initial_hash:
            raise AnalysisError('The saved board changed while being read. Reload it.')
        info['board_path'] = str(board_path)
        info['sha256'] = initial_hash
        write_json(args.output, info)
        emit('result', path=str(Path(args.output).resolve()))
        return

    from pcb_heatmap.solver import analyze
    scenario, data = read_scenario(args.scenario)
    expected = data.get('expected_sha256')
    if expected and expected.lower() != initial_hash:
        raise AnalysisError('The saved board changed. Reload the board before analysis.')
    if not 0.025 <= args.cell_mm <= 5.0:
        raise AnalysisError('Cell size must be between 0.025 and 5.0 mm.')
    if not 100 <= args.max_cells <= 2_000_000:
        raise AnalysisError('The node budget must be between 100 and 2,000,000.')
    info = inspect_board(str(board_path))
    from pcb_heatmap.contacts import validate_contacts, attach_contacts
    contacts = validate_contacts(data.get('contacts', []), info)
    pads = info.get('pads', [])
    if isinstance(pads, list):
        pad_nets = {p['identifier']: p.get('net', '') for p in pads}
    else:
        pad_nets = {key: p.get('net', '') for key, p in pads.items()}
    pad_nets.update({identifier: contact['net'] for identifier, contact in contacts.items()})
    selected_nets = set()
    for terminal in scenario.sources + scenario.loads:
        nets = set()
        for identifier in terminal.pad_ids:
            if identifier not in pad_nets:
                raise AnalysisError('A selected pad is missing from the saved board. Save and reload.')
            if not pad_nets[identifier]:
                raise AnalysisError('Electrical terminals must have a PCB net.')
            nets.add(pad_nets[identifier])
        if len(nets) != 1:
            raise AnalysisError('Each source/load group must contain pads of exactly one net.')
        selected_nets.update(nets)
    out_dir = Path(args.output_dir).resolve()
    output_names = ('result.json', 'result.npz', 'dc-diagnostic.json', 'dc-diagnostic.npz')
    if out_dir.exists() and any((out_dir / name).exists() or (out_dir / name).is_symlink() for name in output_names):
        raise AnalysisError('This output folder already contains a result. Choose a new run folder.')
    out_dir.mkdir(parents=True, exist_ok=True)

    def geometry_progress(message, fraction):
        emit('progress', message=message, progress=max(0.0, min(0.45, float(fraction) * 0.45)))

    raster = rasterize(str(board_path), sorted(selected_nets), cell_mm=args.cell_mm,
                       via_plating_um=scenario.settings.via_plating_um,
                       max_cells=args.max_cells, progress=geometry_progress)
    attach_contacts(raster, contacts)
    if sha(board_path) != initial_hash:
        raise AnalysisError('The saved board changed during extraction. Reload and run again.')
    extracted_at = time.monotonic()

    def solver_progress(message, fraction):
        emit('progress', message=message, progress=0.45 + max(0.0, min(1.0, float(fraction))) * 0.54)

    source_voltages = {}
    for source in scenario.sources:
        net = raster.pads[source.pad_ids[0]].net
        source_voltages[net] = max(source_voltages.get(net, -float('inf')), source.voltage_v)
    def base_metadata(nets, arrays_file, solved_at):
        return dict(schema_version=1, application='PCB Heatmap', version=VERSION,
                    board_path=str(board_path), sha256=initial_hash, arrays_file=arrays_file,
                    original_board_path=data.get('original_board_path', str(board_path)),
                    snapshot=data.get('snapshot'),
                    timings_s=dict(geometry=round(extracted_at - started, 3),
                                   solver=round(solved_at - extracted_at, 3),
                                   output=round(time.monotonic() - solved_at, 3)),
                    elapsed_s=round(time.monotonic() - started, 3), nets=nets,
                    layers=[asdict(layer) for layer in raster.layers],
                    origin_x_mm=raster.origin_x_mm, origin_y_mm=raster.origin_y_mm,
                    cell_mm=raster.cell_mm, source_voltages=source_voltages,
                    scenario=asdict(scenario), warnings=raster.warnings,
                    limitations=[
                        'Steady DC and steady-state board temperature estimates; switching waveforms are not modeled.',
                        'Temperatures describe the board mesh, not semiconductor junction temperatures.',
                        'Uniform top/bottom convection; no automatic airflow, enclosure or radiation model.',
                        'One homogeneous electrically insulating substrate with separately specified in-plane and through-plane conductivity.',
                        'Separate dielectric and metal-base layers for metal-core PCBs are not modeled.',
                        'Terminal pad groups are ideal equipotential contacts or distributed current contacts.',
                        'Inspect geometry warnings and compare progressively finer meshes before trusting hotspots.',
                        'Other nets remain in the thermal model, even when hidden in the result view.'
                    ])

    try:
        result = analyze(raster, scenario, progress=solver_progress)
    except AnalysisError as exc:
        solved_at = time.monotonic()
        diagnostic = getattr(exc, 'diagnostic', None)
        if diagnostic is not None and exc.code in {
                'electrothermal_outside_validity', 'electrothermal_nonfinite',
                'electrothermal_nonconvergence', 'unsupported_metal_core'}:
            if sha(board_path) != initial_hash:
                raise AnalysisError('The saved board changed during the solve. Results were not accepted.') from exc
            nets = sorted(diagnostic['voltage_v'])
            arrays = dict(joule_w=diagnostic['joule_w'], board_mask=raster.board_mask, copper=raster.copper)
            for i, net in enumerate(nets):
                arrays[f'voltage_v__{i}'] = diagnostic['voltage_v'][net]
                arrays[f'current_density_a_mm2__{i}'] = diagnostic['current_density_a_mm2'][net]
            # An invalid thermal candidate must never reach a numerical file.
            write_npz_exclusive(out_dir / 'dc-diagnostic.npz', arrays)
            metadata = base_metadata(nets, 'dc-diagnostic.npz', solved_at)
            metadata.update(analysis_kind='dc_diagnostic', thermal_status='unavailable',
                            reference_temperature_c=diagnostic['reference_temperature_c'],
                            thermal_error=dict(code=exc.code, message=str(exc), details=exc.details),
                            summaries=diagnostic['summaries'], via_current_a=[],
                            via_segments=diagnostic['via_segments'],
                            diagnostics=dict(converged=False, electrical_converged=True,
                                reference_temperature_c=diagnostic['reference_temperature_c'],
                                approximations=['Copper resistivity is fixed at the initial uniform reference temperature.',
                                                'These DC maps do not include temperature feedback or a valid thermal result.']))
            write_json(out_dir / 'dc-diagnostic.json', metadata)
            emit('diagnostic_result', path=str(out_dir / 'dc-diagnostic.json'))
        # Exit remains a failure: exposing valid reference-temperature DC maps
        # must not imply that the rejected thermal solve succeeded.
        raise
    solved_at = time.monotonic()
    if sha(board_path) != initial_hash:
        raise AnalysisError('The saved board changed during the solve. Results were not accepted.')
    nets = sorted(result.voltage_v)
    arrays = {'temperature_c': result.temperature_c, 'joule_w': result.joule_w,
              'board_mask': raster.board_mask, 'copper': raster.copper}
    for i, net in enumerate(nets):
        arrays[f'voltage_v__{i}'] = result.voltage_v[net]
        arrays[f'current_density_a_mm2__{i}'] = result.current_density_a_mm2[net]
    # npz contains numerical arrays only and must always be read with allow_pickle=False.
    write_npz_exclusive(out_dir / 'result.npz', arrays)
    metadata = base_metadata(nets, 'result.npz', solved_at)
    metadata.update(analysis_kind='electrothermal', thermal_status='converged',
                    summaries=result.summaries, via_current_a=result.via_current_a,
                    diagnostics=result.diagnostics)
    write_json(out_dir / 'scenario.json', {**data, 'expected_sha256': initial_hash})
    write_json(out_dir / 'result.json', metadata)
    emit('progress', message='Analysis completed', progress=1.0)
    emit('result', path=str(out_dir / 'result.json'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    inspect = sub.add_parser('inspect')
    inspect.add_argument('--board', required=True)
    inspect.add_argument('--output', required=True)
    layout = sub.add_parser('layout')
    layout.add_argument('--board', required=True)
    layout.add_argument('--output', required=True)
    analyze = sub.add_parser('analyze')
    analyze.add_argument('--board', required=True)
    analyze.add_argument('--scenario', required=True)
    analyze.add_argument('--output-dir', required=True)
    analyze.add_argument('--cell-mm', type=float, default=0.25)
    analyze.add_argument('--max-cells', type=int, default=500000)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        emit('error', message=str(exc), code=getattr(exc, 'code', None), details=getattr(exc, 'details', {}))
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
    # KiCad SWIG wrappers may emit native object-ownership chatter on interpreter
    # shutdown. All output files are already closed; avoid that shutdown path.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == '__main__':
    main()
