# PCB Heatmap 0.3.4

![PCB Heatmap logosu](docs/icon-preview.png)

Çok katmanlı DC akım dağılımı, gerilim düşümü, bakır kaybı ve tahmini kararlı
**kart sıcaklığı** için ücretsiz, yerel çalışan KiCad 10 eklentisi. Kaynak,
yük ve komponent ısısını kayıtlı PCB görünümüne tıklayarak tanımla; renkli
haritaları katman ve ağ bazında incele. İngilizce ve Türkçe arayüz bulunur.

**0.3.4 ilk açık yayındır.** Windows / KiCad 10.0 SWIG ActionPlugin test
sürümüdür.

Bu bir karşılaştırma ve sıcak nokta araştırma prototipidir; **onaylı amper
kapasitesi hesabı veya doğrulanmış çalışma akımı sınırı değildir**. Kart
sıcaklığını tahmin eder, yarıiletken jonksiyon sıcaklığını vermez. PWM/anahtarlama
kayıplarını kendiliğinden hesaplamaz; hava akışı CFD'si, radyasyon, soğutucu ve
termal arayüz malzemelerini modellemez. Bilinen komponent kayıplarını gir;
kabulleri, daha ince ızgara sonuçlarını ve bağımsız ölçümleri kontrol et.

Analiz bilgisayarda yerel çalışır; hesap, abonelik, haricî çözücü veya başka
bir KiCad analiz eklentisi gerekmez. Kart verileri gönderilmez. NumPy ve
wxPython, KiCad Python'unda önceden bulunmalıdır; eklenti paket kurmaz.

[English](README.md) · [Sürümler](https://github.com/MEY-26/pcb-heatmap/releases) · [Hata bildir](https://github.com/MEY-26/pcb-heatmap/issues)

## Kurulum

`PCB_Heatmap-0.3.4-pcm.zip` dosyasını
[0.3.4 sürüm sayfasından](https://github.com/MEY-26/pcb-heatmap/releases/tag/v0.3.4)
indir. KiCad Proje Yöneticisi'nde **Plugin and Content Manager → Install from
File / Dosyadan Kur** yoluyla bu ZIP'i seç. Varsayılan katalog kabulü ayrı bir
süreçtir; [yayın durumuna bak](PUBLISHING.tr.md). Metadata kabul edilip katalog
yenilenmeden eklentinin resmî katalog aramasında bulunacağını varsayma.

Diğer seçenek, bu depodaki `pcb_heatmap` klasörünü
`%APPDATA%/kicad/10.0/scripting/plugins/pcb_heatmap` konumuna kopyalamaktır.
Mevcut kurulumu önce eklentilerin tarandığı klasörün dışında yedekle. Aynı anda
iki kurulum yöntemini kullanma; çift araç çubuğu düğmesi oluşabilir.

Action Plugins listesini yenile veya PCB editörünü yeniden aç; **Tools →
External Plugins → PCB Heatmap** yolundan başlat. Güncellemeden sonra eklenti
penceresini kapatıp yeniden aç. 24 ve 48 piksellik araç çubuğu simgelerinin
yanında ayrı 64 piksellik katalog ikonu bulunur. Bu sürüm KiCad 10'un yerel
Python ActionPlugin arayüzünü kullanır; IPC eklentisi değildir. Test edilen
Windows KiCad 10 Python'unda NumPy ve wxPython bulunur. Linux/macOS çalışma
zamanı doğrulanmadığından paket metadatasında bu platformlar ilan edilmez.

## Doğrudan kart görünümü üzerinden kullanım

Ana görünümde kayıtlı PCB'nin padleri, yolları, viaları, dolu zone alanları
ve komponent referansları gösterilir. Katman seçerek o katmanın bakırını
inceleyebilirsin. Dolu zone alanları otomatik okunur; analiz noktası koymak
için zone üzerindeki bakıra da tıklayabilirsin. Kart bilgisinde zone sayıları yer
alır. Boş veya güncel olmayan dolgular için KiCad'de **B** tuşuna basıp
kaydetmek ve eklentide kartı yeniden okumak gerekir.

Pad adı yazmak yerine görünümdeki atama modlarını kullan:

- **Kaynak V:** modu seç, kart üzerindeki bir pade veya bakır noktasına
  tıkla; kaynak gerilimini gir.
- **Yük A:** modu seç, aynı ağdaki başka bir pade veya bakır noktasına
  tıkla; o noktadan çekilecek toplam akımı gir.
- **Isı W:** gerekiyorsa bir konuma tıklayıp komponentin gerçek kaybını gir.
  Isı noktası FR4 üzerinde de olabilir; elektriksel uç oluşturmaz.
- **Seç:** Ctrl tuşuyla birden fazla pade tıkla, ardından bir atama modu seç.
  Girdiğin tek değer seçili pad grubunun tamamına uygulanır. Seçim bütün ağa
  otomatik genişletilmez.

Kaynak, yük ve ısı işaretleri doğrudan PCB üzerinde görünür. Mevcut işarete
tıklayarak değerini düzenleyebilirsin. Yandaki listeden de atamalar
düzenlenebilir veya kaldırılabilir; **Tümünü kaldır** seçeneği de vardır.
Senaryoyu kaydedip yüklemek hem pad gruplarını hem koordinatla tanımlanan
noktasal temasları korur.

Bu görünüm analiz düzenleyicisidir: kaynak PCB'yi, gerçek pad geometrisini,
ağ atamalarını veya şemayı değiştirmez.

## İlk kullanım

**Kaynak ve yük için farklı fiziksel padler seçilir.** Kaynak, akımın bakır
ağa girdiği; yük ise aynı ağdan çıktığı yerdir. Aynı padi hem kaynak hem yük
olarak eklemek kart üzerinde bir akım yolu tanımlamaz ve hata verir.

Bir güç dağıtım ağında iki uçlu basit bir örnek:

1. KiCad'de **B** tuşuna bas, kartı kaydet; eklentide **Kayıtlı PCB'yi yenile**
   düğmesini kullan. Katman kalınlıklarını ve uyarıları kontrol et. Dosyada
   açık bakır/dielektrik stackup tanımı bulunmalıdır.
2. **Kaynak V** modunu seç. Eklentinin kart görünümünde giriş padine tıkla;
   gerçek kaynak gerilimini gir. **5 V** yalnız örnektir, varsayılan değildir.
3. **Yük A** modunu seç. Aynı ağda, akımı çeken devrenin yanında bulunan
   **başka bir fiziksel pade** tıkla ve toplam akımı gir. **1 A** yalnız
   örnektir, varsayılan değildir. Başka ağdaki bir çıkış için ayrı kaynak/yük
   çifti gerekir.
4. Bu ilk bakır yol analizinde **komponent ısısını boş bırak** ve analizi
   çalıştır. İki uç arasındaki kayıtlı bakır dolgular, yollar, padler ve via
   bağlantıları otomatik hesaba katılır.

Kaynak/yük çakışması hatasında yanlış yük satırını kaldırıp diğer fiziksel
padle tekrar ekle. Padler gerçekten ayrı olduğu halde ızgara hücreleri
çakışıyorsa daha ince ızgara kullan. Aynı padi kaynak ve yük olarak seçmek,
ızgarayı incelterek düzeltilemez.

Doğrudan bakır üzerine tıklamak, o koordinat ve katmanda **sanal analiz
teması** oluşturur. Bu temas gerçek pad değildir; çözünmüş ızgarada tek hücre
kaplar. Fiziksel bağlantıyı bir pad temsil ediyorsa o padi kullan. Noktasal
temaslarda, özellikle dar bakır veya başka bir uç yakınında, ızgarayı
incelterek sonucu kontrol et. Kaynak ve yük aynı padi veya aynı çözünmüş
temas hücresini paylaşamaz.

## Gezinme ve sonuçlar

Tekerlek, imlecin bulunduğu noktaya göre yakınlaştırır. Orta veya sağ fare
tuşunu basılı tutup sürükleyerek kartı kaydırabilirsin. **Sığdır** bütün
kartı yeniden gösterir. Referans araması, pad atamadan önce komponenti
bulmayı kolaylaştırır.

Analiz sonrasında sıcaklık (°C), akım yoğunluğu (A/mm²) veya gerilim
sapmasının büyüklüğü (mV), PCB ile hizalı renkli katman olarak gösterilir.
Katman ve ağ filtreleri yalnız **görünümü** değiştirir; bütün katmanlar ve
komşu bakırlar termal hesapta kalır. Aynı sonuç ve gösterim türünde renk
ölçeği katmanlar arasında ortaktır.

Ortam sıcaklığını, üst/alt taşınım katsayısını, via duvar bakırını, ızgara
aralığını ve düğüm bütçesini fiziksel ayarlardan belirle. Via duvar kalınlığı
katman bakırından bağımsızdır; sabit amper/via kuralı kullanılmaz. Daha ince
ızgarayla tekrarlayıp sonucun ve sıcak noktanın kararlı kaldığını kontrol et.
Çözülemeyen temaslar ve bağlantısız yollar hata verir; sahte bağlantı kurulmaz.

KiCad'deki PCB seçimini alma ve elle pad seçme seçenekleri alternatif olarak
kullanılabilir. Ana akış kart görünümündeki tıklamalardır. Analiz her durumda
KiCad'deki kaydedilmemiş değişiklikleri değil kayıtlı dosyayı kullanır.

## Taban malzemesi ve ısı iletkenliği

Termal taban malzemesi **FR4**, **seramik** veya **özel yalıtkan malzeme**
olarak seçilebilir. Malzeme türü yapıyı tanımlar; seçim sayısal iletkenliği
kendiliğinden doldurmaz veya kullanıcının değerlerini değiştirmez. Üreticinin
**W/(m·K)** cinsinden verdiği ısı iletkenliğini **kart düzlemi (XY)** ve
**katmanlar arası (Z)** için ayrı gir. İki alana aynı sayı ancak izotropik
malzeme yaklaşımı uygunsa yazılır. KiCad'deki dielektrik sabiti ve kayıp
tanjantı elektriksel özelliklerdir; bu ısıl değerleri sağlamaz.

Model, bakır dışındaki taban hacminin tamamında bu iki sabit değeri kullanır.
Farklı derinliklerde farklı dielektrikler, yapıştırıcı katmanları ve malzemenin
sıcaklığa bağlı özellikleri ayrı modellenmez. Fiziksel bakır/dielektrik
kalınlıkları kayıtlı KiCad stackup'ından alınmaya devam eder. Yalnız `fr4_k`
içeren eski senaryolarda bu sayı iki yönde de aynen korunur; geçmişten kalan
bu kayıt anahtarı artık genel taban malzemesinin XY iletkenliğini ifade eder.

**Alüminyum / metal çekirdekli PCB** desteklenmeyen yapı olarak gösterilir.
İnce elektriksel yalıtkan ile ayrı metal tabanın farklı fiziksel katmanlar
olarak modellenmesi gerekir. Bütün tabana alüminyumun k değerini vermek
yanıltıcı bir ısı yolu oluşturacağından bu yapı için termal sonuç üretilmez.
Elektriksel yollar geçerliyse, girilen ortam referans sıcaklığındaki DC
gerilim, akım yoğunluğu ve bakır kayıp haritaları yine incelenebilir; bunlar
sıcaklık geri beslemesini veya komponent ısısını içermez.
Alüminyum nitrür (**AlN**) elektriksel olarak yalıtkan bir seramiktir ve seramik
grubuna girer; alüminyum metal tabanlı PCB ile aynı değildir. Via bulunan
kartlarda mevcut via duvarı yaklaşımı, Z iletkenliğinin girilen bakır
iletkenliğinden yüksek olmamasını da gerektirir.

Üreticilerin yapı açıklamaları: [CeramTec seramik tabanlar](https://www.ceramtec-industrial.com/en/products-applications/substrates/aln-substrates)
ve [TCLAD yalıtılmış metal tabanlar](https://tclad.com/products/insulated-metal-substrate/).
Bu kaynaklar malzeme ailelerini açıklar; otomatik hazır değer listesi değildir.

## Girilen değerlerin anlamı

Bir kaynak/yük grubu tek ağa ait olmalıdır. Farklı ağlar için ayrı uçlar
tanımlanır. Pozitif yük akımı ağdan çekilir, negatif değer ağa akım verir.
GND dönüşü için konnektörde 0 V referans, fiziksel olarak ayrı dönüş
padlerinde negatif akım kullanılabilir.

**Komponent ısısı isteğe bağlıdır.** Yalnız kartı ısıtan bilinen komponent
kaybını ekle; rastgele ısı değeri girmek gerekmez. Yüke aktarılan güç PCB ısısı
değildir. Bakır/via kayıplarını çözücü zaten hesaplar; aynı kayıpları elle
ısı kaynağı olarak tekrar ekleme.

Amper/watt değeri seçili grubun toplamıdır; pad sayısıyla çarpılmaz. Dört
ayrı yük grubuna 1'er A yazmak ortak beslemeden **toplam 4 A**
çeker. Dört yük konumunu tek grupta seçip 1 A yazmak ise **toplam 1 A**
anlamına gelir; her konuma 1 A uygulanmaz. Bu sürümde yükler sabit DC
akımıyla tanımlanır. Direnç/sabit güç yükü,
regülatör, kontakt direnci, anahtarlama dalga şekli ve anahtarlama elemanlarının
otomatik devre modelleri henüz yoktur.

Gerilim, elektriksel referansı ve gösterilen gerilim seviyelerini belirler.
Akımın elle belirlendiği bu modelde yolun ısınması **I²R** kaybından
hesaplanır; kaynak gerilimi × yük akımı, yüke aktarılan güçtür ve PCB'de oluşan ısı
olarak kullanılmaz.

## Hesap ve sınırlar

Aktif netlerin bakır geometrisinden çok katmanlı direnç ağı kurulur. Via ve
iletken delikli padler; delik çapı, ayrı duvar kaplaması ve gerçek katman
aralığıyla bağlanır. Katman akımları eşit kabul edilmez; çözümden bulunur.
Kaynak padleri ideal eşpotansiyel temas, yük akımları seçili pad hücrelerine
dağıtılmış akım olarak modellenir.

Yol/via I²R kayıpları ve elle girilen komponent kayıpları termal modele
aktarılır. Yalıtkan taban malzemesi, aktif olmayan netlerin bakırları ve bütün katmanlar ısı
iletimine katılır. Elektriksel olarak ayrı netlerin ısıl etkileşimi korunur.
Bakırın sıcaklığa bağlı direnciyle hesap tekrarlanır; yakınsamayan sonuç
geçerliymiş gibi gösterilmez.

Bu bir 2.5D ızgara yaklaşımıdır. Bakır kesitleri/kenarları örneklenir; via
temas yayılımı yaklaşık modellenir. Dar boşluklar, küçük padler ve kesikler
yeterli çözünürlük ister. Düğüm bütçesi aşılırsa işlem durur; çözünürlük
haber verilmeden düşürülmez. Dolguları kullanıcı KiCad'de güncelleyip kaydeder.

Oval delikli padlerin delik içi bakır kaplaması hesaptan
çıkarılır ve açık uyarı gösterilir. Yuvarlak iletken delikler, geçişli ve
kör viaların gerçek katman aralıkları modellenir. Arayüzün varsayılan bütçesi 500.000 katman hücresidir; Hesap ayarlarında
2.000.000 hücreye kadar artırılabilir. Çözünürlük otomatik düşürülmez.

Üst/alt yüzeyde sabit taşınım kullanılır. Radyasyon, kart kenarı taşınımı,
kasa/hava akışı CFD'si, termal ped/soğutucu ve paket içi jonksiyon/kılıf
modelleri yoktur. Komponent kayıpları elle verilir. Sonuçlar karşılaştırma ve
sıcak nokta araştırması içindir; doğrulanmış çalışma akımı kapasitesi belirlemez.
Üretim değerleri, daha ince ızgara, elle hesap ve gerçek ölçümle doğrulanır.

Sonuçlar yerel `scenario.json`, `result.json` ve `result.npz` dosyalarına
yazılır. NPZ yalnız sayısal diziler içerir, pickle yüklenmez. Hiçbir dosya
gönderilmez. Eklenti PCB, şema, footprint, bağlantı veya proje ayarlarını
değiştirmez/kaydetmez. İptal yalnız ayrı hesap sürecini sonlandırır.

## Doğrulama

Testler; bilinen yol direnci, paralel katmanlar, via katman aralığı/kaplaması,
akım/güç dengesi, taşınımla ısı dengesi, başka nete ısı yayılması, GND dönüş
akımı, bağlantısız uçlar, iptal ve sıcaklık geri beslemesini kontrol eder.
Geçici KiCad örnekleri katman sırası, kesikler, bakır dolgusu, via halkaları
ve pad temaslarını sınar. Kullanıcının kartı test paketine eklenmez.

Depo kökünden test gruplarını ayrı çalıştır. Taşınabilir/paket grupları
geliştirme bağımlılıklarını, arayüz grubu Windows'ta wxPython'u gerektirir.
Yerel grup KiCad 10'un `pcbnew` içeren Python'uyla çalıştırılmalıdır; bu ortam
yoksa testler başarılı sayılarak atlanmaz:

```sh
python ci/run_tests.py portable
python ci/run_tests.py package
python ci/run_tests.py gui
python ci/run_tests.py native
```

Barındırılan taşınabilir/paket CI işinin geçmesi, yerel KiCad veya Windows
arayüz bütünleşmesinin sınandığı anlamına gelmez; bunlar ayrı gruplardır.

Lisans: MIT. `LICENSE` dosyasına bakılabilir.

Aşağıdaki sürüm başlıkları yerel geliştirme adımlarını anlatır; 0.3.4 ilk açık
yayındır. Bu özelliklerin tamamı mevcut pakete dahildir.

## 0.2.0 değişiklikleri

Kart merkezli analiz görünümü eklendi: kayıtlı bakır geometrisi ve
referanslar, pad/bakır noktasına tıklayarak atama, çoklu pad grubu,
düzenlenebilir kart üstü işaretler, yakınlaştırma/kaydırma/sığdırma/arama ve
PCB ile hizalı ısı haritası. Senaryolar pad gruplarının yanında sanal
noktasal temasları da saklar. Dolu zone alanları otomatik okunur ve sayıları
gösterilir. Kart salt okunur kalır; çok katmanlı DC ve tahmini kart sıcaklığı
hesabının yukarıdaki sınırları geçerlidir.


## 0.3.0 değişiklikleri ve kullanım

- Ctrl ile boşluğa, yola, zone'a, deliğe veya viaya yanlışlıkla tıklamak seçili
  pad grubunu bozmaz ve noktasal temas oluşturmaz.
- **Görünürlük…** düğmesinden referansları, pad numaralarını, baskı/yazı/
  çizimleri, yolları, bakır dolguları ve viaları ayrı açıp kapatabilirsin. Bu
  seçenekler yalnız görünümü değiştirir; hesapta gizlenen bakırlar da yer alır.
  Padler ve analiz işaretleri seçilebilir kalır.
- Gerilim kaynağı eklenince **Komponent seçim ağı** o kaynağın ağına geçer.
  Komponent gövdesine tıklandığında yalnız o footprint'in seçilen kaynak ağındaki
  padleri seçilir. Doğrudan pad tıklaması yine tek padi
  seçer. Ctrl ile birden fazla komponent gövdesini biriktirip Yük düğmesine
  basarak gruba toplam akım atayabilirsin. Yük modundayken normal gövde tıklaması
  eşleşen padler için değer penceresi açar. İç katmanlarda bakır nokta seçimi
  korunur. **Tek pad / bakır seçimi** ile bu özelliği kapatabilir veya çoklu
  besleme senaryosunda kutudan başka bir kaynak ağı seçebilirsin.
- Aç/Yenile işlemi kayıtlı PCB'nin yerel analiz kopyasını alır. Her hesap,
  görünümdeki bu kopyanın kendine ait bir kopyası üzerinde çalışır. Hesap sürerken
  asıl PCB'yi düzenleyip kaydedebilirsin; sonuç hâlâ ekrandaki kart kopyasına
  aittir. Yeni PCB düzenlemelerini analize almak için **Yenile** düğmesini kullan.
  Kopya yolu, SHA-256, oluşturulma zamanı ve asıl dosya bilgisi yerel sonuçlara
  kaydedilir. Değiştirilmiş kopyalar ve görüntüyle eşleşmeyen sonuçlar reddedilir.
- Açılır kutuların kendisi/listesi, sekmeler ve tablo başlıkları açık renk
  çizilir. KiCad'in koyu teması bu alanlardaki yazıları gizleyemez; KiCad'in genel
  teması değiştirilmez.
- Hesap motorunda çok seviyeli önkoşullandırma ve önceki çözümden başlama
  kullanılır. Aynı ince ızgaranın denklemleri çözülür; çözünürlük, via aralıkları
  veya diğer katmanların ısıl katkısı azaltılmaz. Yakınsama ve enerji kontrolleri
  korunur. Sonuç dosyasında geometri/hesap/çıktı süreleri ayrı bulunur.



## 0.3.1 yük toplamı ve durdurulan analizler

Giriş panelinde her ağın yük grupları toplanır; çekilen ve verilen akım ayrı
gösterilir. Her satır kendi grup toplamını ekler, akım diğer satırlara otomatik
bölünmez. Aynı pad grubunu yeniden eklemek mevcut değerini düzenler, yanlışlıkla
yeni bir yük oluşturmaz. Eski senaryoların verileri korunur; yinelenen gruplar
gösterilir ve arayüzden tekrar analiz başlatmadan önce kaldırılmaları istenir.

Örneğin üç ayrı 1 A satırı toplam 3 A ister. Amaç üç temas konumunun birlikte
toplam 1 A çekmesiyse bunlar Ctrl ile birlikte seçilip tek gruba 1 A atanır
veya toplam akım bilinçli olarak ayrı satırlara bölünür. Kararlı DC modeli
akımları otomatik olarak dönüştürmez veya küçültmez.

Model geçerlilik sınırını aşarsa, sonlu sayısal değer üretemezse veya yakınsamazsa
hata nedeni ve gerçek ağ bazlı yük toplamları İngilizce/Türkçe açıklanır. Hesap
turu, hücre ve fiziksel ayarlar yapılandırılmış hata ayrıntılarına eklenir. Model
eşiğinin aşılması gerçek kartın o sıcaklığa çıkacağının tahmini değildir; reddedilen
hesap durumları yakınsamış sıcaklık haritası olarak gösterilmez.


## 0.3.2: sıcaklık çözülemediğinde DC yollarını inceleme

Sıcaklık hesabı durduğunda ilk geçerli elektriksel çözüm artık kaybolmaz.
Görünüm **Bakır kayıp yoğunluğu · W/mm²** ile açılır; **Akım yoğunluğu** ve
**Gerilim sapması** da her katman için seçilebilir. Kalıcı bilgi satırı, bakır
direncinin senaryodaki başlangıç ortam sıcaklığında sabit alındığını belirtir.
Bu inceleme verisinde sıcaklık seçeneği bulunmaz. Bunlar referans sıcaklıktaki
DC sonuçlarıdır; çalışma sıcaklığının tahmini veya yakınsamış elektrotermal
sonucun yerine geçen bir veri değildir.

Asıl termal hata korunur, pencerede DC haritalarının hazır olduğu belirtilir.
Sonuç klasörüne `dc-diagnostic.json` ve `dc-diagnostic.npz` yazılır; geçersiz
sıcaklık dizisi yazılmaz. Akımlar, güçler veya başlangıç sıcaklığı değiştirilmez.
İptal, elektriksel bağlantısızlık veya yalnız ısı kaynağı olan senaryolarda
kısmi elektrik sonucu uydurulmaz. Senaryo veya ayarlar değişirse bu haritalar
da geçersizleşir ve yeniden hesap istenir.

Bakır kayıp yoğunluğu, hücredeki Joule kaybının hücre alanına bölünmesidir.
Analiz edilen ağların toplamını gösterir; katmanlarda aynı renk ölçeği kullanılır.
Komponent ısısı veya sıcaklık değildir. Normal yakınsamış sonuçlarda da bu
görünüm bulunur; o durumda yakınsamış sıcaklıktaki bakır kaybı gösterilir.

Üst/alt taşınım değerleri fiziksel kabuldür. Varsayılan 10/10 W/m²K; ölçülmüş
soğutucuyu, kablo üzerinden ısı uzaklaşmasını veya zorlanmış hava akışını
tanımlamaz. Elektriksel yollar bağlı olsa da yüksek sürekli akım bu kabullerle
geçerli kararlı sıcaklık sonucu vermeyebilir. Eklenti harita göstermek için
soğutmayı otomatik artırmaz veya akımı azaltmaz. Sıcaklık senaryosunda gerçek
soğutma koşullarının verileri kullanılmalıdır.


## 0.3.3: genel girişler ve çoklu atama satırları

- Yeni kaynak gerilimi, yük akımı ve komponent ısısı alanları boş açılır.
  Analizin gerektirdiği değerler kullanıcı tarafından girilir; belirli bir
  karta özel değer verilmez. Mevcut atamayı düzenlerken kayıtlı değeri açılır.
- Giriş listesinde Ctrl ile ayrı satırlar, Shift ile satır aralığı seçilebilir.
  **Seçileni kaldır** seçili bütün satırları kaldırır. **Değeri düzenle**, aynı
  türde seçilmiş atamaların hepsine bir değer uygular. Volt, amper ve watt
  farklı anlamlar taşıdığından karışık türler birlikte düzenlenmez.
- Hesap sürerken sayı alanları açık renk ve okunaklı kalır. Alanlar işlem
  bitene kadar kilitlidir; görünüm düzeltmesi fiziksel değerleri değiştirmez.
- Yardım, örnekler ve paket açıklamaları genel PCB terimleri kullanır.
  Mevcut senaryolarda kullanıcının açıkça girdiği değerler korunur.


## 0.3.4: tutarlı açık tema ve hatırlanan hesap ayarları

Düğmelerin üzerine gelme, basılı, odak ve kilitli durumları; araç seçimleri, checkbox'lar, pad listesi ve değer giriş pencereleri eklentinin kendi açık kontrollerini kullanır. KiCad teması değiştirilmez.

Hesap ayarları düzenlemeden sonra, analiz öncesinde ve kapanışta otomatik saklanır; sonraki açılışta geri gelir. Malzeme, düzlem içi/katmanlar arası iletkenlik, ortam, taşınım, via kaplaması, hücre boyu/bütçesi ve sınır işaretleri buna dahildir. Ayarlar kullanıcıya özeldir; PCB dosyaları ve kaynak/yük atamalarıyla karışmaz. Dosya: `%APPDATA%/kicad/pcb_heatmap/calculation-settings.json`. Senaryo dosyaları kendi ayarlarını korur.

Yalnız komponent ısısı verilen analizlerde, elektriksel çözüm için seçilmemiş ağların mevcut pad alanları da çözülür. Ayrı bakır adalarının birleştirilmesini reddeden kontrol korunur; hata artık katman/ağ adını da gösterir.
