"""Palette resolution for the plugin window.

The plugin paints its own controls, so it owns every colour it draws.  It does
**not** call ``wx.App.SetAppearance`` and never restyles a KiCad window: the
palette is applied to this frame's own controls only.

Three inputs are combined:

* the desktop appearance (dark / light) from wx, or an explicit user choice;
* the KDE accent colour, so buttons and selections match the desktop;
* the active KiCad PCB colour theme, so the board view matches pcbnew.

Every reader is defensive: a missing, unreadable or malformed file degrades to
a built-in default rather than raising inside a paint handler.
"""
from __future__ import annotations

import configparser
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re

from . import paths
from .colormap import DEFAULT_RAMP

DEFAULT_ACCENT = '#3d7fbf'
FALLBACK_CANVAS = '#15202d'

_COLOR_PATTERN = re.compile(r'^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')
_FUNCTION_PATTERN = re.compile(r'^rgba?\(\s*([^)]*)\)$', re.IGNORECASE)


# --------------------------------------------------------------------------- #
# colour helpers
# --------------------------------------------------------------------------- #
def rgb_tuple(value):
    """Parse ``#rrggbb`` / ``#rgb`` / ``rgb(...)`` / ``rgba(...)`` to ``(r,g,b)``."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    match = _COLOR_PATTERN.match(text)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = ''.join(character * 2 for character in digits)
        return tuple(int(digits[index:index + 2], 16) for index in (0, 2, 4))
    match = _FUNCTION_PATTERN.match(text)
    if match:
        parts = [part for part in re.split(r'[,\s/]+', match.group(1).strip()) if part]
        if len(parts) < 3:
            return None
        channels = []
        for part in parts[:3]:
            try:
                number = float(part.rstrip('%'))
            except ValueError:
                return None
            if part.endswith('%'):
                number = number * 255.0 / 100.0
            if not math.isfinite(number):
                return None
            channels.append(max(0, min(255, int(round(number)))))
        return tuple(channels)
    return None


def hex_color(value, fallback=None):
    """Normalise any accepted colour spelling to ``#rrggbb``."""
    channels = rgb_tuple(value)
    if channels is None:
        return fallback
    return '#{0:02x}{1:02x}{2:02x}'.format(*channels)


def blend(first, second, amount):
    """Linear blend ``first`` towards ``second`` by ``amount`` in ``[0, 1]``."""
    a, b = rgb_tuple(first), rgb_tuple(second)
    if a is None or b is None:
        return first if a is not None else second
    amount = max(0.0, min(1.0, float(amount)))
    channels = [int(round(left + (right - left) * amount)) for left, right in zip(a, b)]
    return '#{0:02x}{1:02x}{2:02x}'.format(*channels)


def luminance(value):
    """Relative luminance in ``[0, 1]`` for contrast decisions."""
    channels = rgb_tuple(value)
    if channels is None:
        return 0.5

    def linear(channel):
        channel = channel / 255.0
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    return 0.2126 * linear(channels[0]) + 0.7152 * linear(channels[1]) + 0.0722 * linear(channels[2])


def readable_text(background, light='#ffffff', dark='#101418'):
    """Choose the text colour with the better contrast ratio."""
    return dark if luminance(background) > 0.42 else light


def is_dark(value):
    return luminance(value) < 0.42


