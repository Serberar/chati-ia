$AiRoot = Split-Path -Parent $PSScriptRoot
. "$PSScriptRoot\comfy_args.ps1"
. "$PSScriptRoot\opencode_env.ps1"
foreach ($name in "OLLAMA_MODELS", "CHATI_DATA_ROOT") {  # ver Update-EnvFromUser
    $value = [Environment]::GetEnvironmentVariable($name, "User")
    if ($value) { Set-Item -Path "Env:$name" -Value $value }
}
$DataRoot = if (Test-Path "$AiRoot\.git") { $AiRoot }
            elseif ($env:CHATI_DATA_ROOT) { $env:CHATI_DATA_ROOT }
                           elseif ([Environment]::GetEnvironmentVariable("CHATI_DATA_ROOT", "User")) {
                               [Environment]::GetEnvironmentVariable("CHATI_DATA_ROOT", "User") }
            elseif ($env:LOCALAPPDATA) { "$env:LOCALAPPDATA\ChatiIA" }
            else { $AiRoot }
$StateDir = "$DataRoot\data\logs"
New-Item -ItemType Directory -Path $StateDir -Force -ErrorAction SilentlyContinue | Out-Null
$LogFile = "$StateDir\watchdog.log"
$BackupMarker = "$StateDir\last_backup.txt"
if (-not (Test-Path $BackupMarker) -and (Test-Path "$PSScriptRoot\last_backup.txt")) {
    Copy-Item "$PSScriptRoot\last_backup.txt" $BackupMarker -ErrorAction SilentlyContinue  # de antes del cambio
}
$CheckIntervalSeconds = 30
$FailuresBeforeRestart = 2
$SlowStartFailures = 4
$Failures = @{}

function Write-Log($msg) {
    if ((Test-Path $LogFile) -and (Get-Item $LogFile).Length -gt 2MB) {
        Move-Item -Force $LogFile "$LogFile.old"
    }
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - $msg"
    Add-Content -Path $LogFile -Value $line
}

function Update-EnvFromUser {
    foreach ($name in "OLLAMA_MODELS", "CHATI_DATA_ROOT") {
        $value = [Environment]::GetEnvironmentVariable($name, "User")
        if ($value) { Set-Item -Path "Env:$name" -Value $value }
    }
}

function Test-Down($name, $url, $threshold = $FailuresBeforeRestart, $headers = @{}) {
    if (Test-Url $url $headers) {
        $Failures[$name] = 0
        return $false
    }
    $Failures[$name] = 1 + [int]$Failures[$name]
    if ($Failures[$name] -lt $threshold) {
        Write-Log "$name no responde (aviso $($Failures[$name])/$threshold)."
        return $false
    }
    $Failures[$name] = 0
    Update-EnvFromUser
    return $true
}

