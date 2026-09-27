"""Create a PE copy with non-runtime DWARF debug sections cleared.

This is deliberately narrow release tooling, not a general-purpose PE editor.
It leaves the executable's section layout and runtime code untouched while
removing raw data from sections whose resolved names begin with ``.debug``.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


class PEFormatError(ValueError):
    """The supplied file is not a PE executable with valid section metadata."""


def _require_range(data: bytes | bytearray, offset: int, size: int, label: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise PEFormatError(f"Invalid {label} range in PE file.")


def _coff_string_table(data: bytes | bytearray, pe_offset: int) -> bytes:
    pointer_to_symbols = struct.unpack_from("<I", data, pe_offset + 12)[0]
    number_of_symbols = struct.unpack_from("<I", data, pe_offset + 16)[0]
    if not pointer_to_symbols:
        return b""

    symbol_table_size = number_of_symbols * 18
    _require_range(data, pointer_to_symbols, symbol_table_size + 4, "COFF symbol table")
    string_table_offset = pointer_to_symbols + symbol_table_size
    string_table_size = struct.unpack_from("<I", data, string_table_offset)[0]
    if string_table_size < 4:
        raise PEFormatError("Invalid COFF string table size.")
    _require_range(data, string_table_offset, string_table_size, "COFF string table")
    return bytes(data[string_table_offset : string_table_offset + string_table_size])


def _section_name(raw_name: bytes, string_table: bytes) -> str:
    raw_name = raw_name.split(b"\0", 1)[0]
    if not raw_name.startswith(b"/"):
        return raw_name.decode("ascii", errors="strict")

    try:
        string_offset = int(raw_name[1:].decode("ascii"))
    except ValueError as error:
        raise PEFormatError("Invalid long PE section name.") from error

    if string_offset < 4 or string_offset >= len(string_table):
        raise PEFormatError("Long PE section name is outside the COFF string table.")
    end = string_table.find(b"\0", string_offset)
    if end < 0:
        raise PEFormatError("Long PE section name is not NUL-terminated.")
    return string_table[string_offset:end].decode("ascii", errors="strict")


def debug_section_spans(data: bytes | bytearray) -> list[tuple[str, int, int]]:
    """Return ``(name, raw_offset, raw_size)`` for all PE ``.debug*`` sections."""

    _require_range(data, 0, 0x40, "DOS header")
    if bytes(data[:2]) != b"MZ":
        raise PEFormatError("Not a DOS/PE executable.")

    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    _require_range(data, pe_offset, 24, "PE header")
    if bytes(data[pe_offset : pe_offset + 4]) != b"PE\0\0":
        raise PEFormatError("PE signature is missing.")

    section_count = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_header_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    section_table_offset = pe_offset + 24 + optional_header_size
    _require_range(data, section_table_offset, section_count * 40, "PE section table")
    string_table = _coff_string_table(data, pe_offset)

    spans: list[tuple[str, int, int]] = []
    for index in range(section_count):
        section_offset = section_table_offset + index * 40
        name = _section_name(bytes(data[section_offset : section_offset + 8]), string_table)
        raw_size = struct.unpack_from("<I", data, section_offset + 16)[0]
        raw_offset = struct.unpack_from("<I", data, section_offset + 20)[0]
        if not name.startswith(".debug") or raw_size == 0:
            continue
        _require_range(data, raw_offset, raw_size, f"{name} section")
        spans.append((name, raw_offset, raw_size))
    return spans


def _checksum_offset(data: bytes | bytearray) -> int:
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    optional_header_offset = pe_offset + 24
    _require_range(data, optional_header_offset, 68, "PE optional header")
    return optional_header_offset + 64


def _pe_checksum(data: bytes | bytearray, checksum_offset: int) -> int:
    """Calculate the standard PE checksum after excluding its checksum field."""

    checksum = 0
    for offset in range(0, len(data), 2):
        if checksum_offset <= offset < checksum_offset + 4:
            word = 0
        else:
            low = data[offset]
            high = data[offset + 1] if offset + 1 < len(data) else 0
            word = low | (high << 8)
        checksum = (checksum & 0xFFFF) + (checksum >> 16) + word
        checksum = (checksum & 0xFFFF) + (checksum >> 16)
    checksum = (checksum & 0xFFFF) + (checksum >> 16)
    return (checksum + len(data)) & 0xFFFFFFFF


def strip_debug_sections(source: Path, destination: Path) -> tuple[str, ...]:
    """Write a sanitized PE copy and return the debug sections that were cleared."""

    if source.resolve() == destination.resolve():
        raise ValueError("Source and destination must be different files.")

    data = bytearray(source.read_bytes())
    spans = debug_section_spans(data)
    if not spans:
        raise PEFormatError("No PE debug sections were found to clear.")

    for _name, raw_offset, raw_size in spans:
        data[raw_offset : raw_offset + raw_size] = b"\0" * raw_size

    checksum_offset = _checksum_offset(data)
    struct.pack_into("<I", data, checksum_offset, 0)
    struct.pack_into("<I", data, checksum_offset, _pe_checksum(data, checksum_offset))
    destination.write_bytes(data)
    return tuple(name for name, _offset, _size in spans)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write a copy of a PE executable with .debug* section data cleared."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()

    try:
        sections = strip_debug_sections(args.source, args.destination)
    except (OSError, PEFormatError, ValueError) as error:
        parser.error(str(error))

    print(f"Cleared PE debug sections: {', '.join(sections)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
