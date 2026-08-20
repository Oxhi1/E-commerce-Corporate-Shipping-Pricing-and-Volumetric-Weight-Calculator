# Matematiksel model

Bu belge motorun karar fonksiyonunu, her teriminin nereden geldiğini ve hangi
varsayımlara dayandığını açıklar. Amaç, sayıların savunulabilir olması: bir
yöneticinin "bu 80 TL nereden çıktı" sorusuna kalem kalem cevap verebilmek.

---

## 1 · Amaç fonksiyonu

### 1.1 Çıkış noktası

```
Seçilen = argmin_k [ F_k(D) + R_k·S + Z_k(L) ]
```

- `k` — çalışılan kargo firmaları
- `F_k(D)` — `k` firmasının `D` desi için sözleşme fiyatı
- `R_k` — hasar/kayıp risk oranı
- `S` — sepetteki ürünlerin toplam değeri
- `Z_k(L)` — `L` lokasyonu için gecikme maliyeti

İskelet doğru: nakliye + risk + gecikme. Uygulanan hâli aynı fikrin ölçülebilir
bir genişletmesi.

### 1.2 Uygulanan hâl

```
TELC_k = F_k(D, z, σ)                    nakliye
       + Σ_b p̂_{k,z,c(b)} · Zarar(b)     beklenen hasar maliyeti
       + Z_k(L)                          beklenen gecikme maliyeti
       + O_k                             ambalaj + operasyonel sürtünme
       − V_k                             hacim taahhüdü gölge fiyatı  [uygulanmadı]

Skor_k = E[TELC_k] + λ · (CVaR₉₅(hasar) − E[hasar])

Seçilen = argmin_{k ∈ K_uygun} Skor_k
```

`K_uygun`: hizmet bölgesi, kapıda ödeme desteği, azami parça desisi, günlük
kapasite ve çıkış saati kısıtlarını geçen firmalar.

**Önemli:** plan seçimi firma seçimiyle *birlikte* yapılır. Önce "en iyi plan"ı
seçip sonra firma aramak yanlış olurdu — PTT'nin 50 desilik parça sınırı, tek
koliye sıkıştıran planı onun için uygunsuz kılarken iki koliye bölen planı uygun
kılar. Doğru çift ancak ikisi birlikte arandığında bulunur.

---

## 2 · Desi ve nakliye ücreti

### 2.1 Desi

```
hacimsel_desi = (en × boy × yükseklik) / 3000        [cm]
ücretli_desi  = yuvarla_k( max(hacimsel_desi, ağırlık_kg) )
```

Yuvarlama kuralı (`ceil` / `half_up` / adım) firma sözleşmesinde yazar ve tarife
dosyasında konfigüre edilir. Kademe sınırında bu kural tek başına fiyatı değiştirir.

**Kayan nokta inceliği.** `33×22×11/3000` gibi bir hesap ikilik tabanda tam ifade
edilemez; `2.0` olması gereken bir değer `2.0000000004` çıkıp yukarı yuvarlanırsa
müşteri bir üst tarife kademesinden fatura alır. Tüm yuvarlamalar `EPS = 1e-9`
toleransıyla yapılır.

**İç ölçü vs dış ölçü.** Kargo firması kolinin **dışını** ölçer:

```
dış_kenar = iç_kenar + 2 × oluklu_mukavva_kalınlığı
```

K10 kutusunda: iç 80×60×50 → 80,0 desi, dış 81,6×61,6×51,6 → 86,5 desi (%8 fark).
Sadece iç ölçüyle hesap yapan bir motor her koliyi sistematik olarak ucuz tahmin
eder.

### 2.2 Ek ücret sırası

Sıra fiyatı değiştirir. Uygulanan sıra (`tariff/surcharges.py::SURCHARGE_ORDER`):

1. taban tarife — desi kademesi × bölge
2. asgari ücret tabanı — `max(taban, min_charge)`, **parça başına**
3. hacim indirimi
4. yakıt farkı — **indirimli** taban üzerinden
5. kapıda ödeme — sabit, gönderi başına bir kez
6. sigorta — beyan değeri üzerinden, gönderi başına bir kez
7. KDV — hepsinin toplamı üzerinden

3. ve 4. adımın sırası kritik. Yakıt farkı indirimli tutar üzerinden hesaplanır;
ters sıra firmanın lehinedir ve sözleşmede açıkça belirtilmediyse lehte yorum
yapılmıyor. 1.000 TL'lik bir faturada ~8 TL fark; yılda 200 bin gönderide 1,6
milyon TL.