function Test-Url($url, $headers = @{}) {
    try {
        $resp = Invoke-WebRequest -Uri $url -Headers $headers -UseBasicParsing -TimeoutSec 5
        return $resp.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Get-OpenCodePassword {
    $file = "$DataRoot\data\opencode_password.txt"
    if (Test-Path $file) {
        $current = (Get-Content $file -Raw -ErrorAction Stop).Trim()
        if ($current) { return $current }
    }
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $password = [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_").TrimEnd("=")
    New-Item -ItemType Directory -Force -Path (Split-Path $file) | Out-Null
    Set-Content -Path $file -Value $password -NoNewline -Encoding ascii
    return $password
}

function Get-OpenCodeHeaders {
    $pair = [Text.Encoding]::ASCII.GetBytes("opencode:" + (Get-OpenCodePassword))
    return @{ Authorization = "Basic " + [Convert]::ToBase64String($pair) }
}

function Ensure-Ollama {
    if (Get-Process -Name "OllamaSetup*" -ErrorAction SilentlyContinue) {
        $Failures["Ollama"] = 0
        return
    }
    if (Test-Down "Ollama" "http://127.0.0.1:11434/api/tags" $SlowStartFailures) {
        Write-Log "Ollama caido. Reiniciando..."
        foreach ($c in Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue) {
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 1
        foreach ($p in Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" -ErrorAction SilentlyContinue) {
            if (-not (Get-Process -Id $p.ParentProcessId -ErrorAction SilentlyContinue)) {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
                Write-Log "Proceso de modelo huerfano cerrado ($($p.ProcessId))."
            }
        }
        $env:OLLAMA_FLASH_ATTENTION = "0"
        if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { $env:HIP_VISIBLE_DEVICES = "-1" }
        Start-Process -FilePath (Get-Command ollama -ErrorAction SilentlyContinue).Source -ArgumentList "serve" -WindowStyle Hidden
        Write-Log "Ollama reiniciado."
    }
}

function Stop-ByPort($port) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue
        if ($proc -and $proc.ParentProcessId) {
            Stop-Process -Id $proc.ParentProcessId -Force -ErrorAction SilentlyContinue
        }
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

function Ensure-ComfyUI {
    if (-not (Test-Path "$DataRoot\ComfyUI\venv\Scripts\python.exe")) { return }  # instalado sin imagenes
    if (Test-Down "ComfyUI" "http://127.0.0.1:8188/system_stats" $SlowStartFailures) {
        Write-Log "ComfyUI caido. Reiniciando..."
        Stop-ByPort 8188
        Start-Sleep -Seconds 2
        Start-Process -FilePath "$DataRoot\ComfyUI\venv\Scripts\python.exe" -ArgumentList (Get-ComfyArgs $AiRoot $DataRoot) `
            -WorkingDirectory "$DataRoot\ComfyUI" -WindowStyle Hidden
        Write-Log "ComfyUI reiniciado (tardara ~20-30s en responder)."
    }
}

function Ensure-Orchestrator {
    if (Test-Down "Orquestador" "http://127.0.0.1:8899/health") {
        Write-Log "Orquestador caido. Reiniciando..."
        Stop-ByPort 8899
        Start-Sleep -Seconds 2
        Start-Process -FilePath "$AiRoot\orchestrator\venv\Scripts\python.exe" `
            -ArgumentList "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8899" `
            -WorkingDirectory "$AiRoot\orchestrator" -WindowStyle Hidden
        Write-Log "Orquestador reiniciado."
    }
}

function Ensure-OpenCode {
    if (Test-Down "OpenCode" "http://127.0.0.1:8901/" $FailuresBeforeRestart (Get-OpenCodeHeaders)) {
        Write-Log "Agente de codigo (OpenCode) caido. Reiniciando..."
        Stop-ByPort 8901
        Start-Sleep -Seconds 1
        Start-ChatiOpenCode $AiRoot $DataRoot (Get-OpenCodePassword)
        Write-Log "Agente de codigo reiniciado."
    }
}

function Ensure-DailyBackup {
    $marker = $BackupMarker
    $today = Get-Date -Format "yyyy-MM-dd"
    if (-not (Test-Path $marker)) {
        # Recien instalada: aun no hay nada que copiar y reiniciaria Chati en el primer uso.
        New-Item -ItemType Directory -Path (Split-Path -Parent $marker) -Force | Out-Null
        Set-Content -Path $marker -Value $today
        return
    }
    $last = Get-Content $marker -Raw
    if ($last.Trim() -ne $today) {
        $hour = (Get-Date).Hour
        $overdue = $true
        try { $overdue = ((Get-Date) - [datetime]::ParseExact($last.Trim(), "yyyy-MM-dd", $null)).TotalDays -ge 2 } catch {}
        if (-not $overdue -and ($hour -lt 3 -or $hour -ge 7)) { return }
        try {
            $h = Invoke-RestMethod -Uri "http://127.0.0.1:8899/health?busy=true" -TimeoutSec 30
            if ($h.busy) { return }
        } catch {}  # orquestador caido: se puede copiar igualmente
        Write-Log "Backup diario pendiente. Ejecutando..."
        try {
            & powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\backup.ps1" *>> $LogFile
            Write-Log "Backup diario completado."
        } catch {
            Write-Log "Backup diario fallo: $_"
        }
    }
}

Write-Log "Watchdog iniciado."

while ($true) {
    foreach ($check in "Ensure-Ollama", "Ensure-ComfyUI", "Ensure-Orchestrator", "Ensure-OpenCode", "Ensure-DailyBackup") {
        try { & $check } catch { Write-Log "Fallo en ${check}: $_" }
    }
    Start-Sleep -Seconds $CheckIntervalSeconds
}
