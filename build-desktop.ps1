$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskBuildPython = if ($env:PAPERTAG_BUILD_PYTHON) { $env:PAPERTAG_BUILD_PYTHON } else { '.\.venv\Scripts\python.exe' }
& $taskBuildPython -m PyInstaller --noconfirm --clean --windowed --onedir --name LiteratureLibrary --add-data 'frontend;frontend' --add-data 'licenses;licenses' --collect-all webview --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.http.h11_impl --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on desktop.py
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
