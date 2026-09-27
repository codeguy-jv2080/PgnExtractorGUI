"""Read-only PGN game counting through the bundled pgn-extract executable."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from .input_file_list import InputFileListError, write_input_file_list

SUMMARY_PATTERN = re.compile(
    r"(?m)^(?P<matched>\d+) games? matched out of (?P<total>\d+)\.\s*$"
)


class GameCountError(RuntimeError):
    """Raised when pgn-extract cannot provide a reliable game count."""


def count_games(binary: Path, input_files: Sequence[Path]) -> int:
    """Return the number of games across ``input_files`` without writing output.

    ``-r`` is pgn-extract's documented check-only mode.  ``--quiet`` keeps the
    normal per-game progress out of the response, while the following
    ``--summary`` restores just the final count.  The order of those two
    options matters to pgn-extract.  Input paths are supplied through
    pgn-extract's ``-f`` file-list option, rather than one argv item per file,
    so a large selection cannot exceed Windows' command-line length limit.
    """

    if not input_files:
        raise GameCountError("Select at least one PGN file to count.")

    try:
        with TemporaryDirectory(prefix="pgn-extract-gui-count-") as temporary_directory:
            file_list = write_input_file_list(Path(temporary_directory), input_files)
            completed = subprocess.run(
                [
                    str(binary),
                    "-r",
                    "--quiet",
                    "--summary",
                    f"-f{file_list}",
                ],
                cwd=str(binary.parent),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    except InputFileListError as error:
        raise GameCountError(str(error)) from error
    except OSError as error:
        raise GameCountError(f"Could not prepare or start pgn-extract: {error}") from error

    combined_output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    match = SUMMARY_PATTERN.search(combined_output)
    if completed.returncode != 0:
        detail = _diagnostic(combined_output)
        if detail:
            raise GameCountError(f"pgn-extract could not count the selected file(s): {detail}")
        raise GameCountError(
            f"pgn-extract could not count the selected file(s) (exit code {completed.returncode})."
        )
    if match is None:
        raise GameCountError("pgn-extract did not return a game count for the selected file(s).")
    return int(match.group("total"))


def _diagnostic(output: str) -> str:
    """Return the first useful pgn-extract diagnostic without flooding the UI."""

    for line in output.splitlines():
        text = line.strip()
        if text:
            return text[:600]
    return ""


__all__ = ["GameCountError", "count_games"]
