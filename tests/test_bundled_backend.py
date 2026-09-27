from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.paths import AppPaths

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_GAMES = Path(__file__).with_name("fixtures") / "sample_games.pgn"
BUNDLED_BINARY = PROJECT_ROOT / "bin" / "pgn-extract.exe"
VERSION_RECORD = PROJECT_ROOT / "resources" / "pgn-extract" / "VERSION.txt"


def test_bundled_binary_has_a_matching_hash_and_no_local_windows_paths() -> None:
    payload = BUNDLED_BINARY.read_bytes()
    recorded_hash = re.search(
        r"^\s*SHA-256:\s*([0-9A-Fa-f]{64})\s*$",
        VERSION_RECORD.read_text(encoding="utf-8"),
        re.MULTILINE,
    )

    assert recorded_hash is not None
    assert hashlib.sha256(payload).hexdigest().upper() == recorded_hash.group(1).upper()

    lowered = payload.lower()
    assert b":\\users\\" not in lowered
    assert b":/users/" not in lowered
    assert b"appdata" not in lowered


def test_bundled_v26_06_binary_runs_a_filtered_export(tmp_path: Path) -> None:
    """Exercise the real bundled binary through the API and staging runner."""

    paths = AppPaths(root_dir=PROJECT_ROOT, data_dir=tmp_path / "app-data")
    client = TestClient(create_app(paths=paths))

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["pgn_extract_version"] == "26-06"

    destination = tmp_path / "training-games.pgn"
    destination.write_text("existing output", encoding="utf-8")
    response = client.post(
        "/api/runs",
        json={
            "form": {
                "input_files": [str(SAMPLE_GAMES)],
                "output_path": str(destination),
                "overwrite_output": True,
                "game_filters": {"event": "Training"},
                "formatting": {
                    "output_format": "pgn",
                    "variations": "keep",
                    "include_tags": True,
                    "include_comments": True,
                    "include_nags": True,
                },
            },
        },
    )
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]

    deadline = time.monotonic() + 5
    job: dict[str, object] = {}
    while time.monotonic() < deadline:
        job_response = client.get(f"/api/runs/{job_id}")
        assert job_response.status_code == 200
        job = job_response.json()
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.025)

    assert job["status"] == "succeeded", job
    assert job["returncode"] == 0
    assert job["outputs"] == [str(destination)]
    written = destination.read_text(encoding="utf-8")
    assert '[Event "Training Match"]' in written
    assert '[Event "Practice Match"]' not in written
