# PCB Heatmap 0.4.0 — interface rebuild and Linux support

The analysis model is unchanged; this release is about understanding it.

- New task-oriented window: a Board / Inputs / Model / Results / Report rail,
  a single top bar, a single action bar and floating canvas overlays replace six
  stacked control bands.
- The window follows the active KiCad PCB colour theme and the desktop accent
  colour (KDE `AccentColor`), with Auto / Dark / Light in the Appearance menu.
  No KiCad window is restyled and no global appearance setting is changed.
- Grouped terminals are explicit: select pads (Ctrl+click, Shift+drag marquee or
  a component click), enter ONE group total, and choose *Equal per pad* (default)
  or *By copper area*. The dialog previews the division per pad and `Split…`
  changes the rule later. Scenarios saved before 0.4.0 keep the 0.3.4 rule.
- Results now state what was analysed: per-net draw and copper loss, copper area,
  via count and worst via current density, mesh cells, iterations, preconditioner,
  geometry/solver/output seconds and the CPU threads used. The Board page reports
  the Python runtime and the run-folder location.
- Selectable colour scales (rainbow remains the default; viridis, inferno, magma,
  turbo, greyscale) that recolour without re-solving.
- Faster repeat runs: the rasterised board is cached by board hash and meshing
  settings (about 7 s of geometry becomes 0.4 s on this board), polygon sampling
  is vectorised with NumPy and only the stackup subtree is parsed instead of the
  whole board file. Speed/precision presets pair the cell size with a solver
  tolerance (1e-6/1e-7/1e-8).
- A persistent analysis worker keeps the meshed board, the thermal multilevel
  preconditioner and warm temperature/voltage guesses between runs: measured
  17.2 s for the first run and 2.6 s for a rerun on a six-layer board after
  changing a load value. The worker ends when the window closes or a run is
  cancelled.
- Panning and zooming with a map displayed blit a whole-board preview bitmap at
  4x the old resolution (6144 px longest edge), copying only the visible source
  rectangle: ~2-5 ms per gesture frame instead of ~350 ms, and zooming out always
  shows the whole board rather than the previous viewport shrinking to a square.
  The bitmap is built once after the board loads and again when a map first
  appears (~0.7 s, ~120 MB); `WORLD_BITMAP_LIMIT` trades memory for detail.
- Per-layer copper foil thickness in the plugin, saved with the scenario.
- Interaction: right-click pad actions, an adaptive selection card, Delete for
  rows (confirming only for four or more), inline value editing, Ctrl+Z/Ctrl+Shift+Z,
  pad role tinting, a marker visibility toggle and a session run history.
- Linux support: `platforms: ["windows", "linux"]` metadata, XDG state/config
  paths with fallbacks when a location is not writable, a runtime probe that
  accepts any interpreter able to import `pcbnew` and `numpy`, and a Linux GUI CI
  job. Windows behaviour is unchanged.

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
