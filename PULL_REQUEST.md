# PCB Heatmap 0.4.0 — Linux support, themed UI rebuild, explicit terminal groups, faster repeat runs

> **Vibecoded by `deepseek-v4.1-flash:1017`** (DeepSeek Harness).
> Tested on **Fedora Linux 44** (KDE Plasma, Wayland) with **KiCad 10.0.8**.

Fork of [MEY-26/pcb-heatmap](https://github.com/MEY-26/pcb-heatmap) at `v0.3.4`.

## Summary

This branch makes the plugin a first-class Linux and Windows KiCad 10 plugin,
rebuilds the window so it follows the host KiCad PCB theme and the desktop accent
colour, makes grouped terminals explicit (one total, a visible per-pad split),
and removes most of the wait from repeated analyses of the same board.

The numerical model is unchanged. All solver changes are additive: extra
diagnostics, an optional copper-thickness override, and a warm start.

## Why

- `0.3.4` declared `platforms: ["windows"]`, wrote run folders through
  `%LOCALAPPDATA%`, and its window forced a light navy palette inside a dark
  KiCad session.
- Grouped terminals already worked, but the split rule was invisible (equal per
  copper cell), and the multi-pad flow was buried in a paragraph of hints.
- Vias, copper area, timings and CPU information were computed or available but
  never shown; the results text did not scroll with the pane.
- Interactive pan/zoom rebuilt ~2.4k paths and re-stroked them on every mouse
  event (~350 ms per frame, 3 fps).

## What changed

### Linux

- `metadata.json`: `platforms: ["windows", "linux"]`; install and runtime text
  describes distribution-provided or bundled KiCad Python.
- New `paths.py`: XDG config/state paths with Windows `%APPDATA%` /
  `%LOCALAPPDATA%` precedence, and writable fallbacks for the run folder
  (state directory → KiCad config → private temporary folder).
- `worker_python()` now accepts any interpreter that can import `pcbnew` and
  `numpy` (probe cached), instead of a hard-coded name whitelist.
- PCM gate accepts any non-empty subset of `{windows, linux}`; package tests and
  README/README.tr install instructions cover native and Flatpak KiCad.
- New Linux GUI job in CI (`python3-wxgtk4.0`, `xvfb`, `GSETTINGS_BACKEND=memory`).

### Interface

- One top bar, one action bar and a Board / Inputs / Model / Results / Report
  tool rail replace six stacked control bands.
- New `theme.py` reads the active KiCad PCB theme (`appearance.color_theme`,
  plus `colors/user.json` overrides) and the KDE accent colour, composes a
  dark/light palette, and repaints live. No KiCad window is restyled and no
  global appearance setting is touched.
- New `widgets.py` and `icons.py`: painted buttons, segmented controls, pills,
  tool rail, legend, message bar and code-drawn glyphs.
- Assignment: right-click a pad for *Set as source / load / heat*, an adaptive
  selection card (nothing / one pad / a group), Ctrl+click and Shift+drag
  marquee, pad role tinting, and a marker visibility toggle (pin, `M`, Layers).
- List: Delete/Backspace removes rows (confirming for four or more), inline
  value editing, Ctrl+Z / Ctrl+Shift+Z undo/redo.
- Results: rich summary plus a scrolling detail pane that wraps to the pane
  width, and a session run history.
- The Layers dialog is widened and no longer elides its labels.

### Terminals and model

- Explicit split rule per load group: *Equal per pad* (new default) or *By
  copper area* (the 0.3.4 rule). The assignment dialog previews the division and
  `Split…` changes the rule later.
- Per-layer copper foil thickness in µm, defaulting to the board stackup and
  saved with the scenario/case.
- Speed / precision presets (Fast 0.5 mm / Balanced 0.35 mm / Fine 0.25 mm) set
  mesh size and solver tolerance together; every model control has a tooltip.
- Results now state what was analysed: per-net draw and copper loss, copper
  area, via count and worst via current density, mesh cells, iterations,
  preconditioner, geometry/solver/output seconds and CPU cores.

### Performance

- Polygon sampling moved to `geometry.py` and vectorised with NumPy.
- Only the `(stackup)` subtree is parsed instead of the whole board file.
- Rasterised boards are cached (JSON + compressed NumPy), keyed by board hash,
  cell size, cell budget, plating and analysed nets, with size/age pruning.
- A persistent `worker.py serve` keeps the meshed board, thermal multilevel
  preconditioner and previous temperature/voltage as warm starts between runs.
- Pan/zoom uses a whole-board preview bitmap with a visible-source-rectangle
  blit during the gesture, then a sharp vector frame 140 ms after it stops.

Measured on a six-layer board with one analysed net (0.25 mm cells):

| Metric | Before | After |
| --- | --- | --- |
| First analysis in a session | ~17 s | ~17 s (unchanged) |
| Re-run after changing a load value | ~17 s | **~2.6 s** |
| Geometry phase on a cached re-run | 6.8 s | **0.4 s** |
| Gesture frame with a map shown | ~350 ms | **2–5 ms** |

Solver-only multithreading was evaluated and not added: threaded NumPy scaled
1.4× at 16 threads on this hardware, and the matvec is gather + `bincount`.

## Screenshots

- [Temperature analysis in the KiCad `wDark` theme](docs/screenshots/ui-temperature.png)
- [Temperature map with markers hidden](docs/screenshots/board-temperature.png)
- [Current density zoomed around the 54 V / 90 A terminals](docs/screenshots/current-density.png)
- [Model panel: presets, per-layer copper, solver precision](docs/screenshots/ui-dark-model.png)
- [Results: nets, copper area, vias, cells, timings and history](docs/screenshots/ui-dark-results.png)

## Compatibility

- Windows behaviour is preserved (no `fcntl`, `CREATE_NO_WINDOW`, `%APPDATA%`).
- Scenarios saved by 0.3.4 keep the old area-weighted split; absent
  `copper_um` means the physical stackup is used.
- Existing calculation settings load unchanged; `solver_tolerance` defaults to
  1e-8 when absent.
- Read-only guarantee unchanged: no network, no PCB writes, worker isolated, SHA
  checks on every read and solve.

## Test environment

Everything below was run on **Fedora Linux 44** (KDE Plasma, Wayland session,
AMD Ryzen 9 5950X, 32 logical CPUs) with **KiCad 10.0.8**, Python 3.14.10,
wxPython 4.2.4/GTK3 and NumPy 2.4.6. The native suite used the distribution's
`pcbnew`; the plugin was installed and exercised inside the Flatpak KiCad build.

## Testing

```
python ci/run_tests.py portable   # 140 tests
python ci/run_tests.py gui        # 50 tests (requires wxPython + display)
python ci/run_tests.py native     # 33 tests (requires pcbnew)
python ci/run_tests.py package    # 8 tests
python build_pcm.py               # deterministic PCM archive
python tools/canvas_smoke.py      # canvas/overlay smoke
```

231 tests pass locally. New coverage: theme/KDE/theme-JSON parsing, colormap
parity with 0.3.4, geometry parity against brute force, raster cache
round-trip/corruption/pruning, copper override physics, warm-start equivalence
and invalidation, terminal split conservation, adaptive card, Delete/undo/inline
edit, presets and the marker toggle.

## Known limitations

- Flatpak/AppImage KiCad works only when its bundled interpreter can import
  `pcbnew` and `numpy`; the Board page reports the interpreter it found.
- The 4× preview bitmap costs ~120 MB while a map is shown; lower
  `board_view.WORLD_BITMAP_LIMIT` to 4096 for ~54 MB.
- The warm worker is killed on Cancel (next run starts cold) and holds tens of
  MB while the window is open.
- Per-net parallel solving and a fully vector-based sharp-while-panning renderer
  are documented follow-ups, not included.
- macOS is untested.

## Checklist

- [x] Portable, GUI, native and package suites pass
- [x] Windows path preserved, Linux added to metadata and CI
- [x] No new runtime dependencies (`wx`, `numpy`, `pcbnew` only)
- [x] Read-only behaviour and worker isolation preserved
- [x] README, README.tr, release notes and PCM archive updated
- [x] Provenance and Fedora 44 test environment documented
