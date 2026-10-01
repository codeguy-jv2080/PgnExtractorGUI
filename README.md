# PgnExtractorGUI

PgnExtractorGUI is a standalone, local Windows GUI frontend for the
[pgn-extract](https://www.cs.kent.ac.uk/people/staff/djb/pgn-extract/) command-line
program. It presents selected pgn-extract options in a desktop interface, previews
the constructed command, and invokes the executable locally. It does not require a
cloud service or transmit PGN files.

The GUI code lives entirely in this repository. The separate local pgn-extract
repository is a read-only reference and must not be modified by this project.

## Download the Windows app

[Download PgnExtractorGUI for Windows x64](https://github.com/codeguy-jv2080/PgnExtractorGUI/releases/download/v0.1.0/PgnExtractorGUI-v0.1.0-windows-x64.zip).

Choose **Extract All**, open the extracted `PgnExtractorGUI` folder, and run
**PgnExtractorGUI.exe**. Keep its `_internal` folder and the other supplied files
together. The download includes Python and the pgn-extract backend; no development
setup is required.

The repository's **Code > Download ZIP** and release **Source code** links contain
the source project. Use the Windows app download above to run the packaged program.

## Architecture

- A Python FastAPI backend serves the local application UI and runs the bundled
  pgn-extract backend with an argument list rather than a shell command.
- pywebview hosts the local UI in a Windows desktop window.
- SQLite stores app settings, saved presets, and limited run history under
  %LOCALAPPDATA%\PgnExtractorGUI. PGN input files and their contents are not copied
  into that database.
- The packaged executable includes the app UI, resources, and the supplied
  pgn-extract executable in a one-directory distribution.

## Repository layout

    PgnExtractorGUI/
      app/                         FastAPI backend and static UI
      bin/pgn-extract.exe          Bundled pgn-extract v26-06 runtime backend
      resources/pgn-extract/       Bundled ECO data, GPL notice, and version record
      launcher.py                  Desktop application entry point
      run-dev.bat                  Development launcher; does not install packages
      build-windows.bat            PyInstaller one-directory build; does not download
      PgnExtractorGUI.spec         PyInstaller definition

## Required pgn-extract version

This checkout bundles a Windows pgn-extract v26-06 executable at:

    bin\pgn-extract.exe

The matching upstream source revision is
[e69e863 (v26-06)](https://github.com/kentdjb/pgn-extract/tree/e69e863b70f2fb8ed7916752db95e1c771daf4f0).
Its direct source archive is
[available from GitHub](https://github.com/kentdjb/pgn-extract/archive/e69e863b70f2fb8ed7916752db95e1c771daf4f0.tar.gz).

The application first honors a user-configured compatible executable, then uses the
bundled binary above. A root-level pgn-extract.exe is only a compatibility-checked
fallback; an older v26-04 copy is rejected. Neither batch script modifies or deletes
that root-level file.

The pgn-extract reference repository remains read-only input for this work. To
replace or upgrade the bundled backend, build the reference source separately or
obtain a trusted matching Windows binary, then deliberately replace only:

    bin\pgn-extract.exe

Verify the bundled backend before use:

    .\bin\pgn-extract.exe --version

The matching upstream ECO file is bundled at resources\pgn-extract\eco.pgn and is
included in the Windows distribution with the executable.

## Development setup

Use a supported Windows Python installation (Python 3.10 or newer). The commands
below intentionally perform dependency installation only when you run them; neither
batch script downloads anything automatically.

    python -m venv .venv
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\python -m pip install -e ".[dev]"
    .venv\Scripts\python launcher.py

You can also run run-dev.bat directly. It automatically uses
.venv\Scripts\python.exe when that interpreter exists, and otherwise falls back to
python on PATH:

    run-dev.bat

The launcher checks for the supplied pgn-extract binary before the GUI starts.

## Build a Windows package

With the v26-06 binary in place:

    .venv\Scripts\python -m pip install -e ".[build]"
    build-windows.bat

build-windows.bat automatically prefers .venv\Scripts\python.exe when available.

The output is:

    dist\PgnExtractorGUI\PgnExtractorGUI.exe

The build is a one-directory package containing the FastAPI/pywebview application,
the pgn-extract v26-06 backend, its bundled ECO/GPL resources, and a
`THIRD_PARTY_LICENSES` folder describing the exact Python build environment.

The packaged Windows executable is not code-signed. Windows SmartScreen or another
reputation-based security prompt may therefore appear on first launch. It deliberately
fails if the local binary, application files, or build dependencies are missing. It
never fetches binaries, dependencies, or source code itself. Rebuilding replaces
generated project build and dist folders but does not alter SQLite user data in
%LOCALAPPDATA%.

## Data safety

The application should preserve source PGN files. It uses explicit output paths and
confirms overwrite or append actions before invoking pgn-extract options that can
change an existing output file. User settings are kept separately from project files
so rebuilding or deleting dist does not destroy them.

## Tests

Once the application modules are present, run:

    python -m pytest

The package configuration also supports:

    python -m ruff check .

## Third-party notices

See THIRD_PARTY_NOTICES.md. In particular, anyone distributing a package that
contains pgn-extract must meet its upstream GPL-3.0-or-later obligations, including
providing the applicable license and corresponding source as required. The exact
v26-06 source revision and archive are linked above and in the notice file.

## License

PgnExtractorGUI is licensed under GPL-3.0-or-later. See `LICENSE` and
`THIRD_PARTY_NOTICES.md`. The bundled pgn-extract backend and other third-party
components retain their own applicable notices and license terms.
