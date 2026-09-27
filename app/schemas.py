"""Pydantic request/response shapes for the local FastAPI API.

The GUI posts a structured form instead of a shell command.  These schemas
validate transport-level shape and obvious unsafe text; ``command_builder``
remains the authority that maps supported form fields to pgn-extract options.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_PATH_TEXT_CHARS = 32_767
MAX_ADVANCED_TOKENS = 256
MAX_TOKEN_CHARS = 4_096
MAX_PRESET_NAME_CHARS = 120


class SchemaValidationError(ValueError):
    """A Pydantic-compatible validation error for malformed JSON fields."""


class ApiModel(BaseModel):
    """Common forward-compatible API model configuration."""

    # Extra form fields are retained rather than rejected so a newer local
    # frontend can talk to an older backend and command_builder can issue an
    # explicit, user-facing error only when an option is unsupported.
    model_config = ConfigDict(extra="allow", populate_by_name=True)


def _validate_text(value: Any, *, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be text.")
    if "\x00" in value:
        raise ValueError(f"{field_name} cannot contain a null character.")
    if len(value) > maximum:
        raise ValueError(f"{field_name} is too long.")
    return value


def _validate_text_list(value: Any, *, field_name: str, maximum_items: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list.")
    if len(value) > maximum_items:
        raise ValueError(f"{field_name} has too many entries.")
    return [
        _validate_text(item, field_name=field_name, maximum=MAX_TOKEN_CHARS)
        for item in value
    ]


class FormState(ApiModel):
    """Browser form state used for command preview, execution, and presets."""

    input_files: list[str] = Field(default_factory=list)
    # The current UI sends these compatibility mirrors.  Keeping them makes
    # saved presets from earlier builds portable.
    sources: list[str] = Field(default_factory=list)
    stdin_text: str | None = Field(default=None, max_length=2_000_000)
    output_path: str | None = Field(default=None, max_length=MAX_PATH_TEXT_CHARS)
    append_output: bool = False
    overwrite_output: bool = False
    split_games: int | None = Field(default=None, ge=1)
    split_output_dir: str | None = Field(default=None, max_length=MAX_PATH_TEXT_CHARS)
    validation_only: bool = False
    game_filters: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    formatting: dict[str, Any] = Field(default_factory=dict)
    advanced_tokens: list[str] = Field(default_factory=list)
    literal_tokens: list[str] = Field(default_factory=list)

    @field_validator("input_files", "sources", mode="before")
    @classmethod
    def validate_path_lists(cls, value: Any) -> list[str]:
        values = _validate_text_list(value, field_name="File paths", maximum_items=1_024)
        return [
            _validate_text(item, field_name="File path", maximum=MAX_PATH_TEXT_CHARS)
            for item in values
        ]

    @field_validator("advanced_tokens", "literal_tokens", mode="before")
    @classmethod
    def validate_advanced_tokens(cls, value: Any) -> list[str]:
        return _validate_text_list(
            value, field_name="Advanced arguments", maximum_items=MAX_ADVANCED_TOKENS
        )

    @field_validator("stdin_text")
    @classmethod
    def validate_stdin_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_text(value, field_name="PGN text", maximum=2_000_000)

    @field_validator("output_path", "split_output_dir")
    @classmethod
    def validate_optional_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_text(value, field_name="Path", maximum=MAX_PATH_TEXT_CHARS)

    @field_validator("game_filters", "filters", "formatting", mode="before")
    @classmethod
    def validate_option_objects(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise SchemaValidationError("Option groups must be objects.")
        return value

    @model_validator(mode="after")
    def synchronize_compatibility_fields(self) -> FormState:
        """Make current and historical frontend field names interchangeable."""

        if not self.input_files and self.sources:
            self.input_files = list(self.sources)
        elif self.input_files and not self.sources:
            self.sources = list(self.input_files)

        if not self.game_filters and self.filters:
            self.game_filters = dict(self.filters)
        elif self.game_filters and not self.filters:
            self.filters = dict(self.game_filters)

        if not self.advanced_tokens and self.literal_tokens:
            self.advanced_tokens = list(self.literal_tokens)
        elif self.advanced_tokens and not self.literal_tokens:
            self.literal_tokens = list(self.advanced_tokens)
        return self

    def command_form(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary consumed by ``command_builder``."""

        return self.model_dump(mode="json")


class CommandRequest(ApiModel):
    """Shared request for ``/api/command/preview`` and ``/api/runs``."""

    form: FormState
    confirm_overwrite: bool = False


PreviewRequest = CommandRequest
RunRequest = CommandRequest


class PresetCreateRequest(ApiModel):
    """Payload posted by the Save preset control."""

    name: str = Field(min_length=1, max_length=MAX_PRESET_NAME_CHARS)
    form: FormState

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = _validate_text(value, field_name="Preset name", maximum=MAX_PRESET_NAME_CHARS).strip()
        if not normalized:
            raise ValueError("Preset name cannot be empty.")
        return normalized

    def store_options(self) -> dict[str, Any]:
        """Return the form object stored by :class:`SettingsStore`.

        The preset endpoint exposes this same value under its response
        ``form`` key, so it must not be wrapped in another ``{"form": ...}``
        object.
        """

        return self.form.command_form()


class PresetUpdateRequest(ApiModel):
    """Optional preset fields for a future edit/rename endpoint."""

    name: str | None = Field(default=None, min_length=1, max_length=MAX_PRESET_NAME_CHARS)
    form: FormState | None = None

    @field_validator("name")
    @classmethod
    def validate_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _validate_text(value, field_name="Preset name", maximum=MAX_PRESET_NAME_CHARS).strip()
        if not normalized:
            raise ValueError("Preset name cannot be empty.")
        return normalized


class SettingsUpdateRequest(ApiModel):
    """Persisted GUI state, normally the last completed form."""

    form: FormState | None = None
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("settings", mode="before")
    @classmethod
    def validate_settings(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise SchemaValidationError("Settings values must be an object.")
        return value


# Response models keep route documentation readable.  The routes may return a
# dict directly when that is more convenient; FastAPI will validate it against
# these models when they are declared as ``response_model``.
class BinaryStatusResponse(ApiModel):
    path: str | None = None
    source: str | None = None
    exists: bool = False
    recognized: bool = False
    version: str | None = None
    compatible: bool = False
    minimum_supported_version: str | None = None
    message: str | None = None


class HealthResponse(ApiModel):
    status: str = "ok"
    pgn_extract_version: str | None = None
    binary: BinaryStatusResponse | None = None


class PresetResponse(ApiModel):
    id: int
    name: str
    form: dict[str, Any]
    created_at: str | None = None
    updated_at: str | None = None


class RunHistoryResponse(ApiModel):
    id: int
    created_at: str
    command: list[str]
    input_paths: list[str]
    output_path: str | None = None
    status: str
    exit_code: int | None = None
    duration_ms: int | None = None
    diagnostics: str = ""


class ErrorResponse(ApiModel):
    detail: str


__all__ = [
    "ApiModel",
    "BinaryStatusResponse",
    "CommandRequest",
    "ErrorResponse",
    "FormState",
    "HealthResponse",
    "PresetCreateRequest",
    "PresetResponse",
    "PresetUpdateRequest",
    "PreviewRequest",
    "RunHistoryResponse",
    "RunRequest",
    "SchemaValidationError",
    "SettingsUpdateRequest",
]
