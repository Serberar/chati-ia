param(
    [string]$AiRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$DataRoot = $(if (Test-Path "$(Split-Path -Parent $PSScriptRoot)\.git") {  # copia de desarrollo, ver orchestrator/infra/paths.py
                               Split-Path -Parent $PSScriptRoot }
                           elseif ($env:CHATI_DATA_ROOT) { $env:CHATI_DATA_ROOT }
                           elseif ([Environment]::GetEnvironmentVariable("CHATI_DATA_ROOT", "User")) {
                               [Environment]::GetEnvironmentVariable("CHATI_DATA_ROOT", "User") }
                           elseif ($env:LOCALAPPDATA) { "$env:LOCALAPPDATA\ChatiIA" }
                           else { (Split-Path -Parent $PSScriptRoot) }),
    [switch]$Stay
)

function Test-Url($url) {
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
        return $resp.StatusCode -eq 200
    } catch {
        return $false
    }
}

Write-Host "=== Arrancando Ollama ===" -ForegroundColor Cyan
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Ollama.lnk" -ErrorAction SilentlyContinue
if (-not (Test-Url "http://127.0.0.1:11434/api/tags")) {
    $env:OLLAMA_FLASH_ATTENTION = "0"
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { $env:HIP_VISIBLE_DEVICES = "-1" }
    Start-Process -FilePath (Get-Command ollama).Source -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 2
} else {
    Write-Host "Ollama ya esta corriendo." -ForegroundColor Green
}

Write-Host "=== Arrancando ComfyUI ===" -ForegroundColor Cyan
if (-not (Test-Url "http://127.0.0.1:8188/system_stats")) {
    . "$PSScriptRoot\comfy_args.ps1"
    Start-Process -FilePath "$DataRoot\ComfyUI\venv\Scripts\python.exe" -ArgumentList (Get-ComfyArgs $AiRoot $DataRoot) -WorkingDirectory "$DataRoot\ComfyUI" -WindowStyle Hidden
    Write-Host "ComfyUI arrancando (tarda ~20-30s en estar listo)..." -ForegroundColor Yellow
} else {
    Write-Host "ComfyUI ya esta corriendo." -ForegroundColor Green
}

Write-Host "=== Arrancando el orquestador ===" -ForegroundColor Cyan
if (-not (Test-Url "http://127.0.0.1:8899/health")) {
    Write-Host "Esperando a que ComfyUI este listo antes de arrancar el orquestador..." -ForegroundColor Yellow
    $deadline = (Get-Date).AddSeconds(60)
    while (-not (Test-Url "http://127.0.0.1:8188/system_stats") -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
    }
    Start-Process -FilePath "$AiRoot\orchestrator\venv\Scripts\python.exe" `
        -ArgumentList "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8899" `
        -WorkingDirectory "$AiRoot\orchestrator" -WindowStyle Hidden
    Write-Host "Orquestador arrancando..." -ForegroundColor Yellow
} else {
    Write-Host "El orquestador ya esta corriendo." -ForegroundColor Green
}

Write-Host "=== Arrancando el agente de codigo (OpenCode) ===" -ForegroundColor Cyan
$ocFile = "$DataRoot\data\opencode_password.txt"
if (-not ((Test-Path $ocFile) -and (Get-Content $ocFile -Raw).Trim())) {
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    New-Item -ItemType Directory -Force -Path (Split-Path $ocFile) | Out-Null
    Set-Content -Path $ocFile -Encoding ascii -NoNewline `
        -Value ([Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_").TrimEnd("="))
}
$ocPassword = (Get-Content $ocFile -Raw).Trim()
$ocAuth = @{ Authorization = "Basic " + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("opencode:$ocPassword")) }
$ocUp = $false
try { $ocUp = (Invoke-WebRequest -Uri "http://127.0.0.1:8901/" -Headers $ocAuth -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } catch {}
if (-not $ocUp) {
    $env:OPENCODE_SERVER_PASSWORD = $ocPassword
    Start-Process -FilePath "$env:APPDATA\npm\opencode.cmd" -ArgumentList "serve", "--port", "8901", "--hostname", "127.0.0.1" `
        -WorkingDirectory $AiRoot -WindowStyle Hidden
    Write-Host "Agente de codigo arrancando..." -ForegroundColor Yellow
} else {
    Write-Host "El agente de codigo ya esta corriendo." -ForegroundColor Green
}

$watchdogScript = "$PSScriptRoot\watchdog.ps1"
$watchdogRunning = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like "*$watchdogScript*" }
if ($Stay -and -not $watchdogRunning) {
    Write-Host "=== Vigilando (este proceso sigue vivo) ===" -ForegroundColor Cyan
    & $watchdogScript
} elseif (-not $watchdogRunning) {
    Write-Host "=== Arrancando el vigilante ===" -ForegroundColor Cyan
    Start-Process -FilePath "conhost.exe" -WorkingDirectory $PSScriptRoot `
        -ArgumentList "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$watchdogScript`""
}

Start-Sleep -Seconds 5
Write-Host "`n=== Listo. Abre http://localhost:8899 en el navegador. ===" -ForegroundColor Cyan
