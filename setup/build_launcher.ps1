param(
    [string]$AiRoot = (Split-Path -Parent $PSScriptRoot)
)
$ErrorActionPreference = "Stop"

$python = "$AiRoot\orchestrator\venv\Scripts\python.exe"
& $python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    & $python -m pip install pyinstaller
}

$work = Join-Path $env:TEMP "chati_launcher_build"
& $python -m PyInstaller --noconfirm --clean --windowed --onedir `
    --name ChatiIA `
    --icon "$AiRoot\icono.ico" `
    --version-file "$PSScriptRoot\launcher_version.txt" `
    --paths "$AiRoot\orchestrator" `
    --distpath $AiRoot `
    --workpath $work --specpath $work `
    "$AiRoot\orchestrator\desktop_app.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallo (codigo $LASTEXITCODE)" }

Write-Host "Lanzador creado: $AiRoot\ChatiIA\ChatiIA.exe" -ForegroundColor Green
