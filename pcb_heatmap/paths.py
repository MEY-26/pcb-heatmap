"""Per-user directories for settings, interface state and analysis runs.

Windows keeps its ``%APPDATA%`` / ``%LOCALAPPDATA%`` convention.  Every other
platform follows the XDG base-directory specification with its documented
fallbacks, so a Linux installation never writes litter into ``$HOME``.

Nothing here imports wx or KiCad, and nothing writes to disk; callers create
directories explicitly and report an unwritable location instead of silently
falling back to a temporary path.
"""
from __future__ import annotations

import os
from pathlib import Path
import time

APPLICATION = 'pcb_heatmap'
_WINDOWS = os.name == 'nt'
KICAD_VERSION = '10.0'
FLATPAK_ID = 'org.kicad.KiCad'


def home():
    """The user's home directory, or a defensible fallback."""
    try:
        return Path.home()
    except (RuntimeError, OSError):
        return Path(os.environ.get('USERPROFILE') or os.environ.get('HOME') or '.')


def _env_directory(name):
    value = os.environ.get(name, '')
    if not value.strip():
        return None
    try:
        return Path(value).expanduser()
    except (RuntimeError, OSError):
        return None


def config_root():
    """Per-user configuration directory."""
    if _WINDOWS:
        return _env_directory('APPDATA') or home() / 'AppData' / 'Roaming'
    return _env_directory('XDG_CONFIG_HOME') or home() / '.config'


def state_root():
    """Per-user state directory: logs, caches and analysis run folders."""
    if _WINDOWS:
        return _env_directory('LOCALAPPDATA') or home() / 'AppData' / 'Local'
    return _env_directory('XDG_STATE_HOME') or home() / '.local' / 'state'


def data_root():
    """Per-user data directory (KiCad plugin and library installs)."""
    if _WINDOWS:
        return _env_directory('APPDATA') or home() / 'AppData' / 'Roaming'
    return _env_directory('XDG_DATA_HOME') or home() / '.local' / 'share'


def settings_directory():
    return config_root() / 'kicad' / APPLICATION


def calculation_settings_path():
    return settings_directory() / 'calculation-settings.json'


def ui_state_path():
    return settings_directory() / 'ui-state.json'


def runs_root():
    """Where analysis workspaces are created."""
    return state_root() / APPLICATION / 'runs'


def new_run_directory(timestamp=None):
    """Create and return a fresh, uniquely named run directory.

    ``FileExistsError`` from a name collision inside the same clock tick is
    retried with the nanosecond suffix already present in the name.
    """
    root = runs_root()
    stamp = timestamp or time.strftime('%Y%m%d-%H%M%S')
    for attempt in range(16):
        name = f'{stamp}-{time.time_ns() % 1_000_000:06d}'
        if attempt:
            name = f'{stamp}-{time.time_ns() % 1_000_000:06d}-{attempt}'
        candidate = root / name
        try:
            candidate.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        return candidate
    raise OSError(f'Could not create a unique run folder under {root}')


def kicad_config_directories(version=KICAD_VERSION):
    """Candidate KiCad configuration directories, most specific first.

    Copes with a native install (``~/.config``), a Flatpak install
    (``~/.var/app/<id>/config``) and an explicit ``KICAD_CONFIG_HOME`` that
    may or may not already include the version folder.
    """
    candidates = []
    override = _env_directory('KICAD_CONFIG_HOME')
    if override is not None:
        candidates.append(override)
        candidates.append(override / version)
    candidates += [
        config_root() / 'kicad' / version,
        home() / '.var' / 'app' / FLATPAK_ID / 'config' / 'kicad' / version,
    ]
    ordered, seen = [], set()
    for directory in candidates:
        key = str(directory)
        if key not in seen:
            seen.add(key)
            ordered.append(directory)
    return ordered


def plugin_directories(version=KICAD_VERSION):
    """Where a manual plugin install is expected to live, for documentation
    and diagnostics.  Not used to load code."""
    return [
        data_root() / 'kicad' / version / 'scripting' / 'plugins',
        home() / '.var' / 'app' / FLATPAK_ID / 'data' / 'kicad' / version / 'scripting' / 'plugins',
    ]


def describe_runs_root():
    """A human-readable location for error messages."""
    return str(runs_root())
