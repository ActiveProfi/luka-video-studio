# Установка библиотек для точных аннотаций (не меняет текущий pipeline).
# Запуск из корня проекта:
#   .\scripts\install-annotation-tools.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "Шаг 1: Python-библиотеки (annotations)..." -ForegroundColor Cyan
& .\.venv\Scripts\pip.exe install -e ".[annotations]"

Write-Host ""
Write-Host "Шаг 2 (опционально): OCR — раскомментируйте строку ниже, если нужен поиск текста на экране." -ForegroundColor Yellow
# & .\.venv\Scripts\pip.exe install -e ".[annotations-ocr]"

Write-Host ""
Write-Host "Шаг 3: npm-пакеты для ручной разметки в браузере (Fabric.js)..." -ForegroundColor Cyan
Set-Location "$Root\review-ui"
& npm install fabric@^6.5.4 konva@^9.3.18 react-konva@^18.2.10 --save

Write-Host ""
Write-Host "Шаг 4: Проверка..." -ForegroundColor Cyan
Set-Location $Root
& .\.venv\Scripts\python.exe -m src.tools.annotation_toolkit.check_install

Write-Host ""
Write-Host "Готово. Текущий этап аннотаций не изменён — инструменты в src/tools/annotation_toolkit/" -ForegroundColor Green
