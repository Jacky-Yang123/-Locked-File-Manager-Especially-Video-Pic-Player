"""HTTP Range header parsing shared by every streaming endpoint.

A single implementation prevents the regression we hit before: several
handlers parsed ``Range`` by splitting on ``-`` and treating a missing
start byte as ``0``.  That silently turned a *suffix* request
(``bytes=-1024`` = "the LAST 1024 bytes") into a *prefix* request
(``bytes=0-1024``), so players probing for a trailing MP4 ``moov`` atom
received the head of the file instead and refused to open the video.
"""

from typing import Optional, Tuple


def parse_range_header(range_header: Optional[str], total_size: int) -> Optional[Tuple[int, int]]:
    """Parse a single-range ``Range`` header into inclusive ``(start, end)``.

    Supports all three RFC 7233 forms::

        bytes=0-1023     explicit window
        bytes=1024-      open ended (to the end of the file)
        bytes=-1024      suffix: the LAST 1024 bytes

    Returns ``None`` when *total_size* is not positive, the header is empty
    or malformed, or the range lies completely outside the file (callers
    should answer 416).  A malformed header is treated as "no range" by
    returning ``(0, total_size - 1)`` so clients still get the full body.
    """
    if total_size <= 0:
        return None

    if not range_header:
        return (0, total_size - 1)

    spec = range_header.strip()
    if "=" in spec:
        _, _, spec = spec.partition("=")
    spec = spec.strip()

    # Only the first range of a multi-range request is honoured.
    if "," in spec:
        spec = spec.split(",", 1)[0].strip()

    if "-" not in spec:
        return (0, total_size - 1)

    start_str, _, end_str = spec.partition("-")
    start_str = start_str.strip()
    end_str = end_str.strip()

    try:
        if not start_str:
            # Suffix form: the last N bytes.
            if not end_str:
                return (0, total_size - 1)
            suffix_len = int(end_str)
            if suffix_len <= 0:
                return None
            if suffix_len >= total_size:
                return (0, total_size - 1)
            return (total_size - suffix_len, total_size - 1)

        start = int(start_str)
        if start < 0 or start >= total_size:
            return None

        if not end_str:
            # Open ended: start -> EOF.
            return (start, total_size - 1)

        end = int(end_str)
        if end < start:
            return None
        if end >= total_size:
            end = total_size - 1
        return (start, end)
    except (TypeError, ValueError):
        return (0, total_size - 1)
