# One-time setup for RestaurantIQ. Works from any folder:
#   powershell -ExecutionPolicy Bypass -File "C:\Users\jaide\Desktop\Data prj\restaurantiq\setup.ps1"
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creating Python 3.11 virtual environment..."
    py -3.11 -m venv (Join-Path $backend ".venv")
}
Write-Host "Installing backend packages..."
& $python -m pip install -r (Join-Path $backend "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed (see the messages above)." }

Write-Host "Installing frontend packages..."
Push-Location $frontend
try { npm install; if ($LASTEXITCODE -ne 0) { throw "npm install failed." } } finally { Pop-Location }

Write-Host ""
Write-Host "Setup complete. Checking the MongoDB connection (RIQ_MONGO_URI in backend\.env)..."
Push-Location $backend
try { & $python -m app.db_check } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) {
    Write-Host "MongoDB is not ready yet: fix the problem shown above, then run: .\.venv\Scripts\python.exe -m app.db_check"
}