# --------------------------------------------------------------------------- #
# palette
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Palette:
    name: str = 'PCB Heatmap dark'
    dark: bool = True
    ramp: str = DEFAULT_RAMP

    bg: str = '#1b1e21'
    panel: str = '#23272b'
    panel_alt: str = '#1f2326'
    elevated: str = '#2a2f33'
    header: str = '#202326'
    border: str = '#343a40'
    divider: str = '#2c3237'

    text: str = '#f0f1f2'
    muted: str = '#9aa4ad'
    disabled: str = '#6b737a'

    accent: str = DEFAULT_ACCENT
    accent_text: str = '#ffffff'
    accent_soft: str = '#2b3f52'
    accent_hover: str = '#4c8fd0'
    selection: str = '#2b3f52'
    selection_text: str = '#f0f1f2'

    danger: str = '#e5545b'
    warning: str = '#f0a35e'
    ok: str = '#46b37c'

    canvas_bg: str = FALLBACK_CANVAS
    canvas_grid: str = '#26313c'
    canvas_outline: str = '#a5b9c5'
    silk: str = '#efe9c4'
    edge: str = '#d0d2cd'
    pad: str = '#cfd39a'
    via: str = '#e3b72e'
    via_hole: str = '#101418'

    source: str = '#43d9a3'
    load: str = '#f5b45f'
    heat: str = '#ff6f7d'

    copper: tuple = field(default_factory=lambda: (
        '#c83434', '#4d7fc4', '#7fc87f', '#ce7d2c', '#4fcbcb',
        '#db628b', '#a7a5c6', '#28ccd9', '#e8b2a7', '#f2eda1'))

    def layer_color(self, index):
        copper = self.copper or (self.edge,)
        return copper[int(index) % len(copper)]

    def marker_color(self, kind):
        return {'source': self.source, 'V': self.source,
                'load': self.load, 'A': self.load,
                'heat': self.heat, 'W': self.heat}.get(str(kind), self.accent)

    def surface(self, role):
        return {'header': self.header, 'panel': self.panel, 'card': self.elevated,
                'strip': self.panel_alt, 'status': self.panel_alt,
                'board': self.canvas_bg}.get(role, self.panel)


DARK_BASE = dict(
    bg='#1b1e21', panel='#23272b', panel_alt='#1f2326', elevated='#2a2f33',
    header='#202326', border='#343a40', divider='#2c3237',
    text='#f0f1f2', muted='#9aa4ad', disabled='#6b737a',
    danger='#e5545b', warning='#f0a35e', ok='#46b37c',
    source='#43d9a3', load='#f5b45f', heat='#ff6f7d',
)

LIGHT_BASE = dict(
    bg='#f2f5f8', panel='#ffffff', panel_alt='#f7fafc', elevated='#ffffff',
    header='#ffffff', border='#d7e0e8', divider='#e6edf2',
    text='#16232f', muted='#5c6f80', disabled='#98a6b3',
    danger='#c0392b', warning='#a16207', ok='#1a7f4b',
    source='#0f8a63', load='#b26a00', heat='#c62828',
)


def _accent_variants(accent, background, dark):
    accent = hex_color(accent) or DEFAULT_ACCENT
    if dark:
        soft = blend(background, accent, 0.22)
        hover = blend(accent, '#ffffff', 0.12)
    else:
        soft = blend('#ffffff', accent, 0.14)
        hover = blend(accent, '#000000', 0.12)
    return dict(accent=accent, accent_text=readable_text(accent),
                accent_soft=soft, selection=soft,
                selection_text=readable_text(soft), accent_hover=hover)


# --------------------------------------------------------------------------- #
# system appearance and desktop accent
# --------------------------------------------------------------------------- #
def system_is_dark():
    """Best-effort dark-mode detection; defaults to dark, KiCad's usual look."""
    try:
        import wx
        appearance = wx.SystemSettings.GetAppearance()
        return bool(appearance.IsDark())
    except Exception:
        pass
    try:
        import wx
        colour = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        return is_dark('#{0:02x}{1:02x}{2:02x}'.format(colour.Red(), colour.Green(), colour.Blue()))
    except Exception:
        return True


