# Veri sözleşmesi

Motorun okuduğu her dosyanın şeması, doğrulama kuralları ve gerçek veriye geçiş
notları.

---

## 1 · Kargo tarifesi — `data/carriers/*.yaml`

```yaml
carrier: ARAS                    # CarrierCode
display_name: Aras Kargo
source: synthetic                # synthetic | contract  ← arayüzdeki rozet bunu okur
note: "..."
valid_from: 2026-01-01
currency: TRY

rounding: ceil                   # ceil | half_up | none
desi_step: 1.0
min_charge: 79.90                # PARÇA BAŞINA uygulanır

desi_tiers:
  - up_to: 1
    zones: {sehir_ici: 68.00, bolge_ici: 76.00, bolgeler_arasi: 88.00, uzak: 99.00}
  - up_to: 2
    zones: {...}
  # ... 30 desiye kadar

over_30_per_desi:                # tablonun üstünde desi başı birim fiyat
  {sehir_ici: 6.50, bolge_ici: 7.50, bolgeler_arasi: 9.00, uzak: 10.50}

surcharges:
  fuel_pct: 0.085                # yakıt farkı — İNDİRİMDEN SONRA uygulanır
  cod_fee: 24.00                 # gönderi başına bir kez
  insurance: {free_limit: 500, pct_above: 0.004}
  vat_pct: 0.20

volume_discounts:                # artan eşiğe göre sıralı olmalı
  - {monthly_parcels_gte: 5000, pct: 0.06}
  - {monthly_parcels_gte: 10000, pct: 0.09}

service:
  sla_days: {sehir_ici: 1, bolge_ici: 2, bolgeler_arasi: 3, uzak: 4}
  rural_extra_days: 1
  cutoff: "17:00"

constraints:
  max_desi_per_parcel: 100
  cod_supported: true
  unserved_plates: []            # hizmet verilmeyen il plakaları
```

### Doğrulama kuralları

Yükleme sırasında zorlanır; ihlali `TariffLoadError` ile **yüklemeyi durdurur**.
Yarım yüklenmiş bir tarife seti, sessizce yanlış firma seçmekten iyidir.

| Kural | Neden |
|---|---|
| Desi kademeleri artan ve tekil | Sıralı arama doğru sonuç versin |
| Her kademede dört bölgenin hepsi | Eksik bölge = çalışma zamanı `KeyError` |
| **Fiyat desi arttıkça düşemez** | Elle düzenlenmiş matriste en sık ve en zor fark edilen hata |
| Hacim indirimleri artan eşiğe göre sıralı | `volume_discount_pct` en yüksek uygulanabiliri seçer |
| `over_30_per_desi` dört bölgeyi de içerir | Tablo üstü fiyatlama |
| Aynı firma için iki dosya olamaz | Belirsiz tarife |

### `source` alanı

`synthetic` | `contract`. Bu bayrak:

- `Tariff.is_synthetic` → `FreightQuote.is_synthetic_tariff`
- → API cevabında `synthetic_tariff_warning`
- → arayüzde **"ÖRNEK TARİFE"** rozeti
- → basılan ZPL etiketinde uyarı satırı

Uydurma fiyatların gerçek sözleşme fiyatı sanılması bu projedeki en ciddi yanlış
anlaşılma riski; bayrak zorunlu ve `test_adapters.py` ile korunuyor.

---

## 2 · İl kayıtları — `data/zones/tr_iller.csv`

```csv
plate,name,region,population,lat,lon,is_remote
34,İstanbul,marmara,15655924,41.01,28.98,0
65,Van,dogu_anadolu,1127612,38.49,43.38,1
```

| Sütun | Kullanım |
|---|---|
| `plate` | 1-81, birincil anahtar |
| `region` | `Region` enum'u — bölge içi/bölgeler arası ayrımı |
| `population` | Monte Carlo'da sipariş dağıtma ağırlığı (TÜİK 2023, yaklaşık) |
| `lat` / `lon` | Haversine mesafesi → uzak bölge eşiği (900 km) |
| `is_remote` | Mesafeye bakmadan `UZAK` sınıfı |

**Bölge sınıfı türetilir, tabloya yazılmaz:**

1. Aynı il → `SEHIR_ICI`
2. Varış ili `is_remote` → `UZAK`
3. Aynı coğrafi bölge → `BOLGE_ICI`
4. Mesafe > 900 km → `UZAK`
5. Diğer → `BOLGELER_ARASI`

Böylece çıkış deposu Bursa'dan İstanbul'a taşınsa bile sınıflandırma kendini
günceller.

---

## 3 · Koli katalogu — `data/boxes/catalog.yaml`

```yaml
boxes:
  - code: K05
    name: Büyük kutu
    inner: {length_cm: 40, width_cm: 30, height_cm: 20}
    wall_cm: 0.5              # oluklu mukavva et kalınlığı
    tare_kg: 0.47
    max_payload_kg: 20
    unit_cost_try: 11.80
    soft_only: false          # true = kargo poşeti
```

