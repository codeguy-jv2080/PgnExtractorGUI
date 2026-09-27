"""Convert GUI form state into a safe pgn-extract argv plan."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import list2cmdline
from typing import Any

from .input_file_list import INPUT_FILE_LIST_NAME


class CommandBuildError(ValueError):
    """Raised when a GUI request cannot become a safe command."""


@dataclass(frozen=True)
class OutputTarget:
    """A user-visible destination that is staged before it is committed."""

    name: str
    destination: Path
    mode: str = "create"  # ``create``, ``replace``, or ``append``


@dataclass
class CommandPlan:
    binary: Path
    argv: list[str]
    input_files: list[Path]
    stdin_text: str | None = None
    tag_criteria: list[str] = field(default_factory=list)
    outputs: list[OutputTarget] = field(default_factory=list)
    generated_output_directory: Path | None = None
    generated_output_mode: str | None = None
    warnings: list[str] = field(default_factory=list)
    unsafe_argument_file: bool = False

    @property
    def preview_argv(self) -> list[str]:
        """Return a readable argv preview without expanding every input path."""

        argv = list(self.argv)
        if self.input_files:
            # The runner writes this app-owned file in a per-run folder before
            # starting pgn-extract.  Its stable name makes the preview useful
            # without exposing an implementation marker or a giant command.
            argv.extend(["-f", INPUT_FILE_LIST_NAME])
        return argv

    @property
    def display_command(self) -> str:
        """A Windows-quotable preview only; this is never executed in a shell."""

        return list2cmdline([str(self.binary), *self.preview_argv])

    def to_preview(self) -> dict[str, Any]:
        return {
            "argv": [str(self.binary), *self.preview_argv],
            "display": self.display_command,
            "warnings": self.warnings,
            "outputs": [
                {"name": item.name, "path": str(item.destination), "mode": item.mode}
                for item in self.outputs
            ],
            "generated_output_directory": (
                str(self.generated_output_directory)
                if self.generated_output_directory
                else None
            ),
        }


OUTPUT_OPTION_NAMES = {
    "--output",
    "--append",
    "--duplicates",
    "--nonmatching",
    "--logfile",
}

DATE_VALUE_PATTERN = re.compile(r"^\d{4}(?:\.\d{2}(?:\.\d{2})?)?$")


def _as_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _path(value: Any, field_name: str) -> Path:
    text = _as_text(value)
    if not text:
        raise CommandBuildError(f"{field_name} is required.")
    # Resolve lexical ``..`` segments (and existing links) so an output cannot
    # bypass the input/output collision check by spelling the same file twice.
    return Path(text).expanduser().resolve(strict=False)


def _positive_integer(value: Any, field_name: str, minimum: int = 1) -> int | None:
    text = _as_text(value)
    if not text:
        return None
    try:
        number = int(text)
    except ValueError as error:
        raise CommandBuildError(f"{field_name} must be a whole number.") from error
    if number < minimum:
        raise CommandBuildError(f"{field_name} must be at least {minimum}.")
    return number


def _checkbox(container: dict[str, Any], name: str, default: bool = False) -> bool:
    value = container.get(name, default)
    return value is True or value in {1, "1", "true", "True", "on"}


def _normalise_input_files(value: Any) -> list[Path]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CommandBuildError("Input files must be a list.")
    files: list[Path] = []
    for raw_path in value:
        candidate = _path(raw_path, "An input file")
        if not candidate.is_file():
            raise CommandBuildError(f"Input file does not exist: {candidate}")
        files.append(candidate)
    return files


def _same_file(left: Path, right: Path) -> bool:
    """Compare normalized paths, including existing hard links where possible."""

    if left == right:
        return True
    try:
        return left.exists() and right.exists() and left.samefile(right)
    except OSError:
        return False


def _require_safe_advanced_tokens(tokens: Iterable[Any]) -> tuple[list[str], bool, str | None]:
    """Validate literal advanced argv tokens.

    File-producing switches use structured GUI fields so their targets can be
    staged.  This avoids bypassing overwrite confirmation with a pasted shell
    fragment.  ``-A`` remains available only as an explicitly acknowledged
    legacy mode because its contents can carry arbitrary output directives.
    """

    if isinstance(tokens, (str, bytes)):
        raise CommandBuildError("Advanced arguments must be a list of argv tokens.")

    normalised: list[str] = []
    unsafe_argument_file = False
    generated_mode: str | None = None
    reject_next = False

    for raw_token in tokens:
        token = _as_text(raw_token)
        if not token:
            continue
        if "\x00" in token:
            raise CommandBuildError("Advanced arguments cannot contain NUL characters.")
        if reject_next:
            raise CommandBuildError(
                "Output destinations must be chosen with the Output controls, not Advanced arguments."
            )
        if token in OUTPUT_OPTION_NAMES:
            reject_next = True
            continue
        if token.startswith(("-o", "-a", "-d", "-n", "-l", "-L")) and not token.startswith("--"):
            # Single-character flags need an attached path in pgn-extract.
            raise CommandBuildError(
                "Output destinations must be chosen with the Output controls, not Advanced arguments."
            )
        if any(token.startswith(f"{option}=") for option in OUTPUT_OPTION_NAMES):
            raise CommandBuildError(
                "Output destinations must be chosen with the Output controls, not Advanced arguments."
            )
        if token == "-A" or token.startswith("-A"):
            unsafe_argument_file = True
        if token.startswith("-E") or token == "--split-eco":
            generated_mode = "append"
        if token.startswith("-#"):
            generated_mode = "replace"
        normalised.append(token)

    if reject_next:
        raise CommandBuildError("An advanced output option is missing its filename.")
    return normalised, unsafe_argument_file, generated_mode


def _criterion_value(tag_name: str, value: Any) -> str:
    """Return a tag-criteria value that is safe to write into a criteria file."""

    text = _as_text(value)
    if '"' in text or "\n" in text or "\r" in text:
        raise CommandBuildError(f"{tag_name} criteria cannot contain quotes or newlines.")
    return text


def _date_criterion_value(field_name: str, value: Any) -> str:
    """Validate the YYYY, YYYY.MM, or YYYY.MM.DD forms accepted by pgn-extract."""

    text = _criterion_value("Date", value)
    if text and not DATE_VALUE_PATTERN.fullmatch(text):
        raise CommandBuildError(f"{field_name} must use YYYY, YYYY.MM, or YYYY.MM.DD.")
    return text


def _selected_game_ranges(value: Any) -> str | None:
    """Validate pgn-extract's strictly ascending --selectonly range syntax."""

    text = _as_text(value)
    if not text:
        return None

    ranges: list[str] = []
    previous_end = 0
    for raw_range in text.split(","):
        part = raw_range.strip()
        if not part:
            raise CommandBuildError("Selected games must be a comma-separated list of game numbers or ranges.")
        bounds = part.split(":")
        if len(bounds) > 2 or any(not bound.isdecimal() for bound in bounds):
            raise CommandBuildError("Selected game ranges use one colon, for example 1:10,15,89:94.")
        start = _positive_integer(bounds[0], "Selected game number")
        end = _positive_integer(bounds[-1], "Selected game number")
        assert start is not None and end is not None  # Non-empty range parts always yield a number.
        if start > end:
            raise CommandBuildError("Selected game ranges must run from the smaller number to the larger number.")
        if start <= previous_end:
            raise CommandBuildError("Selected game ranges must be strictly ascending and cannot overlap.")
        ranges.append(str(start) if start == end else f"{start}:{end}")
        previous_end = end
    return ",".join(ranges)


