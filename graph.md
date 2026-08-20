# graph.md — Proje Haritası ve Oturum Sürekliliği Dosyası

> **Bu dosyanın amacı:** yeni bir oturumda (yeni bir Claude session'ı, ya da aradan
> haftalar geçtikten sonra sen) projeyi kodu baştan taramadan anlayıp kaldığı yerden
> devam edebilmek. Kodun *ne olduğunu* değil, **neden öyle olduğunu ve nereye
> bağlandığını** anlatır.
>
> **Kullanım protokolü:**
> 1. Oturum başında **önce bu dosya** okunur, sonra `docs/03-mimari.md` (derinlik gerekiyorsa).
> 2. Aktif iş varsa ilgili **plan dosyası** okunur → `plans/` altında (bkz. §12).
> 3. Oturum sonunda §11 (Açık uçlar) ve §12 (Oturum kayıtları) **güncellenir**.
> 4. Kod değişikliği bu dosyadaki bir kuralı ihlal ediyorsa: ya değişiklik yanlıştır,
>    ya da kural değişmiştir → kural burada güncellenir. Sessizce ayrışmasına izin verilmez.

**Son güncelleme:** 2026-08-13 · **Depo:** `C:\OZDİLEK` · **Git:** başlatılmamış (⚠ bkz. §11)

---

## 1 · Tek cümlelik kimlik

Sipariş anında, **beklenen toplam sahiplenme maliyetini** (nakliye + hasar + gecikme +
operasyon) minimize eden kargo firmasını seçen bir karar motoru; artı bu motorun ne
kadar kazandırdığını sahte-dünya karşısında ölçen bir Monte Carlo simülasyonu.

**Çözdüğü iki gizli maliyet:**
- **Desi şişmesi** — ürün desileri ayrı ayrı toplanıyor; oysa fatura *kolinin dış
  desisi* üzerinden kesilmeli. Sanal kutulama bunu düzeltiyor.
- **Görünmeyen maliyet** — en ucuz teklif en ucuz *sonuç* değil. Hasar, yan hasar
  (sızıntı), gecikme, iade ve müşteri kaybı hiçbir yerde "nakliye gideri" olarak
  görünmüyor ama bütçeye yansıyor.

**Projenin varlık gerekçesi tek satırda (simülasyon çıktısı):** P1 "en ucuz nakliyeyi
seç" politikası faturayı en aza indiriyor (290,38 TL — hepsinden düşük) ama toplam
maliyeti mevcut duruma (P0) göre **kötüleştiriyor** (464,86 vs 398,32 TL).

---

## 2 · Amaçlanan çalışma yapısı (uçtan uca akış)

```
                          SEPET (Cart) + ADRES (il plakası) + bayraklar (kapıda ödeme, kırsal, CLV)
                                            │
                    ┌───────────────────────┴───────────────────────┐
                    │                                               │
            ┌───────▼────────┐                          ┌───────────▼────────────┐
            │ PackingPlanner │  tarifeyi BİLMEZ         │ ProvinceRegistry       │
            │ 3B yerleştirme │                          │ 81 il → ZoneClass      │
            └───────┬────────┘                          └───────────┬────────────┘
                    │                                               │
        Pareto cephesi: birkaç aday plan                    çıkış=Bursa(16) → bölge sınıfı
        (desi ↓ , parça sayısı ↓) düzleminde                sehir_ici|bolge_ici|
                    │                                        bolgeler_arasi|uzak
                    └───────────────────┬───────────────────────────┘
                                        │
                        ┌───────────────▼────────────────┐
                        │  her (FİRMA × PLAN) çifti için │   5 firma × N plan
                        └───────────────┬────────────────┘
                                        │
        ┌────────────────┬──────────────┼──────────────┬─────────────────┐
        │                │              │              │                 │
  ┌─────▼──────┐  ┌──────▼───────┐ ┌────▼─────┐  ┌─────▼──────┐  ┌───────▼──────┐
  │ Uygunluk   │  │ Freight      │ │ Damage   │  │ Delay      │  │ Objective    │
  │ constraints│  │ Calculator   │ │ CostModel│  │ CostModel  │  │ tail premium │
  │ bölge/desi │  │ F_k(D,z,σ)   │ │ p̂·Zarar  │  │ Z_k(L)     │  │ λ·CVaR₉₅     │
  │ cut-off    │  │ tarife+ek+KDV│ │ Bayesçi  │  │ log-normal │  │              │
  │ kapasite   │  │              │ │ shrinkage│  │            │  │              │
  └─────┬──────┘  └──────┬───────┘ └────┬─────┘  └─────┬──────┘  └───────┬──────┘
        │                │              │              │                 │
        └────────────────┴──────────────┼──────────────┴─────────────────┘
                                        │
                          ┌─────────────▼──────────────┐
                          │  CarrierSelector.decide()  │
                          │  firma başına en iyi plan  │
                          │  → skora göre sırala       │
                          └─────────────┬──────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │                   │                   │
              ┌─────▼─────┐      ┌──────▼──────┐     ┌──────▼──────┐
              │ Decision  │      │ explain.py  │     │ labels/     │
              │ seçim     │      │ gerekçe     │     │ Code128/ZPL │
              └───────────┘      └─────────────┘     └─────────────┘
```

