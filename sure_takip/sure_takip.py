#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 SÜRE TAKİP  —  Geçici İthalat / Rejim Süre Takip Masaüstü Uygulaması
=====================================================================

Excel takip dosyasının (Dosya No / Firma / Beyanname No / Rejim /
Süre Sonu / Durum / Açıklama / Teminat) yerini alan, tamamen ÇEVRİMDIŞI
çalışan bir masaüstü uygulamasıdır. Veriler yerel bir SQLite
veritabanında saklanır; uygulama kapansa bile kaybolmaz.

---------------------------------------------------------------------
KURULUM
---------------------------------------------------------------------
    pip install customtkinter openpyxl

    (Linux'ta ayrıca Tk gerekir:  sudo apt install python3-tk)

ÇALIŞTIRMA
---------------------------------------------------------------------
    python sure_takip.py

EK KOMUTLAR
---------------------------------------------------------------------
    python sure_takip.py --test            # İş kurallarını test eder (arayüz açmaz)
    python sure_takip.py --sifre-sifirla   # Yönetici şifresini varsayılana döndürür
    python sure_takip.py --veritabani yol  # Farklı bir veritabanı dosyası kullanır

---------------------------------------------------------------------
ÖNEMLİ İŞ KURALI — "DURUM" SÜTUNU
---------------------------------------------------------------------
Durum, Excel'deki şu formülün birebir karşılığıdır ve her zaman
otomatik hesaplanır; veritabanında SAKLANMAZ, kullanıcı elle giremez:

    =IF(F="","",
      IF(F-TODAY()>30,"NORMAL",
      IF(F>=TODAY(),"DİKKAT 1 ay kaldı",
      IF(TODAY()-F<=30,"ÖNEMLİ 1.ay esnek sürede",
      IF(TODAY()-F<=60,"TEHLİKELİ 2.ay esnek sürede","süre geçti")))))

---------------------------------------------------------------------
YETKİLENDİRME
---------------------------------------------------------------------
  * Yeni kayıt ekleme  -> serbest (şifre istemez)
  * Kayıt düzenleme    -> yönetici şifresi ister
  * Kayıt silme        -> yönetici şifresi ister
  * Durum sütunu       -> her koşulda salt okunur
  * Varsayılan şifre   -> "admin123"  (aşağıdaki VARSAYILAN_SIFRE
                          sabitinden veya Ayarlar penceresinden
                          değiştirilebilir)
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

# --- Arayüz kütüphaneleri -------------------------------------------------
# Not: --test gibi arayüzsüz komutların Tk kurulu olmayan makinelerde de
# çalışabilmesi için içe aktarma hataları burada yakalanır.
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    import customtkinter as ctk

    ARAYUZ_HATASI: str | None = None
except Exception as _hata:  # pragma: no cover - ortama bağlı
    tk = ttk = filedialog = messagebox = None  # type: ignore[assignment]
    ARAYUZ_HATASI = str(_hata)

    class _ArayuzYerTutucu:
        """Tk kurulu olmayan makinelerde modülün yine de yüklenebilmesini sağlar.

        Yalnızca sınıf tanımlarının (Modal, Uygulama…) temel sınıf ihtiyacını
        karşılar; arayüz açılmaya çalışıldığında main() anlaşılır bir hata verir.
        """

        CTk = object
        CTkToplevel = object

    ctk = _ArayuzYerTutucu()  # type: ignore[assignment]


# =========================================================================
#  1. BÖLÜM — SABİTLER VE AYARLAR
# =========================================================================

UYGULAMA_ADI = "Süre Takip"
SURUM = "1.0"



def _uygulama_klasoru() -> Path:
    """Uygulamanın kendi klasörü.

    PyInstaller ile tek dosyalık .exe hâline getirildiğinde `__file__`
    geçici bir çıkarma klasörünü (``_MEIPASS``) gösterir; oraya yazılan
    veritabanı program kapanınca SİLİNİR. Bu yüzden paketlenmiş çalışmada
    .exe dosyasının bulunduğu klasör kullanılır.
    """
    if getattr(sys, "frozen", False):          # PyInstaller / cx_Freeze
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _yazilabilir_mi(klasor: Path) -> bool:
    """Klasöre dosya yazılabiliyor mu? (Program Files gibi korumalı yerler için)"""
    try:
        klasor.mkdir(parents=True, exist_ok=True)
        deneme = klasor / ".yazma_denemesi"
        deneme.write_text("x", encoding="utf-8")
        deneme.unlink()
        return True
    except OSError:
        return False


def _varsayilan_veritabani() -> Path:
    """Veritabanı dosyasının varsayılan konumu.

    Öncelik uygulamanın kendi klasörüdür (taşınabilirlik: klasörü kopyalamak
    verileri de taşır). O klasör salt okunursa (örn. "Program Files" altına
    kurulmuşsa) kullanıcının kendi klasörüne düşülür.
    """
    klasor = _uygulama_klasoru()
    if _yazilabilir_mi(klasor):
        return klasor / "sure_takip.db"
    return Path.home() / "SureTakip" / "sure_takip.db"


UYGULAMA_KLASORU = _uygulama_klasoru()
VARSAYILAN_VERITABANI = _varsayilan_veritabani()

# Yönetici şifresi — yalnızca veritabanı ilk kez oluşturulduğunda veya
# "--sifre-sifirla" komutu çalıştırıldığında geçerlidir. Sonrasında şifre,
# veritabanında güvenli (PBKDF2) özet olarak saklanır.
VARSAYILAN_SIFRE = "admin123"

# Şifre özetleme parametreleri
PBKDF2_DONGU = 200_000

# --- Durum değerleri (Excel'deki metinlerle birebir aynı) ----------------
DURUM_BOS = ""
DURUM_NORMAL = "NORMAL"
DURUM_DIKKAT = "DİKKAT 1 ay kaldı"
DURUM_ONEMLI = "ÖNEMLİ 1.ay esnek sürede"
DURUM_TEHLIKELI = "TEHLİKELİ 2.ay esnek sürede"
DURUM_GECTI = "süre geçti"

# Filtre kutusunda görünecek sıra
DURUM_SIRASI = [
    DURUM_NORMAL,
    DURUM_DIKKAT,
    DURUM_ONEMLI,
    DURUM_TEHLIKELI,
    DURUM_GECTI,
    DURUM_BOS,
]

# Durum önem sırası (sıralama ve özet kartları için)
DURUM_AGIRLIK = {
    DURUM_GECTI: 0,
    DURUM_TEHLIKELI: 1,
    DURUM_ONEMLI: 2,
    DURUM_DIKKAT: 3,
    DURUM_NORMAL: 4,
    DURUM_BOS: 5,
}

# --- Renk paleti ---------------------------------------------------------
# Her renk (açık tema, koyu tema) ikilisi olarak tanımlanır.
PALET = {
    "arkaplan":       ("#f2f4f8", "#15171c"),
    "yuzey":          ("#ffffff", "#1d2027"),
    "yuzey2":         ("#e9edf3", "#252932"),
    "kenar":          ("#d5dbe4", "#31363f"),
    "metin":          ("#1b2029", "#e9ecf1"),
    "metin_soluk":    ("#5c6675", "#9aa3b2"),
    "vurgu":          ("#2f6fed", "#4d8bff"),
    "vurgu_koyu":     ("#2559c4", "#3d78e8"),
    "tehlike":        ("#d13438", "#e05257"),
    "tehlike_koyu":   ("#b02226", "#c43f44"),
    "basari":         ("#1f8a4c", "#2ea55d"),
}

# Durum -> (açık tema arkaplan, koyu tema arkaplan, açık yazı, koyu yazı)
# Tablo satırları bu renklerle etiketlenir.
DURUM_RENKLERI = {
    DURUM_NORMAL:    ("#e3f6e9", "#17362a", "#14663c", "#7ee2a8"),
    DURUM_DIKKAT:    ("#fdf3d4", "#3a3218", "#8a6100", "#ffd666"),
    DURUM_ONEMLI:    ("#ffe6cf", "#3d2a17", "#a04b00", "#ffb066"),
    DURUM_TEHLIKELI: ("#ffd9d2", "#43241d", "#9c2a12", "#ff9478"),
    DURUM_GECTI:     ("#ffd0d4", "#451f24", "#96121c", "#ff8a94"),
    DURUM_BOS:       ("#f4f5f7", "#22252c", "#6b7280", "#9aa3b2"),
}

# Excel dışa aktarımında kullanılacak dolgu renkleri (ARGB)
DURUM_EXCEL_RENK = {
    DURUM_NORMAL:    "FFE3F6E9",
    DURUM_DIKKAT:    "FFFDF3D4",
    DURUM_ONEMLI:    "FFFFE6CF",
    DURUM_TEHLIKELI: "FFFFD9D2",
    DURUM_GECTI:     "FFFFD0D4",
    DURUM_BOS:       "FFFFFFFF",
}

# Excel içe aktarımında tanınan başlık adları (küçük harfe indirgenmiş hâlleri)
BASLIK_ESLESTIRME = {
    "dosya_no": {"dosya no", "dosyano", "dosya", "dosya numarasi", "dosya nu"},
    "firma": {"firma", "firma adi", "musteri", "unvan", "firma unvani"},
    "beyanname_no": {
        "beyanname no", "beyanna no", "beyanname", "beyanname numarasi",
        "beyanname nu", "byn no", "beyannameno",
    },
    "rejim": {"rejim", "rejim kodu", "rejim no"},
    "sure_sonu": {
        "sure sonu", "suresonu", "bitis tarihi", "vade", "vade tarihi",
        "son tarih", "sure bitis",
    },
    "durum": {"durum"},  # Okunur ama YOK SAYILIR — Durum daima hesaplanır.
    "aciklama": {"aciklama", "not", "notlar", "aciklamalar"},
    "teminat": {"teminat", "teminat tutari", "teminat no"},
}

# Tablo sütunları: (anahtar, başlık, genişlik, hizalama)
TABLO_SUTUNLARI = [
    ("dosya_no",     "Dosya No",     105, "w"),
    ("firma",        "Firma",        165, "w"),
    ("beyanname_no", "Beyanname No", 185, "w"),
    ("rejim",        "Rejim",         75, "center"),
    ("sure_sonu",    "Süre Sonu",    105, "center"),
    ("kalan",        "Kalan (gün)",  105, "center"),
    ("durum",        "Durum",        210, "w"),
    ("aciklama",     "Açıklama",     175, "w"),
    ("teminat",      "Teminat",      105, "w"),
]


# =========================================================================
#  2. BÖLÜM — İŞ KURALLARI (ARAYÜZDEN BAĞIMSIZ, TEST EDİLEBİLİR)
# =========================================================================

def durum_hesapla(sure_sonu: date | None, bugun: date | None = None) -> str:
    """Excel'deki G sütunu formülünün birebir Python karşılığı.

    Kural:
        Süre Sonu boş                -> ""
        (Süre Sonu - Bugün) > 30     -> "NORMAL"
        (Süre Sonu - Bugün) >= 0     -> "DİKKAT 1 ay kaldı"
        (Bugün - Süre Sonu) <= 30    -> "ÖNEMLİ 1.ay esnek sürede"
        (Bugün - Süre Sonu) <= 60    -> "TEHLİKELİ 2.ay esnek sürede"
        daha eski                    -> "süre geçti"
    """
    if sure_sonu is None:
        return DURUM_BOS
    if bugun is None:
        bugun = date.today()
    fark = (sure_sonu - bugun).days          # Excel'deki  F - TODAY()
    if fark > 30:
        return DURUM_NORMAL
    if fark >= 0:                            # F >= TODAY()
        return DURUM_DIKKAT
    if -fark <= 30:                          # TODAY() - F <= 30
        return DURUM_ONEMLI
    if -fark <= 60:                          # TODAY() - F <= 60
        return DURUM_TEHLIKELI
    return DURUM_GECTI


def kalan_gun(sure_sonu: date | None, bugun: date | None = None) -> int | None:
    """Süre sonuna kaç gün kaldığını verir (negatifse süre geçmiştir)."""
    if sure_sonu is None:
        return None
    return (sure_sonu - (bugun or date.today())).days


# Kabul edilen tarih yazım biçimleri (ilk sıradaki tercih edilendir).
TARIH_BICIMLERI = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y.%m.%d")


def tarih_ayikla(deger) -> date | None:
    """Metin / datetime / Excel seri numarasını `date` nesnesine çevirir.

    Çözümlenemeyen değerler için None döner (hata fırlatmaz).
    """
    if deger is None:
        return None
    if isinstance(deger, datetime):
        return deger.date()
    if isinstance(deger, date):
        return deger
    if isinstance(deger, (int, float)):
        # Excel tarih seri numarası (1899-12-30 başlangıçlı).
        if 20_000 <= float(deger) <= 80_000:
            return date(1899, 12, 30) + timedelta(days=int(deger))
        return None
    metin = str(deger).strip()
    if not metin:
        return None
    # "2026-10-08 00:00:00" gibi saat ekli değerleri kırp.
    metin = metin.split(" ")[0].split("T")[0]
    for bicim in TARIH_BICIMLERI:
        try:
            return datetime.strptime(metin, bicim).date()
        except ValueError:
            continue
    return None


def tarih_metin(deger: date | None) -> str:
    """`date` -> 'YYYY-AA-GG' metni (None ise boş metin)."""
    return deger.isoformat() if deger else ""


# --- Konsol çıktısı (Windows cp1252 uyumu) -------------------------------
# Windows'ta konsol kod sayfası genelde cp1252'dir ve "✓" gibi işaretleri,
# hatta "ı ğ ş İ" harflerini basamaz; doğrudan print() UnicodeEncodeError
# ile ÇÖKER. Aşağıdaki yardımcılar akışı UTF-8'e çevirmeyi dener, olmazsa
# basılamayan karakterleri güvenle değiştirir.

def _konsolu_hazirla() -> None:
    """Standart çıktıyı, Unicode karakterlerde çökmeyecek hâle getirir."""
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.reconfigure(encoding="utf-8", errors="replace")  # Python 3.7+
        except (AttributeError, OSError, ValueError):
            pass


def _basilabilir_mi(ornek: str) -> bool:
    """Verilen metin, etkin konsol kodlamasıyla basılabiliyor mu?"""
    kodlama = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        ornek.encode(kodlama)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def yaz(metin: str = "") -> None:
    """Konsola, kodlama hatasına düşmeden yazar."""
    try:
        print(metin)
    except UnicodeEncodeError:
        kodlama = getattr(sys.stdout, "encoding", None) or "ascii"
        print(metin.encode(kodlama, "replace").decode(kodlama, "replace"))


# Türkçe harfleri arama/karşılaştırma için sadeleştirme tablosu.
_TR_SADE = str.maketrans({
    "ı": "i", "İ": "i", "I": "i", "i": "i",
    "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u", "ö": "o", "Ö": "o",
    "ç": "c", "Ç": "c", "â": "a", "Â": "a", "î": "i", "û": "u",
})


def tr_sadelestir(metin) -> str:
    """Türkçe'ye duyarlı, büyük/küçük harf ayrımsız karşılaştırma anahtarı."""
    if metin is None:
        return ""
    return str(metin).translate(_TR_SADE).lower().strip()


def baslik_anahtari(metin) -> str:
    """Excel başlığını eşleştirme sözlüğüyle kıyaslanabilir hâle getirir."""
    sade = tr_sadelestir(metin)
    return re.sub(r"\s+", " ", sade.replace(".", " ").replace("_", " ")).strip()


# =========================================================================
#  3. BÖLÜM — ŞİFRE YÖNETİMİ
# =========================================================================

def sifre_ozetle(sifre: str, tuz: str | None = None, dongu: int = PBKDF2_DONGU) -> str:
    """Şifreyi 'pbkdf2_sha256$dongu$tuz$ozet' biçiminde güvenli özete çevirir."""
    tuz = tuz or secrets.token_hex(16)
    ozet = hashlib.pbkdf2_hmac("sha256", sifre.encode("utf-8"), tuz.encode("utf-8"), dongu)
    return f"pbkdf2_sha256${dongu}${tuz}${ozet.hex()}"


def sifre_karsilastir(sifre: str, kayitli_ozet: str) -> bool:
    """Girilen şifre ile saklanan özeti zamanlama saldırısına kapalı biçimde kıyaslar."""
    try:
        algo, dongu, tuz, _ = kayitli_ozet.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        yeni = sifre_ozetle(sifre, tuz, int(dongu))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(yeni, kayitli_ozet)


# =========================================================================
#  4. BÖLÜM — VERİTABANI KATMANI (SQLite)
# =========================================================================

class Veritabani:
    """Tüm SQLite işlemlerini kapsayan basit veri erişim katmanı.

    Tasarım notu: "Durum" bilinçli olarak bir SÜTUN DEĞİLDİR. Böylece
    veriye elle bile müdahale edilse Durum bozulamaz; her zaman
    `durum_hesapla()` ile Süre Sonu'ndan türetilir.
    """

    def __init__(self, yol: Path):
        self.yol = Path(yol)
        self.yol.parent.mkdir(parents=True, exist_ok=True)
        self.baglanti = sqlite3.connect(str(self.yol))
        self.baglanti.row_factory = sqlite3.Row
        self.baglanti.execute("PRAGMA journal_mode=WAL")
        self.baglanti.execute("PRAGMA foreign_keys=ON")
        self._kur()

    # ---------------------------------------------------------------- kurulum
    def _kur(self) -> None:
        """Tabloları oluşturur ve ilk çalıştırmada varsayılan ayarları yazar."""
        self.baglanti.executescript(
            """
            CREATE TABLE IF NOT EXISTS kayitlar (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                dosya_no      TEXT NOT NULL DEFAULT '',
                firma         TEXT NOT NULL DEFAULT '',
                beyanname_no  TEXT NOT NULL DEFAULT '',
                rejim         TEXT NOT NULL DEFAULT '',
                sure_sonu     TEXT,                     -- 'YYYY-AA-GG' ya da NULL
                aciklama      TEXT NOT NULL DEFAULT '',
                teminat       TEXT NOT NULL DEFAULT '',
                olusturma     TEXT NOT NULL,
                guncelleme    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ayarlar (
                anahtar TEXT PRIMARY KEY,
                deger   TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS ix_kayitlar_dosya
                ON kayitlar(dosya_no);
            CREATE INDEX IF NOT EXISTS ix_kayitlar_beyanname
                ON kayitlar(beyanname_no);
            CREATE INDEX IF NOT EXISTS ix_kayitlar_sure
                ON kayitlar(sure_sonu);
            """
        )
        # İlk çalıştırma varsayılanları
        if self.ayar_al("sifre_ozeti") is None:
            self.ayar_yaz("sifre_ozeti", sifre_ozetle(VARSAYILAN_SIFRE))
        if self.ayar_al("tema") is None:
            self.ayar_yaz("tema", "Sistem")
        if self.ayar_al("oturum_dakika") is None:
            # 0 = her düzenleme/silme işleminde şifre sorulur (varsayılan davranış)
            self.ayar_yaz("oturum_dakika", "0")
        self.baglanti.commit()

    # ------------------------------------------------------------------ ayarlar
    def ayar_al(self, anahtar: str, varsayilan: str | None = None) -> str | None:
        satir = self.baglanti.execute(
            "SELECT deger FROM ayarlar WHERE anahtar = ?", (anahtar,)
        ).fetchone()
        return satir["deger"] if satir else varsayilan

    def ayar_yaz(self, anahtar: str, deger: str) -> None:
        self.baglanti.execute(
            "INSERT INTO ayarlar(anahtar, deger) VALUES(?, ?) "
            "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger",
            (anahtar, str(deger)),
        )
        self.baglanti.commit()

    # -------------------------------------------------------------------- şifre
    def sifre_dogru_mu(self, sifre: str) -> bool:
        ozet = self.ayar_al("sifre_ozeti") or ""
        return sifre_karsilastir(sifre, ozet)

    def sifre_degistir(self, yeni_sifre: str) -> None:
        self.ayar_yaz("sifre_ozeti", sifre_ozetle(yeni_sifre))

    # ------------------------------------------------------------------ kayıtlar
    @staticmethod
    def _satiri_cevir(satir: sqlite3.Row, bugun: date | None = None) -> dict:
        """Veritabanı satırını, Durum'u hesaplanmış bir sözlüğe dönüştürür."""
        tarih = tarih_ayikla(satir["sure_sonu"])
        return {
            "id": satir["id"],
            "dosya_no": satir["dosya_no"],
            "firma": satir["firma"],
            "beyanname_no": satir["beyanname_no"],
            "rejim": satir["rejim"],
            "sure_sonu": tarih_metin(tarih),
            "sure_sonu_tarih": tarih,
            "durum": durum_hesapla(tarih, bugun),      # <-- daima hesaplanır
            "kalan": kalan_gun(tarih, bugun),
            "aciklama": satir["aciklama"],
            "teminat": satir["teminat"],
        }

    def tum_kayitlar(self, bugun: date | None = None) -> list[dict]:
        satirlar = self.baglanti.execute(
            "SELECT * FROM kayitlar ORDER BY id"
        ).fetchall()
        return [self._satiri_cevir(s, bugun) for s in satirlar]

    def kayit_getir(self, kayit_id: int) -> dict | None:
        satir = self.baglanti.execute(
            "SELECT * FROM kayitlar WHERE id = ?", (kayit_id,)
        ).fetchone()
        return self._satiri_cevir(satir) if satir else None

    def kayit_ekle(self, veri: dict) -> int:
        simdi = datetime.now().isoformat(timespec="seconds")
        imlec = self.baglanti.execute(
            """INSERT INTO kayitlar
               (dosya_no, firma, beyanname_no, rejim, sure_sonu,
                aciklama, teminat, olusturma, guncelleme)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                veri.get("dosya_no", ""),
                veri.get("firma", ""),
                veri.get("beyanname_no", ""),
                veri.get("rejim", ""),
                veri.get("sure_sonu") or None,
                veri.get("aciklama", ""),
                veri.get("teminat", ""),
                simdi,
                simdi,
            ),
        )
        self.baglanti.commit()
        return int(imlec.lastrowid)

    def kayit_guncelle(self, kayit_id: int, veri: dict) -> None:
        self.baglanti.execute(
            """UPDATE kayitlar SET
                   dosya_no = ?, firma = ?, beyanname_no = ?, rejim = ?,
                   sure_sonu = ?, aciklama = ?, teminat = ?, guncelleme = ?
               WHERE id = ?""",
            (
                veri.get("dosya_no", ""),
                veri.get("firma", ""),
                veri.get("beyanname_no", ""),
                veri.get("rejim", ""),
                veri.get("sure_sonu") or None,
                veri.get("aciklama", ""),
                veri.get("teminat", ""),
                datetime.now().isoformat(timespec="seconds"),
                kayit_id,
            ),
        )
        self.baglanti.commit()

    def kayit_sil(self, kayit_id: int) -> None:
        self.baglanti.execute("DELETE FROM kayitlar WHERE id = ?", (kayit_id,))
        self.baglanti.commit()

    def tumunu_sil(self) -> int:
        imlec = self.baglanti.execute("DELETE FROM kayitlar")
        self.baglanti.commit()
        return imlec.rowcount

    def kayit_sayisi(self) -> int:
        return int(self.baglanti.execute("SELECT COUNT(*) FROM kayitlar").fetchone()[0])

    def ayni_kayit_var_mi(self, dosya_no: str, beyanname_no: str) -> bool:
        """İçe aktarımda mükerrer kayıtları elemek için kullanılır."""
        satir = self.baglanti.execute(
            "SELECT 1 FROM kayitlar WHERE dosya_no = ? AND beyanname_no = ? LIMIT 1",
            (dosya_no, beyanname_no),
        ).fetchone()
        return satir is not None

    def kapat(self) -> None:
        try:
            self.baglanti.close()
        except sqlite3.Error:
            pass


# =========================================================================
#  5. BÖLÜM — EXCEL İÇE / DIŞA AKTARMA
# =========================================================================

def _openpyxl_yukle():
    """openpyxl'i geç yükler; kurulu değilse anlaşılır bir hata verir."""
    try:
        import openpyxl  # noqa: F401  (yalnızca varlık kontrolü)
        return openpyxl
    except ImportError as hata:
        raise RuntimeError(
            "Excel işlemleri için 'openpyxl' kütüphanesi gerekiyor.\n\n"
            "Kurmak için:\n    pip install openpyxl"
        ) from hata


def excelden_oku(dosya_yolu: str | Path) -> tuple[list[dict], list[str]]:
    """Bir .xlsx dosyasını okuyup kayıt sözlükleri listesi döndürür.

    Orijinal takip dosyasının yapısını da destekler:
      * Aynı sayfada birden fazla blok bulunabilir (5300, 5100 ...).
      * Her bloğun kendi başlık satırı olabilir.
      * Blok başlığındaki tek başına duran rejim numarası (örn. 5300),
        satırında rejim yazmayan kayıtlara otomatik atanır.

    Dönüş: (kayitlar, uyarilar)
    """
    openpyxl = _openpyxl_yukle()
    # data_only=True: formül yerine hesaplanmış değer okunur.
    calisma_kitabi = openpyxl.load_workbook(str(dosya_yolu), data_only=True, read_only=True)

    kayitlar: list[dict] = []
    uyarilar: list[str] = []

    for sayfa in calisma_kitabi.worksheets:
        sutun_haritasi: dict[str, int] | None = None
        blok_rejimi = ""

        for satir_no, satir in enumerate(sayfa.iter_rows(values_only=True), start=1):
            if satir is None:
                continue
            dolu_hucreler = [h for h in satir if h not in (None, "")]

            # 1) Başlık satırı mı? ("Dosya No" + "Firma" birlikte geçiyorsa evet)
            metinler = {baslik_anahtari(h) for h in satir if isinstance(h, str)}
            if metinler & BASLIK_ESLESTIRME["dosya_no"] and metinler & BASLIK_ESLESTIRME["firma"]:
                sutun_haritasi = {}
                for indis, hucre in enumerate(satir):
                    if not isinstance(hucre, str):
                        continue
                    anahtar = baslik_anahtari(hucre)
                    for alan, adlar in BASLIK_ESLESTIRME.items():
                        if anahtar in adlar:
                            sutun_haritasi.setdefault(alan, indis)
                continue

            # 2) Tek başına duran tam sayı -> blok rejim kodu (örn. 5300 / 5100)
            if len(dolu_hucreler) == 1:
                tek = dolu_hucreler[0]
                if isinstance(tek, (int, float)) and float(tek).is_integer():
                    blok_rejimi = str(int(tek))
                    continue
                if sutun_haritasi is None:
                    # Başlık satırından önceki serbest metin (sayfa başlığı vb.)
                    continue

            # 3) Henüz başlık bulunamadıysa bu satırı atla
            if not sutun_haritasi or not dolu_hucreler:
                continue

            def al(alan: str):
                indis = sutun_haritasi.get(alan)
                if indis is None or indis >= len(satir):
                    return None
                return satir[indis]

            def metin(alan: str) -> str:
                deger = al(alan)
                if deger is None:
                    return ""
                if isinstance(deger, float) and deger.is_integer():
                    return str(int(deger))
                return str(deger).strip()

            dosya_no = metin("dosya_no")
            firma = metin("firma")
            beyanname_no = metin("beyanname_no")
            # Tümü boşsa bu bir dolgu satırıdır (orijinal dosyada formülle dolu
            # ama verisi olmayan onlarca satır var) -> atla.
            if not (dosya_no or firma or beyanname_no):
                continue

            ham_tarih = al("sure_sonu")
            tarih = tarih_ayikla(ham_tarih)
            if ham_tarih not in (None, "") and tarih is None:
                uyarilar.append(
                    f"{sayfa.title}!satır {satir_no}: '{ham_tarih}' tarih olarak "
                    f"okunamadı, Süre Sonu boş bırakıldı."
                )

            kayitlar.append({
                "dosya_no": dosya_no,
                "firma": firma,
                "beyanname_no": beyanname_no,
                "rejim": metin("rejim") or blok_rejimi,
                "sure_sonu": tarih_metin(tarih),
                "aciklama": metin("aciklama"),
                "teminat": metin("teminat"),
                # NOT: Dosyadaki "Durum" sütunu bilinçli olarak okunmaz;
                # Durum her zaman Süre Sonu'ndan yeniden hesaplanır.
            })

    calisma_kitabi.close()
    return kayitlar, uyarilar


def excele_yaz(dosya_yolu: str | Path, kayitlar: list[dict]) -> None:
    """Kayıtları biçimlendirilmiş bir .xlsx dosyasına yazar.

    Durum sütunu, uygulamadaki renklerle aynı dolgu renkleriyle yazılır;
    böylece dışa aktarılan dosya ekrandaki tabloyla birebir okunur.
    """
    openpyxl = _openpyxl_yukle()
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    calisma_kitabi = openpyxl.Workbook()
    sayfa = calisma_kitabi.active
    sayfa.title = "Süre Takip"

    basliklar = ["Dosya No", "Firma", "Beyanname No", "Rejim",
                 "Süre Sonu", "Durum", "Açıklama", "Teminat"]
    genislikler = [14, 22, 22, 8, 13, 27, 24, 14]

    baslik_dolgusu = PatternFill("solid", fgColor="FF2F6FED")
    baslik_yazisi = Font(bold=True, color="FFFFFFFF", size=11)
    ince_kenar = Border(*(Side(style="thin", color="FFD5DBE4"),) * 4)

    # --- Başlık satırı ---
    for sutun, baslik in enumerate(basliklar, start=1):
        hucre = sayfa.cell(row=1, column=sutun, value=baslik)
        hucre.fill = baslik_dolgusu
        hucre.font = baslik_yazisi
        hucre.alignment = Alignment(horizontal="center", vertical="center")
        sayfa.column_dimensions[get_column_letter(sutun)].width = genislikler[sutun - 1]
    sayfa.row_dimensions[1].height = 24

    # --- Veri satırları ---
    for satir_no, kayit in enumerate(kayitlar, start=2):
        tarih = kayit.get("sure_sonu_tarih") or tarih_ayikla(kayit.get("sure_sonu"))
        durum = kayit.get("durum", durum_hesapla(tarih))

        degerler = [
            kayit.get("dosya_no", ""),
            kayit.get("firma", ""),
            kayit.get("beyanname_no", ""),
            kayit.get("rejim", ""),
            tarih,                      # gerçek tarih değeri olarak yazılır
            durum,
            kayit.get("aciklama", ""),
            kayit.get("teminat", ""),
        ]
        for sutun, deger in enumerate(degerler, start=1):
            hucre = sayfa.cell(row=satir_no, column=sutun, value=deger)
            hucre.border = ince_kenar
            if sutun == 5 and tarih:                       # Süre Sonu
                hucre.number_format = "yyyy-mm-dd"
                hucre.alignment = Alignment(horizontal="center")
            elif sutun == 4:                               # Rejim
                hucre.alignment = Alignment(horizontal="center")
            if sutun == 6:                                 # Durum
                hucre.fill = PatternFill(
                    "solid", fgColor=DURUM_EXCEL_RENK.get(durum, "FFFFFFFF")
                )
                hucre.font = Font(bold=durum in (DURUM_GECTI, DURUM_TEHLIKELI))

    # --- Kullanım kolaylıkları ---
    sayfa.freeze_panes = "A2"
    if kayitlar:
        sayfa.auto_filter.ref = f"A1:H{len(kayitlar) + 1}"

    calisma_kitabi.save(str(dosya_yolu))


# =========================================================================
#  6. BÖLÜM — ORTAK ARAYÜZ YARDIMCILARI
# =========================================================================

def _renk(anahtar: str) -> tuple[str, str]:
    """PALET'ten (açık, koyu) renk ikilisini verir."""
    return PALET[anahtar]


def _tema_indeksi() -> int:
    """Etkin temanın renk ikilisindeki indeksi: 0 = açık, 1 = koyu."""
    return 1 if ctk.get_appearance_mode().lower() == "dark" else 0


def _tek_renk(anahtar: str) -> str:
    """Etkin temaya göre tek bir renk kodu (ttk widget'ları için gerekir)."""
    return PALET[anahtar][_tema_indeksi()]


class Modal(ctk.CTkToplevel):
    """Tüm açılır pencerelerin ortak temeli: ortalanır, kilitler, Esc ile kapanır."""

    def __init__(self, ana, baslik: str, genislik: int = 460, yukseklik: int = 300):
        super().__init__(ana)
        self.sonuc = None
        self._ana = ana
        self.title(baslik)
        self.resizable(False, False)
        self.configure(fg_color=_renk("arkaplan"))
        self.transient(ana)
        self._temel_boyut = (genislik, yukseklik)
        self._ortala(ana, genislik, yukseklik)
        self.protocol("WM_DELETE_WINDOW", self.iptal)
        self.bind("<Escape>", lambda _e: self.iptal())
        # CTkToplevel kısa süre gizli açıldığı için grab_set hemen çalışmaz.
        self.after(120, self._kilitle)

    def _kilitle(self) -> None:
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            self.after(80, self._kilitle)

    def _ortala(self, ana, genislik: int, yukseklik: int) -> None:
        try:
            ana.update_idletasks()
            x = ana.winfo_rootx() + max((ana.winfo_width() - genislik) // 2, 0)
            y = ana.winfo_rooty() + max((ana.winfo_height() - yukseklik) // 3, 0)
        except tk.TclError:
            x, y = 240, 160
        self.geometry(f"{genislik}x{yukseklik}+{max(x, 0)}+{max(y, 0)}")

    def icerige_uydur(self) -> None:
        """Pencereyi içeriğin gerçek boyutuna göre büyütür.

        İşletim sistemine göre yazı tipi ölçüleri değiştiği için sabit
        piksel değerleri her makinede yetmeyebilir; bu yöntem alt alanların
        kırpılmasını önler.
        """
        self.update_idletasks()
        temel_g, temel_y = self._temel_boyut
        genislik = min(max(self.winfo_reqwidth(), temel_g), self.winfo_screenwidth() - 60)
        yukseklik = min(max(self.winfo_reqheight(), temel_y), self.winfo_screenheight() - 90)
        self._ortala(self._ana, genislik, yukseklik)

    def iptal(self, *_args) -> None:
        self.sonuc = None
        self._kapat()

    def _kapat(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def bekle(self):
        """Pencere kapanana kadar bekler ve sonucu döndürür."""
        self.wait_window()
        return self.sonuc


class SifreDialog(Modal):
    """Yönetici şifresi soran kilit penceresi.

    Doğru şifre girilirse `bekle()` True döndürür; iptal/yanlış durumunda None.
    """

    def __init__(self, ana, veritabani: Veritabani, aciklama: str):
        super().__init__(ana, "Yönetici Doğrulaması", 420, 270)
        self.veritabani = veritabani

        govde = ctk.CTkFrame(self, fg_color=_renk("yuzey"), corner_radius=12)
        govde.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            govde, text="Yönetici Şifresi",
            font=ctk.CTkFont(size=17, weight="bold"), text_color=_renk("metin"),
        ).pack(anchor="w", padx=20, pady=(18, 2))

        ctk.CTkLabel(
            govde, text=aciklama, font=ctk.CTkFont(size=12),
            text_color=_renk("metin_soluk"), wraplength=330, justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 12))

        self.giris = ctk.CTkEntry(
            govde, show="●", placeholder_text="Şifre", height=38,
            border_color=_renk("kenar"), fg_color=_renk("yuzey2"),
            text_color=_renk("metin"),
        )
        self.giris.pack(fill="x", padx=20)
        self.giris.bind("<Return>", lambda _e: self.onayla())

        self.uyari = ctk.CTkLabel(
            govde, text="", font=ctk.CTkFont(size=12),
            text_color=_renk("tehlike"),
        )
        self.uyari.pack(anchor="w", padx=20, pady=(6, 0))

        dugmeler = ctk.CTkFrame(govde, fg_color="transparent")
        dugmeler.pack(fill="x", padx=20, pady=(10, 18))
        ctk.CTkButton(
            dugmeler, text="İptal", width=100, height=36, command=self.iptal,
            fg_color=_renk("yuzey2"), hover_color=_renk("kenar"),
            text_color=_renk("metin"),
        ).pack(side="right")
        ctk.CTkButton(
            dugmeler, text="Onayla", width=110, height=36, command=self.onayla,
            fg_color=_renk("vurgu"), hover_color=_renk("vurgu_koyu"),
        ).pack(side="right", padx=(0, 8))

        self.icerige_uydur()
        self.after(200, self.giris.focus_set)

    def onayla(self) -> None:
        if self.veritabani.sifre_dogru_mu(self.giris.get()):
            self.sonuc = True
            self._kapat()
        else:
            self.uyari.configure(text="Şifre hatalı. Lütfen tekrar deneyin.")
            self.giris.delete(0, "end")
            self.giris.focus_set()


class KayitDialog(Modal):
    """Yeni kayıt ekleme / mevcut kaydı düzenleme formu.

    Durum alanı SALT OKUNURDUR: Süre Sonu yazıldıkça anlık olarak
    yeniden hesaplanır ve rengiyle birlikte gösterilir.
    """

    def __init__(self, ana, kayit: dict | None = None):
        duzenleme = kayit is not None
        baslik = "Kaydı Düzenle" if duzenleme else "Yeni Kayıt"
        super().__init__(ana, baslik, 580, 670)
        self.kayit = kayit or {}

        govde = ctk.CTkFrame(self, fg_color=_renk("yuzey"), corner_radius=12)
        govde.pack(fill="both", expand=True, padx=16, pady=16)
        govde.grid_columnconfigure(0, weight=1)
        govde.grid_rowconfigure(1, weight=1)

        # --- Başlık ---
        baslik_kutusu = ctk.CTkFrame(govde, fg_color="transparent")
        baslik_kutusu.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 0))
        ctk.CTkLabel(
            baslik_kutusu, text=baslik, font=ctk.CTkFont(size=19, weight="bold"),
            text_color=_renk("metin"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            baslik_kutusu,
            text=("Kaydı güncelledikten sonra Durum otomatik yenilenir."
                  if duzenleme else
                  "Zorunlu alan yoktur; en az bir alanı doldurmanız yeterlidir."),
            font=ctk.CTkFont(size=12), text_color=_renk("metin_soluk"),
        ).pack(anchor="w", pady=(2, 0))

        # --- Alanlar (iki sütunlu ızgara) ---
        alanlar = ctk.CTkFrame(govde, fg_color="transparent")
        alanlar.grid(row=1, column=0, sticky="nsew", padx=22, pady=(18, 0))
        alanlar.grid_columnconfigure((0, 1), weight=1, uniform="alan")

        self.girisler: dict[str, ctk.CTkEntry] = {}

        def alan_ekle(anahtar, etiket, ipucu, satir, sutun=0, genislik=1):
            """Etiket + giriş kutusu ikilisini ızgaraya yerleştirir."""
            kutu = ctk.CTkFrame(alanlar, fg_color="transparent")
            kutu.grid(row=satir, column=sutun, columnspan=genislik, sticky="ew",
                      padx=((0, 6) if sutun == 0 and genislik == 1 else
                            (6, 0) if sutun == 1 else (0, 0)),
                      pady=(0, 12))
            kutu.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                kutu, text=etiket, font=ctk.CTkFont(size=12, weight="bold"),
                text_color=_renk("metin_soluk"), anchor="w",
            ).grid(row=0, column=0, sticky="w", pady=(0, 3))
            giris = ctk.CTkEntry(
                kutu, height=36, placeholder_text=ipucu,
                border_color=_renk("kenar"), fg_color=_renk("yuzey2"),
                text_color=_renk("metin"),
            )
            giris.grid(row=1, column=0, sticky="ew")
            giris.insert(0, str(self.kayit.get(anahtar, "") or ""))
            self.girisler[anahtar] = giris
            return giris

        alan_ekle("dosya_no", "Dosya No", "örn. 26-12440", 0, 0)
        alan_ekle("firma", "Firma", "örn. AKSA", 0, 1)
        alan_ekle("beyanname_no", "Beyanname No", "örn. 26061500IM00000499", 1, 0, 2)
        alan_ekle("rejim", "Rejim", "örn. 5300", 2, 0)
        alan_ekle("sure_sonu", "Süre Sonu", "YYYY-AA-GG  (boş bırakılabilir)", 2, 1)

        # Süre Sonu değiştikçe Durum anlık hesaplanır
        self.girisler["sure_sonu"].bind("<KeyRelease>", lambda _e: self._durumu_yenile())
        self.girisler["sure_sonu"].bind("<FocusOut>", lambda _e: self._durumu_yenile())

        # --- Durum (SALT OKUNUR) ---
        durum_kutusu = ctk.CTkFrame(alanlar, fg_color="transparent")
        durum_kutusu.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        durum_kutusu.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            durum_kutusu, text="Durum  ·  otomatik hesaplanır, elle düzenlenemez",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=_renk("metin_soluk"), anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 3))
        self.durum_etiketi = ctk.CTkLabel(
            durum_kutusu, text="—", height=38, corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w",
        )
        self.durum_etiketi.grid(row=1, column=0, sticky="ew")

        alan_ekle("aciklama", "Açıklama", "serbest metin", 4, 0, 2)
        alan_ekle("teminat", "Teminat", "örn. 125.000 TL", 5, 0, 2)

        # --- Alt düğmeler ---
        dugmeler = ctk.CTkFrame(govde, fg_color="transparent")
        dugmeler.grid(row=2, column=0, sticky="ew", padx=22, pady=(6, 18))
        ctk.CTkButton(
            dugmeler, text="İptal", width=110, height=38, command=self.iptal,
            fg_color=_renk("yuzey2"), hover_color=_renk("kenar"),
            text_color=_renk("metin"),
        ).pack(side="right")
        ctk.CTkButton(
            dugmeler, text="Kaydet", width=130, height=38, command=self.kaydet,
            fg_color=_renk("vurgu"), hover_color=_renk("vurgu_koyu"),
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="right", padx=(0, 8))

        self.bind("<Control-Return>", lambda _e: self.kaydet())
        self._durumu_yenile()
        self.icerige_uydur()
        self.after(220, self.girisler["dosya_no"].focus_set)

    # ------------------------------------------------------------------ yardımcı
    def _durumu_yenile(self) -> None:
        """Süre Sonu kutusundaki değere göre Durum önizlemesini günceller."""
        ham = self.girisler["sure_sonu"].get().strip()
        tarih = tarih_ayikla(ham)
        if ham and tarih is None:
            self.durum_etiketi.configure(
                text="  Tarih okunamadı — YYYY-AA-GG biçiminde yazın",
                fg_color=_renk("yuzey2"), text_color=_renk("tehlike"),
            )
            return
        durum = durum_hesapla(tarih)
        kalan = kalan_gun(tarih)
        acik_bg, koyu_bg, acik_yazi, koyu_yazi = DURUM_RENKLERI[durum]
        metin = f"  {durum}" if durum else "  (Süre Sonu boş — durum hesaplanmaz)"
        if kalan is not None:
            metin += f"   ·   {kalan} gün" if kalan >= 0 else f"   ·   {abs(kalan)} gün geçti"
        self.durum_etiketi.configure(
            text=metin, fg_color=(acik_bg, koyu_bg), text_color=(acik_yazi, koyu_yazi)
        )

    def kaydet(self) -> None:
        veri = {a: g.get().strip() for a, g in self.girisler.items()}
        ham_tarih = veri["sure_sonu"]
        tarih = tarih_ayikla(ham_tarih)
        if ham_tarih and tarih is None:
            messagebox.showwarning(
                "Geçersiz tarih",
                "Süre Sonu 'YYYY-AA-GG' biçiminde olmalıdır.\n"
                "Örnek: 2026-10-08\n\n(Alanı boş bırakabilirsiniz.)",
                parent=self,
            )
            self.girisler["sure_sonu"].focus_set()
            return
        veri["sure_sonu"] = tarih_metin(tarih)
        if not any(veri[a] for a in ("dosya_no", "firma", "beyanname_no", "sure_sonu")):
            messagebox.showwarning(
                "Boş kayıt",
                "En az Dosya No, Firma, Beyanname No veya Süre Sonu alanlarından "
                "birini doldurmalısınız.",
                parent=self,
            )
            return
        self.sonuc = veri
        self._kapat()