def _make_tag_criteria(filters: dict[str, Any]) -> list[str]:
    tags = {
        "Player": _as_text(filters.get("player")),
        "Event": _as_text(filters.get("event")),
        "Site": _as_text(filters.get("site")),
        "Date": _as_text(filters.get("date")),
        "Round": _as_text(filters.get("round")),
        "White": _as_text(filters.get("white")),
        "Black": _as_text(filters.get("black")),
        "Result": _as_text(filters.get("result")),
        "ECO": _as_text(filters.get("eco")),
    }
    criteria: list[str] = []
    for tag_name, value in tags.items():
        if not value:
            continue
        if tag_name == "Date":
            value = _date_criterion_value("Date/year", value)
        else:
            value = _criterion_value(tag_name, value)
        criteria.append(f'{tag_name} "{value}"')

    date_from = _date_criterion_value("Date from", filters.get("date_from"))
    date_to = _date_criterion_value("Date through", filters.get("date_to"))
    if tags["Date"] and (date_from or date_to):
        raise CommandBuildError("Use either Date/year or a Date from/through range, not both.")
    if date_from:
        criteria.append(f'Date >= "{date_from}"')
    if date_to:
        criteria.append(f'Date <= "{date_to}"')

    minimum_elo = _positive_integer(filters.get("minimum_elo"), "Minimum Elo", minimum=0)
    maximum_elo = _positive_integer(filters.get("maximum_elo"), "Maximum Elo", minimum=0)
    if minimum_elo is not None and maximum_elo is not None and minimum_elo > maximum_elo:
        raise CommandBuildError("Minimum Elo cannot be greater than maximum Elo.")
    if minimum_elo is not None:
        criteria.append(f'Elo >= "{minimum_elo}"')
    if maximum_elo is not None:
        criteria.append(f'Elo <= "{maximum_elo}"')
    return criteria