**İç ölçü ürünlerin sığdığı hacim, dış ölçü kargo firmasının ölçtüğü:**

```
dış_kenar = iç_kenar + 2 × wall_cm
```

`soft_only: true` (kargo poşetleri) kırılabilir veya sıvı ürün kabul etmez —
`packing/rules.py::box_accepts` zorlar.

---

## 4 · Ürün katalogu — `data/catalog/products.csv`

```csv
sku,name,category,length_cm,width_cm,height_cm,weight_kg,unit_price_try,
fragility,is_liquid,is_absorbent,stackable,max_stack_load_kg,compressibility
```

| Sütun | Anlam |
|---|---|
| `category` | `ProductCategory` (11 değer) — katalog kırılımı |
| `fragility` | `yok` / `dusuk` / `orta` / `yuksek` → dolgu payı |
| `is_liquid` | Sızıntı kaynağı olabilir |
| `is_absorbent` | Sızıntıdan zarar görür (yan hasarın kurbanı) |
| `stackable` | Üzerine ürün konabilir mi |
| `max_stack_load_kg` | Taşıyabileceği azami yük |
| `compressibility` | 0-0,35 — yumuşak tekstilin en küçük boyutunda ezilme oranı |

Bir ürün hem sıvı hem emici olamaz (`Product` doğrulaması).

`ProductCategory` → `RiskCategory` indirgemesi `CATEGORY_RISK_MAP` ile yapılır:
11 kategori yerine 4 risk sınıfı (tekstil / kırılabilir / sıvı / cihaz). Sebep:
`5 × 4 × 11 = 220` hücrenin çoğu boş kalırdı; 4 sınıfa indirgeyerek hücre başına
düşen veri ~3 katına çıkıyor.

---

## 5 · Geçmiş sevkiyat — `data/history/shipments.csv`

Motorun **tek bilgi kaynağı**. Hasar oranlarını ve teslimat süreleri dağılımını
buradan tahmin eder.

```csv
shipment_id,carrier,dest_plate,zone,risk_category,is_rural,
declared_value_try,promised_days,delivery_days,damaged
```

| Sütun | Kullanan model |
|---|---|
| `carrier`, `zone`, `risk_category`, `damaged` | `DamageRateEstimator` |
| `carrier`, `zone`, `is_rural`, `delivery_days`, `promised_days` | `DeliveryTimeEstimator` |

`delivery_days` **sürekli** transit süresidir; gönderi `⌈T⌉` gününde teslim
edilir. `T > promised_days` tam olarak "geç kaldı" demektir.

`promised_days` o gönderinin *o anki* SLA'sidir (kırsal ise +1). Teslimat modeli
`log(delivery_days / promised_days)` üzerinde çalıştığı için bu sütun zorunlu.

### Veri neden kasıtlı dengesiz

Sentetik üretim firma dağılımını çarpık (ARAS %45, PTT %5), bölge dağılımını
nüfusa ağırlıklı tutar. Sonuç: 80 hücrenin bazılarında 5 gönderi, bazılarında
9.000. Hiyerarşik shrinkage'ın varlık sebebi tam olarak bu — dengeli bir veri
setinde ham oranlar da iş görürdü ve model gereksiz görünürdü.

---

## 6 · Gerçek veri yuvası

`adapters/protocol.py` üç `typing.Protocol` tanımlar:

```python
class TariffSource(Protocol):
    def available_carriers(self) -> tuple[CarrierCode, ...]: ...
    def load(self, carrier: CarrierCode) -> Tariff: ...

class ProductCatalogSource(Protocol):
    def load(self) -> dict[str, Product]: ...

class ShipmentHistorySource(Protocol):
    def load(self) -> pd.DataFrame: ...
```

`Protocol` kullanıldı (soyut taban sınıf değil): uygulayıcıların bu modülden
türemesi gerekmiyor, yalnızca doğru imzayı taşıması yetiyor. Böylece harici bir
ERP istemcisi de — bu paketi hiç bilmeden — geçerli bir kaynak olur.

### Sözleşme tarifesi içe aktarımı

Kargo firmaları tarifeleri **matris** halinde gönderir:

```csv
up_to_desi,sehir_ici,bolge_ici,bolgeler_arasi,uzak
1,62.00,70.00,81.00,92.00
2,68.00,77.00,89.00,101.00
```

```python
from desi_engine.adapters import ContractMeta, from_csv, write_yaml

tarife = from_csv(Path("aras_2026.csv"), meta)   # veya from_excel(...)
write_yaml(tarife, Path("backend/data/carriers"))
```

`ContractMeta` matriste bulunmayan alanları taşır (asgari ücret, yakıt farkı, SLA,
kısıtlar). **Varsayılan verilmedi** — sessizce yanlış bir yakıt farkı varsaymaktansa
açıkça sorulması daha iyi.

İçe aktarılan tarife `source: contract` işaretlenir. Ayrı bir "gerçek veri modu"
kodu yok: içe aktarım bir kez yapılır, motor bundan sonra her zamanki gibi
`data/carriers/*.yaml` okur.
