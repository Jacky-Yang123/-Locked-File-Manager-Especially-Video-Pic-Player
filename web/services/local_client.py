"""
Local filesystem storage client — lets the web app serve encrypted videos
directly from a local folder (e.g. the PC's own encrypted library) without
needing a NAS / WebDAV / SMB.

Virtual path mapping: the configured local root maps to '/' on the web side.
    local root  <root>          ->  virtual '/'
    <root>/J/a.evf              ->  virtual '/J/a.evf'
"""
import os
import time
from pathlib import PurePosixPath
from typing import List, Dict, Optional

from .storage_client import StorageClient


class LocalClient(StorageClient):
    """Reads encrypted files from a local directory."""

    def __init__(self, root_path: str, username: str = '', password: str = ''):
        # Normalize: strip trailing separators; accept both / and \ paths
        self.root = os.path.normpath(os.path.abspath(root_path.strip(' /\\')))

    def _to_local(self, virtual_path: str) -> str:
        """Map a virtual path ('/J/a.evf') to a real local path."""
        rel = virtual_path.strip('/').replace('/', os.sep)
        if not rel:
            return self.root
        local = os.path.normpath(os.path.join(self.root, rel))
        # Path traversal guard: must stay inside root
        if not (local == self.root or local.startswith(self.root + os.sep)):
            raise ValueError(f"Path outside local root: {virtual_path}")
        return local

    def _to_virtual(self, local_path: str) -> str:
        """Map a real local path back to a virtual path."""
        local = os.path.normpath(local_path)
        rel = os.path.relpath(local, self.root)
        if rel == '.':
            return '/'
        return '/' + rel.replace(os.sep, '/')

    def test_connection(self) -> bool:
        return os.path.isdir(self.root)

    def list_dir(self, path: str = '/') -> List[Dict]:
        local = self._to_local(path)
        items = []
        try:
            for name in os.listdir(local):
                if name.startswith('.') or name.startswith('@'):
                    continue
                full = os.path.join(local, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                is_dir = os.path.isdir(full)
                vpath = self._to_virtual(full)
                if is_dir and not vpath.endswith('/'):
                    vpath += '/'
                items.append({
                    'name': name,
                    'path': vpath,
                    'is_dir': is_dir,
                    'size': st.st_size,
                    'mtime': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(st.st_mtime)),
                    'ext': PurePosixPath(name).suffix.lower() if not is_dir else ''
                })
        except FileNotFoundError:
            raise Exception(f"本地目录不存在: {local}")
        items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        return items

    def list_dir_recursive(self, path: str = '/') -> List[Dict]:
        """Recursively list all files using os.walk."""
        local = self._to_local(path)
        results = []
        for dirpath, dirnames, filenames in os.walk(local):
            # Skip hidden dirs
            dirnames[:] = [d for d in dirnames if not d.startswith('.') and not d.startswith('@')]
            for fname in filenames:
                if fname.startswith('.'):
                    continue
                full = os.path.join(dirpath, fname)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                results.append({
                    'name': fname,
                    'path': self._to_virtual(full),
                    'is_dir': False,
                    'size': st.st_size,
                    'mtime': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(st.st_mtime)),
                    'ext': PurePosixPath(fname).suffix.lower()
                })
        return results

    def get_evf_original_ext(self, path: str) -> str:
        local = self._to_local(path)
        try:
            with open(local, 'rb') as f:
                data = f.read(70)
                if len(data) >= 70:
                    return data[50:66].decode('utf-8', errors='ignore').strip('\x00').lower()
        except Exception:
            pass
        return ""

    def get_file_stream(self, path: str, start: int = 0, end: int = -1):
        """Return a minimal file-like wrapper honoring seek/read (range slicing)."""
        return LocalFileStream(self._to_local(path))

    def get_file_object(self, path: str):
        """Open the local file as a plain binary file object (seekable)."""
        return open(self._to_local(path), 'rb')


class LocalFileStream:
    """File-like wrapper around a local file with seek/read/tell/close."""

    def __init__(self, local_path: str):
        self._f = open(local_path, 'rb')
        self._size = os.fstat(self._f.fileno()).st_size

    def seek(self, offset: int, whence: int = 0):
        return self._f.seek(offset, whence)

    def tell(self) -> int:
        return self._f.tell()

    def read(self, size: int = -1) -> bytes:
        return self._f.read(size)

    def close(self):
        try:
            self._f.close()
        except Exception:
            pass
