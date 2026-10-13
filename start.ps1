$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$literaturePython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $literaturePython)) {
    python -m venv .venv
    & $literaturePython -m pip install -r requirements.txt
}
Write-Host '科研文献库: http://127.0.0.1:8765'
Write-Host '关闭此窗口或按 Ctrl+C 停止。不会自动导入文献。'
& $literaturePython -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
