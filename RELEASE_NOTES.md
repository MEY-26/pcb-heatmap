# PCB Heatmap 0.3.4 — first public release

Free, local Windows / KiCad 10.0 SWIG ActionPlugin for interactive multilayer DC
and estimated steady-state board-temperature maps. This is PCB Heatmap's first
public release.

- Click pads, copper points or matching component pads to assign voltage sources,
  current-load groups and optional known component losses.
- Include saved filled zones, tracks, pads, via plating/spans and physical
  stackup. Inspect temperature, current density, voltage deviation and copper
  loss by layer/net while all modeled layers remain in the coupled solve.
- Analyze private saved-board snapshots without changing the real PCB, pad nets
  or schematic. Save scenarios and retain calculation/material settings.
- English/Turkish UI, light controls, visibility toggles, grouped selection,
  multiple assignment rows and the new project/toolbar icons are included.
- When thermal solving fails, independently valid reference-temperature DC maps
  remain clearly marked; an invalid temperature map is not presented as a result.

This is an engineering prototype for comparison, not certified ampacity or a
validated operating-current rating. It does not model junction temperature,
automatic PWM/switching losses, CFD, radiation, heatsinks or thermal-interface
materials. Component heat must be entered from independent loss estimates.
Material, cooling and mesh assumptions require checking against real construction
and measurements. A large convection value is not a measured heatsink model.

Regression checks cover portable equations/conservation, Windows wx controls and
native extraction from temporary synthetic KiCad fixtures. They do not constitute
physical validation of a manufactured PCB. Linux/macOS runtime is unverified.
No private user board or schematic is distributed.

Download `PCB_Heatmap-0.3.4-pcm.zip` and use **KiCad Plugin and Content Manager →
Install from File…**. NumPy and wxPython must already exist in KiCad's Python;
the plugin does not install dependencies. Relaunch the plugin after updating.
Official KiCad catalogue review and refresh are a separate, pending process.

## Türkçe

PCB Heatmap'in ilk açık yayınıdır: Windows / KiCad 10.0 için ücretsiz, yerel
SWIG ActionPlugin.

Kart görünümünde pad, bakır noktası veya aynı ağdaki komponent padlerini seçip
gerilim kaynağı, toplam akım yükü ve bilinen komponent kaybı atanabilir. Kayıtlı
bakır dolgular, yollar, padler, via kaplaması/katman aralığı ve fiziksel stackup
hesaba katılır. Bütün katmanlar çözümde kalırken sıcaklık, akım yoğunluğu,
gerilim sapması ve bakır kaybı katman/ağ bazında görüntülenir.

Analiz, gerçek PCB, pad ağları ve şemayı değiştirmeyen özel kayıtlı-kart
kopyalarında çalışır. Senaryolar ve hesap/malzeme ayarları saklanabilir.
İki dilde açık arayüz, görünürlük seçenekleri, çoklu seçim/atama ve yeni ikonlar
dahildir. Sıcaklık çözülemediğinde geçerli referans-sıcaklık DC haritaları ayrı
etiketlenir; geçersiz sıcaklık haritası sonuç gibi gösterilmez.

Bu karşılaştırma prototipi, onaylı amper kapasitesi veya doğrulanmış çalışma
akımı sınırı vermez. Jonksiyon sıcaklığı, otomatik PWM/anahtarlama kayıpları,
CFD, radyasyon, soğutucu ve termal arayüz malzemeleri modellenmez. Komponent
kayıpları bağımsız hesapla girilir; malzeme, soğutma ve ızgara gerçek üretim ve
ölçümlerle kontrol edilmelidir. Büyük taşınım katsayısı ölçülmüş soğutucu değildir.

Taşınabilir hesap/korunum, Windows wx arayüz ve geçici sentetik KiCad örneklerinde
yerel çıkarım regresyonları bulunur. Bunlar üretilmiş kartın fiziksel
doğrulaması değildir. Linux/macOS çalışma zamanı doğrulanmadı. Kullanıcının
özel PCB veya şeması yayımlanmaz.

`PCB_Heatmap-0.3.4-pcm.zip` paketini **Plugin and Content Manager → Install from
File…** ile kur. KiCad Python'unda NumPy ve wxPython önceden bulunmalıdır;
eklenti bağımlılık kurmaz. Güncellemeden sonra eklentiyi yeniden aç.
Resmî KiCad katalog incelemesi ve yenilenmesi ayrı süreç olarak bekleniyor.
