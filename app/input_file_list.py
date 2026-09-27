"""Create the short-lived file lists accepted by ``pgn-extract -f``."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

INPUT_FILE_LIST_NAME = "input-files.txt"


class InputFileListError(RuntimeError):
    """Raised when an app-owned pgn-extract input list cannot be created safely."""


def write_input_file_list(work_dir: Path, input_files: Iterable[Path]) -> Path:
    """Write raw absolute PGN paths, one per line, into ``work_dir``.

    ``pgn-extract -f`` reads one filename from each line, so paths are never
    quoted, shell-escaped, or passed through a command-line parser.  A newline
    or NUL in a filename would make that representation ambiguous and is
    rejected before anything is written.
    """

    directory = Path(work_dir)
    if not directory.is_dir():
        raise InputFileListError(
            f"Could not create input file list: folder does not exist: {directory}"
        )

    lines: list[str] = []
    for input_file in input_files:
        path = Path(input_file)
        if not path.is_absolute():
            raise InputFileListError(f"Input file path must be absolute: {path}")
        raw_path = str(path)
        if "\x00" in raw_path or "\r" in raw_path or "\n" in raw_path:
            raise InputFileListError(
                "Input file paths cannot contain NUL characters or newlines."
            )
        lines.append(raw_path)

    if not lines:
        raise InputFileListError("Cannot create an input file list without input files.")

    destination = directory / INPUT_FILE_LIST_NAME
    try:
        # The per-run directory is unique.  Exclusive creation still prevents
        # silently replacing an unexpected file if that invariant changes.
        with destination.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(lines))
            stream.write("\n")
    except (OSError, UnicodeError) as error:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise InputFileListError(f"Could not create input file list: {error}") from error
    return destination


__all__ = ["INPUT_FILE_LIST_NAME", "InputFileListError", "write_input_file_list"]
