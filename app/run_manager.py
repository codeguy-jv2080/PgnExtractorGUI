"""Serialized, staged execution of the local pgn-extract binary."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .command_builder import CommandPlan
from .input_file_list import write_input_file_list
from .paths import AppPaths

MAX_CAPTURE_BYTES = 2 * 1024 * 1024
TERMINATE_TIMEOUT_SECONDS = 5.0


class RunError(RuntimeError):
    """Base exception for a run that cannot be started safely."""


class RunConflictError(RunError):
    """Raised when a user confirmation is needed before changing files."""


@dataclass(frozen=True)
class DestinationSnapshot:
    """A lightweight identity check used to detect external file changes."""

    exists: bool
    device: int | None = None
    inode: int | None = None
    size: int | None = None
    modified_ns: int | None = None


@dataclass
class RunJob:
    """Mutable state for one app-owned pgn-extract process."""

    id: str
    plan: CommandPlan
    status: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    finished_at: str | None = None
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    warnings: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    error: str | None = None
    work_dir: Path | None = None
    display_command: str = ""
    _process: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    _cancel_requested: bool = field(default=False, repr=False)
    _output_snapshots: dict[str, DestinationSnapshot] = field(default_factory=dict, repr=False)
    _generated_output_snapshots: dict[str, DestinationSnapshot] = field(
        default_factory=dict, repr=False
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "warnings": self.warnings,
            "outputs": self.outputs,
            "error": self.error,
            "display_command": self.display_command,
        }


class RunManager:
    """Run one pgn-extract command at a time in an app-owned staging folder.

    Direct ``pgn-extract`` outputs are written only into a unique folder below
    the application's per-user data directory.  Files are copied/renamed to
    user-selected destinations only after a zero exit status and any required
    confirmation.  This makes output failures leave existing PGNs intact.
    """

    def __init__(
        self,
        paths: AppPaths,
        history_recorder: Callable[..., Any] | None = None,
        *,
        capture_limit: int = MAX_CAPTURE_BYTES,
    ) -> None:
        self.paths = paths
        self.paths.ensure_data_directories()
        self._history_recorder = history_recorder
        self._capture_limit = max(1024, int(capture_limit))
        self._lock = threading.RLock()
        self._jobs: dict[str, RunJob] = {}
        self._active_job_id: str | None = None

    def start(self, plan: CommandPlan, *, confirm_overwrite: bool = False) -> RunJob:
        """Validate and begin a background job.

        ``confirm_overwrite`` is intentionally a request-level choice.  The UI
        shows the paths returned by command preview before it sends this flag.
        """

        with self._lock:
            if self._active_job_id is not None:
                active = self._jobs.get(self._active_job_id)
                if active and active.status in {"queued", "running", "cancelling"}:
                    raise RunConflictError("Another pgn-extract run is already active.")
                self._active_job_id = None

            output_snapshots, generated_output_snapshots = self._preflight(
                plan, confirm_overwrite=confirm_overwrite
            )
            job = RunJob(
                id=uuid4().hex,
                plan=plan,
                warnings=list(plan.warnings),
                display_command=plan.display_command,
                _output_snapshots=output_snapshots,
                _generated_output_snapshots=generated_output_snapshots,
            )
            self._jobs[job.id] = job
            self._active_job_id = job.id
            worker = threading.Thread(
                target=self._run_worker,
                args=(job, confirm_overwrite),
                name=f"pgn-extract-{job.id[:8]}",
                daemon=True,
            )
            worker.start()
            return job

    def get(self, job_id: str) -> RunJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> RunJob:
        """Request cancellation of a queued or running subprocess."""

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise RunError("Run not found.")
            if job.status in {"succeeded", "failed", "cancelled"}:
                return job
            job._cancel_requested = True
            if job.status == "queued":
                job.status = "cancelled"
                job.finished_at = datetime.now(timezone.utc).isoformat()
                return job
            job.status = "cancelling"
            process = job._process

        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        return job

    def _preflight(
        self, plan: CommandPlan, *, confirm_overwrite: bool
    ) -> tuple[dict[str, DestinationSnapshot], dict[str, DestinationSnapshot]]:
        if not plan.binary.is_file():
            raise RunError(f"pgn-extract executable does not exist: {plan.binary}")
        for input_file in plan.input_files:
            if not input_file.is_file():
                raise RunError(f"Input file no longer exists: {input_file}")

        output_snapshots: dict[str, DestinationSnapshot] = {}
        for output in plan.outputs:
            if not output.destination.parent.is_dir():
                raise RunError(f"Output folder does not exist: {output.destination.parent}")
            if output.mode not in {"create", "replace", "append"}:
                raise RunError(f"Unsupported output mode: {output.mode}")
            snapshot = self._snapshot(output.destination)
            output_snapshots[output.name] = snapshot
            if snapshot.exists and not output.destination.is_file():
                raise RunError(f"Output destination is not a file: {output.destination}")
            if snapshot.exists and output.mode == "create":
                raise RunConflictError(
                    f"Output file already exists: {output.destination}. "
                    "Choose Overwrite or Append explicitly."
                )
            if snapshot.exists and not confirm_overwrite:
                action = "append to" if output.mode == "append" else "replace"
                raise RunConflictError(
                    f"Confirmation is required to {action} existing file: {output.destination}"
                )

        generated_output_snapshots: dict[str, DestinationSnapshot] = {}
        if plan.generated_output_directory is not None:
            if not plan.generated_output_directory.is_dir():
                raise RunError(
                    f"Split-output folder no longer exists: {plan.generated_output_directory}"
                )
            # pgn-extract uses predictable names for -E and -#.  There is no
            # safe way to know the complete list before parsing, so require a
            # deliberate confirmation for all split runs.
            if not confirm_overwrite:
                raise RunConflictError(
                    "Confirmation is required before exporting generated split-output files."
                )
            generated_output_snapshots = self._snapshot_generated_outputs(
                plan.generated_output_directory
            )
        if plan.unsafe_argument_file and not confirm_overwrite:
            raise RunConflictError(
                "Confirmation is required for a legacy -A argument file because it may define output paths."
            )
        return output_snapshots, generated_output_snapshots

    def _run_worker(self, job: RunJob, confirm_overwrite: bool) -> None:
        started = time.monotonic()
        work_dir = self.paths.run_dir / job.id
        try:
            work_dir.mkdir(parents=True, exist_ok=False)
            job.work_dir = work_dir
            with self._lock:
                if job._cancel_requested:
                    job.status = "cancelled"
                    return
                job.status = "running"
                job.started_at = datetime.now(timezone.utc).isoformat()

            argv, staged_outputs = self._materialise_command(job.plan, work_dir)
            job.display_command = subprocess.list2cmdline([str(job.plan.binary), *argv])
            process = subprocess.Popen(
                [str(job.plan.binary), *argv],
                cwd=work_dir,
                stdin=subprocess.PIPE if job.plan.stdin_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            with self._lock:
                job._process = process

            # Start draining child output before writing pasted PGN to stdin.
            # Otherwise a process that emits output while consuming input can
            # fill its stdout pipe, stop reading stdin, and deadlock this write.
            stdout_parts: list[bytes] = []
            stderr_parts: list[bytes] = []
            capture_state = {"stdout": False, "stderr": False}
            readers = [
                threading.Thread(
                    target=self._capture_stream,
                    args=(process.stdout, stdout_parts, capture_state, "stdout"),
                    daemon=True,
                ),
                threading.Thread(
                    target=self._capture_stream,
                    args=(process.stderr, stderr_parts, capture_state, "stderr"),
                    daemon=True,
                ),
            ]
            for reader in readers:
                reader.start()

            if job.plan.stdin_text is not None and process.stdin is not None:
                try:
                    process.stdin.write(job.plan.stdin_text.encode("utf-8"))
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass

            while process.poll() is None:
                if job._cancel_requested:
                    self._terminate_process(process)
                    break
                time.sleep(0.1)
            job.returncode = process.wait()
            for reader in readers:
                reader.join(timeout=2)

            job.stdout = b"".join(stdout_parts).decode("utf-8", errors="replace")
            job.stderr = b"".join(stderr_parts).decode("utf-8", errors="replace")
            job.stdout_truncated = capture_state["stdout"]
            job.stderr_truncated = capture_state["stderr"]

            if job._cancel_requested:
                job.status = "cancelled"
                job.error = "The run was cancelled. Any staged output was not exported."
            elif job.returncode == 0:
                exported = self._commit_outputs(
                    job,
                    staged_outputs,
                    work_dir,
                    confirm_overwrite=confirm_overwrite,
                )
                job.outputs = [str(path) for path in exported]
                job.status = "succeeded"
            else:
                job.status = "failed"
                job.error = f"pgn-extract exited with code {job.returncode}."
        except Exception as error:  # noqa: BLE001 - worker failures must reach the GUI.
            job.status = "cancelled" if job._cancel_requested else "failed"
            job.error = str(error)
        finally:
            job.finished_at = datetime.now(timezone.utc).isoformat()
            duration_ms = int((time.monotonic() - started) * 1000)
            self._record_history(job, duration_ms)
            with self._lock:
                job._process = None
                if self._active_job_id == job.id:
                    self._active_job_id = None

    def _capture_stream(
        self,
        stream: Any,
        destination: list[bytes],
        state: dict[str, bool],
        name: str,
    ) -> None:
        if stream is None:
            return
        total = 0
        try:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                permitted = 0
                if total < self._capture_limit:
                    permitted = self._capture_limit - total
                    destination.append(chunk[:permitted])
                    total += min(len(chunk), permitted)
                if len(chunk) > permitted:
                    state[name] = True
        finally:
            try:
                stream.close()
            except OSError:
                pass

    @staticmethod
    def _terminate_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=TERMINATE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass

    def _materialise_command(
        self,
        plan: CommandPlan,
        work_dir: Path,
    ) -> tuple[list[str], dict[str, Path]]:
        staged_outputs: dict[str, Path] = {}
        for index, output in enumerate(plan.outputs):
            suffix = output.destination.suffix or ".pgn"
            staged_outputs[output.name] = work_dir / f"output-{index}{suffix}"

        argv: list[str] = []
        for token in plan.argv:
            materialised = token
            for index, output in enumerate(plan.outputs):
                materialised = materialised.replace(
                    f"__PGN_EXTRACT_GUI_OUTPUT_{index}__",
                    str(staged_outputs[output.name]),
                )
            if "__PGN_EXTRACT_GUI_TAGS__" in materialised:
                criteria_path = work_dir / "tag-criteria.txt"
                criteria_path.write_text("\n".join(plan.tag_criteria) + "\n", encoding="utf-8")
                materialised = materialised.replace("__PGN_EXTRACT_GUI_TAGS__", str(criteria_path))
            argv.append(materialised)
        if plan.input_files:
            input_file_list = write_input_file_list(work_dir, plan.input_files)
            argv.extend(["-f", str(input_file_list)])
        return argv, staged_outputs

    def _commit_outputs(
        self,
        job: RunJob,
        staged_outputs: dict[str, Path],
        work_dir: Path,
        *,
        confirm_overwrite: bool,
    ) -> list[Path]:
        plan = job.plan
        exported: list[Path] = []
        for output in plan.outputs:
            staged = staged_outputs[output.name]
            if not staged.exists():
                # A successful check-only run may intentionally have no output.
                continue
            destination = output.destination
            expected = job._output_snapshots.get(output.name)
            if expected is None:
                raise RunError(f"No preflight snapshot exists for {destination}.")
            self._validate_destination_snapshot(
                destination,
                expected,
                mode=output.mode,
                confirm_overwrite=confirm_overwrite,
            )
            if output.mode == "append" and expected.exists:
                self._append_staged_file(staged, destination, expected)
            elif expected.exists:
                self._replace_staged_file(staged, destination, expected)
            else:
                self._create_staged_file(staged, destination)
            staged.unlink(missing_ok=True)
            exported.append(destination)

        if plan.generated_output_directory is not None:
            exported.extend(
                self._commit_generated_outputs(
                    plan.generated_output_directory,
                    plan.generated_output_mode or "replace",
                    work_dir,
                    confirm_overwrite=confirm_overwrite,
                    expected_snapshots=job._generated_output_snapshots,
                )
            )
        return exported

    def _commit_generated_outputs(
        self,
        destination_directory: Path,
        mode: str,
        work_dir: Path,
        *,
        confirm_overwrite: bool,
        expected_snapshots: dict[str, DestinationSnapshot],
    ) -> list[Path]:
        if not confirm_overwrite:
            raise RunConflictError("Split-output confirmation was lost.")
        if mode not in {"replace", "append"}:
            raise RunError(f"Unsupported split-output mode: {mode}")

        sources = sorted(work_dir.glob("*.pgn"))
        for source in sources:
            destination = destination_directory / source.name
            expected = expected_snapshots.get(source.name, DestinationSnapshot(exists=False))
            self._validate_generated_destination(destination, expected)

        exported: list[Path] = []
        for source in sources:
            destination = destination_directory / source.name
            expected = expected_snapshots.get(source.name, DestinationSnapshot(exists=False))
            if mode == "append" and expected.exists:
                self._append_staged_file(source, destination, expected)
            elif expected.exists:
                self._replace_staged_file(source, destination, expected)
            else:
                self._create_staged_file(source, destination)
            exported.append(destination)
        return exported

    @staticmethod
    def _snapshot(path: Path) -> DestinationSnapshot:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return DestinationSnapshot(exists=False)
        except OSError as error:
            raise RunError(f"Could not inspect output destination {path}: {error}") from error
        return DestinationSnapshot(
            exists=True,
            device=stat.st_dev,
            inode=stat.st_ino,
            size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
        )

    def _snapshot_generated_outputs(self, directory: Path) -> dict[str, DestinationSnapshot]:
        snapshots: dict[str, DestinationSnapshot] = {}
        try:
            candidates = list(directory.glob("*.pgn"))
        except OSError as error:
            raise RunError(f"Could not inspect split-output folder {directory}: {error}") from error
        for candidate in candidates:
            snapshot = self._snapshot(candidate)
            if snapshot.exists and not candidate.is_file():
                raise RunError(f"Split-output destination is not a file: {candidate}")
            snapshots[candidate.name] = snapshot
        return snapshots

    def _validate_destination_snapshot(
        self,
        destination: Path,
        expected: DestinationSnapshot,
        *,
        mode: str,
        confirm_overwrite: bool,
    ) -> None:
        current = self._snapshot(destination)
        if current != expected:
            raise RunConflictError(
                f"Output changed after this run started: {destination}. Review it and run again."
            )
        if mode == "create":
            if current.exists:
                raise RunConflictError(
                    f"Output file already exists: {destination}. Choose Overwrite or Append explicitly."
                )
            return
        if current.exists and not confirm_overwrite:
            action = "append to" if mode == "append" else "replace"
            raise RunConflictError(f"Confirmation was lost before attempting to {action} {destination}.")

    def _validate_generated_destination(
        self, destination: Path, expected: DestinationSnapshot
    ) -> None:
        current = self._snapshot(destination)
        if current != expected:
            raise RunConflictError(
                f"Split-output file changed after this run started: {destination}. "
                "Review it and run again."
            )
        if current.exists and not destination.is_file():
            raise RunError(f"Split-output destination is not a file: {destination}")

    @staticmethod
    def _reserve_temporary_file(destination: Path) -> Path:
        while True:
            temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
            try:
                with temporary.open("xb"):
                    pass
                return temporary
            except FileExistsError:
                continue

    def _copy_to_temporary(self, source: Path, destination: Path) -> Path:
        temporary = self._reserve_temporary_file(destination)
        try:
            shutil.copy2(source, temporary)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return temporary

    def _replace_staged_file(
        self, source: Path, destination: Path, expected: DestinationSnapshot
    ) -> None:
        temporary = self._copy_to_temporary(source, destination)
        try:
            if self._snapshot(destination) != expected:
                raise RunConflictError(
                    f"Output changed while it was being prepared: {destination}. Review it and run again."
                )
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _append_staged_file(
        self, source: Path, destination: Path, expected: DestinationSnapshot
    ) -> None:
        temporary = self._reserve_temporary_file(destination)
        try:
            with destination.open("rb") as existing, temporary.open("wb") as combined:
                shutil.copyfileobj(existing, combined, length=1024 * 1024)
                with source.open("rb") as staged:
                    shutil.copyfileobj(staged, combined, length=1024 * 1024)
                combined.flush()
                os.fsync(combined.fileno())
            if self._snapshot(destination) != expected:
                raise RunConflictError(
                    f"Output changed while it was being prepared: {destination}. Review it and run again."
                )
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _create_staged_file(self, source: Path, destination: Path) -> None:
        """Create a destination without ever replacing a newly appeared file."""

        temporary = self._copy_to_temporary(source, destination)
        try:
            try:
                # Both paths are in the destination directory, so a hard-link
                # creation is an atomic no-replace operation on NTFS.
                os.link(temporary, destination)
                return
            except FileExistsError as error:
                raise RunConflictError(
                    f"Output appeared while this run was executing: {destination}. "
                    "Review it and run again."
                ) from error
            except OSError:
                # Filesystems without hard links use an exclusive create.  It
                # cannot overwrite a file that appeared after the preflight.
                try:
                    with destination.open("xb") as created, temporary.open("rb") as staged:
                        shutil.copyfileobj(staged, created, length=1024 * 1024)
                        created.flush()
                        os.fsync(created.fileno())
                except FileExistsError as error:
                    raise RunConflictError(
                        f"Output appeared while this run was executing: {destination}. "
                        "Review it and run again."
                    ) from error
        finally:
            temporary.unlink(missing_ok=True)

    def _record_history(self, job: RunJob, duration_ms: int) -> None:
        if self._history_recorder is None:
            return
        diagnostics = job.stderr
        if job.error:
            diagnostics = f"{diagnostics}\n{job.error}".strip()
        try:
            self._history_recorder(
                command=[str(job.plan.binary), *job.plan.preview_argv],
                input_paths=[str(path) for path in job.plan.input_files],
                output_path=(str(job.plan.outputs[0].destination) if job.plan.outputs else None),
                status=job.status,
                exit_code=job.returncode,
                duration_ms=duration_ms,
                diagnostics=diagnostics,
            )
        except Exception:  # noqa: BLE001, S110 - history must not change a completed run result.
            # A run result must not become a failure merely because the optional
            # history record could not be stored.
            pass


__all__ = [
    "MAX_CAPTURE_BYTES",
    "RunConflictError",
    "RunError",
    "RunJob",
    "RunManager",
]
