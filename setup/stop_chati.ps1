param([Parameter(Mandatory = $true)] [string]$AiRoot, [switch]$All)

$root = [IO.Path]::GetFullPath($AiRoot).TrimEnd("\") + "\"
$watchdog = [regex]::Escape("$root" + "setup\") + "(watchdog|start_all)\.ps1"

function Get-ChatiProcesses {
    Get-CimInstance Win32_Process | Where-Object {
        ($_.CommandLine -match $watchdog) -or
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($root, "OrdinalIgnoreCase"))
    }
}

foreach ($p in Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match $watchdog }) {
    if ($All) { taskkill.exe /PID $p.ProcessId /T /F *> $null }
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
foreach ($p in Get-ChatiProcesses) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
foreach ($port in 8899, 8901) {
    foreach ($c in Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}
if ($All) {
    foreach ($c in Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue) {
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue
        $parent = if ($parent) { Get-Process -Id $parent.ParentProcessId -ErrorAction SilentlyContinue }
        if ($parent -and $parent.Name -eq "python") { Stop-Process -Id $parent.Id -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Get-Process -Name "ollama app", "ollama", "llama-server" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

$deadline = (Get-Date).AddSeconds(20)
while ((Get-ChatiProcesses) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
