from collections.abc import Iterator
from pathlib import Path


class RangeError(ValueError):
    pass


def parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    if not range_header.startswith("bytes="):
        raise RangeError("Only bytes range is supported")

    range_value = range_header.split("=", 1)[1].strip()
    if "," in range_value:
        raise RangeError("Multiple ranges are not supported")

    start_str, sep, end_str = range_value.partition("-")
    if sep != "-":
        raise RangeError("Invalid range format")

    if start_str == "" and end_str == "":
        raise RangeError("Invalid range bounds")

    if start_str == "":
        # Suffix range: bytes=-500 -> last 500 bytes
        try:
            suffix = int(end_str)
        except ValueError as exc:
            raise RangeError("Invalid range number") from exc
        if suffix <= 0:
            raise RangeError("Invalid suffix length")
        start = max(file_size - suffix, 0)
        end = file_size - 1
        return start, end

    try:
        start = int(start_str)
    except ValueError as exc:
        raise RangeError("Invalid range start") from exc

    if start < 0 or start >= file_size:
        raise RangeError("Range start out of bounds")

    if end_str == "":
        end = file_size - 1
    else:
        try:
            end = int(end_str)
        except ValueError as exc:
            raise RangeError("Invalid range end") from exc
        if end < start:
            raise RangeError("Range end before start")
        if end >= file_size:
            end = file_size - 1

    return start, end


def iter_file_chunks(path: Path, start: int, end: int, chunk_size: int) -> Iterator[bytes]:
    remaining = end - start + 1
    with path.open("rb") as file:
        file.seek(start)
        while remaining > 0:
            read_size = min(chunk_size, remaining)
            data = file.read(read_size)
            if not data:
                break
            remaining -= len(data)
            yield data

