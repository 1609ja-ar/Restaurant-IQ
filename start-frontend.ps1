# Starts the RestaurantIQ frontend (Vite, usually http://localhost:5173). Works from any folder.
$frontend = Join-Path $PSScriptRoot "frontend"
if (-not (Test-Path (Join-Path $frontend "node_modules"))) { throw "Frontend is not set up yet. Run setup.ps1 first." }
Set-Location $frontend
npm run dev