Asgari ücretin **parça başına** uygulanması, koli bölme kararının neden desiden
ibaret olmadığını açıklar: 5 koliye bölerek 56 desiye inmek, 2 koliyle 57 desiden
pahalıya gelebilir.

---

## 3 · Sanal kutulama

### 3.1 Amaç fonksiyonu

Klasik bin-packing "en az kutu" arar. Fatura desi üzerinden kesildiği için bizim
amacımız farklı: **toplam ücretli desi**. Ama parça başına asgari ücret yüzünden
bu da tek başına yetmez.

Çözüm: planlayıcı `(toplam desi, parça sayısı)` düzleminde **Pareto-optimal**
birkaç aday üretir; hangisinin ucuz olduğunu tarifeyi bilen karar motoru söyler.

Adaylar, açgözlü algoritma **kutu boyutu tavanı** değiştirilerek defalarca
koşturularak üretilir. Tavan küçükse çok parçalı/düşük desili, büyükse az
parçalı/yüksek desili planlar çıkar; arada tüm ara çözümler.

### 3.2 Yerleştirme

Köşe noktaları + yerçekimi oturtması (Crainic vd. 2008 "Extreme Point" ailesinin
pratik bir varyantı):

1. Her yerleştirilen ürün üç yeni aday nokta üretir: `(x+dx, y, z)`, `(x, y+dy, z)`,
   `(x, y, z+dz)`.
2. Her aday seçilmeden önce **oturtulur**: önce z (yerçekimi), sonra y ve x
   ekseninde çarpana kadar kaydırılır. İki tur — y/x kayması ürünü yeni bir yüzeyin
   üstüne getirebilir ve z yeniden düşebilir.
3. Uygun yerleşimler arasından "en alt, en arka, en sol" seçilir.

Oturtma adımı olmadan tipik dolgu oranı ~%45'te kalıyor; oturtmayla ~%65-75.

**Fiziksel kurallar** (her biri bir hasar modunu karşılar):

| Kural | Karşıladığı hasar |
|---|---|
| Sıvı, emici ürünün üzerine konmaz | sızıntı aşağı akar, tekstili götürür |
| Kırılabilir ürün kenar dolgu payı ister | darbe |
| Ürünün tabanının ≥%70'i desteklenmeli | havada asılı ürün, çökme |
| İstif yükü yığın boyunca aşağı yayılır | ezilme |
| Kargo poşetine cam/sıvı girmez | delinme |

İstif yükü propagasyonu: A, B'nin üzerinde ve B de C'nin üzerindeyse C hem A'yı hem
B'yi taşır. Birden fazla destekleyici varsa yük temas alanıyla orantılı
paylaştırılır. Bu, gerçek yük dağılımının (rijitlik, ağırlık merkezi) belgelenmiş
bir yaklaşımıdır.

### 3.3 Baz çizgiler

Tasarruf ancak **ulaşılabilir** bir alternatife kıyasla anlamlıdır.

| Baz çizgi | Ne anlatır |
|---|---|
| `quoted_sum_desi` | Ürün desilerinin toplamı. **Fiziksel olarak ulaşılamaz** — hiçbir gönderi kolisiz gitmez. Şirketin bugün müşteriye söylediği sayı bu. |
| `one_box_per_item_desi` | Her ürün kendi en küçük kolisinde. Konsolidasyon mantığı olmayan bir deponun yaptığı. **Tasarruf iddiasının paydası bu.** |
| `volume_rule_desi` | "Hacimleri topla, o hacme sığan en küçük kutuyu seç" — geometriyi yok sayan Excel mantığı. Seçtiği kutu çoğu zaman yetmez; o durumda bir üst kutuya geçilir. |

`quoted_sum_desi` ile gerçek desi arasındaki fark **kotasyon açığı** olarak ayrıca
raporlanır. Bu bir tasarruf değil, mevcut sistemin düşük fiyat verdiğini gösteren
bir bulgudur — fark her siparişte sessizce cepten ödenmektedir.

---

## 4 · Bayesçi hasar modeli

### 4.1 Problem

`(firma × bölge × ürün tipi)` = 5 × 4 × 4 = 80 hücre. Geçmiş veri çarpık:

