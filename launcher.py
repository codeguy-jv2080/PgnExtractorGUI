"""Windows desktop launcher for the local FastAPI/pywebview application."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Any


def _find_open_loopback_port() -> int:
    """Reserve an ephemeral loopback port long enough to configure Uvicorn."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class DesktopBridge:
    """Small local-only bridge used by the HTML UI for native file dialogs."""

    def __init__(self, webview_module: Any) -> None:
        self._webview = webview_module
        self._window: Any | None = None

    def attach_window(self, window: Any) -> None:
        self._window = window

    def pickFiles(self, options: dict[str, Any] | None = None) -> list[str]:
        options = options or {}
        result = self._dialog(
            self._webview.OPEN_DIALOG,
            allow_multiple=bool(options.get("multiple", True)),
            file_types=self._file_types(options),
        )
        return self._paths(result)

    def pickSaveFile(self, options: dict[str, Any] | None = None) -> list[str]:
        options = options or {}
        result = self._dialog(
            self._webview.SAVE_DIALOG,
            save_filename=str(options.get("suggestedName") or "extracted.pgn"),
            file_types=self._file_types(options),
        )
        return self._paths(result)

    def pickDirectory(self, options: dict[str, Any] | None = None) -> list[str]:
        result = self._dialog(self._webview.FOLDER_DIALOG)
        return self._paths(result)

    def _dialog(self, dialog_type: Any, **kwargs: Any) -> Any:
        if self._window is None:
            raise RuntimeError("The desktop window has not finished loading.")
        return self._window.create_file_dialog(dialog_type, **kwargs)

    @staticmethod
    def _file_types(options: dict[str, Any]) -> tuple[str, ...]:
        extensions = options.get("extensions")
        if not isinstance(extensions, list):
            return ("PGN files (*.pgn)", "All files (*.*)")
        patterns = [f"*.{str(extension).lstrip('.')}" for extension in extensions if extension]
        if not patterns:
            return ("All files (*.*)",)
        return (f"Supported files ({';'.join(patterns)})", "All files (*.*)")

    @staticmethod
    def _paths(value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, (str, Path)):
            return [str(value)]
        return [str(path) for path in value]


def main() -> int:
    """Run the app in a native window with an in-process loopback backend."""

    try:
        import uvicorn
        import webview
    except ImportError as error:
        missing = getattr(error, "name", "a required package")
        raise SystemExit(
            f"PgnExtractorGUI is not installed completely (missing {missing}). "
            "Run run-dev.bat or install the project dependencies first."
        ) from error

    from app.main import create_app
    from app.pgn_binary import PgnExtractBinaryError, require_compatible_binary

    port = _find_open_loopback_port()
    app = create_app()
    try:
        require_compatible_binary(app.state.services.refresh_binary_info())
    except PgnExtractBinaryError as error:
        raise SystemExit(f"PgnExtractorGUI cannot start: {error}") from error
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, name="PgnExtractorGUI-API", daemon=True)
    server_thread.start()

    deadline = time.monotonic() + 10
    while not server.started and server_thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        server_thread.join(timeout=2)
        raise SystemExit("The local PGN Extract GUI server did not start.")

    bridge = DesktopBridge(webview)
    window = webview.create_window(
        "PGN Extract GUI",
        f"http://127.0.0.1:{port}/",
        js_api=bridge,
        width=1360,
        height=900,
        min_size=(960, 640),
    )
    bridge.attach_window(window)

    try:
        webview.start()
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
