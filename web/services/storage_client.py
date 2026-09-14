import abc
import os
import hashlib
from pathlib import PurePosixPath
from typing import List, Dict, Optional

from config import CACHE_DIR

class StorageClient(abc.ABC):
    """Abstract base class for storage clients (WebDAV, SMB, etc.)."""
    
    @abc.abstractmethod
    def test_connection(self) -> bool:
        pass

    @abc.abstractmethod
    def list_dir(self, path: str = '/') -> List[Dict]:
        pass

    @abc.abstractmethod
    def list_dir_recursive(self, path: str = '/') -> List[Dict]:
        pass

    @abc.abstractmethod
    def get_evf_original_ext(self, path: str) -> str:
        pass

    @abc.abstractmethod
    def get_file_stream(self, path: str, start: int = 0, end: int = -1):
        pass

    @abc.abstractmethod
    def get_file_object(self, path: str):
        pass

    def get_cached_path(self, remote_path: str) -> str:
        """Get local cache path for a remote file."""
        path_hash = hashlib.md5(remote_path.encode('utf-8')).hexdigest()
        ext = PurePosixPath(remote_path).suffix
        return os.path.join(CACHE_DIR, f"{path_hash}{ext}")


def get_storage_client(url: str, username: str = '', password: str = '',
                       storage_type: str = '', local_path: str = '') -> StorageClient:
    """Factory function to get the appropriate storage client.
    storage_type='local' uses the local filesystem client (local_path is the folder).
    Otherwise picks WebDAV/SMB from the URL scheme."""
    if storage_type == 'local':
        from .local_client import LocalClient
        return LocalClient(local_path or url, username, password)

    url = url.strip()
    if url.startswith(r'\\') or url.startswith('smb://'):
        from .smb_client import SMBClient
        return SMBClient(url, username, password)
    else:
        from .webdav_client import WebDAVClient
        # Auto-prefix with http:// if missing
        if not url.startswith('http://') and not url.startswith('https://'):
            url = 'http://' + url
        return WebDAVClient(url, username, password)
