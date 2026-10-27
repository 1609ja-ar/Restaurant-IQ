# Starts the RestaurantIQ backend on http://127.0.0.1:8010. Works from any folder.
$backend = Join-Path $PSScriptRoot "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Backend is not set up yet. Run setup.ps1 first." }
Set-Location $backend
# Quick database check first: the API starts either way, but this shows a MongoDB problem right away.
& $python -m app.db_check
if ($LASTEXITCODE -ne 0) { Write-Warning "MongoDB is not reachable (see above). The API starts, but sign-in will fail until it is." }
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