**Amaç fonksiyonu (uygulanan hâli):**

```
TELC_k = F_k(D, z, σ)                  nakliye  (tarife + ek ücretler + KDV)
       + Σ_b p̂_{k,z,c(b)} · Zarar(b)   beklenen hasar maliyeti
       + Z_k(L)                        beklenen gecikme maliyeti
       + O_k                           ambalaj + operasyonel sürtünme

Skor_k = TELC_k + λ · (CVaR₉₅(hasar) − E[hasar])          ← kuyruk riski primi

Zarar(b) = Σᵢ değerᵢ·şiddetᵢ  +  kontaminasyon·Σⱼ emici_değerⱼ
         + yeniden_gönderim + elleçleme + çağrı  +  p_churn·CLV
```

Tam türetim → [`docs/01-matematiksel-model.md`](docs/01-matematiksel-model.md)

---

## 3 · Mimari: katmanlar ve bağımlılık yönü

```
   dış dünya      ┌──────────────────────────────────────────┐
                  │  api/  ·  cli.py  ·  reporting.py        │   HTTP, terminal, HTML
                  └──────────────────┬───────────────────────┘
                                     │
   kurulum        ┌──────────────────▼───────────────────────┐
                  │  engine.py   (Engine / EngineConfig)     │   bileşenleri birleştirir
                  └──────────────────┬───────────────────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
   ┌─────▼──────┐            ┌───────▼────────┐          ┌───────▼────────┐
   │ adapters/  │            │  decision/     │          │  simulation/   │
   │ dosya, CSV │            │  seçici,kısıt  │          │  dünya,koşucu  │
   └─────┬──────┘            └───────┬────────┘          └───────┬────────┘
         └───────────────────────────┼───────────────────────────┘
                                     │
     ┌───────────┬───────────────────┼───────────────┬────────────┐
┌────▼────┐ ┌────▼────┐        ┌─────▼─────┐   ┌─────▼────┐  ┌────▼────┐
│ tariff/ │ │ packing/│        │   risk/   │   │   sla/   │  │ labels/ │
└────┬────┘ └────┬────┘        └─────┬─────┘   └─────┬────┘  └────┬────┘
     └───────────┴───────────────────┼───────────────┴────────────┘
                                     │
                             ┌───────▼───────┐
                             │   domain/     │   enum, desi aritmetiği, modeller
                             └───────────────┘
```

### ⚠ Katman kuralı (ihlal edilirse mimari bozulur)

`domain`, `packing`, `tariff`, `risk`, `sla`, `decision` = **saf Python çekirdeği.**
Dosya sistemine, HTTP'ye, FastAPI'ye bağımlı **değildir**. Tüm I/O yalnızca
`adapters/` ve `api/` içinde toplanır. Oklar yalnızca aşağı doğru.

Somut faydaları (bunlar kaybedilirse kural ihlal edilmiş demektir):
1. Çekirdek testleri saniyeler sürüyor (277 test ≈ 15 sn, çoğu geçmiş veriyi okumak).
2. Motor CLI'dan, API'den ve simülasyondan **aynı** kurulumla çağrılıyor →
   "API'de farklı davranıyor" sınıfı hatalar yapısal olarak imkânsız.
3. Gerçek veriye geçiş tek modülde: `adapters/contract_import.py`.

---

## 4 · Modül modül harita

Her satır: **ne yapar** / **bilmediği şey** (bu ikinci sütun tasarımın kendisidir).