def read_kde_accent(config_directories=None):
    """Read the desktop accent colour, preferring KDE's modern key."""
    directories = config_directories or [
        paths.config_root(), paths.home() / '.config',
        paths.home() / '.var' / 'app' / paths.FLATPAK_ID / 'config',
    ]
    for directory in directories:
        filename = Path(directory) / 'kdeglobals'
        parser = configparser.ConfigParser(strict=False, interpolation=None)
        try:
            with filename.open('r', encoding='utf-8', errors='replace') as source:
                parser.read_file(source, source=str(filename))
        except (OSError, configparser.Error, UnicodeError):
            continue
        for section, key in (('General', 'AccentColor'),
                             ('Colors:Selection', 'BackgroundNormal'),
                             ('Colors:Window', 'DecorationFocus')):
            if not parser.has_option(section, key):
                continue
            colour = hex_color('rgb(' + parser.get(section, key) + ')')
            if colour:
                return colour
    return None


# --------------------------------------------------------------------------- #
# KiCad colour theme
# --------------------------------------------------------------------------- #
def _config_theme_document(directory):
    filename = Path(directory) / 'pcbnew.json'
    try:
        with filename.open('r', encoding='utf-8', errors='replace') as source:
            document = json.load(source)
    except (OSError, ValueError, UnicodeError):
        return None, None
    if not isinstance(document, dict):
        return None, None
    appearance = document.get('appearance')
    theme = appearance.get('color_theme') if isinstance(appearance, dict) else None
    return (theme if isinstance(theme, str) else None), Path(directory)


