"""Render the plugin window to a PNG for documentation and visual review.

Run it with an X11 display (``GDK_BACKEND=x11`` under Wayland) because it blits
the window rectangle from the screen.  It never writes a PCB and never starts a
solve unless ``--synthetic-result`` is given; that option fabricates small
arrays so the Results section can be photographed without a board file.

    GDK_BACKEND=x11 python tools/capture_ui.py --board path/to.kicad_pcb \
        --out docs/screenshots/ui.png --section results
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import time

os.environ.setdefault('PCB_HEATMAP_HEADLESS', '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

import numpy as np  # noqa: E402
import wx  # noqa: E402

from pcb_heatmap.visual_gui import VisualFrame  # noqa: E402


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        wx.Yield()
        time.sleep(0.02)


def pump_until(predicate, timeout=180.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        wx.Yield()
        time.sleep(0.05)
        if predicate():
            return True
    return False


def _near(pixel, target, tolerance=3):
    return all(abs(pixel[index] - target[index]) <= tolerance for index in range(3))


def _window_origin(image, rail_rgb=(31, 35, 38)):
    """Locate the tool rail strip, whose left edge is the window's left edge."""
    width, height = image.size
    pixels = image.load()
    step = max(1, width // 900)
    for x in range(0, width - 60, step):
        for y in range(0, max(1, height - 400), 4):
            column = all(_near(pixels[x + 4, y + offset], rail_rgb) for offset in (0, 40, 120, 240))
            if column:
                top = y
                while top > 0 and _near(pixels[x + 4, top - 1], rail_rgb):
                    top -= 1
                return x, top
    return None


def capture(frame, path):
    """Photograph the window through KWin, cropping the compositor margins.

    ``wx.ScreenDC`` cannot read a Wayland surface (and an X11 client's pixels
    are not in the XWayland root), so the desktop's own screenshot tool is used
    when it is available.  A pure X11 session still falls back to a screen blit.
    """
    print('capture: begin', flush=True)
    pump(0.6)
    frame.Update()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = path.with_name(path.stem + '.raw' + path.suffix)
    config = Path('.capture-config').resolve()
    config.mkdir(parents=True, exist_ok=True)
    # Maximising is honoured by the compositor without needing activation, so
    # the whole screen belongs to this window and no coordinates are needed.
    frame.Maximize(True)
    pump(1.6)
    display = wx.Display(0).GetGeometry()
    try:
        subprocess.run(['spectacle', '-b', '-n', '-f', '-o', str(raw)],
                       capture_output=True, timeout=60, check=False,
                       env=dict(os.environ, XDG_CONFIG_HOME=str(config),
                                KDEHOME=str(config)))
    except (OSError, subprocess.SubprocessError):
        raw = None
    frame.Maximize(False)
    if raw is not None and raw.exists() and raw.stat().st_size:
        try:
            from PIL import Image
            image = Image.open(raw).convert('RGB')
            ratio = image.width / float(max(1, display.width))
            size = frame.GetSize()
            origin = _window_origin(image)
            if origin is not None:
                left, rail_top = origin
                top = max(0, rail_top - int(self_top := 50 * ratio))
                box = (left, top, min(image.width, left + int(size.width * ratio)),
                       min(image.height, top + int(size.height * ratio)))
                image.crop(box).save(path)
            else:
                image.crop((0, 0, min(image.width, int(display.width * ratio)),
                            min(image.height, int(display.height * ratio)))).save(path)
            raw.unlink(missing_ok=True)
            return path
        except Exception as exc:
            print('capture: crop failed', exc, flush=True)
    position, size = frame.GetScreenPosition(), frame.GetSize()
    display = wx.Display(0).GetGeometry()
    try:
        subprocess.run(['spectacle', '-b', '-n', '-f', '-o', str(raw)],
                       capture_output=True, timeout=60, check=False,
                       env=dict(os.environ, XDG_CONFIG_HOME=str(config),
                                KDEHOME=str(config)))
    except (OSError, subprocess.SubprocessError):
        raw = None
    if raw is not None and raw.exists() and raw.stat().st_size:
        try:
            from PIL import Image
            image = Image.open(raw).convert('RGB')
            scale_x = image.width / float(max(1, display.width))
            scale_y = image.height / float(max(1, display.height))
            box = (int(position.x * scale_x), int(position.y * scale_y),
                   int((position.x + size.width) * scale_x),
                   int((position.y + size.height) * scale_y))
            image.crop(box).save(path)
            raw.unlink(missing_ok=True)
            return path
        except Exception as exc:
            print('capture: crop failed', exc, flush=True)
    position, size = frame.GetScreenPosition(), frame.GetSize()
    screen = wx.ScreenDC()
    bitmap = wx.Bitmap(max(1, size.width), max(1, size.height))
    memory = wx.MemoryDC(bitmap)
    memory.Blit(0, 0, size.width, size.height, screen, position.x, position.y)
    memory.SelectObject(wx.NullBitmap)
    bitmap.SaveFile(str(path), wx.BITMAP_TYPE_PNG)
    return path


def synthetic_result(frame):
    """Populate the viewer with clearly synthetic arrays for a layout photo."""
    shape = (len(frame.inspection.get('layers') or [1]), 40, 60)
    temperature = np.full(shape, 28.0)
    temperature[:, 12:28, 18:42] += 26.0
    temperature[0, 20, 30] = 61.3
    voltage = np.full(shape, 5.0)
    voltage[:, 10:30, 20:44] = 4.93
    density = np.zeros(shape)
    density[:, 10:30, 20:44] = 18.5
    joule = np.zeros(shape)
    joule[:, 10:30, 20:44] = 0.02
    directory = Path(tempfile.mkdtemp(prefix='pcb-heatmap-capture-'))
    np.savez_compressed(directory / 'result.npz', temperature_c=temperature,
                        voltage_v__0=voltage, current_density_a_mm2__0=density,
                        joule_w=joule, board_mask=np.ones(shape[1:], bool),
                        copper=np.ones(shape))
    summary = dict(max_temperature_c=61.3, max_rise_c=36.3,
                   hotspot=dict(layer='F.Cu', x_mm=17.5, y_mm=11.25),
                   total_heat_w=2.04, joule_w=1.74, component_heat_w=0.3,
                   nets={'VBUS': dict(load_current_a=3.0, joule_w=1.74, max_delta_v=0.07,
                                      copper_area_mm2=184.6, via_count=214,
                                      max_via_density_a_mm2=12.4,
                                      terminal_groups=[dict(total_a=3.0, distribution='per_pad',
                                                            pads=[dict(label='J1.1', current_a=1.0, cells=3),
                                                                  dict(label='J1.2', current_a=1.0, cells=3),
                                                                  dict(label='J1.3', current_a=1.0, cells=3)])])})
    metadata = dict(arrays_file='result.npz', nets=['VBUS'],
                    sha256=frame.inspection.get('sha256', ''),
                    layers=frame.inspection.get('layers', [dict(name='F.Cu')]),
                    source_voltages_v={'VBUS': 5.0}, origin_x_mm=0, origin_y_mm=0,
                    cell_mm=0.25, summaries=summary,
                    diagnostics=dict(thermal_cells=184320, preconditioner='multilevel',
                                     iterations=[dict(iteration=1)], thermal_energy_error_w=1e-6,
                                     warnings=['Peak temperature approaches the configured limit.']),
                    timings_s=dict(geometry=1.9, solver=3.4, output=0.2),
                    compute=dict(cpu_count=24, threads=8, python='3.14.10', numpy='2.4.6'),
                    warnings=[])
    (directory / 'result.json').write_text(json.dumps(metadata), encoding='utf-8')
    frame.load_result(directory / 'result.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', default='')
    parser.add_argument('--out', default='docs/screenshots/ui.png')
    parser.add_argument('--section', default='inputs',
                        choices=('board', 'inputs', 'model', 'results', 'report'))
    parser.add_argument('--language', default='en', choices=('en', 'tr'))
    parser.add_argument('--appearance', default='auto', choices=('auto', 'dark', 'light'))
    parser.add_argument('--width', type=int, default=1480)
    parser.add_argument('--height', type=int, default=920)
    parser.add_argument('--synthetic-result', action='store_true')
    parser.add_argument('--wait', type=float, default=25.0)
    args = parser.parse_args()

    app = wx.App(False)
    print('creating frame', flush=True)
    frame = VisualFrame(board_path=args.board or None, pcb_context=False,
                        preferences_path=str(Path(tempfile.mkdtemp()) / 'prefs.json'))
    frame.ui_state.update(appearance=args.appearance, width=args.width, height=args.height)
    frame.apply_theme()
    frame.SetSize((args.width, args.height))
    frame.Show()
    print('frame shown', flush=True)
    if args.language == 'tr':
        frame.language_choice.SetSelection(1)
        frame.change_language()
    if args.board:
        print('waiting for the board layout', flush=True)
        pump_until(lambda: frame.inspection is not None, args.wait)
        print('layout wait finished; inspection', frame.inspection is not None, flush=True)
        pump(0.5)
    if frame.IsBeingDeleted():
        print('FAILED: the window was closed before capture', flush=True)
        os._exit(2)
    if args.synthetic_result and frame.inspection:
        synthetic_result(frame)
        pump(0.5)
    frame.show_section(args.section)
    pump(0.6)
    print('capture: ready', flush=True)
    path = capture(frame, args.out)
    print(f'CAPTURED {path} ({path.stat().st_size} bytes)', flush=True)
    # A GTK teardown can block on a compositor that never answers; the PNG is
    # already on disk, so leave without waiting for the event loop to unwind.
    os._exit(0)


if __name__ == '__main__':
    main()
