"""Native bilingual UI for a saved-board, isolated-process analysis.

Only selection capture touches pcbnew, on the UI thread. Raster extraction and
the numerical solve run in a separate process. No methods modify the live PCB.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import numpy as np
import wx
import wx.lib.scrolledpanel as scrolled
from wx.lib.wordwrap import wordwrap

from .i18n import tr, format_analysis_error
from .model import VERSION, conflicting_terminal_ids
from .ui_controls import (LightSpinCtrlDouble, LightChoice, LightButton,
                          LightNotebook, LightListCtrl, LightCheckListBox)
from .preferences import load_calculation_settings, save_calculation_settings

NAVY = '#172e43'
TEAL = '#007e87'
MUTED = '#546b80'
BG = '#eef3f7'
WHITE = '#ffffff'


def apply_light_palette(root):
    """Own every client-control colour without changing KiCad's appearance.

    Embedded wx controls otherwise inherit KiCad's dark foreground/native
    backgrounds while our result panels deliberately remain light.
    """
    def visit(window, dark_surface=False):
        role = getattr(window, '_heatmap_role', '')
        dark_surface = dark_surface or role == 'header'
        is_static = isinstance(window, wx.StaticText)
        is_surface = isinstance(window, (wx.Panel, wx.Dialog, wx.Frame, wx.Notebook, wx.SplitterWindow))
        if isinstance(window, wx.Control) and not is_static:
            # Per-control switch only; never call wx.App.SetAppearance or change
            # any parent KiCad window's global theme.
            window.SetThemeEnabled(False)
        background = NAVY if role == 'header' else BG if isinstance(window, (wx.Frame, wx.SplitterWindow, wx.Notebook)) else WHITE
        if is_static and dark_surface:
            window.SetOwnBackgroundColour(NAVY)
            window.SetOwnForegroundColour(WHITE)
        else:
            window.SetOwnBackgroundColour(background)
            window.SetOwnForegroundColour(TEAL if role == 'primary' else NAVY)
        if isinstance(window, wx.ListCtrl):
            window.SetTextColour(NAVY)
        for child in window.GetChildren():
            visit(child, dark_surface=dark_surface if is_surface else False)
        window.Refresh()
    visit(root)


def sha256(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def worker_python():
    """Use KiCad's own Python rather than installing a second runtime."""
    candidates = []
    try:
        import pcbnew
        origin = Path(pcbnew.__file__).resolve()
        for parent in origin.parents:
            candidates += [parent / 'python.exe', parent / 'bin' / 'python.exe']
    except ImportError:
        pass
    candidates.append(Path(sys.executable))
    for candidate in candidates:
        if candidate.is_file() and candidate.name.lower() in ('python.exe', 'python3', 'python', 'python3.11', 'python3.12'):
            return str(candidate)
    raise RuntimeError('KiCad Python runtime not found. Launch with KiCad’s bundled Python.')


def colorize(values, valid, low, high):
    """Single shared non-logarithmic scale; no smoothing of numerical cells."""
    stops = np.array([[22, 42, 88], [30, 104, 207], [26, 190, 205],
                      [86, 209, 116], [246, 224, 66], [245, 128, 32],
                      [198, 34, 36]], dtype=float)
    normalized = np.clip((np.nan_to_num(values, nan=low) - low) / max(high - low, 1e-12), 0, 1)
    positions = normalized * (len(stops) - 1)
    a = np.minimum(positions.astype(int), len(stops) - 2)
    weight = (positions - a)[..., None]
    rgb = np.asarray(stops[a] * (1 - weight) + stops[a + 1] * weight, dtype=np.uint8)
    rgb[~valid] = [237, 242, 246]
    return np.ascontiguousarray(rgb)


