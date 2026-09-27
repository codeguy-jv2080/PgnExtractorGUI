@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON_EXE=python"
set "INSTALL_COMMAND=python -m pip install -e .[build]"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
    set "INSTALL_COMMAND=.venv\Scripts\python -m pip install -e .[build]"
)

if not exist "launcher.py" (
    echo ERROR: launcher.py is missing. Run this script from a complete PgnExtractorGUI checkout.
    exit /b 1
)

if not exist "PgnExtractorGUI.spec" (
    echo ERROR: PgnExtractorGUI.spec is missing.
    exit /b 1
)

if not exist "bin\pgn-extract.exe" (
    echo ERROR: Missing bin\pgn-extract.exe.
    echo        A local pgn-extract v26-06 Windows executable is required.
    echo        This script never downloads or builds pgn-extract automatically.
    exit /b 1
)

if not exist "resources\pgn-extract\VERSION.txt" (
    echo ERROR: resources\pgn-extract\VERSION.txt is missing.
    exit /b 1
)

findstr /c:"26-06" "resources\pgn-extract\VERSION.txt" >nul
if errorlevel 1 (
    echo ERROR: VERSION.txt does not declare the required pgn-extract v26-06 target.
    exit /b 1
)

"%PYTHON_EXE%" --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python was not found.
    echo        Create .venv or install a supported Python release on PATH.
    exit /b 1
)

"%PYTHON_EXE%" -c "import PyInstaller, fastapi, uvicorn, webview" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Build dependencies are not installed for this Python interpreter.
    echo        Install them explicitly with: %INSTALL_COMMAND%
    exit /b 1
)

"%PYTHON_EXE%" "tools\verify_bundled_backend.py" "bin\pgn-extract.exe" "resources\pgn-extract\VERSION.txt"
if errorlevel 1 (
    echo ERROR: The bundled pgn-extract executable failed release hygiene checks.
    exit /b 1
)

"%PYTHON_EXE%" "tools\collect_third_party_licenses.py" "build\third_party_licenses"
if errorlevel 1 (
    echo ERROR: Third-party license material could not be collected.
    exit /b 1
)

echo Building a local one-directory Windows package...
echo Existing generated build and dist folders for this project may be replaced.
"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean "PgnExtractorGUI.spec"
set "BUILD_EXIT_CODE=%ERRORLEVEL%"

if not "%BUILD_EXIT_CODE%"=="0" (
    echo ERROR: Packaging failed.
    endlocal & exit /b %BUILD_EXIT_CODE%
)

copy /y "README.md" "dist\PgnExtractorGUI\README.md" >nul
if errorlevel 1 (
    echo ERROR: README.md could not be added to the Windows package.
    exit /b 1
)

copy /y "LICENSE" "dist\PgnExtractorGUI\LICENSE" >nul
if errorlevel 1 (
    echo ERROR: LICENSE could not be added to the Windows package.
    exit /b 1
)

copy /y "THIRD_PARTY_NOTICES.md" "dist\PgnExtractorGUI\THIRD_PARTY_NOTICES.md" >nul
if errorlevel 1 (
    echo ERROR: THIRD_PARTY_NOTICES.md could not be added to the Windows package.
    exit /b 1
)

xcopy /e /i /q /y "build\third_party_licenses" "dist\PgnExtractorGUI\THIRD_PARTY_LICENSES" >nul
if errorlevel 2 (
    echo ERROR: Third-party license material could not be added to the Windows package.
    exit /b 1
)

"%PYTHON_EXE%" "tools\verify_bundled_backend.py" "dist\PgnExtractorGUI\_internal\bin\pgn-extract.exe" "resources\pgn-extract\VERSION.txt"
if errorlevel 1 (
    echo ERROR: The packaged pgn-extract executable failed release hygiene checks.
    exit /b 1
)

echo.
echo Build complete: dist\PgnExtractorGUI\PgnExtractorGUI.exe
endlocal & exit /b 0
