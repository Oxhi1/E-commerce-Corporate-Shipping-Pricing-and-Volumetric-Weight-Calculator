# ADR-0001 · Desi tasarrufu hangi baz çizgiye kıyasla ölçülür

**Durum:** kabul edildi · **Tarih:** 2026-08-07

## Bağlam

Projenin ilk tasarımında desi tasarrufu, "sepetteki ürünlerin desilerinin
toplamı"na kıyasla ölçülüyordu. İlk gerçek koşuda şu çıktı:

```
Banyo seti (4 havlu + 1 bornoz)
  naif desi toplamı : 16,86
  motorun planı     : 21,94
  "tasarruf"        : -%30,1
```

Motor her sepette **negatif tasarruf** üretiyordu.

## Sorun

Ürün desilerinin toplamı **fiziksel olarak ulaşılamaz bir sayı**. Hiçbir gönderi
kolisiz gitmez ve her koli içindekinden büyüktür. Bu sayıya kıyasla ölçülen bir
tasarruf her zaman negatif çıkar ve hiçbir şey anlatmaz.

Aynı zamanda bu sayıyı büsbütün atmak da yanlış olurdu: şirketin bugün müşteriye ve
bütçeye söylediği rakam bu.

## Karar

Üç baz çizgi ayrı ayrı hesaplanır ve **farklı şeyler için** kullanılır:

| Baz çizgi | Ne için |
|---|---|
| `quoted_sum_desi` | Kotasyon açığını ölçmek. Bir tasarruf değil, **gizli zarar** olarak raporlanır. |
| `one_box_per_item_desi` | **Tasarruf iddiasının paydası.** Konsolidasyon mantığı olmayan bir deponun gerçekten yaptığı şey. |
| `volume_rule_desi` | "Hacimleri topla, sığan en küçük kutuyu seç" — Excel mantığıyla karşılaştırma. |

`PackingPlan.desi_savings_pct` ikinciyi kullanır; `quote_gap_pct` ayrı bir metrik
olarak ve açıkça "pozitif değer bir tasarruf değil, gizli bir zarardır" notuyla
sunulur.

## Sonuç

Aynı sepette:

```
kotasyon toplamı  : 16,86 desi   [ulaşılamaz]
her ürün ayrı koli: 25,96 desi   (5 koli)
motorun planı     : 18,30 desi   (3 koli)  →  %29,5 tasarruf
kotasyon açığı    : +%8,5        →  her siparişte cepten ödenen
```

İki bulgu birden ortaya çıktı: motor gerçekten kazandırıyor **ve** mevcut sistem
düşük fiyat veriyor. İkincisi ilk tasarımda tamamen görünmezdi.

## Alternatifler

**Sadece kotasyon toplamını kullanmak** — reddedildi, ölçülemez.

**Sadece "her ürün ayrı koli"yi kullanmak** — reddedildi, kotasyon açığı bulgusu
kaybolurdu.

**"Her ürün ayrı koli" yerine tek sabit kutu (örn. hep K07)** — reddedildi, hangi
kutunun seçileceği keyfi olurdu ve baz çizgi tartışmaya açık kalırdı.
