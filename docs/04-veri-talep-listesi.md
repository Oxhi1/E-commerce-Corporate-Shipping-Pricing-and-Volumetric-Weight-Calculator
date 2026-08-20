# Veri Talep Listesi — Kargo Karar Motoru

**Tarih:** 2026-08-13 · **Proje:** Çok firmalı kargo fiyatlama ve desi motoru

Sistem şu an **sentetik (örnek) veriyle** çalışıyor ve teknik olarak tamamlanmış
durumda. Gerçek Özdilek verisine geçmek için yazılım tarafında değişiklik gerekmiyor;
ihtiyaç yalnızca **veri**. Aşağıda hangi verinin hangi birimden isteneceği listelenmiştir.

---

## Özet

| # | Veri | Kimden | Zorluk | Öncelik |
|---|---|---|---|---|
| 1 | Kargo sözleşme tarifeleri | Satın Alma / Sözleşme | Düşük | **1** |
| 2 | Koli ve ambalaj ölçüleri | Depo / Lojistik | Çok düşük | **2** |
| 3 | Ürün ölçü ve ağırlıkları | ERP / IT | Orta | **3** |
| 4 | Geçmiş sevkiyat kayıtları | ERP / IT + Müşteri Hizmetleri | Yüksek | **4** |
| 5 | Hasar tanımı ve kurtarma oranları | Kalite / Müşteri Hizmetleri | Orta | 5 |
| 6 | Birim operasyon maliyetleri | Muhasebe / Finans | Düşük | 6 |
| 7 | Müşteri değeri ve kayıp oranları | CRM / Pazarlama | Orta | 7 |

**İlk üç kalem tamamlandığında** sistem nakliye tarafında tamamen gerçek rakam üretmeye
başlar: koli optimizasyonuyla elde edilen desi tasarrufu ve firmalar arası fatura
karşılaştırması gerçek olur. Hasar ve gecikme tarafı 4-7. kalemler gelene kadar örnek
veriyle çalışmaya devam eder. Yani **ara bir kademede de sunulabilir sonuç** çıkar.

---

## 1 · Kargo sözleşme tarifeleri

**Kimden:** Satın Alma / Sözleşme Yönetimi
**Kapsam:** Çalışılan her kargo firması için ayrı ayrı

### İstenen

**a) Fiyat matrisi** — desi kademeleri × bölge fiyatları

| Desi | Şehir içi | Bölge içi | Bölgeler arası | Uzak |
|---|---|---|---|---|
| 1 | … | … | … | … |
| 2 | … | … | … | … |

> Sözleşmede bölge ayrımı yoksa (tüm bölgeler tek fiyat) sorun değil, belirtilmesi yeterli.

**b) Fiyat matrisinde yer almayan sözleşme maddeleri**

| Madde | Not |
|---|---|
| Asgari ücret | **Gönderi başına mı, parça başına mı** — bu ayrım hesabı doğrudan değiştirir |
| Desi yuvarlama kuralı | Yukarı yuvarlama / en yakına / yuvarlama yok |
| Tablonun bittiği desinin üstü | Desi başına birim fiyat, bölge bazında |
| Yakıt farkı oranı | İndirimden önce mi sonra mı uygulandığı |
| Kapıda ödeme hizmet bedeli | |
| Sigorta | Muafiyet limiti + limit üstü oran |
| KDV oranı | |
| Hacim indirim kademeleri | Aylık gönderi adedi eşiği → indirim oranı |
| Taahhüt edilen teslimat süresi | Bölge bazında gün; kırsal ek gün |
| Son çıkış saati (cut-off) | Aynı gün sevkiyat için |
| Parça başına azami desi | Firma kısıtı |
| Hizmet verilmeyen iller | Varsa plaka listesi |

**c) Ayrıca:** Özdilek'in **gerçek aylık gönderi adedi** — hacim indirim kademesini
belirlediği için doğrudan fiyata etki ediyor.

**Format:** Excel veya CSV. Sözleşme metninin kendisi de yeterli, biz çıkarırız.

---

## 2 · Koli ve ambalaj ölçüleri

**Kimden:** Depo / Lojistik
**Zorluk:** Bir öğleden sonrada tamamlanabilir. Etkisi en yüksek kalemlerden biri.

Depoda fiilen kullanılan her koli ve kargo poşeti tipi için:

| Bilgi | Not |
|---|---|
| Kod / ad | K01, K02 … |
| **İç ölçü** (en × boy × yükseklik) | Ürünlerin sığdığı hacim |
| **Karton et kalınlığı** | ⚠ Kritik — aşağıya bakınız |
| Boş ağırlık (dara) | |
| Azami taşıma yükü | |
| Birim maliyeti | |
| Kargo poşeti mi? | Poşete cam/sıvı konulamıyor |

> ⚠ **İç ölçü ile dış ölçü ayrımı kritik.** Kargo firması **dış** ölçüyü ölçüp faturayı
> ona göre kesiyor. Bu ayrım atlanırsa sistem her koli için sistematik olarak düşük desi
> hesaplar; büyük kolilerde fark bir tarife kademesine denk gelebiliyor.

**Ayrıca:** Sevkiyatın çıktığı deponun ili doğrulanmalı (şu an Bursa varsayılıyor).

---

## 3 · Ürün ölçü ve ağırlıkları

**Kimden:** ERP / IT (temel bilgiler) + ürün ekibi (fiziksel nitelikler)

**a) ERP'den çekilebilecekler** — her SKU için:
SKU, ürün adı, kategori, **ambalajlı** en/boy/yükseklik, ağırlık, birim satış fiyatı

