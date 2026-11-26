param(
    [string]$AiRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$DataRoot = $(if ($env:LOCALAPPDATA) { "$env:LOCALAPPDATA\ChatiIA" } else { (Split-Path -Parent $PSScriptRoot) }),
    [ValidateSet("si", "no", "igual")] [string]$Autostart = "no",
    [ValidateSet("si", "no", "igual")] [string]$Tailscale = "no",   # publicar Chati en la red Tailscale del usuario
    [ValidateSet("si", "no", "igual")] [string]$ConImagen = "si"    # instalar ComfyUI y PyTorch (imagenes y video)
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path "$DataRoot\data\logs" -ErrorAction SilentlyContinue | Out-Null
# El instalador mira este archivo: si no esta al acabar, es que se corto y avisa.
$okFile = "$DataRoot\data\instalacion_ok.txt"
Remove-Item $okFile -Force -ErrorAction SilentlyContinue
try { Start-Transcript -Path "$DataRoot\data\logs\instalacion.log" -Append | Out-Null } catch {}
$ProgressPreference = "SilentlyContinue"

Write-Host "=== Instalando Chati IA ===" -ForegroundColor Cyan
Write-Host "Codigo: $AiRoot" -ForegroundColor Cyan
Write-Host "Datos y modelos: $DataRoot" -ForegroundColor Cyan

setx CHATI_DATA_ROOT "$DataRoot" | Out-Null
$env:CHATI_DATA_ROOT = $DataRoot

# Si el usuario ya tenia Ollama, es suyo: no se le cambia la carpeta de modelos ni se le cierra.
$userModels = [Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "User")
$OllamaPrevio = [bool](Get-Command ollama -ErrorAction SilentlyContinue)
$OllamaPropio = (-not $OllamaPrevio) -or ($userModels -and $userModels.StartsWith($DataRoot, "OrdinalIgnoreCase"))

New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
if (-not ([IO.Path]::GetFullPath($DataRoot).StartsWith([IO.Path]::GetFullPath($env:USERPROFILE), "OrdinalIgnoreCase"))) {
    $me = "${env:USERDOMAIN}\${env:USERNAME}"
    icacls $DataRoot /inheritance:r /grant:r "${me}:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" /Q | Out-Null
    if (Get-ChildItem -LiteralPath $DataRoot -Force) { icacls "$DataRoot\*" /reset /T /C /Q | Out-Null }
    Write-Host "Carpeta de datos restringida a $env:USERNAME (fuera del perfil de usuario)." -ForegroundColor Green
}

function Update-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}

