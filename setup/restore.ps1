param(
    [string]$Zip = "",
    [string]$CarpetaCopias = "$env:USERPROFILE\OneDrive\IA-Personal-Backups",
    [string]$DataRoot = ""
)

$AiRoot = Split-Path -Parent $PSScriptRoot
$chatiDataRoot = if (Test-Path "$AiRoot\.git") { $AiRoot }  # copia de desarrollo, ver orchestrator/infra/paths.py
                 elseif ($env:CHATI_DATA_ROOT) { $env:CHATI_DATA_ROOT }
                 elseif ([Environment]::GetEnvironmentVariable("CHATI_DATA_ROOT", "User")) {
                     [Environment]::GetEnvironmentVariable("CHATI_DATA_ROOT", "User") }
                 elseif ($env:LOCALAPPDATA) { "$env:LOCALAPPDATA\ChatiIA" }
                 else { $AiRoot }
if (-not $DataRoot) { $DataRoot = $chatiDataRoot }
$data = "$DataRoot\data"
$isLiveData = [IO.Path]::GetFullPath($DataRoot).TrimEnd("\") -eq [IO.Path]::GetFullPath($chatiDataRoot).TrimEnd("\")

if (-not $Zip) {
    $latest = Get-ChildItem $CarpetaCopias -Filter "ia-personal-data_*.zip" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { Write-Host "No hay copias en $CarpetaCopias." -ForegroundColor Red; exit 1 }
    $Zip = $latest.FullName
}
if (-not (Test-Path $Zip)) { Write-Host "No existe $Zip" -ForegroundColor Red; exit 1 }

Add-Type -AssemblyName System.IO.Compression.FileSystem
$entries = [System.IO.Compression.ZipFile]::OpenRead($Zip)
try { $hasUsers = @($entries.Entries | Where-Object { $_.FullName -eq "users.db" }).Count -gt 0 }
finally { $entries.Dispose() }
if (-not $hasUsers) { Write-Host "$Zip no parece una copia de Chati (no tiene users.db)." -ForegroundColor Red; exit 1 }

Write-Host "Restaurando $Zip en $data" -ForegroundColor Cyan

function Stop-ByPort($port) {
    foreach ($c in Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue
        if ($proc -and $proc.ParentProcessId) { Stop-Process -Id $proc.ParentProcessId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

$wasRunning = $isLiveData -and [bool](Get-NetTCPConnection -LocalPort 8899 -State Listen -ErrorAction SilentlyContinue)
if ($wasRunning) { Stop-ByPort 8899; Start-Sleep -Seconds 2 }

if (Test-Path $data) {
    $apartado = "$data.antes-de-restaurar_$(Get-Date -Format 'yyyy-MM-dd_HHmmss')"
    Move-Item $data $apartado
    Write-Host "Lo que habia se ha apartado en $apartado" -ForegroundColor Yellow
}
Expand-Archive -Path $Zip -DestinationPath $data -Force
if ($apartado) {
    foreach ($key in "opencode_password.txt", "registration_key.txt", "api_key.txt") {
        if ((Test-Path "$apartado\$key") -and -not (Test-Path "$data\$key")) {
            Copy-Item "$apartado\$key" "$data\$key"
        }
    }
}
Write-Host "Copia restaurada." -ForegroundColor Green

if ($wasRunning) {
    Start-Process -FilePath "$AiRoot\orchestrator\venv\Scripts\python.exe" `
        -ArgumentList "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8899" `
        -WorkingDirectory "$AiRoot\orchestrator" -WindowStyle Hidden
    Write-Host "Orquestador arrancado. Inicia sesion de nuevo." -ForegroundColor Green
}