> ⚠ Ölçüler ürünün **satış ambalajıyla birlikte** hâli olmalı; çıplak ürün ölçüsü değil.

**b) ERP'de büyük ihtimalle bulunmayanlar** — kırılganlık derecesi, sıvı mı, sıvıyı emer
mi, üstüne ürün konabilir mi, taşıyabileceği azami yük, sıkışabilirlik oranı.

> Bunlar için binlerce ürünü tek tek işaretlemeye gerek yok: **kategori bazında öntanım
> tablosu** kurup istisnaları (cam, sıvı, elektrikli cihaz) elle işaretlemek yeterli.
> Bu tabloyu biz hazırlayıp onaya sunabiliriz.

---

## 4 · Geçmiş sevkiyat kayıtları — en kritik kalem

**Kimden:** ERP / IT + Müşteri Hizmetleri (hasar kayıtları)

Sistemin hasar riski ve teslimat süresi hakkındaki **tek bilgi kaynağı**. Bu veri
olmadan projenin ana iddiası — gizli maliyetlerin ölçülmesi — sayısal olarak
gösterilemez.

Her sevkiyat satırı için:

| Alan | Kaynak |
|---|---|
| Kargo firması | ERP |
| Varış ili | ERP |
| Kırsal adres mi | ERP |
| Sipariş tutarı | ERP |
| Sipariş içeriği (ürün kategorisi) | ERP |
| Çıkış tarihi | ERP / kargo takip |
| Teslim tarihi | Kargo takip |
| **Hasar / iade bayrağı** | Müşteri Hizmetleri, iade kayıtları |

**Dönem ve hacim:**
- En az **12 ay**, tercihen 24 ay
- Alt sınır ~10-15 bin sevkiyat, ideal 50-60 bin
- Veri dağılımının dengesiz olması **sorun değil** — model bunun için tasarlandı; bazı
  firma/bölge kırılımlarında az kayıt olması beklenen durum

**Not:** Teslim süresi yalnızca gün olarak varsa da çalışır, saat bazında olması daha
iyi sonuç verir.

---

## 5 · Hasar tanımı ve kurtarma oranları

**Kimden:** Kalite / Müşteri Hizmetleri

**a) "Hasarlı" tanımının sabitlenmesi — en önemli tek karar.**
Müşteri beyanı mı, depo iade kabulünde tespit mi, sigorta dosyası açılması mı?
Üçü farklı oranlar üretir. Tek bir tanım seçilip **tüm dönem için tutarlı** uygulanmalı;
tanım veri içinde kayarsa sonuçlar anlamsızlaşır ve bu fark edilmez.

**b) Hasar gerçekleştiğinde ürün değerinin ne kadarı kurtarılıyor?** Ürün tipine göre:
tekstil (outlet'te satılabilir), cam/porselen, sıvı, küçük ev aleti.
Kaba yüzde tahmini yeterli.

**c) Kolideki sıvı sızdığında** yanındaki ürünlerin de zarar görme oranı — geçmiş
vakalardan yaklaşık bir oran.

---

## 6 · Birim operasyon maliyetleri

**Kimden:** Muhasebe / Finans

| Kalem | Not |
|---|---|
| Şikâyet çağrısı başına maliyet | Çağrı merkezi |
| Depo elleçleme + yeniden paketleme maliyeti | Hasarlı gönderi başına |
| İade maliyeti | İade nakliyesi + depo kabulü + stok düzeltme |
| Yerine yenisini gönderme maliyeti | |
| Gecikme telafisi | Kupon / indirim, gün başına ortalama |

Kaba ortalamalar yeterli; kuruş hassasiyeti gerekmiyor.

---

## 7 · Müşteri değeri ve kayıp oranları

**Kimden:** CRM / Pazarlama

| Bilgi | Not |
|---|---|
| Müşteri yaşam boyu değeri (CLV) | Ortalama veya segment bazında |
| Hasarlı teslimat sonrası müşteri kaybı oranı | Kohort analizi |
| Geç teslimat sonrası müşteri kaybı oranı | |
| Geç teslimatta sipariş reddi / iade oranı | |

Bu kalemler mutlak TL rakamını etkiler, ancak **firma sıralamasını genellikle
değiştirmez.** Sistemde bunu test eden bir duyarlılık analizi modülü mevcut; gerçek
değerler geldiğinde önce o çalıştırılacak.

---

## Minimum başlangıç paketi

Tümü aynı anda gelmek zorunda değil. Şu üçü ile somut çıktı üretilebilir:

1. **Bir firmanın** sözleşme tarifesi (madde 1)
2. Koli ölçüleri (madde 2)
3. Bir ürün grubunun ölçü ve ağırlıkları (madde 3-a)

Bu paketle koli optimizasyonunun gerçek desi tasarrufu ve gerçek fatura tutarları
gösterilebilir. Kalan kalemler geldikçe sistem kademeli olarak tamamlanır.

---

## Veri gelene kadar ne yapılıyor

Sistem sentetik veriyle çalışmaya devam ediyor ve **tam işlevsel**. Örnek fiyatların
gerçek sözleşme fiyatı sanılmaması için, sentetik veriyle çalışan her firma arayüzde
**"ÖRNEK TARİFE"** rozetiyle işaretleniyor; bu rozet basılan kargo etiketine kadar
taşınıyor. Gerçek tarife yüklendiğinde ilgili firmadan otomatik olarak kalkıyor.

Teknik ayrıntı ve şemalar: [`docs/02-veri-sozlesmesi.md`](02-veri-sozlesmesi.md) ·
[`plans/AKTIF-gercek-veri-gecisi.md`](../plans/AKTIF-gercek-veri-gecisi.md)
