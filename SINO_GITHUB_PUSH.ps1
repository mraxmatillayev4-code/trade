# SINO -> GitHub push v2 (kod repo ILDIZIGA yoziladi, shunda Render Dockerfile topadi).
# PowerShell 5.1: ASCII only, && yoq. .env va kalitlar push qilinmaydi.
$ErrorActionPreference = 'Stop'

$src = Join-Path $env:USERPROFILE 'Desktop\SINO_BOT_FINAL\trading_signal_bot'
if (-not (Test-Path (Join-Path $src 'app'))) {
    Write-Host ('XATO: bot papkasi topilmadi: ' + $src) -ForegroundColor Red
    Read-Host 'Yopish uchun Enter'
    exit 1
}

$stage = Join-Path $env:USERPROFILE 'Desktop\sino_gh_push'
Write-Host ''
Write-Host '===== SINO -> GITHUB PUSH v2 (kod repo ildiziga) =====' -ForegroundColor Cyan
Write-Host ('Manba : ' + $src) -ForegroundColor DarkGray

Write-Host ''
Write-Host '1) Tozalash va nusxalash...' -ForegroundColor Yellow
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

$xd = @('.git', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.venv', 'venv', 'env', '.idea', '.vscode', '_git_backup_trading_signal_bot', 'node_modules')
$xf = @('.env', 'sino_deploy.ps1', 'sino_install.ps1', '*.pyc', '*.pyo', '*.db', '*.sqlite3', '*.sqlite', '*.log', '*.session', '*.session-journal')
robocopy $src $stage /E /XD $xd /XF $xf /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Host ('XATO: robocopy kod ' + $LASTEXITCODE) -ForegroundColor Red
    Read-Host 'Yopish uchun Enter'
    exit 1
}

Get-ChildItem -Path $stage -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq '.env' } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# Render uchun kerakli fayllar
$must = @('Dockerfile', 'requirements.txt', 'render.yaml', 'app\main.py', 'app\services\channel_inbox.py', 'app\services\channel_ocr.py')
$miss = @()
foreach ($m in $must) { if (-not (Test-Path (Join-Path $stage $m))) { $miss += $m } }
if ($miss.Count -gt 0) {
    Write-Host ('XATO: kerakli fayllar yoq: ' + ($miss -join ', ')) -ForegroundColor Red
    Write-Host 'Skriptni bot papkasida saqlab, osha papkadan ishga tushirganingizga ishonch qiling.' -ForegroundColor Red
    Read-Host 'Yopish uchun Enter'
    exit 1
}

# .gitignore
$gi = @'
.venv/
venv/
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.env
.env.local
*.session
*.session-journal
*.db
*.sqlite3
*.log
.idea/
.vscode/
'@
Set-Content -Path (Join-Path $stage '.gitignore') -Value $gi -Encoding ASCII

$files = (Get-ChildItem -Path $stage -Recurse -File -Force).Count
Write-Host ('   nusxa tayyor: ' + $files + ' ta fayl') -ForegroundColor Green

Write-Host ''
Write-Host '2) Maxfiy malumot tekshiruvi (tokenlar ketmasligi uchun)...' -ForegroundColor Yellow
$leak = Get-ChildItem -Path $stage -Recurse -File -Force |
    Select-String -Pattern 'glpat-', '[0-9]{8,10}:[A-Za-z0-9_-]{30,}' -List -ErrorAction SilentlyContinue
if ($leak) {
    Write-Host 'XATO: maxfiy matn topildi - push TOXTATILDI:' -ForegroundColor Red
    $leak | ForEach-Object { Write-Host ('   ' + $_.Path) -ForegroundColor Red }
    Read-Host 'Yopish uchun Enter'
    exit 1
}
Write-Host '   toza: token/kalit topilmadi.' -ForegroundColor Green

Write-Host ''
Write-Host '3) Tuzatishlar joyidami?' -ForegroundColor Yellow
$m1 = Select-String -Path (Join-Path $stage 'app\services\channel_inbox.py') -Pattern 'AI zaxira' -SimpleMatch -Quiet
$m2 = Select-String -Path (Join-Path $stage 'app\services\channel_ocr.py') -Pattern '_TESS_DONE' -SimpleMatch -Quiet
$m3 = Select-String -Path (Join-Path $stage 'app\services\channel_parse.py') -Pattern '_gold_levels' -SimpleMatch -Quiet
if ($m1 -and $m2 -and $m3) {
    Write-Host '   tuzatishlar bor (AI zaxira, tesseract, parser).' -ForegroundColor Green
} else {
    Write-Host ('   OGOHLANTIRISH: marker topilmadi -> ' + $m1 + '/' + $m2 + '/' + $m3) -ForegroundColor Yellow
    Write-Host '   Lokal fayllar eski bolishi mumkin: sino_deploy.ps1 (v43) ni qayta ishga tushiring.' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '4) Git repo tayyorlanmoqda...' -ForegroundColor Yellow
Set-Location $stage
git init -q
git add -A
$tracked = (git ls-files | Measure-Object).Count
Write-Host ('   gitga qoshildi: ' + $tracked + ' ta fayl') -ForegroundColor DarkGray

$envTracked = git ls-files | Where-Object { $_ -match '(^|/)\.env$' }
if ($envTracked) {
    Write-Host 'XATO: .env gitga tushdi - push qilinmadi!' -ForegroundColor Red
    Read-Host 'Yopish uchun Enter'
    exit 1
}
$dockTracked = git ls-files | Where-Object { $_ -eq 'Dockerfile' }
if (-not $dockTracked) {
    Write-Host 'XATO: Dockerfile gitga tushmadi - toxtatildi.' -ForegroundColor Red
    Read-Host 'Yopish uchun Enter'
    exit 1
}

git -c user.name='mraxmatillayev4-code' -c user.email='mraxmatillayev4@gmail.com' commit -q -m 'SINO v43: kanal AI zaxira + tesseract OCR + parser tuzatishlar'
$hasOrigin = (git remote 2>$null) | Where-Object { $_ -eq 'origin' }
if ($hasOrigin) { git remote remove origin }
git remote add origin https://github.com/mraxmatillayev4-code/trade.git

Write-Host ''
Write-Host '5) GitHubga push (main, force)...' -ForegroundColor Yellow
git push origin HEAD:main --force
if ($LASTEXITCODE -ne 0) {
    Write-Host 'XATO: push otmadi (GitHub login/ruxsat).' -ForegroundColor Red
    Read-Host 'Yopish uchun Enter'
    exit 1
}

Write-Host ''
Write-Host 'TAYYOR: kod GitHub main ildiziga yuklandi.' -ForegroundColor Green
Write-Host ''
Write-Host 'Endi Renderda:' -ForegroundColor Cyan
Write-Host '  1) Settings -> Build & Deploy -> Root Directory BOSH bolsin (trading_signal_bot yozilgan bolsa - ochirib tashlang)'
Write-Host '  2) Dockerfile Path = Dockerfile'
Write-Host '  3) Manual Deploy'
Write-Host ''
Write-Host 'MUHIM: GitHub repo OCHIQ (public) - Settings -> General -> Danger Zone -> Make private qiling.' -ForegroundColor Yellow
Read-Host 'Yopish uchun Enter'