| | Gönderi | Hasar | Ham oran | Gerçek |
|---|---:|---:|---:|---:|
| PTT / şehir içi / cihaz | 5 | 0 | %0,00 | %0,78 |
| Sürat / şehir içi / sıvı | 33 | 1 | %3,03 | %1,24 |
| Aras / bölgeler arası / tekstil | 9.118 | 32 | %0,35 | %0,30 |

Ham oranlar iki yönde de tehlikeli: sıfır bir tahmin karar motorunda o firmayı
sonsuz cazip yapar; 33 gönderiden çıkan %3 ise gerçeğin altı katıdır.

### 4.2 Beta-Binom

Hasar bir Bernoulli olayı. Hücredeki gerçek oran `p` bilinmiyor; onu bir Beta
dağılımıyla temsil ediyoruz. Beta, Binom'un eşlenik önselidir → posterior yine Beta,
kapalı formda. 50 bin siparişlik bir Monte Carlo'da bu, saniyelerle saatler
arasındaki farktır.

`α = κ·p_önsel`, `β = κ·(1−p_önsel)` yazıldığında posterior ortalama tam olarak:

```
p_posterior = (κ·p_önsel + gözlenen_hasar) / (κ + gönderi_sayısı)
```

Yani `κ`, önselin **kaç gönderilik veriye denk** sayıldığıdır.

### 4.3 Hiyerarşi

```
p₀    = genel ortalama
p_k   = (κ₀·p₀   + d_k)   / (κ₀ + n_k)        firma
p_kz  = (κ₁·p_k  + d_kz)  / (κ₁ + n_kz)       firma × bölge
p_kzc = (κ₂·p_kz + d_kzc) / (κ₂ + n_kzc)      firma × bölge × kategori
```

Her katmanın tahmini bir alt katmanın önseli olur. Geçiş kesintisiz ve otomatik —
"n < 30 ise üst katmanı kullan" gibi keyfi bir eşik yok.

### 4.4 κ nasıl kestiriliyor

Elle seçilmiyor. Her katmanda Beta-Binom marjinal log-olabilirliği maksimize edilir:

```
log L(n, d | α, β) = ln B(d+α, n−d+β) − ln B(α, β)     + sabit
```

`κ` üzerinde 90 noktalı logaritmik ızgara araması. Deterministik, türev
gerektirmez, yerel maksimuma takılmaz. `fit` yalnızca bir kez çalıştığı için
optimizasyon süresi önemsiz.

Hücreler arası gerçek farklılık büyükse küçük bir `κ` çıkar (veriye güven),
farklılık gürültüden ibaretse büyük bir `κ` (önsele güven).

Izgara üst sınırı sonlu (10⁴): sonsuz `κ`, 9.000 gönderilik bir hücreyi bile
önsele ezdirirdi.

### 4.5 Ölçülen sonuç

80 hücrede gerçek oranlara kıyasla (gerçek oranlara yalnızca test erişebilir):

| | Ham oran | Shrinkage'lı | İyileşme |
|---|---:|---:|---:|
| Ortalama mutlak hata | %0,714 | %0,484 | %32 |
| RMSE | %1,051 | %0,830 | %21 |

### 4.6 Riskten kaçınma

`risk_aversion_level` verildiğinde nokta tahmin yerine posterior üst güven sınırı
kullanılır. Bunun etkisi: "bu firma hakkında az şey biliyoruz" durumu otomatik
olarak daha yüksek bir risk varsayımına dönüşür.

5 gönderide 0 hasar ile 5.000 gönderide 0 hasar — ikisinin de ham oranı %0, ama üst
güven sınırları çok farklı. **"Bilmiyoruz", "iyi" demek değildir.**

---

## 5 · Zarar fonksiyonu

```
Zarar(b) = Σᵢ değerᵢ · şiddetᵢ                       doğrudan
         + kontaminasyon · Σⱼ emici_değerⱼ·(1−şiddetⱼ) yan hasar
         + yeniden_gönderim + elleçleme + çağrı        lojistik
         + churn_olasılığı · CLV                       müşteri kaybı
```

**Şiddet** = hasar olayı gerçekleştiğinde ürünün değerinin ne kadarının kaybedildiği:

| Risk sınıfı | Şiddet | Gerekçe |
|---|---:|---|
| Tekstil | 0,35 | outlet'te satılabilir, temizlenebilir |
| Cihaz | 0,80 | darbe genellikle onarılamaz |
| Sıvı | 0,85 | ambalaj bütünlüğü bozulunca satılamaz |
| Kırılabilir | 0,95 | kurtarılamaz |