| Modül | Ana dosyalar & tipler | Sorumluluk | Bilmediği şey |
|---|---|---|---|
| `domain/` | `enums.py`, `models.py` (`Dimensions`, `Product`, `CartLine`, `Cart`, `Address`, `Order`), `units.py` | Desi aritmetiği, para yuvarlaması (`money()`), çekirdek modeller | Kargo firmaları, fiyatlar |
| `packing/` | `packer.py` (`PackingPlanner`, `PackingPlan`, `GroupPacking`), `extreme_point.py`, `geometry.py`, `boxes.py` (`BoxCatalog`), `rules.py` (`PackingRules`), `baselines.py`, `render.py` (SVG) | Koli katalogu, 3B yerleştirme, Pareto plan adayları, baz çizgiler, izometrik görsel | Tarifeler, hasar oranları |
| `tariff/` | `schema.py` (`Tariff`), `loader.py` (`TariffRepository`), `zones.py` (`ProvinceRegistry`), `calculator.py` (`FreightCalculator`, `FreightQuote`, `ParcelCharge`), `surcharges.py` | Şema+doğrulama, il→bölge çözümleme, ücret hesaplama, ek ücret sırası | Paketleme, risk |
| `risk/` | `beta_binomial.py`, `hierarchy.py` (`DamageRateEstimator`), `damage_cost.py` (`DamageCostModel`, `DamageLoss`, `ExpectedDamageCost`, `DamageCostParams`) | Beta-Binom, 4 katmanlı hiyerarşik shrinkage, zarar fonksiyonu | Tarifeler, teslimat süresi |
| `sla/` | `delivery_time.py` (`DeliveryTimeEstimator`, `OvershootFit`, `FittedDelivery`), `delay_cost.py` (`DelayCostModel`, `DelayCostParams`) | log(gerçekleşen/vaat) dağılımı, gecikme maliyeti | Hasar, fiyat |
| `decision/` | `constraints.py` (`check_eligibility`, `Eligibility`, `Ineligibility`, `CapacityLedger`), `objective.py` (`ObjectiveParams`, `CostComponents`, `conditional_value_at_risk`, `tail_premium`), `selector.py` (`CarrierSelector`), `explain.py` | Kısıt denetimi, amaç fonksiyonu, seçim, gerekçe üretimi | Verinin nereden geldiği |
| `labels/` | `barcode.py` (Code 128-B), `zpl.py` | Etiket üretimi; ZPL yetkili çıktı, SVG önizleme | Neden bu firma seçildi (metin olarak alır) |
| `simulation/` | `world.py` (`TrueWorld`, `DeliveryDistribution`, `HistoricalMix`), `generators.py`, `policies.py` (P0–P4), `runner.py` (`SimulationRunner`, `SimulationConfig`, `SimulationResult`, `SensitivitySweep`), `metrics.py` | Gerçek dünya, sipariş üretimi, politikalar, koşucu, metrikler | — (en üst katman) |
| `adapters/` | `protocol.py` (3 `Protocol`), `files.py` (`FileTariffSource`, `Csv*Source`), `contract_import.py` (`from_csv`, `from_excel`, `write_yaml`, `ContractMeta`) | Dosya okuma, gerçek sözleşme içe aktarımı | Motorun ne yaptığı |
| `api/` | `main.py`, `schemas.py`, `mapping.py` | FastAPI uygulaması, DTO'lar, domain↔DTO dönüşümü | — |
| kök | `engine.py`, `cli.py`, `reporting.py` | Kurulum / terminal / bağımsız HTML rapor | — |

### Kritik alt-mekanizmalar (yeni oturumda en çok kafa karıştıranlar)

**A · Sanal kutulama (`packing/packer.py`)**
- Yöntem: köşe noktaları + **yerçekimi oturtması** (önce z, sonra y ve x ekseninde
  çarpana kadar kaydır). Oturtma olmadan dolgu ~%45, oturtmayla ~%65-75.
- Planlayıcı **tek plan değil, Pareto cephesi** üretir: (toplam desi, parça sayısı)
  düzleminde baskın olmayan adaylar. Sebep: asgari ücret **parça başına** uygulanır,
  bu yüzden "en az desi" tek başına doğru amaç değil.
- Fiziksel kurallar (`rules.py`): sıvı emici ürünün üstüne konmaz, kırılabilir dolgu
  payı ister, istif yükü yığın boyunca aşağı yayılır, kargo poşetine cam/sıvı girmez.
