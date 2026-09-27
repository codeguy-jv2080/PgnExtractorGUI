from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from app.game_counter import count_games


def test_count_games_uses_pgn_extract_check_only_summary_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(arguments, **kwargs):  # type: ignore[no-untyped-def]
        captured["arguments"] = list(arguments)
        captured["kwargs"] = kwargs
        file_list = Path(arguments[-1][2:])
        captured["file_list"] = file_list
        captured["file_list_contents"] = file_list.read_text(encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="2 games matched out of 2.\n")

    monkeypatch.setattr("app.game_counter.subprocess.run", fake_run)

    binary = Path(r"C:\\pgn-extract\\pgn-extract.exe")
    sources = [Path(r"C:\\games\\sample-one.pgn"), Path(r"C:\\games\\sample-two.pgn")]
    assert count_games(binary, sources) == 2
    assert captured["arguments"] == [
        str(binary),
        "-r",
        "--quiet",
        "--summary",
        f"-f{captured['file_list']}",
    ]
    assert captured["file_list_contents"] == "\n".join(str(source) for source in sources) + "\n"
    assert not captured["file_list"].exists()  # type: ignore[union-attr]
    assert captured["kwargs"] == {
        "cwd": str(binary.parent),
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "check": False,
        "shell": False,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def test_count_games_does_not_expand_a_large_selection_into_the_command_line(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(arguments, **kwargs):  # type: ignore[no-untyped-def]
        captured["arguments"] = list(arguments)
        file_list = Path(arguments[-1][2:])
        captured["file_list_contents"] = file_list.read_text(encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="694 games matched out of 694.\n", stderr="")

    monkeypatch.setattr("app.game_counter.subprocess.run", fake_run)

    binary = Path(r"C:\\pgn-extract\\pgn-extract.exe")
    sources = [
        Path(r"D:\\A deliberately long folder name\\Another long folder name")
        / f"twic-{index:04d}.pgn"
        for index in range(694)
    ]

    assert count_games(binary, sources) == 694
    arguments = captured["arguments"]
    assert isinstance(arguments, list)
    assert len(arguments) == 5
    assert all(str(source) not in arguments for source in sources)
    assert captured["file_list_contents"] == "\n".join(str(source) for source in sources) + "\n"
