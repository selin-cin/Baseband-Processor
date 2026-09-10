# Süre Takip

Geçici ithalat / rejim süre takip Excel dosyasının yerini alan, **tamamen
çevrimdışı** çalışan masaüstü uygulaması. Python + CustomTkinter ile yazılmıştır,
veriler yerel bir **SQLite** veritabanında saklanır.

![Süre Takip ana ekranı](ekran-goruntusu.png)

---

## Kurulum

```bash
pip install customtkinter openpyxl
```

veya:

```bash
pip install -r requirements.txt
```

Linux kullanıyorsanız Tk paketi de gerekir (Windows ve macOS'ta Python ile
birlikte gelir):

```bash
sudo apt install python3-tk
```

## Çalıştırma

```bash
python sure_takip.py
```

İlk açılışta uygulamanın bulunduğu klasörde `sure_takip.db` dosyası oluşturulur.
Tüm kayıtlar bu dosyada tutulur; uygulama kapansa bile veriler kaybolmaz.

### Ek komutlar

| Komut | Açıklama |
|---|---|
| `python sure_takip.py` | Uygulamayı açar |
| `python sure_takip.py --test` | Arayüz açmadan iş kurallarını doğrular (33 test) |
| `python sure_takip.py --sifre-sifirla` | Yönetici şifresini varsayılana (`admin123`) döndürür |
| `python sure_takip.py --veritabani D:\takip\veri.db` | Farklı bir veritabanı dosyası kullanır |

---

## Veri yapısı

| # | Sütun | Tip | Not |
|---|---|---|---|
| 1 | Dosya No | Metin | |
| 2 | Firma | Metin | |
| 3 | Beyanname No | Metin | |
| 4 | Rejim | Metin / Sayı | örn. 5300, 5100 |
| 5 | Süre Sonu | Tarih | `YYYY-AA-GG` |
| 6 | **Durum** | **Otomatik** | **Salt okunur — elle yazılamaz** |
| 7 | Açıklama | Metin | |
| 8 | Teminat | Metin / Sayı | |

Tabloda ayrıca türetilmiş bir **Kalan (gün)** sütunu gösterilir; süre sonuna kaç
gün kaldığını (negatifse kaç gün geçtiğini) belirtir. Bu sütun da veritabanında
saklanmaz, her açılışta hesaplanır.

---

## Durum kuralı

Excel'deki `G` sütunu formülünün birebir karşılığıdır:

```
=IF(F="","",
  IF(F-TODAY()>30,"NORMAL",
  IF(F>=TODAY(),"DİKKAT 1 ay kaldı",
  IF(TODAY()-F<=30,"ÖNEMLİ 1.ay esnek sürede",
  IF(TODAY()-F<=60,"TEHLİKELİ 2.ay esnek sürede","süre geçti")))))
```

| Koşul | Durum | Renk |
|---|---|---|
| Süre Sonu boş | *(boş)* | Gri |
| Süre sonuna **30 günden fazla** var | `NORMAL` | Yeşil |
| Süre sonuna **0–30 gün** var | `DİKKAT 1 ay kaldı` | Sarı |
| Süre **1–30 gün** geçmiş | `ÖNEMLİ 1.ay esnek sürede` | Turuncu |
| Süre **31–60 gün** geçmiş | `TEHLİKELİ 2.ay esnek sürede` | Koyu turuncu |
| Süre **60 günden fazla** geçmiş | `süre geçti` | Kırmızı |

Durum tablodaki satırları renklendirir ve üstteki özet kartlarında sayılır.
Kartlara tıklayarak o duruma göre anında filtreleyebilirsiniz.

> **Neden elle değiştirilemez?**
> `durum` bilinçli olarak bir veritabanı sütunu **değildir**. Yalnızca Süre
> Sonu saklanır; Durum her görüntülemede yeniden hesaplanır. Böylece veritabanına
> doğrudan müdahale edilse bile Durum bozulamaz.

---

## Yetkilendirme

Varsayılan yönetici şifresi: **`admin123`**

| İşlem | Şifre gerekir mi? |
|---|---|
| Yeni kayıt ekleme | ❌ Hayır — herkes ekleyebilir |
| Kayıt düzenleme | ✅ Evet |
| Kayıt silme | ✅ Evet (şifre + onay) |
| İçe aktarımda mevcut kayıtları silme | ✅ Evet |
| Ayarları açma | ✅ Evet |
| Durum sütununu değiştirme | ⛔ Hiçbir şekilde mümkün değil |

Şifre veritabanında düz metin olarak değil, **PBKDF2-HMAC-SHA256** (200.000
döngü, rastgele tuz) özeti olarak saklanır.

**Şifreyi değiştirmek için** üç yol vardır:

1. Uygulama içinden: **Ayarlar → Yönetici Şifresini Değiştir**
2. Şifre unutulduysa: `python sure_takip.py --sifre-sifirla`
3. Kurulum öncesi: `sure_takip.py` içindeki `VARSAYILAN_SIFRE` sabiti
   (yalnızca veritabanı ilk kez oluşturulurken geçerlidir)

### Yönetici oturumu

Varsayılan olarak **her düzenleme ve silme işleminde** şifre sorulur. Yoğun
çalışırken bu yorucu olursa **Ayarlar → Yönetici Oturumu** bölümünden 5, 15 veya
60 dakikalık bir süre seçebilirsiniz; bu sürede şifre tekrar sorulmaz. Araç
çubuğundaki **Yönetici: Açık** düğmesine basarak oturumu istediğiniz an
kapatabilirsiniz.

---

## Excel içe / dışa aktarma

### Excel'den İçe Aktar

Mevcut takip dosyanızı doğrudan okuyabilir. Desteklenenler:

