# AKTIF · Gerçek veriye geçiş — veri ihtiyaç listesi

> **Durum:** veri toplama aşaması · **Açıldı:** 2026-08-13 · **İlgili:** [`../graph.md`](../graph.md) §5, §11
> **Kod değişikliği gerektirmez.** Motorun sentetik ve gerçek hâli arasındaki tek fark
> `adapters/contract_import.py`; çekirdeğin (`domain`, `packing`, `tariff`, `risk`, `sla`,
> `decision`) hiçbir satırı değişmez. Bu dosya **hangi verinin kimden isteneceğini** listeler.

---

## Amaç

Motoru sentetik veriden gerçek Özdilek verisine taşımak için gereken **tam veri
envanterini** çıkarmak, kaynağını ve zorluğunu işaretlemek, kademeli geçiş sırası belirlemek.

## Kapsam dışı

- Depo kökündeki `kargo.txt` **kullanılmıyor** — firmadan gelen ham dosya, biçimi
  farklı, bu aşamada karışılmayacak. (Açık uç olarak `graph.md` §11/A1'de duruyor.)
- Yeni kargo firması eklenmesi (DHL vb. → A2) bu planın parçası değil.
- Motor mantığında, şemada veya amaç fonksiyonunda değişiklik yok.

---

## 1 · Kargo tarifesi — firma başına

**Dosya:** `backend/data/carriers/<firma>.yaml` · **Kaynak:** sözleşme metni + satın alma
**Zorluk:** düşük · **Öncelik:** 1

Fiyat matrisi **tek başına yetmez.** `ContractMeta` bilinçli olarak varsayılansız
tanımlandı — sessizce yanlış bir yakıt farkı varsaymak, sistematik olarak yanlış firma
seçtirir ve fark edilmesi neredeyse imkânsızdır.

| Alan | Ne isteniyor | Not |
|---|---|---|
| `desi_tiers[].zones` | Her desi kademesi × **4 bölge** fiyatı | `sehir_ici, bolge_ici, bolgeler_arasi, uzak` — dördü de zorunlu |
| `over_30_per_desi` | Tablo üstü desi başı birim fiyat (4 bölge) | Son kademenin üstü böyle fiyatlanır |
| `min_charge` | Asgari ücret | ⚠ **parça başına** uygulanır, gönderi başına değil |
| `rounding` | `ceil` / `half_up` / `none` | Kademe sınırında tek başına fiyatı değiştirir |
| `desi_step` | Ücretli desi adımı | Genelde 1.0 |
| `surcharges.fuel_pct` | Yakıt farkı oranı | ⚠ **indirimden sonra** uygulanır |
| `surcharges.cod_fee` | Kapıda ödeme bedeli | Gönderi başına bir kez |
| `surcharges.insurance` | `free_limit` + `pct_above` | Muafiyet üstü tutarın yüzdesi |
| `surcharges.vat_pct` | KDV | |
| `volume_discounts` | `(aylık_gönderi_eşiği, indirim_oranı)` listesi | Artan eşiğe göre sıralı |
| `service.sla_days` | 4 bölge için vaat edilen gün | Vaat, gerçekleşme değil |
| `service.rural_extra_days` | Kırsal ek gün | |
| `service.cutoff` | Aynı gün çıkış son saati | `"17:00"` biçiminde |
| `constraints.max_desi_per_parcel` | Parça başına azami desi | Plan seçimini doğrudan etkiler |
| `constraints.cod_supported` | Kapıda ödeme var mı | |
| `constraints.unserved_plates` | Hizmet verilmeyen il plakaları | |

**İki uyarı:**
- Şema, fiyatın desi arttıkça **düşmesini** reddeder (`TariffLoadError`). Eşit olması
  sorun değil, düşmesi sorun. Elle düzenlenmiş matriste en sık ve en zor fark edilen hata.
- Firma "tüm bölgeler tek fiyat" veriyorsa aynı değer 4 sütuna yazılır. Motor çalışır,
  ama bölge ayrımının karar gücü o firma için sıfırlanır.

**İçe aktarım:**
```python
from desi_engine.adapters import ContractMeta, from_csv, write_yaml
tarife = from_csv(Path("firma_2026.csv"), meta)   # veya from_excel(...)
write_yaml(tarife, Path("backend/data/carriers"))
```
Beklenen matris biçimi:
```csv
up_to_desi,sehir_ici,bolge_ici,bolgeler_arasi,uzak
1,62.00,70.00,81.00,92.00
```
İçe aktarılan tarife `source: contract` işaretlenir → arayüzdeki **"ÖRNEK TARİFE"**
rozeti o firmadan kalkar.

- [ ] Firma listesi kesinleşti (şu an 5: ARAS, MNG, YURTICI, SURAT, PTT)
- [ ] Her firma için fiyat matrisi alındı
- [ ] Her firma için `ContractMeta` alanları sözleşmeden dolduruldu
- [ ] `from_csv` + `write_yaml` ile YAML üretildi, monotonluk doğrulaması geçti

---

## 2 · Koli katalogu — en yüksek getiri / çaba oranı

**Dosya:** `backend/data/boxes/catalog.yaml` · **Kaynak:** depo ambalaj stoğu
**Zorluk:** çok düşük · **Öncelik:** 2

```yaml
- code: K05
  name: Büyük kutu
  inner: {length_cm: 40, width_cm: 30, height_cm: 20}
  wall_cm: 0.5              # oluklu mukavva et kalınlığı
  tare_kg: 0.47
  max_payload_kg: 20
  unit_cost_try: 11.80
  soft_only: false          # true = kargo poşeti
```

⚠ **İç ölçü ≠ dış ölçü.** `dış_kenar = iç_kenar + 2 × wall_cm`; fatura **dış** ölçüden
kesilir. Bu ayrım atlanırsa her koli sistematik olarak düşük desi tahmin eder; büyük
kolilerde fark bir tarife kademesine denk gelebiliyor.

`soft_only: true` (kargo poşetleri) kırılabilir veya sıvı ürün kabul etmez.

- [ ] Depoda fiilen kullanılan koli/poşet tipleri listelendi
- [ ] Her tip için iç ölçü + et kalınlığı ölçüldü
- [ ] Darası, azami taşıma yükü, birim maliyeti alındı

---

## 3 · Ürün katalogu

**Dosya:** `backend/data/catalog/products.csv` · **Zorluk:** orta · **Öncelik:** 3

```csv
sku,name,category,length_cm,width_cm,height_cm,weight_kg,unit_price_try,
fragility,is_liquid,is_absorbent,stackable,max_stack_load_kg,compressibility
```

İki farklı kaynağa bölünüyor:

**A · ERP / PIM'den gelir**
`sku, name, category, length_cm, width_cm, height_cm, weight_kg, unit_price_try`
→ ⚠ Ölçüler ürünün **satış ambalajlı** hâli olmalı, çıplak ürün değil.
→ `category` = `ProductCategory` (11 değer: havlu, nevresim, bornoz, battaniye, perde,
ev_dekor, mutfak, deterjan, gida_sivi, kisisel_bakim, kucuk_ev_aleti)

**B · ERP'de yoktur, elle atanır**

| Sütun | Değerler | Ne belirler |
|---|---|---|
| `fragility` | `yok` / `dusuk` / `orta` / `yuksek` | Dolgu payı + hasar şiddeti |
| `is_liquid` | 0/1 | Sızıntı kaynağı olabilir |
| `is_absorbent` | 0/1 | Sızıntıdan zarar görür (yan hasarın kurbanı) |
| `stackable` | 0/1 | Üzerine ürün konabilir mi |
| `max_stack_load_kg` | kg | Taşıyabileceği azami yük |
| `compressibility` | 0–0,35 | Yumuşak tekstilin ezilme oranı |

→ Binlerce SKU için tek tek değil: **kategori → öntanım eşlemesi** kurup istisnaları elle
düzeltmek pratik yol. Bir ürün hem sıvı hem emici olamaz (`Product` doğrulaması reddeder).

- [ ] ERP'den ölçü + ağırlık + fiyat çekildi
- [ ] Ölçülerin ambalajlı hâl olduğu doğrulandı
- [ ] Kategori → fiziksel bayrak öntanım tablosu hazırlandı
- [ ] İstisnalar (sıvı, cam, cihaz) elle işaretlendi

---

## 4 · Geçmiş sevkiyat — en zor, en değerli

**Dosya:** `backend/data/history/shipments.csv` · **Zorluk:** yüksek · **Öncelik:** 4
**Şu an:** 59.913 satır sentetik. Motorun hasar ve teslimat hakkındaki **tek** bilgi kaynağı.

```csv
shipment_id,carrier,dest_plate,zone,risk_category,is_rural,
declared_value_try,promised_days,delivery_days,damaged
```

| Sütun | Nereden | Zorluk |
|---|---|---|
| `carrier`, `dest_plate` | ERP sevkiyat kaydı | kolay |
| `zone` | **türetilir** — ham veride olmasa da `ProvinceRegistry` hesaplar | — |
| `risk_category` | sipariş içeriğinden baskın kategori (4 sınıf) | türetilir |
| `is_rural`, `declared_value_try` | ERP | kolay |
| `promised_days` | o gönderinin **o günkü** SLA'si (kırsal +1) | ⚠ genelde kayıtlı değil; sözleşme SLA tablosundan geriye dönük hesaplanır. **Zorunlu** — model `log(gerçekleşen/vaat)` üzerinde çalışıyor |
| `delivery_days` | teslim − çıkış, **sürekli** değer | tamsayı gün varsa çalışır, çözünürlük düşer |
| `damaged` | 0/1 — hasar & iade kayıtları | ⚠ **en zor kalem**, aşağıya bak |

**`damaged` tanımı sabitlenmeli.** Müşteri beyanı mı, depo iade kabulü mü, sigorta
dosyası mı? Tanım veri kümesi içinde kayarsa oranlar anlamsızlaşır ve model bunu fark
edemez. Tek bir tanım seçilip tüm dönem için tutarlı uygulanmalı.

**Hacim ihtiyacı.** 5 firma × 4 bölge × 4 risk kategorisi = **80 hücre**.
- ~10–15 bin sevkiyat → anlamlı sonuç
- ~50–60 bin → ideal
- Az veri modeli **çökertmez**: hiyerarşik shrinkage otomatik olarak üst katmana yaslanır
  (tasarım zaten bunun için). Dengesiz veri sorun değil, beklenen durum.

**Hiç yoksa ne olur.** Motor `p̂` kestiremez. Seçenekler: (a) firma/sektör yayınlanmış
oranları önsel olarak girilir, (b) geçici olarak "nakliye + gecikme" modunda koşulur —
ama projenin ana iddiası (gizli hasar maliyeti) ölçülemez hâle gelir.

- [ ] `damaged` tanımı seçildi ve yazıya döküldü
- [ ] ERP sevkiyat + kargo takip + iade/hasar kayıtları birleştirildi
- [ ] `promised_days` geriye dönük hesaplandı
- [ ] Hücre başına gönderi sayısı dağılımı çıkarıldı (en seyrek hücre kaç gönderi?)

---

## 5 · İl kayıtları — zaten gerçek

**Dosya:** `backend/data/zones/tr_iller.csv` · **Öncelik:** 5 (yalnızca gözden geçirme)

`plate, name, region, population, lat, lon, is_remote` — gerçek veri (TÜİK nüfus, koordinat).
Değiştirilmesi gerekmeyen tek dosya. Bölge sınıfı tabloya yazılmaz, **türetilir**
(aynı il → `SEHIR_ICI`; `is_remote` → `UZAK`; aynı bölge → `BOLGE_ICI`; >900 km → `UZAK`;
diğer → `BOLGELER_ARASI`).

- [ ] Çıkış deposu plakası doğrulandı (`DEFAULT_ORIGIN_PLATE` = 16 / Bursa)
- [ ] `is_remote` listesi Özdilek operasyonuna göre gözden geçirildi

---

## 6 · Maliyet parametreleri — dosyada değil, kodda varsayılan

Bunlar da **veri**, şu an tahmin. Kaynak: maliyet muhasebesi, iade istatistikleri, CRM.

### `DamageCostParams` — `risk/damage_cost.py`

| Parametre | Şimdiki | Kaynak |
|---|---:|---|
| `severity[yumusak]` | 0,35 | iade kayıtlarında kurtarılan değer oranı |
| `severity[cihaz]` | 0,80 | " |
| `severity[sivi]` | 0,85 | " |
| `severity[kirilabilir]` | 0,95 | " |
| `contamination_spread` | 0,85 | sızıntı vakalarında yan hasar görülme oranı |
| `reship_freight_try` | 120 TL | lojistik maliyet muhasebesi |
| `handling_cost_try` | 45 TL | depo elleçleme + yeniden paketleme |
| `call_center_cost_try` | 35 TL | çağrı başı maliyet |
| `churn_probability` | 0,18 | CRM kohort analizi (hasar sonrası) |
| `risk_aversion_level` | `None` | politika kararı: az veriye sahip firma riskli sayılsın mı |

### `DelayCostParams` — `sla/delay_cost.py`

| Parametre | Şimdiki | Kaynak |
|---|---:|---|
| `call_center_cost_try` | 35 TL | çağrı başı maliyet |
| `return_probability_if_late` | 0,09 | iade istatistikleri |
| `return_cost_try` | 165 TL | iade nakliyesi + depo kabul + stok düzeltme |
| `goodwill_per_day_try` | 22 TL | kupon / indirim / telafi bütçesi |
| `churn_probability_if_late` | 0,06 | CRM |
| `max_charged_lateness_days` | 10 | politika kararı (kuyruk tavanı) |

### `ObjectiveParams` — `decision/objective.py`

| Parametre | Şimdiki | Kaynak |
|---|---:|---|
| `risk_aversion_lambda` | 0,0 | yönetim kararı — 0 = risk-nötr |
| `operational_cost_try` (firma başına) | 0 | zayıf API entegrasyonu, elle veri girişi, şube teslim zorunluluğu |
| `include_packaging_cost` | `True` | |

### `EngineConfig` — `engine.py`

| Parametre | Şimdiki | Kaynak |
|---|---:|---|
| `monthly_parcel_volume` | 7.000 | ⚠ gerçek aylık gönderi adedi — **hacim indirim kademesini** doğrudan belirler |
| `origin_plate` | 16 (Bursa) | operasyon |

### Sipariş bazında

| Alan | Kaynak |
|---|---|
| `customer_clv_try` | CRM müşteri yaşam boyu değeri |

**Bunlar yanlışsa ne olur:** mutlak TL rakamı kayar ama **firma sıralaması çoğunlukla
korunur**. `SensitivitySweep` (`simulation/runner.py`) tam olarak bunu test etmek için var
— gerçek değerler geldiğinde önce duyarlılık taraması koşulmalı.

- [ ] Muhasebeden birim maliyetler alındı (çağrı, elleçleme, iade, yeniden gönderim)
- [ ] CRM'den churn oranları ve CLV alındı
- [ ] Gerçek aylık gönderi adedi öğrenildi
- [ ] Duyarlılık taraması koşuldu, sıralamanın kararlılığı doğrulandı

---

## 7 · Altyapı durumu — neyin hazır olduğu, neyin olmadığı

> Bu bölüm `graph.md` §11/**A6** ile eşleşir. Veri toplanırken paralel yürütülebilir;
> hiçbiri mimariyi değiştirmiyor.

### Hazır (dokunulmasına gerek yok)

| # | Ne | Nerede |
|---|---|---|
| ✅ | **Çekirdek hiçbir dosya okumuyor** — tüm giriş `adapters/` üzerinden | katman kuralı, `graph.md` §3 |
| ✅ | **Tarife okuma + tam şema doğrulaması** (monotonluk, eksik bölge, tekil firma) | `tariff/loader.py`, `tariff/schema.py` |
| ✅ | **Sözleşme dönüştürücüsü** `from_csv` / `from_excel` + `ContractMeta` → `write_yaml` | `adapters/contract_import.py` |
| ✅ | **`source: synthetic\|contract` bayrağı** — API → arayüz rozeti → ZPL etiketine kadar taşınıyor | `tariff/schema.py::is_synthetic` |
| ✅ | **Sıcak yeniden yükleme** — fiyat değişince süreç yeniden başlatılmıyor | `TariffRepository.reload()` |
| ✅ | **Bozuk veri sessizce geçmiyor** — tek bozuk dosya tüm yüklemeyi durduruyor | `TariffLoadError` |
| ✅ | **Ürün katalogu sütun doğrulaması** + tekil SKU + satır bazlı hata mesajı | `adapters/files.py::PRODUCT_COLUMNS` |
| ✅ | **Koli / il dosyaları** dosya değişimiyle çalışıyor | `BoxCatalog.from_yaml`, `ProvinceRegistry.from_csv` |
| ✅ | **Maliyet parametreleri enjekte edilebilir** | `EngineConfig(damage_params=…, delay_params=…, objective=…, monthly_parcel_volume=…, origin_plate=…)` |
| ✅ | **Üç `Protocol` tanımlı** (`runtime_checkable`) | `adapters/protocol.py` |

**Sonuç:** §1 (tarife), §2 (koli), §3 (ürün) için altyapı **eksiksiz** — bugün doğru
içerikli dosyaları koysan çalışır. Aşağıdaki üç boşluk yalnızca §4 (geçmiş sevkiyat),
canlı ERP bağlantısı ve §6 (parametreler) tarafında.

### A6.1 · `Protocol`'ler `Engine`'e takılamıyor

`adapters/protocol.py` üç protokol tanımlıyor ve dokümantasyon "ERP'den çeken bir sınıf
yaz, motorun hiçbir satırı değişmez" diyor. **Protokol düzeyinde doğru, kurulum düzeyinde
değil:** `EngineConfig` yalnızca `data_dir` alıyor, `engine.py` okuyucuları sabit kuruyor:

```python
@cached_property
def tariff_source(self) -> FileTariffSource:
    return FileTariffSource(self.data_dir / "carriers")     # ← sabit
```

Bugün özel bir kaynak yazsan `Engine`'e veremezsin; `CarrierSelector`'ı elle kurman gerekir.

**Düzeltme taslağı:** `EngineConfig`'e üç opsiyonel alan; `None` ise mevcut dosya
okuyucusuna düş.
```python
tariff_source: TariffSource | None = None
product_source: ProductCatalogSource | None = None
history_source: ShipmentHistorySource | None = None
```
- [ ] `EngineConfig` alanları eklendi, `cached_property`'ler `or` ile geri düşüyor
- [ ] Sahte bir kaynakla enjeksiyon testi yazıldı (`test_adapters.py`)

### A6.2 · `shipments.csv` sütun doğrulaması yok

`CsvShipmentHistorySource.load` düz `pd.read_csv` yapıyor. Ürün katalogunda eksik sütun
anında ve anlaşılır patlıyor; geçmiş veride ise hata **model eğitiminin ortasında**
`KeyError` olarak çıkıyor. Gerçek ERP verisinde en olası hata tam da bu.

**Düzeltme taslağı:** `PRODUCT_COLUMNS` ile aynı deseni uygula.
```python
HISTORY_COLUMNS = frozenset({
    "carrier", "dest_plate", "zone", "risk_category", "is_rural",
    "declared_value_try", "promised_days", "delivery_days", "damaged",
})
```
- [ ] `HISTORY_COLUMNS` eklendi, `load()` içinde eksik sütun kontrolü yapıldı
- [ ] Enum değerleri de doğrulandı (`zone`, `risk_category`, `carrier` geçerli mi)
- [ ] Eksik sütunlu CSV ile hata mesajı testi yazıldı

### A6.3 · Maliyet parametrelerinin dosya yolu yok

`DamageCostParams`, `DelayCostParams`, `ObjectiveParams` yalnızca kod düzeyinde yaşıyor.
Diğer her şey (tarife, ürün, koli, il, geçmiş) veri dosyasında olduğu için bu bir
tutarsızlık: muhasebeden gelen bir rakamı güncellemek Python dosyasına dokunmayı
gerektiriyor. §6'daki 20 parametre bu yüzden versiyonlanamıyor ve kim ne zaman değiştirdi
izlenemiyor.

**Düzeltme taslağı:** `data/params/cost.yaml` + bir okuyucu; `EngineConfig` varsayılanı
oradan alsın, verilmezse koddaki değerler geçerli kalsın (geriye uyumlu).

- [ ] `data/params/cost.yaml` şeması tasarlandı (üç blok: damage / delay / objective)
- [ ] Okuyucu `adapters/files.py`'a eklendi
- [ ] Dosya yoksa koddaki varsayılanlara düşüyor (mevcut testler kırılmamalı)

---

## Kademeli geçiş sırası

```
1) Tarife  ──▶  2) Koli katalogu  ──▶  3) Ürün ölçü/ağırlık
                        │
                        ▼
        ┌───────────────────────────────────┐
        │  ARA KADEME: nakliye tarafı       │
        │  TAMAMEN GERÇEK                   │
        │  · desi tasarrufu gerçek rakam    │
        │  · fatura karşılaştırması gerçek  │
        │  · hasar + gecikme hâlâ sentetik  │
        └───────────────────────────────────┘
                        │
                        ▼
        4) Geçmiş sevkiyat  ──▶  5) Maliyet parametreleri
                        │
                        ▼
                 TAM GERÇEK MOTOR
```

İlk üç adım tamamlandığında **gösterilebilir bir ara kademe** oluşuyor: nakliye tarafı
gerçek rakam veriyor, gizli maliyet tarafı sentetik kalıyor. Bu, geçmiş veri toplanması
beklenirken sunulabilir bir durum.

---

## Doğrulama kriteri

Her veri kümesi yerine oturduğunda:

```bash
cd backend
$env:PYTHONUTF8=1
pytest -q                                  # 277 test yeşil kalmalı
python -m desi_engine.cli rate --cart examples/banyo_seti.json --city 34
python -m desi_engine.cli decide --cart examples/zeytinyagi_nevresim.json --city 65 --explain
```

- [ ] Tüm testler yeşil (gerçek veri şema doğrulamalarını geçiyor)
- [ ] Arayüzde ilgili firmadan **"ÖRNEK TARİFE"** rozeti kalktı
- [ ] `decide --explain` çıktısındaki kalemler elle kontrol edilebiliyor
- [ ] Duyarlılık taraması firma sıralamasının kararlı olduğunu gösteriyor

---

## Durum notları

**2026-08-13** — Envanter çıkarıldı (§1-6), kod değişikliği yok. Veri toplama henüz
başlamadı. Depo kökündeki `kargo.txt` bilinçli olarak kapsam dışı bırakıldı (firmadan
gelen ham dosya, biçimi mevcut `from_csv` şemasına uymuyor — ayrı bir iş, `graph.md` A1).

**2026-08-13** — §7 eklendi: altyapı denetlendi. Tarife/koli/ürün tarafı **eksiksiz**;
üç boşluk bulundu ve `graph.md` §11'e A6.1–A6.3 olarak işlendi. Üçü de küçük, mimariyi
değiştirmiyor, veri toplamayla paralel yürütülebilir. Kod değişikliği yok — yalnızca
düzeltme taslakları yazıldı.

### Nereden devam edilecek

İki iş kolu paralel yürüyebilir:

| Kol | İş | Bağımlılık |
|---|---|---|
| **Veri** | §1 tarife → §2 koli → §3 ürün ölçüleri | dış (satın alma, depo, ERP) — bekleme süresi var |
| **Kod** | A6.2 (en küçük, en yüksek fayda) → A6.1 → A6.3 | yok — hemen başlanabilir |

Kod kolu için önerilen sıra: **A6.2** geçmiş veri gelmeden önce bitmeli, çünkü ilk
gerçek `shipments.csv` denemesinde hatayı anlaşılır kılacak olan tam da o.
