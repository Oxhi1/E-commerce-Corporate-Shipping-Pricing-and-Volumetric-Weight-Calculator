# Özdilek — Çok Firmalı Kargo Fiyatlama ve Desi Motoru

Sipariş anında **beklenen toplam sahiplenme maliyetini** (nakliye + hasar + gecikme)
minimize eden kargo firmasını seçen bir karar motoru ve bu motorun ne kadar
kazandırdığını ölçen bir Monte Carlo simülasyonu.

> **ÖRNEK TARİFE.** Bu depo sentetik tarife ve sentetik geçmiş sevkiyat verisiyle
> çalışır. Büyüklük mertebeleri gerçekçidir, rakamlar gerçek Özdilek sözleşme
> fiyatları **değildir**. Gerçek veriye geçiş için → [Gerçek veriye geçiş](#gerçek-veriye-geçiş)

---

## Problem

E-ticaret sevkiyatında iki maliyet sessizce kaybediliyor:

**1. Desi şişmesi.** Sepetteki ürünlerin desileri ayrı ayrı toplanıyor. Oysa 3 desi
havlu ile 4 desi deterjan aynı koliye girdiğinde fatura 7 desi değil, gerçek kutu
desisi kadar olmalı.

**2. Görünmeyen maliyet.** En ucuz teklif çoğu zaman en ucuz *sonuç* değil. Bir
firmanın belirli bir bölgede %5 hasar oranı varsa, patlayan bir şişe zeytinyağı
aynı kolideki nevresimi de götürür; 4 TL'lik nakliye tasarrufu 900 TL'lik zarara
dönüşür. Geç teslimat da çağrı merkezi, iade ve müşteri kaybı olarak bütçeye
yansır ama hiçbir yerde "nakliye gideri" diye görünmez.

### Simülasyonun bulduğu

20.000 siparişlik bir koşuda (tohum 42), sipariş başına:

| Politika | TL/sipariş | Nakliye | Gizli maliyet payı | Hasar | Gecikme | Ort. gün |
|---|---:|---:|---:|---:|---:|---:|
| P0 Tek firma (mevcut durum) | 398,32 | 328,16 | %17,6 | %1,00 | %13,1 | 2,06 |
| **P1 En ucuz nakliye** | **464,86** | **290,38** | **%37,5** | %2,79 | %36,7 | 4,31 |
| P2 En hızlı teslimat | 406,79 | 354,73 | %12,8 | %0,60 | %8,3 | 1,50 |
| **P3 Toplam maliyet (bu motor)** | **388,59** | 318,09 | %18,1 | %1,07 | %16,0 | 2,37 |
| P4 TELC + kapasite kısıtı | 388,67 | 318,14 | %18,1 | %1,07 | %16,0 | 2,38 |

- **P3 vs P0**: sipariş başına **+9,73 TL** tasarruf (%2,44), %95 G.A. [+6,79, +13,12] — anlamlı
- **P3 vs P1**: sipariş başına **+76,27 TL** tasarruf (%16,4), %95 G.A. [+67,81, +85,11] — anlamlı
- Kalibrasyon hatası (ECE): **0,0042** · koşu süresi 241 sn (12,1 ms/sipariş)

En çarpıcı bulgu **P1**: "en ucuz nakliyeyi seç" kuralı faturayı en aza indiriyor
(290,38 TL — hepsinden düşük) ama toplam maliyeti **P0'ın bile üzerine** çıkarıyor.
Hasar oranı üç katına, gecikme oranı üç katına çıkıyor. Projenin varlık gerekçesi
tam olarak bu satır.

**P4 ile P3 neredeyse eşit** (fark 0,08 TL): bu senaryoda günlük kapasite kısıtı
pratikte bağlamıyor. Kapasite payı düşürüldüğünde (`capacity_share`) fark açılıyor;
`test_capacity_constraint_spreads_the_volume` bunu doğruluyor.

---

## Hızlı başlangıç

```bash
# Backend
cd backend
pip install -e ".[dev]"
python scripts/generate_synthetic_tariffs.py     # data/carriers/*.yaml
python scripts/generate_synthetic_history.py     # data/history/shipments.csv
pytest -q                                        # 277 test

# API
uvicorn desi_engine.api.main:app --reload        # http://localhost:8000/docs

# Arayüz (ayrı terminal)
cd frontend && npm install && npm run dev        # http://localhost:5173
```

> **Windows notu.** Depo yolunda Türkçe karakter varsa (`C:\OZDİLEK`) Python'ın
> konsol kodlaması bozulabilir. `set PYTHONUTF8=1` (veya PowerShell'de
> `$env:PYTHONUTF8=1`) bunu çözer.

### Arayüz olmadan denemek

```bash
cd backend

# Tüm firmaların teklifleri, kalem kalem
python -m desi_engine.cli rate --cart examples/banyo_seti.json --city 34

# Karar + gerekçe  (kabul kriteri #2'nin senaryosu)
python -m desi_engine.cli decide --cart examples/zeytinyagi_nevresim.json --city 65 --explain

# Koli planı ve desi tasarrufu
python -m desi_engine.cli pack --cart examples/buyuk_tekstil.json --verbose

# Koli yerleşiminin izometrik görseli (rapora/sunuma gömmek için)
python -m desi_engine.cli pack --cart examples/zeytinyagi_nevresim.json --render out/koli.svg

# Monte Carlo + HTML rapor
python -m desi_engine.cli simulate --orders 20000 --seed 42 --report reports/simulasyon.html
```

---

## Matematiksel model

Çekirdek fikir:

```
Seçilen = argmin_k [ F_k(D) + R_k·S + Z_k(L) ]
```

Uygulanan hâli, aynı fikrin ölçülebilir bir genişletmesi:

```
TELC_k = F_k(D, z, σ)                  nakliye (tarife + ek ücretler + KDV)
       + Σ_b p̂_{k,z,c(b)} · Zarar(b)   beklenen hasar maliyeti
       + Z_k(L)                        beklenen gecikme maliyeti
       + O_k                           ambalaj + operasyonel sürtünme

Skor_k = TELC_k + λ · (CVaR₉₅(hasar) − E[hasar])
```

İki yerde ayrılıyor:

**`R_k·S` → `p̂ · Zarar(b)`.** Hasar maliyeti sepet tutarına eşit değil. Ezilen bir
havlu %100 zarar değildir (outlet'te satılır), kırılan bir porselen takım %100'dür.
Ve zarar sepetten fazlasını götürür:

```
Zarar(b) = Σᵢ değerᵢ · şiddetᵢ                    doğrudan
         + kontaminasyon · Σⱼ emici_değerⱼ        yan hasar (sızıntı)
         + yeniden_gönderim + elleçleme + çağrı   lojistik
         + churn_olasılığı · CLV                  müşteri kaybı
```

**`λ·CVaR₉₅`.** Beklenen değer, "nadiren çok kötü" ile "sık sık biraz kötü"yü aynı
sayıya indirger. `λ>0` verildiğinde motor kuyruğu da fiyatlar. İki noktalı hasar
dağılımı için CVaR kapalı formda: `min(1, p/α) · Zarar`.

Tam türetim → [`docs/01-matematiksel-model.md`](docs/01-matematiksel-model.md)

---

## Nasıl çalışıyor

```
sepet
  │
  ├─▶ PackingPlanner ──▶ birkaç aday koli planı (Pareto cephesi)
  │                      3B yerleştirme + fiziksel kurallar
  │
  └─▶ her (firma × plan) çifti için:
        ├─ kısıt denetimi      hizmet bölgesi, desi limiti, cut-off, kapasite
        ├─ FreightCalculator   F_k  — tarife + ek ücret sırası
        ├─ DamageCostModel     E[hasar] — Bayesçi p̂ × zarar fonksiyonu
        ├─ DelayCostModel      Z_k — log-normal teslimat dağılımı
        └─ ObjectiveParams     kuyruk riski primi
              │
              ▼
      firma başına en iyi plan ──▶ skora göre sırala ──▶ gerekçe üret ──▶ etiket
```

### 1 · Sanal kutulama

Ürün desileri toplanmaz; ürünler gerçek ölçüleriyle standart kolilere yerleştirilir
ve fatura **kolinin dış desisi** üzerinden hesaplanır (iç ölçü ürünlerin sığdığı
hacim, dış ölçü kargo firmasının ölçtüğü — K10'da fark %8).

Yöntem: köşe noktaları + **yerçekimi oturtması**. Ham köşe noktaları boşluk
bırakıyor; her aday seçilmeden önce önce z, sonra y ve x ekseninde çarpana kadar
kaydırılıyor. Oturtma olmadan tipik dolgu oranı ~%45, oturtmayla ~%65-75.

Üç tasarım kararı:

- **"Hepsi tek koliye sığıyor" en ucuz demek değil.** Örnek bir sepette tek koli
  86,5 desi; K09+K04 bölmesi 57,2 desi.
- **En az desi de tek başına doğru amaç değil.** Asgari ücret **parça başına**
  uygulanır. Bu yüzden planlayıcı (desi, parça sayısı) düzleminde Pareto-optimal
  birkaç aday üretir; hangisinin kazandığını tarifeyi bilen karar motoru söyler.
- **Sıvı ayrımı bir paketleme kuralı değil, bir maliyet kararı.** Zeytinyağını
  nevresimden ayırmak bir koli daha demek; paketleyici hasar maliyetini bilmiyor.

Fiziksel kurallar: sıvı emici ürünün üzerine konmaz, kırılabilir ürün dolgu payı
ister, istif yükü yığın boyunca aşağı yayılır, kargo poşetine cam/sıvı girmez.

### 2 · Bayesçi hasar modeli

`(firma × bölge × ürün tipi)` = 80 hücre, ama geçmiş veri çarpık: en yoğun hücrede
9.118 gönderi, en seyrekte 5. Ham oranlar kullanılamaz — 5 gönderide 0 hasar
"risksiz" değil, "hiçbir şey bilmiyoruz" demektir; 33 gönderide 1 hasar ham hâliyle
%3 görünür ve gerçeğin (~%0,5) altı katıdır.

Dört katmanlı Beta-Binom shrinkage:

```
p₀    = genel ortalama
p_k   = (κ₀·p₀   + d_k)   / (κ₀ + n_k)        firma
p_kz  = (κ₁·p_k  + d_kz)  / (κ₁ + n_kz)       firma × bölge
p_kzc = (κ₂·p_kz + d_kzc) / (κ₂ + n_kzc)      firma × bölge × kategori
```

`κ` elle seçilmez; her katmanda marjinal olabilirlik maksimize edilerek veriden
kestirilir. Ölçülen sonuç — 80 hücrede gerçeğe kıyasla ortalama mutlak hata:

| | Ham oran | Shrinkage'lı |
|---|---:|---:|
| MAE | %0,71 | **%0,48** |
| RMSE | %1,05 | **%0,83** |

Yoğun hücrelerde tahmin ham orana yakınsıyor (%2 önsel ağırlık), seyrek hücrelerde
üst katmana yaslanıyor (%97). Geçiş kesintisiz — "n < 30 ise üst katmanı kullan"
gibi keyfi bir eşik yok.

### 3 · Teslimat ve gecikme

Firmanın SLA'si bir **vaat**; gerçekleşen süre başka bir şey. Motor geçmiş veriden
`log(gerçekleşen / vaat)` dağılımını kestiriyor — bu büyüklük ölçekten bağımsız
("firma vaadini yüzde kaç aşıyor"), böylece 1 günlük şehir içi hücresi 4 günlük uzak
bölge hücreleriyle aynı havuzda anlamlı şekilde birleşebiliyor.

```
Z_k = P(gecikme)·(çağrı + p_iade·iade + p_churn·CLV) + E[(T−vaat)⁺]·gün_başı_telafi
```

`E[(T−d)⁺]` log-normal için kapalı formda hesaplanıyor; Monte Carlo'da milyonlarca
kez çağrıldığı için sayısal integral her koşuyu dakikalarca uzatırdı.

### 4 · Monte Carlo

Üç metodolojik ilke:

- **Motor gerçeği bilmez.** `TrueWorld` gerçek hasar olasılıklarını ve teslimat
  dağılımlarını tutar; karar motoru yalnızca ondan üretilmiş **gözlenmiş geçmiş
  veriyi** görür. Bu ayrım olmasaydı simülasyon kendi cevabını kopyalardı.
- **Ortak rastgele sayılar.** Her sipariş için şans çekilişleri bir kez yapılır ve
  tüm politikalar aynı çekilişleri kullanır. "MNG'yi seçseydim bu koli hasar görür
  müydü" sorusu aynı şansla cevaplanır.
- **Eşleştirilmiş bootstrap.** Aynı sipariş için iki politikanın maliyeti eşleşmiş
  bir çift; farkların dağılımından güven aralığı çıkarılır. Aralık sıfırı kapsıyorsa
  rapor bunu **"ANLAMSIZ"** olarak işaretler.

Kalibrasyon kontrolü: motorun "%2 hasar olasılığı" dediği gönderilerin gerçekten
~%2'si hasar görüyor mu? ECE = **0,0046**.

---

## Proje yapısı

```
backend/
├─ src/desi_engine/
│  ├─ domain/       enum'lar, desi aritmetiği, çekirdek modeller
│  ├─ packing/      koli katalogu, 3B yerleştirme, Pareto planlayıcı, baz çizgiler
│  ├─ tariff/       şema+doğrulama, bölge çözümleyici, ücret hesaplayıcı
│  ├─ risk/         Beta-Binom, hiyerarşik shrinkage, hasar maliyeti
│  ├─ sla/          teslimat süresi kestirimi, gecikme maliyeti
│  ├─ decision/     kısıtlar, amaç fonksiyonu, seçici, açıklama üretimi
│  ├─ labels/       Code 128, ZPL, HTML önizleme
│  ├─ simulation/   gerçek dünya, sipariş üreteci, politikalar, koşucu, metrikler
│  ├─ adapters/     veri kaynağı protokolleri, dosya okuyucuları, sözleşme içe aktarımı
│  ├─ api/          FastAPI uygulaması, şemalar, dönüşüm
│  ├─ engine.py     motorun birleştirilmesi
│  ├─ cli.py        komut satırı arayüzü
│  └─ reporting.py  bağımsız HTML rapor
├─ data/            tarifeler, 81 il, koli katalogu, ürün katalogu, geçmiş sevkiyat
├─ scripts/         sentetik veri üreticileri
├─ examples/        örnek sepetler
└─ tests/           277 test

frontend/           Vite + React + TypeScript (grafik/3B kütüphanesi yok)
docs/               matematiksel model, veri sözleşmesi, mimari kararlar
```

**Katman kuralı.** `domain`, `packing`, `tariff`, `risk`, `sla`, `decision` saf
Python çekirdeğidir — dosya sistemine, HTTP'ye veya FastAPI'ye bağımlı değildir.
Tüm I/O `adapters` ve `api` içinde toplanır. Bu sayede motor simülasyondan da
API'den de aynı şekilde çağrılır ve çekirdek testleri saniyeler sürer.

---

## Gerçek veriye geçiş

Motorun sentetik veriyle çalışan hâli ile gerçek sözleşmelerle çalışan hâli
arasındaki tek fark `adapters/contract_import.py`. Çekirdeğin hiçbir satırı
değişmez.

```python
from datetime import date
from pathlib import Path
from desi_engine.adapters import ContractMeta, from_csv, write_yaml
from desi_engine.domain import CarrierCode, RoundingRule, ZoneClass

meta = ContractMeta(
    carrier=CarrierCode.ARAS,
    display_name="Aras Kargo",
    valid_from=date(2026, 1, 1),
    min_charge=74.50,
    rounding=RoundingRule.CEIL,
    fuel_pct=0.08,
    cod_fee=22.0,
    insurance_free_limit=500.0,
    insurance_pct_above=0.004,
    vat_pct=0.20,
    over_top_tier_per_desi={z.value: 6.0 for z in ZoneClass},
    sla_days={"sehir_ici": 1, "bolge_ici": 2, "bolgeler_arasi": 3, "uzak": 4},
    cutoff="17:00",
    max_desi_per_parcel=100.0,
)

tarife = from_csv(Path("aras_2026.csv"), meta)   # veya from_excel(...)
write_yaml(tarife, Path("backend/data/carriers"))
```

Beklenen matris biçimi:

```csv
up_to_desi,sehir_ici,bolge_ici,bolgeler_arasi,uzak
1,62.00,70.00,81.00,92.00
2,68.00,77.00,89.00,101.00
```

İçe aktarılan tarife `source: contract` işaretlenir ve arayüzdeki **"ÖRNEK TARİFE"**
rozeti o firmadan kalkar. Yükleme sırasında fiyat monotonluğu doğrulanır — elle
düzenlenmiş bir matriste en sık görülen ve fark edilmesi en zor hata budur.

Aynı yuva geçmiş sevkiyat verisi ve ürün katalogu için de var:
`adapters/protocol.py` üç `Protocol` tanımlar (`TariffSource`,
`ProductCatalogSource`, `ShipmentHistorySource`); ERP'den çeken bir istemci de —
bu paketi hiç bilmeden — geçerli bir kaynak olur.

---

## Doğrulama

```bash
cd backend
pytest -q                                        # 277 test
pytest --cov=desi_engine --cov-report=term       # toplam %87, çekirdekte %91-100
ruff check src tests scripts                     # temiz
ruff format --check src tests scripts

cd ../frontend
npm run typecheck && npm run build
```

Toplam kapsamı çeken kısımlar API/CLI/rapor katmanları; karar mantığını taşıyan
`domain`, `packing`, `tariff`, `risk`, `sla`, `decision` modülleri %91-100
aralığında.

**Kabul kriterleri ve durumları:**

| # | Kriter | Durum |
|---|---|---|
| 1 | Tüm testler yeşil, çekirdekte ≥%80 kapsam | ✅ 277 test, toplam %87 / çekirdek %91-100 |
| 2 | Van'a giden zeytinyağı + nevresim sepetinde motor en ucuz firmayı **seçmiyor** ve sebebini yan hasar kalemiyle sayısal gösteriyor | ✅ Sürat 440,74 TL reddedildi, PTT seçildi, 326,37 TL kazanç |
| 3 | Kutulama ölçülebilir desi düşüşü üretiyor, yerleşim görsel olarak doğrulanabiliyor | ✅ Referans sepetlerde %13-32, izometrik 3B görünüm |
| 4 | Monte Carlo tasarrufu %95 G.A. ile raporluyor; aralık sıfırı kapsıyorsa dürüstçe söylüyor | ✅ Eşleştirilmiş bootstrap, "ANLAMSIZ" etiketi |
| 5 | Sabit tohumla iki koşu birebir aynı sonucu veriyor | ✅ `test_is_reproducible` |
| 6 | Tarife dosyasındaki fiyat elle değiştirilince motor yeni fiyatı kullanıyor | ✅ `TariffRepository.reload()`, kodda gömülü fiyat yok |

---

## Bilinen sınırlar

Dürüstlük gereği, bu projenin **yapmadığı** şeyler:

- **Barkod fiziksel okuyucuyla test edilmedi.** ZPL çıktısı yetkili kaynaktır
  (barkodu yazıcı kodlar); SVG önizleme standart Code 128-B tablosundan çizilir ve
  yapısal olarak doğrulanır (modül sayısı, sağlama toplamı), ama bir el terminaliyle
  denenmedi.
- **3B yerleştirme tam projeksiyon tabanlı Extreme Point değil.** Köşe noktaları +
  yerçekimi oturtması kullanılıyor; ürünler dikdörtgen prizma olarak modelleniyor.
  Yumuşak tekstil için bu son varsayım iyimserdir, `compressibility` kısmen telafi eder.
- **Koli görseli SVG, PNG değil.** Raster çıktı Pillow veya matplotlib gerektirirdi;
  bağımlılık eklemek yerine SVG üretiliyor (her ölçekte keskin, rapora doğrudan
  gömülebilir). PNG isteyen `rsvg-convert` veya bir tarayıcıdan geçirebilir.
- **Hacim taahhüdü gölge fiyatı (`V_k`) uygulanmadı.** Açgözlü seçim yıllık taahhüt
  kademesini kaçırabilir; Lagrange dualiyle çözülmesi planlanan bir sonraki adım.
- **Teslimat modelindeki shrinkage basitleştirilmiş.** Hasar modelinde `κ` marjinal
  olabilirlikle kestirilirken, teslimatta sabit bir sözde-gözlem sayısı kullanılıyor
  (teslimat hücreleri çok daha kalabalık olduğu için marjinal katkı küçük).
- **Simülasyon koşuları bellekte tutuluyor.** Tek kullanıcılı demo için yeterli;
  çok kullanıcılı bir kurulumda kalıcı depoya taşınmalı.
- **Sonuçlar sentetik dünyaya bağlı.** "%17 tasarruf" rakamı, `simulation/world.py`
  içindeki hasar oranları ve teslimat hızları varsayımının sonucudur. Gerçek Özdilek
  verisiyle sayı değişir; değişmeyecek olan, **hangi maliyet kalemlerinin
  ölçüldüğü**dür.

---

## Dokümanlar

| Dosya | İçerik |
|---|---|
| [`docs/01-matematiksel-model.md`](docs/01-matematiksel-model.md) | Modelin tam türetimi, Beta-Binom, CVaR, kalibrasyon |
| [`docs/02-veri-sozlesmesi.md`](docs/02-veri-sozlesmesi.md) | Tarife/katalog/geçmiş veri şemaları |
| [`docs/03-mimari.md`](docs/03-mimari.md) | Katmanlar, bağımlılık yönü, performans |
| [`docs/adr/`](docs/adr/) | Mimari karar kayıtları — neden böyle yapıldı |