function Install-Tool($name, $wingetId, $url, $signer, $installerArgs, [switch]$Msi, [int[]]$OkCodes = @(0),
                      [string]$FileName = "") {
    Write-Host "Instalando $name..." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id $wingetId -e --silent --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -eq 0) { Update-Path; return }
        Write-Host "winget no pudo instalar ${name}; se usa el instalador oficial." -ForegroundColor Yellow
    }
    $file = Join-Path $env:TEMP $(if ($FileName) { $FileName } else { Split-Path $url -Leaf })
    Write-Host "  Descargando $url ..." -ForegroundColor DarkGray
    Invoke-WebRequest -Uri $url -OutFile $file -UseBasicParsing
    $sig = Get-AuthenticodeSignature $file
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notlike "CN=$signer*") {
        Remove-Item $file -Force
        throw "El instalador de $name no tiene la firma esperada ($signer). No se ejecuta."
    }
    Write-Host "  Firma correcta ($signer). Instalando..." -ForegroundColor DarkGray
    if ($Msi) {
        $p = Start-Process msiexec.exe -ArgumentList "/i `"$file`" /qn /norestart" -PassThru
    } else {
        $p = Start-Process $file -ArgumentList $installerArgs -PassThru
    }
    $p.WaitForExit()
    Remove-Item $file -Force -ErrorAction SilentlyContinue
    if ($OkCodes -notcontains $p.ExitCode) { throw "El instalador de $name fallo (codigo $($p.ExitCode))." }
    Update-Path
}

$vcRuntime = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" -ErrorAction SilentlyContinue
if (-not ($vcRuntime -and $vcRuntime.Installed -eq 1)) {
    Install-Tool "Visual C++ (librerias de Microsoft)" "Microsoft.VCRedist.2015+.x64" `
        "https://aka.ms/vs/17/release/vc_redist.x64.exe" "Microsoft Corporation" "/install /quiet /norestart" `
        -OkCodes 0, 3010, 1638
} else {
    Write-Host "Librerias de Visual C++ ya instaladas." -ForegroundColor Green
}

$wv2 = @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
         "HKCU:\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}") |
    ForEach-Object { (Get-ItemProperty $_ -ErrorAction SilentlyContinue).pv } |
    Where-Object { $_ -and $_ -ne "0.0.0.0" }
if (-not $wv2) {
    Install-Tool "Motor de Edge (WebView2)" "Microsoft.EdgeWebView2Runtime" "https://go.microsoft.com/fwlink/p/?LinkId=2124703" `
        "Microsoft Corporation" "/silent /install" -FileName "MicrosoftEdgeWebview2Setup.exe"
} else {
    Write-Host "Motor de Edge (WebView2) ya instalado." -ForegroundColor Green
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Install-Tool "Ollama" "Ollama.Ollama" "https://github.com/ollama/ollama/releases/download/v0.34.4/OllamaSetup.exe" `
        "Ollama Inc" "/VERYSILENT /NORESTART /SUPPRESSMSGBOXES"
} else {
    Write-Host "Ollama ya instalado." -ForegroundColor Green
}

function Find-Python312 {
    $candidates = @()
    try { $candidates += (& py -3.12 -c "import sys; print(sys.executable)" 2>$null) } catch { }
    $candidates += "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", "$env:ProgramFiles\Python312\python.exe"
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c) -and ($c -notlike "*\WindowsApps\*")) {
            if (((& $c --version 2>&1) -join " ") -match "Python 3\.12\.") { return $c }
        }
    }
    return $null
}
$PythonExe = Find-Python312
if (-not $PythonExe) {
    Install-Tool "Python 3.12" "Python.Python.3.12" "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" `
        "Python Software Foundation" "/quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1 Include_test=0"
    $PythonExe = Find-Python312
    if (-not $PythonExe) { throw "No se encuentra Python 3.12 despues de instalarlo." }
}
Write-Host "Python: $PythonExe" -ForegroundColor Green

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Install-Tool "Git" "Git.Git" "https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.4/Git-2.55.0.4-64-bit.exe" `
        "Johannes Schindelin" "/VERYSILENT /NORESTART /NOCANCEL /SP- /SUPPRESSMSGBOXES"
} else {
    Write-Host "Git ya instalado." -ForegroundColor Green
}

if ($OllamaPropio) {
    setx OLLAMA_MODELS "$DataRoot\models\text" | Out-Null
    $env:OLLAMA_MODELS = "$DataRoot\models\text"
    Write-Host "OLLAMA_MODELS -> $DataRoot\models\text" -ForegroundColor Green
} else {
    if ($userModels) { $env:OLLAMA_MODELS = $userModels }
    Write-Host "Ya tenias Ollama: Chati usara tus modelos y no cambia su configuracion." -ForegroundColor Green
}

# Solo para este proceso: Chati la fija al arrancar (infra/paths.py), sin tocar la de otros programas.
$env:HF_HOME = "$DataRoot\models\voice\hf_cache"

$piperDir = "$DataRoot\models\voice\piper"
$piperOnnx = "$piperDir\es_ES-davefx-medium.onnx"
if (-not (Test-Path $piperOnnx)) {
    Write-Host "Descargando voz de Piper (es_ES-davefx-medium, ~63MB)..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $piperDir -Force | Out-Null
    $piperBase = "https://huggingface.co/rhasspy/piper-voices/resolve/c10ece1aade47bb51c153c893d14e5bf8e5b7117/es/es_ES/davefx/medium"
    Invoke-WebRequest -Uri "$piperBase/es_ES-davefx-medium.onnx" -OutFile $piperOnnx
    Invoke-WebRequest -Uri "$piperBase/es_ES-davefx-medium.onnx.json" -OutFile "$piperOnnx.json"
    $expected = @{
        $piperOnnx = "6658b03b1a6c316ee4c265a9896abc1393353c2d9e1bca7d66c2c442e222a917"
        "$piperOnnx.json" = "0e0dda87c732f6f38771ff274a6380d9252f327dca77aa2963d5fbdf9ec54842"
    }
    foreach ($f in $expected.Keys) {
        if ((Get-FileHash $f -Algorithm SHA256).Hash.ToLower() -ne $expected[$f]) {
            Remove-Item $f -Force
            throw "La voz de Piper descargada no coincide con la esperada ($f). Se ha borrado por seguridad."
        }
    }
    Write-Host "Voz de Piper descargada y comprobada." -ForegroundColor Green
} else {
    Write-Host "Voz de Piper ya presente, no se descarga de nuevo." -ForegroundColor Green
}

$env:OLLAMA_FLASH_ATTENTION = "0"
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { $env:HIP_VISIBLE_DEVICES = "-1" }
if ($OllamaPropio) {
    setx OLLAMA_FLASH_ATTENTION "0" | Out-Null
    Write-Host "OLLAMA_FLASH_ATTENTION -> 0 (fix GPUs Blackwell, ollama/ollama#18276)" -ForegroundColor Green
    if ($env:HIP_VISIBLE_DEVICES) { setx HIP_VISIBLE_DEVICES "-1" | Out-Null }
    Get-Process | Where-Object { $_.ProcessName -match "^ollama" } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}
$ollamaUp = $false
try { $ollamaUp = (Invoke-WebRequest "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } catch {}
if (-not $ollamaUp) {
    Start-Process -FilePath (Get-Command ollama).Source -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}
ollama list

$ComfyCommit = "30bdda1ef13a3a34fce2cd2fec633f15d832122a"
$TorchPackages = @("torch==2.12.0.dev20260408+cu128", "torchvision==0.27.0.dev20260407+cu128",
                   "torchaudio==2.11.0.dev20260407+cu128")
$OpenCodeVersion = "1.18.32"

function Install-Torch($python) {
    & $python -m pip install --pre @TorchPackages --index-url https://download.pytorch.org/whl/nightly/cu128
    if ($LASTEXITCODE -ne 0) {
        Write-Host "AVISO: la version probada de PyTorch ya no esta disponible; se instala la estable." -ForegroundColor Yellow
        & $python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
    }
}

function Set-PinnedCheckout($dir, $commit) {
    git -C $dir fetch --quiet origin $commit 2>$null
    git -C $dir checkout --quiet $commit
    if ($LASTEXITCODE -ne 0) { Write-Host "AVISO: no se pudo fijar $dir en $commit" -ForegroundColor Yellow }
}

$comfy = "$DataRoot\ComfyUI"
$InstalarComfy = ($ConImagen -eq "si") -or ($ConImagen -eq "igual" -and (Test-Path "$comfy\venv"))
if (-not $InstalarComfy) {
    Write-Host "Sin imagenes ni video: no se instala ComfyUI (vuelve a ejecutar el instalador para anadirlo)." -ForegroundColor Green
}
if ($InstalarComfy -and -not (Test-Path $comfy)) {
    Write-Host "Clonando ComfyUI..." -ForegroundColor Yellow
    git clone https://github.com/Comfy-Org/ComfyUI.git $comfy
    Set-PinnedCheckout $comfy $ComfyCommit
}

$comfyNodes = @{
    "ComfyUI-GGUF"           = @("https://github.com/city96/ComfyUI-GGUF.git", "6ea2651e7df66d7585f6ffee804b20e92fb38b8a")
    "ComfyUI-Manager"        = @("https://github.com/Comfy-Org/ComfyUI-Manager.git", "b75fc664ecab9c4602380d9660833d02f6a63333")
}
foreach ($name in $comfyNodes.Keys) {
    $nodeDir = "$comfy\custom_nodes\$name"
    if ($InstalarComfy -and -not (Test-Path $nodeDir)) {
        Write-Host "Clonando nodo personalizado $name..." -ForegroundColor Yellow
        git clone $comfyNodes[$name][0] $nodeDir
        Set-PinnedCheckout $nodeDir $comfyNodes[$name][1]
    }
}

if (-not $InstalarComfy) {
    Write-Host "Entorno de ComfyUI omitido." -ForegroundColor DarkGray
} elseif (-not (Test-Path "$comfy\venv")) {
    Write-Host "Creando entorno virtual de ComfyUI..." -ForegroundColor Yellow
    & $PythonExe -m venv "$comfy\venv"
    & "$comfy\venv\Scripts\python.exe" -m pip install --upgrade pip

    Install-Torch "$comfy\venv\Scripts\python.exe"

    & "$comfy\venv\Scripts\python.exe" -m pip install -r "$comfy\requirements.txt"

    foreach ($node in Get-ChildItem "$comfy\custom_nodes" -Directory -ErrorAction SilentlyContinue) {
        $req = Join-Path $node.FullName "requirements.txt"
        if (Test-Path $req) {
            & "$comfy\venv\Scripts\python.exe" -m pip install -r $req
        }
    }
    Write-Host "Entorno de ComfyUI creado." -ForegroundColor Green
} else {
    Write-Host "El venv de ComfyUI ya existe, no se toca." -ForegroundColor Green
}

$extraModelPaths = @'
# Rutas centralizadas de modelos - Chati IA
# Los pesos viven fuera de ComfyUI, organizados por agente (img/vid), para
# poder actualizarlos/copiarlos sin depender de la instalacion de ComfyUI.

img_models:
    base_path: {0}\models\img\
    checkpoints: checkpoints
    diffusion_models: diffusion_models
    text_encoders: text_encoders
    vae: vae
    clip_vision: clip_vision
    upscale_models: upscale_models

vid_models:
    base_path: {0}\models\vid\
    checkpoints: checkpoints
    diffusion_models: diffusion_models
    text_encoders: text_encoders
    vae: vae
'@ -f $DataRoot
$extraModelPathsFile = "$comfy\extra_model_paths.yaml"
if (-not (Test-Path $extraModelPathsFile)) {
    Set-Content -Path $extraModelPathsFile -Value $extraModelPaths -Encoding utf8
    Write-Host "extra_model_paths.yaml generado." -ForegroundColor Green
}

$orch = "$AiRoot\orchestrator"
if (Test-Path $orch) {
    $newVenv = -not (Test-Path "$orch\venv")
    if ($newVenv) {
        Write-Host "Creando entorno virtual del orquestador..." -ForegroundColor Yellow
        & $PythonExe -m venv "$orch\venv"
        & "$orch\venv\Scripts\python.exe" -m pip install --upgrade pip
    }

    $lockFile = "$orch\requirements.lock.txt"
    $lockStamp = "$orch\venv\chati_lock.sha256"
    $lockHash = (Get-FileHash $lockFile -Algorithm SHA256).Hash
    if ($newVenv -or -not (Test-Path $lockStamp) -or (Get-Content $lockStamp -Raw).Trim() -ne $lockHash) {
        Write-Host "Instalando las librerias del orquestador..." -ForegroundColor Yellow
        & "$orch\venv\Scripts\python.exe" -m pip install -r $lockFile
        if ($LASTEXITCODE -eq 0) {
            Set-Content -Path $lockStamp -Value $lockHash -NoNewline -Encoding ascii
        } else {
            Write-Host "AVISO: pip no pudo instalar todas las librerias (se reintenta en la proxima instalacion)." -ForegroundColor Yellow
        }
    } else {
        Write-Host "Librerias del orquestador al dia." -ForegroundColor Green
    }

    if ($newVenv) {
        & "$orch\venv\Scripts\python.exe" -m playwright install chromium
        Write-Host "Entorno del orquestador creado." -ForegroundColor Green
    }
} else {
    Write-Host "No se encontro $orch - copia la carpeta orchestrator antes de ejecutar esto." -ForegroundColor Red
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Install-Tool "Node.js" "OpenJS.NodeJS.LTS" "https://nodejs.org/dist/v24.19.0/node-v24.19.0-x64.msi" `
        "OpenJS Foundation" "" -Msi
} else {
    Write-Host "Node.js ya instalado." -ForegroundColor Green
}

