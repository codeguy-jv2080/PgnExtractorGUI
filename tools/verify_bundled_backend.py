"""Verify release hygiene for the bundled pgn-extract executable."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

PRIVATE_PATH_MARKERS = (b":\\users\\", b":/users/", b"appdata")
SHA256_PATTERN = re.compile(r"^\s*SHA-256:\s*([0-9A-Fa-f]{64})\s*$", re.MULTILINE)


def expected_sha256(version_record: Path) -> str:
    match = SHA256_PATTERN.search(version_record.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"No SHA-256 value found in {version_record}.")
    return match.group(1).upper()


def verify(binary: Path, version_record: Path) -> list[str]:
    payload = binary.read_bytes()
    actual_sha256 = hashlib.sha256(payload).hexdigest().upper()
    errors: list[str] = []
    if actual_sha256 != expected_sha256(version_record):
        errors.append("Bundled backend hash does not match VERSION.txt.")

    lowered = payload.lower()
    if any(marker in lowered for marker in PRIVATE_PATH_MARKERS):
        errors.append("Bundled backend contains a local Windows path marker.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify bundled pgn-extract release hygiene.")
    parser.add_argument("binary", type=Path)
    parser.add_argument("version_record", type=Path)
    args = parser.parse_args()

    try:
        errors = verify(args.binary, args.version_record)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("Bundled pgn-extract passed release hygiene checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
