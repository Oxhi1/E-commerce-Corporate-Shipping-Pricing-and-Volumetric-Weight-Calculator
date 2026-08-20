# ADR-0002 · Planlayıcı tarifeyi bilmez, aday plan üretir

**Durum:** kabul edildi · **Tarih:** 2026-08-07

## Bağlam

Sanal kutulama "en az desi" hedefiyle yazıldı. İlk sürümde planlayıcı, sepetteki
tüm ürünleri alan ilk kutuyu bulunca duruyordu.

Gerçek bir sepette (6 havlu + 2 nevresim + 2 bornoz) bu, K10 kutusunu seçiyordu:
**86,5 desi**. Oysa K09 + K04 bölmesi **57,2 desi**.

"En az desi" hedefine geçildiğinde bu sefer başka bir şey oldu: planlayıcı 6 küçük
koliye bölüp 44,65 desiye indi. Ama asgari ücret **parça başına** uygulanıyor —
Aras'ta 79,90 TL × 6 koli = 479,40 TL taban, 2 koliyle 159,80 TL.

## Sorun

Doğru koli planı, tarifeye bağlı. Ama paketleme algoritmasını tarifeye bağımlı
kılmak iki sorun yaratır:

1. **Önbellek geçersizleşir.** Monte Carlo'da paketleme en pahalı parça; koli-doldurma
   önbelleği %49 isabet veriyor. Plan tarifeye bağlı olsaydı her firma için ayrı
   hesaplanır, isabet oranı düşerdi.
2. **Sorumluluk karışır.** Paketleyicinin yakıt farkını veya hacim indirimini
   bilmesi gerekirdi.

Üstelik aynı problem sıvı ayrımında da var: zeytinyağını nevresimden ayırmak bir
koli daha demek. Buna paketleyici karar veremez; hasar maliyetini bilmiyor.

## Karar

Planlayıcı **tek bir plan değil, birkaç iyi aday plan** üretir. Hangisinin ucuz
olduğunu, tarifeyi ve hasar modelini bilen karar motoru söyler.

Adaylar `(toplam desi, parça sayısı)` düzleminde **Pareto cephesi** olarak üretilir:
açgözlü algoritma, kutu boyutu tavanı değiştirilerek defalarca koşturulur. Tavan
küçükse çok parçalı/düşük desili, büyükse az parçalı/yüksek desili planlar çıkar.

Kontaminasyon riski olan sepetlerde ikinci bir strateji ("sıvılar ayrı") eklenir.

Aynı sepette üretilen cephe:

```
7 koli  56,77 desi    P02+P02+P03+K04+K04+K04+K06
6 koli  61,39 desi    K04+K04+K04+K06+K07+P02
2 koli  72,58 desi    K09+K07
1 koli  86,46 desi    K10
```

`CarrierSelector` her (firma × plan) çiftini fiyatlar ve firma başına en iyi planı
seçer. Bu, PTT'nin 50 desilik parça sınırı gibi kısıtları da doğru ele alır: tek
koliye sıkıştıran plan PTT için uygunsuz, iki koliye bölen plan uygun.

## Sonuç

- Paketleme önbelleği siparişler arası paylaşılabiliyor (%49 isabet).
- Sıvı ayrımı bir kural değil, ölçülen bir maliyet karşılaştırması oldu.
- Parça sayısı ile desi arasındaki takas tarifeye göre otomatik çözülüyor.

Maliyet: firma başına 1 yerine ~4 değerlendirme. Kabul edilebilir — değerlendirme
paketlemeden çok daha ucuz.

## Alternatifler

**Planlayıcıya tarifeyi vermek** — reddedildi, önbellek ve sorumluluk sorunları.

**Tüm plan kombinasyonlarını denemek** — reddedildi, kombinatorik olarak patlıyor
ve Pareto cephesi dışındaki planlar tanım gereği kaybediyor.

**Sabit bir "en fazla 2 koli" kuralı** — reddedildi, keyfi ve sepete göre yanlış.
