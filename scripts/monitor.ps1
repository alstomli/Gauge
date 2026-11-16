param(
    [ValidateSet('mcp','scan','config','test')]
    [string]$Command = 'mcp'
)
$ErrorActionPreference = 'Stop'
$monitorRoot = Split-Path -Parent $PSScriptRoot
$monitorPython = Join-Path $monitorRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $monitorPython)) { throw 'Create .venv and install requirements first; see README.md.' }
Push-Location $monitorRoot
try {
    if ($Command -eq 'test') { & $monitorPython -m unittest discover -v }
    else { & $monitorPython -m cache_monitor $Command }
    if ($LASTEXITCODE -ne 0) { throw "Monitor exited with code $LASTEXITCODE" }
}
finally { Pop-Location }