* Aynı sayfada **birden fazla blok** (5300 bloğu, 5100 bloğu…) ve her bloğun
  kendi başlık satırı
* Blok başındaki tek başına duran rejim numarasının (örn. `5300`), o bloktaki
  rejim hücresi boş olan kayıtlara otomatik atanması
* Başlık adı varyasyonları: `Beyanname No` / `Beyanna No`, `Süre Sonu` /
  `Bitiş Tarihi` / `Vade` gibi
* Tarih biçimleri: `YYYY-AA-GG`, `GG.AA.YYYY`, `GG/AA/YYYY`, gerçek Excel tarih
  hücreleri ve Excel tarih seri numaraları
* Verisi olmayan (yalnızca formülle dolu) satırların atlanması

İçe aktarırken iki seçenek sunulur:

* **Mevcutları koru** → yalnızca yeni kayıtlar eklenir; aynı *Dosya No +
  Beyanname No* ikilisine sahip kayıtlar atlanır
* **Sil ve yükle** → mevcut kayıtlar silinip dosyadakilerle değiştirilir
  *(yönetici şifresi ister)*

> Dosyadaki `Durum` sütunu **okunmaz**. Durum her zaman Süre Sonu'ndan yeniden
> hesaplanır; böylece elle bozulmuş durum değerleri uygulamaya taşınmaz.

### Excel'e Aktar

Kayıtlar biçimlendirilmiş bir `.xlsx` dosyasına yazılır: başlık satırı sabitlenir,
otomatik filtre açılır, Süre Sonu gerçek tarih hücresi olarak, Durum ise
ekrandakiyle aynı renk dolgusuyla kaydedilir. Ekranda filtre etkinse yalnızca
görünen kayıtları mı yoksa tümünü mü aktaracağınız sorulur.

---

## Arama ve filtreleme

* **Arama çubuğu** — Firma, Beyanname No ve Dosya No alanlarında anlık (harf
  yazdıkça) filtreleme yapar. Türkçe karakterlere duyarsızdır: `isin` yazmak
  `IŞIN`'ı, `gurpom` yazmak `GÜRPOM`'u bulur.
* **Durum filtresi** — tek bir duruma göre daraltır.
* **Rejim filtresi** — veritabanındaki rejim kodlarından otomatik doldurulur.
* **Sütun başlıkları** — tıklayınca o sütuna göre sıralar, tekrar tıklayınca
  ters çevirir. Süre Sonu'na göre sıralamada tarihi boş kayıtlar daima sona gider.

---

## Klavye kısayolları

| Kısayol | İşlem |
|---|---|
| `Ctrl` + `N` | Yeni kayıt |
| `Ctrl` + `F` | Arama kutusuna geç |
| `Ctrl` + `E` | Excel'e aktar |
| `Delete` | Seçili kaydı sil (şifre ister) |
| `F5` | Yenile |
| Çift tıklama | Seçili kaydı düzenle (şifre ister) |
| `Esc` | Açık pencereyi kapat |

---

## Veri saklama ve yedekleme

Tüm veriler tek bir dosyada tutulur: **`sure_takip.db`** (uygulamayla aynı klasör).

Yedeklemek için bu dosyayı kopyalamanız yeterlidir. Uygulama açıkken WAL kipi
kullanıldığından, yedek alırken `sure_takip.db-wal` ve `sure_takip.db-shm`
dosyalarını da kopyalayın ya da yedeği uygulama kapalıyken alın.

Dosyayı başka bir yere koymak isterseniz:

```bash
python sure_takip.py --veritabani "D:\Ortak\takip\sure_takip.db"
```

> Uygulama hiçbir ağ bağlantısı kurmaz; kurulum sonrası internet gerektirmez.

---

## Windows'ta tek dosyalık .exe üretme (isteğe bağlı)

Bilgisayarında Python olmayan kullanıcılar için:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "SureTakip" sure_takip.py
```

Oluşan `dist/SureTakip.exe` dosyası tek başına çalışır. Veritabanı `.exe` ile
aynı klasörde oluşur.

---

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| `ModuleNotFoundError: No module named 'customtkinter'` | `pip install customtkinter` |
| `ModuleNotFoundError: No module named 'tkinter'` (Linux) | `sudo apt install python3-tk` |
| Excel düğmeleri "Eksik kütüphane" diyor | `pip install openpyxl` |
| Şifre unutuldu | `python sure_takip.py --sifre-sifirla` |
| "Dosya açık" hatasıyla dışa aktarılamıyor | Hedef `.xlsx` dosyasını Excel'de kapatın |
| Satır renkleri görünmüyor | Uygulama Tk'nin bilinen etiket-rengi hatasını kendisi düzeltir; sorun sürerse Python'u güncelleyin |

---

## Dosya yapısı

```
sure_takip/
├── sure_takip.py        # Uygulamanın tamamı (tek dosya)
├── requirements.txt     # Bağımlılıklar
├── README.md            # Bu belge
└── sure_takip.db        # İlk çalıştırmada otomatik oluşur (depoya girmez)
```

`sure_takip.py` içindeki bölümler:

| Bölüm | İçerik |
|---|---|
| 1 | Sabitler, renk paleti, sütun tanımları |
| 2 | İş kuralları (`durum_hesapla`, tarih ayıklama, Türkçe arama) |
| 3 | Şifre özetleme ve doğrulama |
| 4 | SQLite veri erişim katmanı |
| 5 | Excel içe / dışa aktarma |
| 6 | Ortak arayüz bileşenleri ve pencereler |
| 7 | Ana pencere |
| 8 | İş kuralı testleri (`--test`) |
| 9 | Giriş noktası (`main`) |
