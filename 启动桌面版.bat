@echo off
cd /d "%~dp0"
if exist "dist\LiteratureLibrary\LiteratureLibrary.exe" (
    start "" "dist\LiteratureLibrary\LiteratureLibrary.exe"
) else (
    start "" ".venv\Scripts\pythonw.exe" "desktop.py"
)
