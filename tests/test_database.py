from pathlib import Path

from app.database import Database
from app.paths import get_app_paths
from app.settings_store import SettingsStore


def test_database_initializes_and_does_not_persist_pasted_pgn(tmp_path: Path) -> None:
    paths = get_app_paths(root_dir=tmp_path / "install", data_dir=tmp_path / "data")
    database = Database(paths)
    store = SettingsStore(database)

    report = store.initialize()
    store.set("last_form", {"input_files": ["C:/games.pgn"], "stdin_text": '[Event "Secret"]'})
    preset = store.create_preset("Local test", {"stdin_text": "not stored", "formatting": {}})
    history = store.record_history(
        command=["pgn-extract.exe", "--quiet"],
        input_paths=["C:/games.pgn"],
        output_path="C:/out.pgn",
        status="succeeded",
        diagnostics="done",
    )

    assert report.created is True
    assert paths.database_path.is_file()
    assert store.get("last_form") == {"input_files": ["C:/games.pgn"]}
    assert preset.options == {"formatting": {}}
    assert history.status == "succeeded"
    assert len(store.list_history()) == 1


def test_clear_presets_is_scoped_to_presets_and_preserves_files(tmp_path: Path) -> None:
    paths = get_app_paths(root_dir=tmp_path / "install", data_dir=tmp_path / "data")
    store = SettingsStore(Database(paths))
    source_file = tmp_path / "source.pgn"
    output_file = tmp_path / "output.pgn"
    source_file.write_text('[Event "Source"]\n', encoding="utf-8")
    output_file.write_text('[Event "Output"]\n', encoding="utf-8")

    store.set("last_form", {"input_files": [str(source_file)], "theme": "light"})
    history = store.record_history(
        command=["pgn-extract.exe", str(source_file)],
        input_paths=[source_file],
        output_path=output_file,
        status="succeeded",
    )
    first = store.create_preset("First", {"formatting": {"comments": "keep"}})
    second = store.create_preset("Second", {"formatting": {"comments": "remove"}})

    assert store.clear_presets() == 2
    assert store.list_presets() == []
    assert store.get_preset(first.id) is None
    assert store.get_preset(second.id) is None
    assert store.get("last_form") == {"input_files": [str(source_file)], "theme": "light"}
    assert store.list_history() == [history]
    assert source_file.read_text(encoding="utf-8") == '[Event "Source"]\n'
    assert output_file.read_text(encoding="utf-8") == '[Event "Output"]\n'
    assert store.clear_presets() == 0