class AyarlarDialog(Modal):
    """Yönetici şifresini ve kilit davranışını değiştirme penceresi."""

    def __init__(self, ana, veritabani: Veritabani):
        super().__init__(ana, "Ayarlar", 500, 570)
        self.veritabani = veritabani

        govde = ctk.CTkFrame(self, fg_color=_renk("yuzey"), corner_radius=12)
        govde.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            govde, text="Ayarlar", font=ctk.CTkFont(size=18, weight="bold"),
            text_color=_renk("metin"),
        ).pack(anchor="w", padx=22, pady=(18, 14))

        # --- Şifre değiştirme ---
        ctk.CTkLabel(
            govde, text="YÖNETİCİ ŞİFRESİNİ DEĞİŞTİR",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=_renk("metin_soluk"),
        ).pack(anchor="w", padx=22)

        self.mevcut = self._sifre_kutusu(govde, "Mevcut şifre")
        self.yeni = self._sifre_kutusu(govde, "Yeni şifre (en az 4 karakter)")
        self.tekrar = self._sifre_kutusu(govde, "Yeni şifre (tekrar)")

        ctk.CTkButton(
            govde, text="Şifreyi Güncelle", height=36, command=self.sifreyi_guncelle,
            fg_color=_renk("vurgu"), hover_color=_renk("vurgu_koyu"),
        ).pack(fill="x", padx=22, pady=(12, 4))

        # --- Kilit süresi ---
        ctk.CTkLabel(
            govde, text="YÖNETİCİ OTURUMU",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=_renk("metin_soluk"),
        ).pack(anchor="w", padx=22, pady=(16, 4))
        ctk.CTkLabel(
            govde,
            text=("Şifre girildikten sonra yöneticinin ne kadar süre açık kalacağı.\n"
                  "\"Her işlemde sor\" en güvenli seçenektir."),
            font=ctk.CTkFont(size=12), text_color=_renk("metin_soluk"), justify="left",
        ).pack(anchor="w", padx=22)

        mevcut_dk = self.veritabani.ayar_al("oturum_dakika", "0")
        self._sure_secenekleri = {
            "Her işlemde sor": "0", "5 dakika": "5",
            "15 dakika": "15", "60 dakika": "60",
        }
        ters = {v: k for k, v in self._sure_secenekleri.items()}
        self.sure_kutusu = ctk.CTkOptionMenu(
            govde, values=list(self._sure_secenekleri.keys()),
            command=self._sure_degisti, height=34,
            fg_color=_renk("yuzey2"), button_color=_renk("kenar"),
            button_hover_color=_renk("vurgu"), text_color=_renk("metin"),
        )
        self.sure_kutusu.set(ters.get(str(mevcut_dk), "Her işlemde sor"))
        self.sure_kutusu.pack(fill="x", padx=22, pady=(8, 0))

        # --- Veritabanı yolu ---
        ctk.CTkLabel(
            govde, text=f"Veritabanı:  {self.veritabani.yol}",
            font=ctk.CTkFont(size=11), text_color=_renk("metin_soluk"),
            wraplength=430, justify="left",
        ).pack(anchor="w", padx=22, pady=(18, 0))

        ctk.CTkButton(
            govde, text="Kapat", height=36, width=110, command=self.iptal,
            fg_color=_renk("yuzey2"), hover_color=_renk("kenar"),
            text_color=_renk("metin"),
        ).pack(side="bottom", anchor="e", padx=22, pady=16)

        self.icerige_uydur()

    def _sifre_kutusu(self, ana, ipucu: str) -> ctk.CTkEntry:
        giris = ctk.CTkEntry(
            ana, show="●", placeholder_text=ipucu, height=36,
            border_color=_renk("kenar"), fg_color=_renk("yuzey2"),
            text_color=_renk("metin"),
        )
        giris.pack(fill="x", padx=22, pady=(8, 0))
        return giris

    def _sure_degisti(self, secim: str) -> None:
        self.veritabani.ayar_yaz("oturum_dakika", self._sure_secenekleri[secim])
        self.sonuc = "degisti"

    def sifreyi_guncelle(self) -> None:
        if not self.veritabani.sifre_dogru_mu(self.mevcut.get()):
            messagebox.showerror("Hata", "Mevcut şifre yanlış.", parent=self)
            return
        yeni = self.yeni.get()
        if len(yeni) < 4:
            messagebox.showwarning("Hata", "Yeni şifre en az 4 karakter olmalıdır.", parent=self)
            return
        if yeni != self.tekrar.get():
            messagebox.showwarning("Hata", "Yeni şifreler birbiriyle uyuşmuyor.", parent=self)
            return
        self.veritabani.sifre_degistir(yeni)
        for kutu in (self.mevcut, self.yeni, self.tekrar):
            kutu.delete(0, "end")
        messagebox.showinfo("Tamam", "Yönetici şifresi güncellendi.", parent=self)


