# Add PCB Heatmap 0.3.4

Add the first public release of **PCB Heatmap**, a free local KiCad 10
ActionPlugin for multilayer DC power-path investigation and estimated
steady-state board-temperature maps.

Users click the saved PCB view to assign voltage-source contacts, current-load
groups and optional known component heat. Filled zones, tracks, pads, vias and
the physical stackup participate. Layer/net display filters leave the coupled
model unchanged. English/Turkish UI, scenarios, visibility controls and private
saved-board snapshots support interactive investigation without rewriting the
source PCB, real pad nets or schematic. No account or remote solver is required.

## Package facts

- Identifier: `com.github.mey-26.pcb-heatmap`
- Author: Mehmet Emin Yaman — https://github.com/MEY-26
- Source: https://github.com/MEY-26/pcb-heatmap
- Release: https://github.com/MEY-26/pcb-heatmap/releases/tag/v0.3.4
- Archive: `PCB_Heatmap-0.3.4-pcm.zip`
- Version/status/platform: `0.3.4` / `testing` / `windows`
- KiCad: `10.0`; runtime: `swig`; license: MIT
- NumPy and wxPython must already be available in KiCad's Python. No automatic
  dependency download or installation is performed.

This is a new package. The archive's metadata omits
download fields; the repository submission supplies its public URL, SHA-256,
download size and install size. A separate 64×64 catalogue icon is included.

## Model limits and validation scope

This is an engineering prototype for comparison and hotspot investigation,
not certified ampacity or a validated operating-current rating. It estimates
steady-state board temperature, not semiconductor junction temperature. It does
not automatically calculate PWM/switching losses or model radiation, airflow
CFD, heatsinks or thermal-interface materials. Physical material/cooling inputs,
mesh refinement and independent measurements remain necessary.

Regression coverage includes portable equations/current-power conservation,
Windows wx UI/snapshot behavior and native extraction from temporary synthetic
KiCad boards. No private PCB or schematic is distributed. Software checks are
not experimental validation of a manufactured board. Linux/macOS runtime has
not been verified and is not declared as supported.

Completed source CI, official package/icon validators, public-download hash/size
checks and metadata CI results should accompany the submitted request. Checks
still running must be reported as pending rather than passing. Maintainer review
and a catalogue refresh are required before claiming official PCM availability.
