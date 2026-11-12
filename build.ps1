$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python environment.' }
}
& $pythonPath -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Failed to install dependencies.' }
& $pythonPath -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
& $pythonPath tools\package_release.py
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }

