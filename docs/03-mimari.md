# Mimari

## Katmanlar ve bağımlılık yönü

```
                      ┌──────────────────────────────┐
   dış dünya          │  api/   ·  cli.py            │   HTTP, dosya, terminal
                      │  reporting.py                │
                      └──────────────┬───────────────┘
                                     │
                      ┌──────────────▼───────────────┐
   kurulum            │  engine.py                   │   bileşenleri birleştirir
                      └──────────────┬───────────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         │                           │                           │
┌────────▼────────┐        ┌─────────▼─────────┐       ┌─────────▼─────────┐
│  adapters/      │        │   decision/       │       │  simulation/      │
│  dosya, sözleşme│        │   seçici, kısıtlar│       │  dünya, koşucu    │
└────────┬────────┘        └─────────┬─────────┘       └─────────┬─────────┘
         │                           │                           │
         └───────────────────────────┼───────────────────────────┘
                                     │
        ┌────────────┬───────────────┼───────────────┬────────────┐
        │            │               │               │            │
   ┌────▼────┐  ┌────▼────┐    ┌─────▼─────┐   ┌─────▼────┐  ┌────▼────┐
   │ tariff/ │  │ packing/│    │   risk/   │   │   sla/   │  │ labels/ │
   └────┬────┘  └────┬────┘    └─────┬─────┘   └─────┬────┘  └────┬────┘
        └────────────┴───────────────┼───────────────┴────────────┘
                                     │
                             ┌───────▼───────┐
                             │   domain/     │   enum, desi, modeller
                             └───────────────┘
```

**Kural:** oklar yalnızca aşağı doğru. `domain`, `packing`, `tariff`, `risk`, `sla`,
`decision` saf Python çekirdeğidir — dosya sistemine, HTTP'ye veya FastAPI'ye
bağımlı değildir. Tüm I/O `adapters` ve `api` içinde toplanır.

Bunun üç somut faydası var:

1. **Çekirdek testleri saniyeler sürüyor.** Disk veya ağ yok; 277 testin tamamı
   ~15 saniyede koşuyor (bunun çoğu geçmiş veriyi bir kez okumaktan geliyor).
2. **Motor üç yerden aynı şekilde çağrılıyor.** CLI, API ve simülasyon `engine.py`
   üzerinden aynı kurulumu alıyor; "API'de farklı davranıyor" sınıfı hatalar
   yapısal olarak imkânsız.
3. **Gerçek veriye geçiş tek modülde.** `adapters/contract_import.py` dışında
   hiçbir dosya sentetik/gerçek ayrımını bilmiyor.

---

## Modül sorumlulukları

| Modül | Sorumluluk | Bilmediği şey |
|---|---|---|
| `domain` | Desi aritmetiği, para yuvarlaması, ürün/sepet/adres modelleri | Kargo firmaları, fiyatlar |
| `packing` | Koli katalogu, 3B yerleştirme, Pareto plan adayları, baz çizgiler | Tarifeler, hasar oranları |
| `tariff` | Şema + doğrulama, bölge çözümleme, ücret hesaplama | Paketleme, risk |
| `risk` | Beta-Binom, hiyerarşik shrinkage, zarar fonksiyonu | Tarifeler, teslimat süresi |
| `sla` | Teslimat süresi kestirimi, gecikme maliyeti | Hasar, fiyat |
| `decision` | Kısıt denetimi, amaç fonksiyonu, seçim, gerekçe | Veri nereden geldiği |
| `labels` | Code 128, ZPL, HTML önizleme | Neden bu firmanın seçildiği (metin olarak alır) |
| `simulation` | Gerçek dünya, sipariş üretimi, politikalar, metrikler | — (en üstte) |
| `adapters` | Dosya okuma, sözleşme içe aktarımı | Motorun ne yaptığı |

---

## Kritik tasarım kararları

### Plan seçimi ile firma seçimi birlikte yapılır

Önce "en iyi plan"ı seçip sonra firma aramak yanlış olurdu. PTT'nin 50 desilik parça
sınırı, tek koliye sıkıştıran planı onun için uygunsuz kılarken iki koliye bölen
planı uygun kılar.

`PackingPlanner` birkaç aday plan üretir; `CarrierSelector` her (firma × plan)
çiftini fiyatlar ve firma başına en iyi planı seçer.

### Planlayıcı tarifeyi bilmez, karar motoru paketlemeyi bilir

Asimetri kasıtlı. Paketleme kararının tarifeye bağımlı olması, tarife değiştiğinde
paketleme önbelleğini geçersiz kılardı — Monte Carlo'da önbellek isabet oranı
%48'den %0'a düşerdi.

Bunun yerine planlayıcı, tarifeden bağımsız bir Pareto cephesi üretir ve seçim
yukarı devredilir.

