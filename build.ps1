$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Flet   = Join-Path $Root ".venv\Scripts\flet.exe"

if (-not (Test-Path $Python)) {
    Write-Host "[1/6] Создаю виртуальное окружение .venv..."
    python -m venv .venv
}
if (-not (Test-Path $Flet)) {
    Write-Host "[2/6] Устанавливаю зависимости (flet, playwright, ...) и PyInstaller..."
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r req.txt pyinstaller
} else {
    Write-Host "[2/6] Зависимости уже установлены."
}

$Version = "0.1.0"
try {
    $tag = git describe --tags --abbrev=0 2>$null
    if ($tag) { $Version = $tag.TrimStart('v') }
} catch {}
$VerParts = (($Version -split '\.') + @('0','0','0','0'))[0..3]
$FileVersion = $VerParts -join '.'

$AppName = "GetCourseVideoDownloader"
$Res = Join-Path $Root "resources"

Write-Host "[3/6] FFmpeg..."
New-Item -ItemType Directory -Force -Path $Res | Out-Null
$ffmpegExe = Join-Path $Res "ffmpeg.exe"
if (-not (Test-Path $ffmpegExe)) {
    Write-Host "  Скачиваю ffmpeg-release-essentials (~80 МБ)..."
    $ffmpegZip = Join-Path $env:TEMP "ffmpeg-release-essentials.zip"
    curl.exe -L -o $ffmpegZip "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    $extract = Join-Path $env:TEMP "ffmpeg-build"
    if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
    Expand-Archive $ffmpegZip -DestinationPath $extract -Force
    $found = Get-ChildItem $extract -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    Copy-Item $found.FullName $ffmpegExe -Force
} else {
    Write-Host "  ffmpeg.exe уже есть в resources\."
}

Write-Host "[4/6] Браузеры Playwright (Firefox)..."
$msPwSrc = Join-Path $env:LOCALAPPDATA "ms-playwright"
$msPwDst = Join-Path $Res "ms-playwright"
if (-not (Test-Path $msPwSrc)) {
    Write-Host "  Не найдены браузеры, устанавливаю Firefox через playwright..."
    & $Python -m playwright install firefox
}
if (Test-Path $msPwSrc) {
    New-Item -ItemType Directory -Force -Path $msPwDst | Out-Null
    Get-ChildItem $msPwSrc -Directory -Filter "firefox-*" | ForEach-Object {
        Write-Host "  Копирую $($_.Name)..."
        Copy-Item $_.FullName $msPwDst -Recurse -Force
    }
} else {
    Write-Error "Не удалось получить браузеры Playwright (нет $msPwSrc)."
}

Write-Host "[5/6] flet pack..."
& $Flet pack main.py -y -D -n $AppName `
    --product-name "GetCourse Video Downloader" `
    --file-description "Загрузка видео с GetCourse" `
    --company-name "Mark Pekun" `
    --product-version $Version `
    --file-version $FileVersion
if ($LASTEXITCODE -ne 0) { throw "flet pack завершился с ошибкой ($LASTEXITCODE)" }

Write-Host "[6/6] Формирую релиз..."
$DistApp = Join-Path $Root "dist\$AppName"
Copy-Item $Res $DistApp -Recurse -Force

$ZipPath = Join-Path $Root "dist\$AppName-win-x64.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path $DistApp -DestinationPath $ZipPath -CompressionLevel Optimal -Force

Write-Host ""
Write-Host "Готово: $ZipPath"
Write-Host "Проверка: запустите $DistApp\$AppName.exe"
