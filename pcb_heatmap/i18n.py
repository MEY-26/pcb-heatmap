"""Small explicit English / Turkish catalog; English is the initial language."""
TEXT = {
    'title': ('PCB Heatmap', 'PCB Isı Haritası'),
    'subtitle': ('Local, read-only DC and steady-state thermal analysis', 'Yerel, salt okunur DC ve kararlı durum ısıl analizi'),
    'language': ('Language / Dil', 'Language / Dil'),
    'saved_only': ('Analyses use the saved PCB. Save in KiCad, then Reload. The source PCB is never modified.', 'Analiz kaydedilmiş PCB ile yapılır. KiCad’de kaydet, ardından Yenile. Kaynak PCB değiştirilmez.'),
    'browse': ('Open saved PCB…', 'Kayıtlı PCB aç…'),
    'reload': ('Reload saved PCB', 'Kayıtlı PCB’yi yenile'),
    'no_board': ('No saved PCB loaded.', 'Kayıtlı PCB yüklenmedi.'),
    'inspect': ('Reading saved PCB…', 'Kayıtlı PCB okunuyor…'),
    'source': ('Add voltage source', 'Gerilim kaynağı ekle'),
    'load': ('Add current load', 'Akım yükü ekle'),
    'heat': ('Add component heat (optional)', 'Komponent ısısı ekle (isteğe bağlı)'),
    'capture_hint': ('1. Select input pads, then add a voltage source.\n2. Select different output pads on the SAME net, then add a current load.\nTracks, vias and filled zones are included automatically.', '1. Giriş padlerini seç, gerilim kaynağı ekle.\n2. AYNI ağdaki farklı çıkış padlerini seç, akım yükü ekle.\nYollar, vialar ve dolgulu zone’lar otomatik alınır.'),
    'manual': ('Choose pads manually', 'Padleri elle seç'),
    'selected': ('Use PCB selection', 'PCB seçimini kullan'),
    'kind': ('Kind', 'Tür'),
    'net': ('Net', 'Ağ'),
    'pads': ('Pads', 'Padler'),
    'value': ('Group total', 'Toplam'),
    'remove': ('Remove selected', 'Seçileni kaldır'),
    'remove_all': ('Remove all', 'Tümünü kaldır'),
    'group_hint': ('Each row is a group total, not a per-pad value. +A draws current; −A injects it. For a return net, use a 0 V source and negative load current. Add source/load pairs for every analysed net.', 'Her satır pad başına değil grup toplamıdır. +A akım çeker; −A akım verir. Dönüş ağı için 0 V kaynak ve negatif yük akımı kullan. Her analiz ağına kaynak/yük çifti ekle.'),
    'settings': ('Physical settings', 'Fiziksel ayarlar'),
    'terminals': ('Sources and loads', 'Kaynaklar ve yükler'),
    'ambient': ('Ambient (°C)', 'Ortam (°C)'),
    'conv_top': ('Top convection (W/m²K)', 'Üst yüz taşınımı (W/m²K)'),
    'conv_bottom': ('Bottom convection (W/m²K)', 'Alt yüz taşınımı (W/m²K)'),
    'plating': ('Via wall copper (µm)', 'Via duvar bakırı (µm)'),
    'grid': ('Grid cell (mm)', 'Hücre boyu (mm)'),
    'fr4': ('Substrate conductivity (W/mK)', 'Yalıtkan taban ısı iletkenliği (W/mK)'),
    'substrate_xy': ('Substrate k XY (W/mK)', 'Yalıtkan taban k XY (W/mK)'),
    'substrate_z': ('Substrate k Z (W/mK)', 'Yalıtkan taban k Z (W/mK)'),
    'substrate_material': ('Board substrate', 'Kart taban malzemesi'),
    'material_custom': ('Other / custom insulator', 'Diğer / özel yalıtkan'),
    'material_fr4': ('FR4', 'FR4'),
    'material_ceramic': ('Ceramic', 'Seramik'),
    'material_metal_core': ('Aluminium / metal core (DC only)', 'Alüminyum / metal çekirdek (yalnız DC)'),
    'substrate_hint': ('Enter the material datasheet values: XY spreads heat along the board; Z transfers it between layers. For an isotropic material, enter the same value twice. Choosing a material does not supply measured values.', 'Malzemenin veri sayfasındaki değerleri gir: XY kart boyunca, Z katmanlar arasında ısı iletir. İzotropik malzemede iki değeri aynı gir. Malzeme seçimi ölçülmüş bir değer atamaz.'),
    'metal_core_hint': ('DC maps are available. Thermal analysis of a metal-core board requires a separate metal base and thin insulating layer, which this model does not yet represent. Do not enter bulk aluminium conductivity as the insulator value.', 'DC haritaları kullanılabilir. Metal çekirdekli kartın sıcaklık hesabı, ayrı metal taban ve ince yalıtkan gerektirir; mevcut model bunları henüz temsil etmez. Yalıtkan değerine alüminyumun iletkenliğini yazma.'),
    'preferences_hint': ('Calculation settings are saved automatically for the next launch.', 'Hesap ayarları sonraki açılış için otomatik saklanır.'),
    'settings_save_error': ('Calculation settings could not be saved to the user folder.', 'Hesap ayarları kullanıcı klasörüne kaydedilemedi.'),
    'ok': ('OK', 'Tamam'),
    'copper': ('Copper conductivity (W/mK)', 'Bakır ısı iletkenliği (W/mK)'),
    'temp_limit': ('Temperature marker (°C)', 'Sıcaklık sınır işareti (°C)'),
    'drop_limit': ('Drop marker (V)', 'Gerilim düşümü sınırı (V)'),
    'limit_hint': ('Markers flag results; they do not constitute a validated current rating.', 'Sınır işaretleri sonuçları belirtir; doğrulanmış akım kapasitesi anlamına gelmez.'),
    'scope': ('Steady DC approximation. Includes board-layer heat spreading and copper Joule loss. Add component losses separately. This does not model switching waveforms, airflow fields or semiconductor junction temperature.', 'Kararlı DC yaklaşımı. Katmanlar arası ısı yayılımı ve bakır Joule kaybı hesaba katılır. Komponent kayıpları ayrıca girilir. Anahtarlama dalga şekilleri, hava akışı alanı ve yarı iletken jonksiyon sıcaklığı modellenmez.'),
    'run': ('Analyse saved PCB', 'Kayıtlı PCB’yi analiz et'),
    'cancel': ('Cancel', 'İptal'),
    'results': ('Results folder', 'Sonuç klasörü'),
    'temperature': ('Temperature · °C', 'Sıcaklık · °C'),
    'density': ('Current density · A/mm²', 'Akım yoğunluğu · A/mm²'),
    'drop': ('Voltage deviation |ΔV| · mV', 'Gerilim sapması |ΔV| · mV'),
    'layer': ('Layer', 'Katman'),
    'all_layers': ('All layers · maximum', 'Tüm katmanlar · en yüksek'),
    'empty_view': ('Load a saved PCB, select source/load pads, then run the analysis.\nHidden layers remain included in the calculation.', 'Kayıtlı PCB yükle, kaynak/yük padlerini seç ve analizi çalıştır.\nGizlenen katmanlar hesapta kalır.'),
    'no_values': ('No finite values for this view.', 'Bu görünümde geçerli değer yok.'),
    'ready': ('Ready.', 'Hazır.'),
    'complete': ('Analysis complete. Display filters never change the solution.', 'Analiz tamamlandı. Görünüm filtreleri hesabı değiştirmez.'),
    'cancelled': ('Analysis cancelled. Source PCB unchanged.', 'Analiz iptal edildi. Kaynak PCB değiştirilmedi.'),
    'error': ('PCB Heatmap', 'PCB Isı Haritası'),
    'save_first': ('Save the PCB in KiCad first, then Reload. This tool reads the saved file only.', 'Önce PCB’yi KiCad’de kaydet, ardından Yenile. Bu araç yalnız kaydedilmiş dosyayı okur.'),
    'changed': ('The saved PCB has changed. Reload before adding terminals or analysing.', 'Kayıtlı PCB değişti. Pad eklemeden veya analizden önce Yenile.'),
    'switched': ('The active KiCad board is different. Open/Reload that board before capturing its selection.', 'Etkin KiCad kartı farklı. Seçimini almadan önce o kartı Aç/Yenile ile yükle.'),
    'selection_empty': ('Select the source/load pads or their footprints. Tracks and filled zones are read automatically; they are not terminal selections. You can also choose pads manually.', 'Kaynak/yük padlerini veya footprintlerini seç. Yollar ve dolgulu zone’lar otomatik okunur; uç seçimi olarak kullanılmaz. Padleri elle de seçebilirsin.'),
    'terminal_overlap': ('These pads are already used as both source and load: {pads}.\n\nThe source is where current enters this copper net; the load must be DIFFERENT pads on the SAME net, where current leaves it. Select the other pads in KiCad before adding the load. Reducing the grid size will not fix using the same pad twice.', 'Şu padler hem kaynak hem yük olarak seçilmiş: {pads}.\n\nKaynak, akımın bu bakır ağa girdiği yerdir. Yük için AYNI ağda, akımın çıktığı FARKLI padleri seçmelisin. Yük eklemeden önce KiCad’de diğer padleri seç. Aynı padi iki kez kullanmak hücre boyunu küçülterek düzelmez.'),
    'terminal_cells_overlap': ('Different source/load pads share the same calculation cells. Choose physically separate terminals or use a finer grid. Filled zones remain included automatically.', 'Kaynak ve yük padleri aynı hesap hücrelerine denk geliyor. Fiziksel olarak ayrı uçlar seç veya hücre boyunu küçült. Dolgulu zone’lar hesaba otomatik katılır.'),
    'board_summary': ('{file} · {layers} layers · {pads} pads · {zones} copper zones ({filled} filled) · {sha}', '{file} · {layers} katman · {pads} pad · {zones} bakır zone ({filled} dolgulu) · {sha}'),
    'usage': ('Help', 'Kullanım'),
    'usage_text': ('1. In KiCad, refill zones (B) and save. Reload the saved PCB here.\n\n2. Select the input pads or a copper point on the PCB and add the actual source voltage. New value fields are empty.\n\n3. Clear that selection, then select DIFFERENT receiving pads or a copper point on the SAME net. Enter the TOTAL current drawn by that group. Different nets need separate source/load pairs.\n\n4. Component heat is optional: enter actual device losses in watts. Copper/via I²R losses are calculated automatically.\n\n5. Run the analysis. Choose a layer and temperature, current density or voltage deviation. All layers remain coupled.\n\nTracks, vias and saved filled zones are read automatically. For a return net, use a 0 V source and return loads with negative current. Ctrl-click or Shift-click list rows to select several assignments; remove them together or edit a selection of one kind.', '1. KiCad’de B ile zone’ları doldur ve kaydet. Burada kayıtlı PCB’yi yenile.\n\n2. PCB’de giriş padlerini veya bir bakır noktasını seçip gerçek kaynak gerilimini ekle. Yeni değer alanları boştur.\n\n3. Seçimi temizle; AYNI ağda akımı alacak FARKLI padleri veya bir bakır noktasını seç. Grup TOPLAM akımını gir. Farklı ağlar için ayrı kaynak/yük çiftleri ekle.\n\n4. Komponent ısısı isteğe bağlıdır: parçanın kendi kaybını watt olarak girersin. Bakır/via I²R kayıpları otomatik hesaplanır.\n\n5. Analizi çalıştır; katmanı ve sıcaklık, akım yoğunluğu veya gerilim sapması görünümünü seç. Tüm katmanlar hesaba birlikte katılır.\n\nYollar, vialar ve kayıtlı dolgulu zone’lar otomatik okunur. Dönüş ağında 0 V kaynak ve negatif akımlı dönüş yükleri kullan. Listede Ctrl veya Shift ile birden fazla satır seç; birlikte kaldır veya tek türden seçili atamaları birlikte düzenle.'),
    'choose_pads': ('Choose pads explicitly', 'Padleri açıkça seç'),
    'choose_hint': ('Only checked pads are added. Selecting a footprint does not automatically add all its pads.', 'Yalnız işaretlenen padler eklenir. Footprint seçmek bütün padlerini otomatik eklemez.'),
    'filter': ('Filter reference / pad / net', 'Referans / pad / ağ filtresi'),
    'check_visible': ('Check visible', 'Görünenleri işaretle'),
    'uncheck': ('Uncheck all', 'İşaretleri kaldır'),
    'next': ('Continue', 'Devam'),
    'single_net': ('A source or current-load group must contain pads on one net. Add separate rows for different nets.', 'Bir kaynak veya akım yükü grubu tek ağdaki padlerden oluşmalı. Farklı ağlar için ayrı satır ekle.'),
    'empty_net': ('Electrical terminals require a named connected net.', 'Elektriksel uçlar adlandırılmış bağlı bir ağ gerektirir.'),
    'source_value': ('Source voltage (V)', 'Kaynak gerilimi (V)'),
    'load_value': ('Total group current (A)', 'Grup toplam akımı (A)'),
    'heat_value': ('Total group heat (W)', 'Grup toplam ısısı (W)'),
    'invalid': ('Enter a finite number. Current must be nonzero and heat must be positive.', 'Sonlu bir sayı gir. Akım sıfırdan farklı, ısı pozitif olmalı.'),
    'needs_case': ('Add at least one voltage source and one current load, or one component heat group.', 'En az bir gerilim kaynağı ve akım yükü veya bir komponent ısı grubu ekle.'),
    'missing_pair': ('Every electrically analysed net needs at least one source and current load: ', 'Elektriksel analizdeki her ağ en az bir kaynak ve akım yükü gerektirir: '),
    'inspect_done': ('Saved PCB loaded. Previous terminal rows were cleared.', 'Kayıtlı PCB yüklendi. Önceki pad grupları temizlendi.'),
    'close_running': ('A worker is running. Cancel it and close this window?', 'Bir hesaplama çalışıyor. İptal edip pencere kapatılsın mı?'),
    'hottest': ('Hottest', 'En sıcak'),
    'peak': ('View peak', 'Görünüm tepe değeri'),
    'warnings': ('Model notes', 'Model notları'),
    'save_case': ('Save case…', 'Senaryoyu kaydet…'),
    'load_case': ('Load case…', 'Senaryo yükle…'),
    'case_board': ('This case belongs to a different saved board. Load the matching PCB first.', 'Bu senaryo farklı bir kayıtlı karta ait. Önce eşleşen PCB’yi yükle.'),
    'total_heat': ('Total heat', 'Toplam ısı'),
    'joule': ('Copper loss', 'Bakır kaybı'),
    'component_heat': ('Component heat', 'Komponent ısısı'),
    'common_scale': ('One scale for all layers', 'Tüm katmanlar aynı ölçekte'),
    'grid_short': ('Grid', 'Hücre'),
    'board_info': ('layers · pads', 'katman · pad'),
    'via_peak': ('Highest via current', 'En yüksek via akımı'),
}


