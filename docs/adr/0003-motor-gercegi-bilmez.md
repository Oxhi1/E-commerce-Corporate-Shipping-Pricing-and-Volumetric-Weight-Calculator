# ADR-0003 · Simülasyonda motor gerçek parametreleri göremez

**Durum:** kabul edildi · **Tarih:** 2026-08-07

## Bağlam

Monte Carlo simülasyonu iki şeye ihtiyaç duyar: gerçek hasar olasılıkları (sonucu
üretmek için) ve motorun kullanacağı tahminler (kararı vermek için).

En kolay uygulama ikisini aynı yerden okumaktır.

## Sorun

Motor gerçek hasar oranını bilseydi her zaman doğru firmayı seçerdi. "%17 tasarruf"
sonucu modelin değil **kurgunun** eseri olurdu; gerçek hayatta motor bu bilgiye
sahip olmayacak.

Aynı şey teslimat süreleri için de geçerli.

## Karar

İki ayrı dünya:

```
TrueWorld  (simulation/world.py)
  ├─ gerçek hasar olasılıkları      p(firma, bölge, kategori)
  └─ gerçek teslimat dağılımları    lognormal(μ, σ)
        │
        │  örnekleme  →  data/history/shipments.csv
        ▼
DamageRateEstimator + DeliveryTimeEstimator
  └─ yalnızca gözlenmiş geçmiş veriyi görür
        │
        ▼
   CarrierSelector  ──▶ karar
        │
        ▼
   SimulationRunner ──▶ sonucu TrueWorld ile gerçekleştirir
```

`CarrierSelector` `TrueWorld`'e **hiçbir referans tutmaz**. Erişimi kod düzeyinde
imkânsız.

Geçmiş veri kasıtlı olarak dengesiz üretilir (firma dağılımı çarpık, bölge dağılımı
nüfusa ağırlıklı) — böylece motor gerçek hayattaki gibi bazı hücrelerde neredeyse
kör kalır ve hiyerarşik shrinkage'ın değeri ölçülebilir hale gelir.

## Sonuç

Motorun tahminleri gerçekten yanılıyor ve bu ölçülebiliyor:

| | Ham oran | Shrinkage'lı |
|---|---:|---:|
| 80 hücrede ortalama mutlak hata | %0,714 | %0,484 |

Kalibrasyon eğrisi de bu ayrım sayesinde anlamlı: motorun "%2" dediği gönderilerin
gerçekten ~%2'si hasar görüyor mu? (ECE = 0,0046)

Gerçek dünya parametrelerine yalnızca **testler** erişir — modelin gerçeğe ne kadar
yaklaştığını ölçmek için (`test_shrinkage_beats_raw_rates_against_truth`).

## Ek karar: ortak rastgele sayılar

Aynı gerekçenin devamı. Her sipariş için şans çekilişleri bir kez yapılır ve tüm
politikalar aynı çekilişleri kullanır:

- koli başına tekdüze `u` → hasar: `u < gerçek_olasılık`
- standart normal `z` → teslimat: `T = exp(μ + σ·z)`

Böylece "MNG'yi seçseydim bu koli hasar görür müydü" sorusu aynı şansla cevaplanır.
Bu olmadan politikalar arasındaki fark, siparişlerin ve şansın gürültüsünde
kaybolurdu — eşleştirilmiş bootstrap'ın güven aralığı belirgin şekilde genişliyor
(`test_pairing_tightens_the_interval`).

Ayrıca fiyatlama, paketleme ve risk hesabı sipariş başına **bir kez** yapılır;
politikalar yalnızca seçim kuralında ayrışır. Aksi halde "P3 daha iyi" sonucu, karar
kuralından mı yoksa farklı bir hesaplamadan mı geldiği anlaşılamazdı.

## Alternatifler

**Motorun gerçek parametreleri okuması** — reddedildi, simülasyon kendi cevabını
kopyalar.

**Geçmiş veriyi dengeli üretmek** — reddedildi, ham oranlar da iş görürdü ve Bayesçi
model gereksiz görünürdü. Gerçek hayattaki veri de dengeli değil.

**Her politikayı bağımsız rastgelelikle koşturmak** — reddedildi, karşılaştırma
gürültüde kaybolur.
