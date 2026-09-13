<#
    Süre Takip — kısayol oluşturucu
    KURULUM.bat tarafından çağrılır. Masaüstüne ve Başlat menüsüne,
    simgesi ayarlanmış "Süre Takip" kısayolu koyar.

    Kısayolun hedefi pythonw.exe (ya da pyw.exe) olduğu için uygulama
    açılırken siyah konsol penceresi HİÇ görünmez.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Klasor            # sure_takip.py dosyasının bulunduğu klasör
)

$ErrorActionPreference = "Stop"

try {
    $Klasor = (Resolve-Path -LiteralPath $Klasor).Path
    $betik  = Join-Path $Klasor "sure_takip.py"
    $simge  = Join-Path $Klasor "simge.ico"

    if (-not (Test-Path -LiteralPath $betik)) {
        Write-Host "  [!] sure_takip.py bulunamadi: $betik"
        exit 1
    }

    # --- Pencereli Python yorumlayıcısını bul (konsolsuz çalışma için) ---
    $hedef = $null
    $onEk  = ""
    foreach ($ad in @("pythonw.exe", "pyw.exe")) {
        $komut = Get-Command $ad -ErrorAction SilentlyContinue
        if ($komut) {
            $hedef = $komut.Source
            if ($ad -eq "pyw.exe") { $onEk = "-3 " }   # py launcher sürüm bekler
            break
        }
    }
    if (-not $hedef) {
        Write-Host "  [!] pythonw.exe / pyw.exe bulunamadi."
        exit 1
    }

    # --- Kısayolları oluştur ---
    $kabuk = New-Object -ComObject WScript.Shell
    $konumlar = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs")
    )

    $sayac = 0
    foreach ($konum in $konumlar) {
        if ([string]::IsNullOrWhiteSpace($konum) -or -not (Test-Path -LiteralPath $konum)) {
            continue
        }
        $yol = Join-Path $konum "Süre Takip.lnk"
        $kisayol = $kabuk.CreateShortcut($yol)
        $kisayol.TargetPath       = $hedef
        $kisayol.Arguments        = $onEk + '"' + $betik + '"'
        $kisayol.WorkingDirectory = $Klasor
        $kisayol.Description      = "Süre Takip — Geçici İthalat / Rejim Süre Takibi"
        if (Test-Path -LiteralPath $simge) {
            $kisayol.IconLocation = $simge
        }
        $kisayol.Save()
        Write-Host "      Kisayol olusturuldu: $yol"
        $sayac++
    }

    if ($sayac -eq 0) {
        Write-Host "  [!] Hicbir kisayol olusturulamadi."
        exit 1
    }
    exit 0
}
catch {
    Write-Host "  [!] Kisayol olusturulurken hata: $($_.Exception.Message)"
    exit 1
}
