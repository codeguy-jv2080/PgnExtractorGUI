from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.paths import get_app_paths

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_GAMES = PROJECT_ROOT / "tests" / "fixtures" / "sample_games.pgn"


def test_api_starts_with_the_bundled_binary_and_saves_a_preset(tmp_path: Path) -> None:
    paths = get_app_paths(root_dir=PROJECT_ROOT, data_dir=tmp_path / "data")
    app = create_app(paths=paths)

    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["binary"]["compatible"] is True
        assert health.json()["binary"]["version"] == "26-06"

        response = client.post(
            "/api/presets",
            json={"name": "Only main line", "form": {"formatting": {"variations": "mainline"}}},
        )
        assert response.status_code == 201
        assert response.json()["form"]["formatting"]["variations"] == "mainline"

        presets = client.get("/api/presets")
        assert presets.status_code == 200
        assert presets.json()["presets"][0]["name"] == "Only main line"


def test_preset_delete_endpoints_only_remove_requested_presets(tmp_path: Path) -> None:
    paths = get_app_paths(root_dir=PROJECT_ROOT, data_dir=tmp_path / "data")
    app = create_app(paths=paths)
    source_file = tmp_path / "source.pgn"
    output_file = tmp_path / "output.pgn"
    source_file.write_text('[Event "Source"]\n', encoding="utf-8")
    output_file.write_text('[Event "Output"]\n', encoding="utf-8")

    with TestClient(app) as client:
        services = app.state.services
        services.store.set("last_form", {"input_files": [str(source_file)]})
        history = services.store.record_history(
            command=["pgn-extract.exe", str(source_file)],
            input_paths=[source_file],
            output_path=output_file,
            status="succeeded",
        )
        first = client.post("/api/presets", json={"name": "First", "form": {}})
        second = client.post("/api/presets", json={"name": "Second", "form": {}})
        assert first.status_code == 201
        assert second.status_code == 201

        missing = client.delete("/api/presets/999999")
        assert missing.status_code == 404
        assert [item["name"] for item in client.get("/api/presets").json()["presets"]] == [
            "First",
            "Second",
        ]

        deleted_one = client.delete(f"/api/presets/{first.json()['id']}")
        assert deleted_one.status_code == 204
        assert [item["name"] for item in client.get("/api/presets").json()["presets"]] == [
            "Second"
        ]

        deleted_all = client.delete("/api/presets")
        assert deleted_all.status_code == 200
        assert deleted_all.json() == {"deleted": 1}
        assert client.get("/api/presets").json()["presets"] == []
        assert client.get("/api/settings").json()["form"] == {
            "input_files": [str(source_file)]
        }
        assert client.get("/api/history").json()["history"] == [history.to_dict()]

    assert source_file.read_text(encoding="utf-8") == '[Event "Source"]\n'
    assert output_file.read_text(encoding="utf-8") == '[Event "Output"]\n'


def test_saving_a_clean_form_preserves_presets_history_and_files(tmp_path: Path) -> None:
    """The Reset to Defaults UI persists only its clean current-form state."""

    paths = get_app_paths(root_dir=PROJECT_ROOT, data_dir=tmp_path / "data")
    app = create_app(paths=paths)
    source_file = tmp_path / "source.pgn"
    output_file = tmp_path / "output.pgn"
    source_file.write_text('[Event "Source"]\n', encoding="utf-8")
    output_file.write_text('[Event "Output"]\n', encoding="utf-8")
    non_default_form = {
        "input_files": [str(source_file)],
        "output_path": str(output_file),
        "game_filters": {"eco": "C42"},
        "formatting": {"variations": "remove", "remove_comments": True},
    }
    clean_form = {
        "input_files": [],
        "sources": [],
        "output_path": None,
        "append_output": False,
        "overwrite_output": False,
        "split_games": None,
        "split_output_dir": None,
        "validation_only": False,
        "game_filters": {},
        "filters": {},
        "formatting": {"variations": "keep", "include_tags": True},
        "advanced_tokens": [],
    }

    with TestClient(app) as client:
        initial = client.put(
            "/api/settings",
            json={"form": non_default_form, "settings": {"ui_theme": "light"}},
        )
        assert initial.status_code == 200
        preset = client.post("/api/presets", json={"name": "Keep me", "form": non_default_form})
        assert preset.status_code == 201
        history = app.state.services.store.record_history(
            command=["pgn-extract.exe", str(source_file)],
            input_paths=[source_file],
            output_path=output_file,
            status="succeeded",
        )

        reset = client.post("/api/settings", json={"form": clean_form})
        assert reset.status_code == 200
        assert reset.json()["form"] == clean_form
        assert reset.json()["settings"]["ui_theme"] == "light"
        assert client.get("/api/presets").json()["presets"] == [
            {
                "id": preset.json()["id"],
                "name": "Keep me",
                "form": non_default_form,
                "created_at": preset.json()["created_at"],
                "updated_at": preset.json()["updated_at"],
            }
        ]
        assert client.get("/api/history").json()["history"] == [history.to_dict()]

    assert source_file.read_text(encoding="utf-8") == '[Event "Source"]\n'
    assert output_file.read_text(encoding="utf-8") == '[Event "Output"]\n'


def test_game_count_uses_selected_input_files_without_creating_output(tmp_path: Path) -> None:
    paths = get_app_paths(root_dir=PROJECT_ROOT, data_dir=tmp_path / "data")
    app = create_app(paths=paths)
    sentinel_output = tmp_path / "should-not-exist.pgn"

    with TestClient(app) as client:
        response = client.post(
            "/api/game-count",
            json={"input_files": [str(SAMPLE_GAMES), str(SAMPLE_GAMES)]},
        )

    assert response.status_code == 200
    assert response.json() == {"game_count": 4, "input_file_count": 2}
    assert not sentinel_output.exists()


def test_game_count_rejects_a_missing_input_file(tmp_path: Path) -> None:
    paths = get_app_paths(root_dir=PROJECT_ROOT, data_dir=tmp_path / "data")
    app = create_app(paths=paths)

    with TestClient(app) as client:
        response = client.post(
            "/api/game-count",
            json={"input_files": [str(tmp_path / "missing.pgn")]},
        )

    assert response.status_code == 400
    assert "does not exist" in response.json()["detail"]


def test_validation_mode_is_not_saved_for_the_next_startup(tmp_path: Path) -> None:
    paths = get_app_paths(root_dir=PROJECT_ROOT, data_dir=tmp_path / "data")
    app = create_app(paths=paths)
    validation_form = {
        "input_files": [str(SAMPLE_GAMES)],
        "validation_only": True,
        "formatting": {},
    }

    with TestClient(app) as client:
        preview = client.post("/api/command/preview", json={"form": validation_form})
        assert preview.status_code == 200
        assert "-r" in preview.json()["argv"]

        run = client.post("/api/runs", json={"form": validation_form})
        assert run.status_code == 201

        settings = client.get("/api/settings")
        assert settings.status_code == 200
        assert settings.json()["form"]["validation_only"] is False