**Yan hasar** yalnızca kolide hem sıvı hem emici ürün varsa devreye girer. Emici
ürünün `doğrudan` içinde zaten sayılan kısmı çıkarılır — aynı zararı iki kez
yazmamak için.

**Kolinin risk sınıfı = içindeki en kırılgan ürünün sınıfı.** İçinde cam olan bir
koli, yanında havlu olsa bile cam kolisi gibi taşınır ve öyle hasar görür. Ortalama
almak bu gerçeği gizlerdi.

**Müşteri kaybı gönderi başına bir kez sayılır.** Müşteri, iki kolisi birden hasar
görse de bir kez kaybedilir; koli başına churn eklemek çok parçalı gönderileri
haksız cezalandırırdı.

---

## 6 · Gecikme maliyeti

### 6.1 Neden log-normal

Teslimat süresi pozitif, sağa çarpık ve çarpımsal gecikmelerden oluşur (aktarma
bekleme × hat yoğunluğu × şube kapasitesi). Normal dağılım negatif gün üretir;
üstel dağılım kuyruğu fazla kalın modeller.

`T` **sürekli** transit süresidir; gönderi `⌈T⌉` gününde teslim edilir. `T = 0,7`
"vaat edilen ilk gün içinde teslim" demektir ve `T > vaat` tam olarak "geç kaldı"
anlamına gelir. Bu tanım sayesinde kırpmaya gerek kalmıyor.

### 6.2 Ölçekten bağımsız kestirim

Kestirim doğrudan gün sayısı üzerinde değil, `log(gerçekleşen / vaat)` üzerinde
yapılır.

Sebep: seyrek hücreler firma ortalamasına çekilirken 1 günlük bir şehir içi hücresi,
aynı firmanın 4 günlük uzak bölge hücreleriyle aynı havuza girip yukarı çekiliyordu.
Yurtiçi şehir içinde gerçek %5 gecikmeye karşı %13 tahmin üretiliyordu.

`log(gerçekleşen/vaat)` ölçekten bağımsızdır ("firma vaadini yüzde kaç aşıyor") ve
bölgeler arası havuzlama artık anlamlı. Mutlak dağılıma dönüş, sorulan hücrenin
kendi SLA'siyle: `μ_mutlak = μ_aşım + ln(SLA)`.

### 6.3 Maliyet

```
Z_k = P(T > vaat) · (çağrı_merkezi + p_iade·iade_maliyeti + p_churn·CLV)
    + min(E[(T − vaat)⁺], tavan) · gün_başı_telafi
```

İlk terim gecikmenin **olup olmamasına** bağlı sabit maliyetler, ikincisi
**süresine** bağlı maliyet. Bir gün geciken siparişle beş gün geciken sipariş aynı
şey değildir.

`E[(T−d)⁺]` log-normal için kapalı formda:

```
E[(T−d)⁺] = E[T]·Φ((μ + σ² − ln d)/σ) − d·Φ((μ − ln d)/σ)
```

Kapalı form önemli: Monte Carlo'da milyonlarca kez çağrılıyor.

Gün başı telafiye **tavan** konur; sınırsız bırakılırsa log-normal kuyruğu tek bir
uç örnekle bütün kararı belirleyebilir.

---

## 7 · Kuyruk riski (CVaR)

Beklenen değer, "nadiren çok kötü" ile "sık sık biraz kötü"yü aynı sayıya indirger.
3.870 TL'lik bir sepette %5 hasar olasılığı ile %0,5 olasılıkta on kat zarar aynı
beklenen maliyeti verir — ama işletme için aynı şey değildir.

Hasar maliyeti iki noktalı bir dağılım olduğu için CVaR kapalı formda:

```
CVaR_α = min(1, p/α) · Zarar
```

Türetim: gönderi `p` olasılıkla `Zarar` kadar, `1−p` olasılıkla 0 maliyet üretir.
En kötü `α` dilimin beklenen değeri:

- `p ≥ α` → dilim tamamen hasar olaylarından oluşur → `Zarar`
- `p < α` → `[p·Zarar + (α−p)·0] / α` → `(p/α)·Zarar`

Skora eklenen **prim**, beklenen değerin *üzerindeki* fazladır:

```
prim = λ · max(0, CVaR_α − p·Zarar)
```

