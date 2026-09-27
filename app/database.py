"""SQLite setup and safe schema migration support.

Only GUI metadata is stored here.  In particular, this module never imports,
copies, or stores the contents of PGN input/output files.  Before changing an
existing database schema it verifies the database and writes a SQLite backup
alongside the user's local application data.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .paths import AppPaths

SCHEMA_VERSION = 1
DEFAULT_BUSY_TIMEOUT_MS = 5_000


class DatabaseError(RuntimeError):
    """Base class for database initialization and migration errors."""


class DatabaseIntegrityError(DatabaseError):
    """Raised when SQLite reports a damaged database before a migration."""


class DatabaseSchemaError(DatabaseError):
    """Raised when a database is not a schema this application understands."""


class DatabaseMigrationError(DatabaseError):
    """Raised when a schema migration cannot be completed safely."""


@dataclass(frozen=True)
class InitializationReport:
    """Outcome of :meth:`Database.initialize`.

    ``backup_path`` is populated only when an existing database was upgraded.
    A backup is intentionally retained; this app never prunes user backups.
    """

    database_path: Path
    schema_version: int
    created: bool
    backup_path: Path | None
    integrity_result: tuple[str, ...]


_APP_TABLES = frozenset({"app_meta", "settings", "presets", "run_history"})
_REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "app_meta": frozenset({"key", "value"}),
    "settings": frozenset({"key", "value_json", "updated_at"}),
    "presets": frozenset({"id", "name", "options_json", "created_at", "updated_at"}),
    "run_history": frozenset(
        {
            "id",
            "created_at",
            "command_json",
            "input_paths_json",
            "output_path",
            "status",
            "exit_code",
            "duration_ms",
            "diagnostics_text",
        }
    ),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """A small, thread-safe SQLite database wrapper for application metadata.

    Parameters may be either an :class:`~app.paths.AppPaths` instance or a
    database path.  Passing ``AppPaths`` is preferred because it supplies the
    correct per-user backup location.
    """

    def __init__(
        self,
        location: AppPaths | str | Path,
        *,
        backup_dir: str | Path | None = None,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        if isinstance(location, AppPaths):
            self.path = location.database_path
            default_backup_dir = location.backup_dir
        else:
            self.path = Path(location).expanduser().resolve()
            default_backup_dir = self.path.parent / "backups"

        self.backup_dir = (
            Path(backup_dir).expanduser().resolve()
            if backup_dir is not None
            else default_backup_dir
        )
        self.busy_timeout_ms = max(0, int(busy_timeout_ms))
        self._lock = threading.RLock()
        self._initialized_report: InitializationReport | None = None

    @property
    def database_path(self) -> Path:
        """Compatibility-friendly name for the underlying database file."""

        return self.path

    def initialize(self) -> InitializationReport:
        """Create or upgrade the database after a verification/backup step.

        This is idempotent for the running process.  It makes no changes if an
        already-current database is found.  Unknown schema versions and failed
        integrity checks fail closed rather than risking user metadata.
        """

        with self._lock:
            if self._initialized_report is not None:
                return self._initialized_report

            self.path.parent.mkdir(parents=True, exist_ok=True)
            existed_before = self.path.exists()
            existing_nonempty = existed_before and self.path.stat().st_size > 0
            integrity_result = self.integrity_check() if existing_nonempty else ("ok",)
            if not self._integrity_is_ok(integrity_result):
                detail = "; ".join(integrity_result)
                raise DatabaseIntegrityError(
                    f"SQLite integrity check failed for {self.path}: {detail}"
                )

            # Inspect the schema before creating a backup or modifying it.  A
            # non-empty, unrelated SQLite file should be left completely alone.
            if existing_nonempty:
                with self._read_only_connection() as connection:
                    current_version = self._schema_version(connection)
                    self._validate_known_schema(connection, current_version)
            else:
                current_version = 0

            if current_version > SCHEMA_VERSION:
                raise DatabaseSchemaError(
                    f"Database schema v{current_version} is newer than this app supports "
                    f"(v{SCHEMA_VERSION})."
                )

            needs_migration = current_version < SCHEMA_VERSION
            backup_path: Path | None = None
            if needs_migration and existing_nonempty:
                backup_path = self.create_backup(current_version)

            try:
                connection = self._open_connection()
                try:
                    if needs_migration:
                        connection.execute("BEGIN IMMEDIATE")
                        try:
                            # A second process could have migrated while this
                            # process was preparing its backup.
                            locked_version = self._schema_version(connection)
                            if locked_version != current_version:
                                raise DatabaseMigrationError(
                                    "The database schema changed while initialization was running. "
                                    "Restart the application and try again."
                                )
                            self._apply_migrations(connection, locked_version)
                            self._validate_known_schema(connection, SCHEMA_VERSION)
                            connection.execute("COMMIT")
                        except Exception:
                            connection.execute("ROLLBACK")
                            raise

                    # WAL improves responsiveness when a UI request reads run
                    # history while a worker records a completed run.  It is a
                    # database setting only; no PGN data is touched.
                    connection.execute("PRAGMA journal_mode = WAL")
                finally:
                    # sqlite3.Connection's context manager commits/rolls back
                    # but does *not* close.  Explicit closure matters on
                    # Windows, where an open handle prevents file operations.
                    connection.close()
            except DatabaseError:
                raise
            except sqlite3.Error as error:
                raise DatabaseMigrationError(
                    f"Could not initialize SQLite database {self.path}: {error}"
                ) from error

            self._initialized_report = InitializationReport(
                database_path=self.path,
                schema_version=SCHEMA_VERSION,
                created=not existed_before,
                backup_path=backup_path,
                integrity_result=integrity_result,
            )
            return self._initialized_report

    def integrity_check(self) -> tuple[str, ...]:
        """Return SQLite's integrity-check messages without modifying the DB."""

        if not self.path.exists() or self.path.stat().st_size == 0:
            return ("ok",)

        try:
            with self._read_only_connection() as connection:
                rows = connection.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.Error as error:
            return (f"unable to read database: {error}",)

        messages = tuple(str(row[0]) for row in rows if row and row[0] is not None)
        return messages or ("ok",)

    def create_backup(self, schema_version: int | None = None) -> Path:
        """Create a consistent SQLite backup without replacing an existing file."""

        if not self.path.exists():
            raise DatabaseMigrationError("Cannot back up a database file that does not exist.")

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        version = schema_version if schema_version is not None else self._read_schema_version()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        base_name = f"{self.path.stem}-before-v{version}-{timestamp}"
        destination = self.backup_dir / f"{base_name}.sqlite3"
        suffix = 1
        # Reserve the destination with an exclusive create before SQLite opens
        # it.  This avoids even a theoretical race in which a user-created
        # file with the same timestamped name could be overwritten by backup.
        while True:
            try:
                with destination.open("xb"):
                    pass
                break
            except FileExistsError:
                destination = self.backup_dir / f"{base_name}-{suffix}.sqlite3"
                suffix += 1

        try:
            with self._read_only_connection() as source:
                target = sqlite3.connect(destination)
                try:
                    source.backup(target)
                    target.commit()
                finally:
                    target.close()
        except sqlite3.Error as error:
            raise DatabaseMigrationError(
                f"Could not create a backup of {self.path}: {error}"
            ) from error

        return destination

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured autocommit SQLite connection.

        Use :meth:`transaction` for a multi-statement mutation.  Every caller
        receives its own connection so FastAPI request threads do not share a
        SQLite connection object.
        """

        self.initialize()
        connection = self._open_connection()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection inside an immediate, rollback-on-error transaction."""

        self.initialize()
        connection = self._open_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()

    def _open_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=max(0.1, self.busy_timeout_ms / 1000),
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    @contextmanager
    def _read_only_connection(self) -> Iterator[sqlite3.Connection]:
        uri = f"{self.path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
        try:
            yield connection
        finally:
            connection.close()

    def _read_schema_version(self) -> int:
        with self._read_only_connection() as connection:
            return self._schema_version(connection)

    @staticmethod
    def _schema_version(connection: sqlite3.Connection) -> int:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])

    @staticmethod
    def _integrity_is_ok(messages: tuple[str, ...]) -> bool:
        return len(messages) == 1 and messages[0].strip().lower() == "ok"

    def _validate_known_schema(self, connection: sqlite3.Connection, version: int) -> None:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        unknown_tables = tables - _APP_TABLES
        if unknown_tables:
            names = ", ".join(sorted(unknown_tables))
            raise DatabaseSchemaError(
                f"Refusing to alter {self.path}; it contains unknown table(s): {names}."
            )

        if version > SCHEMA_VERSION:
            return

        if version >= 1:
            missing_tables = _APP_TABLES - tables
            if missing_tables:
                detail = ", ".join(sorted(missing_tables))
                raise DatabaseSchemaError(
                    f"Refusing to use {self.path}; schema v{version} is missing expected "
                    f"table(s): {detail}."
                )

        for table in tables:
            expected = _REQUIRED_COLUMNS.get(table)
            if expected is None:
                continue
            columns = {
                str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            missing = expected - columns
            if missing:
                detail = ", ".join(sorted(missing))
                raise DatabaseSchemaError(
                    f"Refusing to alter {self.path}; table {table!r} is missing expected "
                    f"column(s): {detail}."
                )

    def _apply_migrations(self, connection: sqlite3.Connection, current_version: int) -> None:
        for version in range(current_version + 1, SCHEMA_VERSION + 1):
            migration = _MIGRATIONS.get(version)
            if migration is None:
                raise DatabaseMigrationError(f"No migration is available for schema v{version}.")
            migration(connection)


def _migration_1(connection: sqlite3.Connection) -> None:
    """Create the first metadata-only schema."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            options_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS run_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            command_json TEXT NOT NULL,
            input_paths_json TEXT NOT NULL,
            output_path TEXT,
            status TEXT NOT NULL,
            exit_code INTEGER,
            duration_ms INTEGER,
            diagnostics_text TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_run_history_created_at "
        "ON run_history(created_at DESC, id DESC)"
    )
    connection.execute(
        "INSERT OR REPLACE INTO app_meta(key, value) VALUES (?, ?)",
        ("created_at", _utc_now()),
    )
    connection.execute("PRAGMA user_version = 1")


_MIGRATIONS = {1: _migration_1}


def initialize_database(location: AppPaths | str | Path) -> InitializationReport:
    """Convenience helper for startup code that only needs initialization."""

    return Database(location).initialize()


__all__ = [
    "DEFAULT_BUSY_TIMEOUT_MS",
    "SCHEMA_VERSION",
    "Database",
    "DatabaseError",
    "DatabaseIntegrityError",
    "DatabaseMigrationError",
    "DatabaseSchemaError",
    "InitializationReport",
    "initialize_database",
]
