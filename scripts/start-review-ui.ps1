# Запуск веб-интерфейса согласования (2 окна откроются автоматически)
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$reviewUi = Join-Path $ProjectRoot "review-ui"

if (-not (Test-Path $python)) {
    Write-Host "Ошибка: сначала создайте .venv (py -3.13 -m venv .venv)" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path (Join-Path $reviewUi "node_modules"))) {
    Write-Host "Устанавливаю npm-пакеты..." -ForegroundColor Yellow
    Set-Location -LiteralPath $reviewUi
    npm install
    Set-Location -LiteralPath $ProjectRoot
}

Write-Host "Запуск API на http://127.0.0.1:8000 ..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location -LiteralPath '$ProjectRoot'; & '$python' -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000 --reload"

Start-Sleep -Seconds 2

Write-Host "Запуск интерфейса на http://127.0.0.1:5173 ..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location -LiteralPath '$reviewUi'; npm run dev"

Start-Sleep -Seconds 4
Start-Process "http://127.0.0.1:5173"

Write-Host ""
Write-Host "Готово! Браузер должен открыться." -ForegroundColor Green
Write-Host "Если нет — откройте вручную: http://127.0.0.1:5173" -ForegroundColor Cyan
Write-Host "Не закрывайте два окна PowerShell (API и UI)." -ForegroundColor Yellow
