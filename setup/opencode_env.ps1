# Arranca OpenCode con la configuracion de Chati, sin usar ni cambiar la del usuario.
function Start-ChatiOpenCode($AiRoot, $DataRoot, $password) {
    $root = [Environment]::GetEnvironmentVariable("CHATI_DATA_ROOT", "User")
    if (-not (Test-Path "$DataRoot\opencode-config\opencode\opencode.json") -and $root) { $DataRoot = $root }
    $exe = "$env:APPDATA\npm\opencode.cmd"
    if (-not (Test-Path $exe)) { $exe = (Get-Command opencode -ErrorAction SilentlyContinue).Source }
    if (-not $exe) { return }
    $before = $env:XDG_CONFIG_HOME
    if (Test-Path "$DataRoot\opencode-config\opencode\opencode.json") { $env:XDG_CONFIG_HOME = "$DataRoot\opencode-config" }
    $env:OPENCODE_SERVER_PASSWORD = $password
    try {
        Start-Process -FilePath $exe -ArgumentList "serve", "--port", "8901", "--hostname", "127.0.0.1" `
            -WorkingDirectory $AiRoot -WindowStyle Hidden
    } finally {
        $env:XDG_CONFIG_HOME = $before
    }
}
