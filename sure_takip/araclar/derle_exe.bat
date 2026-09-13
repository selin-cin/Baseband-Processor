@echo off
rem ===================================================================
rem  SURE TAKIP - TEK DOSYALIK .EXE URETME  (Windows, gelistirici araci)
rem
rem  Bu dosyayi SIZ bir kez calistirin. Sonucta olusan
rem      dist\SureTakip.exe
rem  dosyasi tek basina calisir: karsi bilgisayarda Python,
rem  kutuphane, kurulum HICBIR SEY gerekmez. O dosyayi kopyalayip
rem  masaustune koymak yeterlidir.
rem
rem  Not: .exe yalnizca uzerinde uretildigi isletim sistemi icin
rem       gecerlidir. Windows .exe'si Windows'ta uretilmelidir.
rem ===================================================================
setlocal
cd /d "%~dp0.."
title Sure Takip - EXE Derleme

echo.
echo   ============================================
echo      SURE TAKIP  -  EXE DERLEME
echo   ============================================
echo.

set "PY="
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
echo   [!] Python bulunamadi. Once ana klasordeki KURULUM.bat dosyasini calistirin.
goto :son

:python_bulundu
echo   [1/2] PyInstaller ve kutuphaneler hazirlaniyor...
%PY% -m pip install --quiet --disable-pip-version-check --upgrade pyinstaller customtkinter openpyxl || %PY% -m pip install --quiet --disable-pip-version-check --user --upgrade pyinstaller customtkinter openpyxl
if errorlevel 1 (
    echo   [!] PyInstaller kurulamadi. Internet baglantinizi denetleyin.
    goto :son
)

echo   [2/2] EXE derleniyor... Bu islem 1-3 dakika surebilir.
echo.
rem --collect-all customtkinter: CustomTkinter tema JSON dosyalarini
rem paketin icine ekler; aksi halde .exe acilisinda tema hatasi verir.
%PY% -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "SureTakip" ^
    --icon "simge.ico" ^
    --collect-all customtkinter ^
    "sure_takip.py"

if errorlevel 1 (
    echo.
    echo   [!] Derleme basarisiz oldu. Yukaridaki hata mesajina bakin.
    goto :son
)

echo.
echo   ============================================
echo      TAMAMLANDI
echo   ============================================
echo.
echo   Olusan dosya:  %CD%\dist\SureTakip.exe
echo.
echo   Bu tek dosyayi babanizin bilgisayarina kopyalayin. Calistirmak
echo   icin cift tiklamak yeterli; hicbir kurulum gerekmez.
echo.
echo   Veritabani (sure_takip.db) .exe ile ayni klasorde olusur;
echo   bu yuzden .exe'yi kendi klasorune koymaniz onerilir.
echo.

:son
echo   Kapatmak icin bir tusa basin...
pause >nul
endlocal
