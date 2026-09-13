@echo off
rem ===================================================================
rem  SURE TAKIP - BASLATICI  (Windows)
rem
rem  Kisayol kullanmak istemiyorsaniz bu dosyaya cift tiklayin.
rem  Eksik kutuphane varsa sessizce kurar, sonra uygulamayi acar.
rem  Uygulama pencereli (pythonw) baslatildigi icin siyah konsol
rem  penceresi ekranda kalmaz.
rem ===================================================================
setlocal
cd /d "%~dp0"

set "PY="
set "PYW="

py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
    set "PYW=pyw -3"
    goto :python_bulundu
)

python -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=python"
    set "PYW=pythonw"
    goto :python_bulundu
)

echo.
echo   [!] Python bulunamadi. Once "KURULUM.bat" dosyasina cift tiklayin.
echo.
pause
exit /b 1

:python_bulundu
rem --- Kutuphaneler eksikse kur ---
%PY% -c "import customtkinter, openpyxl" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Ilk calistirma: gerekli kutuphaneler kuruluyor...
    echo   Lutfen bekleyin, bu yalnizca bir kez olacak.
    echo.
    %PY% -m pip install --quiet --disable-pip-version-check customtkinter openpyxl || %PY% -m pip install --quiet --disable-pip-version-check --user customtkinter openpyxl
    %PY% -c "import customtkinter, openpyxl" >nul 2>&1
    if errorlevel 1 (
        echo   [!] Kutuphaneler kurulamadi. "KURULUM.bat" dosyasini calistirin.
        echo.
        pause
        exit /b 1
    )
)

rem --- Uygulamayi pencereli baslat, konsolu kapat ---
start "Sure Takip" %PYW% "%~dp0sure_takip.py"
exit /b 0
