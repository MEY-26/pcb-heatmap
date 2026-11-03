"""PCB-first local editor: visual terminals and aligned analysis overlays.

The PCB canvas is a saved-file snapshot. All edits in this window belong only
to the analysis scenario; the user's KiCad board is never changed.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import time
import uuid

import numpy as np
import wx
import wx.lib.scrolledpanel as scrolled

from .board_view import BoardCanvas
from .contacts import validate_contacts
from .gui import MainFrame, PadPicker, LightTextEntryDialog, apply_light_palette, sha256, NAVY, TEAL, WHITE, BG
from .i18n import tr, format_analysis_error
from .model import VERSION, conflicting_terminal_ids, duplicate_terminal_groups, load_totals
from .snapshot import create_snapshot
from .ui_controls import (LightChoice, LightListCtrl, LightNotebook, LightSpinCtrl,
                          LightSpinCtrlDouble, LightButton, LightToggleButton, LightCheckBox)


TEXT = {
    'subtitle': ('Click your PCB to define inputs, loads and heat. View results on the same board.', 'Giriş, yük ve ısı noktalarını PCB üzerinde seç; sonuçları aynı kartın üzerinde gör.'),
    'select_mode': ('Select', 'Seç'),
    'source_mode': ('Source · V', 'Kaynak · V'),
    'load_mode': ('Load · A', 'Yük · A'),
    'heat_mode': ('Heat · W', 'Isı · W'),
    'fit': ('Fit board', 'Kartı sığdır'),
    'search_hint': ('Find footprint reference', 'Komponent referansını bul'),
    'find': ('Find', 'Bul'),
    'board_view': ('PCB layout', 'PCB görünümü'),
    'case_tab': ('Inputs and loads', 'Girişler ve yükler'),
    'settings_tab': ('Calculation settings', 'Hesap ayarları'),
    'notes_tab': ('Model notes', 'Model notları'),
    'edit': ('Edit value', 'Değeri düzenle'),
    'multiselect_hint': ('List: Ctrl+click adds rows; Shift+click selects a range.', 'Liste: Ctrl+tık ile satır ekle; Shift+tık ile aralık seç.'),
    'batch_edit_hint': ('Assign this value to EACH of the {count} selected rows. Rows remain separate; their totals are added normally.', 'Bu değer seçili {count} satırın HER BİRİNE atanır. Satırlar ayrı kalır; toplamları normal şekilde toplanır.'),
    'mixed_kinds': ('Select rows of the same kind to edit their values together. You can remove different kinds together.', 'Değerleri birlikte düzenlemek için aynı türde satırlar seç. Farklı türleri birlikte kaldırabilirsin.'),
    'batch_value_prompt': ('{count} selected rows', '{count} seçili satır'),
    'ok': ('OK', 'Tamam'),
    'group': ('Contact / group', 'Nokta / grup'),
    'empty_selection': ('Select pads on the board. Ctrl+click groups pads. Middle/right drag pans; the wheel zooms.', 'Kart üzerinde pad seç. Ctrl+tık ile padleri grupla. Orta/sağ tuşla sürükle, tekerlekle yakınlaş.'),
    'selected_count': ('Selected: {count} pads · {net}', 'Seçili: {count} pad · {net}'),
    'hint_select': ('Click a pad to inspect it; Ctrl+click to select a group. Choose Source, Load or Heat to enter values on the board.', 'Padi tıklayarak incele; Ctrl+tık ile grup seç. Kartın üzerinde değer girmek için Kaynak, Yük veya Isı aracını seç.'),
    'hint_source': ('Click the input pad or copper where current enters; enter its voltage. Sources are green.', 'Akımın girdiği giriş padini veya bakırı tıkla; gerilimini gir. Kaynaklar yeşil gösterilir.'),
    'hint_load': ('Click different receiving pads/copper on the same net; enter the group current. Loads are orange.', 'Aynı ağda akımı alacak farklı padleri/bakırı tıkla; grup akımını gir. Yükler turuncu gösterilir.'),
    'hint_heat': ('Click a component pad or board location; enter its own heat loss in watts. Optional: copper heating is automatic.', 'Komponent padini veya kart konumunu tıkla; parçanın kendi kaybını watt olarak gir. İsteğe bağlıdır; bakır ısınması otomatik hesaplanır.'),
    'no_copper': ('Click a pad or copper on the visible layer. Use Heat for a board location without a net.', 'Görünen katmandaki bir padi veya bakırı tıkla. Ağsız kart konumlarında Isı aracını kullan.'),
    'no_matching_pads': ('{reference}: no visible pads on {net}. Choose another component or change Component selection net.', '{reference}: {net} ağında görünen pad yok. Başka komponent seç veya Komponent seçim ağını değiştir.'),
    'references': ('References', 'Referanslar'),
    'visibility': ('Visibility…', 'Görünürlük…'),
    'pad_numbers': ('Pad numbers', 'Pad numaraları'),
    'drawings': ('Silkscreen, text and drawings', 'Baskı, yazılar ve çizimler'),
    'tracks': ('Tracks', 'Yollar'),
    'zones': ('Filled zones', 'Bakır dolgular'),
    'vias': ('Vias', 'Vialar'),
    'source_net': ('Component selection net', 'Komponent seçim ağı'),
    'no_source_net': ('Exact pad / copper selection', 'Tek pad / bakır seçimi'),
    'component_hint': ('After adding a source, click a component body to select its pads on this net. Direct pad clicks stay precise.', 'Kaynak ekledikten sonra bu ağdaki padlerini seçmek için komponent gövdesini tıkla. Doğrudan pad tıklaması tek padi seçer.'),
    'snapshot': ('Snapshot', 'Analiz kopyası'),
    'snapshot_hint': ('Analysis uses this saved-board copy. You can edit the original PCB while it runs. Reload to capture your new edits.', 'Analiz bu kayıtlı kart kopyasını kullanır. Hesap sürerken asıl PCB’yi düzenleyebilirsin. Yeni düzenlemeleri almak için Yenile’ye bas.'),
    'opacity': ('Map opacity', 'Harita yoğunluğu'),
    'power': ('Copper loss density · W/mm²', 'Bakır kayıp yoğunluğu · W/mm²'),
    'dc_notice': ('No valid temperature result. These are DC maps with copper resistance fixed at {temperature:g} °C; they are not a temperature prediction. Copper loss sums the analysed nets.', 'Geçerli sıcaklık sonucu yok. Bu DC haritalarında bakır direnci {temperature:g} °C’de sabit kabul edilir; sıcaklık tahmini değildir. Bakır kaybı, analiz edilen ağların toplamıdır.'),
    'dc_ready': ('DC diagnostic maps are available; the thermal calculation failed.', 'DC inceleme haritaları hazır; sıcaklık hesabı tamamlanamadı.'),
    'dc_summary': ('Reference copper temperature: {temperature:g} °C · DC copper loss: {power:.4g} W', 'Bakır direnci için referans: {temperature:g} °C · DC bakır kaybı: {power:.4g} W'),
    'dc_incomplete': ('These maps do not include temperature feedback, GND return unless explicitly analysed, or unassigned component losses.', 'Bu haritalar sıcaklık geri beslemesini, ayrıca analiz edilmediyse GND dönüşünü veya girilmemiş komponent kayıplarını içermez.'),
    'cooling_hint': ('Surface-to-air convection coefficient. Default 10 W/m²K represents weak convection; use known cooling data. Cable/heatsink heat paths and radiation are not modeled.', 'Yüzeyden havaya taşınım katsayısı. Varsayılan 10 W/m²K zayıf taşınım kabulüdür; bilinen soğutma verilerini kullan. Kablo/soğutucu üzerinden ısı uzaklaşması ve radyasyon modellenmez.'),
    'saved_only': ('This view uses the saved PCB, including filled zones. Refill and save in KiCad before reloading. Analysis markers do not edit the PCB.', 'Bu görünüm kayıtlı PCB’yi ve dolgulu zone’ları kullanır. Yenilemeden önce KiCad’de dolguları güncelleyip kaydet. Analiz işaretleri PCB’yi değiştirmez.'),
    'empty_groups': ('Source → receiving load on the same net.\nClick a marker to edit its value.', 'Kaynak → aynı ağdaki alıcı yük.\nDeğerini değiştirmek için işareti tıkla.'),
    'point': ('Point', 'Nokta'),
    'group_short': ('{first} + {count}', '{first} + {count}'),
    'no_loads': ('No current loads assigned.', 'Henüz akım yükü atanmadı.'),
    'load_net_summary': ('{net}: {count} groups · draw {draw:g} A · injection {injection:g} A', '{net}: {count} grup · çekilen {draw:g} A · verilen {injection:g} A'),
    'group_totals_hint': ('Each load row adds its own current. For shared current, Ctrl-select all receiving components and assign ONE group total.', 'Her yük satırı kendi akımını ayrıca ekler. Paylaşılan akım için alıcı komponentleri Ctrl ile birlikte seçip TEK grup toplamı ata.'),
    'duplicate_group': ('Rows {first} and {second} use the same {kind} pads: {pads}. Remove the repeated row before analysis; its current is counted again.', '{first}. ve {second}. satır aynı {kind} padlerini kullanıyor: {pads}. Analizden önce yinelenen satırı kaldır; akımı bir kez daha toplanıyor.'),
    'duplicate_hint': ('Repeated contact groups: {count}. Remove duplicate rows before analysis.', 'Yinelenen nokta grubu: {count}. Analizden önce tekrarlanan satırları kaldır.'),
    'group_updated': ('Existing group updated; no additional load was added.', 'Mevcut grup güncellendi; ek yük oluşturulmadı.'),
    'load_dialog_hint': ('The value is the TOTAL for one contact group, not per pad. Each load row adds its own current.', 'Değer, pad başına değil bir nokta grubunun TOPLAMIDIR. Her yük satırı kendi akımını ayrıca ekler.'),
    'limit_nodes': ('Mesh cell budget', 'Hesap hücresi bütçesi'),
    'changed_case': ('Scenario changed. Run the analysis again to update the map.', 'Senaryo değişti. Haritayı güncellemek için analizi yeniden çalıştır.'),
    'layout_ready': ('PCB ready. Choose Source or Load, then click the board.', 'PCB hazır. Kaynak veya Yük aracını seçip kartı tıkla.'),
    'same_point': ('This copper point is already a source/load of the opposite kind. Choose a different input/output location.', 'Bu bakır noktası zaten diğer türde kaynak/yük olarak kullanılıyor. Farklı bir giriş/çıkış konumu seç.'),
    'case_error': ('The scenario does not match this saved PCB or contains invalid contacts.', 'Senaryo bu kayıtlı PCB ile eşleşmiyor veya geçersiz noktalar içeriyor.'),
    'not_found': ('Reference not found on this board.', 'Referans bu kartta bulunamadı.'),
    'json_only': ('Save the analysis scenario as a .json file. PCB, schematic and project files cannot be replaced.', 'Analiz senaryosunu .json dosyası olarak kaydet. PCB, şema ve proje dosyalarının üzerine yazılamaz.'),
    'all_layers': ('All layers · maximum', 'Tüm katmanlar · en yüksek'),
    'usage_text': (
        'Open or reload your saved PCB. Copper, filled zones, pads and vias appear directly.\n\n'
        'Choose Source V and click the input pad/copper. Enter the voltage. Then choose Load A and click DIFFERENT receiving copper on the SAME net; enter its total current.\n\n'
        'For a multi-pad contact, choose Select and Ctrl+click pads, then press Source/Load. Heat W is optional device loss; it can be placed on a component or board location.\n\n'
        'Click coloured markers to edit values. Use the contact list to remove groups. Source/load contacts must not overlap.\n\n'
        'Wheel: zoom at the cursor. Middle/right drag: pan. Fit board resets the view. Search a reference to find a component.\n\n'
        'Run analysis, then choose temperature, current density or voltage deviation. Layer selection changes only the view; the calculation still includes all layers. Copper point contacts occupy one mesh cell: refine the grid when studying the contact itself.\n\n'
        'No PCB or library files are modified. Save scenarios separately. Refill/save the PCB in KiCad before Reload.\n\n'
        'If temperature cannot be solved, the initial-temperature DC current, voltage-drop and copper-loss maps remain available. The yellow notice explains their reference temperature; they are not temperature results.',
        'Kayıtlı PCB’yi aç veya yenile. Bakır, dolgulu zone, pad ve vialar doğrudan görünür.\n\n'
        'Kaynak V aracını seçip giriş padini/bakırını tıkla ve gerilimi gir. Ardından Yük A aracını seç; AYNI ağda FARKLI bir alıcı bakırı tıkla ve toplam akımını gir.\n\n'
        'Çok padli bir bağlantı için Seç aracında Ctrl+tık ile padleri işaretle, sonra Kaynak/Yük düğmesine bas. Isı W isteğe bağlı komponent kaybıdır; komponent veya kart konumuna yerleştirilebilir.\n\n'
        'Renkli işaretleri tıklayarak değerlerini değiştir. Grupları listedeki kaldır düğmeleriyle sil. Kaynak ve yük noktaları çakışmamalı.\n\n'
        'Tekerlek: imlecin konumuna yakınlaş. Orta/sağ tuşla sürükle: kaydır. Kartı sığdır: görünümü sıfırla. Referans aramasıyla komponent bul.\n\n'
        'Analizi çalıştır, sonra sıcaklık/akım yoğunluğu/gerilim sapmasını seç. Katman seçimi yalnız görünümü değiştirir; hesap tüm katmanları içerir. Bakır üzerine konan noktalar bir hesap hücresi kaplar; noktanın kendisini incelerken hücreyi küçült.\n\n'
        'PCB veya kütüphane dosyaları değiştirilmez. Senaryolar ayrı kaydedilir. Yenilemeden önce KiCad’de dolguları güncelleyip PCB’yi kaydet.\n\n'
        'Sıcaklık hesaplanamazsa başlangıç sıcaklığındaki DC akım, gerilim düşümü ve bakır kaybı haritaları açık kalır. Sarı bilgi satırı referans sıcaklığını belirtir; bu haritalar sıcaklık sonucu değildir.'),
}


class VisualFrame(MainFrame):
    def __init__(self, board_path=None, pcb_context=False, preferences_path=None):
        self.layout_data = None
        self.point_contacts = {}
        self.mode = 'select'
        self.result_dirty = False
        self.mode_buttons = {}
        self.snapshot = None
        self.active_source_net = ''
        self.view_keys = ('board_view', 'temperature', 'density', 'drop', 'power')
        self._diagnostic_path = None
        self._terminal_row_ids = []
        self._refreshing_rows = False
        super().__init__(board_path, pcb_context, preferences_path)
        self.SetSize((1500, 980))
        self.SetMinSize((1120, 740))

    def t(self, key):
        pair = TEXT.get(key)
        return pair[1 if self.language == 'tr' else 0] if pair else tr(key, self.language)

    def _build(self):
        self.SetBackgroundColour(BG)
        outer = wx.BoxSizer(wx.VERTICAL)
        header = wx.Panel(self)
        header._heatmap_role = 'header'
        hs = wx.BoxSizer(wx.HORIZONTAL)
        labels = wx.BoxSizer(wx.VERTICAL)
        title = self.label(header, 'title')
        title.SetFont(wx.Font(20, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        labels.Add(title, 0, wx.BOTTOM, 3)
        labels.Add(self.label(header, 'subtitle'))
        hs.Add(labels, 1, wx.ALL, 14)
        hs.Add(wx.StaticText(header, label='v' + VERSION), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 12)
        self.language_choice = LightChoice(header, choices=['English', 'Türkçe'])
        self.language_choice.SetSelection(0)
        self.language_choice.Bind(wx.EVT_CHOICE, self.change_language)
        hs.Add(self.language_choice, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 14)
        header.SetSizer(hs)
        outer.Add(header, 0, wx.EXPAND)

        navigation = wx.BoxSizer(wx.HORIZONTAL)
        self.open_button = self.button(self, 'browse', self.browse)
        self.reload_button = self.button(self, 'reload', self.reload)
        self.usage_button = self.button(self, 'usage', self.show_usage)
        for button in (self.open_button, self.reload_button, self.usage_button):
            navigation.Add(button, 0, wx.RIGHT, 7)
        self.board_label = wx.StaticText(self, label=self.t('no_board'))
        navigation.Add(self.board_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        outer.Add(navigation, 0, wx.ALL | wx.EXPAND, 10)

        tools = wx.BoxSizer(wx.HORIZONTAL)
        for mode, key in [('select', 'select_mode'), ('source', 'source_mode'), ('load', 'load_mode'), ('heat', 'heat_mode')]:
            button = LightToggleButton(self, label=self.t(key))
            button.Bind(wx.EVT_TOGGLEBUTTON, lambda event, m=mode: self.choose_mode(m))
            self.bound_text.append((button, key))
            self.mode_buttons[mode] = button
            tools.Add(button, 0, wx.RIGHT, 5)
        self.mode_buttons['select'].SetValue(True)
        self.fit_button = self.button(self, 'fit', lambda event: self.canvas.fit_board())
        tools.Add(self.fit_button, 0, wx.LEFT | wx.RIGHT, 9)
        self.search = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER, size=(175, -1))
        self.search.SetDescriptiveText(self.t('search_hint'))
        self.search.Bind(wx.EVT_TEXT_ENTER, self.find_reference)
        tools.Add(self.search, 0, wx.RIGHT, 5)
        tools.Add(self.button(self, 'find', self.find_reference), 0, wx.RIGHT, 10)
        tools.Add(self.button(self, 'visibility', self.show_visibility), 0, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(tools, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        matching = wx.BoxSizer(wx.HORIZONTAL)
        matching.Add(self.label(self, 'source_net'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.source_net = LightChoice(self, choices=[self.t('no_source_net')], size=(260, -1))
        self.source_net.SetMinSize((260, self.source_net.FromDIP(28)))
        self.source_net.SetSelection(0)
        self.source_net.Bind(wx.EVT_CHOICE, self.change_source_net)
        matching.Add(self.source_net, 0, wx.RIGHT, 10)
        matching_hint = self.label(self, 'component_hint')
        matching_hint.Wrap(600)
        matching.Add(matching_hint, 1, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(matching, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.mode_hint = wx.StaticText(self, label=self.t('hint_select'))
        outer.Add(self.mode_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.analysis_notice = wx.StaticText(self, label='')
        outer.Add(self.analysis_notice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.analysis_notice.Hide()

        split = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        left = wx.Panel(split)
        self.sidebar_notebook = LightNotebook(left)
        case = wx.Panel(self.sidebar_notebook)
        cs = wx.BoxSizer(wx.VERTICAL)
        self.selection_info = wx.StaticText(case, label=self.t('empty_selection'))
        self.selection_info.Wrap(300)
        cs.Add(self.selection_info, 0, wx.ALL | wx.EXPAND, 10)
        self.terminals = LightListCtrl(case, style=wx.LC_REPORT)
        for key, width in [('kind', 43), ('group', 174), ('value', 85)]:
            self.terminals.InsertColumn(self.terminals.GetColumnCount(), self.t(key), width=width)
        self.terminals.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.edit_selected)
        self.terminals.Bind(wx.EVT_LIST_ITEM_SELECTED, self.highlight_row)
        self.terminals.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.highlight_row)
        cs.Add(self.terminals, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        self.list_hint = self.label(case, 'multiselect_hint')
        self.list_hint.Wrap(300)
        cs.Add(self.list_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        self.current_summary = wx.StaticText(case, label=self.t('no_loads'))
        self.current_summary.SetFont(self.current_summary.GetFont().Bold())
        cs.Add(self.current_summary, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        self.group_totals_hint = self.label(case, 'group_totals_hint')
        self.group_totals_hint.Wrap(300)
        cs.Add(self.group_totals_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.edit_button = self.button(case, 'edit', self.edit_selected)
        self.remove_button = self.button(case, 'remove', self.remove_group)
        row.Add(self.edit_button, 1, wx.RIGHT, 5)
        row.Add(self.remove_button, 1)
        cs.Add(row, 0, wx.ALL | wx.EXPAND, 8)
        self.clear_button = self.button(case, 'remove_all', self.clear_groups)
        cs.Add(self.clear_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.case_save_button = self.button(case, 'save_case', self.save_case)
        self.case_load_button = self.button(case, 'load_case', self.load_case)
        row.Add(self.case_save_button, 1, wx.RIGHT, 5)
        row.Add(self.case_load_button, 1)
        cs.Add(row, 0, wx.ALL | wx.EXPAND, 8)
        case.SetSizer(cs)
        self.sidebar_notebook.AddPage(case, self.t('case_tab'))

        settings = scrolled.ScrolledPanel(self.sidebar_notebook)
        ss = wx.BoxSizer(wx.VERTICAL)
        self.build_material_picker(settings, ss)
        grid = wx.FlexGridSizer(cols=2, hgap=6, vgap=9)
        grid.AddGrowableCol(0)
        self.setting_controls = {}
        for key, field, value, low, high, increment, digits in [
            ('ambient', 'ambient_c', 25, -40, 150, 1, 1),
            ('conv_top', 'convection_top', 10, 0, 1000, 1, 1),
            ('conv_bottom', 'convection_bottom', 10, 0, 1000, 1, 1),
            ('plating', 'via_plating_um', 25, 5, 150, 1, 1),
            ('grid', 'cell_mm', .25, .025, 2, .025, 3),
            ('substrate_xy', 'fr4_k', .3, .01, 1000, .05, 3),
            ('substrate_z', 'substrate_k_z', .3, .01, 1000, .05, 3),
            ('copper', 'copper_k', 400, 100, 500, 5, 0),
            ('temp_limit', 'max_temperature_c', 100, -40, 400, 5, 1),
            ('drop_limit', 'max_delta_v', .5, .001, 100, .01, 3)]:
            label = self.label(settings, key)
            label._heatmap_setting_label = True
            label.Wrap(190)
            grid.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            control = LightSpinCtrlDouble(settings, min=low, max=high, initial=value, inc=increment, size=(92, -1))
            control.SetDigits(digits)
            control.Bind(wx.EVT_SPINCTRLDOUBLE, self.invalidate_result)
            control.Bind(wx.EVT_TEXT, self.invalidate_result)
            self.setting_controls[field] = control
            if field in ('convection_top', 'convection_bottom'):
                control.SetToolTip(self.t('cooling_hint'))
            grid.Add(control)
        ss.Add(grid, 0, wx.ALL | wx.EXPAND, 10)
        ss.Add(self.label(settings, 'limit_nodes'), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.node_budget = LightSpinCtrl(settings, min=10000, max=2000000, initial=500000)
        self.node_budget.Bind(wx.EVT_SPINCTRL, self.invalidate_result)
        ss.Add(self.node_budget, 0, wx.ALL | wx.EXPAND, 10)
        saved_hint = self.label(settings, 'preferences_hint')
        saved_hint.Wrap(290)
        ss.Add(saved_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        self.scope = self.label(settings, 'scope')
        self.scope.Wrap(290)
        ss.Add(self.scope, 0, wx.ALL | wx.EXPAND, 10)
        settings.SetSizer(ss)
        settings.SetupScrolling(scroll_x=False)
        self.sidebar_notebook.AddPage(settings, self.t('settings_tab'))
        notes_panel = wx.Panel(self.sidebar_notebook)
        ns = wx.BoxSizer(wx.VERTICAL)
        self.notes = wx.TextCtrl(notes_panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        ns.Add(self.notes, 1, wx.ALL | wx.EXPAND, 8)
        notes_panel.SetSizer(ns)
        self.sidebar_notebook.AddPage(notes_panel, self.t('notes_tab'))
        ls = wx.BoxSizer(wx.VERTICAL)
        ls.Add(self.sidebar_notebook, 1, wx.EXPAND)
        left.SetSizer(ls)

        right = wx.Panel(split)
        rs = wx.BoxSizer(wx.VERTICAL)
        filters = wx.BoxSizer(wx.HORIZONTAL)
        self.layer = LightChoice(right)
        self.layer.Set([self.t('all_layers')])
        self.layer.SetSelection(0)
        self.view = LightChoice(right, choices=[self.t(key) for key in self.view_keys])
        self.view.SetSelection(0)
        self.net = LightChoice(right)
        for control in (self.layer, self.view, self.net):
            control.Bind(wx.EVT_CHOICE, self.render_result)
            filters.Add(control, 1, wx.RIGHT, 7)
        rs.Add(filters, 0, wx.ALL | wx.EXPAND, 8)
        self.canvas = BoardCanvas(right, on_pick=self.board_pick, on_marker=self.marker_pick, language=lambda: self.language)
        rs.Add(self.canvas, 1, wx.EXPAND)
        bottom = wx.BoxSizer(wx.HORIZONTAL)
        self.opacity_label = self.label(right, 'opacity')
        bottom.Add(self.opacity_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 7)
        self.opacity = wx.Slider(right, value=68, minValue=10, maxValue=95, size=(145, -1))
        self.opacity.Bind(wx.EVT_SLIDER, self.render_result)
        bottom.Add(self.opacity, 0, wx.ALIGN_CENTER_VERTICAL)
        self.stats = wx.StaticText(right, label='')
        bottom.Add(self.stats, 1, wx.ALL | wx.EXPAND, 8)
        rs.Add(bottom, 0, wx.EXPAND)
        right.SetSizer(rs)
        split.SplitVertically(left, right, 340)
        split.SetMinimumPaneSize(300)
        outer.Add(split, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 10)

        foot = wx.BoxSizer(wx.HORIZONTAL)
        self.progress = wx.Gauge(self, range=1000)
        foot.Add(self.progress, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.folder_button = self.button(self, 'results', self.open_results)
        self.cancel_button = self.button(self, 'cancel', self.cancel)
        self.run_button = self.button(self, 'run', self.analyze)
        self.run_button._heatmap_role = 'primary'
        for control in (self.folder_button, self.cancel_button, self.run_button):
            foot.Add(control, 0, wx.RIGHT, 6)
        outer.Add(foot, 0, wx.ALL | wx.EXPAND, 10)
        self.SetSizer(outer)
        self.CreateStatusBar()
        self.SetStatusText(self.t('ready'))
        apply_light_palette(self)
        self.folder_button.Disable()
        self.busy(False)

    def busy(self, value):
        for control in (self.open_button, self.reload_button, self.edit_button, self.remove_button,
                        self.clear_button, self.case_save_button, self.case_load_button,
                        self.node_budget, self.material_choice, *self.setting_controls.values(), *self.mode_buttons.values()):
            control.Enable(not value)
        self.run_button.Enable(not value and self.inspection is not None)
        self.cancel_button.Enable(value)

    def change_language(self, event=None):
        self.language = 'tr' if self.language_choice.GetSelection() == 1 else 'en'
        for control, key in self.bound_text:
            control.SetLabel(self.t(key))
            if isinstance(control, wx.StaticText) and control.GetParent() is not self:
                width = (190 if getattr(control, '_heatmap_setting_label', False) else 280
                         if isinstance(control.GetParent(), scrolled.ScrolledPanel) else
                         max(180, control.GetParent().GetClientSize().width - 20))
                control.Wrap(width)
        for i, key in enumerate(('case_tab', 'settings_tab', 'notes_tab')):
            self.sidebar_notebook.SetPageText(i, self.t(key))
        view = max(0, self.view.GetSelection())
        self.view.Set([self.t(key) for key in self.view_keys])
        self.view.SetSelection(view)
        if self.layer.GetCount():
            self.layer.SetString(0, self.t('all_layers'))
        self.search.SetDescriptiveText(self.t('search_hint'))
        material_index = self.material_choice.GetSelection()
        self.material_choice.Set([self.t('material_' + key) for key in self.material_ids])
        self.material_choice.SetSelection(material_index)
        self.update_material_hint()
        for field in ('convection_top', 'convection_bottom'):
            self.setting_controls[field].SetToolTip(self.t('cooling_hint'))
        self.refresh_source_nets()
        for index, key in enumerate(('kind', 'group', 'value')):
            col = self.terminals.GetColumn(index)
            col.SetText(self.t(key)); self.terminals.SetColumn(index, col)
        self.mode_hint.SetLabel(self.t('hint_' + self.mode))
        self.update_board_label()
        self.refresh_rows()
        self.update_selection_info()
        if self.result is not None:
            self.refresh_result_notes()
        self.render_result()
        self.update_analysis_notice()
        if self.process is None:
            self.SetStatusText(self.t('dc_ready') if self.is_dc_diagnostic() else self.t('snapshot_hint'))
        self.Layout()

    def reload(self, event=None, use_active=True, board_path=None):
        if self.process is not None:
            return
        candidate = str(Path(board_path).resolve()) if board_path else self.board_path
        if self.pcb_context and use_active:
            import pcbnew
            board = pcbnew.GetBoard()
            path = board.GetFileName() if board else ''
            if path:
                candidate = str(Path(path).resolve())
                self.live_bound = True
        if not candidate or not Path(candidate).is_file():
            self.error(self.t('save_first'))
            return
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PCBHeatmap' / 'runs'
        run = base / (time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns())[-6:])
        run.mkdir(parents=True, exist_ok=False)
        try:
            snapshot = create_snapshot(candidate, run)
        except Exception as exc:
            self.error(exc)
            return
        self.snapshot = snapshot
        self.board_path = candidate
        self._inspection_path = run / 'layout.json'
        self.inspection = self.layout_data = None
        self.pad_by_id.clear(); self.point_contacts.clear(); self.rows.clear()
        self.result = self.arrays = None
        self.result_dirty = False
        self.update_analysis_notice()
        self.canvas.set_layout(None)
        self.stats.SetLabel(''); self.refresh_rows()
        self.folder_button.Disable()
        self.start_worker('layout', ['layout', '--board', self.snapshot['path'], '--output', str(self._inspection_path)])

    def browse(self, event=None):
        with wx.FileDialog(self, self.t('browse'), wildcard='KiCad PCB (*.kicad_pcb)|*.kicad_pcb', style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.live_bound = False
                self.reload(use_active=False, board_path=dialog.GetPath())

    def accept_layout(self, data):
        self.inspection = self.layout_data = data
        self.pad_by_id = {pad['identifier']: pad for pad in data.get('pads', [])}
        self.point_contacts = {}
        self.rows = []
        self.canvas.set_layout(data)
        self.layer.Set([self.t('all_layers')] + [layer['name'] for layer in data['layers']])
        self.layer.SetSelection(1 if data['layers'] else 0)
        self.view_keys = ('board_view', 'temperature', 'density', 'drop', 'power')
        self.view.Set([self.t(key) for key in self.view_keys])
        self.view.SetSelection(0)
        self.update_board_label()
        self.refresh_rows()
        self.notes.SetValue(self.t('saved_only') + '\n\n' + self.t('snapshot_hint') + '\n\n' + '\n'.join(data.get('warnings', [])))
        self.render_result()
        self.update_selection_info()
        self.SetStatusText(self.t('layout_ready'))
        self.busy(False)

    def worker_finished(self, token, mode, code, lines):
        if self.process_token is not token or self.IsBeingDeleted():
            return
        if mode == 'analyze' and code != 0 and self._diagnostic_path:
            self.process = self.process_token = None
            self.busy(False)
            try:
                self.load_result(self._diagnostic_path)
                self.progress.SetValue(0)
                self.folder_button.Enable()
                self.SetStatusText(self.t('dc_ready'))
                self.error(self.t('dc_ready') + '\n\n' + '\n'.join(self.last_log or lines[-12:]))
            except Exception as exc:
                self.error(exc)
            return
        if mode != 'layout':
            super().worker_finished(token, mode, code, lines)
            return
        self.process = self.process_token = None
        self.busy(False)
        if code != 0:
            self.error('\n'.join(self.last_log or lines[-12:]))
            return
        try:
            data = json.loads(self._inspection_path.read_text(encoding='utf8'))
            if sha256(self.snapshot['path']) != data['sha256']:
                raise ValueError(self.t('changed'))
            self.accept_layout(data)
        except Exception as exc:
            self.error(exc)

    def start_worker(self, mode, arguments):
        self._diagnostic_path = None
        super().start_worker(mode, arguments)

    def worker_event(self, token, event):
        if self.process_token is not token or self.IsBeingDeleted():
            return
        if event.get('type') == 'diagnostic_result':
            path = Path(event.get('path', '')).resolve()
            # Results are accepted only from this worker's fresh run folder.
            if self.result_dir and path.parent == Path(self.result_dir).resolve() and path.name == 'dc-diagnostic.json':
                self._diagnostic_path = path
            return
        super().worker_event(token, event)

    def choose_mode(self, mode):
        selected = self.canvas.get_selection()
        self.mode = mode
        for key, button in self.mode_buttons.items():
            button.SetValue(key == mode)
        self.canvas.set_mode(mode)
        self.mode_hint.SetLabel(self.t('hint_' + mode))
        if mode != 'select' and selected:
            self.define_contact(mode, selected, [])
        self.Layout()

    def update_board_label(self):
        if not self.inspection:
            return
        stats = self.inspection.get('stats', {})
        self.board_label.SetLabel(self.t('board_summary').format(
            file=Path(self.board_path).name, layers=len(self.inspection.get('layers', [])),
            pads=len(self.inspection.get('pads', [])), zones=stats.get('copper_zones', '—'),
            filled=stats.get('filled_copper_zones', '—'), sha=self.inspection.get('sha256', '')[:10]))
        self.board_label.SetLabel(self.board_label.GetLabel() + ' · ' + self.t('snapshot'))
        self.board_label.SetToolTip(self.board_path + '\n' + self.t('snapshot_hint') +
                                   ('\n' + self.snapshot['path'] if self.snapshot else ''))

    def verified(self, require_live=False):
        """Validate the displayed copy, never a file the user is still editing."""
        if not self.inspection:
            self.error(self.t('save_first'))
            return False
        try:
            path = self.snapshot['path'] if self.snapshot else self.board_path
            if sha256(path) != self.inspection['sha256']:
                raise ValueError(self.t('changed'))
            return True
        except Exception as exc:
            self.error(exc)
            return False

    def show_visibility(self, event=None):
        with wx.Dialog(self, title=self.t('visibility').rstrip('…')) as dialog:
            sizer = wx.BoxSizer(wx.VERTICAL)
            for key, value in self.canvas.get_visibility().items():
                checkbox = LightCheckBox(dialog, label=self.t(key))
                checkbox.SetValue(value)
                checkbox.Bind(wx.EVT_CHECKBOX, lambda event, k=key, c=checkbox:
                              self.canvas.set_visibility(**{k: c.GetValue()}))
                sizer.Add(checkbox, 0, wx.ALL, 8)
            ok = LightButton(dialog, wx.ID_OK, self.t('ok'))
            ok.SetDefault()
            sizer.Add(ok, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
            dialog.SetSizerAndFit(sizer)
            apply_light_palette(dialog)
            dialog.CentreOnParent()
            dialog.ShowModal()

    def refresh_source_nets(self, preferred=None):
        nets = list(dict.fromkeys(self.pad_by_id[i].get('net', '')
                    for row in self.rows if row['kind'] == 'source'
                    for i in row['pad_ids'] if i in self.pad_by_id))
        nets = [net for net in nets if net]
        current = self.active_source_net if preferred is None else preferred
        if current and current not in nets:
            current = nets[-1] if nets else ''
        self.source_net.Set([self.t('no_source_net')] + nets)
        self.source_net.SetSelection(nets.index(current) + 1 if current else 0)
        self.active_source_net = current
        self.canvas.set_preferred_net(current)

    def change_source_net(self, event=None):
        self.active_source_net = self.source_net.GetStringSelection() if self.source_net.GetSelection() > 0 else ''
        self.canvas.set_preferred_net(self.active_source_net)

    def board_pick(self, picked):
        if not self.inspection or self.process is not None:
            return
        if picked.get('auto_matched') and not picked.get('pad_ids'):
            self.SetStatusText(self.t('no_matching_pads').format(reference=picked.get('reference', ''), net=self.active_source_net))
            self.update_selection_info()
            return
        if picked.get('kind', self.mode) == 'select':
            if picked.get('cancel_tool'):
                self.choose_mode('select')
            self.update_selection_info()
            return
        self.define_contact(picked.get('kind', self.mode), picked.get('pad_ids', []), picked.get('points', []))

    def define_contact(self, kind, pad_ids, points):
        if not self.verified():
            return
        try:
            if kind == 'heat':
                points = [{**point, 'net': ''} for point in points]
            normalized = validate_contacts(points, self.inspection) if points else {}
            identifiers = list(dict.fromkeys(list(pad_ids) + list(normalized)))
            if not identifiers:
                self.error(self.t('no_copper')); return
            meta = dict(self.pad_by_id)
            for identifier, contact in normalized.items():
                meta[identifier] = self.point_metadata(contact)
            if any(identifier not in meta for identifier in identifiers):
                raise ValueError(self.t('changed'))
            nets = {meta[identifier].get('net', '') for identifier in identifiers}
            if kind != 'heat' and ('' in nets or len(nets) != 1):
                self.error(self.t('single_net')); return
            if conflicting_terminal_ids(self.rows + [dict(kind=kind, pad_ids=identifiers)]):
                labels = ', '.join(meta[i]['label'] for i in identifiers)
                self.error(self.t('terminal_overlap').format(pads=labels)); return
            # Distinct point IDs at an identical location should be caught before
            # paying for a mesh/solve, just like duplicate physical pad UUIDs.
            if kind in ('source', 'load'):
                opposite = 'load' if kind == 'source' else 'source'
                for row in self.rows:
                    if row['kind'] != opposite:
                        continue
                    for identifier in row['pad_ids']:
                        old = self.point_contacts.get(identifier)
                        if old and any(old['layer'] == c['layer'] and old['net'] == c['net'] and
                                       math.hypot(old['x_mm'] - c['x_mm'], old['y_mm'] - c['y_mm']) < 1e-6
                                       for c in normalized.values()):
                            self.error(self.t('same_point')); return
            label = ', '.join(meta[i]['label'] for i in identifiers)
            existing = next((row for row in self.rows if row['kind'] == kind and
                             set(row['pad_ids']) == set(identifiers)), None)
            value = self.ask_value(kind, label, existing['value'] if existing else None)
            if value is None:
                return
            self.point_contacts.update(normalized)
            self.pad_by_id.update({i: meta[i] for i in normalized})
            if existing is not None:
                existing['value'] = value
            else:
                self.rows.append(dict(identifier=uuid.uuid4().hex, kind=kind, pad_ids=identifiers, value=value))
            if kind == 'source':
                self.active_source_net = next(iter(nets))
            self.canvas.clear_selection()
            self.refresh_rows()
            self.update_selection_info()
            self.invalidate_result()
            if existing is not None:
                self.SetStatusText(self.t('group_updated'))
        except Exception as exc:
            self.error(exc)

    def point_metadata(self, contact):
        return dict(identifier=contact['identifier'], label=f"{self.t('point')} ({contact['x_mm']:.2f}, {contact['y_mm']:.2f})",
                    net=contact['net'], x_mm=contact['x_mm'], y_mm=contact['y_mm'], layers=[contact['layer']], reference='')

    def ask_value(self, kind, label, current=None):
        key = {'source': 'source_value', 'load': 'load_value', 'heat': 'heat_value'}[kind]
        default = str(current) if current is not None else ''
        title = self.t({'source': 'source_mode', 'load': 'load_mode', 'heat': 'heat_mode'}[kind])
        hint = '\n\n' + self.t('load_dialog_hint') if kind == 'load' else ''
        with LightTextEntryDialog(self, label[:180] + hint + '\n\n' + self.t(key), title, default) as dialog:
            apply_light_palette(dialog)
            dialog.FindWindow(wx.ID_OK).SetLabel(self.t('ok'))
            dialog.FindWindow(wx.ID_CANCEL).SetLabel(self.t('cancel'))
            if dialog.ShowModal() != wx.ID_OK:
                return None
            try:
                value = float(dialog.GetValue().strip().replace(',', '.'))
                if not math.isfinite(value) or (kind == 'load' and value == 0) or (kind == 'heat' and value <= 0):
                    raise ValueError()
                return value
            except ValueError:
                self.error(self.t('invalid'))
                return None

    def update_selection_info(self):
        ids = self.canvas.get_selection()
        if ids:
            names = [self.pad_by_id[i]['label'] for i in ids if i in self.pad_by_id]
            nets = sorted({self.pad_by_id[i].get('net', '') for i in ids if i in self.pad_by_id})
            text = self.t('selected_count').format(count=len(ids), net=', '.join(nets)) + '\n' + ', '.join(names)
        else:
            text = self.t('empty_selection')
        self.selection_info.SetLabel(text)
        self.selection_info.Wrap(max(230, self.selection_info.GetParent().GetClientSize().width - 20))
        self.selection_info.InvalidateBestSize()
        self.selection_info.SetMinSize((-1, self.selection_info.GetBestSize().height))
        self.selection_info.GetParent().Layout()

    def refresh_rows(self):
        selected_ids = {self._terminal_row_ids[index] for index in self.selected_row_indices()
                        if index < len(self._terminal_row_ids)}
        self._refreshing_rows = True
        self.terminals.DeleteAllItems()
        markers = []
        self._terminal_row_ids = []
        for row in self.rows:
            row.setdefault('identifier', uuid.uuid4().hex)
            self._terminal_row_ids.append(row['identifier'])
            unit = {'source': 'V', 'load': 'A', 'heat': 'W'}[row['kind']]
            labels = [self.pad_by_id.get(i, {}).get('label', i) for i in row['pad_ids']]
            short = labels[0] if len(labels) == 1 else self.t('group_short').format(first=labels[0], count=len(labels) - 1)
            index = self.terminals.InsertItem(self.terminals.GetItemCount(), unit)
            self.terminals.SetItem(index, 1, short)
            self.terminals.SetItem(index, 2, f"{row['value']:g} {unit}")
            if row['identifier'] in selected_ids:
                self.terminals.Select(index)
            markers.append(dict(id=row['identifier'], identifier=row['identifier'], kind=row['kind'],
                                pad_ids=[i for i in row['pad_ids'] if i not in self.point_contacts],
                                points=[self.point_contacts[i] for i in row['pad_ids'] if i in self.point_contacts],
                                value=row['value'], label=f"{row['value']:g} {unit}",
                                selected=row['identifier'] in selected_ids))
        self.canvas.set_markers(markers)
        self._refreshing_rows = False
        if selected_ids:
            self.highlight_row()
        self.refresh_source_nets()
        totals = load_totals(self.rows, self.pad_by_id)
        lines = [self.t('load_net_summary').format(net=total['net'], count=total['group_count'],
                                                  draw=total['draw_a'], injection=total['injection_a'])
                 for total in totals]
        duplicates = duplicate_terminal_groups(self.rows)
        if duplicates:
            lines.append(self.t('duplicate_hint').format(count=len(duplicates)))
        full_text = '\n'.join(lines) if lines else self.t('no_loads')
        self.current_summary.SetLabel(full_text)
        self.current_summary.SetToolTip(full_text)
        self.current_summary.Wrap(max(230, self.current_summary.GetParent().GetClientSize().width - 20))
        self.current_summary.InvalidateBestSize()
        self.current_summary.SetMinSize((-1, self.current_summary.GetBestSize().height))
        self.current_summary.SetForegroundColour('#a44b00' if duplicates else NAVY)
        self.current_summary.GetParent().Layout()

    def check_terminal_rows(self, rows):
        if not super().check_terminal_rows(rows):
            return False
        repeated = duplicate_terminal_groups(rows)
        if repeated:
            item = repeated[0]
            self.error(self.t('duplicate_group').format(first=item['first_index'] + 1,
                        second=item['duplicate_index'] + 1, kind=self.t(item['kind'] + '_mode'),
                        pads=', '.join(self.pad_by_id.get(i, {}).get('label', i) for i in item['pad_ids'])))
            return False
        return True

    def marker_pick(self, identifier):
        if self.process is not None:
            return
        identifier = identifier.get('identifier', identifier.get('id')) if isinstance(identifier, dict) else identifier
        for index, row in enumerate(self.rows):
            if row.get('identifier') == identifier:
                for selected in self.selected_row_indices():
                    self.terminals.Select(selected, False)
                self.terminals.Select(index)
                self.edit_row(index)
                return

    def edit_row(self, index):
        if not 0 <= index < len(self.rows) or self.process is not None:
            return
        row = self.rows[index]
        labels = ', '.join(self.pad_by_id[i]['label'] for i in row['pad_ids'])
        value = self.ask_value(row['kind'], labels, row['value'])
        if value is not None:
            row['value'] = value
            self.refresh_rows(); self.invalidate_result()

    def edit_selected(self, event=None):
        if self.process is not None:
            return
        if event is not None and event.GetEventType() == wx.EVT_LIST_ITEM_ACTIVATED.typeId:
            self.edit_row(event.GetIndex())
            return
        indices = self.selected_row_indices()
        if not indices:
            return
        if len(indices) == 1:
            self.edit_row(indices[0])
            return
        rows = [self.rows[index] for index in indices]
        kinds = {row['kind'] for row in rows}
        if len(kinds) != 1:
            self.error(self.t('mixed_kinds'))
            return
        same_value = all(row['value'] == rows[0]['value'] for row in rows)
        label = self.t('batch_value_prompt').format(count=len(rows)) + '\n\n' + self.t('batch_edit_hint').format(count=len(rows))
        value = self.ask_value(rows[0]['kind'], label, rows[0]['value'] if same_value else None)
        if value is not None:
            for row in rows:
                row['value'] = value
            self.refresh_rows()
            self.invalidate_result()

    def highlight_row(self, event=None):
        if self._refreshing_rows:
            return
        indices = self.selected_row_indices()
        self.canvas.set_selection([identifier for index in indices
                                   for identifier in self.rows[index]['pad_ids']
                                   if identifier not in self.point_contacts])
        selected_ids = {self.rows[index].get('identifier') for index in indices}
        for marker in self.canvas.markers:
            marker['selected'] = marker.get('identifier') in selected_ids
        self.canvas.Refresh(False)

    def remove_group(self, event=None):
        if self.process is not None:
            return
        indices = self.selected_row_indices()
        if indices:
            for index in reversed(indices):
                del self.rows[index]
            self.canvas.clear_selection()
            self.prune_contacts(); self.refresh_rows(); self.invalidate_result()

    def clear_groups(self, event=None):
        if self.process is not None:
            return
        self.canvas.clear_selection()
        self.rows.clear(); self.prune_contacts(); self.refresh_rows(); self.invalidate_result()

    def prune_contacts(self):
        keep = {i for row in self.rows for i in row['pad_ids']}
        for identifier in list(self.point_contacts):
            if identifier not in keep:
                self.point_contacts.pop(identifier)
                self.pad_by_id.pop(identifier, None)

    def invalidate_result(self, event=None):
        if getattr(self, 'result', None) is not None:
            self.result_dirty = True
            self.canvas.clear_overlay()
            self.stats.SetLabel(self.t('changed_case'))
            self.SetStatusText(self.t('changed_case'))
            self.update_analysis_notice()
        if event is not None:
            event.Skip()

    def find_reference(self, event=None):
        if self.layout_data and not self.canvas.focus_reference(self.search.GetValue().strip()):
            self.SetStatusText(self.t('not_found'))

    def scenario(self):
        data = super().scenario()
        used = {identifier for row in self.rows for identifier in row['pad_ids']}
        data['contacts'] = [contact for identifier, contact in self.point_contacts.items() if identifier in used]
        data['original_board_path'] = self.board_path
        if self.snapshot:
            data['snapshot'] = dict(self.snapshot)
        return data

    def analyze(self, event=None):
        self.persist_calculation_settings()
        if not self.verified() or not self.check_terminal_rows(self.rows):
            return
        case = self.scenario()
        if not ((case['sources'] and case['loads']) or case['heaters']):
            self.error(self.t('needs_case')); return
        source_nets = {self.pad_by_id[r['pad_ids'][0]]['net'] for r in case['sources']}
        load_nets = {self.pad_by_id[r['pad_ids'][0]]['net'] for r in case['loads']}
        if source_nets != load_nets:
            self.error(self.t('missing_pair') + ', '.join(sorted(source_nets ^ load_nets))); return
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PCBHeatmap' / 'runs'
        self.result_dir = base / (time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns())[-6:])
        self.result_dir.mkdir(parents=True, exist_ok=False)
        try:
            run_snapshot = create_snapshot(self.snapshot['path'] if self.snapshot else self.board_path,
                                           self.result_dir, expected_sha256=self.inspection['sha256'],
                                           original_path=self.board_path)
        except Exception as exc:
            self.error(exc)
            return
        case['snapshot'] = run_snapshot
        path = self.result_dir / 'scenario.json'
        path.write_text(json.dumps(case, indent=2, ensure_ascii=False), encoding='utf8')
        self.invalidate_result()
        self.start_worker('analyze', ['analyze', '--board', run_snapshot['path'], '--scenario', str(path),
                                    '--output-dir', str(self.result_dir), '--cell-mm', str(self.setting_controls['cell_mm'].GetValue()),
                                    '--max-cells', str(self.node_budget.GetValue())])

    def load_result(self, path):
        result = json.loads(Path(path).read_text(encoding='utf8'))
        if self.inspection and result.get('sha256') != self.inspection['sha256']:
            raise ValueError(self.t('changed'))
        with np.load(Path(path).parent / result.get('arrays_file', 'result.npz'), allow_pickle=False) as loaded:
            arrays = {name: np.array(loaded[name], copy=True) for name in loaded.files}
        diagnostic = result.get('analysis_kind') == 'dc_diagnostic'
        if diagnostic and (result.get('thermal_status') != 'unavailable' or 'temperature_c' in arrays):
            raise ValueError('A DC diagnostic must not contain a temperature map.')
        self.result, self.arrays = result, arrays
        self.result_dirty = False
        self.net.Set([str(net) for net in result.get('nets', [])])
        if self.net.GetCount():
            self.net.SetSelection(0)
        self.view_keys = (('board_view', 'density', 'drop', 'power') if diagnostic else
                          ('board_view', 'temperature', 'density', 'drop', 'power'))
        self.view.Set([self.t(key) for key in self.view_keys])
        self.view.SetSelection(self.view_keys.index('power' if diagnostic else 'temperature'))
        self.update_analysis_notice()
        self.refresh_result_notes()
        self.render_result()

    def refresh_result_notes(self):
        super().refresh_result_notes()
        if self.result:
            if self.is_dc_diagnostic():
                error = self.result.get('thermal_error', {})
                text = format_analysis_error(error.get('code'), error.get('details'), self.language)
                self.notes.AppendText('\n\n' + self.t('dc_notice').format(temperature=self.result['reference_temperature_c']) +
                                      '\n' + self.t('dc_incomplete') + ('\n\n' + text if text else ''))
            self.notes.AppendText('\n\n' + self.t('snapshot_hint') + '\nSHA-256: ' + self.result.get('sha256', ''))
            if self.result.get('snapshot'):
                self.notes.AppendText('\n' + str(self.result['snapshot'].get('captured_at', '')))

    def is_dc_diagnostic(self):
        return bool(self.result and self.result.get('analysis_kind') == 'dc_diagnostic')

    def update_analysis_notice(self):
        show = self.is_dc_diagnostic() and not self.result_dirty
        self.analysis_notice.Show(show)
        if show:
            self.analysis_notice.SetLabel(self.t('dc_notice').format(temperature=self.result['reference_temperature_c']))
            self.analysis_notice.SetOwnForegroundColour('#884500')
            self.analysis_notice.SetOwnBackgroundColour('#fff2cc')
            self.analysis_notice.Wrap(max(500, self.GetClientSize().width - 30))
            self.analysis_notice.InvalidateBestSize()
            self.analysis_notice.SetMinSize((-1, self.analysis_notice.GetBestSize().height))
        self.Layout()

    def render_result(self, event=None):
        layer = self.layer.GetSelection() - 1
        self.canvas.set_layer(layer)
        mode = self.view_keys[max(0, self.view.GetSelection())]
        self.net.Enable(mode in ('density', 'drop') and self.net.GetCount() > 0)
        if not self.result or self.result_dirty or mode == 'board_view':
            self.canvas.clear_overlay()
            if not self.result_dirty:
                self.stats.SetLabel('')
            return
        index = max(0, self.net.GetSelection())
        if mode == 'temperature':
            data, units = self.arrays.get('temperature_c'), '°C'
        elif mode == 'density':
            data, units = self.arrays.get(f'current_density_a_mm2__{index}'), 'A/mm²'
            voltage = self.arrays.get(f'voltage_v__{index}')
            if data is not None and voltage is not None:
                data = np.where(np.isfinite(voltage), data, np.nan)
        elif mode == 'drop':
            voltage = self.arrays.get(f'voltage_v__{index}')
            reference = self.result.get('source_voltages', self.result.get('source_voltages_v', {})).get(self.net.GetStringSelection(), 0)
            data, units = (None if voltage is None else np.abs(reference - voltage) * 1000), 'mV'
        else:
            joule = self.arrays.get('joule_w')
            data, units = (None if joule is None else joule / self.result['cell_mm'] ** 2), 'W/mm²'
        if data is None:
            self.canvas.clear_overlay(); return
        mask = np.asarray(self.arrays.get('board_mask', np.ones(data.shape[-2:], bool)), bool)
        finite = np.isfinite(data) & mask
        if mode == 'power' and 'copper' in self.arrays:
            finite &= self.arrays['copper'] > 0
        if not finite.any():
            self.canvas.clear_overlay(); return
        scale = (float(data[finite].min()), float(data[finite].max()))
        visible = np.where(finite[layer], data[layer], np.nan) if layer >= 0 else np.max(np.where(finite, data, -np.inf), axis=0)
        valid = mask & np.isfinite(visible)
        self.canvas.set_overlay(visible, valid, units,
                                (self.result['origin_x_mm'], self.result['origin_y_mm']), self.result['cell_mm'],
                                scale=scale, opacity=self.opacity.GetValue() / 100)
        summary = self.result.get('summaries', {})
        if self.is_dc_diagnostic():
            text = self.t('dc_summary').format(temperature=self.result['reference_temperature_c'], power=summary.get('joule_w', 0))
            text += '\n' + self.t('common_scale')
        else:
            hot = summary.get('hotspot', {})
            text = f"{self.t('hottest')}: {summary.get('max_temperature_c', 0):.2f} °C"
            if hot:
                text += f" · {hot.get('layer', '')} · X {hot.get('x_mm', 0):.2f}, Y {hot.get('y_mm', 0):.2f} mm"
            text += f"\n{self.t('total_heat')}: {summary.get('total_heat_w', 0):.4g} W · {self.t('common_scale')}"
        self.stats.SetLabel(text)
        self.stats.Wrap(max(250, self.stats.GetParent().GetClientSize().width - 300))
        self.stats.InvalidateBestSize()
        self.stats.GetParent().Layout()

    def save_case(self, event=None):
        if not self.verified():
            return
        with wx.FileDialog(self, self.t('save_case'), defaultFile='pcb-heatmap-case.json', wildcard='JSON (*.json)|*.json', style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                try:
                    self.write_case(dialog.GetPath())
                except Exception as exc:
                    self.error(exc)

    def write_case(self, path):
        target = Path(path).resolve()
        if target.suffix.lower() != '.json' or target == Path(self.board_path).resolve():
            raise ValueError(self.t('json_only'))
        data = self.scenario()
        data['cell_mm'] = self.setting_controls['cell_mm'].GetValue()
        data['max_cells'] = self.node_budget.GetValue()
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf8')

    def apply_case(self, data):
        if not self.inspection or data.get('expected_sha256') != self.inspection['sha256']:
            raise ValueError(self.t('case_error'))
        contacts = validate_contacts(data.get('contacts', []), self.inspection)
        meta = {pad['identifier']: pad for pad in self.inspection['pads']}
        meta.update({i: self.point_metadata(contact) for i, contact in contacts.items()})
        rows = []
        for key, kind, field in [('sources', 'source', 'voltage_v'), ('loads', 'load', 'current_a'), ('heaters', 'heat', 'power_w')]:
            for row in data.get(key, []):
                identifiers = row.get('pad_ids', [])
                value = float(row[field])
                if not identifiers or any(i not in meta for i in identifiers) or not math.isfinite(value):
                    raise ValueError(self.t('case_error'))
                if (kind == 'load' and value == 0) or (kind == 'heat' and value <= 0):
                    raise ValueError(self.t('case_error'))
                nets = {meta[i].get('net', '') for i in identifiers}
                if kind != 'heat' and ('' in nets or len(nets) != 1):
                    raise ValueError(self.t('single_net'))
                rows.append(dict(identifier=uuid.uuid4().hex, kind=kind, pad_ids=list(identifiers), value=value))
        if conflicting_terminal_ids(rows):
            raise ValueError(self.t('case_error'))
        settings = data.get('settings', {})
        if not isinstance(settings, dict):
            raise ValueError(self.t('case_error'))
        new_settings = {}
        for key, value in settings.items():
            if key in self.setting_controls:
                if key == 'substrate_k_z' and value is None:
                    continue
                if isinstance(value, bool):
                    raise ValueError(self.t('case_error'))
                number = float(value)
                control = self.setting_controls[key]
                if not math.isfinite(number) or not control.GetMin() <= number <= control.GetMax():
                    raise ValueError(self.t('case_error'))
                new_settings[key] = number
        # Older cases had one isotropic value under the historical fr4_k key.
        if settings.get('substrate_k_z') is None:
            new_settings['substrate_k_z'] = new_settings.get('fr4_k', self.setting_controls['fr4_k'].GetValue())
        material = settings.get('substrate_material', 'custom')
        if material not in self.material_ids:
            raise ValueError(self.t('case_error'))
        if 'cell_mm' in data:
            number = float(data['cell_mm'])
            if not math.isfinite(number) or not .025 <= number <= 2:
                raise ValueError(self.t('case_error'))
            new_settings['cell_mm'] = number
        budget = data.get('max_cells', self.node_budget.GetValue())
        if isinstance(budget, bool) or not isinstance(budget, int) or not 10000 <= budget <= 2000000:
            raise ValueError(self.t('case_error'))
        # Validate the entire case before replacing any current contacts/results.
        self.pad_by_id, self.point_contacts, self.rows = meta, contacts, rows
        self.active_source_net = next((meta[row['pad_ids'][0]]['net']
                                      for row in reversed(rows) if row['kind'] == 'source'), '')
        for key, value in new_settings.items():
            self.setting_controls[key].SetValue(value)
        self.material_choice.SetSelection(self.material_ids.index(material))
        self.update_material_hint()
        if 'max_cells' in data:
            self.node_budget.SetValue(budget)
        self.refresh_rows(); self.calculation_setting_changed()

    def load_case(self, event=None):
        if not self.verified():
            return
        with wx.FileDialog(self, self.t('load_case'), wildcard='JSON (*.json)|*.json', style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                try:
                    self.apply_case(json.loads(Path(dialog.GetPath()).read_text(encoding='utf-8-sig')))
                except Exception as exc:
                    self.error(exc)
