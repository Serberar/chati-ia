param(
    [string]$AiRoot = (Split-Path -Parent $PSScriptRoot)
)

Start-Process -FilePath "$AiRoot\orchestrator\venv\Scripts\pythonw.exe" `
    -ArgumentList "`"$AiRoot\orchestrator\desktop_app.py`"" -WorkingDirectory "$AiRoot\orchestrator"