def tr(key, language='en'):
    pair = TEXT.get(key)
    return pair[1 if language == 'tr' else 0] if pair else key


def format_analysis_error(code, details, language='en'):
    """Translate structured solver failures without inferring a safe result.

    Draw and injection totals are kept separate for each net. In particular,
    negative return current is not subtracted from another net's load. This formatter
    neither changes current assignments nor turns an invalid solve into a map.
    Unknown codes return None so callers can retain their existing fallback.
    """
    import math

    if code == 'unsupported_metal_core':
        return tr('metal_core_hint', language)
    if code == 'unsupported_via_substrate_conductivity':
        return ('This via approximation requires substrate conductivity Z to be no greater than copper conductivity. No temperature prediction is available.'
                if language != 'tr' else 'Mevcut via yaklaşımı, tabanın Z iletkenliğinin bakır iletkenliğinden büyük olmamasını gerektirir. Sıcaklık tahmini üretilemedi.')

    aliases = {'nonfinite': 'electrothermal_nonfinite',
               'nonconvergence': 'electrothermal_nonconvergence'}
    code = aliases.get(code, code)
    if code not in {'electrothermal_outside_validity', 'electrothermal_nonfinite',
                    'electrothermal_nonconvergence'}:
        return None
    details = details if isinstance(details, dict) else {}
    turkish = language == 'tr'

    def number(value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return f'{value:g}' if math.isfinite(value) else None

    iteration = number(details.get('iteration'))
    where = (f' ({iteration}. tur)' if turkish else f' (iteration {iteration})') if iteration else ''
    lines = ['Elektrotermal hesap durduruldu; geçerli bir sıcaklık haritası oluşturulamadı.' if turkish else
             'Electrothermal calculation stopped; no valid temperature map is available.']
    if code == 'electrothermal_outside_validity':
        limit = number(details.get('model_limit_c')) or '1500'
        lines.append((f'Model{where}, {limit} °C hesap geçerlilik sınırını aştı. '
                      'Bu eşik, gerçek kartın ulaşacağı sıcaklık tahmini değildir.') if turkish else
                     (f'The model exceeded its {limit} °C validity cutoff{where}. '
                      'This cutoff is not a prediction of the actual board temperature.'))
    elif code == 'electrothermal_nonfinite':
        lines.append(('Hesapta geçerli sayısal sıcaklık elde edilemedi' + where + '.') if turkish else
                     ('The temperature calculation produced nonfinite values' + where + '.'))
    else:
        lines.append(('Sıcaklık geri beslemesi sabit bir sonuca ulaşmadı' + where + '.') if turkish else
                     ('Temperature feedback did not converge' + where + '.'))

    net_loads = details.get('net_loads', [])
    if isinstance(net_loads, list):
        rows = []
        for item in net_loads:
            if not isinstance(item, dict):
                continue
            net = str(item.get('net', '') or ('(ağ yok)' if turkish else '(no net)'))
            count = number(item.get('group_count'))
            draw, injection = number(item.get('draw_a')), number(item.get('injection_a'))
            if draw is None or injection is None:
                continue
            groups = (f'{count} grup; ' if turkish else f'{count} groups; ') if count else ''
            rows.append((f'{net}: {groups}çekilen {draw} A; verilen {injection} A.') if turkish else
                        (f'{net}: {groups}draw {draw} A; injection {injection} A.'))
        if rows:
            lines.extend(['', 'Atanan akımlar (her ağ ayrı):' if turkish else 'Assigned currents (each net separately):', *rows])

    loss = number(details.get('reference_joule_w'))
    top, bottom = number(details.get('convection_top')), number(details.get('convection_bottom'))
    if loss is not None:
        lines.extend(['', (f'Referans sıcaklıktaki bakır kaybı: {loss} W.' if turkish else
                           f'Copper loss at the reference temperature: {loss} W.')])
        if top is not None and bottom is not None:
            lines.append((f'Modelde üst/alt taşınım: {top} / {bottom} W/m²K.' if turkish else
                          f'Model top/bottom convection: {top} / {bottom} W/m²K.'))

    lines.extend(['',
        ('Her yük satırı ek bir grup akımıdır; akım diğer satırlara otomatik bölünmez. '
         'Yinelenen yükleri ve amaçlanan grup toplamlarını kontrol et.') if turkish else
        ('Each load row adds its group current; it is not automatically divided among other rows. '
         'Check duplicate loads and intended group totals.'),
        ('Bakır geometrisini, hücre boyunu, üst/alt taşınımı ve girilen komponent kayıplarını kontrol et. '
         'Girdiler değiştirilmedi; geçersiz sonuç sınırlandırılıp gösterilmedi.') if turkish else
        ('Review copper geometry, mesh size, top/bottom convection and assigned component losses. '
         'Inputs were not changed; invalid results were not clamped or displayed.')])
    return '\n'.join(lines)
