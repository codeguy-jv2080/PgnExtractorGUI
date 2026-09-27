"""Stable paths for the application installation and per-user state.

The application must be launchable from a shortcut, a batch file, or a
PyInstaller bundle.  For that reason these paths are based on the location of
the application rather than the process working directory.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "PgnExtractorGUI"
DATA_DIR_ENV_VAR = "PGN_EXTRACTOR_GUI_DATA_DIR"
ROOT_DIR_ENV_VAR = "PGN_EXTRACTOR_GUI_ROOT"


def _application_root() -> Path:
    """Return the directory containing the installed application resources.

    ``PGN_EXTRACTOR_GUI_ROOT`` is intentionally supported for portable and
    test installs.  It is never written by the application.  A frozen
    PyInstaller app may keep bundled resources in ``_MEIPASS``; source runs
    use the repository root (the parent of ``app``).
    """

    override = os.environ.get(ROOT_DIR_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()

    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root).resolve()

    return Path(__file__).resolve().parent.parent


def _default_data_dir() -> Path:
    """Return the Windows per-user local application-data directory.

    LOCALAPPDATA is present on supported Windows versions.  The fallback keeps
    development and non-Windows test runs predictable without writing into the
    repository.
    """

    override = os.environ.get(DATA_DIR_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data).expanduser().resolve() / APP_NAME

    return Path.home() / ".local" / "share" / APP_NAME


@dataclass(frozen=True)
class AppPaths:
    """All file locations used by the application.

    ``data_dir`` contains only GUI metadata: settings, saved presets, bounded
    run history, backups, and temporary run folders.  It never contains a copy
    of an input PGN file unless a future caller explicitly places one there.
    """

    root_dir: Path
    data_dir: Path

    @property
    def app_dir(self) -> Path:
        """Alias retained for callers that describe this as the app directory."""

        return self.root_dir

    @property
    def binary_dir(self) -> Path:
        return self.root_dir / "bin"

    @property
    def bundled_binary_path(self) -> Path:
        return self.binary_dir / "pgn-extract.exe"

    @property
    def legacy_binary_path(self) -> Path:
        """Legacy root-level executable, used only as a verified fallback."""

        return self.root_dir / "pgn-extract.exe"

    @property
    def resources_dir(self) -> Path:
        return self.root_dir / "resources" / "pgn-extract"

    @property
    def eco_file(self) -> Path:
        return self.resources_dir / "eco.pgn"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "pgn_extractor_gui.sqlite3"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def run_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_data_directories(self) -> None:
        """Create state directories, without touching PGN files or binaries."""

        for directory in (self.data_dir, self.backup_dir, self.run_dir, self.log_dir):
            directory.mkdir(parents=True, exist_ok=True)


def get_app_paths(
    *,
    root_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> AppPaths:
    """Build an :class:`AppPaths` object without creating any directories."""

    resolved_root = (
        Path(root_dir).expanduser().resolve() if root_dir is not None else _application_root()
    )
    resolved_data = (
        Path(data_dir).expanduser().resolve() if data_dir is not None else _default_data_dir()
    )
    return AppPaths(root_dir=resolved_root, data_dir=resolved_data)


__all__ = [
    "APP_NAME",
    "DATA_DIR_ENV_VAR",
    "ROOT_DIR_ENV_VAR",
    "AppPaths",
    "get_app_paths",
]