def _deep_merge(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override if override is not None else base
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_theme_document(theme, config_directory):
    theme = (theme or '').strip()
    if not theme or theme == '_builtin_default' or theme.startswith('_builtin'):
        return {}, 'KiCad default'
    filename = Path(theme)
    if not filename.is_absolute():
        filename = Path(config_directory) / 'colors' / theme
    try:
        with filename.open('r', encoding='utf-8', errors='replace') as source:
            document = json.load(source)
    except (OSError, ValueError, UnicodeError):
        return {}, 'KiCad default'
    if not isinstance(document, dict):
        return {}, 'KiCad default'
    user = Path(config_directory) / 'colors' / 'user.json'
    try:
        with user.open('r', encoding='utf-8', errors='replace') as source:
            overrides = json.load(source)
        if isinstance(overrides, dict):
            document = _deep_merge(document, overrides)
    except (OSError, ValueError, UnicodeError):
        pass
    meta = document.get('meta')
    name = meta.get('name') if isinstance(meta, dict) else None
    return document, (name if isinstance(name, str) and name else filename.stem)


def _theme_colours(document):
    board = document.get('board') if isinstance(document, dict) else None
    if not isinstance(board, dict):
        return {}
    colours = {}
    background = hex_color(board.get('background'))
    if background:
        colours['canvas_bg'] = background
    copper_map = board.get('copper')
    if isinstance(copper_map, dict):
        ordered = ['f', 'b'] + [f'in{index}' for index in range(1, 33)]
        copper = [hex_color(copper_map[key]) for key in ordered if key in copper_map]
        copper = [value for value in copper if value]
        if copper:
            colours['copper'] = tuple(copper)
    for target, keys in (
            ('silk', ('f_silks', 'b_silks')),
            ('edge', ('edge_cuts',)),
            ('pad', ('pad_plated_hole', 'f_silks')),
            ('via', ('via_hole',)),
            ('via_hole', ('plated_hole', 'via_hole_walls')),
            ('canvas_grid', ('grid',)),
            ('canvas_outline', ('worksheet', 'edge_cuts'))):
        for key in keys:
            value = hex_color(board.get(key))
            if value:
                colours[target] = value
                break
    return colours


def read_kicad_theme(directories=None):
    """Return ``(colours, display_name)`` from the active PCB colour theme."""
    for directory in (directories or paths.kicad_config_directories()):
        theme, config_directory = _config_theme_document(directory)
        if config_directory is None:
            continue
        document, name = _load_theme_document(theme, config_directory)
        return _theme_colours(document), name
    return {}, 'KiCad default'


# --------------------------------------------------------------------------- #
# public composition
# --------------------------------------------------------------------------- #
def build_palette(dark=True, accent=None, kicad=None, theme_name='', ramp=DEFAULT_RAMP,
                  name=None):
    """Compose a palette from an appearance, an accent and a KiCad theme."""
    base = dict(DARK_BASE if dark else LIGHT_BASE)
    palette_name = name or ('PCB Heatmap dark' if dark else 'PCB Heatmap light')
    if theme_name and theme_name != 'KiCad default':
        palette_name += f' · {theme_name}'
    accent_values = _accent_variants(accent or DEFAULT_ACCENT, base['bg'], dark)
    values = dict(base)
    values.update(accent_values)
    values.setdefault('canvas_grid', '#26313c' if dark else '#d7e0e8')
    values.setdefault('canvas_outline', '#a5b9c5')
    canvas = dict(kicad or {})
    for key, value in canvas.items():
        if key != 'copper':
            values[key] = value
    values.setdefault('via_hole', '#101418' if dark else '#3b3f45')
    values['dark'] = bool(dark)
    values['ramp'] = ramp or DEFAULT_RAMP
    values['name'] = palette_name
    if 'copper' in canvas:
        values['copper'] = tuple(canvas['copper'])
    return Palette(**values)


def load_palette(mode='auto', *, accent=None, kicad=None, dark=None, ramp=None,
                 theme_name=None):
    """Resolve ``auto`` / ``dark`` / ``light`` into a concrete palette."""
    mode = mode if mode in ('auto', 'dark', 'light') else 'auto'
    if mode == 'dark':
        resolved_dark = True
    elif mode == 'light':
        resolved_dark = False
    else:
        resolved_dark = system_is_dark() if dark is None else bool(dark)
    if accent is None:
        accent = read_kde_accent()
    if kicad is None or theme_name is None:
        colours, name = read_kicad_theme()
        kicad = colours if kicad is None else kicad
        theme_name = name if theme_name is None else theme_name
    return build_palette(resolved_dark, accent, kicad, theme_name or '', ramp or DEFAULT_RAMP)


# --------------------------------------------------------------------------- #
# applying a palette to an existing window tree
# --------------------------------------------------------------------------- #
def apply_palette(root, palette=None):
    """Colour this frame's own controls; never touches KiCad's windows."""
    palette = palette or load_palette()
    try:
        from . import ui_controls
        ui_controls.set_palette(palette)
    except Exception:
        pass

    def visit(window):
        role = getattr(window, '_heatmap_role', '')
        setter = getattr(window, 'SetPalette', None)
        if callable(setter):
            try:
                setter(palette)
            except Exception:
                pass
        try:
            if hasattr(window, 'SetOwnBackgroundColour'):
                background = palette.surface(role) if role else palette.panel
                if role == 'muted':
                    background = palette.panel
                window.SetOwnBackgroundColour(background)
            if hasattr(window, 'SetOwnForegroundColour'):
                if role in ('muted', 'caption'):
                    foreground = palette.muted
                elif role == 'accent':
                    foreground = palette.accent
                elif role == 'header':
                    foreground = palette.text
                else:
                    foreground = palette.text
                window.SetOwnForegroundColour(foreground)
        except Exception:
            pass
        try:
            import wx
            if isinstance(window, wx.ListCtrl):
                window.SetBackgroundColour(palette.panel)
                window.SetTextColour(palette.text)
            elif isinstance(window, (wx.TextCtrl, wx.SearchCtrl)):
                window.SetBackgroundColour(palette.panel if role != 'strip' else palette.panel_alt)
                window.SetForegroundColour(palette.text)
        except Exception:
            pass
        for child in window.GetChildren():
            visit(child)
        try:
            window.Refresh()
        except Exception:
            pass

    visit(root)


def describe_environment():
    """Short, copyable summary used by Help and diagnostics."""
    palette = load_palette()
    return {
        'palette': palette.name,
        'dark': palette.dark,
        'accent': palette.accent,
        'canvas': palette.canvas_bg,
        'kicad_theme': palette.name.split(' · ')[-1] if ' · ' in palette.name else 'KiCad default',
    }
