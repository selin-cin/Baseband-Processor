#!/usr/bin/env bash
# ===================================================================
#  Süre Takip — başlatıcı (macOS ve Linux)
#
#  macOS: Finder'da bu dosyaya çift tıklamak yeterlidir.
#  Linux: dosya yöneticisinde çift tıklayın ya da terminalden
#         ./"Sure Takip.command" komutuyla çalıştırın.
#
#  Eksik kütüphane varsa kurar, ardından uygulamayı açar.
# ===================================================================
set -uo pipefail

klasor="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$klasor"

bekle_ve_cik() {
    echo
    read -r -p "  Kapatmak için Enter'a basın..." _ || true
    exit "${1:-1}"
}

# --- Uygun Python'u bul ---------------------------------------------
# Bilgisayarda birden fazla Python olabilir; Tk arayüz kütüphanesi
# bunların yalnızca bazılarında kurulu olabilir. Bu yüzden sürümü
# yeterli VE tkinter'ı olan ilk yorumlayıcı seçilir.
adaylar="python3 python python3.13 python3.12 python3.11 python3.10 python3.9"

PY=""
PY_TKSIZ=""
for aday in $adaylar; do
    command -v "$aday" >/dev/null 2>&1 || continue
    "$aday" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null || continue
    if "$aday" -c 'import tkinter' >/dev/null 2>&1; then
        PY="$aday"
        break
    fi
    [ -z "$PY_TKSIZ" ] && PY_TKSIZ="$aday"
done

if [ -z "$PY" ] && [ -n "$PY_TKSIZ" ]; then
    echo
    echo "  [!] Python bulundu ($PY_TKSIZ) ama Tk arayüz kütüphanesi eksik."
    echo
    echo "      Debian/Ubuntu : sudo apt install python3-tk"
    echo "      Fedora        : sudo dnf install python3-tkinter"
    echo "      Arch          : sudo pacman -S tk"
    echo "      macOS         : https://www.python.org adresindeki resmî"
    echo "                      Python paketini kurun (Tk ile birlikte gelir)"
    bekle_ve_cik 1
fi

if [ -z "$PY" ]; then
    echo
    echo "  [!] Python 3.9 veya üzeri bulunamadı."
    echo
    echo "      macOS : https://www.python.org/downloads/macos/"
    echo "      Linux : sudo apt install python3 python3-tk python3-pip"
    bekle_ve_cik 1
fi

# --- Eksik kütüphaneleri kur ----------------------------------------
if ! "$PY" -c 'import customtkinter, openpyxl' >/dev/null 2>&1; then
    echo
    echo "  İlk çalıştırma: gerekli kütüphaneler kuruluyor, lütfen bekleyin..."
    echo
    "$PY" -m pip install --quiet --user customtkinter openpyxl ||
    "$PY" -m pip install --quiet --user --break-system-packages customtkinter openpyxl ||
    "$PY" -m pip install --quiet customtkinter openpyxl || {
        echo
        echo "  [!] Kütüphaneler kurulamadı. İnternet bağlantınızı denetleyin."
        bekle_ve_cik 1
    }
    if ! "$PY" -c 'import customtkinter, openpyxl' >/dev/null 2>&1; then
        echo
        echo "  [!] Kütüphaneler kuruldu ama yüklenemiyor."
        echo "      Sanal ortam kullanıyorsanız etkinleştirip tekrar deneyin."
        bekle_ve_cik 1
    fi
fi

# --- Uygulamayı başlat ----------------------------------------------
exec "$PY" "$klasor/sure_takip.py" "$@"
