"""PCB-first local editor: visual terminals and aligned analysis overlays.

The PCB canvas is a saved-file snapshot. All edits in this window belong only
to the analysis scenario; the user's KiCad board is never changed.
"""
from __future__ import annotations

import copy
import json
import math
import os
import subprocess
import threading
from pathlib import Path
import time
import uuid

import numpy as np
import wx
import wx.lib.scrolledpanel as scrolled

from . import colormap, paths, theme, ui_state, widgets
from .board_view import BoardCanvas
from .contacts import validate_contacts
from .gui import (MainFrame, LightTextEntryDialog, apply_light_palette,
                  light_dialog_buttons, sha256, worker_python)
from .i18n import tr, format_analysis_error
from .model import (DISTRIBUTIONS, conflicting_terminal_ids,
                    duplicate_terminal_groups, load_totals, split_preview)
from .snapshot import create_snapshot
from .ui_controls import (LightButton, LightCheckBox, LightChoice, LightListCtrl,
                          LightSpinCtrl, LightSpinCtrlDouble)


TEXT = {
    'subtitle': ('Click your PCB to define inputs, loads and heat. View results on the same board.', 'Giriş, yük ve ısı noktalarını PCB üzerinde seç; sonuçları aynı kartın üzerinde gör.'),
    'select_mode': ('Select', 'Seç'),
    'source_mode': ('Source · V', 'Kaynak · V'),
    'load_mode': ('Load · A', 'Yük · A'),
    'heat_mode': ('Heat · W', 'Isı · W'),
    'fit': ('Fit', 'Sığdır'),
    'search_hint': ('Find component', 'Komponent bul'),
    'find': ('Find', 'Bul'),
    'board_view': ('Layout', 'Yerleşim'),
    'case_tab': ('Inputs and loads', 'Girişler ve yükler'),
    'settings_tab': ('Calculation settings', 'Hesap ayarları'),
    'notes_tab': ('Model notes', 'Model notları'),
    'edit': ('Edit value', 'Değeri düzenle'),
    'multiselect_hint': ('List: Ctrl+click adds rows; Shift+click selects a range.', 'Liste: Ctrl+tık ile satır ekle; Shift+tık ile aralık seç.'),
    'batch_edit_hint': ('Assign this value to EACH of the {count} selected rows. Rows remain separate; their totals are added normally.', 'Bu değer seçili {count} satırın HER BİRİNE atanır. Satırlar ayrı kalır; toplamları normal şekilde toplanır.'),
    'mixed_kinds': ('Select rows of the same kind to edit their values together. You can remove different kinds together.', 'Değerleri birlikte düzenlemek için aynı türde satırlar seç. Farklı türleri birlikte kaldırabilirsin.'),
    'batch_value_prompt': ('{count} selected rows', '{count} seçili satır'),
    'ok': ('OK', 'Tamam'),
    'group': ('Terminal', 'Uç'),
    'empty_selection': ('Select pads on the board. Ctrl+click groups pads. Middle/right drag pans; the wheel zooms.', 'Kart üzerinde pad seç. Ctrl+tık ile padleri grupla. Orta/sağ tuşla sürükle, tekerlekle yakınlaş.'),
    'selected_count': ('Selected: {count} pads · {net}', 'Seçili: {count} pad · {net}'),
    'hint_select': ('Click a pad to inspect it; Ctrl+click to select a group. Choose Source, Load or Heat to enter values on the board.', 'Padi tıklayarak incele; Ctrl+tık ile grup seç. Kartın üzerinde değer girmek için Kaynak, Yük veya Isı aracını seç.'),
    'hint_source': ('Click the input pad or copper where current enters; enter its voltage. Sources are green.', 'Akımın girdiği giriş padini veya bakırı tıkla; gerilimini gir. Kaynaklar yeşil gösterilir.'),
    'hint_load': ('Click different receiving pads/copper on the same net; enter the group current. Loads are orange.', 'Aynı ağda akımı alacak farklı padleri/bakırı tıkla; grup akımını gir. Yükler turuncu gösterilir.'),
    'hint_heat': ('Click a component pad or board location; enter its own heat loss in watts. Optional: copper heating is automatic.', 'Komponent padini veya kart konumunu tıkla; parçanın kendi kaybını watt olarak gir. İsteğe bağlıdır; bakır ısınması otomatik hesaplanır.'),
    'no_copper': ('Click a pad or copper on the visible layer. Use Heat for a board location without a net.', 'Görünen katmandaki bir padi veya bakırı tıkla. Ağsız kart konumlarında Isı aracını kullan.'),
    'no_matching_pads': ('{reference}: no visible pads on {net}. Choose another component or change Component selection net.', '{reference}: {net} ağında görünen pad yok. Başka komponent seç veya Komponent seçim ağını değiştir.'),
    'references': ('References', 'Referanslar'),
    'visibility': ('Layers', 'Katmanlar'),
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
    'power': ('Power', 'Güç'),
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


PRESETS = {'fast': (0.5, 1e-6), 'balanced': (0.35, 1e-7), 'fine': (0.25, 1e-8)}
PRESET_ORDER = ('fast', 'balanced', 'fine', 'custom')
PRECISIONS = {'fast': 1e-6, 'balanced': 1e-7, 'fine': 1e-8}
PRECISION_ORDER = ('fast', 'balanced', 'fine')

TEXT.update({
    'section_board': ('Board', 'Kart'),
    'section_inputs': ('Inputs', 'Girişler'),
    'section_model': ('Model', 'Model'),
    'section_results': ('Results', 'Sonuçlar'),
    'section_report': ('Report', 'Rapor'),
    'board_hint': ('Open or reload the saved PCB. Analysis reads this file only; the board is never modified.',
                   'Kaydedilmiş PCB’yi aç veya yenile. Analiz yalnız bu dosyayı okur; kart değiştirilmez.'),
    'inputs_hint': ('Pick pads, then enter one total for the group.',
                    'Padleri seç, sonra grup için tek toplam gir.'),
    'model_hint': ('Environment, material, mesh and limits. Edits invalidate the current result.',
                   'Ortam, malzeme, ağ ve sınırlar. Değişiklikler mevcut sonucu geçersiz kılar.'),
    'results_hint': ('What the analysis covered: nets, copper area, vias, cells and timing.',
                     'Analizin kapsadıkları: ağlar, bakır alanı, vialar, hücreler ve süre.'),
    'report_hint': ('Model notes, assumptions and warnings. Copy or save the report.',
                    'Model notları, varsayımlar ve uyarılar. Raporu kopyala veya kaydet.'),
    'appearance': ('Appearance', 'Görünüm'),
    'appearance_auto': ('Follow desktop', 'Masaüstünü izle'),
    'appearance_dark': ('Dark', 'Koyu'),
    'appearance_light': ('Light', 'Açık'),
    'appearance_applied': ('Appearance updated', 'Görünüm güncellendi'),
    'ramp': ('Colour scale', 'Renk ölçeği'),
    'ramp_rainbow': ('Rainbow (release default)', 'Gökkuşağı (sürüm varsayılanı)'),
    'ramp_turbo': ('Turbo', 'Turbo'),
    'ramp_viridis': ('Viridis (colour-blind safe)', 'Viridis (renk körü dostu)'),
    'ramp_inferno': ('Inferno', 'Inferno'),
    'ramp_magma': ('Magma', 'Magma'),
    'ramp_gray': ('Greyscale', 'Gri tonlama'),
    'threads': ('CPU threads (0 = auto)', 'İşlemci iş parçacığı (0 = otomatik)'),
    'threads_hint': ('Applies to dense linear algebra only; the mesh solver itself runs on one core.',
                     'Yalnız yoğun doğrusal cebir için geçerlidir; ağ çözücüsü tek çekirdekte çalışır.'),
    'threads_used': ('Threads', 'İş parçacığı'),
    'cpu_cores': ('CPU cores', 'İşlemci çekirdeği'),
    'stackup': ('Layer thickness', 'Katman kalınlığı'),
    'results_empty': ('No result yet. Define inputs and run the analysis.',
                      'Henüz sonuç yok. Girişleri tanımla ve analizi çalıştır.'),
    'peak_temperature': ('Peak temperature', 'En yüksek sıcaklık'),
    'hotspot': ('Hotspot', 'Sıcak nokta'),
    'energy_residual': ('Thermal energy residual', 'Isıl enerji artığı'),
    'per_net': ('Nets', 'Ağlar'),
    'draw': ('draw', 'çekilen'),
    'loss': ('copper loss', 'bakır kaybı'),
    'copper_area': ('Copper area', 'Bakır alanı'),
    'vias': ('Vias', 'Via'),
    'via_worst': ('worst via', 'en yüksek via'),
    'cells': ('cells', 'hücre'),
    'iterations': ('iterations', 'iterasyon'),
    'preconditioner': ('preconditioner', 'ön koşullayıcı'),
    'warnings': ('Warnings', 'Uyarılar'),
    'working': ('Working…', 'Çalışıyor…'),
    'done': ('Done', 'Tamam'),
    'split': ('Split…', 'Bölüşüm…'),
    'split_rule': ('Split rule', 'Bölüşüm kuralı'),
    'split_per_pad': ('Equal per pad', 'Pad başına eşit'),
    'split_area': ('By copper area', 'Bakır alanına göre'),
    'split_applied': ('{count} group(s) updated: {rule}.', '{count} grup güncellendi: {rule}.'),
    'split_needs_group': ('Select a load row with two or more pads to change its split rule.',
                          'Bölüşüm kuralını değiştirmek için iki veya daha fazla padli bir yük satırı seç.'),
    'group_pads': ('{count} pads · {net}', '{count} pad · {net}'),
    'group_total_hint': ('This is the total for the whole group; it is not multiplied by the number of pads.',
                         'Bu değer grubun toplamıdır; pad sayısıyla çarpılmaz.'),
    'copy_report': ('Copy', 'Kopyala'),
    'save_report': ('Save report…', 'Raporu kaydet…'),
    'report_saved': ('Report saved.', 'Rapor kaydedildi.'),
    'copied': ('Report copied to the clipboard.', 'Rapor panoya kopyalandı.'),
    'ready_saved': ('Saved PCB loaded', 'Kaydedilmiş PCB yüklendi'),
    'ready_zones': ('{filled} of {zones} copper zones filled', '{zones} bakır dolgunun {filled} tanesi dolu'),
    'ready_zones_none': ('No filled copper zones to check', 'Denetlenecek dolgulu bakır yok'),
    'ready_runtime': ('Python runtime: {path}', 'Python çalışma zamanı: {path}'),
    'ready_runs': ('Run folder: {path}', 'Çalışma klasörü: {path}'),
    'runs_unwritable': ('Could not create a run folder under {path}', '{path} altında çalışma klasörü oluşturulamadı'),
    'board_chip': ('{file} · {layers} layers · {pads} pads · {nets} nets',
                   '{file} · {layers} katman · {pads} pad · {nets} ağ'),
    'list_hint': ('Ctrl+click adds pads, Shift+drag selects a rectangle, double-click a row to edit it.',
                  'Ctrl+tık pad ekler, Shift+sürükle dikdörtgen seçer, satıra çift tıkla düzenle.'),
    'assign_source': ('Source…', 'Kaynak…'),
    'no_selection': ('No pads selected', 'Pad seçilmedi'),
    'terminals_empty': ('No terminals yet.\nSelect pads on the board, then choose Source, Load or Heat.',
                        'Henüz uç yok.\nKartta pad seç, sonra Kaynak, Yük veya Isı seç.'),
    'assign_load': ('Load…', 'Yük…'),
    'assign_heat': ('Heat…', 'Isı…'),
    'presets_group': ('Speed and precision', 'Hız ve duyarlılık'),
    'preset_fast': ('Fast (0.5 mm cells)', 'Hızlı (0,5 mm hücre)'),
    'preset_balanced': ('Balanced (0.35 mm cells)', 'Dengeli (0,35 mm hücre)'),
    'preset_fine': ('Fine (0.25 mm cells)', 'İnce (0,25 mm hücre)'),
    'preset_custom': ('Custom', 'Özel'),
    'hint_preset': ('Trade mesh detail against run time. Presets also set the solver tolerance.',
                    'Ağ ayrıntısını çalışma süresiyle dengele. Hazır ayarlar çözücü toleransını da belirler.'),
    'hint_preset_fast': ('Coarse mesh and 1e-6 tolerance. Best for a first look; refine before reporting values.',
                         'Kaba ağ ve 1e-6 tolerans. İlk bakış için; değer bildirmeden önce incelt.'),
    'hint_preset_balanced': ('0.35 mm cells and 1e-7 tolerance. A good default for everyday inspection.',
                             '0,35 mm hücre ve 1e-7 tolerans. Günlük inceleme için iyi varsayılan.'),
    'hint_preset_fine': ('0.25 mm cells and 1e-8 tolerance. Slowest; use for final checks.',
                         '0,25 mm hücre ve 1e-8 tolerans. En yavaş; son kontroller için.'),
    'hint_preset_custom': ('Cell size and tolerance were edited by hand.', 'Hücre boyu ve tolerans elle değiştirildi.'),
    'precision': ('Solver precision', 'Çözücü duyarlılığı'),
    'precision_fast': ('Fast (1e-6)', 'Hızlı (1e-6)'),
    'precision_balanced': ('Balanced (1e-7)', 'Dengeli (1e-7)'),
    'precision_fine': ('Fine (1e-8)', 'İnce (1e-8)'),
    'hint_tolerance': ('Relative residual target of the iterative solver. Tighter values cost iterations; 1e-7 is usually far below engineering relevance.',
                       'Yinelemeli çözücünün bağıl artık hedefi. Sıkı değerler daha çok iterasyon ister; 1e-7 genelde mühendislik öneminin çok altındadır.'),
    'environment_group': ('Environment', 'Ortam'),
    'substrate_group': ('Substrate physics', 'Taban fiziği'),
    'mesh_group': ('Mesh and solver', 'Ağ ve çözücü'),
    'limits_group': ('Warning limits', 'Uyarı sınırları'),
    'copper_group': ('Copper foil thickness', 'Bakır folyo kalınlığı'),
    'hint_copper': ('Foil thickness per copper layer in µm. The board stackup value is {stackup} µm; editing here overrides it for this scenario without changing the PCB.',
                    'Katman başına bakır folyo kalınlığı (µm). Kart yığını değeri {stackup} µm; buradaki değişiklik PCB’yi değiştirmeden bu senaryo için geçerlidir.'),
    'copper_needs_board': ('Open a saved PCB to read its copper layers.', 'Bakır katmanlarını okumak için kayıtlı PCB aç.'),
    'hint_material': ('Choosing a material name is a label only; enter datasheet conductivities below.',
                      'Malzeme adı yalnızca etikettir; aşağıya veri sayfası iletkenliklerini gir.'),
    'hint_ambient': ('Still-air temperature around the board.', 'Kartın çevresindeki durgun hava sıcaklığı.'),
    'hint_convection': ('Surface-to-air convection coefficient. 10 W/m²K is weak natural convection; cable and heatsink paths are not modelled.',
                        'Yüzeyden havaya taşınım katsayısı. 10 W/m²K zayıf doğal taşınımdır; kablo ve soğutucu yolları modellenmez.'),
    'hint_substrate_xy': ('In-plane conductivity: how heat spreads along the board.', 'Düzlem içi iletkenlik: ısının kart boyunca yayılımı.'),
    'hint_substrate_z': ('Through-plane conductivity: how heat moves between layers.', 'Katmanlar arası iletkenlik: ısının katmanlar arasında geçişi.'),
    'hint_copper_k': ('Thermal conductivity of copper at the working temperature.', 'Çalışma sıcaklığında bakırın ısıl iletkenliği.'),
    'hint_grid': ('Mesh cell edge in millimetres. Smaller cells resolve narrow tracks and pads but increase run time roughly with the square of the refinement.',
                  'Ağ hücresi kenarı (mm). Küçük hücreler ince yolları ve padleri çözer ama çalışma süresini yaklaşık karesiyle artırır.'),
    'hint_plating': ('Copper wall thickness of plated via barrels. It sets the via resistance and its heat path between layers.',
                     'Kaplamalı via gövdesinin bakır duvar kalınlığı. Via direncini ve katmanlar arası ısı yolunu belirler.'),
    'hint_budget': ('Upper bound on mesh cells; a run that would exceed it is refused instead of exhausting memory.',
                    'Ağ hücrelerinin üst sınırı; aşacak bir çalışma belleği tüketmek yerine reddedilir.'),
    'hint_limits': ('Only used to flag results that exceed these markers; they are not a validated rating.',
                    'Yalnızca bu işaretleri aşan sonuçları belirtmek için kullanılır; doğrulanmış bir sınır değildir.'),
    'hint_ramp': ('Colour scale for the maps. Changing it recolours the current result without re-running the solve.',
                  'Haritaların renk ölçeği. Değiştirmek çözümü yeniden çalıştırmadan sonucu renklendirir.'),
    'history': ('Run history', 'Çalışma geçmişi'),
    'history_empty': ('No completed runs in this window yet.',
                      'Bu pencerede henüz tamamlanmış çalışma yok.'),
    'select_prompt': ('Click a pad, or Shift-drag around several.',
                      'Bir pade tıkla veya birkaçı için Shift+sürükle.'),
    'multi_hint': ('These pads form one group; the value is the group total.',
                   'Bu padler tek grup; girilen değer grup toplamıdır.'),
    'single_pad_hint': ('Ready to assign', 'Atamaya hazır'),
    'no_net': ('No net', 'Ağ yok'),
    'confirm_remove': ('Remove {count} selected terminal rows?',
                       'Seçili {count} uç satırı kaldırılsın mı?'),
    'undo_done': ('Undid the last change.', 'Son değişiklik geri alındı.'),
    'redo_done': ('Redid the last change.', 'Son değişiklik yeniden yapıldı.'),
    'set_as_source': ('Set as source…', 'Kaynak olarak ata…'),
    'set_as_load': ('Set as load…', 'Yük olarak ata…'),
    'set_as_heat': ('Set as heat…', 'Isı olarak ata…'),
    'add_to_selection': ('Add to selection', 'Seçime ekle'),
    'clear_selection': ('Clear selection', 'Seçimi temizle'),
    'hide_markers': ('Hide source/load markers', 'Kaynak/yük işaretlerini gizle'),
    'show_markers': ('Show source/load markers', 'Kaynak/yük işaretlerini göster'),
    'markers_shown': ('Markers shown.', 'İşaretler gösteriliyor.'),
    'markers_hidden': ('Markers hidden; the whole map is visible.',
                       'İşaretler gizlendi; haritanın tamamı görünür.'),
    'markers': ('Source/load markers', 'Kaynak/yük işaretleri'),
})


class _SegmentProxy:
    """Compatibility facade so a segmented control keeps the old button API."""

    def __init__(self, control, index):
        self.control = control
        self.index = index

    def SetValue(self, value):
        if value:
            self.control.SetSelection(self.index)
            self.control.emit()
        elif self.control.GetSelection() == self.index:
            self.control.SetSelection(-1)
            self.control.Refresh()

    def GetValue(self):
        return self.control.GetSelection() == self.index

    def GetLabel(self):
        labels = self.control.GetStrings()
        return labels[self.index] if 0 <= self.index < len(labels) else ''

    def SetLabel(self, label):
        labels = self.control.GetStrings()
        if 0 <= self.index < len(labels):
            labels[self.index] = str(label)
            self.control.Set(labels, self.control.GetSelection())

    def Enable(self, enable=True):
        return self.control.Enable(enable)

    def Disable(self):
        return self.control.Enable(False)


class Sections(wx.Panel):
    """Side-panel pages with the small notebook API the frame historically used."""

    def __init__(self, parent, labels=(), on_change=None):
        super().__init__(parent, style=wx.BORDER_NONE)
        self._labels = [str(label) for label in labels]
        self._on_change = on_change
        self._book = wx.Simplebook(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._book, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self.SetMinSize((self.FromDIP(260), -1))

    def AddPage(self, page, text, select=False):
        page.Reparent(self._book)
        result = self._book.AddPage(page, text, select)
        if len(self._labels) < self._book.GetPageCount():
            self._labels.append(str(text))
        return result

    def SetSelection(self, index):
        if not 0 <= index < self._book.GetPageCount():
            return self._book.GetSelection()
        current = self._book.GetSelection()
        if current != index:
            self._book.ChangeSelection(index)
            if self._on_change:
                self._on_change(index)
        return current

    def GetSelection(self):
        return self._book.GetSelection()

    def SetPageText(self, index, text):
        self._labels[index] = str(text)
        self._book.SetPageText(index, text)
        return True

    def GetPageText(self, index):
        return self._labels[index] if 0 <= index < len(self._labels) else ''

    def GetPageCount(self):
        return self._book.GetPageCount()

    def GetPage(self, index):
        return self._book.GetPage(index)

    def GetCurrentPage(self):
        return self._book.GetCurrentPage()


class AssignmentDialog(wx.Dialog):
    """One group total, an explicit split rule and a live per-pad preview."""

    def __init__(self, parent, title, description, value='', kind='load',
                 identifiers=(), pads=None, distribution='per_pad', rule_only=False):
        super().__init__(parent, title=title)
        self.kind = kind
        self.identifiers = list(identifiers)
        self.pads = pads or {}
        self.rule_only = rule_only
        self._values = []
        sizer = wx.BoxSizer(wx.VERTICAL)
        head = wx.StaticText(self, label=description)
        head.Wrap(self.FromDIP(460))
        sizer.Add(head, 0, wx.ALL | wx.EXPAND, self.FromDIP(14))
        if not rule_only:
            prompt = wx.StaticText(self, label=parent.t('source_value' if kind == 'source'
                                                       else 'load_value' if kind == 'load'
                                                       else 'heat_value'))
            sizer.Add(prompt, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, self.FromDIP(14))
            self.editor = wx.TextCtrl(self, value=str(value or ''), style=wx.TE_PROCESS_ENTER)
            self.editor.SetMinSize((self.FromDIP(360), -1))
            sizer.Add(self.editor, 0, wx.ALL | wx.EXPAND, self.FromDIP(14))
        self.rule_choice = None
        self.preview = None
        if kind == 'load' and len(self.identifiers) > 1:
            rule_row = wx.BoxSizer(wx.HORIZONTAL)
            caption = wx.StaticText(self, label=parent.t('split_rule'))
            rule_row.Add(caption, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(8))
            self.rule_choice = LightChoice(self, choices=[parent.t('split_per_pad'),
                                                          parent.t('split_area')],
                                           size=(self.FromDIP(190), self.FromDIP(28)))
            self.rule_choice.SetSelection(0 if distribution != 'area' else 1)
            self.rule_choice.Bind(wx.EVT_CHOICE, self.refresh_preview)
            rule_row.Add(self.rule_choice, 1, wx.EXPAND)
            sizer.Add(rule_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(14))
            self.preview = wx.StaticText(self, label='')
            self.preview.Wrap(self.FromDIP(460))
            sizer.Add(self.preview, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                      self.FromDIP(14))
        hint = wx.StaticText(self, label=parent.t('group_total_hint'))
        hint.Wrap(self.FromDIP(460))
        sizer.Add(hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(14))
        sizer.Add(light_dialog_buttons(self, parent), 0, wx.ALL | wx.ALIGN_RIGHT, self.FromDIP(14))
        self.SetSizerAndFit(sizer)
        theme.apply_palette(self, parent.palette)
        self.CentreOnParent()
        if self.rule_choice is not None:
            self.refresh_preview()
        if not rule_only:
            self.editor.SetFocus()
            self.editor.SetSelection(-1, -1)
            self.editor.Bind(wx.EVT_TEXT, self.refresh_preview)

    def current_distribution(self):
        if self.rule_choice is None:
            return 'area'
        return 'per_pad' if self.rule_choice.GetSelection() == 0 else 'area'

    def refresh_preview(self, event=None):
        if self.preview is None:
            return
        try:
            total = float((self.editor.GetValue() if hasattr(self, 'editor') else '0')
                          .strip().replace(',', '.'))
        except (ValueError, AttributeError):
            total = 0.0
        records = split_preview(self.pads, self.identifiers, self.current_distribution(), total)
        lines = []
        for record in records:
            lines.append(f"{record['label']} · {record['value']:.4g} "
                         f"({record['share'] * 100:.1f}%)")
        self.preview.SetLabel('\n'.join(lines[:12]))
        self.preview.Wrap(self.FromDIP(460))
        self.preview.GetParent().Layout()

    def answer(self):
        if self.rule_only:
            return None, self.current_distribution()
        try:
            value = float(self.editor.GetValue().strip().replace(',', '.'))
        except ValueError:
            return None, self.current_distribution()
        return value, self.current_distribution()


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
        self._status_text = ''
        self.section_headings = []
        self.run_history = []
        self._undo_stack = []
        self._redo_stack = []
        self._suspend_undo = False
        self._editing_row = None
        self._analysis_session = None
        state_path = (Path(preferences_path).with_name('ui-state.json')
                      if preferences_path else None)
        self.ui_state = ui_state.load_ui_state(state_path)
        self.palette = theme.load_palette(self.ui_state.get('appearance', 'auto'),
                                          ramp=self.ui_state.get('ramp', 'rainbow'))
        super().__init__(board_path, pcb_context, preferences_path)
        self.SetSize(self._fitted_size())
        self.SetMinSize((self.FromDIP(1024), self.FromDIP(700)))
        # GTK applies a pre-map resize only once the window is realised, so a
        # persisted size is repeated after the first idle to actually land.
        self.Bind(wx.EVT_CHAR_HOOK, self._global_key)
        wx.CallAfter(self._apply_saved_size)

    def _fitted_size(self):
        """Persisted size, clamped to the display so the window never opens off-screen."""
        width = int(self.ui_state.get('width', 1480))
        height = int(self.ui_state.get('height', 920))
        try:
            area = wx.Display(0).GetClientArea()
            width = min(width, max(self.FromDIP(1024), area.width - self.FromDIP(40)))
            height = min(height, max(self.FromDIP(700), area.height - self.FromDIP(80)))
        except Exception:
            pass
        return wx.Size(width, height)

    def _apply_saved_size(self):
        if self.IsBeingDeleted():
            return
        self.SetSize(self._fitted_size())

    def t(self, key):
        pair = TEXT.get(key)
        return pair[1 if self.language == 'tr' else 0] if pair else tr(key, self.language)

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #
    def _build(self):
        palette = self.palette
        self.SetBackgroundColour(palette.bg)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self._build_top_bar(), 0, wx.EXPAND)
        outer.Add(widgets.Divider(self, palette.divider), 0, wx.EXPAND)
        body = wx.BoxSizer(wx.HORIZONTAL)
        self.rail = widgets.ToolRail(self, [
            ('board', 'board', self.t('section_board')),
            ('inputs', 'bolt', self.t('section_inputs')),
            ('model', 'gear', self.t('section_model')),
            ('results', 'chart', self.t('section_results')),
            ('report', 'document', self.t('section_report')),
        ], on_select=self.show_section)
        body.Add(self.rail, 0, wx.EXPAND)
        self.splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        self.splitter.SetMinimumPaneSize(self.FromDIP(300))
        self.section_keys = ('board', 'inputs', 'model', 'results', 'report')
        labels = [self.t('section_' + key) for key in self.section_keys]
        self.sections = Sections(self.splitter, labels, on_change=self._section_changed)
        self.sidebar_notebook = self.sections
        self.pages = [
            self._build_board_page(self.sections),
            self._build_inputs_page(self.sections),
            self._build_model_page(self.sections),
            self._build_results_page(self.sections),
            self._build_report_page(self.sections),
        ]
        for page, label in zip(self.pages, labels):
            self.sections.AddPage(page, label)
        right = self._build_canvas_panel(self.splitter)
        width = max(self.FromDIP(260), min(int(self.ui_state['splitter']), self.FromDIP(620)))
        self.splitter.SplitVertically(self.sections, right, width)
        body.Add(self.splitter, 1, wx.EXPAND)
        outer.Add(body, 1, wx.EXPAND)
        outer.Add(widgets.Divider(self, palette.divider), 0, wx.EXPAND)
        outer.Add(self._build_action_bar(), 0, wx.EXPAND)
        self.SetSizer(outer)
        self.SetMinSize((self.FromDIP(1024), self.FromDIP(700)))
        self.apply_theme()
        section = self.section_keys.index(self.ui_state.get('section', 'inputs')) \
            if self.ui_state.get('section') in self.section_keys else 1
        self.rail.select(self.section_keys[section])
        self.sections.SetSelection(section)
        self.busy(False)

    def _build_top_bar(self):
        palette = self.palette
        bar = wx.Panel(self)
        bar.SetBackgroundColour(palette.header)
        bar.SetMinSize((-1, self.FromDIP(50)))
        row = wx.BoxSizer(wx.HORIZONTAL)
        icon = wx.StaticBitmap(bar, bitmap=wx.Bitmap(
            str(Path(__file__).with_name('toolbar-24.png')), wx.BITMAP_TYPE_PNG))
        row.Add(icon, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, self.FromDIP(12))
        title = wx.StaticText(bar, label='PCB Heatmap')
        title.SetFont(widgets.ui_font(12, wx.FONTWEIGHT_BOLD))
        title.SetForegroundColour(wx.Colour(palette.text))
        row.Add(title, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(14))
        self.board_chip = wx.StaticText(bar, label=self.t('no_board'),
                                        style=wx.ST_ELLIPSIZE_END)
        self.board_chip.SetForegroundColour(wx.Colour(palette.muted))
        row.Add(self.board_chip, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(10))
        self.status_pill = widgets.Pill(bar, self.t('ready'), 'muted')
        row.Add(self.status_pill, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(10))
        self.appearance_button = widgets.IconButton(bar, 'gear', self.t('appearance'),
                                                    size=(self.FromDIP(32), self.FromDIP(32)))
        self.appearance_button.Bind(wx.EVT_BUTTON, self.show_appearance_menu)
        row.Add(self.appearance_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(4))
        self.language_choice = LightChoice(bar, choices=['English', 'Türkçe'],
                                           size=(self.FromDIP(104), self.FromDIP(30)))
        self.language_choice.SetSelection(0)
        self.language_choice.Bind(wx.EVT_CHOICE, self.change_language)
        row.Add(self.language_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(4))
        self.help_button = widgets.IconButton(bar, 'help', self.t('usage'),
                                              size=(self.FromDIP(32), self.FromDIP(32)))
        self.help_button.Bind(wx.EVT_BUTTON, self.show_usage)
        row.Add(self.help_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(10))
        bar.SetSizer(row)
        return bar

    def _page_heading(self, parent, title_key, hint_key=None):
        panel = wx.Panel(parent)
        panel.SetBackgroundColour(self.palette.panel)
        sizer = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(panel, label=self.t(title_key))
        title.SetFont(widgets.ui_font(12, wx.FONTWEIGHT_BOLD))
        sizer.Add(title, 0, wx.EXPAND)
        self.section_headings.append((title, title_key))
        if hint_key:
            hint = wx.StaticText(panel, label=self.t(hint_key))
            hint.SetForegroundColour(wx.Colour(self.palette.muted))
            hint.Wrap(self.FromDIP(300))
            self.bound_text.append((hint, hint_key))
            sizer.Add(hint, 0, wx.TOP | wx.EXPAND, self.FromDIP(4))
        panel.SetSizer(sizer)
        return panel

    def _push(self, parent, key, handler, role='secondary', glyph=None, width=76):
        button = widgets.PushButton(parent, self.t(key), role=role, glyph=glyph,
                                    width=width,
                                    size=(self.FromDIP(width), self.FromDIP(34)))
        button.ApplyPalette(self.palette) if hasattr(button, 'ApplyPalette') else None
        self.bound_text.append((button, key))
        button.Bind(wx.EVT_BUTTON, handler)
        return button

    def _build_board_page(self, parent):
        page = wx.Panel(parent)
        page.SetBackgroundColour(self.palette.panel)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._page_heading(page, 'section_board', 'board_hint'), 0,
                  wx.ALL | wx.EXPAND, self.FromDIP(12))
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.open_button = self._push(page, 'browse', self.browse, glyph='folder')
        self.reload_button = self._push(page, 'reload', self.reload)
        row.Add(self.open_button, 1, wx.RIGHT, self.FromDIP(6))
        row.Add(self.reload_button, 1)
        sizer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(12))
        self.board_label = wx.StaticText(page, label=self.t('no_board'))
        self.board_label.SetForegroundColour(wx.Colour(self.palette.muted))
        self.board_label.Wrap(self.FromDIP(300))
        sizer.Add(self.board_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(12))
        self.readiness = wx.StaticText(page, label='')
        self.readiness.Wrap(self.FromDIP(300))
        sizer.Add(self.readiness, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(12))
        note = self.label(page, 'saved_only')
        note.SetForegroundColour(wx.Colour(self.palette.muted))
        note.Wrap(self.FromDIP(300))
        sizer.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(12))
        sizer.AddStretchSpacer()
        page.SetSizer(sizer)
        return page

    def _build_inputs_page(self, parent):
        page = wx.Panel(parent)
        page.SetBackgroundColour(self.palette.panel)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._page_heading(page, 'section_inputs', 'inputs_hint'), 0,
                  wx.ALL | wx.EXPAND, self.FromDIP(10))
        self.mode_keys = ('select', 'source', 'load', 'heat')
        self.mode_control = widgets.SegmentedControl(
            page, [self.t(key + '_mode') for key in self.mode_keys],
            on_select=lambda index: self.choose_mode(self.mode_keys[max(0, index)]),
            max_width=self.FromDIP(310))
        self.mode_control.ApplyPalette(self.palette)
        self.mode_buttons = {key: _SegmentProxy(self.mode_control, index)
                             for index, key in enumerate(self.mode_keys)}
        sizer.Add(self.mode_control, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(12))
        # The same sentence is shown next to the board where the action happens.
        self.mode_hint = wx.StaticText(page, label=self.t('hint_select'))
        self.mode_hint.SetForegroundColour(wx.Colour(self.palette.muted))
        self.mode_hint.Hide()

        self.section_strip = wx.Panel(page)
        self.section_strip.SetBackgroundColour(self.palette.panel_alt)
        strip = wx.BoxSizer(wx.VERTICAL)
        self.selection_info = wx.StaticText(self.section_strip, label=self.t('no_selection'))
        self.selection_info.SetFont(widgets.ui_font(None, wx.FONTWEIGHT_BOLD))
        self.selection_info.Wrap(self.FromDIP(290))
        strip.Add(self.selection_info, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND,
                  self.FromDIP(10))
        self.selection_detail = wx.StaticText(self.section_strip, label=self.t('select_prompt'))
        self.selection_detail.SetForegroundColour(wx.Colour(self.palette.muted))
        self.selection_detail.Wrap(self.FromDIP(290))
        strip.Add(self.selection_detail, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND,
                  self.FromDIP(3))
        assign = wx.BoxSizer(wx.HORIZONTAL)
        self.assign_buttons = {}
        for key, kind in (('assign_source', 'source'), ('assign_load', 'load'),
                          ('assign_heat', 'heat')):
            button = widgets.PushButton(self.section_strip, self.t(key),
                                        size=(self.FromDIP(88), self.FromDIP(30)))
            button.SetFont(widgets.ui_font(None))
            button.Bind(wx.EVT_BUTTON, lambda event, value=kind: self.assign_selection(value))
            self.bound_text.append((button, key))
            self.assign_buttons[kind] = button
            assign.Add(button, 1, wx.RIGHT, self.FromDIP(4))
        strip.Add(assign, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, self.FromDIP(8))
        self.group_note = wx.StaticText(self.section_strip, label=self.t('group_total_hint'))
        self.group_note.SetForegroundColour(wx.Colour(self.palette.muted))
        self.group_note.Wrap(self.FromDIP(290))
        self.group_note.Hide()
        strip.Add(self.group_note, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(8))
        self.section_strip.SetSizer(strip)
        sizer.Add(self.section_strip, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(10))

        self.source_net_row = wx.Panel(page)
        self.source_net_row.SetBackgroundColour(self.palette.panel)
        net_row = wx.BoxSizer(wx.HORIZONTAL)
        caption = self.label(self.source_net_row, 'source_net')
        caption.SetForegroundColour(wx.Colour(self.palette.muted))
        net_row.Add(caption, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(6))
        self.source_net = LightChoice(self.source_net_row, choices=[self.t('no_source_net')])
        self.source_net.SetSelection(0)
        self.source_net.Bind(wx.EVT_CHOICE, self.change_source_net)
        net_row.Add(self.source_net, 1, wx.EXPAND)
        self.source_net_row.SetSizer(net_row)
        self.source_net_row.Hide()
        sizer.Add(self.source_net_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(12))

        self.terminals = LightListCtrl(page, style=wx.LC_REPORT | wx.LC_EDIT_LABELS)
        for key, width in (('kind', 54), ('group', 146), ('value', 82)):
            self.terminals.InsertColumn(self.terminals.GetColumnCount(), self.t(key), width=width)
        self.terminals.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.edit_selected)
        self.terminals.Bind(wx.EVT_LIST_ITEM_SELECTED, self.highlight_row)
        self.terminals.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.highlight_row)
        self.terminals.SetPlaceholder(self.t('terminals_empty'))
        self.terminals._body.Bind(wx.EVT_KEY_DOWN, self._list_key)
        self.terminals._body.Bind(wx.EVT_LIST_BEGIN_LABEL_EDIT, self._begin_label_edit)
        self.terminals._body.Bind(wx.EVT_LIST_END_LABEL_EDIT, self._end_label_edit)
        sizer.Add(self.terminals, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(10))

        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.edit_button = self._push(page, 'edit', self.edit_selected)
        self.split_button = self._push(page, 'split', self.change_split)
        self.remove_button = self._push(page, 'remove', self.remove_group)
        actions.Add(self.edit_button, 1, wx.RIGHT, self.FromDIP(4))
        actions.Add(self.split_button, 1, wx.RIGHT, self.FromDIP(4))
        actions.Add(self.remove_button, 1)
        sizer.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(10))
        self.clear_button = self._push(page, 'remove_all', self.clear_groups)
        sizer.Add(self.clear_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(10))

        self.current_summary = wx.StaticText(page, label=self.t('no_loads'))
        self.current_summary.SetFont(widgets.ui_font(None, wx.FONTWEIGHT_BOLD))
        self.current_summary.Wrap(self.FromDIP(300))
        sizer.Add(self.current_summary, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(10))
        self.list_hint = self.label(page, 'list_hint')
        self.list_hint.SetForegroundColour(wx.Colour(self.palette.muted))
        self.list_hint.Wrap(self.FromDIP(300))
        self.list_hint.Hide()
        sizer.Add(self.list_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(10))
        cases = wx.BoxSizer(wx.HORIZONTAL)
        self.case_save_button = self._push(page, 'save_case', self.save_case)
        self.case_load_button = self._push(page, 'load_case', self.load_case)
        cases.Add(self.case_save_button, 1, wx.RIGHT, self.FromDIP(4))
        cases.Add(self.case_load_button, 1)
        sizer.Add(cases, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(10))
        page.SetSizer(sizer)
        return page

    def _build_model_page(self, parent):
        page = scrolled.ScrolledPanel(parent)
        page.SetBackgroundColour(self.palette.panel)
        self.model_page = page
        self.material_ids = ('custom', 'fr4', 'ceramic', 'metal_core')
        self.setting_controls = {}
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._page_heading(page, 'section_model', 'model_hint'), 0,
                  wx.ALL | wx.EXPAND, self.FromDIP(10))

        def heading(key, tooltip_key=None):
            label = wx.StaticText(page, label=self.t(key))
            label.SetFont(widgets.ui_font(None, wx.FONTWEIGHT_BOLD))
            label.SetForegroundColour(wx.Colour(self.palette.accent))
            if tooltip_key:
                label.SetToolTip(self.t(tooltip_key))
            self.bound_text.append((label, key))
            sizer.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, self.FromDIP(10))
            return label

        def spin_row(field, label_key, value, low, high, increment, digits, tooltip_key):
            control = LightSpinCtrlDouble(page, min=low, max=high, initial=value,
                                          inc=increment, size=(self.FromDIP(96), -1))
            control.SetDigits(digits)
            control.SetToolTip(self.t(tooltip_key))
            control.Bind(wx.EVT_SPINCTRLDOUBLE, self.invalidate_result)
            control.Bind(wx.EVT_TEXT, self.calculation_setting_changed)
            self.setting_controls[field] = control
            row = wx.BoxSizer(wx.HORIZONTAL)
            label = self.label(page, label_key)
            label._heatmap_setting_label = True
            label.Wrap(self.FromDIP(170))
            label.SetToolTip(self.t(tooltip_key))
            row.Add(label, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(8))
            row.Add(control, 0, wx.ALIGN_CENTER_VERTICAL)
            sizer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(10))
            return control

        # --- speed / precision presets ------------------------------------
        heading('presets_group', 'hint_preset')
        preset_row = wx.BoxSizer(wx.HORIZONTAL)
        self.preset_choice = LightChoice(page, choices=[self.t('preset_' + key)
                                                        for key in PRESET_ORDER],
                                         size=(self.FromDIP(210), -1))
        self.preset_choice.SetToolTip(self.t('hint_preset'))
        self.preset_choice.Bind(wx.EVT_CHOICE, self.apply_preset)
        preset_row.Add(self.preset_choice, 1, wx.EXPAND)
        sizer.Add(preset_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(10))
        self.preset_hint = wx.StaticText(page, label=self.t('hint_preset'))
        self.preset_hint.SetForegroundColour(wx.Colour(self.palette.muted))
        self.preset_hint.Wrap(self.FromDIP(290))
        sizer.Add(self.preset_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(10))

        # --- substrate -----------------------------------------------------
        heading('substrate_material')
        self.material_choice = LightChoice(page, choices=[self.t('material_' + key)
                                                          for key in self.material_ids])
        self.material_choice.SetSelection(0)
        self.material_choice.SetToolTip(self.t('hint_material'))
        self.material_choice.Bind(wx.EVT_CHOICE, self.change_material)
        sizer.Add(self.material_choice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(10))
        self.material_hint = wx.StaticText(page, label='')
        self.material_hint.SetForegroundColour(wx.Colour(self.palette.muted))
        self.material_hint.Wrap(self.FromDIP(290))
        sizer.Add(self.material_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(10))

        # --- environment ---------------------------------------------------
        heading('environment_group')
        spin_row('ambient_c', 'ambient', 25, -40, 200, 1, 1, 'hint_ambient')
        spin_row('convection_top', 'conv_top', 10, 0, 1000, 1, 1, 'hint_convection')
        spin_row('convection_bottom', 'conv_bottom', 10, 0, 1000, 1, 1, 'hint_convection')

        # --- substrate physics ---------------------------------------------
        heading('substrate_group')
        spin_row('fr4_k', 'substrate_xy', .3, .01, 1000, .05, 3, 'hint_substrate_xy')
        spin_row('substrate_k_z', 'substrate_z', .3, .01, 1000, .05, 3, 'hint_substrate_z')
        spin_row('copper_k', 'copper', 400, 100, 500, 5, 0, 'hint_copper_k')

        # --- copper foil ----------------------------------------------------
        heading('copper_group', 'hint_copper')
        self.copper_host = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.copper_host, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(10))
        self.copper_spins = []
        self.copper_rows = []

        # --- mesh and solver ------------------------------------------------
        heading('mesh_group')
        spin_row('cell_mm', 'grid', .25, .025, 2, .025, 3, 'hint_grid')
        self.setting_controls['cell_mm'].Bind(wx.EVT_TEXT, self._sync_preset_event)
        self.setting_controls['cell_mm'].Bind(wx.EVT_SPINCTRLDOUBLE, self._sync_preset_event)
        spin_row('via_plating_um', 'plating', 25, 5, 150, 1, 1, 'hint_plating')
        # Tolerance is edited through the precision choice; the hidden control
        # keeps it in the calculation-settings contract and the saved scenario.
        self.setting_controls['solver_tolerance'] = LightSpinCtrlDouble(
            page, min=1e-10, max=1e-3, initial=1e-8, inc=1e-9, size=(self.FromDIP(96), -1))
        self.setting_controls['solver_tolerance'].SetDigits(10)
        self.setting_controls['solver_tolerance'].Hide()
        precision_row = wx.BoxSizer(wx.HORIZONTAL)
        precision_label = self.label(page, 'precision')
        precision_label._heatmap_setting_label = True
        precision_label.Wrap(self.FromDIP(170))
        precision_label.SetToolTip(self.t('hint_tolerance'))
        precision_row.Add(precision_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(8))
        self.precision_choice = LightChoice(
            page, choices=[self.t('precision_' + key) for key in PRECISION_ORDER],
            size=(self.FromDIP(140), -1))
        self.precision_choice.SetToolTip(self.t('hint_tolerance'))
        self.precision_choice.Bind(wx.EVT_CHOICE, self.change_precision)
        precision_row.Add(self.precision_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(precision_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(10))
        self.node_budget = LightSpinCtrl(page, min=10000, max=2000000, initial=500000,
                                         size=(self.FromDIP(110), -1))
        self.node_budget.SetToolTip(self.t('hint_budget'))
        self.node_budget.Bind(wx.EVT_SPINCTRL, self.invalidate_result)
        budget_row = wx.BoxSizer(wx.HORIZONTAL)
        budget_label = self.label(page, 'limit_nodes')
        budget_label._heatmap_setting_label = True
        budget_label.Wrap(self.FromDIP(160))
        budget_label.SetToolTip(self.t('hint_budget'))
        budget_row.Add(budget_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(8))
        budget_row.Add(self.node_budget, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(budget_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(10))

        # --- warning limits --------------------------------------------------
        heading('limits_group')
        spin_row('max_temperature_c', 'temp_limit', 100, -40, 400, 5, 1, 'hint_limits')
        spin_row('max_delta_v', 'drop_limit', .5, .001, 100, .01, 3, 'hint_limits')

        # --- appearance of maps ---------------------------------------------
        heading('ramp')
        self.ramp_choice = LightChoice(page, choices=[self.t('ramp_' + name)
                                                      for name in colormap.RAMP_ORDER])
        self.ramp_choice.SetSelection(colormap.RAMP_ORDER.index(self.ui_state.get('ramp', 'rainbow'))
                                      if self.ui_state.get('ramp') in colormap.RAMP_ORDER else 0)
        self.ramp_choice.SetToolTip(self.t('hint_ramp'))
        self.ramp_choice.Bind(wx.EVT_CHOICE, self.change_ramp)
        sizer.Add(self.ramp_choice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(10))

        for key, tooltip_key in (('limit_hint', 'hint_limits'), ('scope', None)):
            note = self.label(page, key)
            note.SetForegroundColour(wx.Colour(self.palette.muted))
            note.Wrap(self.FromDIP(290))
            if tooltip_key:
                note.SetToolTip(self.t(tooltip_key))
            sizer.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(10))
        page.SetSizer(sizer)
        page.SetupScrolling(scroll_x=False)
        return page

    # ------------------------------------------------------------------ #
    # model helpers
    # ------------------------------------------------------------------ #
    def rebuild_copper_rows(self):
        """One editable foil thickness per copper layer, defaulting to stackup."""
        if not hasattr(self, 'copper_host'):
            return
        self.copper_host.Clear(delete_windows=True)
        self.copper_spins, self.copper_rows = [], []
        layers = (self.inspection or {}).get('layers') or []
        if not layers:
            note = wx.StaticText(self.model_page, label=self.t('copper_needs_board'))
            note.SetForegroundColour(wx.Colour(self.palette.muted))
            note.Wrap(self.FromDIP(290))
            self.copper_host.Add(note, 0, wx.EXPAND)
        else:
            grid = wx.FlexGridSizer(cols=2, hgap=self.FromDIP(8), vgap=self.FromDIP(6))
            grid.AddGrowableCol(0)
            for layer in layers:
                name = str(layer.get('name', ''))
                stackup = max(1, int(round(float(layer.get('thickness_mm', 0.035)) * 1000)))
                label = wx.StaticText(self.model_page, label=name)
                label.SetToolTip(self.t('hint_copper'))
                spin = LightSpinCtrlDouble(self.model_page, min=1, max=500, initial=stackup,
                                           inc=1, size=(self.FromDIP(76), -1))
                spin.SetDigits(0)
                spin.SetToolTip(self.t('hint_copper').format(stackup=stackup))
                spin.Bind(wx.EVT_TEXT, self.calculation_setting_changed)
                spin.Bind(wx.EVT_SPINCTRLDOUBLE, self.calculation_setting_changed)
                grid.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
                grid.Add(spin, 0, wx.ALIGN_CENTER_VERTICAL)
                self.copper_spins.append(spin)
                self.copper_rows.append((name, spin))
            self.copper_host.Add(grid, 0, wx.EXPAND)
        self.model_page.Layout()
        self.model_page.SetupScrolling(scroll_x=False, scroll_y=True)

    def copper_thickness(self):
        """Explicit per-layer foil thickness in µm, or ``None`` for the stackup."""
        spins = getattr(self, 'copper_spins', [])
        layers = (self.inspection or {}).get('layers') or []
        if not spins or len(spins) != len(layers):
            return None
        values = [int(round(spin.GetValue())) for spin in spins]
        stackup = [max(1, int(round(float(layer.get('thickness_mm', 0.035)) * 1000)))
                   for layer in layers]
        return None if values == stackup else values

    def apply_preset(self, event=None):
        key = PRESET_ORDER[max(0, self.preset_choice.GetSelection())]
        if key != 'custom':
            cell, tolerance = PRESETS[key]
            self.setting_controls['cell_mm'].SetValue(cell)
            self.setting_controls['solver_tolerance'].SetValue(tolerance)
            self.sync_precision(tolerance)
        self.preset_hint.SetLabel(self.t('hint_preset_' + key))
        self.preset_hint.Wrap(self.FromDIP(290))
        self.preset_hint.GetParent().Layout()
        self.invalidate_result()

    def _sync_preset_event(self, event=None):
        self.sync_preset()
        if event is not None:
            self.calculation_setting_changed(event)

    def sync_preset(self):
        if not hasattr(self, 'preset_choice'):
            return
        cell = round(float(self.setting_controls['cell_mm'].GetValue()), 6)
        key = 'custom'
        for name in PRESET_ORDER:
            if name != 'custom' and abs(PRESETS[name][0] - cell) < 1e-9:
                key = name
                break
        self.preset_choice.SetSelection(PRESET_ORDER.index(key))
        self.preset_hint.SetLabel(self.t('hint_preset_' + key))
        self.preset_hint.Wrap(self.FromDIP(290))

    def sync_precision(self, tolerance=None):
        if not hasattr(self, 'precision_choice'):
            return
        if tolerance is None:
            tolerance = float(self.setting_controls['solver_tolerance'].GetValue())
        key = 'fine'
        for name in PRECISION_ORDER:
            if abs(PRECISIONS[name] - tolerance) <= abs(PRECISIONS[name]) * 1e-6:
                key = name
                break
        self.precision_choice.SetSelection(PRECISION_ORDER.index(key))

    def change_precision(self, event=None):
        key = PRECISION_ORDER[max(0, self.precision_choice.GetSelection())]
        self.setting_controls['solver_tolerance'].SetValue(PRECISIONS[key])
        self.invalidate_result()

    def _build_results_page(self, parent):
        page = wx.Panel(parent)
        page.SetBackgroundColour(self.palette.panel)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._page_heading(page, 'section_results', 'results_hint'), 0,
                  wx.ALL | wx.EXPAND, self.FromDIP(10))
        self.result_summary = wx.StaticText(page, label=self.t('results_empty'))
        self.result_summary.SetFont(widgets.ui_font(11))
        sizer.Add(self.result_summary, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(10))
        # A read-only text pane wraps and scrolls with the pane width, which
        # stacked labels could not do reliably inside a scrolled panel.
        self.result_detail = wx.TextCtrl(
            page, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE)
        self.result_detail.SetBackgroundColour(self.palette.panel_alt)
        self.result_detail.SetForegroundColour(wx.Colour(self.palette.text))
        sizer.Add(self.result_detail, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(10))
        self.solve_facts = wx.StaticText(page, label='')
        self.solve_facts.SetForegroundColour(wx.Colour(self.palette.muted))
        sizer.Add(self.solve_facts, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(10))
        history_heading = wx.StaticText(page, label=self.t('history'))
        history_heading.SetFont(widgets.ui_font(None, wx.FONTWEIGHT_BOLD))
        sizer.Add(history_heading, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND,
                  self.FromDIP(10))
        self.history_label = wx.StaticText(page, label=self.t('history_empty'))
        self.history_label.SetForegroundColour(wx.Colour(self.palette.muted))
        sizer.Add(self.history_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  self.FromDIP(10))
        page.SetSizer(sizer)
        return page

    # ------------------------------------------------------------------ #
    # run history (this session only)
    # ------------------------------------------------------------------ #
    def record_history(self):
        result = getattr(self, 'result', None)
        if not result:
            return
        summary = result.get('summaries', {}) or {}
        nets = summary.get('nets', {}) or {}
        drop = max((float(item.get('max_delta_v', 0) or 0) for item in nets.values()),
                   default=0.0)
        copper = sum(float(item.get('copper_area_mm2', 0) or 0) for item in nets.values())
        self.run_history.append(dict(
            time=time.strftime('%H:%M:%S'),
            peak=float(summary.get('max_temperature_c', 0) or 0),
            drop=drop, copper=copper,
            path=str(self.result_dir or '')))
        self.run_history = self.run_history[-8:]
        self.render_history()

    def render_history(self):
        if not hasattr(self, 'history_label'):
            return
        if not self.run_history:
            self.history_label.SetLabel(self.t('history_empty'))
        else:
            lines = [f"{entry['time']} · {entry['peak']:.2f} °C · "
                     f"ΔV {entry['drop']:.3g} V · {entry['copper']:.1f} mm²"
                     for entry in reversed(self.run_history)]
            self.history_label.SetLabel('\n'.join(lines))
        self.history_label.Wrap(max(self.FromDIP(200),
                                    self.history_label.GetParent().GetClientSize().width
                                    - self.FromDIP(24)))
        self.history_label.GetParent().Layout()

    # ------------------------------------------------------------------ #
    # undo / redo over the terminal rows
    # ------------------------------------------------------------------ #
    def _snapshot(self):
        return {'rows': copy.deepcopy(self.rows),
                'contacts': copy.deepcopy(self.point_contacts)}

    def _push_undo(self):
        if getattr(self, '_suspend_undo', False):
            return
        self._undo_stack.append(self._snapshot())
        self._undo_stack = self._undo_stack[-40:]
        self._redo_stack.clear()

    def _restore_snapshot(self, snapshot):
        self._suspend_undo = True
        try:
            self.rows = copy.deepcopy(snapshot['rows'])
            self.point_contacts = copy.deepcopy(snapshot['contacts'])
            for identifier in [key for key in self.pad_by_id if key.startswith('point:')]:
                if identifier not in self.point_contacts:
                    self.pad_by_id.pop(identifier, None)
            for identifier, contact in self.point_contacts.items():
                self.pad_by_id[identifier] = self.point_metadata(contact)
            self.canvas.clear_selection()
            self.refresh_rows()
            self.update_selection_info()
            self.invalidate_result()
        finally:
            self._suspend_undo = False

    def undo(self, event=None):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self._restore_snapshot(self._undo_stack.pop())
        self.SetStatusText(self.t('undo_done'))

    def redo(self, event=None):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        self._restore_snapshot(self._redo_stack.pop())
        self.SetStatusText(self.t('redo_done'))

    def _global_key(self, event):
        focus = wx.Window.FindFocus()
        if isinstance(focus, (wx.TextCtrl, wx.SpinCtrl, wx.SpinCtrlDouble)):
            event.Skip()
            return
        if (event.GetKeyCode() in (ord('M'), ord('m')) and not event.ControlDown()
                and isinstance(focus, BoardCanvas)):
            self.toggle_markers()
            return
        if event.ControlDown() and event.GetKeyCode() in (ord('Z'), ord('z')):
            if event.ShiftDown():
                self.redo()
            else:
                self.undo()
            return
        event.Skip()

    def _list_key(self, event):
        if event.GetKeyCode() in (wx.WXK_DELETE, wx.WXK_BACK):
            self.remove_group()
        else:
            event.Skip()

    def _begin_label_edit(self, event):
        if event.GetColumn() != 2 or getattr(self, 'process', None) is not None:
            event.Veto()
            return
        index = event.GetIndex()
        if not 0 <= index < len(self.rows):
            event.Veto()
            return
        self._editing_row = index
        event.SetText(f"{self.rows[index]['value']:g}")

    def _end_label_edit(self, event):
        if event.IsEditCancelled() or event.GetColumn() != 2:
            return
        index = self._editing_row
        if index is None:
            index = event.GetIndex()
        if not isinstance(index, int) or not 0 <= index < len(self.rows):
            return
        kind = self.rows[index]['kind']
        try:
            value = float(event.GetText().strip().replace(',', '.'))
        except ValueError:
            event.Veto()
            self.error(self.t('invalid'))
            return
        if (not math.isfinite(value) or (kind == 'load' and value == 0)
                or (kind == 'heat' and value <= 0)):
            event.Veto()
            self.error(self.t('invalid'))
            return
        self._push_undo()
        self.rows[index]['value'] = value
        wx.CallAfter(self.refresh_rows)
        wx.CallAfter(self.invalidate_result)

    def _build_report_page(self, parent):
        page = wx.Panel(parent)
        page.SetBackgroundColour(self.palette.panel)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._page_heading(page, 'section_report', 'report_hint'), 0,
                  wx.ALL | wx.EXPAND, self.FromDIP(12))
        self.notes = wx.TextCtrl(page, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE)
        self.notes.SetBackgroundColour(self.palette.panel_alt)
        self.notes.SetForegroundColour(wx.Colour(self.palette.text))
        sizer.Add(self.notes, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(10))
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.copy_report_button = self._push(page, 'copy_report', self.copy_report)
        self.save_report_button = self._push(page, 'save_report', self.save_report)
        row.Add(self.copy_report_button, 1, wx.RIGHT, self.FromDIP(4))
        row.Add(self.save_report_button, 1)
        sizer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(10))
        page.SetSizer(sizer)
        return page

    def _build_canvas_panel(self, parent):
        panel = wx.Panel(parent)
        panel.SetBackgroundColour(self.palette.panel)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.analysis_notice = widgets.MessageBar(panel)
        self.analysis_notice.ApplyPalette(self.palette)
        sizer.Add(self.analysis_notice, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND,
                  self.FromDIP(10))

        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        self.search = wx.SearchCtrl(panel, style=wx.TE_PROCESS_ENTER,
                                    size=(self.FromDIP(150), self.FromDIP(28)))
        self.search.SetDescriptiveText(self.t('search_hint'))
        self.search.Bind(wx.EVT_TEXT_ENTER, self.find_reference)
        toolbar.Add(self.search, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(6))
        self.find_button = self._push(panel, 'find', self.find_reference, glyph='search')
        self.fit_button = self._push(panel, 'fit', lambda event: self.canvas.fit_board())
        self.visibility_button = self._push(panel, 'visibility', self.show_visibility,
                                            glyph='eye', width=88)
        self.markers_button = widgets.IconButton(panel, 'tag', self.t('hide_markers'),
                                                 size=(self.FromDIP(30), self.FromDIP(30)))
        self.markers_button.Bind(wx.EVT_BUTTON, self.toggle_markers)
        toolbar.Add(self.markers_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                    self.FromDIP(6))
        for button in (self.find_button, self.fit_button, self.visibility_button):
            toolbar.Add(button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(6))
        toolbar.AddStretchSpacer()
        layer_caption = self.label(panel, 'layer')
        layer_caption.SetForegroundColour(wx.Colour(self.palette.muted))
        toolbar.Add(layer_caption, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(6))
        self.layer = LightChoice(panel, choices=[self.t('all_layers')],
                                 size=(self.FromDIP(132), self.FromDIP(28)))
        self.layer.SetSelection(0)
        self.layer.Bind(wx.EVT_CHOICE, self.render_result)
        toolbar.Add(self.layer, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(10))
        net_caption = self.label(panel, 'net')
        net_caption.SetForegroundColour(wx.Colour(self.palette.muted))
        toolbar.Add(net_caption, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(6))
        self.net = LightChoice(panel, size=(self.FromDIP(132), self.FromDIP(28)))
        self.net.Bind(wx.EVT_CHOICE, self.render_result)
        toolbar.Add(self.net, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(toolbar, 0, wx.ALL | wx.EXPAND, self.FromDIP(10))

        second = wx.BoxSizer(wx.HORIZONTAL)
        self.view = widgets.SegmentedControl(
            panel, [self.t(key) for key in self.view_keys],
            on_select=lambda index: self.render_result(),
            max_width=self.FromDIP(760))
        self.view.ApplyPalette(self.palette)
        second.Add(self.view, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(10))
        self.canvas_hint = wx.StaticText(panel, label='', style=wx.ST_ELLIPSIZE_END)
        self.canvas_hint.SetForegroundColour(wx.Colour(self.palette.muted))
        second.Add(self.canvas_hint, 1, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(second, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(10))

        self.canvas = BoardCanvas(panel, on_pick=self.board_pick,
                                  on_marker=self.marker_pick,
                                  language=lambda: self.language,
                                  on_context=self.board_context)
        if hasattr(self.canvas, 'ApplyPalette'):
            self.canvas.ApplyPalette(self.palette)
        self.canvas.set_visibility(markers=bool(self.ui_state.get('markers', True)))
        self.markers_button.SetActive(bool(self.ui_state.get('markers', True)))
        sizer.Add(self.canvas, 1, wx.EXPAND)

        bottom = wx.BoxSizer(wx.HORIZONTAL)
        self.legend = widgets.Legend(panel)
        self.legend.ApplyPalette(self.palette)
        bottom.Add(self.legend, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(12))
        info = wx.BoxSizer(wx.VERTICAL)
        self.stats = wx.StaticText(panel, label='')
        self.stats.Wrap(self.FromDIP(360))
        info.Add(self.stats, 0, wx.EXPAND)
        opacity_row = wx.BoxSizer(wx.HORIZONTAL)
        self.opacity_label = self.label(panel, 'opacity')
        self.opacity_label.SetForegroundColour(wx.Colour(self.palette.muted))
        opacity_row.Add(self.opacity_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(6))
        self.opacity = wx.Slider(panel, value=int(self.ui_state.get('opacity', 68)), minValue=10,
                                 maxValue=95, size=(self.FromDIP(150), self.FromDIP(24)))
        self.opacity.Bind(wx.EVT_SLIDER, self.render_result)
        opacity_row.Add(self.opacity, 0, wx.ALIGN_CENTER_VERTICAL)
        info.Add(opacity_row, 0, wx.TOP | wx.EXPAND, self.FromDIP(4))
        bottom.Add(info, 1, wx.EXPAND)
        sizer.Add(bottom, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(10))
        panel.SetSizer(sizer)
        return panel

    def _build_action_bar(self):
        palette = self.palette
        bar = wx.Panel(self)
        bar.SetBackgroundColour(palette.panel_alt)
        bar.SetMinSize((-1, self.FromDIP(58)))
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.run_button = widgets.PushButton(bar, self.t('run'), role='primary', glyph='play',
                                             width=168,
                                             size=(self.FromDIP(150), self.FromDIP(36)))
        self.run_button.ApplyPalette(palette)
        self.run_button.Bind(wx.EVT_BUTTON, self.analyze)
        row.Add(self.run_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, self.FromDIP(12))
        self.cancel_button = widgets.PushButton(bar, self.t('cancel'), width=92,
                                                size=(self.FromDIP(92), self.FromDIP(36)))
        self.cancel_button.ApplyPalette(palette)
        self.cancel_button.Bind(wx.EVT_BUTTON, self.cancel)
        row.Add(self.cancel_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, self.FromDIP(8))
        self.progress = wx.Gauge(bar, range=1000, size=(self.FromDIP(170), self.FromDIP(10)))
        row.Add(self.progress, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, self.FromDIP(14))
        self.message = wx.StaticText(bar, label=self.t('ready'), style=wx.ST_ELLIPSIZE_END)
        self.message.SetForegroundColour(wx.Colour(palette.muted))
        row.Add(self.message, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, self.FromDIP(12))
        self.folder_button = widgets.PushButton(bar, self.t('results'), width=116,
                                                size=(self.FromDIP(116), self.FromDIP(34)))
        self.folder_button.ApplyPalette(palette)
        self.folder_button.Bind(wx.EVT_BUTTON, self.open_results)
        self.folder_button.Disable()
        row.Add(self.folder_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(12))
        bar.SetSizer(row)
        return bar

    # ------------------------------------------------------------------ #
    # appearance, sections and shared chrome
    # ------------------------------------------------------------------ #
    def apply_theme(self, event=None):
        self.palette = palette = theme.load_palette(
            self.ui_state.get('appearance', 'auto'), ramp=self.ui_state.get('ramp', 'rainbow'))
        self.SetBackgroundColour(palette.bg)
        theme.apply_palette(self, palette)
        for window in (getattr(self, 'canvas', None), getattr(self, 'rail', None),
                       getattr(self, 'legend', None), getattr(self, 'analysis_notice', None),
                       getattr(self, 'view', None), getattr(self, 'status_pill', None),
                       getattr(self, 'run_button', None), getattr(self, 'cancel_button', None),
                       getattr(self, 'folder_button', None)):
            setter = getattr(window, 'ApplyPalette', None)
            if callable(setter):
                try:
                    setter(palette)
                except Exception:
                    pass
        if hasattr(self, 'canvas') and hasattr(self.canvas, 'ApplyPalette'):
            self.canvas.ApplyPalette(palette)
        if hasattr(self, 'render_result') and getattr(self, 'result', None) is not None:
            self.render_result()
        self.Layout()

    def show_appearance_menu(self, event=None):
        menu = wx.Menu()
        current = self.ui_state.get('appearance', 'auto')
        modes = (('auto', self.t('appearance_auto')),
                 ('dark', self.t('appearance_dark')),
                 ('light', self.t('appearance_light')))
        for mode, label in modes:
            item = menu.AppendRadioItem(wx.ID_ANY, label)
            item.Check(mode == current)
            self.Bind(wx.EVT_MENU, lambda event, value=mode: self.set_appearance(value), item)
        menu.AppendSeparator()
        ramp_menu = wx.Menu()
        for name in colormap.RAMP_ORDER:
            item = ramp_menu.AppendRadioItem(wx.ID_ANY, self.t('ramp_' + name))
            item.Check(name == self.ui_state.get('ramp', 'rainbow'))
            self.Bind(wx.EVT_MENU, lambda event, value=name: self.set_ramp(value), item)
        menu.AppendSubMenu(ramp_menu, self.t('ramp'))
        self.PopupMenu(menu)
        menu.Destroy()

    def set_appearance(self, mode):
        if mode not in ('auto', 'dark', 'light'):
            return
        self.ui_state['appearance'] = mode
        self.apply_theme()
        self.save_ui_state()
        self.SetStatusText(self.t('appearance_applied') + ' · ' + self.palette.name)

    def set_ramp(self, name):
        if name not in colormap.RAMP_ORDER:
            return
        self.ui_state['ramp'] = name
        if hasattr(self, 'ramp_choice'):
            self.ramp_choice.SetSelection(colormap.RAMP_ORDER.index(name))
        self.legend.SetRamp(name)
        self.canvas.set_ramp(name)
        self.save_ui_state()
        self.render_result()

    def change_ramp(self, event=None):
        index = max(0, self.ramp_choice.GetSelection())
        self.set_ramp(colormap.RAMP_ORDER[index])

    def show_section(self, key):
        if key not in self.section_keys:
            return
        index = self.section_keys.index(key)
        self.sections.SetSelection(index)
        self.rail.select(key)
        self._fit_page(index)

    def _fit_page(self, index):
        """Re-measure a page after the pane or language changed."""
        if not 0 <= index < len(getattr(self, 'pages', [])):
            return
        page = self.pages[index]
        try:
            if hasattr(page, 'SetupScrolling'):
                page.SetupScrolling(scroll_x=False, scroll_y=True)
            if index == self.section_keys.index('results'):
                width = max(self.FromDIP(200),
                            page.GetClientSize().width - self.FromDIP(24))
                for label in (self.result_summary, self.solve_facts, self.history_label):
                    label.Wrap(width)
                self.result_detail.SetSize(-1, -1)
            page.Layout()
        except Exception:
            pass

    def _section_changed(self, index):
        if 0 <= index < len(self.section_keys):
            self.rail.select(self.section_keys[index])
            self.ui_state['section'] = self.section_keys[index]
            self.save_ui_state()
            self._fit_page(index)

    def save_ui_state(self):
        if not hasattr(self, 'ui_state'):
            return
        try:
            size = self.GetSize()
            self.ui_state['width'] = int(size.width)
            self.ui_state['height'] = int(size.height)
            if hasattr(self, 'splitter'):
                self.ui_state['splitter'] = int(self.splitter.GetSashPosition())
            if hasattr(self, 'opacity'):
                self.ui_state['opacity'] = int(self.opacity.GetValue())
            if hasattr(self, 'cpu_threads'):
                self.ui_state['threads'] = int(self.cpu_threads.GetValue())
            if hasattr(self, 'ramp_choice'):
                self.ui_state['ramp'] = colormap.RAMP_ORDER[
                    max(0, self.ramp_choice.GetSelection())]
            if hasattr(self, 'canvas'):
                self.ui_state['markers'] = bool(self.canvas.show_markers)
        except Exception:
            return
        ui_state.save_ui_state(self.ui_state, self.preferences_path and
                              Path(self.preferences_path).with_name('ui-state.json'))

    def SetStatusText(self, text, number=0):
        """Route the frame status line to the action bar message label."""
        self._status_text = str(text)
        message = getattr(self, 'message', None)
        if message is not None:
            message.SetLabel(self._status_text)
            message.GetParent().Layout()
        return True

    def GetStatusText(self, number=0):
        return getattr(self, '_status_text', '')

    def copy_report(self, event=None):
        if not self.notes.GetValue():
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(self.notes.GetValue()))
            wx.TheClipboard.Close()
            self.SetStatusText(self.t('copied'))

    def save_report(self, event=None):
        text = self.notes.GetValue()
        if not text:
            return
        default = (Path(self.board_path).stem if self.board_path else 'pcb-heatmap') + '-report.txt'
        with wx.FileDialog(self, self.t('save_report'), defaultFile=default,
                           wildcard='Text (*.txt)|*.txt',
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                try:
                    Path(dialog.GetPath()).write_text(text, encoding='utf-8')
                    self.SetStatusText(self.t('report_saved'))
                except OSError as exc:
                    self.error(exc)


    def restore_calculation_settings(self):
        super().restore_calculation_settings()
        self.sync_preset()
        self.sync_precision()

    def busy(self, value):
        for control in (self.open_button, self.reload_button, self.edit_button,
                        self.remove_button, self.clear_button, self.case_save_button,
                        self.case_load_button, self.node_budget,
                        self.material_choice, self.ramp_choice, self.preset_choice,
                        self.precision_choice, self.split_button,
                        *getattr(self, 'copper_spins', []),
                        *self.setting_controls.values(), *self.assign_buttons.values()):
            control.Enable(not value)
        self.mode_control.Enable(not value)
        self.run_button.Enable(not value and self.inspection is not None)
        self.cancel_button.Enable(value)
        if hasattr(self, 'status_pill'):
            self.status_pill.SetLabel(self.t('working') if value else self.t('ready'))
            self.status_pill.SetTone('warn' if value else 'muted')
        self.update_selection_info()

    def change_language(self, event=None):
        self.language = 'tr' if self.language_choice.GetSelection() == 1 else 'en'
        for control, key in self.bound_text:
            control.SetLabel(self.t(key))
            if isinstance(control, wx.StaticText):
                width = 150 if getattr(control, '_heatmap_setting_label', False) else 290
                control.Wrap(self.FromDIP(width))
        for title, key in self.section_headings:
            title.SetLabel(self.t(key))
        for index, key in enumerate(self.section_keys):
            self.sections.SetPageText(index, self.t('section_' + key))
            self.rail.buttons[key].SetToolTip(self.t('section_' + key))
        self.mode_control.Set([self.t(key + '_mode') for key in self.mode_keys],
                              self.mode_control.GetSelection())
        material_index = max(0, self.material_choice.GetSelection())
        self.material_choice.Set([self.t('material_' + key) for key in self.material_ids])
        self.material_choice.SetSelection(material_index)
        self.update_material_hint()
        preset_index = max(0, self.preset_choice.GetSelection())
        self.preset_choice.Set([self.t('preset_' + key) for key in PRESET_ORDER])
        self.preset_choice.SetSelection(preset_index)
        precision_index = max(0, self.precision_choice.GetSelection())
        self.precision_choice.Set([self.t('precision_' + key) for key in PRECISION_ORDER])
        self.precision_choice.SetSelection(precision_index)
        self.sync_preset()
        ramp_index = max(0, self.ramp_choice.GetSelection())
        self.ramp_choice.Set([self.t('ramp_' + name) for name in colormap.RAMP_ORDER])
        self.ramp_choice.SetSelection(ramp_index)
        self.search.SetDescriptiveText(self.t('search_hint'))
        self.markers_button.SetToolTip(self.t('hide_markers' if self.canvas.show_markers
                                            else 'show_markers'))
        self.terminals.SetPlaceholder(self.t('terminals_empty'))
        self.language_choice.SetSelection(1 if self.language == 'tr' else 0)
        self.mode_hint.SetLabel(self.t('hint_' + self.mode))
        self.mode_hint.Wrap(self.FromDIP(300))
        self.canvas_hint.SetLabel(self.t('hint_' + self.mode))
        for index, key in enumerate(('kind', 'group', 'value')):
            column = self.terminals.GetColumn(index)
            column.SetText(self.t(key))
            self.terminals.SetColumn(index, column)
        self.status_pill.SetLabel(self.t('ready') if not self.process else self.status_pill.GetLabel())
        self.update_board_label()
        self.refresh_rows()
        self.update_selection_info()
        self.render_history()
        if self.result is not None:
            self.refresh_result_notes()
            self.refresh_result_panel()
        self.render_result()
        self.update_analysis_notice()
        self._fit_page(self.sections.GetSelection())
        self.Layout()

    def choose_mode(self, mode):
        selected = self.canvas.get_selection()
        self.mode = mode if mode in self.mode_keys else 'select'
        index = self.mode_keys.index(self.mode)
        if self.mode_control.GetSelection() != index:
            self.mode_control.SetSelection(index)
        self.canvas.set_mode(self.mode)
        self.mode_hint.SetLabel(self.t('hint_' + self.mode))
        self.mode_hint.Wrap(self.FromDIP(300))
        self.canvas_hint.SetLabel(self.t('hint_' + self.mode))
        self.source_net_row.Show(self.mode == 'source')
        if self.mode != 'select' and selected:
            self.define_contact(self.mode, selected, [])
        self.Layout()

    def update_board_label(self):
        if not self.inspection:
            if hasattr(self, 'board_chip'):
                self.board_chip.SetLabel(self.t('no_board'))
            return
        stats = self.inspection.get('stats', {})
        text = self.t('board_summary').format(
            file=Path(self.board_path).name, layers=len(self.inspection.get('layers', [])),
            pads=len(self.inspection.get('pads', [])), zones=stats.get('copper_zones', '—'),
            filled=stats.get('filled_copper_zones', '—'),
            sha=self.inspection.get('sha256', '')[:10])
        self.board_label.SetLabel(text)
        self.board_label.SetToolTip(self.board_path)
        self.board_label.Wrap(self.FromDIP(300))
        chip = self.t('board_chip').format(
            file=Path(self.board_path).name,
            layers=len(self.inspection.get('layers', [])),
            pads=len(self.inspection.get('pads', [])),
            nets=len(self.inspection.get('nets', [])))
        self.board_chip.SetLabel(chip)
        self.board_chip.SetToolTip(self.board_path)
        self.update_readiness()

    def update_readiness(self):
        def line(ok, text):
            return ('\u2713 ' if ok else '\u26a0 ') + text
        checks = []
        if self.inspection:
            stats = self.inspection.get('stats', {}) or {}
            zones = int(stats.get('copper_zones') or 0)
            filled = int(stats.get('filled_copper_zones') or 0)
            checks.append(line(True, self.t('ready_saved')))
            if zones:
                checks.append(line(filled >= zones,
                                   self.t('ready_zones').format(filled=filled, zones=zones)))
            else:
                checks.append(line(True, self.t('ready_zones_none')))
        else:
            checks.append(line(False, self.t('no_board')))
        try:
            runtime = worker_python()
        except Exception:
            runtime = ''
        checks.append(line(bool(runtime), self.t('ready_runtime').format(path=runtime or '\u2014')))
        checks.append('\u00b7 ' + self.t('ready_runs').format(path=paths.runs_root()))
        self.readiness.SetLabel('\n'.join(checks))
        self.readiness.SetForegroundColour(wx.Colour(self.palette.muted))
        self.readiness.Wrap(self.FromDIP(300))
        parent = self.readiness.GetParent()
        parent.Layout()
        self.readiness.InvalidateBestSize()
        self.readiness.SetMinSize((-1, self.readiness.GetBestSize().height))

    def update_selection_info(self):
        ids = self.canvas.get_selection() if hasattr(self, 'canvas') else []
        pads = [self.pad_by_id[identifier] for identifier in ids
                if identifier in self.pad_by_id]
        nets = sorted({pad.get('net', '') for pad in pads if pad.get('net')})
        if not ids:
            title = self.t('no_selection')
            detail = self.t('select_prompt')
        elif len(ids) == 1:
            pad = pads[0] if pads else {}
            title = pad.get('label', ids[0])
            layers = pad.get('layers') or []
            layer = ''
            if layers and self.inspection:
                names = [item.get('name', '') for item in self.inspection.get('layers', [])]
                index = int(layers[0])
                if 0 <= index < len(names):
                    layer = names[index]
            detail = ' · '.join(part for part in (pad.get('net') or self.t('no_net'), layer,
                                                  self.t('single_pad_hint')) if part)
        else:
            title = self.t('selected_count').format(count=len(ids),
                                                    net=', '.join(nets) or '—')
            detail = self.t('multi_hint')
        self.selection_info.SetLabel(title)
        self.selection_detail.SetLabel(detail)
        width = max(self.FromDIP(230),
                    self.selection_info.GetParent().GetClientSize().width - 20)
        for label in (self.selection_info, self.selection_detail):
            label.Wrap(width)
            label.InvalidateBestSize()
            label.SetMinSize((-1, label.GetBestSize().height))
        self.group_note.Show(len(ids) > 1)
        busy = getattr(self, 'process', None) is not None or not self.inspection
        for kind, button in getattr(self, 'assign_buttons', {}).items():
            usable = bool(ids) and not busy and (
                kind == 'heat' or (len(nets) == 1 and '' not in nets))
            button.Enable(usable)
        self.selection_info.GetParent().Layout()

    def assign_ids(self, kind, identifiers):
        if not identifiers:
            return
        self.define_contact(kind, identifiers, [])

    def add_to_selection(self, identifiers):
        current = list(self.canvas.get_selection())
        self.canvas.selected = list(dict.fromkeys([*current, *identifiers]))
        self.canvas.Refresh(False)
        self.update_selection_info()

    def board_context(self, event):
        """Right-click actions for the pad under the pointer or the selection."""
        if getattr(self, 'process', None) is not None or not self.inspection:
            return
        position = event.GetPosition()
        x, y = self.canvas.screen_to_world(position.x, position.y)
        hit = self.canvas.hit_test(x, y, heat=True)
        hit_ids = list(hit.get('pad_ids') or []) if hit and hit.get('type') in (
            'pad', 'footprint') else []
        selected = list(self.canvas.get_selection())
        target = selected or hit_ids
        menu = wx.Menu()
        if target:
            for kind, key in (('source', 'set_as_source'), ('load', 'set_as_load'),
                              ('heat', 'set_as_heat')):
                item = menu.Append(wx.ID_ANY, self.t(key))
                menu.Bind(wx.EVT_MENU,
                          lambda menu_event, value=kind, ids=target: self.assign_ids(value, ids),
                          item)
            menu.AppendSeparator()
            if hit_ids and (not selected or set(hit_ids) - set(selected)):
                item = menu.Append(wx.ID_ANY, self.t('add_to_selection'))
                menu.Bind(wx.EVT_MENU,
                          lambda menu_event, ids=hit_ids: self.add_to_selection(ids), item)
            if selected:
                item = menu.Append(wx.ID_ANY, self.t('clear_selection'))
                menu.Bind(wx.EVT_MENU, self._clear_selection_menu, item)
            menu.AppendSeparator()
        item = menu.Append(wx.ID_ANY, self.t('fit'))
        menu.Bind(wx.EVT_MENU, lambda menu_event: self.canvas.fit_board(), item)
        self.canvas.PopupMenu(menu, position)
        menu.Destroy()

    def toggle_markers(self, event=None):
        value = not bool(self.canvas.show_markers)
        self.canvas.set_visibility(markers=value)
        self.markers_button.SetActive(value)
        self.markers_button.SetToolTip(self.t('hide_markers' if value else 'show_markers'))
        self.save_ui_state()
        self.SetStatusText(self.t('markers_shown' if value else 'markers_hidden'))

    def _clear_selection_menu(self, event=None):
        self.canvas.clear_selection()
        self.canvas.Refresh(False)
        self.update_selection_info()

    def assign_selection(self, kind):
        if getattr(self, 'process', None) is not None:
            return
        if not self.inspection:
            self.error(self.t('save_first'))
            return
        identifiers = self.canvas.get_selection()
        if not identifiers:
            self.SetStatusText(self.t('selection_empty'))
            return
        self.define_contact(kind, identifiers, [])

    def ask_assignment(self, kind, label, identifiers, current=None, distribution='per_pad'):
        nets = sorted({self.pad_by_id[i].get('net', '') for i in identifiers
                       if i in self.pad_by_id})
        description = label + '\n' + self.t('group_pads').format(
            count=len(identifiers), net=', '.join(nets) or '\u2014')
        title = self.t({'source': 'source_mode', 'load': 'load_mode',
                        'heat': 'heat_mode'}.get(kind, 'load_mode'))
        with AssignmentDialog(self, title, description,
                              value=current if current is not None else '',
                              kind=kind, identifiers=identifiers, pads=self.pad_by_id,
                              distribution=distribution) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return None
            value, chosen = dialog.answer()
        if value is None or not math.isfinite(value):
            self.error(self.t('invalid'))
            return None
        if (kind == 'load' and value == 0) or (kind == 'heat' and value <= 0):
            self.error(self.t('invalid'))
            return None
        return value, chosen

    def change_split(self, event=None):
        if getattr(self, 'process', None) is not None:
            return
        indices = [index for index in self.selected_row_indices()
                   if self.rows[index]['kind'] == 'load'
                   and len(self.rows[index]['pad_ids']) > 1]
        if not indices:
            self.SetStatusText(self.t('split_needs_group'))
            return
        row = self.rows[indices[0]]
        labels = ', '.join(self.pad_by_id[i]['label'] for i in row['pad_ids'])
        with AssignmentDialog(self, self.t('split_rule'), labels, kind='load',
                              identifiers=row['pad_ids'], pads=self.pad_by_id,
                              distribution=row.get('distribution', 'per_pad'),
                              rule_only=True) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            _, chosen = dialog.answer()
        self._push_undo()
        for index in indices:
            self.rows[index]['distribution'] = chosen
        self.refresh_rows()
        self.invalidate_result()
        self.SetStatusText(self.t('split_applied').format(
            count=len(indices),
            rule=self.t('split_per_pad' if chosen == 'per_pad' else 'split_area')))

    def on_close(self, event):
        try:
            self.save_ui_state()
        except Exception:
            pass
        session = self._analysis_session
        if session is not None and session['process'].poll() is None:
            try:
                session['process'].stdin.write('{"type": "shutdown"}\n')
                session['process'].stdin.flush()
            except (OSError, ValueError):
                pass
            try:
                session['process'].kill()
            except OSError:
                pass
        super().on_close(event)

    def current_ramp(self):
        if not hasattr(self, 'ramp_choice'):
            return self.ui_state.get('ramp', 'rainbow')
        index = max(0, self.ramp_choice.GetSelection())
        return colormap.RAMP_ORDER[min(index, len(colormap.RAMP_ORDER) - 1)]

    def refresh_result_panel(self):
        result = getattr(self, 'result', None)
        if not hasattr(self, 'result_summary'):
            return
        if not result or self.result_dirty:
            self.result_summary.SetLabel(self.t('changed_case' if result else 'results_empty'))
            self.result_detail.SetLabel('')
            self.solve_facts.SetLabel('')
            return
        summary = result.get('summaries', {}) or {}
        diagnostics = result.get('diagnostics', {}) or {}
        hot = summary.get('hotspot') or {}
        lines = []
        if self.is_dc_diagnostic():
            lines.append(self.t('dc_summary').format(
                temperature=result.get('reference_temperature_c', 0),
                power=summary.get('joule_w', 0)))
            lines.append(self.t('dc_incomplete'))
        else:
            lines.append(f"{self.t('peak_temperature')}: "
                         f"{float(summary.get('max_temperature_c', 0)):.2f} \u00b0C"
                         f"  (+{float(summary.get('max_rise_c', 0)):.2f} K)")
            if hot:
                lines.append(f"{self.t('hotspot')}: {hot.get('layer', '')} \u00b7 "
                             f"X {float(hot.get('x_mm', 0)):.2f} \u00b7 "
                             f"Y {float(hot.get('y_mm', 0)):.2f} mm")
            lines.append(f"{self.t('total_heat')}: {float(summary.get('total_heat_w', 0)):.4g} W"
                         f" \u00b7 {self.t('joule')}: {float(summary.get('joule_w', 0)):.4g} W"
                         f" \u00b7 {self.t('component_heat')}: "
                         f"{float(summary.get('component_heat_w', 0)):.4g} W")
            residual = diagnostics.get('thermal_energy_error_w')
            if residual is not None:
                lines.append(f"{self.t('energy_residual')}: {float(residual):.3g} W")
        self.result_summary.SetLabel('\n'.join(lines))
        detail = []
        nets = summary.get('nets', {}) or {}
        if nets:
            detail.append(self.t('per_net'))
            for net in sorted(nets):
                item = nets[net] or {}
                detail.append(f"  {net}: {self.t('draw')} "
                              f"{float(item.get('load_current_a', 0)):.4g} A \u00b7 "
                              f"{self.t('loss')} {float(item.get('joule_w', 0)):.4g} W \u00b7 "
                              f"\u0394V {float(item.get('max_delta_v', 0)):.3g} V")
                if item.get('copper_area_mm2') is not None:
                    vias = int(item.get('via_count', 0) or 0)
                    text = (f"    {self.t('copper_area')} "
                            f"{float(item['copper_area_mm2']):.2f} mm\u00b2 \u00b7 "
                            f"{self.t('vias')} {vias}")
                    if vias:
                        text += (f" \u00b7 {self.t('via_worst')} "
                                 f"{float(item.get('max_via_density_a_mm2', 0)):.3g} A/mm\u00b2")
                    detail.append(text)
                for group in item.get('terminal_groups', []) or []:
                    rule = self.t('split_per_pad' if group.get('distribution') == 'per_pad'
                                  else 'split_area')
                    detail.append(f"    {self.t('group')} "
                                  f"{float(group.get('total_a', 0)):.4g} A \u00b7 {rule}")
                    for pad in (group.get('pads') or [])[:16]:
                        detail.append(f"      {pad.get('label', '')}: "
                                      f"{float(pad.get('current_a', 0)):.4g} A "
                                      f"({int(pad.get('cells', 0))} {self.t('cells')})")
        self.result_detail.ChangeValue('\n'.join(detail))
        facts = []
        timings = result.get('timings_s') or {}
        if timings:
            facts.append(' \u00b7 '.join(f'{name} {float(value):.2f} s'
                                         for name, value in timings.items()))
        if diagnostics:
            facts.append(f"{self.t('cells')}: {diagnostics.get('thermal_cells', '\u2014')}"
                         f" \u00b7 {self.t('iterations')}: "
                         f"{len(diagnostics.get('iterations', []))}"
                         f" \u00b7 {self.t('preconditioner')}: "
                         f"{diagnostics.get('preconditioner', '\u2014')}")
        compute = result.get('compute') or {}
        if compute:
            facts.append(f"{self.t('cpu_cores')}: {compute.get('cpu_count', '\u2014')}")
        warnings = [str(value) for value in (result.get('warnings') or [])]
        warnings += [str(value) for value in (diagnostics.get('warnings') or [])
                     if str(value) not in warnings]
        if warnings:
            facts.append(self.t('warnings') + ':')
            facts.extend('  \u2022 ' + warning for warning in warnings)
        self.solve_facts.SetLabel('\n'.join(facts))
        width = max(self.FromDIP(200),
                    self.result_summary.GetParent().GetClientSize().width - self.FromDIP(24))
        for label in (self.result_summary, self.solve_facts):
            label.Wrap(width)
            label.InvalidateBestSize()
        self.result_summary.GetParent().Layout()


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
        try:
            run = paths.new_run_directory()
        except OSError:
            self.error(self.t('runs_unwritable').format(path=paths.runs_root()))
            return
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
        if hasattr(self, 'stackup') and data.get('layers'):
            self.stackup.SetLabel(self.t('stackup') + '\n' + '\n'.join(
                f"{layer['name']} \u00b7 {float(layer.get('thickness_mm', 0)):.3f} mm"
                for layer in data['layers']))
        self.rebuild_copper_rows()
        self.legend.SetRamp(self.current_ramp())
        if hasattr(self.canvas, 'set_ramp'):
            self.canvas.set_ramp(self.current_ramp())
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
            self.status_pill.SetLabel(self.t('error'))
            self.status_pill.SetTone('error')
            self.error('\n'.join(self.last_log or lines[-12:]))
            return
        try:
            data = json.loads(self._inspection_path.read_text(encoding='utf8'))
            if sha256(self.snapshot['path']) != data['sha256']:
                raise ValueError(self.t('changed'))
            self.accept_layout(data)
            self.update_readiness()
            self.status_pill.SetLabel(self.t('ready'))
            self.status_pill.SetTone('ok')
        except Exception as exc:
            self.status_pill.SetLabel(self.t('error'))
            self.status_pill.SetTone('error')
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
        with wx.Dialog(self, title=self.t('visibility').rstrip('…'),
                       size=(self.FromDIP(350), -1)) as dialog:
            sizer = wx.BoxSizer(wx.VERTICAL)
            for key, value in self.canvas.get_visibility().items():
                checkbox = LightCheckBox(dialog, label=self.t(key))
                checkbox.SetValue(value)
                checkbox.SetMinSize((self.FromDIP(316), self.FromDIP(28)))
                checkbox.Bind(wx.EVT_CHECKBOX, lambda event, k=key, c=checkbox:
                              self.canvas.set_visibility(**{k: c.GetValue()}))
                sizer.Add(checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND,
                          self.FromDIP(12))
            ok = LightButton(dialog, wx.ID_OK, self.t('ok'))
            ok.SetDefault()
            sizer.Add(ok, 0, wx.ALL | wx.ALIGN_RIGHT, self.FromDIP(12))
            dialog.SetSizerAndFit(sizer)
            dialog.SetMinSize((self.FromDIP(340), dialog.GetSize().height))
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
            previous = existing.get('distribution', 'per_pad') if existing else 'per_pad'
            if len(identifiers) > 1:
                answer = self.ask_assignment(kind, label, identifiers,
                                             existing['value'] if existing else None,
                                             previous)
                if answer is None:
                    return
                value, distribution = answer
            else:
                value = self.ask_value(kind, label, existing['value'] if existing else None)
                if value is None:
                    return
                distribution = previous
            self._push_undo()
            self.point_contacts.update(normalized)
            self.pad_by_id.update({i: meta[i] for i in normalized})
            if existing is not None:
                existing['value'] = value
                existing['distribution'] = distribution
            else:
                row = dict(identifier=uuid.uuid4().hex, kind=kind, pad_ids=identifiers,
                           value=value)
                if kind == 'load':
                    row['distribution'] = distribution
                self.rows.append(row)
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
        if hasattr(self, 'list_hint'):
            self.list_hint.Show(bool(self.rows))
            self.list_hint.GetParent().Layout()
        self.current_summary.SetLabel(full_text)
        self.current_summary.SetToolTip(full_text)
        self.current_summary.Wrap(max(230, self.current_summary.GetParent().GetClientSize().width - 20))
        self.current_summary.InvalidateBestSize()
        self.current_summary.SetMinSize((-1, self.current_summary.GetBestSize().height))
        self.current_summary.SetForegroundColour(wx.Colour(
            self.palette.warning if duplicates else self.palette.text))
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
            self._push_undo()
            row['value'] = value
            self.refresh_rows(); self.invalidate_result()

    def edit_selected(self, event=None):
        if self.process is not None:
            return
        if event is not None and event.GetEventType() == wx.EVT_LIST_ITEM_ACTIVATED.typeId:
            if event.GetColumn() == 2:
                return
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
        if getattr(self, 'process', None) is not None:
            return
        indices = self.selected_row_indices()
        if not indices:
            return
        if len(indices) >= 4:
            answer = wx.MessageBox(self.t('confirm_remove').format(count=len(indices)),
                                   self.t('remove'),
                                   wx.YES_NO | wx.ICON_QUESTION, self)
            if answer != wx.YES:
                return
        self._push_undo()
        for index in reversed(indices):
            del self.rows[index]
        self.canvas.clear_selection()
        self.prune_contacts()
        self.refresh_rows()
        self.update_selection_info()
        self.invalidate_result()

    def clear_groups(self, event=None):
        if self.process is not None:
            return
        if not self.rows:
            return
        self._push_undo()
        self.canvas.clear_selection()
        self.rows.clear()
        self.prune_contacts()
        self.refresh_rows()
        self.update_selection_info()
        self.invalidate_result()

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
        copper = self.copper_thickness()
        if copper:
            data['settings']['copper_um'] = copper
        used = {identifier for row in self.rows for identifier in row['pad_ids']}
        data['contacts'] = [contact for identifier, contact in self.point_contacts.items() if identifier in used]
        data['original_board_path'] = self.board_path
        if self.snapshot:
            data['snapshot'] = dict(self.snapshot)
        return data

    def _ensure_analysis_session(self):
        session = self._analysis_session
        if session is not None and session['process'].poll() is None:
            return session
        environment = dict(os.environ, PCB_HEATMAP_HEADLESS='1',
                           PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8')
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        process = subprocess.Popen(
            [worker_python(), '-u', str(Path(__file__).with_name('worker.py')), 'serve'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', env=environment,
            creationflags=flags)
        session = {'process': process, 'token': None, 'lines': []}
        self._analysis_session = session
        threading.Thread(target=self._session_reader, args=(session,),
                         daemon=True, name='PCBHeatmap-session').start()
        return session

    def _session_reader(self, session):
        process = session['process']
        lines = []
        try:
            for line in process.stdout:
                line = line.rstrip()
                lines.append(line)
                del lines[:-80]
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get('type') == 'finished':
                    token = session.get('token')
                    session['token'] = None
                    wx.CallAfter(self._session_finished, token,
                                 int(event.get('code', 0)), list(lines))
                else:
                    wx.CallAfter(self._session_event, session.get('token'), event)
        except Exception as exc:
            lines.append(str(exc))
        wx.CallAfter(self._session_dead, session, list(lines))

    def _session_event(self, token, event):
        if token is None or token is not self.process_token:
            return
        self.worker_event(token, event)

    def _session_finished(self, token, code, lines):
        if token is None or token is not self.process_token:
            return
        self.worker_finished(token, 'analyze', code, lines)

    def _session_dead(self, session, lines):
        token = session.get('token')
        session['token'] = None
        if token is not None and token is self.process_token:
            self.worker_finished(token, 'analyze', -1, lines)

    def start_analysis(self, request):
        if self.process is not None:
            return
        try:
            session = self._ensure_analysis_session()
        except Exception as exc:
            self.error(exc)
            return
        token = self.process_token = object()
        session['token'] = token
        self.process = session['process']
        self.process_mode = 'analyze'
        self.last_log = []
        self.progress.SetValue(0)
        self.busy(True)
        try:
            session['process'].stdin.write(json.dumps(dict(type='analyze', **request)) + '\n')
            session['process'].stdin.flush()
        except (OSError, ValueError) as exc:
            self.error(exc)
            self.process = self.process_token = None
            self.busy(False)

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
        try:
            self.result_dir = paths.new_run_directory()
        except OSError:
            self.error(self.t('runs_unwritable').format(path=paths.runs_root()))
            return
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
        self.start_analysis(dict(board=run_snapshot['path'], scenario=str(path),
                                 output_dir=str(self.result_dir),
                                 cell_mm=float(self.setting_controls['cell_mm'].GetValue()),
                                 max_cells=int(self.node_budget.GetValue())))

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
        self.refresh_result_panel()
        self.record_history()
        if hasattr(self, 'status_pill'):
            self.status_pill.SetLabel(self.t('done'))
            self.status_pill.SetTone('ok')

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
        ramp = self.current_ramp()
        if hasattr(self.canvas, 'set_ramp'):
            self.canvas.set_ramp(ramp)
        self.legend.SetRamp(ramp)
        self.net.Enable(mode in ('density', 'drop') and self.net.GetCount() > 0)
        if not self.result or self.result_dirty or mode == 'board_view':
            self.canvas.clear_overlay()
            self.legend.SetScale(0.0, 1.0, '', ramp)
            if not self.result_dirty:
                self.stats.SetLabel('')
            self.canvas_hint.SetLabel(self.t('hint_' + self.mode))
            self.refresh_result_panel()
            return
        index = max(0, self.net.GetSelection())
        if mode == 'temperature':
            data, units = self.arrays.get('temperature_c'), '\u00b0C'
        elif mode == 'density':
            data, units = self.arrays.get(f'current_density_a_mm2__{index}'), 'A/mm\u00b2'
            voltage = self.arrays.get(f'voltage_v__{index}')
            if data is not None and voltage is not None:
                data = np.where(np.isfinite(voltage), data, np.nan)
        elif mode == 'drop':
            voltage = self.arrays.get(f'voltage_v__{index}')
            reference = self.result.get('source_voltages', self.result.get('source_voltages_v', {})).get(self.net.GetStringSelection(), 0)
            data, units = (None if voltage is None else np.abs(reference - voltage) * 1000), 'mV'
        else:
            joule = self.arrays.get('joule_w')
            data, units = (None if joule is None else joule / self.result['cell_mm'] ** 2), 'W/mm\u00b2'
        if data is None:
            self.canvas.clear_overlay()
            self.legend.SetScale(0.0, 1.0, '', ramp)
            return
        mask = np.asarray(self.arrays.get('board_mask', np.ones(data.shape[-2:], bool)), bool)
        finite = np.isfinite(data) & mask
        if mode == 'power' and 'copper' in self.arrays:
            finite &= self.arrays['copper'] > 0
        if not finite.any():
            self.canvas.clear_overlay()
            self.legend.SetScale(0.0, 1.0, '', ramp)
            return
        scale = (float(data[finite].min()), float(data[finite].max()))
        visible = np.where(finite[layer], data[layer], np.nan) if layer >= 0 else np.max(np.where(finite, data, -np.inf), axis=0)
        valid = mask & np.isfinite(visible)
        self.canvas.set_overlay(visible, valid, units,
                                (self.result['origin_x_mm'], self.result['origin_y_mm']), self.result['cell_mm'],
                                scale=scale, opacity=self.opacity.GetValue() / 100, ramp=ramp)
        self.legend.SetScale(scale[0], scale[1], units, ramp)
        summary = self.result.get('summaries', {})
        if self.is_dc_diagnostic():
            text = self.t('dc_summary').format(temperature=self.result['reference_temperature_c'], power=summary.get('joule_w', 0))
            text += '\n' + self.t('common_scale')
        else:
            hot = summary.get('hotspot', {})
            text = f"{self.t('hottest')}: {summary.get('max_temperature_c', 0):.2f} \u00b0C"
            if hot:
                text += f" \u00b7 {hot.get('layer', '')} \u00b7 X {hot.get('x_mm', 0):.2f}, Y {hot.get('y_mm', 0):.2f} mm"
            text += f"\n{self.t('total_heat')}: {summary.get('total_heat_w', 0):.4g} W \u00b7 {self.t('common_scale')}"
        self.stats.SetLabel(text)
        self.stats.Wrap(max(self.FromDIP(220), self.stats.GetParent().GetClientSize().width - self.FromDIP(420)))
        self.stats.InvalidateBestSize()
        self.canvas_hint.SetLabel(
            f"{self.t(mode)} \u00b7 {self.layer.GetStringSelection() or self.t('all_layers')} \u00b7 {units}")
        self.refresh_result_panel()
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
                entry = dict(identifier=uuid.uuid4().hex, kind=kind,
                             pad_ids=list(identifiers), value=value)
                if kind == 'load':
                    distribution = row.get('distribution', 'area')
                    if distribution not in DISTRIBUTIONS:
                        raise ValueError(self.t('case_error'))
                    entry['distribution'] = distribution
                rows.append(entry)
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
        self._push_undo()
        self.pad_by_id, self.point_contacts, self.rows = meta, contacts, rows
        self.active_source_net = next((meta[row['pad_ids'][0]]['net']
                                      for row in reversed(rows) if row['kind'] == 'source'), '')
        for key, value in new_settings.items():
            self.setting_controls[key].SetValue(value)
        copper = settings.get('copper_um')
        if copper and getattr(self, 'copper_spins', None) and len(copper) == len(self.copper_spins):
            values = [float(entry) for entry in copper]
            if any(not math.isfinite(entry) or not 1 <= entry <= 500 for entry in values):
                raise ValueError(self.t('case_error'))
            for spin, entry in zip(self.copper_spins, values):
                spin.SetValue(entry)
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
