"""Windows long-path helpers.

Deep library folders can push a full path past MAX_PATH (260 chars).  Python
itself is manifest-aware, but a folder nested a few levels deeper still makes
``os.scandir`` / ``os.stat`` / ``open`` fail with OSError depending on the
interpreter (notably a frozen PyInstaller build whose manifest may not declare
``longPathAware``).  When that happens a whole directory listing used to be
dropped, which looked like "deeper folders show up empty".

The helpers below transparently retry with the ``\\\\?\\`` extended-length
prefix, so a single unreadable entry can no longer blank out its parent.
"""

import os
from typing import List, Optional

_EXT = "\\\\?\\"


def is_extended(path: str) -> bool:
    return path.startswith("\\\\?\\") or path.startswith("//?/")


def to_extended(path: str) -> str:
    """Return the ``\\\\?\\``-prefixed form of *path* (Windows only)."""
    if os.name != "nt" or is_extended(path):
        return path
    try:
        abs_path = os.path.abspath(path)
    except (OSError, ValueError):
        return path
    if abs_path.startswith("\\\\"):
        # UNC share -> \\?\UNC\server\share
        return "\\\\?\\UNC" + abs_path[1:]
    return _EXT + abs_path


def strip_extended(path: str) -> str:
    """Undo :func:`to_extended` so the path can be returned to clients."""
    if not is_extended(path):
        return path
    if path.startswith("\\\\?\\UNC"):
        return "\\" + path[len("\\\\?\\UNC"):]
    if path.startswith("\\\\?\\"):
        return path[len("\\\\?\\"):]
    return path[len("//?/"):]


def scandir(path: str) -> List[os.DirEntry]:
    """``os.scandir`` that survives long paths; never raises for OSError."""
    try:
        with os.scandir(path) as it:
            return list(it)
    except OSError:
        if os.name == "nt":
            try:
                with os.scandir(to_extended(path)) as it:
                    return list(it)
            except OSError:
                pass
        return []


def entry_stat(entry: os.DirEntry):
    """``stat`` for a single DirEntry, tolerant of long paths."""
    try:
        return entry.stat()
    except OSError:
        if os.name == "nt":
            try:
                return os.stat(to_extended(entry.path))
            except OSError:
                pass
        return None


def entry_path(entry: os.DirEntry) -> str:
    """Child path without the extended-length prefix."""
    return strip_extended(entry.path)


def stat(path: str):
    """``os.stat`` that retries with the extended prefix; ``None`` on failure."""
    try:
        return os.stat(path)
    except OSError:
        if os.name == "nt":
            try:
                return os.stat(to_extended(path))
            except OSError:
                pass
        return None


def open_binary(path: str):
    """``open(path, 'rb')`` tolerant of long paths. Returns ``None`` on failure."""
    try:
        return open(path, "rb")
    except OSError:
        if os.name == "nt":
            try:
                return open(to_extended(path), "rb")
            except OSError:
                pass
        return None


def is_dir(path: str) -> bool:
    st = stat(path)
    return bool(st and os.path.isdir(path)) if st else False
