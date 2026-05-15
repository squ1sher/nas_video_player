import pytest

from app.streaming import RangeError, parse_range_header


def test_parse_range_standard() -> None:
    start, end = parse_range_header("bytes=0-99", 1000)
    assert (start, end) == (0, 99)


def test_parse_range_open_ended() -> None:
    start, end = parse_range_header("bytes=100-", 1000)
    assert (start, end) == (100, 999)


def test_parse_range_suffix() -> None:
    start, end = parse_range_header("bytes=-200", 1000)
    assert (start, end) == (800, 999)


def test_parse_range_rejects_multiple() -> None:
    with pytest.raises(RangeError):
        parse_range_header("bytes=0-10,20-30", 1000)


def test_parse_range_invalid_bounds() -> None:
    with pytest.raises(RangeError):
        parse_range_header("bytes=300-200", 1000)