- Ürünler dikdörtgen prizma olarak modelleniyor; `compressibility` yumuşak tekstil
  için kısmi telafi.

**B · Bayesçi hasar modeli (`risk/hierarchy.py`)**
```
p₀    = genel ortalama
p_k   = (κ₀·p₀   + d_k)   / (κ₀ + n_k)        firma
p_kz  = (κ₁·p_k  + d_kz)  / (κ₁ + n_kz)       firma × bölge
p_kzc = (κ₂·p_kz + d_kzc) / (κ₂ + n_kzc)      firma × bölge × kategori
```
- 80 hücre (5 firma × 4 bölge × 4 risk kategorisi); veri çok çarpık (en yoğun hücre
  9.118 gönderi, en seyrek 5).
- `κ` **elle seçilmez** — her katmanda marjinal olabilirlik maksimize edilerek veriden
  kestirilir. "n < 30 ise üst katmanı kullan" gibi keyfi eşik **yok**.
- Ölçülen kazanç: MAE %0,71 → **%0,48**, RMSE %1,05 → **%0,83**.
- `RiskCategory` kasıtlı olarak kaba (4 değer), `ProductCategory` (11 değer) değil —
  220 hücrenin çoğu boş kalırdı.

**C · Teslimat ve gecikme (`sla/`)**
- SLA bir **vaat**; motor `log(gerçekleşen / vaat)` dağılımını kestirir. Ölçekten
  bağımsız olduğu için 1 günlük şehir içi hücresi 4 günlük uzak bölge hücresiyle
  aynı havuzda birleşebiliyor.
- `E[(T−d)⁺]` log-normal için **kapalı formda** — Monte Carlo'da milyonlarca kez
  çağrıldığı için sayısal integral her koşuyu dakikalarca uzatırdı.

**D · Monte Carlo (`simulation/`)** — üç metodolojik ilke:
1. **Motor gerçeği bilmez.** `TrueWorld` gerçek olasılıkları tutar; karar motoru
   yalnızca ondan üretilmiş *gözlenmiş geçmiş veriyi* görür. (→ `docs/adr/0003`)
2. **Ortak rastgele sayılar.** Şans çekilişleri sipariş başına bir kez yapılır, tüm
   politikalar aynı çekilişleri kullanır (`_CommonRandomNumbers`).
3. **Eşleştirilmiş bootstrap.** Fark dağılımından %95 G.A.; aralık sıfırı kapsıyorsa
   rapor **"ANLAMSIZ"** yazar.
- Politikalar: `P0` tek firma (baz) · `P1` en ucuz nakliye · `P2` en hızlı ·
  `P3` TELC (bu motor) · `P4` TELC + kapasite kısıtı.
- Kalibrasyon: ECE ≈ 0,0042–0,0046.

---

## 5 · Veri katmanı

```
backend/data/
├─ carriers/     aras.yaml, mng.yaml, ptt.yaml, surat.yaml, yurtici.yaml   (5 firma, SENTETİK)
├─ zones/        tr_iller.csv          81 il → bölge/mesafe
├─ boxes/        catalog.yaml          standart koli katalogu (K04, K09, K10, ...)
├─ catalog/      products.csv          48 ürün (ölçü, ağırlık, kırılganlık, sıvı/emici)
└─ history/      shipments.csv         ~3,3 MB sentetik geçmiş sevkiyat (hasar+teslimat)

backend/scripts/ generate_synthetic_tariffs.py · generate_synthetic_history.py
backend/examples/ banyo_seti · buyuk_tekstil · kirilabilir · zeytinyagi_nevresim (.json)
```

**Sentetik/gerçek ayrımı kodda değil, veride.** `Tariff.source` alanı
(`synthetic` | `contract`) API cevabına, arayüzdeki **"ÖRNEK TARİFE"** rozetine ve
basılan etikete kadar taşınır. Motorda "sentetik mod" diye bir kod yolu **yok**.

**Gerçek veriye geçiş yuvası:** `adapters/contract_import.py` → `from_csv` / `from_excel`
+ `ContractMeta` → `write_yaml(...)`. Çekirdeğin hiçbir satırı değişmez. Yükleme
sırasında **fiyat monotonluğu doğrulanır** (elle düzenlenmiş matriste en sık ve en zor
fark edilen hata). Beklenen matris biçimi:
```csv
up_to_desi,sehir_ici,bolge_ici,bolgeler_arasi,uzak
1,62.00,70.00,81.00,92.00
```
Aynı yuva geçmiş veri ve ürün katalogu için de var: `adapters/protocol.py` üç `Protocol`
tanımlar (`TariffSource`, `ProductCatalogSource`, `ShipmentHistorySource`) — ERP'den
çeken bir istemci bu paketi hiç bilmeden geçerli bir kaynak olur.

