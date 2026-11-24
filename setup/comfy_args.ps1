function Get-ComfyArgs($AiRoot, $DataRoot) {
    $installedRoot = [Environment]::GetEnvironmentVariable("CHATI_DATA_ROOT", "User")
    if (-not $installedRoot) { $installedRoot = "$env:LOCALAPPDATA\ChatiIA" }
    $installedYaml = "$installedRoot\ComfyUI\extra_model_paths.yaml"
    if ((Test-Path "$AiRoot\.git") -and ($installedRoot -ne $DataRoot) -and (Test-Path $installedYaml)) {
        return @("main.py", "--extra-model-paths-config", "`"$installedYaml`"")
    }
    return @("main.py")
}
