# PCB Heatmap publication and validation

Package identifier: `com.github.mey-26.pcb-heatmap`.
Source repository: [MEY-26/pcb-heatmap](https://github.com/MEY-26/pcb-heatmap).
Author: Mehmet Emin Yaman — [MEY-26](https://github.com/MEY-26).
License: MIT. Target: Windows / KiCad 10.0, `runtime: swig`, testing status.

## First public release

PCB Heatmap 0.3.4 is the first public release. Earlier version sections in the
README describe local development, not older public releases.

Release tag: `v0.3.4`.
Release page: [PCB Heatmap 0.3.4](https://github.com/MEY-26/pcb-heatmap/releases/tag/v0.3.4).
Artifacts: `PCB_Heatmap-0.3.4-pcm.zip` and `SHA256SUMS.txt`.

A public GitHub release and an installable ZIP do not mean acceptance into the
default KiCad catalogue. This new package still requires a separate metadata
submission, successful validation, maintainer review and catalogue refresh.
The merge-request URL and completed CI evidence must be recorded after those
operations succeed; none is claimed here in advance. Until catalogue acceptance,
install the release ZIP through **Plugin and Content Manager → Install from File**.

## Build and immutable artifacts

At the repository root, run `python build_pcm.py`. The package metadata must
match the runtime version `0.3.4`, use this package identifier, declare only the
tested Windows platform and retain `runtime: swig`.

The ZIP metadata omits download fields. Official submission metadata contains
the public release URL, SHA-256, archive size and extracted install size.
Verify the downloaded public ZIP against those fields before submitting it.
Never replace an archive after publishing or submitting its hash: a changed
archive requires a new version.

## Verification scope

Use `python ci/run_tests.py portable`, `package`, `gui` and `native` as separate
checks. GUI needs Windows wxPython; native needs KiCad 10 bundled Python with
`pcbnew`. The runner reports missing runtimes as an error rather than silently
skipping their checks. Hosted portable/package CI does not verify native KiCad.

Development checks cover portable electrical/thermal equations and conservation,
Windows wx selection/controls/settings, immutable analysis snapshots and native
extraction from temporary synthetic KiCad boards. Public tests and fixtures do
not include private user projects. The release process must record the actual
completed test counts, package/schema checks and source/archive identity after
those checks finish; pending checks are not treated as passing.

These are software regression and numerical consistency checks, not experimental
validation or certification of PCB ampacity. The solver is a steady-DC, 2.5D
board-temperature approximation. It omits semiconductor junction/package models,
automatic switching/PWM losses, radiation, enclosure/airflow CFD, heatsinks and
TIMs. Linux/macOS runtime has not been verified. NumPy and wxPython must already
be supplied by the user's KiCad Python; no automatic installer runs.

## Data and source boundaries

The plugin reads a saved PCB and works on private local snapshots. Scenarios,
preferences, numerical arrays and result files are local. Real PCB/schematic
files, net assignments and project settings are not rewritten. No account,
subscription, remote solver or board upload is used by the analysis.

Only plugin sources, synthetic tests, documentation and package assets belong
in this public repository. Check the staged files before committing; never
include user PCB/schematic files, private scenarios, analysis results or credentials.
