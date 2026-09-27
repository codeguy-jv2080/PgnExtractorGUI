from pathlib import Path

import pytest

from app.command_builder import CommandBuildError, build_command
from app.input_file_list import INPUT_FILE_LIST_NAME


def _files(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    binary = tmp_path / "pgn-extract.exe"
    source = tmp_path / "input.pgn"
    output = tmp_path / "filtered.pgn"
    eco = tmp_path / "eco.pgn"
    for file in (binary, source, eco):
        file.write_text("placeholder", encoding="utf-8")
    return binary, source, output, eco


def test_builds_a_structured_command_and_uses_staged_output_marker(tmp_path: Path) -> None:
    binary, source, output, eco = _files(tmp_path)
    form = {
        "input_files": [str(source)],
        "output_path": str(output),
        "game_filters": {
            "white": "Fischer",
            "event": "Candidates",
            "min_plies": 12,
            "max_plies": 160,
            "first_game": 2,
            "last_game": 40,
            "checkmate": True,
            "setup_position": True,
        },
        "formatting": {
            "output_format": "pgn",
            "variations": "mainline",
            "include_comments": False,
            "include_nags": False,
            "include_tags": False,
            "include_fen_comments": True,
            "classify_eco": True,
            "line_width": 100,
        },
        "advanced_tokens": ["--summary", "--quiet"],
    }

    plan = build_command(form, binary=binary, eco_file=eco)

    assert "-t__PGN_EXTRACT_GUI_TAGS__" in plan.argv
    assert "--minply" in plan.argv and "12" in plan.argv
    assert "--maxply" in plan.argv and "160" in plan.argv
    assert "--checkmate" in plan.argv
    assert "--onlysetuptags" in plan.argv
    assert "--nocomments" in plan.argv
    assert "--nonags" in plan.argv
    assert "--novars" in plan.argv
    assert "--notags" in plan.argv
    assert "--fencomments" in plan.argv
    assert f"-e{eco.absolute()}" in plan.argv
    assert "-w100" in plan.argv
    assert "__PGN_EXTRACT_GUI_OUTPUT_0__" in plan.argv
    assert plan.outputs[0].destination == output.absolute()
    assert plan.tag_criteria == ['Event "Candidates"', 'White "Fischer"']
    assert str(source.absolute()) not in plan.argv
    assert plan.preview_argv[-2:] == ["-f", INPUT_FILE_LIST_NAME]
    assert str(source.absolute()) not in plan.display_command
    assert plan.to_preview()["argv"][-2:] == ["-f", INPUT_FILE_LIST_NAME]


@pytest.mark.parametrize("tokens", [["--output", "other.pgn"], ["-aother.pgn"], ["--append=out.pgn"]])
def test_rejects_advanced_output_switches(tmp_path: Path, tokens: list[str]) -> None:
    binary, source, _, eco = _files(tmp_path)
    with pytest.raises(CommandBuildError, match="Output destinations"):
        build_command(
            {
                "input_files": [str(source)],
                "formatting": {},
                "advanced_tokens": tokens,
            },
            binary=binary,
            eco_file=eco,
        )


def test_requires_an_input_source(tmp_path: Path) -> None:
    binary, _, _, eco = _files(tmp_path)
    with pytest.raises(CommandBuildError, match="Select at least one PGN"):
        build_command({"formatting": {}}, binary=binary, eco_file=eco)


def test_builds_requested_filter_cleanup_split_and_validation_options(tmp_path: Path) -> None:
    binary, source, _, eco = _files(tmp_path)
    second_source = tmp_path / "second.pgn"
    split_directory = tmp_path / "split"
    second_source.write_text("placeholder", encoding="utf-8")
    split_directory.mkdir()

    plan = build_command(
        {
            "input_files": [str(source), str(second_source)],
            "split_games": 250,
            "split_output_dir": str(split_directory),
            "game_filters": {
                "player": "Tal",
                "date_from": "1960",
                "date_to": "1962.12.31",
                "minimum_elo": 2400,
                "maximum_elo": 2800,
                "result": "1-0",
                "eco": "C42",
                "selected_games": "1:10,15,89:94",
            },
            "formatting": {
                "remove_duplicates": True,
                "remove_comments": True,
                "remove_nags": True,
                "variations": "remove",
                "classify_eco": True,
            },
        },
        binary=binary,
        eco_file=eco,
    )

    assert "--noduplicates" in plan.argv
    assert "--nocomments" in plan.argv
    assert "--nonags" in plan.argv
    assert "--novars" in plan.argv
    assert "--selectonly" in plan.argv
    assert "1:10,15,89:94" in plan.argv
    assert "-#250" in plan.argv
    assert f"-e{eco.absolute()}" in plan.argv
    assert plan.generated_output_directory == split_directory.absolute()
    assert plan.generated_output_mode == "replace"
    assert plan.tag_criteria == [
        'Player "Tal"',
        'Result "1-0"',
        'ECO "C42"',
        'Date >= "1960"',
        'Date <= "1962.12.31"',
        'Elo >= "2400"',
        'Elo <= "2800"',
    ]
    assert str(source.absolute()) not in plan.argv
    assert str(second_source.absolute()) not in plan.argv
    assert plan.preview_argv[-2:] == ["-f", INPUT_FILE_LIST_NAME]


@pytest.mark.parametrize("selected_games", ["1:4,4:8", "4:1", "1,,3", "1-3", "1:", ":3"])
def test_rejects_invalid_selected_game_ranges(tmp_path: Path, selected_games: str) -> None:
    binary, source, _, eco = _files(tmp_path)
    with pytest.raises(CommandBuildError, match="Selected game"):
        build_command(
            {
                "input_files": [str(source)],
                "game_filters": {"selected_games": selected_games},
                "formatting": {},
            },
            binary=binary,
            eco_file=eco,
        )


def test_validation_only_does_not_accept_output_or_split_files(tmp_path: Path) -> None:
    binary, source, output, eco = _files(tmp_path)
    with pytest.raises(CommandBuildError, match="Validation only"):
        build_command(
            {
                "input_files": [str(source)],
                "output_path": str(output),
                "validation_only": True,
                "formatting": {},
            },
            binary=binary,
            eco_file=eco,
        )

    plan = build_command(
        {
            "input_files": [str(source)],
            "validation_only": True,
            "formatting": {},
        },
        binary=binary,
        eco_file=eco,
    )
    assert plan.argv == ["-r"]
    assert plan.preview_argv == ["-r", "-f", INPUT_FILE_LIST_NAME]
