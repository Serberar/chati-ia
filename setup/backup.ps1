param(
    [string]$Destino = "",  # vacio: <datos>\copias. A la nube, solo si se pide aqui
    [int]$Mantener = 14  # cuantas copias recientes conservar
)

$AiRoot = Split-Path -Parent $PSScriptRoot
$DataRoot = if (Test-Path "$AiRoot\.git") { $AiRoot }  # copia de desarrollo, ver orchestrator/infra/paths.py
            elseif ($env:CHATI_DATA_ROOT) { $env:CHATI_DATA_ROOT }
                           elseif ([Environment]::GetEnvironmentVariable("CHATI_DATA_ROOT", "User")) {
                               [Environment]::GetEnvironmentVariable("CHATI_DATA_ROOT", "User") }
            elseif ($env:LOCALAPPDATA) { "$env:LOCALAPPDATA\ChatiIA" }
            else { $AiRoot }
$origen = "$DataRoot\data"
if (-not $Destino) { $Destino = "$DataRoot\copias" }
$fecha = Get-Date -Format "yyyy-MM-dd_HHmm"
$nombreZip = "ia-personal-data_$fecha.zip"

if (-not (Test-Path $origen)) {
    Write-Host "No existe $origen todavia, nada que copiar." -ForegroundColor Yellow
    exit 0
}

function Test-Url($url) {
    try { (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 }
    catch { $false }
}

function Stop-ByPort($port) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue
        if ($proc -and $proc.ParentProcessId) { Stop-Process -Id $proc.ParentProcessId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

$wasRunning = Test-Url "http://127.0.0.1:8899/health"
if ($wasRunning) {
    Write-Host "Parando el orquestador un momento para un backup consistente..." -ForegroundColor Yellow
    Stop-ByPort 8899
    Start-Sleep -Seconds 2
}

if (-not (Test-Path $Destino)) {
    New-Item -ItemType Directory -Path $Destino -Force | Out-Null
}

$zipPath = Join-Path $Destino $nombreZip
$noCopiar = @("opencode_password.txt", "registration_key.txt", "api_key.txt", "logs", "metrics.jsonl", "arranque.log",
              "webview", "sesiones_recordadas.json")  # sesiones del navegador: ademas, en uso fallan al comprimir
$items = Get-ChildItem -LiteralPath $origen -Force | Where-Object { $noCopiar -notcontains $_.Name }
Compress-Archive -LiteralPath $items.FullName -DestinationPath $zipPath -Force
Write-Host "Backup creado: $zipPath" -ForegroundColor Green

if ($wasRunning) {
    Start-Process -FilePath "$AiRoot\orchestrator\venv\Scripts\python.exe" `
        -ArgumentList "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8899" `
        -WorkingDirectory "$AiRoot\orchestrator" -WindowStyle Hidden
    Write-Host "Orquestador reiniciado." -ForegroundColor Green
}

$antiguos = Get-ChildItem $Destino -Filter "ia-personal-data_*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -Skip $Mantener
foreach ($f in $antiguos) {
    Remove-Item $f.FullName -Force
    Write-Host "Backup antiguo eliminado: $($f.Name)" -ForegroundColor DarkGray
}

New-Item -ItemType Directory -Path "$origen\logs" -Force | Out-Null
Set-Content -Path "$origen\logs\last_backup.txt" -Value (Get-Date -Format "yyyy-MM-dd")