# =========================================================================
#  7. BÖLÜM — ANA PENCERE
# =========================================================================

TABLO_STILI = "Takip.Treeview"


def _map_temizle(stil, stil_adi: str, secenek: str):
    """Tk 8.6.9+ hata düzeltmesi.

    Bu sürümlerde ttk'nin varsayılan durum eşlemesi, Treeview satır
    etiketlerine (tag) verilen renkleri yok sayar. ("!disabled", "!selected")
    girdilerini eşlemeden çıkarmak sorunu giderir — Durum renklerinin
    görünmesi buna bağlıdır.
    """
    return [
        girdi for girdi in stil.map(stil_adi, query_opt=secenek)
        if girdi[:2] != ("!disabled", "!selected")
    ]


class Uygulama(ctk.CTk):
    """Süre Takip ana penceresi."""

    def __init__(self, veritabani: Veritabani):
        super().__init__()
        self.veritabani = veritabani
        self.kayitlar: list[dict] = []          # ekranda görünen (filtrelenmiş) kayıtlar
        self.yonetici_bitis: datetime | None = None   # yönetici oturumunun bitiş anı
        self._sirala_sutun = "sure_sonu"
        self._sirala_ters = False

        self.title(f"{UYGULAMA_ADI} — Geçici İthalat / Rejim Süre Takibi")
        self.geometry("1380x800")
        self.minsize(1060, 620)
        self.configure(fg_color=_renk("arkaplan"))

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._ust_serit()
        self._arac_cubugu()
        self._tablo()
        self._alt_serit()
        self._kisayollar()

        self._ttk_stili()
        self.yenile()
        self._gun_donumu_zamanlayici()

    # ================================================================== ÜST ŞERİT
    def _ust_serit(self) -> None:
        serit = ctk.CTkFrame(self, fg_color=_renk("yuzey"), corner_radius=0, height=92)
        serit.grid(row=0, column=0, sticky="ew")
        serit.grid_columnconfigure(1, weight=1)
        serit.grid_propagate(False)

        baslik_kutusu = ctk.CTkFrame(serit, fg_color="transparent")
        baslik_kutusu.grid(row=0, column=0, sticky="w", padx=(22, 0), pady=14)
        ctk.CTkLabel(
            baslik_kutusu, text=UYGULAMA_ADI,
            font=ctk.CTkFont(size=24, weight="bold"), text_color=_renk("metin"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            baslik_kutusu,
            text=f"Geçici İthalat / Rejim Süre Takibi  ·  Bugün: {date.today():%d.%m.%Y}",
            font=ctk.CTkFont(size=12), text_color=_renk("metin_soluk"),
        ).pack(anchor="w")

        # --- Özet kartları (tıklanınca ilgili duruma göre filtreler) ---
        kartlar = ctk.CTkFrame(serit, fg_color="transparent")
        kartlar.grid(row=0, column=2, sticky="e", padx=(0, 20), pady=12)
        self.ozet_etiketleri: dict[str, ctk.CTkLabel] = {}

        kart_tanimlari = [
            ("Toplam", "TOPLAM", _renk("metin")),
            ("Normal", DURUM_NORMAL, ("#14663c", "#7ee2a8")),
            ("Dikkat", DURUM_DIKKAT, ("#8a6100", "#ffd666")),
            ("Önemli", DURUM_ONEMLI, ("#a04b00", "#ffb066")),
            ("Tehlikeli", DURUM_TEHLIKELI, ("#9c2a12", "#ff9478")),
            ("Süre Geçti", DURUM_GECTI, ("#96121c", "#ff8a94")),
        ]
        for sutun, (etiket, durum, renk) in enumerate(kart_tanimlari):
            kart = ctk.CTkFrame(kartlar, fg_color=_renk("yuzey2"), corner_radius=10,
                                width=118, height=62)
            kart.grid(row=0, column=sutun, padx=4)
            kart.grid_propagate(False)
            sayi = ctk.CTkLabel(kart, text="0", font=ctk.CTkFont(size=20, weight="bold"),
                                text_color=renk)
            sayi.place(relx=0.5, y=20, anchor="center")
            ad = ctk.CTkLabel(kart, text=etiket, font=ctk.CTkFont(size=11),
                              text_color=_renk("metin_soluk"))
            ad.place(relx=0.5, y=45, anchor="center")
            self.ozet_etiketleri[durum] = sayi
            # Kartın kendisi ve içindeki etiketler tıklanabilir olsun
            for parca in (kart, sayi, ad):
                parca.bind("<Button-1>", lambda _e, d=durum: self._karta_tiklandi(d))
                parca.configure(cursor="hand2")

    def _karta_tiklandi(self, durum: str) -> None:
        """Özet kartına tıklanınca durum filtresini ayarlar."""
        self.durum_filtresi.set("Tümü" if durum == "TOPLAM" else (durum or "(Boş)"))
        self.yenile()

    # ================================================================ ARAÇ ÇUBUĞU
    def _arac_cubugu(self) -> None:
        cubuk = ctk.CTkFrame(self, fg_color=_renk("arkaplan"), corner_radius=0)
        cubuk.grid(row=1, column=0, sticky="ew", padx=18, pady=(12, 8))
        cubuk.grid_columnconfigure(0, weight=1)

        # --- 1. satır: arama ve filtreler ---
        ust = ctk.CTkFrame(cubuk, fg_color="transparent")
        ust.grid(row=0, column=0, sticky="ew")
        ust.grid_columnconfigure(0, weight=1)

        self.arama = ctk.CTkEntry(
            ust, height=40, font=ctk.CTkFont(size=13),
            placeholder_text="Ara:  Firma, Beyanname No veya Dosya No…",
            border_color=_renk("kenar"), fg_color=_renk("yuzey"),
            text_color=_renk("metin"),
        )
        self.arama.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.arama.bind("<KeyRelease>", lambda _e: self.yenile())   # anlık filtreleme

        self.durum_filtresi = ctk.StringVar(value="Tümü")
        self.durum_kutusu = ctk.CTkOptionMenu(
            ust, variable=self.durum_filtresi, width=210, height=40,
            values=["Tümü"] + [d if d else "(Boş)" for d in DURUM_SIRASI],
            command=lambda _s: self.yenile(),
            fg_color=_renk("yuzey"), button_color=_renk("kenar"),
            button_hover_color=_renk("vurgu"), text_color=_renk("metin"),
            font=ctk.CTkFont(size=12),
        )
        self.durum_kutusu.grid(row=0, column=1, padx=4)

        self.rejim_filtresi = ctk.StringVar(value="Tüm rejimler")
        self.rejim_kutusu = ctk.CTkOptionMenu(
            ust, variable=self.rejim_filtresi, width=140, height=40,
            values=["Tüm rejimler"], command=lambda _s: self.yenile(),
            fg_color=_renk("yuzey"), button_color=_renk("kenar"),
            button_hover_color=_renk("vurgu"), text_color=_renk("metin"),
            font=ctk.CTkFont(size=12),
        )
        self.rejim_kutusu.grid(row=0, column=2, padx=4)

        ctk.CTkButton(
            ust, text="Temizle", width=90, height=40, command=self.filtreleri_temizle,
            fg_color=_renk("yuzey"), hover_color=_renk("kenar"),
            text_color=_renk("metin_soluk"),
        ).grid(row=0, column=3, padx=4)

        self.tema_secici = ctk.CTkSegmentedButton(
            ust, values=["Açık", "Koyu"], width=140, height=40,
            command=self.tema_degistir,
            selected_color=_renk("vurgu"), selected_hover_color=_renk("vurgu_koyu"),
            fg_color=_renk("yuzey"), unselected_color=_renk("yuzey"),
            unselected_hover_color=_renk("kenar"), font=ctk.CTkFont(size=12),
        )
        self.tema_secici.set("Koyu" if _tema_indeksi() else "Açık")
        self.tema_secici.grid(row=0, column=4, padx=(8, 0))

        # --- 2. satır: işlem düğmeleri ---
        alt = ctk.CTkFrame(cubuk, fg_color="transparent")
        alt.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        def dugme(ana, metin, komut, **secenekler):
            varsayilan = dict(
                height=38, corner_radius=8, font=ctk.CTkFont(size=13),
                fg_color=_renk("yuzey"), hover_color=_renk("kenar"),
                text_color=_renk("metin"),
            )
            varsayilan.update(secenekler)
            btn = ctk.CTkButton(ana, text=metin, command=komut, **varsayilan)
            btn.pack(side="left", padx=(0, 8))
            return btn

        dugme(alt, "+  Yeni Kayıt", self.yeni_kayit, width=140,
              fg_color=_renk("vurgu"), hover_color=_renk("vurgu_koyu"),
              text_color="#ffffff", font=ctk.CTkFont(size=13, weight="bold"))
        dugme(alt, "Düzenle", self.duzenle, width=110)
        dugme(alt, "Sil", self.sil, width=90,
              hover_color=_renk("tehlike"), text_color=_renk("tehlike"))

        ctk.CTkLabel(alt, text="│", text_color=_renk("kenar")).pack(side="left", padx=6)

        dugme(alt, "Excel'den İçe Aktar", self.excelden_aktar, width=170)
        dugme(alt, "Excel'e Aktar", self.excele_aktar, width=140)

        ctk.CTkLabel(alt, text="│", text_color=_renk("kenar")).pack(side="left", padx=6)

        dugme(alt, "Yenile", self.yenile, width=90)
        dugme(alt, "Ayarlar", self.ayarlar_ac, width=100)

        self.kilit_dugmesi = ctk.CTkButton(
            alt, text="Yönetici: Kilitli", width=150, height=38, corner_radius=8,
            command=self.kilidi_degistir, font=ctk.CTkFont(size=12),
            fg_color=_renk("yuzey"), hover_color=_renk("kenar"),
            text_color=_renk("metin_soluk"),
        )
        self.kilit_dugmesi.pack(side="right")

    # ======================================================================= TABLO
    def _tablo(self) -> None:
        cerceve = ctk.CTkFrame(self, fg_color=_renk("yuzey"), corner_radius=12)
        cerceve.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 8))
        cerceve.grid_columnconfigure(0, weight=1)
        cerceve.grid_rowconfigure(0, weight=1)

        anahtarlar = [a for a, *_ in TABLO_SUTUNLARI]
        self.tablo = ttk.Treeview(
            cerceve, columns=anahtarlar, show="headings",
            style=TABLO_STILI, selectmode="browse",
        )
        for anahtar, baslik, genislik, hizalama in TABLO_SUTUNLARI:
            self.tablo.heading(
                anahtar, text=baslik, anchor="w",
                command=lambda a=anahtar: self._sutuna_gore_sirala(a),
            )
            self.tablo.column(anahtar, width=genislik, minwidth=60,
                              anchor=hizalama, stretch=(anahtar in ("firma", "aciklama")))
        self.tablo.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)

        dikey = ctk.CTkScrollbar(cerceve, command=self.tablo.yview,
                                 button_color=_renk("kenar"),
                                 button_hover_color=_renk("metin_soluk"))
        dikey.grid(row=0, column=1, sticky="ns", padx=(2, 8), pady=10)
        yatay = ctk.CTkScrollbar(cerceve, orientation="horizontal",
                                 command=self.tablo.xview,
                                 button_color=_renk("kenar"),
                                 button_hover_color=_renk("metin_soluk"))
        yatay.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)

        # Çift tıklama = düzenle (şifre ister)
        self.tablo.bind("<Double-1>", lambda _e: self.duzenle())

    # =================================================================== ALT ŞERİT
    def _alt_serit(self) -> None:
        serit = ctk.CTkFrame(self, fg_color=_renk("yuzey"), corner_radius=0, height=34)
        serit.grid(row=3, column=0, sticky="ew")
        serit.grid_propagate(False)
        serit.grid_columnconfigure(1, weight=1)

        self.sayac_etiketi = ctk.CTkLabel(
            serit, text="", font=ctk.CTkFont(size=12), text_color=_renk("metin_soluk")
        )
        self.sayac_etiketi.grid(row=0, column=0, sticky="w", padx=20)

        ctk.CTkLabel(
            serit, text=f"Veritabanı: {self.veritabani.yol}",
            font=ctk.CTkFont(size=11), text_color=_renk("metin_soluk"),
        ).grid(row=0, column=1, sticky="e", padx=(0, 16))

        ctk.CTkLabel(
            serit, text=f"{UYGULAMA_ADI} v{SURUM}",
            font=ctk.CTkFont(size=11), text_color=_renk("metin_soluk"),
        ).grid(row=0, column=2, sticky="e", padx=(0, 20))

    def _kisayollar(self) -> None:
        """Klavye kısayolları."""
        self.bind("<Control-n>", lambda _e: self.yeni_kayit())
        self.bind("<Control-f>", lambda _e: self.arama.focus_set())
        self.bind("<Control-e>", lambda _e: self.excele_aktar())
        self.bind("<F5>", lambda _e: self.yenile())
        self.bind("<Delete>", lambda _e: self.sil())
        self.protocol("WM_DELETE_WINDOW", self.kapat)

    # ================================================================ TEMA / STİL
    def _ttk_stili(self) -> None:
        """ttk.Treeview'i CustomTkinter temasıyla uyumlu hâle getirir."""
        stil = ttk.Style(self)
        try:
            stil.theme_use("clam")     # renklerin uygulanabilmesi için gerekli
        except tk.TclError:
            pass

        yuzey = _tek_renk("yuzey")
        metin = _tek_renk("metin")
        kenar = _tek_renk("kenar")
        vurgu = _tek_renk("vurgu")

        stil.configure(
            TABLO_STILI, background=yuzey, fieldbackground=yuzey, foreground=metin,
            rowheight=32, borderwidth=0, font=("Segoe UI", 10),
        )
        stil.configure(
            f"{TABLO_STILI}.Heading", background=_tek_renk("yuzey2"),
            foreground=_tek_renk("metin_soluk"), relief="flat", borderwidth=0,
            padding=(8, 10), font=("Segoe UI", 10, "bold"),
        )
        stil.map(f"{TABLO_STILI}.Heading",
                 background=[("active", kenar)], foreground=[("active", metin)])
        stil.map(TABLO_STILI,
                 background=[("selected", vurgu)], foreground=[("selected", "#ffffff")])
        # Tk 8.6.9+ etiket rengi hatasının düzeltmesi (bkz. _map_temizle)
        stil.map(TABLO_STILI,
                 background=_map_temizle(stil, TABLO_STILI, "background"),
                 foreground=_map_temizle(stil, TABLO_STILI, "foreground"))
        stil.map(TABLO_STILI, background=[("selected", vurgu)],
                 foreground=[("selected", "#ffffff")])

        # Durum satır renkleri
        indis = _tema_indeksi()
        for durum, (acik_bg, koyu_bg, acik_yazi, koyu_yazi) in DURUM_RENKLERI.items():
            self.tablo.tag_configure(
                self._etiket_adi(durum),
                background=(koyu_bg if indis else acik_bg),
                foreground=(koyu_yazi if indis else acik_yazi),
            )

    @staticmethod
    def _etiket_adi(durum: str) -> str:
        """Durum metnini Treeview etiket adına çevirir."""
        return "durum_bos" if not durum else "durum_" + str(DURUM_AGIRLIK.get(durum, 9))

    def tema_degistir(self, secim: str) -> None:
        ctk.set_appearance_mode("dark" if secim == "Koyu" else "light")
        self.veritabani.ayar_yaz("tema", secim)
        self._ttk_stili()     # ttk renkleri otomatik değişmez, elle yenilenir
        self.yenile()

    # =================================================================== VERİ AKIŞI
    def yenile(self, *_args) -> None:
        """Veritabanını okur, filtreleri uygular ve tabloyu yeniden çizer."""
        bugun = date.today()
        tum_kayitlar = self.veritabani.tum_kayitlar(bugun)

        # Rejim filtresi seçeneklerini güncel tut
        rejimler = sorted({k["rejim"] for k in tum_kayitlar if k["rejim"]})
        secenekler = ["Tüm rejimler"] + rejimler
        if self.rejim_kutusu.cget("values") != secenekler:
            mevcut = self.rejim_filtresi.get()
            self.rejim_kutusu.configure(values=secenekler)
            if mevcut not in secenekler:
                self.rejim_filtresi.set("Tüm rejimler")

        self.kayitlar = self._filtrele(tum_kayitlar)
        self._sirala()
        self._tabloyu_ciz()
        self._ozetleri_guncelle(tum_kayitlar)

        toplam = len(tum_kayitlar)
        gorunen = len(self.kayitlar)
        metin = (f"{gorunen} kayıt gösteriliyor" if gorunen == toplam
                 else f"{gorunen} / {toplam} kayıt gösteriliyor  (filtre etkin)")
        self.sayac_etiketi.configure(text=metin)
        self._kilit_gorunumu()

    def _filtrele(self, kayitlar: list[dict]) -> list[dict]:
        """Arama metni, durum ve rejim filtrelerini uygular."""
        arama = tr_sadelestir(self.arama.get())
        durum_secimi = self.durum_filtresi.get()
        rejim_secimi = self.rejim_filtresi.get()

        sonuc = []
        for kayit in kayitlar:
            # Arama: Firma, Beyanname No, Dosya No (istenen üç alan)
            if arama:
                havuz = " ".join(tr_sadelestir(kayit[alan]) for alan in
                                 ("firma", "beyanname_no", "dosya_no"))
                if arama not in havuz:
                    continue
            if durum_secimi != "Tümü":
                beklenen = "" if durum_secimi == "(Boş)" else durum_secimi
                if kayit["durum"] != beklenen:
                    continue
            if rejim_secimi != "Tüm rejimler" and kayit["rejim"] != rejim_secimi:
                continue
            sonuc.append(kayit)
        return sonuc

    def _sirala(self) -> None:
        """Seçili sütuna göre görünen kayıtları sıralar."""
        anahtar = self._sirala_sutun

        def sira_degeri(kayit):
            if anahtar == "durum":
                # Önem sırasına göre: önce süresi geçenler
                return (DURUM_AGIRLIK.get(kayit["durum"], 9),)
            if anahtar in ("sure_sonu", "kalan"):
                tarih = kayit["sure_sonu_tarih"]
                # Tarihi olmayan kayıtlar her zaman sona
                return (tarih is None, tarih or date.min)
            if anahtar == "rejim":
                ham = kayit["rejim"]
                return (ham == "", int(ham) if ham.isdigit() else 0, tr_sadelestir(ham))
            return (tr_sadelestir(kayit.get(anahtar, "")),)

        self.kayitlar.sort(key=sira_degeri, reverse=self._sirala_ters)

    def _sutuna_gore_sirala(self, anahtar: str) -> None:
        if self._sirala_sutun == anahtar:
            self._sirala_ters = not self._sirala_ters
        else:
            self._sirala_sutun, self._sirala_ters = anahtar, False
        # Başlıklara sıralama okunu yaz
        for a, baslik, *_ in TABLO_SUTUNLARI:
            ok = "  ▼" if self._sirala_ters else "  ▲"
            self.tablo.heading(a, text=baslik + (ok if a == anahtar else ""))
        self.yenile()

    def _tabloyu_ciz(self) -> None:
        secili = self.secili_id()
        self.tablo.delete(*self.tablo.get_children())
        for kayit in self.kayitlar:
            kalan = kayit["kalan"]
            self.tablo.insert(
                "", "end", iid=str(kayit["id"]),
                values=(
                    kayit["dosya_no"],
                    kayit["firma"],
                    kayit["beyanname_no"],
                    kayit["rejim"],
                    kayit["sure_sonu"],
                    "" if kalan is None else str(kalan),
                    kayit["durum"],
                    kayit["aciklama"],
                    kayit["teminat"],
                ),
                tags=(self._etiket_adi(kayit["durum"]),),
            )
        # Yenilemeden sonra seçimi koru
        if secili and self.tablo.exists(str(secili)):
            self.tablo.selection_set(str(secili))
            self.tablo.see(str(secili))

    def _ozetleri_guncelle(self, tum_kayitlar: list[dict]) -> None:
        sayimlar = {durum: 0 for durum in DURUM_RENKLERI}
        for kayit in tum_kayitlar:
            sayimlar[kayit["durum"]] = sayimlar.get(kayit["durum"], 0) + 1
        for durum, etiket in self.ozet_etiketleri.items():
            deger = len(tum_kayitlar) if durum == "TOPLAM" else sayimlar.get(durum, 0)
            etiket.configure(text=str(deger))

    def _gun_donumu_zamanlayici(self) -> None:
        """Uygulama açık kalsa bile Durum'un güncel kalması için düzenli yenileme."""
        self.after(30 * 60 * 1000, self._periyodik_yenile)

    def _periyodik_yenile(self) -> None:
        self.yenile()
        self._gun_donumu_zamanlayici()

    # ================================================================== YETKİ / KİLİT
    def secili_id(self) -> int | None:
        """Tabloda seçili kaydın kimliği (yoksa None)."""
        secim = self.tablo.selection()
        return int(secim[0]) if secim else None

    def _yonetici_acik_mi(self) -> bool:
        """Yönetici oturumu hâlâ geçerli mi?"""
        return self.yonetici_bitis is not None and datetime.now() < self.yonetici_bitis

    def _kilit_gorunumu(self) -> None:
        """Kilit düğmesinin metnini ve rengini duruma göre günceller."""
        if self._yonetici_acik_mi():
            kalan_dk = max(int((self.yonetici_bitis - datetime.now()).total_seconds() // 60), 0)
            self.kilit_dugmesi.configure(
                text=f"Yönetici: Açık ({kalan_dk} dk)",
                text_color=_renk("basari"), hover_color=_renk("kenar"),
            )
        else:
            self.kilit_dugmesi.configure(
                text="Yönetici: Kilitli", text_color=_renk("metin_soluk"),
                hover_color=_renk("kenar"),
            )

    def yonetici_dogrula(self, aciklama: str) -> bool:
        """Düzenleme/silme öncesi şifre kontrolü.

        Ayarlarda bir oturum süresi tanımlıysa, şifre bir kez girildikten sonra
        o süre boyunca tekrar sorulmaz. Varsayılan ayar (0 dakika) her işlemde
        şifre sorulmasıdır.
        """
        if self._yonetici_acik_mi():
            return True
        onay = SifreDialog(self, self.veritabani, aciklama).bekle()
        if not onay:
            return False
        try:
            dakika = int(self.veritabani.ayar_al("oturum_dakika", "0") or 0)
        except ValueError:
            dakika = 0
        self.yonetici_bitis = (datetime.now() + timedelta(minutes=dakika)) if dakika > 0 else None
        self._kilit_gorunumu()
        return True

    def kilidi_degistir(self) -> None:
        """Kilit düğmesi: açıksa kilitler, kilitliyse şifre sorar."""
        if self._yonetici_acik_mi():
            self.yonetici_bitis = None
            self._kilit_gorunumu()
            return
        self.yonetici_dogrula("Yönetici oturumunu açmak için şifrenizi girin.")

    # ===================================================================== İŞLEMLER
    def yeni_kayit(self) -> None:
        """Yeni kayıt ekler — şifre GEREKTİRMEZ (herkes ekleyebilir)."""
        veri = KayitDialog(self).bekle()
        if not veri:
            return
        yeni_id = self.veritabani.kayit_ekle(veri)
        self.yenile()
        if self.tablo.exists(str(yeni_id)):
            self.tablo.selection_set(str(yeni_id))
            self.tablo.see(str(yeni_id))

    def duzenle(self) -> None:
        """Mevcut kaydı düzenler — önce yönetici şifresi sorulur."""
        kayit_id = self.secili_id()
        if kayit_id is None:
            messagebox.showinfo("Kayıt seçilmedi",
                                "Lütfen düzenlemek istediğiniz satırı seçin.", parent=self)
            return
        kayit = self.veritabani.kayit_getir(kayit_id)
        if kayit is None:
            self.yenile()
            return
        if not self.yonetici_dogrula(
            f"“{kayit['dosya_no'] or kayit['firma'] or kayit['beyanname_no']}” kaydını "
            f"düzenlemek için yönetici şifresi gerekiyor."
        ):
            return
        veri = KayitDialog(self, kayit).bekle()
        if not veri:
            return
        self.veritabani.kayit_guncelle(kayit_id, veri)
        self.yenile()

    def sil(self) -> None:
        """Kaydı siler — önce yönetici şifresi, sonra onay sorulur."""
        kayit_id = self.secili_id()
        if kayit_id is None:
            messagebox.showinfo("Kayıt seçilmedi",
                                "Lütfen silmek istediğiniz satırı seçin.", parent=self)
            return
        kayit = self.veritabani.kayit_getir(kayit_id)
        if kayit is None:
            self.yenile()
            return
        tanim = kayit["dosya_no"] or kayit["firma"] or kayit["beyanname_no"] or f"#{kayit_id}"
        if not self.yonetici_dogrula(f"“{tanim}” kaydını silmek için yönetici şifresi gerekiyor."):
            return
        if not messagebox.askyesno(
            "Kaydı sil",
            f"Bu kayıt kalıcı olarak silinecek:\n\n"
            f"Dosya No: {kayit['dosya_no'] or '—'}\n"
            f"Firma: {kayit['firma'] or '—'}\n"
            f"Beyanname No: {kayit['beyanname_no'] or '—'}\n\n"
            f"Devam edilsin mi?",
            icon="warning", parent=self,
        ):
            return
        self.veritabani.kayit_sil(kayit_id)
        self.yenile()

    def filtreleri_temizle(self) -> None:
        self.arama.delete(0, "end")
        self.durum_filtresi.set("Tümü")
        self.rejim_filtresi.set("Tüm rejimler")
        self.yenile()

    def ayarlar_ac(self) -> None:
        """Ayarlar penceresi — güvenlik ayarları içerdiği için şifre ister."""
        if not self.yonetici_dogrula("Ayarları açmak için yönetici şifresi gerekiyor."):
            return
        AyarlarDialog(self, self.veritabani).bekle()
        self.yenile()

    # ======================================================== EXCEL İÇE / DIŞA AKTARMA
    def excelden_aktar(self) -> None:
        """Bir .xlsx dosyasını okuyup kayıtları veritabanına ekler."""
        yol = filedialog.askopenfilename(
            title="İçe aktarılacak Excel dosyasını seçin",
            filetypes=[("Excel dosyaları", "*.xlsx *.xlsm"), ("Tüm dosyalar", "*.*")],
            parent=self,
        )
        if not yol:
            return
        try:
            gelen, uyarilar = excelden_oku(yol)
        except RuntimeError as hata:            # openpyxl kurulu değil
            messagebox.showerror("Eksik kütüphane", str(hata), parent=self)
            return
        except Exception as hata:               # bozuk/korumalı dosya vb.
            messagebox.showerror(
                "Dosya okunamadı",
                f"Excel dosyası okunurken bir sorun oluştu:\n\n{hata}", parent=self)
            return

        if not gelen:
            messagebox.showwarning(
                "Kayıt bulunamadı",
                "Dosyada tanınabilir bir kayıt bulunamadı.\n\n"
                "Sayfada en az 'Dosya No' ve 'Firma' başlıklarını içeren bir "
                "başlık satırı olmalıdır.", parent=self)
            return

        mevcut_sayi = self.veritabani.kayit_sayisi()
        temizle = False
        if mevcut_sayi:
            cevap = messagebox.askyesnocancel(
                "İçe aktarma biçimi",
                f"Dosyada {len(gelen)} kayıt bulundu. Veritabanında hâlihazırda "
                f"{mevcut_sayi} kayıt var.\n\n"
                f"EVET  →  Mevcut kayıtları sil, dosyadakilerle değiştir\n"
                f"HAYIR →  Mevcutları koru, yalnızca yeni kayıtları ekle\n"
                f"İPTAL →  Vazgeç",
                parent=self,
            )
            if cevap is None:
                return
            temizle = bool(cevap)
            if temizle and not self.yonetici_dogrula(
                f"Mevcut {mevcut_sayi} kaydın silinmesi için yönetici şifresi gerekiyor."
            ):
                return
            if temizle:
                self.veritabani.tumunu_sil()

        eklenen = atlanan = 0
        for kayit in gelen:
            # Aynı Dosya No + Beyanname No ikilisi zaten varsa tekrar eklenmez.
            if not temizle and self.veritabani.ayni_kayit_var_mi(
                kayit["dosya_no"], kayit["beyanname_no"]
            ):
                atlanan += 1
                continue
            self.veritabani.kayit_ekle(kayit)
            eklenen += 1

        self.filtreleri_temizle()

        ozet = f"{eklenen} kayıt içe aktarıldı."
        if atlanan:
            ozet += f"\n{atlanan} kayıt zaten mevcut olduğu için atlandı."
        if uyarilar:
            ilk = "\n".join(f"• {u}" for u in uyarilar[:8])
            ozet += f"\n\nUyarılar ({len(uyarilar)}):\n{ilk}"
            if len(uyarilar) > 8:
                ozet += f"\n… ve {len(uyarilar) - 8} uyarı daha."
        messagebox.showinfo("İçe aktarma tamamlandı", ozet, parent=self)

    def excele_aktar(self) -> None:
        """Kayıtları biçimlendirilmiş bir .xlsx dosyasına yazar."""
        toplam = self.veritabani.tum_kayitlar()
        if not toplam:
            messagebox.showinfo("Kayıt yok", "Dışa aktarılacak kayıt bulunmuyor.", parent=self)
            return

        aktarilacak = toplam
        filtre_etkin = len(self.kayitlar) != len(toplam)
        if filtre_etkin:
            if messagebox.askyesno(
                "Dışa aktarma kapsamı",
                f"Ekranda filtrelenmiş {len(self.kayitlar)} kayıt görünüyor.\n\n"
                f"EVET  →  Yalnızca görünen {len(self.kayitlar)} kaydı aktar\n"
                f"HAYIR →  Tüm {len(toplam)} kaydı aktar",
                parent=self,
            ):
                aktarilacak = self.kayitlar

        yol = filedialog.asksaveasfilename(
            title="Excel dosyasını kaydet",
            defaultextension=".xlsx",
            initialfile=f"sure_takip_{date.today():%Y%m%d}.xlsx",
            filetypes=[("Excel dosyası", "*.xlsx")],
            parent=self,
        )
        if not yol:
            return
        try:
            excele_yaz(yol, aktarilacak)
        except RuntimeError as hata:
            messagebox.showerror("Eksik kütüphane", str(hata), parent=self)
            return
        except PermissionError:
            messagebox.showerror(
                "Dosya açık",
                "Dosya başka bir programda (muhtemelen Excel'de) açık olduğu için "
                "kaydedilemedi.\nDosyayı kapatıp tekrar deneyin.", parent=self)
            return
        except Exception as hata:
            messagebox.showerror("Kaydedilemedi", f"Excel dosyası yazılamadı:\n\n{hata}",
                                 parent=self)
            return
        messagebox.showinfo(
            "Dışa aktarma tamamlandı",
            f"{len(aktarilacak)} kayıt kaydedildi:\n\n{yol}", parent=self)

    # ======================================================================== KAPANIŞ
    def kapat(self) -> None:
        self.veritabani.kapat()
        self.destroy()


# =========================================================================
#  8. BÖLÜM — İŞ KURALI TESTLERİ  (python sure_takip.py --test)
# =========================================================================

def kendini_test_et() -> int:
    """Arayüz açmadan iş kurallarını doğrular. Hata sayısını döndürür."""
    hatalar: list[str] = []
    _konsolu_hazirla()
    # Dar kod sayfalı konsollarda (Windows cmd) ASCII işaretlere düşülür.
    onay, hata_im = ("✓", "✗") if _basilabilir_mi("✓✗ığş") else ("[OK]", "[!!]")

    def kontrol(aciklama: str, elde_edilen, beklenen) -> None:
        if elde_edilen != beklenen:
            hatalar.append(f"  {hata_im} {aciklama}\n      beklenen: {beklenen!r}\n      "
                           f"elde edilen: {elde_edilen!r}")
        else:
            yaz(f"  {onay} {aciklama}")

    bugun = date(2026, 9, 10)
    yaz("Durum hesaplama (referans gün: 2026-09-10)")
    kontrol("Süre Sonu boş -> ''", durum_hesapla(None, bugun), DURUM_BOS)
    kontrol("+31 gün -> NORMAL", durum_hesapla(bugun + timedelta(days=31), bugun), DURUM_NORMAL)
    kontrol("+30 gün -> DİKKAT (sınır)", durum_hesapla(bugun + timedelta(days=30), bugun), DURUM_DIKKAT)
    kontrol("+1 gün  -> DİKKAT", durum_hesapla(bugun + timedelta(days=1), bugun), DURUM_DIKKAT)
    kontrol("bugün   -> DİKKAT (sınır)", durum_hesapla(bugun, bugun), DURUM_DIKKAT)
    kontrol("-1 gün  -> ÖNEMLİ", durum_hesapla(bugun - timedelta(days=1), bugun), DURUM_ONEMLI)
    kontrol("-30 gün -> ÖNEMLİ (sınır)", durum_hesapla(bugun - timedelta(days=30), bugun), DURUM_ONEMLI)
    kontrol("-31 gün -> TEHLİKELİ", durum_hesapla(bugun - timedelta(days=31), bugun), DURUM_TEHLIKELI)
    kontrol("-60 gün -> TEHLİKELİ (sınır)", durum_hesapla(bugun - timedelta(days=60), bugun), DURUM_TEHLIKELI)
    kontrol("-61 gün -> süre geçti", durum_hesapla(bugun - timedelta(days=61), bugun), DURUM_GECTI)

    yaz("\nTarih ayıklama")
    kontrol("'2026-10-08'", tarih_ayikla("2026-10-08"), date(2026, 10, 8))
    kontrol("'08.10.2026'", tarih_ayikla("08.10.2026"), date(2026, 10, 8))
    kontrol("'08/10/2026'", tarih_ayikla("08/10/2026"), date(2026, 10, 8))
    kontrol("datetime", tarih_ayikla(datetime(2026, 10, 8, 13, 5)), date(2026, 10, 8))
    excel_seri = (date(2026, 10, 8) - date(1899, 12, 30)).days   # = 46303
    kontrol(f"Excel seri no {excel_seri}", tarih_ayikla(excel_seri), date(2026, 10, 8))
    kontrol("boş metin", tarih_ayikla("   "), None)
    kontrol("geçersiz metin", tarih_ayikla("abc"), None)

    yaz("\nTürkçe arama sadeleştirme")
    kontrol("'İŞIN' -> 'isin'", tr_sadelestir("IŞIN"), "isin")
    kontrol("'Gürpom' -> 'gurpom'", tr_sadelestir("Gürpom"), "gurpom")
    kontrol("başlık 'Beyanna No'", baslik_anahtari("Beyanna No") in
            BASLIK_ESLESTIRME["beyanname_no"], True)
    kontrol("başlık 'Süre Sonu'", baslik_anahtari("Süre Sonu") in
            BASLIK_ESLESTIRME["sure_sonu"], True)

    yaz("\nŞifre yönetimi")
    ozet = sifre_ozetle("admin123", dongu=1000)
    kontrol("doğru şifre kabul", sifre_karsilastir("admin123", ozet), True)
    kontrol("yanlış şifre ret", sifre_karsilastir("admin124", ozet), False)
    kontrol("bozuk özet ret", sifre_karsilastir("admin123", "cop"), False)

    yaz("\nPaketlenmiş (.exe) çalışma yolu")
    onceki = getattr(sys, "frozen", None)
    try:
        sys.frozen = True          # PyInstaller'ın yaptığını taklit et
        kontrol(".exe yanındaki klasör kullanılıyor",
                _uygulama_klasoru(), Path(sys.executable).resolve().parent)
    finally:
        if onceki is None:
            del sys.frozen
        else:
            sys.frozen = onceki
    kontrol("betik olarak çalışırken betik klasörü",
            _uygulama_klasoru(), Path(__file__).resolve().parent)
    kontrol("yazılabilirlik denetimi (uygulama klasörü)",
            _yazilabilir_mi(_uygulama_klasoru()), True)
    # Ebeveyni bir DOSYA olan yol: mkdir hem Windows'ta hem Unix'te başarısız olur.
    with tempfile.NamedTemporaryFile(suffix=".engel", delete=False) as engel:
        engel_yolu = Path(engel.name)
    try:
        kontrol("yazılamayan klasörde geri düşüş",
                _yazilabilir_mi(engel_yolu / "altklasor"), False)
    finally:
        engel_yolu.unlink(missing_ok=True)

    yaz("\nVeritabanı (geçici, bellek içi)")
    gecici = Veritabani(Path(tempfile.gettempdir()) / f"_st_test_{os.getpid()}.db")
    try:
        yeni_id = gecici.kayit_ekle({
            "dosya_no": "26-12440", "firma": "AKSA",
            "beyanname_no": "26061500IM00000499", "rejim": "5300",
            "sure_sonu": "2027-03-31", "aciklama": "", "teminat": "",
        })
        kayit = gecici.kayit_getir(yeni_id)
        kontrol("kayıt okundu", kayit["firma"], "AKSA")
        kontrol("durum türetildi", kayit["durum"], durum_hesapla(date(2027, 3, 31)))
        kontrol("mükerrer tespiti", gecici.ayni_kayit_var_mi("26-12440", "26061500IM00000499"), True)
        kontrol("varsayılan şifre", gecici.sifre_dogru_mu(VARSAYILAN_SIFRE), True)
        gecici.kayit_guncelle(yeni_id, {**kayit, "firma": "AKSA A.Ş."})
        kontrol("güncelleme", gecici.kayit_getir(yeni_id)["firma"], "AKSA A.Ş.")
        # "durum" bir sütun DEĞİLDİR: elle yazılamayacağının kanıtı
        sutunlar = {s[1] for s in gecici.baglanti.execute("PRAGMA table_info(kayitlar)")}
        kontrol("'durum' sütunu yok (salt okunur)", "durum" in sutunlar, False)
        gecici.kayit_sil(yeni_id)
        kontrol("silme", gecici.kayit_sayisi(), 0)
    finally:
        gecici.kapat()
        try:
            gecici.yol.unlink()
            for ek in ("-wal", "-shm"):
                Path(str(gecici.yol) + ek).unlink(missing_ok=True)
        except OSError:
            pass

    yaz()
    if hatalar:
        yaz(f"{len(hatalar)} TEST BASARISIZ:")
        yaz("\n".join(hatalar))
    else:
        yaz("Tum testler basarili.")     # saf ASCII: her konsolda okunur
    return len(hatalar)


# =========================================================================
#  9. BÖLÜM — GİRİŞ NOKTASI
# =========================================================================

def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(
        prog="sure_takip.py",
        description=f"{UYGULAMA_ADI} — Geçici İthalat / Rejim Süre Takip Uygulaması",
    )
    ayristirici.add_argument(
        "--veritabani", metavar="YOL", default=str(VARSAYILAN_VERITABANI),
        help="Kullanılacak SQLite veritabanı dosyası "
             f"(varsayılan: {VARSAYILAN_VERITABANI})",
    )
    ayristirici.add_argument(
        "--sifre-sifirla", action="store_true",
        help=f"Yönetici şifresini varsayılana ('{VARSAYILAN_SIFRE}') döndürür",
    )
    ayristirici.add_argument(
        "--test", action="store_true",
        help="Arayüz açmadan iş kurallarını test eder",
    )
    argumanlar = ayristirici.parse_args(argv)

    if argumanlar.test:
        return 1 if kendini_test_et() else 0

    veritabani = Veritabani(Path(argumanlar.veritabani))

    if argumanlar.sifre_sifirla:
        veritabani.sifre_degistir(VARSAYILAN_SIFRE)
        veritabani.kapat()
        _konsolu_hazirla()
        yaz(f"Yonetici sifresi varsayilana donduruldu: {VARSAYILAN_SIFRE}")
        return 0

    if ARAYUZ_HATASI is not None:      # Tk / CustomTkinter kurulu değil
        veritabani.kapat()
        _konsolu_hazirla()
        print(
            "Arayüz başlatılamadı.\n\n"
            f"Ayrıntı: {ARAYUZ_HATASI}\n\n"
            "Gerekli kurulum:\n"
            "    pip install customtkinter openpyxl\n"
            "Linux'ta ayrıca:\n"
            "    sudo apt install python3-tk",
            file=sys.stderr,
        )
        return 2

    # Kayıtlı tema tercihini uygula
    tema = veritabani.ayar_al("tema", "Sistem")
    ctk.set_appearance_mode({"Açık": "light", "Koyu": "dark"}.get(tema, "system"))
    ctk.set_default_color_theme("blue")

    uygulama = Uygulama(veritabani)
    uygulama.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