> ⚠ **`kargo.txt` (depo kökü)** — DHL / Aras / Yurtiçi için **gerçek görünümlü** bir
> tarife matrisi içeriyor ("tüm bölgeler tek fiyat", dosya ücreti, 31–9999 desi birim
> fiyatı, ağır kargo hizmeti). **Hiçbir kod bu dosyayı okumuyor.** DHL `CarrierCode`
> enum'unda da yok. Bu, projenin en belirgin açık ucu → §11.

---

## 6 · Dış yüzeyler

### CLI (`python -m desi_engine.cli <cmd>` veya `desi <cmd>`)
| Komut | Ne yapar | Örnek |
|---|---|---|
| `rate` | Tüm firmaların teklifleri, kalem kalem | `rate --cart examples/banyo_seti.json --city 34` |
| `decide` | Karar + gerekçe | `decide --cart examples/zeytinyagi_nevresim.json --city 65 --explain` |
| `pack` | Koli planı, desi tasarrufu, `--render out/koli.svg` | `pack --cart examples/buyuk_tekstil.json --verbose` |
| `simulate` | Monte Carlo + HTML rapor | `simulate --orders 20000 --seed 42 --report reports/simulasyon.html` |

### HTTP API (FastAPI, `uvicorn desi_engine.api.main:app --reload` → `:8000/docs`)
```
GET  /api/v1/health
GET  /api/v1/catalog/products      GET /api/v1/catalog/cities      GET /api/v1/carriers
POST /api/v1/pack        POST /api/v1/rate       POST /api/v1/decide     POST /api/v1/label
GET  /api/v1/risk/heatmap
POST /api/v1/simulate    GET /api/v1/simulate/{run_id}      (arka planda koşar, bellekte tutulur)
```
Sözleşme testi: cevap **katı JSON** (NaN/Infinity yok), sentetik bayrağı her yerde.

