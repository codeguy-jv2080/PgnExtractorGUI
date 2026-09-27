import sys
import time
from pathlib import Path

import pytest

from app.command_builder import CommandPlan, OutputTarget
from app.input_file_list import INPUT_FILE_LIST_NAME, InputFileListError
from app.paths import get_app_paths
from app.run_manager import RunConflictError, RunManager


def test_runner_stages_then_replaces_confirmed_output(tmp_path: Path) -> None:
    paths = get_app_paths(root_dir=tmp_path / "install", data_dir=tmp_path / "data")
    output = tmp_path / "chosen-output.pgn"
    output.write_text("old data", encoding="utf-8")
    plan = CommandPlan(
        binary=Path(sys.executable),
        argv=[
            "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('new data', encoding='utf-8')",
            "__PGN_EXTRACT_GUI_OUTPUT_0__",
        ],
        input_files=[],
        outputs=[OutputTarget("Matched games", output, mode="replace")],
    )
    manager = RunManager(paths)

    with pytest.raises(RunConflictError):
        manager.start(plan, confirm_overwrite=False)
    assert output.read_text(encoding="utf-8") == "old data"

    job = manager.start(plan, confirm_overwrite=True)
    deadline = time.monotonic() + 10
    while job.status in {"queued", "running", "cancelling"} and time.monotonic() < deadline:
        time.sleep(0.02)

    assert job.status == "succeeded", job.error
    assert output.read_text(encoding="utf-8") == "new data"
    assert job.outputs == [str(output)]


def test_default_create_never_replaces_an_existing_output(tmp_path: Path) -> None:
    paths = get_app_paths(root_dir=tmp_path / "install", data_dir=tmp_path / "data")
    output = tmp_path / "chosen-output.pgn"
    output.write_text("original data", encoding="utf-8")
    plan = CommandPlan(
        binary=Path(sys.executable),
        argv=[],
        input_files=[],
        outputs=[OutputTarget("Matched games", output)],
    )

    with pytest.raises(RunConflictError, match="Choose Overwrite or Append"):
        RunManager(paths).start(plan, confirm_overwrite=True)

    assert output.read_text(encoding="utf-8") == "original data"


def test_runner_supplies_selected_inputs_through_a_staged_file_list(tmp_path: Path) -> None:
    paths = get_app_paths(root_dir=tmp_path / "install", data_dir=tmp_path / "data")
    first = (tmp_path / "first input.pgn").resolve()
    second = (tmp_path / "second input.pgn").resolve()
    first.write_text("[Event \"First\"]\n", encoding="utf-8")
    second.write_text("[Event \"Second\"]\n", encoding="utf-8")
    plan = CommandPlan(
        binary=Path(sys.executable),
        argv=[
            "-c",
            "from pathlib import Path; import sys; print(Path(sys.argv[-1]).read_text(encoding='utf-8'), end='')",
        ],
        input_files=[first, second],
    )

    job = RunManager(paths).start(plan)
    deadline = time.monotonic() + 10
    while job.status in {"queued", "running", "cancelling"} and time.monotonic() < deadline:
        time.sleep(0.02)

    assert job.status == "succeeded", job.error
    assert job.stdout.splitlines() == [str(first), str(second)]
    assert job.work_dir is not None
    assert (job.work_dir / INPUT_FILE_LIST_NAME).read_text(encoding="utf-8").splitlines() == [
        str(first),
        str(second),
    ]
    assert INPUT_FILE_LIST_NAME in job.display_command
    assert str(first) not in job.display_command
    assert str(second) not in job.display_command


def test_runner_reports_a_staged_input_list_failure(monkeypatch, tmp_path: Path) -> None:
    paths = get_app_paths(root_dir=tmp_path / "install", data_dir=tmp_path / "data")
    source = (tmp_path / "input.pgn").resolve()
    source.write_text("[Event \"Example\"]\n", encoding="utf-8")
    plan = CommandPlan(binary=Path(sys.executable), argv=[], input_files=[source])

    def fail_to_write(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise InputFileListError("Could not create input file list: access denied")

    monkeypatch.setattr("app.run_manager.write_input_file_list", fail_to_write)
    job = RunManager(paths).start(plan)
    deadline = time.monotonic() + 10
    while job.status in {"queued", "running", "cancelling"} and time.monotonic() < deadline:
        time.sleep(0.02)

    assert job.status == "failed"
    assert job.error == "Could not create input file list: access denied"
