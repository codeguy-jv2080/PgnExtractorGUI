from app.pgn_binary import parse_version, version_is_compatible


def test_parses_and_compares_pgn_extract_versions() -> None:
    assert parse_version("pgn-extract v26-06") == (26, 6)
    assert parse_version("pgn-extract 26-10") == (26, 10)
    assert parse_version("not pgn-extract") is None
    assert version_is_compatible("pgn-extract v26-06")
    assert not version_is_compatible("pgn-extract v26-04")