### Arayüz (`frontend/`, Vite + React + TS, `npm run dev` → `:5173`)
- Sekmeler (`App.tsx`, tek paylaşılan `order` state'i): **Sanal kutulama · Karar ve
  gerekçe · Etiket · Risk haritası · Simülasyon · Firmalar ve tarifeler**
- `src/api/client.ts` + `types.ts` · `components/` (`OrderBuilder`, `BoxViewer`, `charts`)
  · `pages/` (`PackingPage`, `DecisionPage`, `LabelPage`, `RiskPage`, `SimulationPage`)
- **Grafik kütüphanesi ve 3B kütüphanesi YOK.** Grafikler elle yazılmış SVG; koli
  görünümü izometrik izdüşüm + ressam algoritması (~150 satır). Çıktı 190 KB JS (60 KB gzip).
- Yarış koşulu koruması: `requestId` ile **son gönderilen** kazanır, son gelen değil.

---

## 7 · Değişmez kurallar (değiştirmeden önce iki kez düşün)

1. **Katman kuralı** — çekirdek modüller I/O bilmez (§3).
2. **Planlayıcı tarifeyi bilmez, karar motoru paketlemeyi bilir.** Asimetri kasıtlı:
   paketleme tarifeye bağlansaydı, tarife değiştiğinde paketleme önbelleği geçersiz
   olur, Monte Carlo'da önbellek isabeti %48 → %0 düşerdi. → `docs/adr/0002`
3. **Plan seçimi ile firma seçimi birlikte yapılır.** Önce "en iyi plan" seçip sonra
   firma aramak yanlış: PTT'nin 50 desilik parça sınırı, tek koliye sıkıştıran planı
   onun için uygunsuz kılarken iki koliye bölen planı uygun kılar.
4. **Motor gerçeği bilmez** (simülasyonda). → `docs/adr/0003`
5. **Para `float`, sınırlarda `Decimal`.** Motor içinde `float` (numpy vektörleştirme);
   yalnızca sunum/fatura sınırında `money()` ile kuruşa sabitlenir (yarısı yukarı).
   Python'un yerleşik `round()` bankacı yuvarlaması yapar (`round(2.675,2)==2.67`) —
   fatura satırında istenen davranış bu değil.
6. **Sentetik bayrağı zorunlu ve testle korunuyor** (§5).
7. **Testler tek tek sayılara değil değişmezlere yazılır.** "Bu sepet 18,30 desi
   üretmeli" tipi test her iyileştirmede kırılır; "hiçbir iki ürün üst üste binmez" veya
   "sıvı asla emicinin üstünde olmaz" kırılırsa **her zaman** gerçek bir hatadır.
8. **Kodda gömülü fiyat yok.** Tarife dosyası elle değiştirilince motor yeni fiyatı
   kullanır (`TariffRepository.reload()`).

---

## 8 · Mevcut durum

| Alan | Durum |
|---|---|
| Testler | **277 test yeşil**, ~15 sn |
| Kapsam | toplam **%87**, çekirdek modüllerde **%91-100** |
| Lint | `ruff check` + `ruff format --check` temiz |
| Frontend | `npm run typecheck && npm run build` geçiyor |
| Performans | 35,1 → **11,4 ms/sipariş** (3,1×); 20.000 siparişlik koşu ~3,8 dk |
| Kalibrasyon | ECE ≈ 0,0042 |

**Simülasyon sonucu (20.000 sipariş, tohum 42), TL/sipariş:**

| Politika | Toplam | Nakliye | Gizli pay | Hasar | Gecikme | Ort. gün |
|---|---:|---:|---:|---:|---:|---:|
| P0 Tek firma (mevcut) | 398,32 | 328,16 | %17,6 | %1,00 | %13,1 | 2,06 |
| **P1 En ucuz nakliye** | **464,86** | **290,38** | %37,5 | %2,79 | %36,7 | 4,31 |
| P2 En hızlı | 406,79 | 354,73 | %12,8 | %0,60 | %8,3 | 1,50 |
| **P3 TELC (bu motor)** | **388,59** | 318,09 | %18,1 | %1,07 | %16,0 | 2,37 |
| P4 TELC + kapasite | 388,67 | 318,14 | %18,1 | %1,07 | %16,0 | 2,38 |

P3 vs P0: **+9,73 TL/sipariş** (%2,44), %95 G.A. [+6,79, +13,12] — anlamlı.
P3 vs P1: **+76,27 TL/sipariş** (%16,4), G.A. [+67,81, +85,11] — anlamlı.

**6 kabul kriterinin tamamı ✅** (detay: README "Doğrulama" bölümü).

### Doğrulama komutları (her oturum sonunda çalıştır)
```bash
cd backend
pip install -e ".[dev]"                          # ilk kurulum
pytest -q                                        # 277 test
pytest --cov=desi_engine --cov-report=term
ruff check src tests scripts && ruff format --check src tests scripts
cd ../frontend && npm run typecheck && npm run build
```
> **Windows notu:** depo yolunda Türkçe karakter var (`C:\OZDİLEK`) → Python konsol
> kodlaması bozulabilir. `$env:PYTHONUTF8=1` (PowerShell) bunu çözer. **Her yeni
> terminalde gerekir.**

---

## 9 · Bağımlılıklar

**Backend** (Python ≥3.11): `pydantic≥2.7`, `numpy`, `scipy`, `pandas`, `pyyaml`,
`fastapi`, `uvicorn[standard]` · dev: `pytest`, `pytest-cov`, `hypothesis`, `httpx`,
`ruff` · opsiyonel: `openpyxl` (excel içe aktarım).
**Frontend:** Vite + React + TypeScript. Grafik/3B kütüphanesi yok — bilinçli tercih.
**Yeni bağımlılık eklemek varsayılan olarak reddedilir**; SVG/kapalı form tercih edilmiştir
(ör. PNG yerine SVG, matplotlib/Pillow eklememek için).

---

## 10 · Dokümanlar

| Dosya | İçerik |
|---|---|
| `README.md` | Vitrin: problem, sonuçlar, hızlı başlangıç, kabul kriterleri |
| [`docs/01-matematiksel-model.md`](docs/01-matematiksel-model.md) | Tam türetim: Beta-Binom, CVaR, kalibrasyon |
| [`docs/02-veri-sozlesmesi.md`](docs/02-veri-sozlesmesi.md) | Tarife / katalog / geçmiş veri şemaları |
| [`docs/03-mimari.md`](docs/03-mimari.md) | Katmanlar, bağımlılık yönü, performans, test stratejisi |
| [`docs/04-veri-talep-listesi.md`](docs/04-veri-talep-listesi.md) | **Kurum içi paylaşım için** — hangi veri hangi departmandan isteniyor. Teknik değil, iletilebilir dil |
| [`docs/adr/0001-baz-cizgi-secimi.md`](docs/adr/0001-baz-cizgi-secimi.md) | Baz çizgi neden bu |
| [`docs/adr/0002-planlayici-tarifeyi-bilmez.md`](docs/adr/0002-planlayici-tarifeyi-bilmez.md) | Asimetrinin gerekçesi |
| [`docs/adr/0003-motor-gercegi-bilmez.md`](docs/adr/0003-motor-gercegi-bilmez.md) | Simülasyonun dürüstlüğü |
| **`graph.md`** (bu dosya) | Oturumlar arası harita + durum + açık uçlar |

---

## 11 · Açık uçlar ve bilinen sınırlar

> Sıradaki iş buradan seçilir. Bir madde ele alınacaksa önce `plans/` altında plan
> dosyası açılır (§12), iş bitince madde buradan **çıkarılır** ve §8/§12 güncellenir.

### Aktif açık uçlar (öncelik sırasıyla)

| # | Konu | Not |
|---|---|---|
| A1 | **`kargo.txt` entegre değil** | Depo kökünde DHL/Aras/Yurtiçi için gerçek görünümlü tarife matrisi var, hiçbir kod okumuyor. Biçimi mevcut `from_csv` şemasına uymuyor (tek fiyatlı bölge, "1–5" aralık gösterimi, dosya ücreti, 31–9999 birim fiyat, ağır kargo hizmeti). Karar gerekli: dönüştürücü yazılsın mı, `ContractMeta` genişletilsin mi. |
| A2 | **DHL `CarrierCode`'da yok** | A1 yapılacaksa enum + veri + testler birlikte genişletilmeli (5 → 6 firma; risk hücresi 80 → 96). |
| A3 | **Git deposu başlatılmamış** | `.gitignore` var ama repo yok. Oturumlar arası takip için ilk commit önerilir. |
| A4 | **Hacim taahhüdü gölge fiyatı (`V_k`) uygulanmadı** | Açgözlü seçim yıllık taahhüt kademesini kaçırabilir. Planlanan çözüm: Lagrange duali. Matematiksel modelde yeri hazır. |
| **A5** | **Gerçek veriye geçiş — veri toplama** | 🔵 **AKTİF** → [`plans/AKTIF-gercek-veri-gecisi.md`](plans/AKTIF-gercek-veri-gecisi.md). Tam envanter çıkarıldı: 5 veri dosyası (tarife, koli, ürün, geçmiş sevkiyat, il) + kodda varsayılan olan maliyet parametreleri. Kod değişikliği gerektirmiyor; iş veri toplamada. A1 ile karıştırılmamalı — A5 şema-uyumlu veri, A1 firmadan gelen ham dosya. |
| **A6** | **Gerçek veri altyapısında üç boşluk** | Altyapının büyük kısmı hazır (dosya değiştir → çalışır), ama üç eksik var. Detay + düzeltme taslakları → [`plans/AKTIF-gercek-veri-gecisi.md`](plans/AKTIF-gercek-veri-gecisi.md) §7. Küçük işler, mimariyi değiştirmiyor. |
| ↳ A6.1 | `Protocol`'ler `Engine`'e takılamıyor | `EngineConfig` yalnızca `data_dir` alıyor; `engine.py` okuyucuları sabit kuruyor. "ERP'den çeken sınıf yaz, motor değişmez" iddiası protokol düzeyinde doğru, **kurulum düzeyinde değil**. |
| ↳ A6.2 | `shipments.csv` sütun doğrulaması yok | `CsvShipmentHistorySource.load` düz `pd.read_csv`. Eksik sütun, model eğitiminin ortasında `KeyError` olarak çıkıyor. Ürün katalogunda karşılığı var, burada yok. Gerçek ERP verisinde en olası hata. |
| ↳ A6.3 | Maliyet parametrelerinin dosya yolu yok | `DamageCostParams` / `DelayCostParams` / `ObjectiveParams` yalnızca kod düzeyinde. Diğer her şey veri dosyasında olduğu için tutarsızlık; muhasebeden gelen rakamı güncellemek Python dokunmayı gerektiriyor. |

### Kalıcı sınırlar (bilinçli tercihler — "eksik" değil, "kapsam dışı")

- **Barkod fiziksel okuyucuyla test edilmedi.** ZPL yetkili çıktı (barkodu yazıcı
  kodlar); SVG önizleme yapısal olarak doğrulanıyor (modül sayısı, sağlama toplamı).
- **3B yerleştirme tam projeksiyon tabanlı Extreme Point değil** — köşe noktaları +
  yerçekimi oturtması; ürünler dikdörtgen prizma.
- **Koli görseli SVG, PNG değil** (Pillow/matplotlib bağımlılığı eklememek için).
- **Teslimat modelindeki shrinkage basitleştirilmiş** — hasarda `κ` marjinal
  olabilirlikle kestirilirken teslimatta sabit sözde-gözlem sayısı (`SHRINKAGE_PSEUDO_COUNT`);
  teslimat hücreleri çok daha kalabalık olduğu için marjinal katkı küçük.
- **Simülasyon koşuları bellekte tutuluyor** — tek kullanıcılı demo için yeterli;
  çok kullanıcılı kurulumda kalıcı depoya taşınmalı.
- **Sonuçlar sentetik dünyaya bağlı.** "%17 tasarruf" rakamı `simulation/world.py`
  varsayımlarının sonucudur. Gerçek Özdilek verisiyle sayı değişir; değişmeyecek olan
  **hangi maliyet kalemlerinin ölçüldüğü**dür.

---

## 12 · Oturum protokolü ve kayıtlar

### Plan dosyası düzeni

```
plans/
├─ AKTIF-gercek-veri-gecisi.md   ← ŞU AN AKTİF: gerçek veri ihtiyaç envanteri
└─ arsiv/<tarih>-<konu>.md       ← bitince buraya taşınır
```

Bir plan dosyası şunları içerir: **Amaç · Kapsam dışı · Adımlar (kutucuklu) · Etkilenen
dosyalar · Doğrulama kriteri · Durum notları.** Kod ayrıntısı plan dosyasında kalır;
`graph.md`'ye yalnızca **kalıcı olan** (mimari, kural, durum) yazılır.

### Oturum sonu rutini

1. `pytest -q` + `ruff check` + frontend `typecheck` → sonucu §8'e yaz.
2. Değişen mimari/kural varsa §3, §4, §7'yi güncelle.
3. Açık uç kapandıysa §11'den çıkar; yeni açık uç doğduysa ekle.
4. Aşağıdaki tabloya bir satır ekle. **Bir sonraki adım** sütunu boş bırakılmaz —
   yeni oturum oradan başlar.

### Kayıtlar

| Tarih | Yapılan | Doğrulama | Bir sonraki adım |
|---|---|---|---|
| 2026-08-13 | `graph.md` oluşturuldu: mimari, veri akışı, modül haritası, değişmez kurallar, açık uçlar ve oturum protokolü çıkarıldı. Kod değişikliği yok. | — (yalnızca dokümantasyon) | §11'den bir madde seçilecek. |
| 2026-08-13 | **A5 açıldı:** gerçek veriye geçiş için tam veri envanteri çıkarıldı → [`plans/AKTIF-gercek-veri-gecisi.md`](plans/AKTIF-gercek-veri-gecisi.md). 5 veri dosyası + maliyet parametre bloğu, kaynak/zorluk/öncelik işaretli, kademeli geçiş sırası tanımlı. Kod değişikliği yok. | — (yalnızca dokümantasyon) | Veri toplama: **tarife → koli katalogu → ürün ölçüleri**. |
| 2026-08-13 | **A6 açıldı:** gerçek veri altyapısı denetlendi (plan §7). Tarife/koli/ürün tarafı eksiksiz çıktı; üç boşluk bulundu — Protokoller `Engine`'e takılamıyor (A6.1), `shipments.csv` sütun doğrulaması yok (A6.2), maliyet parametrelerinin dosya yolu yok (A6.3). Düzeltme taslakları plana yazıldı. Kod değişikliği yok. | — (yalnızca dokümantasyon) | **İki kol paralel:** *veri kolu* dış kaynak beklemede (tarife→koli→ürün); *kod kolu* hemen başlayabilir → **A6.2** (en küçük, gerçek `shipments.csv` gelmeden bitmeli) → A6.1 → A6.3. Ayrıca **A3** (git init) hâlâ açık. |
