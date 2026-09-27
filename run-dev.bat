@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON_EXE=python"
set "INSTALL_COMMAND=python -m pip install -e .[dev]"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
    set "INSTALL_COMMAND=.venv\Scripts\python -m pip install -e .[dev]"
)

if not exist "launcher.py" (
    echo ERROR: launcher.py is missing. Run this script from a complete PgnExtractorGUI checkout.
    exit /b 1
)

if not exist "bin\pgn-extract.exe" (
    echo ERROR: Missing bin\pgn-extract.exe.
    echo        Supply the local pgn-extract v26-06 Windows executable before launching.
    exit /b 1
)

"%PYTHON_EXE%" --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python was not found.
    echo        Create .venv or install a supported Python release on PATH.
    exit /b 1
)

"%PYTHON_EXE%" -c "import fastapi, uvicorn, webview" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Required Python packages are not installed for this Python interpreter.
    echo        Install them explicitly with: %INSTALL_COMMAND%
    exit /b 1
)

"%PYTHON_EXE%" launcher.py
set "APP_EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %APP_EXIT_CODE%
