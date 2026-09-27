"""Persistence for GUI settings, saved option presets, and bounded run history.

The store intentionally records only command metadata and a short diagnostics
snippet for runs.  It never persists command stdout, which can contain the
user's PGN games.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from .database import Database, InitializationReport

DEFAULT_MAX_HISTORY_ENTRIES = 100
MAX_HISTORY_ENTRIES = 1_000
MAX_DIAGNOSTICS_CHARS = 16_000
MAX_SETTING_KEY_CHARS = 128
MAX_PRESET_NAME_CHARS = 120
# ``stdin_text`` is accepted for a one-off pgn-extract run but must never be
# written into SQLite.  The GUI otherwise stores only metadata and paths.
VOLATILE_PGN_FIELD_NAMES = frozenset({"stdin_text"})

T = TypeVar("T")


class StoreError(RuntimeError):
    """Base class for settings-store failures."""


class StoreValidationError(StoreError, ValueError):
    """Raised when a caller asks to persist unsupported metadata."""


class PresetNotFoundError(StoreError, LookupError):
    """Raised when updating a preset that no longer exists."""


class PresetNameConflictError(StoreError):
    """Raised when a preset name would duplicate an existing preset."""


@dataclass(frozen=True)
class PresetRecord:
    id: int
    name: str
    options: dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunHistoryRecord:
    id: int
    created_at: str
    command: list[str]
    input_paths: list[str]
    output_path: str | None
    status: str
    exit_code: int | None
    duration_ms: int | None
    diagnostics: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_encode(value: Any, *, label: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise StoreValidationError(f"{label} must be JSON-serializable: {error}") from error


def _json_decode(value: str, *, label: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise StoreError(f"Stored {label} is not valid JSON.") from error


def _without_volatile_pgn_fields(value: Any) -> Any:
    """Copy metadata while removing known fields that can contain whole PGNs."""

    if isinstance(value, Mapping):
        return {
            str(key): _without_volatile_pgn_fields(item)
            for key, item in value.items()
            if str(key).casefold() not in VOLATILE_PGN_FIELD_NAMES
        }
    if isinstance(value, list):
        return [_without_volatile_pgn_fields(item) for item in value]
    if isinstance(value, tuple):
        return [_without_volatile_pgn_fields(item) for item in value]
    return value


def _setting_key(key: str) -> str:
    if not isinstance(key, str):
        raise StoreValidationError("A settings key must be a string.")
    normalized = key.strip()
    if not normalized or len(normalized) > MAX_SETTING_KEY_CHARS or "\x00" in normalized:
        raise StoreValidationError("A settings key must be 1-128 non-null characters.")
    return normalized


def _preset_name(name: str) -> str:
    if not isinstance(name, str):
        raise StoreValidationError("A preset name must be a string.")
    normalized = name.strip()
    if not normalized or len(normalized) > MAX_PRESET_NAME_CHARS or "\x00" in normalized:
        raise StoreValidationError("A preset name must be 1-120 non-null characters.")
    return normalized


def _path_or_none(path: str | Path | None) -> str | None:
    if path is None:
        return None
    value = str(path)
    if "\x00" in value:
        raise StoreValidationError("A path cannot contain a null character.")
    return value


def _string_list(values: Sequence[str | Path], *, label: str) -> list[str]:
    if isinstance(values, (str, bytes)):
        raise StoreValidationError(f"{label} must be a sequence, not one string.")
    result: list[str] = []
    for value in values:
        normalized = str(value)
        if "\x00" in normalized:
            raise StoreValidationError(f"{label} cannot contain null characters.")
        result.append(normalized)
    return result


class SettingsStore:
    """High-level, metadata-only storage backed by :class:`Database`.

    The constructor has no filesystem side effect.  The database is created on
    the first read/write call, via :meth:`Database.initialize`.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def initialize(self) -> InitializationReport:
        return self.database.initialize()

    # -- Settings ---------------------------------------------------------

    def get(self, key: str, default: T | None = None) -> T | Any | None:
        """Get a JSON setting, returning ``default`` when it has not been set."""

        normalized_key = _setting_key(key)
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key = ?", (normalized_key,)
            ).fetchone()
        if row is None:
            return default
        return _json_decode(str(row[0]), label=f"setting {normalized_key!r}")

    def get_all(self) -> dict[str, Any]:
        """Return all settings as a dictionary of decoded JSON values."""

        with self.database.connection() as connection:
            rows = connection.execute("SELECT key, value_json FROM settings ORDER BY key").fetchall()
        return {
            str(row["key"]): _json_decode(
                str(row["value_json"]), label=f"setting {row['key']!r}"
            )
            for row in rows
        }

    list_settings = get_all

    def set(self, key: str, value: Any) -> Any:
        """Persist a JSON-compatible setting and return its safe stored form."""

        normalized_key = _setting_key(key)
        safe_value = _without_volatile_pgn_fields(value)
        encoded_value = _json_encode(safe_value, label=f"setting {normalized_key!r}")
        now = _utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO settings(key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (normalized_key, encoded_value, now),
            )
        return safe_value

    def set_many(self, values: Mapping[str, Any]) -> dict[str, Any]:
        """Persist multiple settings atomically."""

        if not isinstance(values, Mapping):
            raise StoreValidationError("Settings updates must be a mapping.")
        safe_values = {
            _setting_key(key): _without_volatile_pgn_fields(value) for key, value in values.items()
        }
        encoded = [
            (key, _json_encode(value, label=f"setting {key!r}"))
            for key, value in safe_values.items()
        ]
        now = _utc_now()
        with self.database.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO settings(key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                [(key, value, now) for key, value in encoded],
            )
        return safe_values

    def delete(self, key: str) -> bool:
        """Delete one GUI setting.  This does not affect PGN or output files."""

        normalized_key = _setting_key(key)
        with self.database.transaction() as connection:
            result = connection.execute("DELETE FROM settings WHERE key = ?", (normalized_key,))
        return result.rowcount > 0

    delete_setting = delete

    # -- Presets ----------------------------------------------------------

    def list_presets(self) -> list[PresetRecord]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT id, name, options_json, created_at, updated_at FROM presets "
                "ORDER BY name COLLATE NOCASE, id"
            ).fetchall()
        return [self._preset_from_row(row) for row in rows]

    def get_preset(self, preset_id: int) -> PresetRecord | None:
        identifier = self._preset_id(preset_id)
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT id, name, options_json, created_at, updated_at FROM presets WHERE id = ?",
                (identifier,),
            ).fetchone()
        return self._preset_from_row(row) if row is not None else None

    def create_preset(self, name: str, options: Mapping[str, Any]) -> PresetRecord:
        """Save a named command-options preset (not source PGN data)."""

        normalized_name = _preset_name(name)
        encoded_options = self._preset_options(options)
        now = _utc_now()
        try:
            with self.database.transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO presets(name, options_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (normalized_name, encoded_options, now, now),
                )
                identifier = int(cursor.lastrowid)
                row = connection.execute(
                    "SELECT id, name, options_json, created_at, updated_at FROM presets WHERE id = ?",
                    (identifier,),
                ).fetchone()
        except sqlite3.IntegrityError as error:
            raise PresetNameConflictError(
                f"A preset named {normalized_name!r} already exists."
            ) from error
        assert row is not None
        return self._preset_from_row(row)

    save_preset = create_preset

    def update_preset(
        self,
        preset_id: int,
        *,
        name: str | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> PresetRecord:
        """Update a preset's name and/or options atomically."""

        identifier = self._preset_id(preset_id)
        normalized_name = _preset_name(name) if name is not None else None
        encoded_options = self._preset_options(options) if options is not None else None
        try:
            with self.database.transaction() as connection:
                current = connection.execute(
                    "SELECT id, name, options_json, created_at, updated_at FROM presets WHERE id = ?",
                    (identifier,),
                ).fetchone()
                if current is None:
                    raise PresetNotFoundError(f"Preset {identifier} does not exist.")
                next_name = normalized_name if normalized_name is not None else str(current["name"])
                next_options = (
                    encoded_options if encoded_options is not None else str(current["options_json"])
                )
                now = _utc_now()
                connection.execute(
                    "UPDATE presets SET name = ?, options_json = ?, updated_at = ? WHERE id = ?",
                    (next_name, next_options, now, identifier),
                )
                row = connection.execute(
                    "SELECT id, name, options_json, created_at, updated_at FROM presets WHERE id = ?",
                    (identifier,),
                ).fetchone()
        except sqlite3.IntegrityError as error:
            raise PresetNameConflictError(
                f"A preset named {normalized_name!r} already exists."
            ) from error
        assert row is not None
        return self._preset_from_row(row)

    def delete_preset(self, preset_id: int) -> bool:
        """Delete one saved preset record, never any input/output file."""

        identifier = self._preset_id(preset_id)
        with self.database.transaction() as connection:
            result = connection.execute("DELETE FROM presets WHERE id = ?", (identifier,))
        return result.rowcount > 0

    def clear_presets(self) -> int:
        """Delete every saved preset, leaving settings and run history intact.

        This deliberately affects only the ``presets`` table.  It stores no
        PGN file contents and never reads, writes, or removes source/output
        files on disk.
        """

        with self.database.transaction() as connection:
            result = connection.execute("DELETE FROM presets")
        return max(0, result.rowcount)

    # -- Bounded history --------------------------------------------------

    def record_history(
        self,
        *,
        command: Sequence[str | Path],
        input_paths: Sequence[str | Path],
        output_path: str | Path | None,
        status: str,
        exit_code: int | None = None,
        duration_ms: int | None = None,
        diagnostics: str | None = None,
        max_entries: int = DEFAULT_MAX_HISTORY_ENTRIES,
    ) -> RunHistoryRecord:
        """Record a command result while keeping history bounded.

        ``command`` must be an argv sequence, not a shell command string.  The
        method persists its text representation and input/output paths, but
        deliberately has no ``stdout`` parameter so PGN content cannot be
        accidentally saved by normal run-manager use.
        """

        argv = _string_list(command, label="command")
        sources = _string_list(input_paths, label="input paths")
        normalized_output = _path_or_none(output_path)
        normalized_status = self._status(status)
        normalized_exit_code = self._exit_code(exit_code)
        normalized_duration = self._duration(duration_ms)
        normalized_diagnostics = self._diagnostics(diagnostics)
        limit = self._history_limit(max_entries)
        now = _utc_now()

        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO run_history(
                    created_at, command_json, input_paths_json, output_path,
                    status, exit_code, duration_ms, diagnostics_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    _json_encode(argv, label="command"),
                    _json_encode(sources, label="input paths"),
                    normalized_output,
                    normalized_status,
                    normalized_exit_code,
                    normalized_duration,
                    normalized_diagnostics,
                ),
            )
            identifier = int(cursor.lastrowid)
            connection.execute(
                """
                DELETE FROM run_history
                WHERE id NOT IN (
                    SELECT id FROM run_history ORDER BY id DESC LIMIT ?
                )
                """,
                (limit,),
            )
            row = connection.execute(
                """
                SELECT id, created_at, command_json, input_paths_json, output_path,
                       status, exit_code, duration_ms, diagnostics_text
                FROM run_history WHERE id = ?
                """,
                (identifier,),
            ).fetchone()
        assert row is not None
        return self._history_from_row(row)

    record_run = record_history

    def list_history(self, limit: int = DEFAULT_MAX_HISTORY_ENTRIES) -> list[RunHistoryRecord]:
        """Return newest run records first."""

        requested_limit = self._history_limit(limit)
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, command_json, input_paths_json, output_path,
                       status, exit_code, duration_ms, diagnostics_text
                FROM run_history ORDER BY id DESC LIMIT ?
                """,
                (requested_limit,),
            ).fetchall()
        return [self._history_from_row(row) for row in rows]

    def get_history(self, history_id: int) -> RunHistoryRecord | None:
        identifier = self._preset_id(history_id, label="History id")
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT id, created_at, command_json, input_paths_json, output_path,
                       status, exit_code, duration_ms, diagnostics_text
                FROM run_history WHERE id = ?
                """,
                (identifier,),
            ).fetchone()
        return self._history_from_row(row) if row is not None else None

    def clear_history(self) -> int:
        """Remove run-history metadata only; PGN files are never affected."""

        with self.database.transaction() as connection:
            result = connection.execute("DELETE FROM run_history")
        return max(0, result.rowcount)

    @staticmethod
    def _preset_id(value: int, *, label: str = "Preset id") -> int:
        if isinstance(value, bool):
            raise StoreValidationError(f"{label} must be a positive integer.")
        try:
            identifier = int(value)
        except (TypeError, ValueError) as error:
            raise StoreValidationError(f"{label} must be a positive integer.") from error
        if identifier <= 0:
            raise StoreValidationError(f"{label} must be a positive integer.")
        return identifier

    @staticmethod
    def _preset_options(options: Mapping[str, Any]) -> str:
        if not isinstance(options, Mapping):
            raise StoreValidationError("Preset options must be an object/dictionary.")
        return _json_encode(_without_volatile_pgn_fields(dict(options)), label="preset options")

    @staticmethod
    def _status(status: str) -> str:
        if not isinstance(status, str):
            raise StoreValidationError("History status must be a string.")
        normalized = status.strip()
        if not normalized or len(normalized) > 64 or "\x00" in normalized:
            raise StoreValidationError("History status must be 1-64 non-null characters.")
        return normalized

    @staticmethod
    def _exit_code(exit_code: int | None) -> int | None:
        if exit_code is None:
            return None
        if isinstance(exit_code, bool):
            raise StoreValidationError("Exit code must be an integer or null.")
        try:
            return int(exit_code)
        except (TypeError, ValueError) as error:
            raise StoreValidationError("Exit code must be an integer or null.") from error

    @staticmethod
    def _duration(duration_ms: int | None) -> int | None:
        if duration_ms is None:
            return None
        if isinstance(duration_ms, bool):
            raise StoreValidationError("Duration must be a non-negative integer or null.")
        try:
            normalized = int(duration_ms)
        except (TypeError, ValueError) as error:
            raise StoreValidationError(
                "Duration must be a non-negative integer or null."
            ) from error
        if normalized < 0:
            raise StoreValidationError("Duration must be a non-negative integer or null.")
        return normalized

    @staticmethod
    def _diagnostics(diagnostics: str | None) -> str:
        if diagnostics is None:
            return ""
        if not isinstance(diagnostics, str):
            diagnostics = str(diagnostics)
        # Keep the tail, where pgn-extract normally places the final error or
        # matched-game summary.  The marker makes the truncation explicit.
        if len(diagnostics) > MAX_DIAGNOSTICS_CHARS:
            return "[diagnostics truncated]\n" + diagnostics[-MAX_DIAGNOSTICS_CHARS:]
        return diagnostics

    @staticmethod
    def _history_limit(limit: int) -> int:
        if isinstance(limit, bool):
            raise StoreValidationError("History limit must be an integer.")
        try:
            normalized = int(limit)
        except (TypeError, ValueError) as error:
            raise StoreValidationError("History limit must be an integer.") from error
        if not 1 <= normalized <= MAX_HISTORY_ENTRIES:
            raise StoreValidationError(
                f"History limit must be between 1 and {MAX_HISTORY_ENTRIES}."
            )
        return normalized

    @staticmethod
    def _preset_from_row(row: sqlite3.Row) -> PresetRecord:
        options = _json_decode(str(row["options_json"]), label=f"preset {row['id']} options")
        if not isinstance(options, dict):
            raise StoreError(f"Preset {row['id']} options are not an object.")
        return PresetRecord(
            id=int(row["id"]),
            name=str(row["name"]),
            options=options,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _history_from_row(row: sqlite3.Row) -> RunHistoryRecord:
        command = _json_decode(str(row["command_json"]), label=f"history {row['id']} command")
        input_paths = _json_decode(
            str(row["input_paths_json"]), label=f"history {row['id']} input paths"
        )
        if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
            raise StoreError(f"History {row['id']} command is not a string list.")
        if not isinstance(input_paths, list) or not all(
            isinstance(item, str) for item in input_paths
        ):
            raise StoreError(f"History {row['id']} input paths are not a string list.")
        return RunHistoryRecord(
            id=int(row["id"]),
            created_at=str(row["created_at"]),
            command=command,
            input_paths=input_paths,
            output_path=str(row["output_path"]) if row["output_path"] is not None else None,
            status=str(row["status"]),
            exit_code=int(row["exit_code"]) if row["exit_code"] is not None else None,
            duration_ms=int(row["duration_ms"]) if row["duration_ms"] is not None else None,
            diagnostics=str(row["diagnostics_text"]),
        )


__all__ = [
    "DEFAULT_MAX_HISTORY_ENTRIES",
    "MAX_DIAGNOSTICS_CHARS",
    "MAX_HISTORY_ENTRIES",
    "VOLATILE_PGN_FIELD_NAMES",
    "PresetNameConflictError",
    "PresetNotFoundError",
    "PresetRecord",
    "RunHistoryRecord",
    "SettingsStore",
    "StoreError",
    "StoreValidationError",
]
