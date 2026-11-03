# Verification assets

`pcm-schema-v2.json` is the official KiCad PCM v2 metadata schema from
[kicad/addons/metadata](https://gitlab.com/kicad/addons/metadata/-/blob/3fd05579b6e56735d7584c496c9dfc29478de747/schema-v2.json).
It is retained with the upstream repository license in `PCM_SCHEMA_LICENSE.txt`.
This validation asset is not included in the plugin ZIP. PCB Heatmap's own
source code and release package use the MIT license in the repository root.

`run_tests.py` separates portable, wx GUI, native KiCad and package checks.
Hosted CI does not claim to run the native KiCad group.