def build_command(
    form: dict[str, Any],
    binary: Path,
    eco_file: Path | None = None,
) -> CommandPlan:
    """Build a command plan from the browser's structured form state."""

    if not binary.is_file():
        raise CommandBuildError(f"pgn-extract v26-06 was not found: {binary}")

    if not isinstance(form, dict):
        raise CommandBuildError("The request must include a form object.")
    filters = form.get("game_filters") or {}
    formatting = form.get("formatting") or {}
    if not isinstance(filters, dict) or not isinstance(formatting, dict):
        raise CommandBuildError("Filter and formatting settings must be objects.")

    input_files = _normalise_input_files(form.get("input_files"))
    stdin_text = _as_text(form.get("stdin_text")) or None
    if not input_files and not stdin_text:
        raise CommandBuildError("Select at least one PGN input file or paste PGN text.")

    argv: list[str] = []
    tag_criteria = _make_tag_criteria(filters)
    if tag_criteria:
        # The run manager substitutes this literal with a staged criteria file.
        argv.append("-t__PGN_EXTRACT_GUI_TAGS__")

    validation_only = _checkbox(form, "validation_only")
    if validation_only:
        # -r deliberately checks and reports errors without writing matched games.
        argv.append("-r")

    for flag, field_name, minimum in (
        ("--minply", "min_plies", 0),
        ("--maxply", "max_plies", 0),
        ("--firstgame", "first_game", 1),
        ("--gamelimit", "last_game", 1),
    ):
        value = _positive_integer(filters.get(field_name), field_name.replace("_", " "), minimum)
        if value is not None:
            argv.extend([flag, str(value)])

    selected_games = _selected_game_ranges(filters.get("selected_games"))
    if selected_games:
        argv.extend(["--selectonly", selected_games])

    if _checkbox(filters, "checkmate"):
        argv.append("--checkmate")
    if _checkbox(filters, "stalemate"):
        argv.append("--stalemate")
    if _checkbox(filters, "repetition"):
        argv.append("--repetition")
    if _checkbox(filters, "fivefold_repetition"):
        argv.append("--repetition5")
    if _checkbox(filters, "commented"):
        argv.append("--commented")
    if _checkbox(filters, "setup_position"):
        argv.append("--onlysetuptags")

    remove_duplicates = _checkbox(formatting, "remove_duplicates")
    remove_comments = (
        _checkbox(formatting, "remove_comments")
        if "remove_comments" in formatting
        else not _checkbox(
            formatting,
            "keep_comments",
            _checkbox(formatting, "include_comments", True),
        )
    )
    remove_nags = (
        _checkbox(formatting, "remove_nags")
        if "remove_nags" in formatting
        else not _checkbox(
            formatting,
            "keep_nags",
            _checkbox(formatting, "include_nags", True),
        )
    )
    include_tags = _checkbox(formatting, "include_tags", True)
    variation_mode = _as_text(formatting.get("variations")).lower()
    remove_variations = (
        _checkbox(formatting, "remove_variations")
        if "remove_variations" in formatting
        else not _checkbox(formatting, "keep_variations", variation_mode in {"", "keep"})
    )
    if variation_mode in {"mainline", "remove"}:
        remove_variations = True
    if remove_duplicates:
        argv.append("--noduplicates")
    if remove_comments:
        argv.append("--nocomments")
    if remove_nags:
        argv.append("--nonags")
    if remove_variations:
        argv.append("--novars")
    if not include_tags:
        argv.append("--notags")
    if _checkbox(formatting, "fen_comments", _checkbox(formatting, "include_fen_comments")):
        argv.append("--fencomments")

    output_format = _as_text(formatting.get("output_format")).lower()
    if output_format == "pgn":
        output_format = "san"
    allowed_formats = {
        "",
        "san",
        "input",
        "cm",
        "epd",
        "fen",
        "halg",
        "lalg",
        "elalg",
        "xlalg",
        "xolalg",
        "uci",
        "json",
    }
    if output_format not in allowed_formats:
        raise CommandBuildError(f"Unsupported output format: {output_format}")
    if output_format == "input":
        argv.append("-W")
    elif output_format and output_format not in {"san", "json"}:
        argv.append(f"-W{output_format}")
    if output_format == "json":
        argv.append("--json")

    if _checkbox(formatting, "eco", _checkbox(formatting, "classify_eco")):
        if eco_file is None or not eco_file.is_file():
            raise CommandBuildError("The bundled ECO classification file is unavailable.")
        argv.append(f"-e{eco_file.absolute()}")

    line_width = _positive_integer(formatting.get("line_width"), "line width", minimum=20)
    if line_width is not None:
        argv.append(f"-w{line_width}")

    output_path = _as_text(form.get("output_path"))
    append_output = _checkbox(form, "append_output")
    overwrite_output = _checkbox(form, "overwrite_output")
    split_games = _positive_integer(form.get("split_games"), "Games per output file")
    if append_output and overwrite_output:
        raise CommandBuildError("Choose either Append or Overwrite, not both.")
    if validation_only and (output_path or split_games is not None):
        raise CommandBuildError("Validation only checks input and does not write an output PGN or split files.")
    outputs: list[OutputTarget] = []
    warnings: list[str] = []
    if output_path:
        destination = _path(output_path, "Output path")
        if any(_same_file(destination, input_file) for input_file in input_files):
            raise CommandBuildError("The output path cannot be one of the input files.")
        output_mode = "append" if append_output else "replace" if overwrite_output else "create"
        outputs.append(OutputTarget("Matched games", destination, output_mode))
        # The run manager replaces this marker with an app-owned staging path.
        argv.extend(["--append" if append_output else "--output", "__PGN_EXTRACT_GUI_OUTPUT_0__"])
        if append_output:
            warnings.append("Appending changes the selected output file after a successful run.")
        elif overwrite_output:
            warnings.append("Overwrite is selected; an existing output file will be replaced.")
        elif destination.exists():
            warnings.append(
                "The output file already exists. Choose Overwrite or Append before running."
            )
    advanced_tokens, unsafe_argument_file, generated_mode = _require_safe_advanced_tokens(
        form.get("advanced_tokens") or []
    )
    if unsafe_argument_file:
        warnings.append(
            "An -A argument file can contain its own output paths; review it carefully before running."
        )
    if split_games is not None:
        if generated_mode:
            raise CommandBuildError("Choose one split-output method at a time.")
        generated_mode = "replace"
        argv.append(f"-#{split_games}")
    argv.extend(advanced_tokens)

    if generated_mode and outputs:
        raise CommandBuildError(
            "Choose either one Output file or split output (-E/-#), not both."
        )
    if validation_only and generated_mode:
        raise CommandBuildError("Validation only checks input and cannot be combined with split output.")
    if validation_only:
        warnings.append("Validation only checks the input and reports any errors in the run log.")
    elif not output_path and not generated_mode:
        warnings.append("No output file is selected; matched games will be captured from standard output.")

    generated_dir_text = _as_text(form.get("split_output_dir"))
    generated_directory: Path | None = None
    if generated_mode:
        if not generated_dir_text:
            raise CommandBuildError("Choose a split-output folder when splitting games.")
        generated_directory = _path(generated_dir_text, "Split-output folder")
        if not generated_directory.is_dir():
            raise CommandBuildError(f"Split-output folder does not exist: {generated_directory}")
        label = "append to" if generated_mode == "append" else "replace files in"
        warnings.append(f"Split output will {label} {generated_directory}.")

    return CommandPlan(
        binary=binary,
        argv=argv,
        input_files=input_files,
        stdin_text=stdin_text,
        tag_criteria=tag_criteria,
        outputs=outputs,
        generated_output_directory=generated_directory,
        generated_output_mode=generated_mode,
        warnings=warnings,
        unsafe_argument_file=unsafe_argument_file,
    )
