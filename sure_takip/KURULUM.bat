@echo off
rem ===================================================================
rem  SURE TAKIP - TEK SEFERLIK KURULUM  (Windows)
rem
rem  Bu dosyaya bir kez cift tiklamak yeterlidir. Yaptiklari:
rem    1. Bilgisayarda Python olup olmadigini denetler
rem    2. Gerekli kutuphaneleri kurar (customtkinter, openpyxl)
rem    3. Masaustune ve Baslat menusune "Sure Takip" kisayolu koyar
rem
rem  Not: Konsol mesajlari bilincli olarak Turkce karaktersiz yazilmistir;
rem       cmd.exe kod sayfasi farkliliklarinda bozuk gorunmemesi icin.
rem       Uygulamanin kendi arayuzu tam Turkcedir.
rem ===================================================================
setlocal
cd /d "%~dp0"
title Sure Takip - Kurulum
color 0B

echo.
echo   ============================================
echo      SURE TAKIP  -  TEK SEFERLIK KURULUM
echo   ============================================
echo.

rem ---------- 1) Python'u bul --------------------------------------
set "PY="
echo   [1/3] Python araniyor...

py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
    goto :python_bulundu
)

python -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=python"
    goto :python_bulundu
)

echo.
echo   [!] Bilgisayarda Python bulunamadi.
echo.
echo       Yapmaniz gerekenler:
echo         1. https://www.python.org/downloads/ adresine gidin
echo         2. "Download Python" dugmesine basin
echo         3. Kurulum ekranindaki "Add python.exe to PATH" kutusunu
echo            MUTLAKA isaretleyin, sonra "Install Now" deyin
echo         4. Kurulum bitince bu dosyaya yeniden cift tiklayin
echo.
echo       Alternatif: Python kurmak istemiyorsaniz hazir .exe surumunu
echo       kullanabilirsiniz (bkz. README.md - "Hic kurulum istemiyorum").
echo.
goto :son

:python_bulundu
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [!] Python surumu cok eski. En az Python 3.9 gerekiyor.
    echo       https://www.python.org/downloads/ adresinden guncelleyin.
    echo.
    goto :son
)
for /f "delims=" %%v in ('%PY% -c "import sys;print(sys.version.split()[0])"') do set "SURUM=%%v"
echo       Python %SURUM% bulundu.

rem ---------- 2) Kutuphaneleri kur --------------------------------
echo.
echo   [2/3] Gerekli kutuphaneler kuruluyor (internet gerekir)...
echo         Bu islem birkac dakika surebilir, lutfen bekleyin.
echo.
%PY% -m pip install --quiet --disable-pip-version-check customtkinter openpyxl || %PY% -m pip install --quiet --disable-pip-version-check --user customtkinter openpyxl
if errorlevel 1 (
    echo.
    echo   [!] Kutuphaneler kurulamadi.
    echo       Internet baglantinizi denetleyin ve tekrar deneyin.
    echo.
    goto :son
)
%PY% -c "import customtkinter, openpyxl" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [!] Kutuphaneler kurulmus gorunuyor ama yuklenemiyor.
    echo       Bilgisayari yeniden baslatip tekrar deneyin.
    echo.
    goto :son
)
echo       Kutuphaneler hazir.

rem ---------- 3) Kisayollari olustur ------------------------------
echo.
echo   [3/3] Masaustu ve Baslat menusu kisayollari olusturuluyor...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0araclar\kisayol_olustur.ps1" -Klasor "%~dp0."
if errorlevel 1 (
    echo   [!] Kisayol olusturulamadi. Sorun degil: uygulamayi bu klasordeki
    echo       "Sure Takip - Baslat.bat" dosyasina cift tiklayarak acabilirsiniz.
)

echo.
echo   ============================================
echo      KURULUM TAMAMLANDI
echo   ============================================
echo.
echo   Artik masaustundeki "Sure Takip" simgesine cift tiklamak yeterli.
echo   Bir daha bu kurulumu yapmaniza gerek yok.
echo.

:son
echo   Kapatmak icin bir tusa basin...
pause >nul
endlocal
