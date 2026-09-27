from __future__ import annotations

from launcher import DesktopBridge


class _FakeWebview:
    OPEN_DIALOG = "open"
    SAVE_DIALOG = "save"
    FOLDER_DIALOG = "folder"


class _FakeWindow:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.results = [
            ("C:/Games/one.pgn", "C:/Games/two.pgn"),
            "C:/Games/output.pgn",
            "C:/Games/split-output",
        ]

    def create_file_dialog(self, dialog_type: str, **kwargs: object) -> object:
        self.calls.append((dialog_type, kwargs))
        return self.results.pop(0)


def test_desktop_bridge_uses_supported_file_dialog_keywords() -> None:
    bridge = DesktopBridge(_FakeWebview)
    window = _FakeWindow()
    bridge.attach_window(window)

    assert bridge.pickFiles({"multiple": False, "extensions": ["pgn"]}) == [
        "C:/Games/one.pgn",
        "C:/Games/two.pgn",
    ]
    assert bridge.pickSaveFile({"suggestedName": "merged.pgn", "extensions": ["pgn"]}) == [
        "C:/Games/output.pgn"
    ]
    assert bridge.pickDirectory({"title": "Ignored by the native API"}) == ["C:/Games/split-output"]

    assert window.calls == [
        (
            "open",
            {
                "allow_multiple": False,
                "file_types": ("Supported files (*.pgn)", "All files (*.*)"),
            },
        ),
        (
            "save",
            {
                "save_filename": "merged.pgn",
                "file_types": ("Supported files (*.pgn)", "All files (*.*)"),
            },
        ),
        ("folder", {}),
    ]
