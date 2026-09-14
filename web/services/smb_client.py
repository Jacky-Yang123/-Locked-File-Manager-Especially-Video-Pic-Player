import os
import hashlib
import time
from typing import List, Dict, Optional
import smbclient
import smbprotocol.exceptions

from .storage_client import StorageClient


def parse_smb_url(url: str):
    """Parse smb:// or \\\\server\\share format."""
    if url.startswith('smb://'):
        url = url[6:]
        url = url.replace('/', '\\')
        if not url.startswith('\\'):
            url = '\\\\' + url
            
    url = url.replace('/', '\\')
    if url.startswith(r'\\'):
        parts = url[2:].split('\\', 1)
        server = parts[0]
        path = '\\' + parts[1] if len(parts) > 1 else '\\'
        # ensure path doesn't end with \
        if path != '\\' and path.endswith('\\'):
            path = path[:-1]
        return server, path
    return None, None


class SMBFileStream:
    """A file-like object that reads data via SMB."""

    def __init__(self, client: 'SMBClient', remote_path: str):
        self.client = client
        self.remote_path = remote_path
        
        full_path = self.client._build_path(remote_path)
        # Register session if needed
        self.client._ensure_session()
        
        # share_access='r' allows other processes (e.g. preview session) to open the same file concurrently
        self.file = smbclient.open_file(full_path, mode='rb', share_access='r')
        self._size = smbclient.stat(full_path).st_size

    def seek(self, offset: int, whence: int = 0):
        self.file.seek(offset, whence)
        return self.file.tell()

    def tell(self) -> int:
        return self.file.tell()

    def read(self, size: int = -1) -> bytes:
        return self.file.read(size)

    def close(self):
        try:
            self.file.close()
        except:
            pass


class SMBClient(StorageClient):
    """SMB client for NAS file access using smbprotocol."""

    def __init__(self, base_url: str, username: str = '', password: str = ''):
        self.server, self.base_share_path = parse_smb_url(base_url)
        if not self.server:
            raise ValueError(f"Invalid SMB URL format: {base_url}")
            
        self.username = username
        self.password = password
        self._session_registered = False

    def _ensure_session(self):
        if not self._session_registered:
            try:
                smbclient.register_session(self.server, username=self.username, password=self.password)
                self._session_registered = True
            except Exception as e:
                raise ConnectionError(f"SMB 认证失败: {e}")

    def _build_path(self, relative_path: str) -> str:
        """Combine base share path with relative path."""
        rel = relative_path.replace('/', '\\')
        if rel.startswith('\\'):
            rel = rel[1:]
            
        if not self.base_share_path.endswith('\\'):
            full = f"\\\\{self.server}{self.base_share_path}\\{rel}"
        else:
            full = f"\\\\{self.server}{self.base_share_path}{rel}"
            
        if full.endswith('\\'):
            full = full[:-1]
        return full

    def _format_entry(self, entry, rel_path: str) -> Dict:
        """Convert smbclient DirEntry to WebDAV-like dict format."""
        stat = entry.stat()
        is_dir = entry.is_dir()
        
        # Build standard posix-like path for frontend
        path_str = rel_path.replace('\\', '/')
        if not path_str.startswith('/'):
            path_str = '/' + path_str
            
        size = stat.st_size if not is_dir else 0
        ext = os.path.splitext(entry.name)[1].lower() if not is_dir else ''
        
        return {
            'name': entry.name,
            'path': path_str,
            'is_dir': is_dir,
            'size': size,
            'last_modified': stat.st_mtime,
            'ext': ext
        }

    def test_connection(self) -> bool:
        try:
            self._ensure_session()
            # Try to stat the root path
            root_path = self._build_path('/')
            smbclient.stat(root_path)
            return True
        except Exception as e:
            print(f"SMB Test connection failed: {e}")
            return False

    def list_dir(self, path: str = '/') -> List[Dict]:
        self._ensure_session()
        full_path = self._build_path(path)
        
        results = []
        for attempt in range(3):
            try:
                for entry in smbclient.scandir(full_path):
                    if entry.name.startswith('$') or entry.name == 'System Volume Information':
                        continue
                    rel_path = os.path.join(path, entry.name)
                    results.append(self._format_entry(entry, rel_path))
                return results
            except (smbprotocol.exceptions.SMBOSError, Exception) as e:
                msg = str(e)
                if 'credits' in msg.lower() and attempt < 2:
                    time.sleep(2)  # wait for NAS to release credits
                    continue
                raise Exception(f"SMB 读取目录失败: {e}")
            
        return results

    def list_dir_recursive(self, path: str = '/') -> List[Dict]:
        """Recursively list all files in all subdirectories."""
        self._ensure_session()
        
        results = []
        queue = [path]
        
        err_count = 0
        scan_count = 0
        while queue:
            scan_count += 1
            if scan_count % 50 == 0:
                time.sleep(1)  # let NAS replenish SMB credits
            
            current_path = queue.pop(0)
            for attempt in range(3):
                try:
                    full_path = self._build_path(current_path)
                    for entry in smbclient.scandir(full_path):
                        if entry.name.startswith('$') or entry.name == 'System Volume Information':
                            continue
                            
                        rel_path = os.path.join(current_path, entry.name).replace('\\', '/')
                        formatted = self._format_entry(entry, rel_path)
                        
                        if formatted['is_dir']:
                            queue.append(rel_path)
                        else:
                            results.append(formatted)
                    break  # success
                except Exception as e:
                    msg = str(e)
                    if 'credits' in msg.lower() and attempt < 2:
                        time.sleep(2)
                        continue
                    err_count += 1
                    print(f"Failed to scan {current_path}: {e}")
                    break

        if err_count > 0:
            raise Exception(f"Recursive scan incomplete: {err_count} directories failed out of {len(results) + err_count} total. Consider reducing SMB load or increasing NAS max credits.")
                
        return results

    def get_evf_original_ext(self, path: str) -> str:
        """Fetch the original extension from the first 70 bytes of an EVF file."""
        self._ensure_session()
        full_path = self._build_path(path)
        
        try:
            with smbclient.open_file(full_path, mode='rb', share_access='r') as f:
                header_data = f.read(70)
                if len(header_data) >= 66:
                    ext_bytes = header_data[50:66]
                    return ext_bytes.decode('utf-8', errors='ignore').strip('\x00').lower()
        except Exception as e:
            print(f"Error extracting ext for {path}: {e}")
            
        return ""

    def get_file_stream(self, path: str, start: int = 0, end: int = -1):
        """Not directly used by app.py for SMB, as we provide get_file_object instead."""
        pass

    def get_file_object(self, path: str):
        """Return a file-like object supporting seek and read."""
        return SMBFileStream(self, path)