class HeatmapCanvas(wx.Panel):
    def __init__(self, parent, language=lambda: 'en'):
        super().__init__(parent)
        self.language = language
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.values = None
        self.valid = None
        self.bitmap = None
        self.rgb_buffer = None
        self.rgb_bytes = None
        self.source_image = None
        self.scaled_bitmap = None
        self.gradient_bytes = None
        self.gradient_image = None
        self.gradient_bitmap = None
        self.units = ''
        self.low = self.high = 0.0
        self.cell = 1.0
        self.origin = (0.0, 0.0)
        self.image_rect = wx.Rect()
        self.pointer = None
        self.Bind(wx.EVT_PAINT, self.paint)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(), event.Skip()))
        self.Bind(wx.EVT_MOTION, self.hover)

    def clear(self):
        self.values = self.bitmap = None
        self.rgb_buffer = self.rgb_bytes = self.source_image = self.scaled_bitmap = None
        self.Refresh()

    def set_field(self, values, valid, units, origin, cell, scale=None):
        self.values = np.array(values, copy=True)
        self.valid = np.asarray(valid, dtype=bool) & np.isfinite(self.values)
        self.units, self.origin, self.cell = units, origin, cell
        if self.valid.any():
            self.low = float(scale[0] if scale else np.min(self.values[self.valid]))
            self.high = float(scale[1] if scale else np.max(self.values[self.valid]))
            # Keep the RGB storage and a wx-owned image alive explicitly. In
            # KiCad's embedded interpreter a borrowed FromBuffer allocation can
            # be recycled before a later paint event reads the bitmap.
            self.rgb_buffer = colorize(self.values, self.valid, self.low, self.high)
            self.rgb_bytes = self.rgb_buffer.tobytes()
            self.source_image = wx.Image(self.rgb_buffer.shape[1], self.rgb_buffer.shape[0])
            self.source_image.SetData(self.rgb_bytes)
            self.bitmap = wx.Bitmap(self.source_image, depth=24)
            self.scaled_bitmap = None
        else:
            self.bitmap = None
        self.Refresh()

    def paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(WHITE))
        dc.Clear()
        w, h = self.GetClientSize()
        dc.SetTextForeground(MUTED)
        if self.bitmap is None:
            message = tr('empty_view' if self.values is None else 'no_values', self.language())
            for index, line in enumerate(message.splitlines()):
                size = dc.GetTextExtent(line)
                dc.DrawText(line, max(14, (w - size.width) // 2), h // 2 + index * 25)
            return
        bw, bh = self.bitmap.GetWidth(), self.bitmap.GetHeight()
        scale = min(max(w - 40, 1) / bw, max(h - 95, 1) / bh)
        dw, dh = max(1, round(bw * scale)), max(1, round(bh * scale))
        x, y = (w - dw) // 2, max(15, (h - 65 - dh) // 2)
        self.image_rect = wx.Rect(x, y, dw, dh)
        image = self.source_image.Scale(dw, dh, wx.IMAGE_QUALITY_NEAREST)
        self.scaled_bitmap = wx.Bitmap(image, depth=24)
        dc.DrawBitmap(self.scaled_bitmap, x, y)
        dc.SetPen(wx.Pen(wx.Colour('#c3d2df')))
        # Draw the frame without any fill operation. Shared stock brushes in
        # embedded KiCad wx sessions must not paint over the numerical image.
        dc.DrawLine(x, y, x + dw, y)
        dc.DrawLine(x + dw, y, x + dw, y + dh)
        dc.DrawLine(x + dw, y + dh, x, y + dh)
        dc.DrawLine(x, y + dh, x, y)
        gx, gy, gw = max(20, w // 5), h - 45, max(30, w * 3 // 5)
        gradient = colorize(np.linspace(self.low, self.high, gw)[None, :], np.ones((1, gw), bool), self.low, self.high)
        self.gradient_bytes = gradient.tobytes()
        self.gradient_image = wx.Image(gw, 1)
        self.gradient_image.SetData(self.gradient_bytes)
        self.gradient_bitmap = wx.Bitmap(self.gradient_image.Scale(gw, 12, wx.IMAGE_QUALITY_NEAREST), depth=24)
        dc.DrawBitmap(self.gradient_bitmap, gx, gy)
        dc.SetTextForeground(NAVY)
        dc.DrawText(f'{self.low:.4g} {self.units}', gx, gy + 16)
        high_text = f'{self.high:.4g} {self.units}'
        dc.DrawText(high_text, gx + gw - dc.GetTextExtent(high_text).width, gy + 16)

    def hover(self, event):
        if self.values is None or not self.image_rect.Contains(event.GetPosition()):
            return
        x = min(self.values.shape[1] - 1, int((event.GetX() - self.image_rect.x) * self.values.shape[1] / max(self.image_rect.width, 1)))
        y = min(self.values.shape[0] - 1, int((event.GetY() - self.image_rect.y) * self.values.shape[0] / max(self.image_rect.height, 1)))
        if self.valid[y, x]:
            self.SetToolTip(f'X {self.origin[0] + (x + .5) * self.cell:.3f} mm · Y {self.origin[1] + (y + .5) * self.cell:.3f} mm\n{self.values[y, x]:.5g} {self.units}')
        else:
            self.UnsetToolTip()


def light_dialog_buttons(dialog, parent):
    row = wx.BoxSizer(wx.HORIZONTAL)
    cancel = LightButton(dialog, wx.ID_CANCEL, parent.t('cancel'))
    ok = LightButton(dialog, wx.ID_OK, parent.t('ok'))
    row.Add(cancel, 0, wx.RIGHT, 8)
    row.Add(ok)
    ok.SetDefault()
    return row


class LightTextEntryDialog(wx.Dialog):
    """Value entry with the same local controls as the rest of the plugin."""
    def __init__(self, parent, message, caption, value=''):
        super().__init__(parent, title=caption)
        sizer = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(self, label=message)
        label.Wrap(self.FromDIP(480))
        sizer.Add(label, 0, wx.ALL | wx.EXPAND, 14)
        self.editor = wx.TextCtrl(self, value=value, style=wx.TE_PROCESS_ENTER)
        self.editor.SetMinSize((self.FromDIP(320), -1))
        self.editor.Bind(wx.EVT_TEXT_ENTER, lambda event: self.EndModal(wx.ID_OK))
        sizer.Add(self.editor, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 14)
        sizer.Add(light_dialog_buttons(self, parent), 0, wx.ALL | wx.ALIGN_RIGHT, 14)
        self.SetSizerAndFit(sizer)
        apply_light_palette(self)
        self.CentreOnParent()
        self.editor.SetFocus()
        self.editor.SetSelection(-1, -1)

    def GetValue(self):
        return self.editor.GetValue()


class PadPicker(wx.Dialog):
    def __init__(self, parent, pads):
        super().__init__(parent, title=parent.t('choose_pads'), size=(780, 540), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.owner = parent
        self.pads = sorted(pads, key=lambda pad: (pad.get('reference', ''), pad['label'], pad.get('net', '')))
        self.checked = set()
        self.visible = []
        sizer = wx.BoxSizer(wx.VERTICAL)
        hint = wx.StaticText(self, label=parent.t('choose_hint'))
        hint.Wrap(730)
        sizer.Add(hint, 0, wx.ALL | wx.EXPAND, 12)
        self.search = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search.SetDescriptiveText(parent.t('filter'))
        sizer.Add(self.search, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 12)
        self.list = LightCheckListBox(self)
        sizer.Add(self.list, 1, wx.ALL | wx.EXPAND, 12)
        line = wx.BoxSizer(wx.HORIZONTAL)
        for key, handler in [('check_visible', self.check_visible), ('uncheck', self.uncheck)]:
            button = LightButton(self, label=parent.t(key))
            button.Bind(wx.EVT_BUTTON, handler)
            line.Add(button, 0, wx.RIGHT, 8)
        line.AddStretchSpacer()
        line.Add(light_dialog_buttons(self, parent), 0)
        sizer.Add(line, 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(sizer)
        self.search.Bind(wx.EVT_TEXT, self.refresh)
        self.list.Bind(wx.EVT_CHECKLISTBOX, self.check)
        self.refresh()
        apply_light_palette(self)

    def refresh(self, event=None):
        term = self.search.GetValue().casefold()
        self.visible = [pad for pad in self.pads if term in f"{pad['label']} {pad.get('net', '')} {pad.get('footprint', '')}".casefold()]
        self.list.Set([f"{pad['label']}  |  {pad.get('net', '') or '(no net)'}  |  {pad.get('footprint', '')}" for pad in self.visible])
        for index, pad in enumerate(self.visible):
            self.list.Check(index, pad['identifier'] in self.checked)

    def check(self, event):
        index = event.GetInt()
        identifier = self.visible[index]['identifier']
        if self.list.IsChecked(index):
            self.checked.add(identifier)
        else:
            self.checked.discard(identifier)

    def check_visible(self, event):
        self.checked.update(pad['identifier'] for pad in self.visible)
        self.refresh()

    def uncheck(self, event):
        self.checked.clear()
        self.refresh()

    def identifiers(self):
        return [pad['identifier'] for pad in self.pads if pad['identifier'] in self.checked]


class MainFrame(wx.Frame):
    def __init__(self, board_path=None, pcb_context=False, preferences_path=None):
        super().__init__(None, title=f'PCB Heatmap {VERSION}', size=(1450, 940))
        self.SetIcon(wx.Icon(str(Path(__file__).with_name('toolbar-48.png')), wx.BITMAP_TYPE_PNG))
        self.SetMinSize((1100, 700))
        self.language = 'en'
        self.pcb_context = pcb_context
        self.live_bound = pcb_context
        self.board_path = str(Path(board_path).resolve()) if board_path else ''
        self.inspection = None
        self.pad_by_id = {}
        self.rows = []
        self.process = None
        self.process_token = None
        self.process_mode = None
        self.result_dir = None
        self.result = None
        self.arrays = None
        self.bound_text = []
        self.active_result_kind = None
        self.last_log = []
        self.preferences_path = preferences_path or os.environ.get('PCB_HEATMAP_SETTINGS_PATH')
        self._restoring_settings = True
        self._build()
        self.restore_calculation_settings()
        self._settings_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.persist_calculation_settings, self._settings_timer)
        for control in self.setting_controls.values():
            control.Bind(wx.EVT_TEXT, self.calculation_setting_changed)
            control.Bind(wx.EVT_SPINCTRLDOUBLE, self.calculation_setting_changed)
        if hasattr(self, 'node_budget'):
            self.node_budget.Bind(wx.EVT_TEXT, self.calculation_setting_changed)
            self.node_budget.Bind(wx.EVT_SPINCTRL, self.calculation_setting_changed)
        self._restoring_settings = False
        self.Bind(wx.EVT_CLOSE, self.on_close)
        if self.board_path:
            wx.CallAfter(self.reload)

    def t(self, key):
        return tr(key, self.language)

    def label(self, parent, key, **kwargs):
        control = wx.StaticText(parent, label=self.t(key), **kwargs)
        self.bound_text.append((control, key))
        return control

    def button(self, parent, key, handler):
        button = LightButton(parent, label=self.t(key))
        self.bound_text.append((button, key))
        button.Bind(wx.EVT_BUTTON, handler)
        return button

    def build_material_picker(self, parent, sizer):
        self.material_ids = ('custom', 'fr4', 'ceramic', 'metal_core')
        sizer.Add(self.label(parent, 'substrate_material'), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.material_choice = LightChoice(parent, choices=[self.t('material_' + key) for key in self.material_ids])
        self.material_choice.SetSelection(0)
        self.material_choice.Bind(wx.EVT_CHOICE, self.change_material)
        sizer.Add(self.material_choice, 0, wx.ALL | wx.EXPAND, 10)
        self.material_hint = wx.StaticText(parent)
        self.material_hint.SetMinSize((1, -1))
        sizer.Add(self.material_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        self.update_material_hint()

    def selected_material(self):
        return self.material_ids[max(0, self.material_choice.GetSelection())]

    def update_material_hint(self):
        key = 'metal_core_hint' if self.selected_material() == 'metal_core' else 'substrate_hint'
        # During construction a scrolled page can temporarily be as wide as
        # the frame. That width must never become the sidebar's minimum width.
        dc = wx.ClientDC(self.material_hint)
        dc.SetFont(self.material_hint.GetFont())
        self.material_hint.SetLabel(wordwrap(self.t(key), self.FromDIP(270), dc))
        self.material_hint.GetParent().Layout()

    def change_material(self, event=None):
        self.update_material_hint()
        self.calculation_setting_changed(event)

    def calculation_values(self):
        values = {key: control.GetValue() for key, control in self.setting_controls.items()}
        values['substrate_material'] = self.selected_material()
        if hasattr(self, 'node_budget'):
            values['node_budget'] = self.node_budget.GetValue()
        return values

    def restore_calculation_settings(self):
        saved = load_calculation_settings(self.preferences_path)
        for key, control in self.setting_controls.items():
            value = saved.get(key)
            if key == 'substrate_k_z' and value is None:
                value = saved.get('fr4_k', self.setting_controls['fr4_k'].GetValue())
            if value is not None:
                control.SetValue(value)
        if saved.get('substrate_material') in self.material_ids:
            self.material_choice.SetSelection(self.material_ids.index(saved['substrate_material']))
        if hasattr(self, 'node_budget') and 'node_budget' in saved:
            self.node_budget.SetValue(saved['node_budget'])
        self.update_material_hint()

    def calculation_setting_changed(self, event=None):
        if not self._restoring_settings:
            if hasattr(self, 'invalidate_result'):
                self.invalidate_result()
            self._settings_timer.StartOnce(450)
        if event is not None:
            event.Skip()

    def persist_calculation_settings(self, event=None):
        if not self._restoring_settings:
            saved = save_calculation_settings(self.calculation_values(), self.preferences_path)
            if not saved:
                self.SetStatusText(self.t('settings_save_error'))
            return saved
        return True

    def _build(self):
        self.SetBackgroundColour(BG)
        outer = wx.BoxSizer(wx.VERTICAL)
        header = wx.Panel(self)
        header._heatmap_role = 'header'
        header.SetBackgroundColour(NAVY)
        hs = wx.BoxSizer(wx.HORIZONTAL)
        text = wx.BoxSizer(wx.VERTICAL)
        title = self.label(header, 'title')
        title.SetFont(wx.Font(21, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        title.SetForegroundColour(WHITE)
        subtitle = self.label(header, 'subtitle')
        subtitle.SetForegroundColour(wx.Colour('#c6d9e8'))
        text.Add(title, 0, wx.BOTTOM, 3)
        text.Add(subtitle)
        hs.Add(text, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 16)
        langbox = wx.BoxSizer(wx.VERTICAL)
        langlabel = self.label(header, 'language')
        langlabel.SetForegroundColour(WHITE)
        self.language_choice = LightChoice(header, choices=['English', 'Türkçe'])
        self.language_choice.SetSelection(0)
        self.language_choice.Bind(wx.EVT_CHOICE, self.change_language)
        langbox.Add(langlabel, 0, wx.BOTTOM, 3)
        langbox.Add(self.language_choice, 0, wx.EXPAND)
        hs.Add(langbox, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 16)
        header.SetSizer(hs)
        outer.Add(header, 0, wx.EXPAND)
        controls = wx.BoxSizer(wx.HORIZONTAL)
        self.open_button = self.button(self, 'browse', self.browse)
        self.reload_button = self.button(self, 'reload', self.reload)
        self.usage_button = self.button(self, 'usage', self.show_usage)
        controls.Add(self.open_button, 0, wx.RIGHT, 8)
        controls.Add(self.reload_button, 0, wx.RIGHT, 10)
        controls.Add(self.usage_button, 0, wx.RIGHT, 10)
        self.board_label = wx.StaticText(self, label=self.t('no_board'))
        self.board_label.SetForegroundColour(MUTED)
        controls.Add(self.board_label, 1, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(controls, 0, wx.ALL | wx.EXPAND, 12)
        saved_hint = self.label(self, 'saved_only')
        saved_hint.SetForegroundColour(MUTED)
        outer.Add(saved_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 14)
        split = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        left = wx.Panel(split)
        left.SetBackgroundColour(WHITE)
        notebook = LightNotebook(left)
        self.sidebar_notebook = notebook
        terminals = wx.Panel(notebook)
        terminals.SetBackgroundColour(WHITE)
        ts = wx.BoxSizer(wx.VERTICAL)
        hint = self.label(terminals, 'capture_hint')
        hint.Wrap(370)
        ts.Add(hint, 0, wx.ALL | wx.EXPAND, 10)
        self.capture_mode = LightChoice(terminals)
        self.capture_mode.Set(['Use PCB selection', 'Choose pads manually'])
        self.capture_mode.SetSelection(0 if self.pcb_context else 1)
        ts.Add(self.capture_mode, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        self.add_buttons = []
        for kind in ('source', 'load', 'heat'):
            button = self.button(terminals, kind, lambda event, k=kind: self.add_group(k))
            self.add_buttons.append(button)
            ts.Add(button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        self.terminals = LightListCtrl(terminals, style=wx.LC_REPORT | wx.BORDER_SIMPLE)
        for name, width in [('kind', 73), ('net', 85), ('pads', 132), ('value', 90)]:
            self.terminals.InsertColumn(self.terminals.GetColumnCount(), self.t(name), width=width)
        ts.Add(self.terminals, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        rs = wx.BoxSizer(wx.HORIZONTAL)
        self.remove_button = self.button(terminals, 'remove', self.remove_group)
        self.clear_button = self.button(terminals, 'remove_all', self.clear_groups)
        rs.Add(self.remove_button, 1, wx.RIGHT, 6)
        rs.Add(self.clear_button, 1)
        ts.Add(rs, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        self.group_hint = self.label(terminals, 'group_hint')
        self.group_hint.SetForegroundColour(MUTED)
        self.group_hint.Wrap(370)
        ts.Add(self.group_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        cases = wx.BoxSizer(wx.HORIZONTAL)
        self.case_save_button = self.button(terminals, 'save_case', self.save_case)
        self.case_load_button = self.button(terminals, 'load_case', self.load_case)
        cases.Add(self.case_save_button, 1, wx.RIGHT, 6)
        cases.Add(self.case_load_button, 1)
        ts.Add(cases, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        terminals.SetSizer(ts)
        settings = scrolled.ScrolledPanel(notebook)
        settings.SetBackgroundColour(WHITE)
        ss = wx.BoxSizer(wx.VERTICAL)
        self.build_material_picker(settings, ss)
        grid = wx.FlexGridSizer(cols=2, hgap=12, vgap=10)
        grid.AddGrowableCol(0)
        self.setting_controls = {}
        for key, field, value, minimum, maximum, increment, digits in [
            ('ambient', 'ambient_c', 25, -50, 200, 1, 1),
            ('conv_top', 'convection_top', 10, 0, 1000, 1, 1),
            ('conv_bottom', 'convection_bottom', 10, 0, 1000, 1, 1),
            ('plating', 'via_plating_um', 25, 5, 150, 1, 1),
            ('grid', 'cell_mm', .25, .05, 2, .05, 2),
            ('substrate_xy', 'fr4_k', .3, .01, 1000, .05, 3),
            ('substrate_z', 'substrate_k_z', .3, .01, 1000, .05, 3),
            ('copper', 'copper_k', 400, 100, 500, 5, 0),
            ('temp_limit', 'max_temperature_c', 100, -40, 400, 5, 1),
            ('drop_limit', 'max_delta_v', .5, .001, 100, .01, 3),
        ]:
            label = self.label(settings, key)
            label._heatmap_setting_label = True
            label.Wrap(190)
            grid.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            control = LightSpinCtrlDouble(settings, min=minimum, max=maximum, initial=value, inc=increment, size=(100, -1))
            control.SetDigits(digits)
            self.setting_controls[field] = control
            grid.Add(control, 0)
        ss.Add(grid, 0, wx.ALL | wx.EXPAND, 12)
        limits = self.label(settings, 'limit_hint')
        limits.Wrap(360)
        ss.Add(limits, 0, wx.ALL | wx.EXPAND, 12)
        saved_hint = self.label(settings, 'preferences_hint')
        saved_hint.Wrap(290)
        ss.Add(saved_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.scope = self.label(settings, 'scope')
        self.scope.Wrap(360)
        self.scope.SetForegroundColour(MUTED)
        ss.Add(self.scope, 0, wx.ALL | wx.EXPAND, 12)
        settings.SetSizer(ss)
        settings.SetupScrolling(scroll_x=False)
        notebook.AddPage(terminals, self.t('terminals'))
        notebook.AddPage(settings, self.t('settings'))
        ls = wx.BoxSizer(wx.VERTICAL)
        ls.Add(notebook, 1, wx.EXPAND)
        left.SetSizer(ls)
        right = wx.Panel(split)
        right.SetBackgroundColour(WHITE)
        vr = wx.BoxSizer(wx.VERTICAL)
        filter_row = wx.BoxSizer(wx.HORIZONTAL)
        self.view = LightChoice(right)
        self.layer = LightChoice(right)
        self.net = LightChoice(right)
        self.view.Set([self.t(key) for key in ('temperature', 'density', 'drop')])
        self.view.SetSelection(0)
        self.layer.Set([self.t('all_layers')])
        self.layer.SetSelection(0)
        filter_row.Add(self.view, 1, wx.RIGHT, 8)
        filter_row.Add(self.layer, 1, wx.RIGHT, 8)
        filter_row.Add(self.net, 1)
        for control in (self.view, self.layer, self.net):
            control.Bind(wx.EVT_CHOICE, self.render_result)
        vr.Add(filter_row, 0, wx.ALL | wx.EXPAND, 12)
        self.stats = wx.StaticText(right, label='')
        self.stats.SetForegroundColour(NAVY)
        vr.Add(self.stats, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.canvas = HeatmapCanvas(right, lambda: self.language)
        vr.Add(self.canvas, 1, wx.EXPAND)
        self.notes = wx.TextCtrl(right, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE, size=(-1, 95))
        self.notes.SetForegroundColour(MUTED)
        vr.Add(self.notes, 0, wx.ALL | wx.EXPAND, 10)
        right.SetSizer(vr)
        split.SplitVertically(left, right, 420)
        split.SetMinimumPaneSize(340)
        outer.Add(split, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 12)
        footer = wx.BoxSizer(wx.HORIZONTAL)
        self.progress = wx.Gauge(self, range=1000)
        footer.Add(self.progress, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        self.folder_button = self.button(self, 'results', self.open_results)
        self.folder_button.Disable()
        self.cancel_button = self.button(self, 'cancel', self.cancel)
        self.cancel_button.Disable()
        self.run_button = self.button(self, 'run', self.analyze)
        self.run_button._heatmap_role = 'primary'
        self.run_button.SetForegroundColour(TEAL)
        footer.Add(self.folder_button, 0, wx.RIGHT, 8)
        footer.Add(self.cancel_button, 0, wx.RIGHT, 8)
        footer.Add(self.run_button, 0)
        outer.Add(footer, 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(outer)
        self.CreateStatusBar()
        self.SetStatusText(self.t('ready'))
        apply_light_palette(self)
        self.busy(False)

    def change_language(self, event):
        self.language = 'tr' if self.language_choice.GetSelection() == 1 else 'en'
        for control, key in self.bound_text:
            control.SetLabel(self.t(key))
            if isinstance(control, wx.StaticText):
                available = (190 if getattr(control, '_heatmap_setting_label', False) else 280
                             if isinstance(control.GetParent(), scrolled.ScrolledPanel) else
                             control.GetParent().GetClientSize().width - 28)
                if available > 180:
                    control.Wrap(available)
        self.sidebar_notebook.SetPageText(0, self.t('terminals'))
        self.sidebar_notebook.SetPageText(1, self.t('settings'))
        material_index = self.material_choice.GetSelection()
        self.material_choice.Set([self.t('material_' + key) for key in self.material_ids])
        self.material_choice.SetSelection(material_index)
        self.update_material_hint()
        capture_selection = self.capture_mode.GetSelection()
        self.capture_mode.Set([self.t('selected'), self.t('manual')])
        self.capture_mode.SetSelection(max(capture_selection, 0))
        view_sel = max(0, self.view.GetSelection())
        self.view.Set([self.t(key) for key in ('temperature', 'density', 'drop')])
        self.view.SetSelection(view_sel)
        if self.layer.GetCount():
            self.layer.SetString(0, self.t('all_layers'))
        for index, key in enumerate(('kind', 'net', 'pads', 'value')):
            item = self.terminals.GetColumn(index)
            item.SetText(self.t(key))
            self.terminals.SetColumn(index, item)
        self.refresh_rows()
        if self.result is not None:
            self.refresh_result_notes()
        self.update_board_label()
        self.render_result()
        self.Layout()
        self.canvas.Refresh()

    def error(self, message):
        if 'Source and load terminal cells overlap' in str(message):
            message = self.t('terminal_cells_overlap')
        wx.MessageBox(str(message), self.t('error'), wx.OK | wx.ICON_ERROR, self)

    def show_usage(self, event=None):
        import textwrap
        message = '\n\n'.join(textwrap.fill(part, width=85) for part in self.t('usage_text').split('\n\n'))
        wx.MessageBox(message, self.t('usage'), wx.OK | wx.ICON_INFORMATION, self)

    def update_board_label(self):
        if self.inspection is None:
            return
        stats = self.inspection.get('stats', {})
        self.board_label.SetLabel(self.t('board_summary').format(
            file=Path(self.board_path).name, layers=len(self.inspection.get('layers', [])),
            pads=len(self.pad_by_id), zones=stats.get('copper_zones', '—'),
            filled=stats.get('filled_copper_zones', '—'), sha=self.inspection.get('sha256', '')[:10]))
        self.board_label.SetToolTip(self.board_path)

    def check_terminal_rows(self, rows):
        shared = conflicting_terminal_ids(rows)
        if shared:
            labels = sorted({self.pad_by_id.get(identifier, {}).get('label', identifier) for identifier in shared})
            self.error(self.t('terminal_overlap').format(pads=', '.join(labels)))
            return False
        return True

    def busy(self, value):
        for control in [self.open_button, self.reload_button, self.run_button, *self.add_buttons,
                        self.remove_button, self.clear_button, self.case_save_button, self.case_load_button,
                        self.material_choice, *self.setting_controls.values()]:
            control.Enable(not value)
        self.run_button.Enable(not value and self.inspection is not None)
        self.cancel_button.Enable(value)

    def browse(self, event=None):
        with wx.FileDialog(self, self.t('browse'), wildcard='KiCad PCB (*.kicad_pcb)|*.kicad_pcb', style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.board_path = str(Path(dialog.GetPath()).resolve())
                self.live_bound = False
                self.capture_mode.SetSelection(1)
                self.reload(use_active=False)

    def reload(self, event=None, use_active=True):
        if self.process is not None:
            return
        if self.pcb_context and use_active:
            try:
                import pcbnew
                live = pcbnew.GetBoard()
                live_path = live.GetFileName() if live else ''
                if live_path:
                    self.board_path = str(Path(live_path).resolve())
                    self.live_bound = True
                else:
                    self.error(self.t('save_first'))
                    return
            except Exception as exc:
                self.error(exc)
                return
        if not self.board_path or not Path(self.board_path).is_file():
            self.error(self.t('save_first'))
            return
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PCBHeatmap' / 'runs'
        run = base / (time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns())[-6:])
        run.mkdir(parents=True, exist_ok=False)
        self.inspection = None
        self.pad_by_id.clear()
        self.rows.clear()
        self.refresh_rows()
        self.result = self.arrays = None
        self.stats.SetLabel('')
        self.canvas.clear()
        self.folder_button.Disable()
        self._inspection_path = run / 'inspection.json'
        self.start_worker('inspect', ['inspect', '--board', self.board_path, '--output', str(self._inspection_path)])
        self.SetStatusText(self.t('inspect'))

    def verified(self, require_live=False):
        if self.inspection is None:
            self.error(self.t('save_first'))
            return False
        try:
            if sha256(self.board_path) != self.inspection['sha256']:
                self.error(self.t('changed'))
                return False
            if require_live:
                import pcbnew
                live = pcbnew.GetBoard()
                current = live.GetFileName() if live else ''
                if not current or Path(current).resolve() != Path(self.board_path).resolve():
                    self.error(self.t('switched'))
                    return False
            return True
        except Exception as exc:
            self.error(exc)
            return False

    def selected_pad_ids(self):
        # pcbnew objects must never leave this UI thread or enter worker threads.
        import pcbnew
        selected = list(pcbnew.GetCurrentSelection())
        ids = set()
        footprints = []
        for item in selected:
            if isinstance(item, pcbnew.PAD):
                ids.add(str(item.m_Uuid.AsString()))
            elif isinstance(item, pcbnew.FOOTPRINT):
                footprints.append(item.GetReference())
        if footprints:
            candidates = [pad for pad in self.pad_by_id.values() if pad.get('reference') in footprints]
            with PadPicker(self, candidates) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return []
                ids.update(dialog.identifiers())
        return sorted(identifier for identifier in ids if identifier in self.pad_by_id)

    def add_group(self, kind):
        use_live = self.capture_mode.GetSelection() == 0
        if not self.verified(require_live=use_live):
            return
        try:
            if use_live:
                identifiers = self.selected_pad_ids()
            else:
                with PadPicker(self, list(self.pad_by_id.values())) as dialog:
                    if dialog.ShowModal() != wx.ID_OK:
                        return
                    identifiers = dialog.identifiers()
            if not identifiers:
                self.error(self.t('selection_empty'))
                return
            nets = {self.pad_by_id[identifier].get('net', '') for identifier in identifiers}
            if kind != 'heat' and (len(nets) != 1 or '' in nets):
                self.error(self.t('empty_net' if '' in nets else 'single_net'))
                return
            if kind != 'heat' and not self.check_terminal_rows(
                    self.rows + [dict(kind=kind, pad_ids=identifiers)]):
                return
            key = {'source': 'source_value', 'load': 'load_value', 'heat': 'heat_value'}[kind]
            default = ''
            with LightTextEntryDialog(self, self.t(key), self.t(kind), default) as dialog:
                apply_light_palette(dialog)
                if dialog.ShowModal() != wx.ID_OK:
                    return
                try:
                    value = float(dialog.GetValue().strip().replace(',', '.'))
                    if not math.isfinite(value) or (kind == 'load' and value == 0) or (kind == 'heat' and value <= 0):
                        raise ValueError()
                except ValueError:
                    self.error(self.t('invalid'))
                    return
            self.rows.append({'kind': kind, 'pad_ids': identifiers, 'value': value})
            self.refresh_rows()
        except Exception as exc:
            self.error(exc)

    def refresh_rows(self):
        self.terminals.DeleteAllItems()
        for row in self.rows:
            index = self.terminals.InsertItem(self.terminals.GetItemCount(), self.t(row['kind']).replace(self.t('source'), 'V').replace(self.t('load'), 'A').replace(self.t('heat'), 'W'))
            nets = sorted({self.pad_by_id[i].get('net', '') for i in row['pad_ids'] if i in self.pad_by_id})
            self.terminals.SetItem(index, 1, ', '.join(nets))
            self.terminals.SetItem(index, 2, ', '.join(self.pad_by_id[i]['label'] for i in row['pad_ids'] if i in self.pad_by_id))
            self.terminals.SetItem(index, 3, f"{row['value']:g} {'V' if row['kind'] == 'source' else 'A' if row['kind'] == 'load' else 'W'}")

    def selected_row_indices(self):
        selected = []
        index = self.terminals.GetFirstSelected()
        while index >= 0:
            if index < len(self.rows):
                selected.append(index)
            index = self.terminals.GetNextSelected(index)
        return selected

    def remove_group(self, event):
        if self.process is not None:
            return
        indices = self.selected_row_indices()
        if indices:
            for index in reversed(indices):
                del self.rows[index]
            self.refresh_rows()

    def clear_groups(self, event):
        if self.process is not None:
            return
        self.rows.clear()
        self.refresh_rows()

    def scenario(self):
        settings = {key: control.GetValue() for key, control in self.setting_controls.items() if key != 'cell_mm'}
        settings['substrate_material'] = self.selected_material()
        result = {'sources': [], 'loads': [], 'heaters': [], 'settings': settings,
                  'expected_sha256': self.inspection['sha256'], 'board_path': self.board_path}
        for row in self.rows:
            group = {'pad_ids': row['pad_ids']}
            target, field = {'source': ('sources', 'voltage_v'), 'load': ('loads', 'current_a'), 'heat': ('heaters', 'power_w')}[row['kind']]
            group[field] = row['value']
            result[target].append(group)
        return result

    def analyze(self, event=None):
        self.persist_calculation_settings()
        if not self.verified(require_live=self.live_bound):
            return
        if not self.check_terminal_rows(self.rows):
            return
        case = self.scenario()
        if not ((case['sources'] and case['loads']) or case['heaters']):
            self.error(self.t('needs_case'))
            return
        source_nets = {self.pad_by_id[row['pad_ids'][0]]['net'] for row in case['sources']}
        load_nets = {self.pad_by_id[row['pad_ids'][0]]['net'] for row in case['loads']}
        if source_nets != load_nets:
            self.error(self.t('missing_pair') + ', '.join(sorted(source_nets ^ load_nets)))
            return
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PCBHeatmap' / 'runs'
        self.result_dir = base / (time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns())[-6:])
        self.result_dir.mkdir(parents=True, exist_ok=False)
        case_path = self.result_dir / 'scenario.json'
        case_path.write_text(json.dumps(case, indent=2, ensure_ascii=False), encoding='utf-8')
        self.start_worker('analyze', ['analyze', '--board', self.board_path, '--scenario', str(case_path),
                                    '--output-dir', str(self.result_dir), '--cell-mm', str(self.setting_controls['cell_mm'].GetValue()), '--max-cells', '500000'])

    def start_worker(self, mode, arguments):
        try:
            command = [worker_python(), '-u', str(Path(__file__).with_name('worker.py')), *arguments]
            environment = dict(os.environ, PCB_HEATMAP_HEADLESS='1', PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8')
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace', env=environment, creationflags=flags)
        except Exception as exc:
            self.error(exc)
            return
        self.process = process
        self.process_mode = mode
        token = self.process_token = object()
        self.last_log = []
        self.progress.SetValue(0)
        self.busy(True)

        def reader():
            # This thread owns only stdout, never pcbnew or a wx control.
            lines = []
            try:
                for line in process.stdout:
                    line = line.rstrip()
                    lines.append(line)
                    if len(lines) > 60:
                        del lines[0]
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    wx.CallAfter(self.worker_event, token, event)
                code = process.wait()
            except Exception as exc:
                code = -1
                lines.append(str(exc))
            wx.CallAfter(self.worker_finished, token, mode, code, lines)

        threading.Thread(target=reader, daemon=True, name='PCBHeatmap-stdout').start()

    def worker_event(self, token, event):
        if self.process_token is not token or self.IsBeingDeleted():
            return
        if event.get('type') == 'progress':
            progress = max(0, min(1, float(event.get('progress', 0))))
            self.progress.SetValue(round(progress * 1000))
            self.SetStatusText(str(event.get('message', '')))
        elif event.get('type') == 'error':
            localized = format_analysis_error(event.get('code'), event.get('details', {}), self.language)
            self.last_log.append(localized or str(event.get('message', 'Worker error')))

    def worker_finished(self, token, mode, code, lines):
        if self.process_token is not token or self.IsBeingDeleted():
            return
        self.process = self.process_token = None
        self.busy(False)
        if code != 0:
            self.SetStatusText(self.t('error'))
            self.error('\n'.join(self.last_log or lines[-12:]) or f'Worker exited {code}')
            return
        try:
            if mode == 'inspect':
                data = json.loads(self._inspection_path.read_text(encoding='utf-8'))
                if sha256(self.board_path) != data['sha256']:
                    raise ValueError(self.t('changed'))
                self.inspection = data
                raw_pads = data.get('pads', [])
                self.pad_by_id = raw_pads if isinstance(raw_pads, dict) else {pad['identifier']: pad for pad in raw_pads}
                self.rows.clear()
                self.refresh_rows()
                self.update_board_label()
                self.notes.SetValue('\n'.join(data.get('warnings', [])))
                self.SetStatusText(self.t('inspect_done'))
                self.busy(False)
            else:
                self.load_result(self.result_dir / 'result.json')
                self.progress.SetValue(1000)
                self.SetStatusText(self.t('complete'))
                self.folder_button.Enable()
        except Exception as exc:
            self.error(exc)

    def cancel(self, event=None):
        process = self.process
        if process is not None:
            self.process_token = None
            self.process = None
            try:
                process.terminate()
            except OSError:
                pass
            self.busy(False)
            self.SetStatusText(self.t('cancelled'))

    def load_result(self, path):
        result = json.loads(Path(path).read_text(encoding='utf-8'))
        arrays_path = Path(path).parent / result.get('arrays_file', 'result.npz')
        with np.load(arrays_path, allow_pickle=False) as loaded:
            arrays = {key: np.array(loaded[key], copy=True) for key in loaded.files}
        self.result, self.arrays = result, arrays
        layers = result.get('layers', self.inspection.get('layers', []) if self.inspection else [])
        self.layer.Set([self.t('all_layers')] + [layer['name'] if isinstance(layer, dict) else layer for layer in layers])
        self.layer.SetSelection(0)
        self.net.Set([net['name'] if isinstance(net, dict) else net for net in result.get('nets', [])])
        if self.net.GetCount():
            self.net.SetSelection(0)
        self.refresh_result_notes()
        self.render_result()

    def refresh_result_notes(self):
        if self.result is None:
            return
        notes = list(self.result.get('warnings', []))
        diagnostics = self.result.get('diagnostics', {})
        notes.extend(str(value) for value in diagnostics.get('warnings', []) if str(value) not in notes)
        notes.extend(str(value) for value in diagnostics.get('approximations', []))
        if 'converged' in diagnostics:
            notes.append(f"Converged: {diagnostics['converged']} · iterations: {len(diagnostics.get('iterations', []))}")
        if 'thermal_energy_error_w' in diagnostics:
            notes.append(f"Thermal energy residual: {diagnostics['thermal_energy_error_w']:.4g} W")
        self.notes.SetValue(self.t('scope') + '\n' + '\n'.join(notes))

    def render_result(self, event=None):
        if self.result is None or self.arrays is None:
            self.canvas.Refresh()
            return
        kind = max(self.view.GetSelection(), 0)
        layer_index = self.layer.GetSelection() - 1
        net_index = max(self.net.GetSelection(), 0)
        self.net.Enable(kind != 0 and self.net.GetCount() > 0)
        if kind == 0:
            data = self.arrays['temperature_c']
            units = '°C'
        elif kind == 1:
            data = self.arrays.get(f'current_density_a_mm2__{net_index}')
            voltage_domain = self.arrays.get(f'voltage_v__{net_index}')
            if data is not None and voltage_domain is not None:
                data = np.where(np.isfinite(voltage_domain), data, np.nan)
            units = 'A/mm²'
        else:
            volts = self.arrays.get(f'voltage_v__{net_index}')
            data = None
            if volts is not None:
                reference = None
                refs = self.result.get('source_voltages_v', self.result.get('source_voltages', {}))
                name = self.net.GetStringSelection()
                if isinstance(refs, dict):
                    reference = refs.get(name)
                if reference is None:
                    net_info = self.result.get('nets', [])[net_index]
                    if isinstance(net_info, dict):
                        reference = net_info.get('source_voltage_v')
                if reference is None:
                    values = [row['value'] for row in self.rows if row['kind'] == 'source'
                              and self.pad_by_id[row['pad_ids'][0]].get('net') == name]
                    reference = max(values) if values else 0
                data = np.abs(float(reference) - volts) * 1000
            units = 'mV'
        if data is None:
            self.canvas.clear()
            return
        board_mask = np.asarray(self.arrays.get('board_mask', np.ones(data.shape[-2:], dtype=bool)), dtype=bool)
        finite = np.isfinite(data) & board_mask
        scale = (float(np.min(data[finite])), float(np.max(data[finite]))) if finite.any() else None
        if layer_index >= 0 and data.ndim == 3:
            visible = data[layer_index]
        elif data.ndim == 3:
            has_value = finite.any(axis=0)
            visible = np.max(np.where(finite, data, -np.inf), axis=0)
            visible = np.where(has_value, visible, np.nan)
        else:
            visible = data
        board = board_mask
        if kind == 1:
            valid = np.isfinite(visible) & board
            copper = self.arrays.get('copper')
            if copper is not None:
                valid &= (copper[layer_index] > 0 if layer_index >= 0 else np.any(copper > 0, axis=0))
        else:
            valid = np.isfinite(visible) & board
        origin = (self.result.get('origin_x_mm', 0), self.result.get('origin_y_mm', 0))
        cell = self.result.get('cell_mm', .25)
        self.canvas.set_field(visible, valid, units, origin, cell, scale=scale)
        temp = self.arrays['temperature_c']
        if np.isfinite(temp).any():
            location = np.unravel_index(np.nanargmax(temp), temp.shape)
            if len(location) == 3:
                z, y, x = location
            else:
                z, (y, x) = 0, location
            layers = self.result.get('layers', [])
            name = layers[z]['name'] if layers and isinstance(layers[z], dict) else str(z + 1)
            label = f"{self.t('hottest')}: {float(np.nanmax(temp)):.2f} °C · {name} · X {origin[0] + (x + .5) * cell:.2f}, Y {origin[1] + (y + .5) * cell:.2f} mm"
            summary = self.result.get('summaries', {})
            if 'total_heat_w' in summary:
                label += f"\n{self.t('total_heat')}: {summary['total_heat_w']:.4g} W · {self.t('joule')}: {summary.get('joule_w', 0):.4g} W · {self.t('component_heat')}: {summary.get('component_heat_w', 0):.4g} W"
            via_records = self.result.get('via_current_a', [])
            if via_records:
                peak_via = max(via_records, key=lambda via: abs(via.get('max_current_a', 0)))
                label += f"\n{self.t('via_peak')}: {peak_via.get('max_current_a', 0):.4g} A · {peak_via.get('net', '')} · X {peak_via.get('x_mm', 0):.2f}, Y {peak_via.get('y_mm', 0):.2f} mm"
            if valid.any():
                label += f"\n{self.t('peak')}: {float(np.max(visible[valid])):.4g} {units} · {self.t('grid_short')}: {cell:g} mm · {self.t('common_scale')}"
            self.stats.SetLabel(label)
            # Relayout the panel owning this control: frame.Layout() alone
            # leaves a formerly two-line label clipped after adding losses/vias.
            self.stats.Wrap(max(180, self.stats.GetParent().GetClientSize().width - 24))
            self.stats.InvalidateBestSize()
            self.stats.SetMinSize((-1, self.stats.GetBestSize().height))
            self.stats.GetParent().Layout()
        self.Layout()

    def save_case(self, event):
        if not self.verified():
            return
        with wx.FileDialog(self, self.t('save_case'), defaultFile='heatmap-case.json', wildcard='JSON (*.json)|*.json', style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                data = self.scenario()
                data['cell_mm'] = self.setting_controls['cell_mm'].GetValue()
                Path(dialog.GetPath()).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    def load_case(self, event):
        if not self.verified():
            return
        with wx.FileDialog(self, self.t('load_case'), wildcard='JSON (*.json)|*.json', style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            try:
                data = json.loads(Path(dialog.GetPath()).read_text(encoding='utf-8-sig'))
                if data.get('expected_sha256') != self.inspection['sha256']:
                    raise ValueError(self.t('case_board'))
                rows = []
                for key, kind, field in [('sources', 'source', 'voltage_v'), ('loads', 'load', 'current_a'), ('heaters', 'heat', 'power_w')]:
                    for row in data.get(key, []):
                        if not row.get('pad_ids') or any(identifier not in self.pad_by_id for identifier in row['pad_ids']):
                            raise ValueError(self.t('case_board'))
                        value = float(row[field])
                        if not math.isfinite(value) or (kind == 'load' and value == 0) or (kind == 'heat' and value <= 0):
                            raise ValueError(self.t('invalid'))
                        rows.append({'kind': kind, 'pad_ids': row['pad_ids'], 'value': value})
                if not self.check_terminal_rows(rows):
                    return
                self.rows = rows
                case_settings = data.get('settings', {})
                for key, value in case_settings.items():
                    if key in self.setting_controls:
                        if key == 'substrate_k_z' and value is None:
                            continue
                        self.setting_controls[key].SetValue(float(value))
                if case_settings.get('substrate_k_z') is None:
                    self.setting_controls['substrate_k_z'].SetValue(self.setting_controls['fr4_k'].GetValue())
                material = case_settings.get('substrate_material', 'custom')
                if material in self.material_ids:
                    self.material_choice.SetSelection(self.material_ids.index(material))
                self.update_material_hint()
                if 'cell_mm' in data:
                    self.setting_controls['cell_mm'].SetValue(float(data['cell_mm']))
                self.refresh_rows()
                self.calculation_setting_changed()
            except Exception as exc:
                self.error(exc)

    def open_results(self, event):
        if self.result_dir:
            wx.LaunchDefaultApplication(str(self.result_dir))

    def on_close(self, event):
        if self.process is not None:
            if wx.MessageBox(self.t('close_running'), self.t('title'), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES:
                event.Veto()
                return
            self.cancel()
        self._settings_timer.Stop()
        self.persist_calculation_settings()
        self.Destroy()
