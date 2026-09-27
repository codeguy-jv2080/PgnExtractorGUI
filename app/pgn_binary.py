"""Discovery and safe capability probing for the local pgn-extract executable.

This module never downloads, replaces, deletes, or modifies an executable.  It
only probes candidate files using an argv list (never a shell command) and
prefers the application's bundled ``bin\\pgn-extract.exe`` over the legacy
root-level executable.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .paths import AppPaths, get_app_paths

MIN_SUPPORTED_VERSION = "26-06"
MIN_SUPPORTED_VERSION_TUPLE = (26, 6)
DEFAULT_PROBE_TIMEOUT_SECONDS = 5.0
MAX_PROBE_OUTPUT_CHARS = 16_000

BinarySource = Literal["configured", "bundled", "root-fallback", "missing"]


class PgnExtractBinaryError(RuntimeError):
    """Raised when a caller requires a compatible pgn-extract executable."""


@dataclass(frozen=True)
class ProbeResult:
    """The result of one non-shell ``pgn-extract`` capability probe."""

    arguments: tuple[str, ...]
    return_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    error: str | None = None

    @property
    def output(self) -> str:
        """Combined process output, with stdout first for readability."""

        return "\n".join(part for part in (self.stdout, self.stderr) if part).strip()

    @property
    def succeeded(self) -> bool:
        return self.return_code == 0 and not self.timed_out and self.error is None

    def to_dict(self) -> dict[str, object]:
        return {
            "arguments": list(self.arguments),
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "error": self.error,
        }


@dataclass(frozen=True)
class BinaryInfo:
    """Status of a candidate pgn-extract executable.

    ``compatible`` requires both a recognizable pgn-extract identity and a
    parsed version at least :data:`MIN_SUPPORTED_VERSION`.  This intentionally
    prevents the old v26-04 executable from being silently selected.
    """

    path: Path | None
    source: BinarySource
    exists: bool
    recognized: bool
    version: str | None
    compatible: bool
    message: str
    version_probe: ProbeResult | None = None
    help_probe: ProbeResult | None = None

    @property
    def is_available(self) -> bool:
        return self.exists and self.path is not None

    @property
    def is_compatible(self) -> bool:
        return self.compatible

    @property
    def command(self) -> tuple[str, ...]:
        """The safe argv prefix, or an empty tuple when no binary is usable."""

        return (str(self.path),) if self.compatible and self.path is not None else ()

    def to_dict(self, *, include_probe_output: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "path": str(self.path) if self.path is not None else None,
            "source": self.source,
            "exists": self.exists,
            "recognized": self.recognized,
            "version": self.version,
            "compatible": self.compatible,
            "minimum_supported_version": MIN_SUPPORTED_VERSION,
            "message": self.message,
        }
        if include_probe_output:
            result["version_probe"] = (
                self.version_probe.to_dict() if self.version_probe is not None else None
            )
            result["help_probe"] = (
                self.help_probe.to_dict() if self.help_probe is not None else None
            )
        return result


@dataclass(frozen=True)
class BinaryCandidate:
    """One ordered discovery candidate."""

    path: Path
    source: BinarySource


_VERSION_PATTERN = re.compile(r"\bpgn-extract\s+v?(\d{2})[-.](\d{1,2})\b", re.IGNORECASE)


def parse_version(value: str | None) -> tuple[int, int] | None:
    """Parse a pgn-extract date-style version such as ``26-06``."""

    if not value:
        return None
    match = _VERSION_PATTERN.search(value)
    if match:
        return int(match.group(1)), int(match.group(2))

    simple = re.fullmatch(r"\s*v?(\d{2})[-.](\d{1,2})\s*", value)
    if simple:
        return int(simple.group(1)), int(simple.group(2))
    return None


def version_is_compatible(
    version: str | tuple[int, int] | None,
    *,
    minimum: tuple[int, int] = MIN_SUPPORTED_VERSION_TUPLE,
) -> bool:
    """Return whether a parsed pgn-extract version meets the GUI baseline."""

    parsed = parse_version(version) if isinstance(version, str) else version
    return parsed is not None and parsed >= minimum


def binary_candidates(
    paths: AppPaths | None = None,
    *,
    explicit_path: str | Path | None = None,
) -> list[BinaryCandidate]:
    """Return unique candidates in selection order, without probing them."""

    app_paths = paths or get_app_paths()
    candidates: list[BinaryCandidate] = []
    if explicit_path is not None:
        candidates.append(
            BinaryCandidate(
                path=Path(explicit_path).expanduser().resolve(), source="configured"
            )
        )
    candidates.extend(
        [
            BinaryCandidate(path=app_paths.bundled_binary_path, source="bundled"),
            BinaryCandidate(path=app_paths.legacy_binary_path, source="root-fallback"),
        ]
    )

    # Windows paths are case-insensitive.  Deduplicating prevents the same
    # executable being probed twice when an explicit path points to bin/.
    result: list[BinaryCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.path.resolve()).casefold()
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def probe_binary(
    path: str | Path,
    *,
    source: BinarySource = "configured",
    timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
    minimum_version: tuple[int, int] = MIN_SUPPORTED_VERSION_TUPLE,
) -> BinaryInfo:
    """Probe a candidate with ``--version`` and ``--help`` without a shell.

    ``pgn-extract --help`` intentionally exits non-zero, so its identity text
    is used for recognition rather than its exit code.  All output is captured
    and truncated for UI safety.
    """

    candidate = Path(path).expanduser().resolve()
    try:
        exists = candidate.is_file()
    except OSError as error:
        return BinaryInfo(
            path=candidate,
            source=source,
            exists=False,
            recognized=False,
            version=None,
            compatible=False,
            message=f"Could not inspect executable: {error}",
        )

    if not exists:
        return BinaryInfo(
            path=candidate,
            source=source,
            exists=False,
            recognized=False,
            version=None,
            compatible=False,
            message="Executable was not found.",
        )

    timeout = _normalized_timeout(timeout_seconds)
    version_probe = _run_probe(candidate, "--version", timeout_seconds=timeout)
    help_probe = _run_probe(candidate, "--help", timeout_seconds=timeout)
    version = _extract_version(version_probe.output) or _extract_version(help_probe.output)
    recognized = _looks_like_pgn_extract(version_probe.output) or _looks_like_pgn_extract(
        help_probe.output
    )
    compatible = recognized and version_is_compatible(version, minimum=minimum_version)
    message = _binary_message(
        candidate,
        recognized=recognized,
        version=version,
        compatible=compatible,
        version_probe=version_probe,
        help_probe=help_probe,
        minimum_version=minimum_version,
    )
    return BinaryInfo(
        path=candidate,
        source=source,
        exists=True,
        recognized=recognized,
        version=version,
        compatible=compatible,
        message=message,
        version_probe=version_probe,
        help_probe=help_probe,
    )


def discover_binary(
    paths: AppPaths | None = None,
    *,
    explicit_path: str | Path | None = None,
    timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
    minimum_version: tuple[int, int] = MIN_SUPPORTED_VERSION_TUPLE,
) -> BinaryInfo:
    """Find the first compatible local pgn-extract executable.

    The order is: user-configured path, bundled ``bin\\pgn-extract.exe``, then
    root ``pgn-extract.exe`` as a verified compatibility fallback.  If no
    compatible binary is available, the most informative existing candidate is
    returned for display; it still has ``compatible == False``.
    """

    probes: list[BinaryInfo] = []
    for candidate in binary_candidates(paths, explicit_path=explicit_path):
        info = probe_binary(
            candidate.path,
            source=candidate.source,
            timeout_seconds=timeout_seconds,
            minimum_version=minimum_version,
        )
        probes.append(info)
        if info.compatible:
            return info

    existing = next((info for info in probes if info.exists), None)
    if existing is not None:
        return existing
    return BinaryInfo(
        path=None,
        source="missing",
        exists=False,
        recognized=False,
        version=None,
        compatible=False,
        message=(
            "No compatible pgn-extract executable was found. Expected "
            "bin\\pgn-extract.exe (v26-06 or newer)."
        ),
    )


find_binary = discover_binary
find_pgn_extract = discover_binary


def require_compatible_binary(info: BinaryInfo) -> Path:
    """Return the executable path or raise an actionable startup/run error."""

    if info.compatible and info.path is not None:
        return info.path
    raise PgnExtractBinaryError(info.message)


def _run_probe(path: Path, argument: str, *, timeout_seconds: float) -> ProbeResult:
    argv = (str(path), argument)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            argv,
            cwd=str(path.parent),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            shell=False,
            creationflags=creation_flags,
        )
    except subprocess.TimeoutExpired as error:
        return ProbeResult(
            arguments=(argument,),
            return_code=None,
            stdout=_limited_text(error.stdout),
            stderr=_limited_text(error.stderr),
            timed_out=True,
            error=f"Timed out after {timeout_seconds:g} seconds.",
        )
    except OSError as error:
        return ProbeResult(
            arguments=(argument,),
            return_code=None,
            stdout="",
            stderr="",
            error=str(error),
        )

    return ProbeResult(
        arguments=(argument,),
        return_code=completed.returncode,
        stdout=_limited_text(completed.stdout),
        stderr=_limited_text(completed.stderr),
    )


def _normalized_timeout(value: float) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Probe timeout must be a positive number of seconds.") from error
    if timeout <= 0:
        raise ValueError("Probe timeout must be a positive number of seconds.")
    return timeout


def _limited_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = value
    if len(text) <= MAX_PROBE_OUTPUT_CHARS:
        return text
    return text[:MAX_PROBE_OUTPUT_CHARS] + "\n[probe output truncated]"


def _extract_version(output: str) -> str | None:
    match = _VERSION_PATTERN.search(output)
    if match is None:
        return None
    return f"{int(match.group(1)):02d}-{int(match.group(2)):02d}"


def _looks_like_pgn_extract(output: str) -> bool:
    lowered = output.lower()
    return "pgn-extract" in lowered and (
        "usage:" in lowered
        or "portable game notation" in lowered
        or _VERSION_PATTERN.search(output) is not None
    )


def _binary_message(
    path: Path,
    *,
    recognized: bool,
    version: str | None,
    compatible: bool,
    version_probe: ProbeResult,
    help_probe: ProbeResult,
    minimum_version: tuple[int, int],
) -> str:
    minimum = f"{minimum_version[0]:02d}-{minimum_version[1]:02d}"
    if compatible:
        return f"pgn-extract {version} is ready: {path}"
    if version_probe.timed_out or help_probe.timed_out:
        return f"Timed out while probing {path}."
    if version_probe.error or help_probe.error:
        detail = version_probe.error or help_probe.error
        return f"Could not run {path}: {detail}"
    if not recognized:
        return f"{path} did not identify itself as pgn-extract."
    if version is None:
        return f"pgn-extract was detected at {path}, but its version could not be determined."
    return f"pgn-extract {version} is too old; version {minimum} or newer is required."


__all__ = [
    "DEFAULT_PROBE_TIMEOUT_SECONDS",
    "MAX_PROBE_OUTPUT_CHARS",
    "MIN_SUPPORTED_VERSION",
    "MIN_SUPPORTED_VERSION_TUPLE",
    "BinaryCandidate",
    "BinaryInfo",
    "PgnExtractBinaryError",
    "ProbeResult",
    "binary_candidates",
    "discover_binary",
    "find_binary",
    "find_pgn_extract",
    "parse_version",
    "probe_binary",
    "require_compatible_binary",
    "version_is_compatible",
]
