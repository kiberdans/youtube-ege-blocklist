Write-Host "=== Проверка Python ==="

$python = Get-Command python -ErrorAction SilentlyContinue

if (-not $python) {
    Write-Host "Python не найден."
    Write-Host ""
    Write-Host "Вариант 1 (рекомендуется): winget"
    Write-Host "  winget install Python.Python.3"
    Write-Host ""
    Write-Host "Вариант 2: скачать вручную"
    Write-Host "  https://www.python.org/downloads/"
    Write-Host "  При установке отметьте «Add Python to PATH»"
    exit 1
}

Write-Host "Python найден: $($python.Source)"
& $python.Source --version
Write-Host ""
Write-Host "Устанавливаю customtkinter..."
& $python.Source -m pip install customtkinter
Write-Host ""
Write-Host "Готово. Запустите: python main.py"