`λ = 0` iken sıfır — risk-nötr mod özel bir kod yolu gerektirmez.

**Önemli ayrım:** kuyruk primi bir *skor düzeltmesi*dir, para beklentisi değil.
İkisi karışırsa "ne kadar tasarruf ettik" raporu, gerçekleşmeyecek bir primi
tasarruf gibi gösterirdi. `expected_total_try` ile `score_try` bu yüzden ayrı.

---

## 8 · Simülasyon metodolojisi

### 8.1 Motor gerçeği bilmez

`TrueWorld` gerçek hasar olasılıklarını ve teslimat dağılımlarını tutar. Karar
motoru bu nesneye asla erişemez; yalnızca ondan üretilmiş **gözlenmiş geçmiş
veriyi** görür.

Bu ayrım olmasaydı simülasyon kendi cevabını kopyalardı: motor gerçek hasar oranını
bilseydi her zaman doğru firmayı seçerdi ve "%X tasarruf" sonucu, modelin değil
kurgunun eseri olurdu.

Geçmiş veri kasıtlı olarak dengesiz üretilir (firma dağılımı çarpık, bölge dağılımı
nüfusa ağırlıklı) — hiyerarşik shrinkage'ın varlık sebebi bu.

### 8.2 Ortak rastgele sayılar

Her sipariş için şans çekilişleri **bir kez** yapılır ve tüm politikalar aynı
çekilişleri kullanır:

- koli başına tekdüze `u` → hasar: `u < gerçek_olasılık`
- standart normal `z` → teslimat: `T = exp(μ + σ·z)`

"MNG'yi seçseydim bu koli hasar görür müydü" sorusu aynı şansla cevaplanır. Bu
olmadan politikalar arasındaki fark, siparişlerin ve şansın gürültüsünde kaybolurdu.

Ayrıca fiyatlama, paketleme ve risk hesabı sipariş başına bir kez yapılır;
politikalar yalnızca **seçim kuralında** ayrışır. Aksi halde "P3 daha iyi" sonucu,
karar kuralından mı yoksa farklı bir hesaplamadan mı geldiği anlaşılamazdı.

### 8.3 Eşleştirilmiş bootstrap

Ortak rastgele sayılar sayesinde aynı sipariş için iki politikanın maliyeti
**eşleşmiş** bir çift. Farkların dağılımından yeniden örneklemeyle güven aralığı
çıkarılır.

Eşleştirmeden yapılan bir bootstrap, sipariş büyüklüğü varyansını farka taşır ve
aralığı gereksiz genişletir — gerçek bir kazancı "anlamsız" gösterebilir.

Aralık sıfırı kapsıyorsa rapor bunu **"ANLAMSIZ"** olarak işaretler.

### 8.4 Kalibrasyon

Motorun "%2 hasar olasılığı" dediği gönderilerin gerçekten yaklaşık %2'si hasar
görmeli. İyi ayrım yapan ama kalibre olmayan bir model, doğru firmayı seçse bile
maliyetleri yanlış büyüklükte tahmin eder ve tasarruf raporu güvenilmez olur.

Kovalar eşit genişlikte değil, **eşit sayıda gözlem** içerecek şekilde (quantile)
oluşturulur; hasar olasılıkları çok çarpık dağıldığı için eşit genişlikli kovaların
çoğu boş kalırdı.

Beklenen kalibrasyon hatası (ECE) = gözlem sayısıyla ağırlıklı ortalama sapma.
Ölçülen: **0,0046**.

---

## 9 · Yapılmayanlar

| Terim | Durum | Not |
|---|---|---|
| `V_k` — hacim taahhüdü gölge fiyatı | uygulanmadı | Açgözlü seçim yıllık taahhüt kademesini kaçırabilir. Lagrange dualiyle çözülmeli. |
| Çok günlü kapasite planlaması | uygulanmadı | Kapasite tek gün ufkunda; günler arası kaydırma yok. |
| Teslimat modelinde tam Bayesçi `κ` | basitleştirildi | Sabit sözde-gözlem sayısı. Teslimat hücreleri çok kalabalık olduğu için marjinal katkı küçük. |
| Tam projeksiyon tabanlı Extreme Point | basitleştirildi | Köşe noktaları + yerçekimi oturtması. |
| Ürünlerin dikdörtgen prizma olmayan geometrisi | modellenmedi | Yumuşak tekstil için iyimser; `compressibility` kısmen telafi eder. |
