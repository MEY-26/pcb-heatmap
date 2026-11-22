"""Versioned interface state: appearance, layout and viewer choices.

Kept deliberately separate from ``preferences.py``.  That file holds the
physical calculation controls and keeps its own schema version; this one may
gain layout fields without invalidating a user's saved physics.  Both use the
same atomic-write discipline, and a damaged file always degrades to defaults
instead of blocking a calculation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from . import paths
from .colormap import DEFAULT_RAMP, RAMPS

UI_STATE_VERSION = 1

APPEARANCES = ('auto', 'dark', 'light')
SECTIONS = ('board', 'inputs', 'model', 'results', 'report')

DEFAULTS = {
    'version': UI_STATE_VERSION,
    'appearance': 'auto',
    'section': 'inputs',
    'splitter': 340,
    'opacity': 68,
    'ramp': DEFAULT_RAMP,
    'width': 1480,
    'height': 920,
}

MAX_BYTES = 65536


def _clamp_int(value, minimum, maximum, fallback):
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return max(minimum, min(maximum, value))


def validate_ui_state(state):
    """Return a clean copy containing only known, in-range fields."""
    if not isinstance(state, dict):
        return dict(DEFAULTS)
    result = dict(DEFAULTS)
    appearance = state.get('appearance')
    if appearance in APPEARANCES:
        result['appearance'] = appearance
    section = state.get('section')
    if section in SECTIONS:
        result['section'] = section
    ramp = state.get('ramp')
    if isinstance(ramp, str) and ramp in RAMPS:
        result['ramp'] = ramp
    result['splitter'] = _clamp_int(state.get('splitter'), 260, 620, DEFAULTS['splitter'])
    result['opacity'] = _clamp_int(state.get('opacity'), 10, 95, DEFAULTS['opacity'])
    result['width'] = _clamp_int(state.get('width'), 1024, 10000, DEFAULTS['width'])
    result['height'] = _clamp_int(state.get('height'), 700, 8000, DEFAULTS['height'])
    return result


def ui_state_path():
    return paths.ui_state_path()


def load_ui_state(path=None):
    filename = Path(path) if path is not None else ui_state_path()
    try:
        with filename.open('rb') as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return dict(DEFAULTS)
        document = json.loads(raw.decode('utf-8'))
        if not isinstance(document, dict):
            return dict(DEFAULTS)
        if document.get('version') != UI_STATE_VERSION:
            return dict(DEFAULTS)
        return validate_ui_state(document)
    except (OSError, ValueError, UnicodeError, RecursionError):
        return dict(DEFAULTS)


def save_ui_state(state, path=None):
    """Atomically persist validated state; ``False`` when unavailable."""
    filename = Path(path) if path is not None else ui_state_path()
    document = validate_ui_state(state)
    document['version'] = UI_STATE_VERSION
    pending = None
    try:
        filename.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=filename.parent,
                                         prefix='.ui-state-', suffix='.tmp',
                                         delete=False) as target:
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
