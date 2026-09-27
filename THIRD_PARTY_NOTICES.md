# Third-party notices

PgnExtractorGUI is licensed under GPL-3.0-or-later. This file identifies the
third-party components carried by the Windows release. It is a notice document,
not legal advice.

## License material included with each Windows package

Every packaged Windows release includes the following at its top level:

- `LICENSE` — the PgnExtractorGUI GPL-3.0-or-later license.
- `THIRD_PARTY_NOTICES.md` — this overview.
- `THIRD_PARTY_LICENSES/MANIFEST.txt` — the exact Python package/version
  inventory used for that build.
- `THIRD_PARTY_LICENSES/` — license files copied from the installed package
  metadata, plus the active Python runtime's `LICENSE.txt`.

`tools/collect_third_party_licenses.py` generates that bundle before PyInstaller
runs. It intentionally includes notices for every installed Python distribution
in the build environment, including build-only packages, rather than risk
omitting a package that PyInstaller collected. The build fails if an installed
distribution does not provide license material and has no checked-in override.

## pgn-extract

- Project: pgn-extract, Portable Game Notation (PGN) Manipulator for Chess Games
- Target version: 26-06
- License: GNU General Public License, version 3 or later
- Exact source revision: https://github.com/kentdjb/pgn-extract/tree/e69e863b70f2fb8ed7916752db95e1c771daf4f0
- Exact source archive: https://github.com/kentdjb/pgn-extract/archive/e69e863b70f2fb8ed7916752db95e1c771daf4f0.tar.gz

The pgn-extract v26-06 runtime backend is included at
`_internal/bin/pgn-extract.exe` in a Windows package. Its matching GPL text is
included at `_internal/resources/pgn-extract/COPYING.txt`. The bundled binary's
target revision and SHA-256 are recorded in
`_internal/resources/pgn-extract/VERSION.txt`.

The local pgn-extract source checkout is read-only reference material for this
project and is not modified by PgnExtractorGUI.

## Python runtime and frozen packages

The Windows package is built with Python, PyInstaller, FastAPI, Uvicorn,
pywebview, and their installed dependencies. The exact package versions and
license files for the build are in `THIRD_PARTY_LICENSES/`. The included Python
license text also carries notices for components supplied with that Python
runtime, including OpenSSL and libffi where applicable.

The package can contain Microsoft WebView2, .NET, and Visual C++ runtime
components required by pywebview, pythonnet, or the Python runtime. Those
components retain their own terms. Their upstream licensing information is
available from Microsoft WebView2 (https://developer.microsoft.com/microsoft-edge/webview2/)
and .NET (https://github.com/dotnet/runtime/blob/main/LICENSE.TXT).

## SQLite

- Project: SQLite
- Upstream: https://www.sqlite.org/
- License: Public domain

SQLite stores local application settings, saved presets, and run history. It
does not receive or transmit PGN data.

## Rebuilding or redistributing

Anyone distributing a package containing pgn-extract must meet the applicable
GPL-3.0-or-later obligations, including providing corresponding source as
required. Anyone rebuilding this application should run `build-windows.bat`,
which regenerates the bundled license inventory for the exact local build
environment.
