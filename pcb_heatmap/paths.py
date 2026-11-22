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
import tempfile
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
    """Per-user configuration directory.

    ``%APPDATA%`` wins when it is present, which keeps Windows (and existing
    scripts) working when this code runs under a non-Windows interpreter.
    """
    appdata = _env_directory('APPDATA')
    if appdata is not None:
        return appdata
    return _env_directory('XDG_CONFIG_HOME') or home() / '.config'


def state_root():
    """Per-user state directory: logs, caches and analysis run folders."""
    local = _env_directory('LOCALAPPDATA')
    if local is not None:
        return local
    return _env_directory('XDG_STATE_HOME') or home() / '.local' / 'state'


def data_root():
    """Per-user data directory (KiCad plugin and library installs)."""
    appdata = _env_directory('APPDATA')
    if appdata is not None:
        return appdata
    return _env_directory('XDG_DATA_HOME') or home() / '.local' / 'share'


def settings_directory():
    return config_root() / 'kicad' / APPLICATION


def calculation_settings_path():
    return settings_directory() / 'calculation-settings.json'


def ui_state_path():
    return settings_directory() / 'ui-state.json'


def run_directory_candidates():
    """Writable locations for analysis workspaces, most preferred first.

    A sandboxed or read-only home must not stop an analysis: a KiCad-owned
    configuration folder is tried next, and a private temporary folder last.
    """
    return [
        state_root() / APPLICATION / 'runs',
        config_root() / 'kicad' / APPLICATION / 'runs',
        Path(tempfile.gettempdir()) / APPLICATION / 'runs',
    ]


_RUNS_CACHE = {}


def runs_root():
    """The first writable run-folder root, creating it when needed."""
    candidates = run_directory_candidates()
    key = tuple(str(candidate) for candidate in candidates)
    if key in _RUNS_CACHE:
        return _RUNS_CACHE[key][0]
    for index, candidate in enumerate(candidates):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=candidate, prefix='.write-probe-',
                                             delete=True):
                pass
        except OSError:
            continue
        _RUNS_CACHE[key] = (candidate, index)
        return candidate
    if candidates:
        _RUNS_CACHE[key] = (candidates[-1], len(candidates) - 1)
    return candidates[-1] if candidates else Path(APPLICATION)


def runs_root_is_fallback():
    """True when the primary state directory is unavailable."""
    runs_root()
    key = tuple(str(candidate) for candidate in run_directory_candidates())
    return bool(_RUNS_CACHE.get(key, (None, 0))[1])


def new_run_directory(timestamp=None):
    """Create and return a fresh, uniquely named run directory.

    A name collision inside the same clock tick is retried with an extra
    suffix; if the preferred root became unwritable, the next candidate is used.
    """
    stamp = timestamp or time.strftime('%Y%m%d-%H%M%S')
    last_error = None
    for index, root in enumerate(run_directory_candidates()):
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            last_error = exc
            continue
        for attempt in range(16):
            name = f'{stamp}-{time.time_ns() % 1_000_000:06d}'
            if attempt:
                name = f'{stamp}-{time.time_ns() % 1_000_000:06d}-{attempt}'
            candidate = root / name
            try:
                candidate.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                continue
            except OSError as exc:
                last_error = exc
                break
            key = tuple(str(item) for item in run_directory_candidates())
            _RUNS_CACHE[key] = (root, index)
            return candidate
    raise OSError(f'Could not create a run folder: {last_error}')


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
