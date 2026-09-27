"""Shared backend support for the local PgnExtractorGUI application.

The package deliberately keeps user state outside the installation directory.
PGN data is processed by the external ``pgn-extract`` executable and is never
copied into this package's SQLite database.
"""

from .paths import APP_NAME, AppPaths, get_app_paths

__all__ = ["APP_NAME", "AppPaths", "get_app_paths"]
