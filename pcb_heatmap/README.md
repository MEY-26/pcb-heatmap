# PCB Heatmap 0.3.4

![PCB Heatmap logo](https://raw.githubusercontent.com/MEY-26/pcb-heatmap/main/docs/icon-preview.png)

Free, local KiCad 10 analysis for multilayer DC current distribution, voltage
drop, copper loss and estimated steady-state **board** temperature. Define
sources, loads and component heat by clicking the saved PCB view, then inspect
colored maps by layer and net. English and Turkish UI are included.

**0.3.4 is the first public release.** It is a Windows / KiCad 10.0 SWIG
ActionPlugin testing release.

This is an engineering prototype for comparison and hotspot investigation,
**not a certified ampacity calculator or a validated operating-current rating**.
It estimates board temperature, not semiconductor junction temperature. It does
not automatically calculate PWM/switching losses or model airflow CFD,
radiation, heatsinks or thermal-interface materials. Supply known component
losses and check assumptions, mesh refinement and independent measurements.

Analysis runs on the local computer. No account, subscription, external solver
or other KiCad analysis plugin is required, and board data is not uploaded.
NumPy and wxPython must already be available in KiCad's Python; the plugin never
installs packages automatically.

[Türkçe](README.tr.md) · [Releases](https://github.com/MEY-26/pcb-heatmap/releases) · [Issues](https://github.com/MEY-26/pcb-heatmap/issues)

## Installation

Download `PCB_Heatmap-0.3.4-pcm.zip` from the
[0.3.4 release page](https://github.com/MEY-26/pcb-heatmap/releases/tag/v0.3.4).
In the KiCad Project Manager, open **Plugin and Content Manager → Install from
File…** and select that ZIP. Default-catalogue acceptance is a separate process;
see [publication status](https://github.com/MEY-26/pcb-heatmap/blob/main/PUBLISHING.md). Do not assume the package is available
by searching the official catalogue until its metadata is accepted and refreshed.

Alternatively, copy this repository's `pcb_heatmap` folder into
`%APPDATA%/kicad/10.0/scripting/plugins/pcb_heatmap`, backing up an existing
installation outside the scanned plugin directory first. Use one installation
method at a time to avoid duplicate toolbar actions.

Reload Action Plugins, or reopen the PCB Editor, then choose **Tools →
External Plugins → PCB Heatmap**. After an update, close and relaunch the plugin
window. The toolbar has 24- and 48-pixel assets; the package also includes a
separate 64-pixel catalogue icon. This is the KiCad 10 local Python ActionPlugin
API, not an IPC plugin. The tested Windows KiCad 10 Python supplies NumPy and
wxPython. Linux/macOS runtime has not been verified and is not advertised by
the package metadata.

## Work directly on the board view

The main view displays the saved PCB's pads, tracks, vias, filled zones, and
component references. Choose a layer to inspect its copper. Filled zones are
read automatically; they are not missing because they cannot be selected as
pads. The board information includes the zone counts. Empty or stale fills
must be updated in KiCad with **B**, saved, and reloaded in the plugin.

Use these controls to define the analysis without writing pad names:

- **Source V:** choose the mode, click a pad or copper point on the board,
  then enter the source voltage.
- **Load A:** choose the mode, click another pad or copper point on the same
  net, then enter the total current drawn there.
- **Heat W:** optionally click a location and enter an actual component loss.
  A heat point can also be placed on the insulating substrate; it is not an electrical terminal.
- **Select:** Ctrl-click multiple pads, then choose an assignment mode to
  assign one value to that entire pad group. Groups are not expanded to the
  whole net automatically.

Source, load, and heat markers appear over the PCB. Click an existing marker
to edit its value. The sidebar also lists the assignments for editing or
removal, including **Remove all**. Save/load the scenario to reuse both pad
groups and coordinate-based point contacts.

The view is an analysis editor, not a PCB editor: these actions do not change
the source board, real pad geometry, net assignments, or the schematic.

## First analysis

**Choose different physical pads for the source and load.** The source is where
current enters a copper net; the load is where it leaves that same net. Adding
both to the same pad does not describe a path through the PCB and is rejected.

For a simple two-terminal example on a power-distribution net:

1. Press **B** in KiCad, save, then use **Reload saved PCB** in the plugin.
   Check the layer thicknesses and warnings; the file needs an explicit
   physical copper/dielectric stackup.
2. Choose **Source V**, click an input pad in the plugin's board view, and
   enter its actual voltage. **5 V** is an example, not a default.
3. Choose **Load A**, click a different physical pad near the receiving circuit
   on the same net, and enter its total current. **1 A** is an example, not a
   default. An output on another net needs its own source/load pair.
4. Leave **component heat** empty for this first copper-path analysis and run.
   The existing filled zones, tracks, pads, and via connections between the
   two terminals participate automatically.

If a source/load overlap is reported, remove the incorrect load row and add it
again using the other physical pad. If the pads are genuinely separate but
their mesh cells overlap, use a finer grid. Refining the grid cannot make the
same pad a valid source and load.

Clicking bare copper creates a **virtual analysis contact** at that coordinate
and layer. The contact occupies one resolved mesh cell, not a real physical
pad. Use actual pads when they represent the connection; refine the grid when
using point contacts, especially near narrow copper or another terminal. A
source and load cannot share the same pad or resolved contact cell.

## Navigation and results

Use the wheel to zoom around the pointer, the middle or right mouse button
to drag the board, and **Fit** to show the whole board again. Reference search
helps locate a component before assigning its pads.

After analysis, temperature (°C), current density (A/mm²), or voltage deviation
magnitude (mV) is drawn as a colored overlay aligned with the PCB. Layer and
net filters change the **view**, not the coupled calculation. All modeled
layers and neighboring copper remain in the thermal solve. The color scale
is shared across layers for a given result and display mode.

Set ambient temperature, top/bottom convection, via wall plating, grid
resolution, and node budget in the physical settings. Via wall plating is
independent of foil thickness; no arbitrary A-per-via limit is used. Repeat
with a finer grid: stable results and hotspot positions matter more than a
smooth-looking image. Unresolved contacts or disconnected paths produce an
error instead of a fabricated connection.

The plugin board view is the selection surface. Reload captures the saved file;
unsaved KiCad edits are not included.

## Substrate material and thermal conductivity

The thermal substrate is configurable: **FR4**, **ceramic**, or **custom
insulating substrate**. The category describes the construction; it does not
silently fill in a conductivity or replace the user's values. Enter the
actual manufacturer's thermal conductivity in **W/(m·K)**, separately for
**in-plane (XY)** and **through-plane (Z)** heat flow. Use the same number
only when an isotropic material approximation is appropriate. KiCad's
dielectric constant and loss tangent are electrical properties and do not
supply these thermal conductivities.

The model applies these two constant values to all non-copper substrate
volumes. Different dielectric materials at different depths, bonding layers,
and temperature-dependent material properties are not resolved. The physical
copper/dielectric thicknesses still come from the saved KiCad stackup. Older
scenarios containing only `fr4_k` preserve that exact value in both directions;
this historical storage key now means generic in-plane substrate conductivity.

**Aluminium / metal-core PCB** is shown as an unsupported construction. Its
thin electrical insulation and separate metal base must be modeled as
different physical layers. Substituting aluminium's bulk conductivity for the
whole substrate would produce a misleading heat path, so this construction
does not return a thermal result. Independently valid DC voltage, current
density and copper-loss maps can still be shown at the entered ambient
reference temperature; these do not include thermal feedback or component
heat. Aluminium nitride (**AlN**) is an insulating
ceramic and belongs to the ceramic category; it is different from an aluminium
metal-core PCB. For a via-containing board, the present barrel approximation
also requires Z conductivity no greater than the specified copper conductivity.

Manufacturer construction references: [CeramTec ceramic substrates](https://www.ceramtec-industrial.com/en/products-applications/substrates/aln-substrates)
and [TCLAD insulated metal substrates](https://tclad.com/products/insulated-metal-substrate/).
These references explain material families; they are not automatic presets.

## Meaning of the values

Every source/load group belongs to one net. Different nets need their own
terminals. Positive load current is drawn from the net; negative load current
is injected. For a GND return analysis, use a 0 V reference at the connector
and negative current at physically separate return pads.

**Component heat is optional.** Add it only for a known component loss that
should heat the board; no arbitrary heat entry is needed. Power delivered to a load
is not PCB heat. The solver calculates copper/via Joule losses automatically;
do not enter those losses again as a manual heater.

Source/load/heater values are assigned to entire selected pad groups, not
multiplied by their number of pads. Four separate 1 A load groups draw
**4 A total** from their common supply; one 1 A group spanning four load
locations draws **1 A total**, not 1 A per location. This version supports prescribed
DC current loads; it does not automatically model resistance/power loads,
regulators, contact resistance, switching waveforms, or switching components.

The voltage sets the electrical reference and affects the reported voltage
levels. For a prescribed current, trace heating is calculated from **I²R**;
source voltage × load current is power delivered to the load, not heat generated in the PCB.

## Calculation

- Copper faces form a resistive network on every active electrical net.
- Vias and conductive through-hole pads use the finished-hole diameter,
  separately specified wall plating and actual connected layer span.
- Source pads are ideal equipotential boundaries; load current is distributed
  over the resolved cells of the selected pads. This idealizes the external
  connector, package and contact geometry.
- Current is solved from that network; no equal current split between layers
  is assumed. Edge and barrel `I²R` losses are deposited on the thermal mesh.
- All physical board cells participate in thermal conduction, including the insulating substrate
  and unpowered copper. Copper planes on unrelated nets can therefore spread
  heat without becoming electrically connected.
- A steady-state finite-volume model couples copper layers through dielectric
  and via paths, with uniform top/bottom convection. Copper resistivity is
  iterated against board temperature. Nonconvergence is reported explicitly.

The saved output contains `scenario.json`, human-readable `result.json` and
numerical `result.npz`. NPZ files contain arrays only and are opened with
`allow_pickle=False`. These files are local; nothing is uploaded. Analysis
does not modify or save the PCB, schematic, footprints, net assignments or
project settings. Cancelling terminates only the calculation worker.

## Limits and interpretation

The method is a 2.5D grid approximation with sampled copper coverage/faces,
ideal electrical terminals and simplified via contact spreading. Narrow
clearances, slots and small pads require adequate resolution. The node budget
is enforced; requested resolution is never silently made coarser. Empty/stale
zone fills must be fixed in KiCad by the user and saved before analysis.

Plated oblong-slot barrels are omitted with explicit warnings.
Round PTH barrels, through vias and blind-via spans are modeled. The GUI defaults to 500,000 layer cells and allows a budget of up to
2,000,000 in Calculation settings. No resolution is reduced automatically.

Thermal boundaries omit radiation, edge convection, enclosure/airflow CFD,
thermal-interface materials, heatsinks and package junction/case models.
Component heat must be supplied manually. Copper thickness, via wall plating,
convection and material properties are assumptions until matched to the
manufactured board. These results support comparison and hotspot investigation;
they do not establish a validated operating-current rating. Compare against
hand calculations, mesh refinement and physical measurements.

## Development verification

The stdlib unittest suite checks analytical resistance/current density,
parallel layers, actual via spans/plating, conservation of current and power,
convection heat balance, thermal coupling into another net, signed return
current, disconnected terminals, cancellation and temperature feedback.
Native temporary KiCad fixtures check stackup, cutouts, filled copper, via
annuli and pad contacts. Tests never require or distribute a user's PCB.

Run explicit groups from the repository root. Portable/package checks need the
development requirements; GUI checks need wxPython on Windows. Native checks
must use KiCad 10's bundled Python with `pcbnew` and are not silently skipped:

```sh
python ci/run_tests.py portable
python ci/run_tests.py package
python ci/run_tests.py gui
python ci/run_tests.py native
```

A passing hosted portable/package job does not mean native KiCad or Windows GUI
integration was tested. These groups have separate runtime requirements.

License: MIT. See `LICENSE`.

The numbered change sections below describe local development milestones;
0.3.4 is the first public release. They document features included in this package.

## Changes in 0.2.0

Added a board-centered analysis editor: saved copper geometry and references,
direct pad/copper-point assignment, grouped pad selection, editable on-board
markers, zoom/pan/fit/search, and a heatmap overlay aligned with the board.
Scenarios retain virtual point contacts as well as pad groups. Filled zones
are read automatically and their counts are shown. The model remains read-only
and uses the same multilayer DC and estimated board-temperature limits above.


## 0.3.0 changes and workflow

- Accidental Ctrl-clicks on empty space, tracks, zones, holes or vias preserve
  the selected pad group and do not create point contacts.
- **Visibility…** independently toggles references, pad numbers, silkscreen/text/
  drawings, tracks, filled zones and vias. Hiding items changes only the view,
  never the coupled calculation. Pads and analysis markers remain selectable.
- Adding a voltage source sets **Component selection net**. Click a component
  body to select only that footprint's pads on the chosen source net. Direct pad clicks still select
  that one pad. Ctrl-click bodies accumulates groups; then choose Load to assign
  a total current. In Load mode a normal component click opens the value dialog
  for its matching pads. Internal copper-layer views keep precise copper picking.
  Choose **Exact pad / copper selection** to disable component matching; select
  a different source net in the same box when analyzing multiple supplies.
- The viewer captures a private saved-board snapshot on Open/Reload. Every
  analysis receives its own copy of that displayed snapshot. You can edit and
  save the original PCB during the solve; the map remains tied to the displayed
  copy. **Reload** captures subsequent PCB edits for a new analysis. Snapshot
  paths, SHA-256, capture time and original file provenance are recorded locally.
  Tampered snapshots and results that do not match the view are rejected.
- Combo faces/popups, notebook tabs and table headers are locally painted light
  controls. KiCad's dark theme cannot cover their labels, and its global theme
  is unchanged.
- The numerical solver uses a multilevel preconditioner and warm starts for the
  unchanged fine-grid equations. Requested resolution, via spans and the thermal
  contributions of every layer remain in the model; convergence and conservation
  checks remain enforced. Run results include geometry/solver/output phase times.



## 0.3.1 load totals and rejected analyses

The input panel shows the sum of every load group on each net, keeping drawn
and injected current separate. Each row adds its own group total; current is
not divided between rows automatically. Adding the exact same pad group again
edits its existing value instead of creating an accidental duplicate. Old
scenarios retain their data; repeated groups are shown and must be removed
before starting another GUI analysis.

For example, three separate 1 A rows request 3 A. If the intended total current
is 1 A shared by three contact locations, Ctrl-select those contacts together
and assign one 1 A group, or intentionally split the total between separate
rows. No currents are converted or rescaled automatically by this steady-DC model.

When the electrothermal model exceeds its validity cutoff, produces nonfinite
values, or fails to converge, English/Turkish messages now identify the cause
and show the actual per-net load totals. Structured worker diagnostics include
iteration and mesh/physical settings. A cutoff is not a prediction that the
real board reaches that temperature, and rejected states are never displayed
as converged temperature maps.


## 0.3.2: inspect DC paths when temperature cannot be solved

A thermal failure no longer discards the independently valid first electrical
solution. The viewer opens **Copper loss density · W/mm²**, with **Current
density** and **Voltage deviation** also available on every layer. A persistent
notice says copper resistance is fixed at the scenario's initial ambient
temperature. There is no temperature choice for this diagnostic dataset.
These are reference-temperature DC results, not an operating-temperature
prediction or a substitute for a converged electrothermal result.

The original thermal error remains, its dialog explains that DC maps are ready,
and the result folder contains `dc-diagnostic.json` and `dc-diagnostic.npz`. No
invalid temperature array is written. Current, power and initial-temperature
assumptions are unchanged. Cancellation, disconnected electrical terminals and
heater-only failures do not fabricate partial electrical results. Scenario or
setting changes invalidate the displayed diagnostic maps just like normal maps.

Copper loss density is cell Joule loss divided by cell area, summed over
analysed electrical nets, with one shared scale across layers. It is not
component heat or temperature. The normal converged result also offers this
view using its converged-temperature copper losses.

Top/bottom convection values are physical assumptions; the default 10/10
W/m²K is not a model of a measured heatsink, cable heat path or forced airflow.
A large continuous current can therefore lack a valid steady-state thermal
solution under those assumptions even when its electrical paths are connected.
The plugin does not increase cooling or reduce current automatically to produce
a temperature map. Use actual cooling data when defining a thermal scenario.


## 0.3.3: generic inputs and multiple assignment rows

- New source-voltage, load-current and component-heat fields start empty. Enter
  the values for the current analysis; no board-specific values are supplied.
  Editing an existing assignment still opens its current value.
- Ctrl-click selects separate rows; Shift-click selects a range in the input
  list. **Remove selected** removes every selected row. **Edit value** applies
  a value to all selected assignments of one kind; mixed kinds are not edited
  together because volts, amperes and watts have different meanings.
- Calculation fields keep a light, readable background while the worker runs.
  The fields remain locked until that run ends; their physical values are not
  changed by the visual fix.
- Help, examples and package descriptions use generic PCB terminology. Existing
  saved scenarios keep their explicitly entered values.


## 0.3.4: consistent light controls and remembered calculation settings

Buttons (including hover, pressed, keyboard focus and disabled states), toggles, checkboxes, pad checklist and value-entry dialogs now use the plugin's own light controls. This does not change KiCad's theme.

Calculation settings are saved automatically after edits, before analysis and on close, and restored on the next launch. This includes material category, in-plane/through-plane conductivity, environment, convection, via plating, mesh size/budget and warning markers. Preferences are per user, separate from PCB files and scenario contacts, at `%APPDATA%/kicad/pcb_heatmap/calculation-settings.json`. Scenario files retain their own settings.

Thermal-only component heaters also resolve their existing pad areas when the pad net is not selected for electrical analysis. Separate copper-island rejection remains active and now names the layer/net.
