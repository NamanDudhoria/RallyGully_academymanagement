# One-time: copy rg_data/*.json into Postgres (only inserts missing collections).
Set-Location $PSScriptRoot
$ErrorActionPreference = "Stop"
.\.venv\Scripts\python.exe -m rg_datastore --bootstrap
Write-Host "Done. Check messages above for 'New collections written'."