if (-not (Get-Command opencode -ErrorAction SilentlyContinue)) {
    Write-Host "Instalando OpenCode..." -ForegroundColor Yellow
    npm install -g "opencode-ai@$OpenCodeVersion"
} else {
    Write-Host "OpenCode ya instalado." -ForegroundColor Green
}

# Carpeta propia (XDG_CONFIG_HOME al arrancar OpenCode): la configuracion de OpenCode del usuario no se toca.
$opencodeConfigDir = "$DataRoot\opencode-config\opencode"
if (-not (Test-Path $opencodeConfigDir)) {
    New-Item -ItemType Directory -Path $opencodeConfigDir -Force | Out-Null
}
$opencodeConfig = @'
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": { "baseURL": "http://127.0.0.1:8899/llm/v1", "apiKey": "{env:OPENCODE_SERVER_PASSWORD}",
                   "headerTimeout": 3600000 },
      "models": {
        "qwen2.5:7b": { "name": "Qwen2.5 7B (local, GPU)", "limit": { "context": 16384, "output": 4096 } },
        "qwen3:8b": { "name": "Qwen3 8B (local, GPU)", "limit": { "context": 16384, "output": 4096 } },
        "qwen3-coder:30b-cpu": { "name": "Qwen3 Coder 30B-A3B (local, CPU)", "limit": { "context": 32768, "output": 8192 } },
        "qwen3-coder:30b-mixto": { "name": "Qwen3 Coder 30B-A3B (local, CPU + 12 capas en GPU)", "limit": { "context": 32768, "output": 8192 } }
      }
    }
  },
  "model": "ollama/qwen3-coder:30b-mixto",
  "small_model": "ollama/qwen3-coder:30b-mixto",
  "compaction": { "auto": true, "prune": true },
  "shell": "powershell",
  "instructions": ["AGENTS.md", "__MEMORY_INDEX__"],
  "mcp": {
    "chati": { "type": "local", "command": ["__ORCH_PY__", "__ORCH_DIR__/agent_mcp.py"], "enabled": true,
               "timeout": 600000 }
  },
  "permission": {
    "edit": "ask",
    "webfetch": "ask",
    "todowrite": "allow",
    "chati_lanzar_programa": "ask",
    "chati_renombrar": "ask",
    "chati_editar_bloque": "ask",
    "chati_entorno_python": "ask",
    "chati_plantilla": "ask",
    "bash": {
      "*": "ask",
      "python -m pytest*": "allow", "pytest*": "allow",
      "git status*": "allow", "git diff*": "allow", "git log*": "allow",
      "git show*": "allow", "git branch*": "allow", "git remote -v*": "allow", "git blame*": "allow",
      "Get-ChildItem*": "allow", "Get-Content*": "allow", "Select-String*": "allow", "Test-Path*": "allow",
      "Get-Location*": "allow", "Resolve-Path*": "allow", "Get-Item *": "allow", "Measure-Object*": "allow",
      "python --version*": "allow", "python -V*": "allow", "pip list*": "allow", "pip show*": "allow",
      "pip index versions*": "allow", "node --version*": "allow", "npm --version*": "allow",
      "npm ls*": "allow", "npm outdated*": "allow", "npm view*": "allow",
      "git push*": "ask", "git reset --hard*": "ask", "git clean*": "ask",
      "rm *": "ask", "rm -rf*": "ask", "del *": "ask", "Remove-Item*": "ask"
    }
  },
  "agent": {
    "build": { "temperature": 0.1 },
    "plan": { "temperature": 0.1 },
    "chati": {
      "description": "Agente de Chati IA: tareas sobre los archivos del usuario (rapido, GPU)",
      "mode": "primary", "model": "ollama/qwen3:8b", "temperature": 0.1,
      "prompt": "{file:./chati_agent_prompt.md}",
      "tools": { "task": false, "todowrite": false, "webfetch": false, "skill": false, "write": false, "glob": false, "chati_*": false,
                 "chati_probar_programa": true, "chati_compilar_exe": true }
    },
    "chati-potente": {
      "description": "Agente de Chati IA con el modelo grande (lento, CPU) para tareas complejas",
      "mode": "primary", "model": "ollama/qwen3-coder:30b-mixto", "temperature": 0.1,
      "prompt": "{file:./chati_agent_prompt.md}",
      "tools": { "task": false, "webfetch": false, "skill": false, "glob": false, "chati_*": false,
                 "chati_probar_programa": true, "chati_compilar_exe": true, "chati_plantilla": true,
                 "chati_entorno_python": true, "chati_ver_ventana": true, "chati_docs": true }
    },
    "chati-code": {
      "description": "Chati modo Codigo: programa en el proyecto del usuario (construir)",
      "mode": "primary", "model": "ollama/qwen3-coder:30b-mixto", "temperature": 0.1,
      "prompt": "{file:./chati_code_prompt.md}",
      "tools": { "task": false, "webfetch": false, "skill": false }
    },
    "chati-code-plan": {
      "description": "Chati modo Codigo: analiza el proyecto y propone, sin cambiar nada (planificar)",
      "mode": "primary", "model": "ollama/qwen3-coder:30b-mixto", "temperature": 0.1,
      "prompt": "{file:./chati_code_plan_prompt.md}",
      "tools": { "task": false, "webfetch": false, "skill": false, "edit": false, "write": false, "patch": false,
                 "chati_lanzar_programa": false, "chati_renombrar": false, "chati_usar_web": false,
                 "chati_editar_bloque": false, "chati_entorno_python": false, "chati_plantilla": false }
    }
  }
}
'@
Copy-Item "$PSScriptRoot\chati_agent_prompt.md" "$opencodeConfigDir\chati_agent_prompt.md" -Force
Copy-Item "$PSScriptRoot\chati_code_prompt.md" "$opencodeConfigDir\chati_code_prompt.md" -Force
Copy-Item "$PSScriptRoot\chati_code_plan_prompt.md" "$opencodeConfigDir\chati_code_plan_prompt.md" -Force
$memoryDir = "$DataRoot\data\agente_memoria"
if (-not (Test-Path $memoryDir)) { New-Item -ItemType Directory -Path $memoryDir -Force | Out-Null }
if (-not (Test-Path "$memoryDir\MEMORY.md")) {
    Set-Content -Path "$memoryDir\MEMORY.md" -Value "# Memoria del agente de codigo de Chati`n(vacia)" -Encoding utf8
}
$opencodeConfig = $opencodeConfig.Replace("__ORCH_PY__", "$orch\venv\Scripts\python.exe".Replace("\", "/")).
    Replace("__ORCH_DIR__", $orch.Replace("\", "/")).
    Replace("__MEMORY_INDEX__", "$memoryDir\MEMORY.md".Replace("\", "/"))
Set-Content -Path "$opencodeConfigDir\opencode.json" -Value $opencodeConfig -Encoding utf8
Write-Host "Config de OpenCode escrita en $opencodeConfigDir\opencode.json" -ForegroundColor Green

$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut("$desktop\Chati IA.lnk")
if (Test-Path "$AiRoot\ChatiIA\ChatiIA.exe") {
    $shortcut.TargetPath = "$AiRoot\ChatiIA\ChatiIA.exe"
    $shortcut.WorkingDirectory = "$AiRoot\ChatiIA"
} else {
    $shortcut.TargetPath = "$AiRoot\orchestrator\venv\Scripts\pythonw.exe"
    $shortcut.Arguments = "`"$AiRoot\orchestrator\desktop_app.py`""
    $shortcut.WorkingDirectory = "$AiRoot\orchestrator"
}
$shortcut.IconLocation = "$AiRoot\icono.ico"
$shortcut.Save()
Write-Host "Acceso directo 'Chati IA' creado en el escritorio." -ForegroundColor Green

$startupLink = Join-Path ([Environment]::GetFolderPath("Startup")) "IA-Personal-Watchdog.lnk"
if ($Autostart -eq "si" -or ($Autostart -eq "igual" -and (Test-Path $startupLink))) {
    & powershell -ExecutionPolicy Bypass -File "$AiRoot\setup\install_watchdog.ps1"
} elseif ($Autostart -eq "no") {
    Remove-Item $startupLink -ErrorAction SilentlyContinue
    Write-Host "Chati no arrancara al iniciar Windows (se puede cambiar en Opciones)." -ForegroundColor Green
}

$tailscaleExe = "$env:ProgramFiles\Tailscale\tailscale.exe"
if ($Tailscale -ne "si") {
    Write-Host "Chati no se publica en Tailscale (install.ps1 -Tailscale si para usarla desde el movil)." -ForegroundColor DarkGray
} elseif (Test-Path $tailscaleExe) {
    # En PowerShell 5.1, con "Stop", un aviso por stderr cortaria la instalacion.
    $ErrorActionPreference = "Continue"
    & $tailscaleExe status *> $null
    if ($LASTEXITCODE -eq 0) {
        & $tailscaleExe serve --bg http://127.0.0.1:8899
        if ($LASTEXITCODE -eq 0) {
            Set-Content -Path "$DataRoot\data\tailscale_publicado.txt" -Value "si" -Encoding ascii
            Write-Host "Chati publicada en Tailscale (solo para tus dispositivos)." -ForegroundColor Green
        } else {
            Write-Host "AVISO: no se pudo publicar Chati en Tailscale (tailscale serve)." -ForegroundColor Yellow
        }
    } else {
        Write-Host "Tailscale instalado pero sin sesion: inicia sesion y vuelve a ejecutar install.ps1 para usar Chati desde el movil." -ForegroundColor Yellow
    }
} else {
    Write-Host "Tailscale no esta instalado: para usar Chati desde el movil, instalalo (tailscale.com) y vuelve a ejecutar install.ps1." -ForegroundColor Yellow
}

$ErrorActionPreference = "Stop"
Set-Content -Path $okFile -Value (Get-Date -Format "yyyy-MM-dd HH:mm:ss") -Encoding ascii
Write-Host "`n=== Listo. Modelos de texto/codigo disponibles via 'ollama list'. ===" -ForegroundColor Cyan
Write-Host "Para arrancar todo: doble clic en 'Chati IA' del escritorio," -ForegroundColor Cyan
Write-Host "o powershell -ExecutionPolicy Bypass -File $AiRoot\setup\start_all.ps1" -ForegroundColor Cyan
Write-Host "Los datos de usuarios se generan solos en $DataRoot\data la primera vez que arranca el orquestador." -ForegroundColor Cyan
