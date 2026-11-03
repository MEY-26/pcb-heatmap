"""Small, versioned user preferences for calculation controls only.

These preferences never contain PCB data, terminals or assigned electrical
values.  Reading invalid or unavailable preferences leaves the UI's defaults
in place; an unavailable preferences directory must not prevent analysis.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import tempfile


PREFERENCES_VERSION = 1
MAX_PREFERENCES_BYTES = 65536

# Match the editable calculation controls.  The historical name fr4_k is kept
# in the serialized settings contract even when the substrate is not FR4.
NUMERIC_BOUNDS = {
    'ambient_c': (-40.0, 150.0),
    'convection_top': (0.0, 1000.0),
    'convection_bottom': (0.0, 1000.0),
    'via_plating_um': (5.0, 150.0),
    'cell_mm': (0.025, 2.0),
    'fr4_k': (0.01, 1000.0),
    'substrate_k_z': (0.01, 1000.0),
    'copper_k': (100.0, 500.0),
    'max_temperature_c': (-40.0, 400.0),
    'max_delta_v': (0.001, 100.0),
    'node_budget': (10000, 2000000),
}


def calculation_settings_path():
    """Return a per-user configuration path without importing wx or KiCad."""
    appdata = os.environ.get('APPDATA')
    if appdata:
        root = Path(appdata)
    else:
        root = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return root / 'kicad' / 'pcb_heatmap' / 'calculation-settings.json'


def validate_calculation_settings(settings):
    """Copy only known, finite control values; ignore untrusted extra fields.

    The generic dielectric_k spelling is accepted as an input alias.  Keeping
    fr4_k in the returned dictionary also supports existing scenario files.
    Material identifiers carry presentation metadata; they never override the
    explicit conductivity value saved alongside them.
    """
    if not isinstance(settings, dict):
        return {}
    values = dict(settings)
    if 'fr4_k' not in values and 'dielectric_k' in values:
        values['fr4_k'] = values['dielectric_k']
    result = {}
    for key, (minimum, maximum) in NUMERIC_BOUNDS.items():
        value = values.get(key)
        if key == 'substrate_k_z' and key in values and value is None:
            # None is the explicit backward-compatible isotropic choice.
            result[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        try:
            number = float(value)
        except (ValueError, OverflowError):
            continue
        if not math.isfinite(number) or not minimum <= number <= maximum:
            continue
        if key == 'node_budget':
            if not number.is_integer():
                continue
            result[key] = int(number)
        else:
            result[key] = number
    material = values.get('substrate_material')
    if isinstance(material, str) and material in ('custom', 'fr4', 'ceramic', 'metal_core'):
        result['substrate_material'] = material
    return result


def load_calculation_settings(path=None):
    """Read valid saved controls, or return an empty dict on any file error."""
    filename = Path(path) if path is not None else calculation_settings_path()
    try:
        with filename.open('rb') as source:
            raw = source.read(MAX_PREFERENCES_BYTES + 1)
        if len(raw) > MAX_PREFERENCES_BYTES:
            return {}
        document = json.loads(raw.decode('utf-8'))
        if not isinstance(document, dict):
            return {}
        version = document.get('version')
        if type(version) is not int or version != PREFERENCES_VERSION:
            return {}
        return validate_calculation_settings(document.get('settings'))
    except (OSError, ValueError, UnicodeError, RecursionError):
        return {}


def save_calculation_settings(settings, path=None):
    """Atomically save validated controls, returning False when unavailable.

    A partial write cannot replace the previous preferences.  Callers can use
    the boolean result for a non-modal status message if saving is unavailable.
    """
    filename = Path(path) if path is not None else calculation_settings_path()
    document = {
        'version': PREFERENCES_VERSION,
        'settings': validate_calculation_settings(settings),
    }
    pending = None
    try:
        filename.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=filename.parent,
                                         prefix='.calculation-settings-',
                                         suffix='.tmp', delete=False) as target:
            pending = Path(target.name)
            json.dump(document, target, ensure_ascii=False, allow_nan=False,
                      indent=2, sort_keys=True)
            target.write('\n')
            target.flush()
            os.fsync(target.fileno())
        os.replace(pending, filename)
        return True
    except (OSError, ValueError, OverflowError):
        return False
    finally:
        if pending is not None:
            try:
                pending.unlink(missing_ok=True)
            except OSError:
                pass
