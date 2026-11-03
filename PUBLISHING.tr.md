# PCB Heatmap yayın ve doğrulama durumu

Paket kimliği: `com.github.mey-26.pcb-heatmap`.
Kaynak depo: [MEY-26/pcb-heatmap](https://github.com/MEY-26/pcb-heatmap).
Yazar: Mehmet Emin Yaman — [MEY-26](https://github.com/MEY-26).
Lisans: MIT. Hedef: Windows / KiCad 10.0, `runtime: swig`, test durumu.

## İlk açık yayın

0.3.4, PCB Heatmap'in ilk açık yayınıdır. README'deki eski sürüm başlıkları
önceki açık yayınları değil yerel geliştirmeyi anlatır.

Sürüm etiketi: `v0.3.4`.
Sürüm sayfası: [PCB Heatmap 0.3.4](https://github.com/MEY-26/pcb-heatmap/releases/tag/v0.3.4).
Dosyalar: `PCB_Heatmap-0.3.4-pcm.zip` ve `SHA256SUMS.txt`.

3 Kasım 2026'da `329b61ca07772f853eb4402a2ef6570a21b46ce5` kaynak commit'inden yayımlandı.
[GitHub kaynak CI](https://github.com/MEY-26/pcb-heatmap/actions/runs/41592950688)
Linux hesap/paket ve Windows hesap/arayüz işlerinde başarılı oldu.

[KiCad metadata başvurusu !728](https://gitlab.com/kicad/addons/metadata/-/merge_requests/728) açıldı.
[Fork doğrulama/paketleme](https://gitlab.com/MEY-26/metadata/-/pipelines/3021056773)
ve [başvuru doğrulaması](https://gitlab.com/MEY-26/metadata/-/pipelines/3021058777)
geçti. Başvuru yalnız yeni paketin metadata dosyasını ve 64×64 ikonunu ekler.
Bakımcı incelemesi ve katalog yenilemesi bekleniyor; bu, katalog kabulü değildir.
O zamana kadar ZIP'i **Plugin and Content Manager → Install from File** ile kur.

Açık ZIP indirmesinde SHA-256
`665ae64d0933888f35a984c7631583bce6775f847fcc3ad4f1b84aba260d82fc`,
124800 indirme baytı ve 397198 açılmış kurulum baytı doğrulandı. Resmî yerel
paket/ikon doğrulayıcıları ve v1/v2 metadata şemaları geçti.

## Paket ve değişmez yayın dosyaları

Depo kökünde `python build_pcm.py` çalıştır. Paket metadatası çalışma zamanı
`0.3.4` sürümüyle aynı olmalı; bu paket kimliğini, yalnız sınanan Windows
platformunu ve `runtime: swig` değerini bildirmelidir.

ZIP metadatası indirme alanlarını içermez. Resmî başvuru metadatası açık sürüm
URL'sini, SHA-256'yı, indirme ve açılmış kurulum boyutunu içerir. Başvurmadan
önce açık ZIP'i indirip bunlarla karşılaştır. Yayımlanmış veya hash'i gönderilmiş
paketi değiştirme; içerik değişirse yeni sürüm gerekir.

## Doğrulama kapsamı

`python ci/run_tests.py portable`, `package`, `gui` ve `native` gruplarını ayrı
çalıştır. Arayüz Windows wxPython, yerel grup KiCad 10'un `pcbnew` içeren
Python'unu gerektirir. Çalıştırıcı eksik ortamı testleri sessizce atlamak yerine
hata olarak bildirir. Barındırılan taşınabilir/paket CI, yerel KiCad'i doğrulamaz.

Geliştirme kontrolleri taşınabilir elektrik/ısı denklemleri ve korunumu,
Windows wx seçim/kontrol/ayarları, değişmeyen analiz kopyaları ve geçici sentetik
KiCad kartlarından yerel veri çıkarımını kapsar. Açık testler ve örnekler özel
kullanıcı projeleri içermez. Tamamlanan test sayıları, paket/şema denetimleri ve
kaynak/arşiv kimliği işlemler bitince kaydedilmelidir; bekleyen kontrol başarılı
sayılmaz.

Bunlar yazılım regresyonu ve sayısal tutarlılık testleridir; deneysel PCB
amper kapasitesi doğrulaması veya sertifikasyonu değildir. Çözücü kararlı DC,
2.5D kart sıcaklığı yaklaşımıdır. Jonksiyon/paket modelleri, otomatik PWM ve
anahtarlama kayıpları, radyasyon, kasa/hava akışı CFD'si, soğutucu ve termal
arayüz malzemeleri yoktur. Linux/macOS çalışma zamanı doğrulanmadı. NumPy ve
wxPython kullanıcının KiCad Python'unda önceden bulunmalıdır; otomatik kurulum yoktur.

## Veri ve kaynak sınırları

Eklenti kayıtlı PCB'yi okur ve özel yerel kopyalar üzerinde çalışır. Senaryolar,
tercihler, sayısal diziler ve sonuçlar yereldir. Gerçek PCB/şema dosyaları,
ağ atamaları ve proje ayarları yeniden yazılmaz. Analiz hesap, abonelik,
uzak çözücü veya kart yüklemesi kullanmaz.

Açık depoya yalnız eklenti kaynakları, sentetik testler, doküman ve paket
görselleri eklenmelidir. Commit öncesi dosyaları denetle; kullanıcı PCB/şemaları,
özel senaryolar, analiz sonuçları ve kimlik bilgilerini yayımlama.
