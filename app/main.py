"""FastAPI application for the fully local PGN Extract GUI."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .command_builder import CommandBuildError, CommandPlan, build_command
from .database import Database
from .game_counter import GameCountError, count_games
from .options_catalog import OPTION_CATALOG, catalog_by_group
from .paths import AppPaths, get_app_paths
from .pgn_binary import BinaryInfo, discover_binary, require_compatible_binary
from .run_manager import RunConflictError, RunError, RunManager
from .settings_store import (
    PresetNameConflictError,
    SettingsStore,
    StoreError,
)


@dataclass
class AppServices:
    paths: AppPaths
    database: Database
    store: SettingsStore
    run_manager: RunManager
    binary_info: BinaryInfo

    def refresh_binary_info(self) -> BinaryInfo:
        configured_path = self.store.get("pgn_extract_binary_path")
        explicit_path = configured_path if isinstance(configured_path, str) and configured_path else None
        self.binary_info = discover_binary(self.paths, explicit_path=explicit_path)
        return self.binary_info


def create_app(
    *,
    paths: AppPaths | None = None,
    binary_path: str | Path | None = None,
) -> FastAPI:
    """Create the loopback-only FastAPI app.

    ``launcher.py`` binds this app exclusively to ``127.0.0.1``.  This module
    does not add CORS middleware or remote upload endpoints: the selected
    input paths stay on the user's computer and are passed to pgn-extract as
    local argv values.
    """

    app_paths = paths or get_app_paths()
    app_paths.ensure_data_directories()
    database = Database(app_paths)
    database.initialize()
    store = SettingsStore(database)
    if binary_path is not None:
        # An explicit programmatic path is used by tests or a launcher switch;
        # record it as a normal local setting so it persists across runs.
        store.set("pgn_extract_binary_path", str(Path(binary_path).expanduser().absolute()))
    configured = store.get("pgn_extract_binary_path")
    info = discover_binary(
        app_paths,
        explicit_path=configured if isinstance(configured, str) and configured else None,
    )
    manager = RunManager(app_paths, history_recorder=store.record_history)
    services = AppServices(
        paths=app_paths,
        database=database,
        store=store,
        run_manager=manager,
        binary_info=info,
    )

    app = FastAPI(
        title="PGN Extract GUI",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.services = services

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        binary = services.refresh_binary_info()
        return {
            "name": "PGN Extract GUI",
            "local_only": True,
            "pgn_extract_version": binary.version,
            "binary": binary.to_dict(),
        }

    @app.get("/api/binary")
    def binary_status() -> dict[str, Any]:
        return services.refresh_binary_info().to_dict(include_probe_output=True)

    @app.post("/api/binary")
    async def set_binary(request: Request) -> dict[str, Any]:
        payload = await _json_object(request)
        candidate = _string(payload.get("path"))
        if not candidate:
            services.store.delete("pgn_extract_binary_path")
        else:
            candidate_path = Path(candidate).expanduser().absolute()
            if not candidate_path.is_file():
                raise HTTPException(status_code=400, detail=f"Executable was not found: {candidate_path}")
            services.store.set("pgn_extract_binary_path", str(candidate_path))
        return services.refresh_binary_info().to_dict(include_probe_output=True)

    @app.get("/api/options")
    def options() -> dict[str, Any]:
        binary = services.refresh_binary_info()
        return {
            "binary": binary.to_dict(),
            "pgn_extract_version": binary.version,
            "catalog": OPTION_CATALOG,
            "groups": catalog_by_group(),
        }

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return {
            "form": services.store.get("last_form", {}),
            "settings": services.store.get_all(),
        }

    @app.put("/api/settings")
    @app.post("/api/settings")
    async def save_settings(request: Request) -> dict[str, Any]:
        payload = await _json_object(request)
        form = payload.get("form")
        if form is not None:
            if not isinstance(form, dict):
                raise HTTPException(status_code=400, detail="form must be an object.")
            services.store.set("last_form", form)
        settings_payload = payload.get("settings")
        if settings_payload is not None:
            if not isinstance(settings_payload, dict):
                raise HTTPException(status_code=400, detail="settings must be an object.")
            services.store.set_many(settings_payload)
        return {"form": services.store.get("last_form", {}), "settings": services.store.get_all()}

    @app.get("/api/presets")
    def list_presets() -> dict[str, Any]:
        return {
            "presets": [
                {
                    "id": record.id,
                    "name": record.name,
                    "form": record.options,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                }
                for record in services.store.list_presets()
            ]
        }

    @app.post("/api/presets", status_code=status.HTTP_201_CREATED)
    async def create_preset(request: Request) -> dict[str, Any]:
        payload = await _json_object(request)
        name = _string(payload.get("name"))
        form = payload.get("form", payload.get("options"))
        if not name:
            raise HTTPException(status_code=400, detail="A preset name is required.")
        if not isinstance(form, dict):
            raise HTTPException(status_code=400, detail="Preset form must be an object.")
        try:
            record = services.store.create_preset(name, form)
        except PresetNameConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "id": record.id,
            "name": record.name,
            "form": record.options,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    @app.delete("/api/presets")
    def clear_presets() -> dict[str, int]:
        """Remove saved presets only, returning how many were deleted."""

        try:
            deleted = services.store.clear_presets()
        except StoreError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"deleted": deleted}

    @app.delete("/api/presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_preset(preset_id: int) -> Response:
        try:
            deleted = services.store.delete_preset(preset_id)
        except StoreError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if not deleted:
            raise HTTPException(status_code=404, detail="Preset was not found.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/command/preview")
    async def preview_command(request: Request) -> dict[str, Any]:
        payload = await _json_object(request)
        plan = _build_plan(services, payload)
        return plan.to_preview()

    @app.post("/api/game-count")
    async def game_count(request: Request) -> dict[str, int]:
        """Count the selected input games without creating an output PGN."""

        payload = await _json_object(request)
        info = services.refresh_binary_info()
        try:
            binary = require_compatible_binary(info)
            plan = build_command(
                {
                    "input_files": payload.get("input_files"),
                    "validation_only": True,
                    "game_filters": {},
                    "formatting": {},
                },
                binary=binary,
                eco_file=services.paths.eco_file,
            )
            game_count = await asyncio.to_thread(count_games, binary, plan.input_files)
        except (CommandBuildError, GameCountError, RuntimeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"game_count": game_count, "input_file_count": len(plan.input_files)}

    @app.post("/api/runs", status_code=status.HTTP_201_CREATED)
    async def start_run(request: Request) -> dict[str, Any]:
        payload = await _json_object(request)
        plan = _build_plan(services, payload)
        try:
            # Pressing Run is the user's confirmation of the explicitly selected
            # output action. Append and overwrite still must be selected in the form.
            job = services.run_manager.start(plan, confirm_overwrite=True)
        except RunConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except RunError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        # Validation is a one-run action.  Do not silently restore it as the
        # next startup's mode, where it could suppress an intended output file.
        services.store.set("last_form", _form_for_saved_settings(payload["form"]))
        return job.as_dict()

    @app.get("/api/runs/{job_id}")
    def get_run(job_id: str) -> dict[str, Any]:
        job = services.run_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Run was not found.")
        return job.as_dict()

    @app.post("/api/runs/{job_id}/cancel")
    def cancel_run(job_id: str) -> dict[str, Any]:
        try:
            job = services.run_manager.cancel(job_id)
        except RunError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return job.as_dict()

    @app.get("/api/history")
    def run_history(limit: int = 100) -> dict[str, Any]:
        try:
            records = services.store.list_history(limit=limit)
        except StoreError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"history": [record.to_dict() for record in records]}

    @app.delete("/api/history", status_code=status.HTTP_204_NO_CONTENT)
    def clear_history() -> Response:
        services.store.clear_history()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    static_dir = app_paths.root_dir / "app" / "static"
    index_file = static_dir / "index.html"
    if not static_dir.is_dir() or not index_file.is_file():
        raise RuntimeError(f"The bundled web interface is missing: {static_dir}")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(index_file)

    return app


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as error:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    return payload


def _build_plan(services: AppServices, payload: dict[str, Any]) -> CommandPlan:
    form = payload.get("form")
    if not isinstance(form, dict):
        raise HTTPException(status_code=400, detail="form must be an object.")
    info = services.refresh_binary_info()
    try:
        binary = require_compatible_binary(info)
        return build_command(form, binary=binary, eco_file=services.paths.eco_file)
    except (CommandBuildError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _form_for_saved_settings(form: dict[str, Any]) -> dict[str, Any]:
    """Return a reusable form state without carrying forward check-only mode."""

    saved = dict(form)
    saved["validation_only"] = False
    return saved


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = ["AppServices", "create_app"]
