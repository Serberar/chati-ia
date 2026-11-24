$scriptPath = "$PSScriptRoot\watchdog.ps1"
$startupFolder = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupFolder "IA-Personal-Watchdog.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "conhost.exe"
$shortcut.Arguments = "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.WindowStyle = 7  # minimizado
$shortcut.Description = "Vigila y reinicia Ollama/ComfyUI/orquestador si se caen"
$shortcut.Save()

if (Test-Path $shortcutPath) {
    Write-Host "Acceso directo creado: $shortcutPath" -ForegroundColor Green
    Write-Host "El vigilante arrancara solo la proxima vez que inicies sesion en Windows." -ForegroundColor Green
    Write-Host "Para quitarlo: borra ese archivo .lnk." -ForegroundColor Yellow
} else {
    Write-Host "ERROR: no se pudo crear el acceso directo." -ForegroundColor Red
    exit 1
}