### Sentetik/gerçek ayrımı veride, kodda değil

`Tariff.source` alanı (`synthetic` | `contract`) API cevabına, arayüzdeki rozete ve
basılan etikete kadar taşınır. Motorda "sentetik mod" diye bir kod yolu yok.

Uydurma fiyatların gerçek sözleşme fiyatı sanılması bu projedeki en ciddi yanlış
anlaşılma riski; bu yüzden bayrak zorunlu ve testlerle korunuyor.

### Para `float`, sınırlarda `Decimal`

Motor içinde `float` kullanılıyor — `Decimal` numpy ile vektörleştirmeyi imkânsız
kılar ve Monte Carlo koşusunu yavaşlatır. Para yalnızca *sunum ve fatura
sınırlarında* `money()` ile kuruşa sabitlenir (yarısı yukarı, `Decimal` ile).

Python'un yerleşik `round()` bankacı yuvarlaması yapar (`round(2.675, 2) == 2.67`);
fatura satırlarında beklenen davranış bu değildir.

---

## Performans

Monte Carlo koşusu, sürenin %89'unu paketlemede geçiriyordu. Profil sonrası
uygulanan optimizasyonlar:

| Optimizasyon | Kazanç |
|---|---|
| Sıcak yolda `Cuboid` property yerine düz float demetleri | ~%30 |
| Kutu boyutu tavanı spektrumunu 13'ten 5'e indirme | ~%25 |
| `rotation_triples` LRU önbelleği (247 bin çağrı → önbellek) | ~%8 |
| `fill_box` sonuçlarının siparişler arası paylaşılan önbelleği | ~%8 |
| `scipy.stats.norm.ppf` önbelleği | ~%4 |

Sonuç: **35,1 ms/sipariş → 11,4 ms/sipariş** (3,1× hızlanma). 20.000 siparişlik bir
koşu ~3,8 dakika.

Önbellek isabet oranları: sepet düzeyi %32 (48 ürünlük katalogdan çok fazla bileşim
çıkıyor), koli-doldurma düzeyi %49 (ürün alt kümeleri sürekli tekrar ediyor).

Optimizasyonlar okunabilirlikten bilinçli bir ödün; davranış
`tests/test_packing.py` içindeki geometrik değişmezlerle korunuyor (hiçbir iki ürün
çakışmaz, tüm ürünler kutu sınırları içinde, hepsi tam bir kez yerleştirilir).

---

## Arayüz

Vite + React + TypeScript. **Grafik kütüphanesi ve 3B kütüphanesi yok.**

- **Grafikler** elle yazılmış SVG. Bir grafik kütüphanesi kendi varsayılan paletini
  getirir ve doğrulanmış paletin üzerine yazardı; ayrıca HTML raporuyla arayüzün
  aynı görünmesi gerekiyor.
- **3B koli görünümü** izometrik izdüşüm + ressam algoritması. Görselleştirilen şey
  eksen hizalı prizmalardan ibaret; ~150 satır tutuyor, WebGL bağımlılığı yok, her
  ölçekte keskin ve `<title>` ile erişilebilir.

Sonuç: 190 KB JS (60 KB gzip).

Renkler `dataviz` yönergesinin doğrulanmış kategorik paletinden alındı ve
`validate_palette.js` ile hem açık hem koyu temada denetlendi. Açık temada üç renk
yüzeye karşı 3:1 kontrastın altında kalıyor; bu yüzden her grafikte görünür değer
etiketleri ve tam veri tablosu var — renk hiçbir yerde tek başına bilgi taşımıyor.

---

## Test stratejisi

Ağırlık tek tek sayılara değil **değişmezlere** verildi. "Bu sepet 18,30 desi
üretmeli" türü bir test, algoritmayı iyileştiren her değişiklikte kırılır ve
insanları testi güncellemeye alıştırır. Buna karşılık "hiçbir iki ürün üst üste
binmez" veya "sıvı hiçbir zaman emici ürünün üstünde olmaz" kurallarının kırılması
her zaman gerçek bir hatadır.

| Tür | Örnek |
|---|---|
| Altın vaka | Desi hesabı, tarife kademe sınırı, ek ücret sırası |
| Property-based (hypothesis) | Kutulama değişmezleri, ücretli desi sınırları |
| İstatistiksel | Shrinkage'ın gerçeğe ham orandan yakın olması, `κ` geri kazanımı |
| Davranışsal | Motor en ucuzu reddediyor / bazen kabul ediyor / tek firmaya kilitlenmiyor |
| Sözleşme | API cevabı katı JSON (NaN/Infinity yok), sentetik bayrağı her yerde |
| Tekrarlanabilirlik | Aynı tohum → birebir aynı simülasyon sonucu |

277 test, çekirdek modüllerde %91-100 kapsam.
