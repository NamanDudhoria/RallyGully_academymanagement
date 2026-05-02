# Run RallyGully Academy locally (creates venv if missing, installs deps, starts Streamlit).
Set-Location $PSScriptRoot
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment .venv ..."
    py -3 -m venv .venv
}

Write-Host "Installing dependencies..."
.\.venv\Scripts\pip.exe install -r requirements.txt

Write-Host "Starting Streamlit..."
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
