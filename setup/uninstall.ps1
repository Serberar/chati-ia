# Deshace lo que install.ps1 cambio en Windows. No borra conversaciones ni modelos (lo pregunta el desinstalador).
param([Parameter(Mandatory = $true)] [string]$AiRoot)

$DataRoot = [Environment]::GetEnvironmentVariable("CHATI_DATA_ROOT", "User")
if (-not $DataRoot) { $DataRoot = "$env:LOCALAPPDATA\ChatiIA" }

& "$PSScriptRoot\stop_chati.ps1" -AiRoot $AiRoot

$tailscaleExe = "$env:ProgramFiles\Tailscale\tailscale.exe"
$mark = "$DataRoot\data\tailscale_publicado.txt"
if ((Test-Path $mark) -and (Test-Path $tailscaleExe)) {
    # solo si lo publicado sigue siendo Chati
    if ((& $tailscaleExe serve status 2>$null) -match "127\.0\.0\.1:8899") { & $tailscaleExe serve --https=443 off *> $null }
    Remove-Item $mark -ErrorAction SilentlyContinue
}

Remove-Item (Join-Path ([Environment]::GetFolderPath("Startup")) "IA-Personal-Watchdog.lnk") -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "Chati IA.lnk") -ErrorAction SilentlyContinue

# Solo se quitan las variables que apuntan a Chati.
$models = [Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "User")
$own = $models -and $models.StartsWith($DataRoot, "OrdinalIgnoreCase")
foreach ($name in "OLLAMA_MODELS", "HF_HOME", "CHATI_DATA_ROOT") {
    $value = [Environment]::GetEnvironmentVariable($name, "User")
    if ($value -and $value.StartsWith($DataRoot, "OrdinalIgnoreCase")) {
        [Environment]::SetEnvironmentVariable($name, $null, "User")
    }
}
if ($own) {
    foreach ($name in "OLLAMA_FLASH_ATTENTION", "HIP_VISIBLE_DEVICES") {
        [Environment]::SetEnvironmentVariable($name, $null, "User")
    }
}
