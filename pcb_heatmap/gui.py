"""Native bilingual UI for a saved-board, isolated-process analysis.

Only selection capture touches pcbnew, on the UI thread. Raster extraction and
the numerical solve run in a separate process. No methods modify the live PCB.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import wx
from wx.lib.wordwrap import wordwrap

from . import paths, theme
from .i18n import tr, format_analysis_error
from .model import VERSION, conflicting_terminal_ids
from .ui_controls import LightButton
from .preferences import load_calculation_settings, save_calculation_settings


def apply_light_palette(root, palette=None):
    """Colour this frame's own controls from the resolved theme palette.

    The historical name is kept because dialogs and tests call it; the palette
    is no longer forced light, so dialogs follow the same dark/light appearance
    as the main window without touching any KiCad window.
    """
    theme.apply_palette(root, palette)


def sha256(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


_RUNTIME_PROBES = {}


def _runtime_can_import(candidate):
    """True when a separate interpreter really has pcbnew and NumPy."""
    key = str(candidate)
    if key in _RUNTIME_PROBES:
        return _RUNTIME_PROBES[key]
    ok = False
    try:
        probe = subprocess.run(
            [key, '-c', 'import pcbnew, numpy'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        ok = probe.returncode == 0
    except (OSError, subprocess.SubprocessError, ValueError):
        ok = False
    _RUNTIME_PROBES[key] = ok
    return ok


def worker_python():
    """Use KiCad's own Python rather than installing a second runtime.

    A distribution interpreter is often called ``python3.14`` or lives in a
    bundle, so the historical name whitelist is only a fast path: any
    interpreter that can import pcbnew and NumPy is accepted.  Inside KiCad the
    running interpreter is already such a runtime.
    """
    executable = Path(sys.executable)
    if executable.is_file() and 'pcbnew' in sys.modules and 'numpy' in sys.modules:
        return str(executable)
    candidates = []
    try:
        import pcbnew
        origin = Path(pcbnew.__file__).resolve()
        for parent in origin.parents:
            candidates += [parent / 'python.exe', parent / 'bin' / 'python.exe',
                           parent / 'bin' / 'python3', parent / 'python3']
    except ImportError:
        pass
    candidates.append(executable)
    names = ('python.exe', 'python3', 'python', 'python3.11', 'python3.12', 'python3.13',
             'python3.14')
    seen = []
    for candidate in candidates:
        if candidate.is_file() and str(candidate) not in seen:
            seen.append(str(candidate))
    for candidate in seen:
        if Path(candidate).name.lower() in names and _runtime_can_import(candidate):
            return candidate
    for candidate in seen:
        if _runtime_can_import(candidate):
            return candidate
    raise RuntimeError(
        'KiCad Python runtime not found: no interpreter could import pcbnew and numpy. '
        'On Linux install the distribution\'s KiCad Python bindings (for example '
        'python3-wxgtk4.0 with pcbnew) or run the plugin from KiCad\'s bundled interpreter.')


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

    def error(self, message):
        if 'Source and load terminal cells overlap' in str(message):
            message = self.t('terminal_cells_overlap')
        wx.MessageBox(str(message), self.t('error'), wx.OK | wx.ICON_ERROR, self)

    def show_usage(self, event=None):
        import textwrap
        message = '\n\n'.join(textwrap.fill(part, width=85) for part in self.t('usage_text').split('\n\n'))
        wx.MessageBox(message, self.t('usage'), wx.OK | wx.ICON_INFORMATION, self)


    def check_terminal_rows(self, rows):
        shared = conflicting_terminal_ids(rows)
        if shared:
            labels = sorted({self.pad_by_id.get(identifier, {}).get('label', identifier) for identifier in shared})
            self.error(self.t('terminal_overlap').format(pads=', '.join(labels)))
            return False
        return True


    def selected_row_indices(self):
        selected = []
        index = self.terminals.GetFirstSelected()
        while index >= 0:
            if index < len(self.rows):
                selected.append(index)
            index = self.terminals.GetNextSelected(index)
        return selected


    def scenario(self):
        settings = {key: control.GetValue() for key, control in self.setting_controls.items() if key != 'cell_mm'}
        settings['substrate_material'] = self.selected_material()
        result = {'sources': [], 'loads': [], 'heaters': [], 'settings': settings,
                  'expected_sha256': self.inspection['sha256'], 'board_path': self.board_path}
        for row in self.rows:
            group = {'pad_ids': row['pad_ids']}
            target, field = {'source': ('sources', 'voltage_v'), 'load': ('loads', 'current_a'), 'heat': ('heaters', 'power_w')}[row['kind']]
            group[field] = row['value']
            if row['kind'] == 'load':
                group['distribution'] = row.get('distribution', 'area')
            result[target].append(group)
        return result


    def start_worker(self, mode, arguments):
        try:
            command = [worker_python(), '-u', str(Path(__file__).with_name('worker.py')), *arguments]
            environment = dict(os.environ, PCB_HEATMAP_HEADLESS='1',
                               PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8')
            requested = 0
            threads = getattr(self, 'cpu_threads', None)
            if threads is not None:
                try:
                    requested = int(threads.GetValue())
                except (TypeError, ValueError, RuntimeError):
                    requested = 0
            if requested > 0:
                for variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
                                 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
                    environment[variable] = str(requested)
            environment['PCB_HEATMAP_THREADS'] = str(max(0, requested))
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
            session = getattr(self, '_analysis_session', None)
            if session is not None:
                session['token'] = None
            try:
                # Killing also drops the persistent worker's warm state, which
                # is the only way to interrupt a running native solver.
                process.kill()
            except OSError:
                pass
            self.busy(False)
            self.SetStatusText(self.t('cancelled'))


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
