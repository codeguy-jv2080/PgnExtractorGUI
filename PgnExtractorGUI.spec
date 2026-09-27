# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller definition for the self-contained, one-directory Windows build.
# The build script performs the same preflight checks so missing prerequisites
# fail before PyInstaller starts collecting files.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path(SPECPATH).resolve()
entry_point = project_root / "launcher.py"
static_dir = project_root / "app" / "static"
resources_dir = project_root / "resources"
pgn_extract_binary = project_root / "bin" / "pgn-extract.exe"
project_license = project_root / "LICENSE"
third_party_notices = project_root / "THIRD_PARTY_NOTICES.md"
third_party_licenses = project_root / "build" / "third_party_licenses"
readme = project_root / "README.md"

required_paths = (
    entry_point,
    static_dir,
    resources_dir,
    pgn_extract_binary,
    project_license,
    third_party_notices,
    third_party_licenses,
    readme,
)
missing_paths = [str(path.relative_to(project_root)) for path in required_paths if not path.exists()]
if missing_paths:
    raise SystemExit(
        "Cannot build PgnExtractorGUI. Missing required project files: "
        + ", ".join(missing_paths)
        + ". Install/copy the local prerequisites; the build does not download them."
    )

datas = [
    (str(static_dir), "app/static"),
    (str(resources_dir), "resources"),
    (str(pgn_extract_binary), "bin"),
]
datas += collect_data_files("webview")

# pywebview selects a native Windows backend dynamically. Collect its runtime
# modules, but not its build-time PyInstaller hook package: freezing that hook
# pulls PyInstaller and development-only dependencies into the application.
hiddenimports = [
    module for module in collect_submodules("webview") if not module.startswith("webview.__pyinstaller")
]

a = Analysis(
    [str(entry_point)],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PgnExtractorGUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PgnExtractorGUI",
)
