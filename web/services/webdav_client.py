"""
WebDAV client service for browsing and fetching files from NAS.
Uses pure requests library with PROPFIND for directory listing.
"""
import os
import re
import hashlib
import requests
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath
from typing import List, Dict, Optional
import urllib.parse
from urllib.parse import unquote, urljoin, urlparse

from config import CACHE_DIR
from .storage_client import StorageClient


class WebDAVFileStream:
    """A file-like object that reads data on-demand via WebDAV HTTP Range requests."""

    def __init__(self, client: 'WebDAVClient', remote_path: str):
        self.client = client
        self.remote_path = remote_path
        self._pos = 0

        url = client._build_url(remote_path)
        resp = client.session.head(url, timeout=10)
        resp.raise_for_status()
        self._size = int(resp.headers.get('content-length', 0))

    def seek(self, offset: int, whence: int = 0):
        if whence == 0:
            self._pos = offset
        elif whence == 1:
            self._pos += offset
        elif whence == 2:
            self._pos = self._size + offset
        return self._pos

    def tell(self) -> int:
        return self._pos

    def read(self, size: int = -1) -> bytes:
        if size == -1 or size is None:
            size = self._size - self._pos
        if size <= 0 or self._pos >= self._size:
            return b''

        range_end = min(self._size - 1, self._pos + size - 1)
        resp = self.client.get_file_stream(self.remote_path, self._pos, range_end)
        data = resp.content
        self._pos += len(data)
        return data

    def close(self):
        pass


class WebDAVClient(StorageClient):
    """WebDAV client for NAS file access."""

    def __init__(self, base_url: str, username: str = '', password: str = ''):
        self.base_url = base_url.rstrip('/')
        self.auth = (username, password) if username else None
        self.session = requests.Session()
        if self.auth:
            self.session.auth = self.auth
        self.timeout = 30

    def list_dir(self, path: str = '/') -> List[Dict]:
        """List files and directories at the given path using PROPFIND."""
        url = self._build_url(path)

        headers = {'Depth': '1', 'Content-Type': 'application/xml'}
        body = '''<?xml version="1.0" encoding="utf-8"?>
        <D:propfind xmlns:D="DAV:">
            <D:prop>
                <D:displayname/>
                <D:getcontentlength/>
                <D:getlastmodified/>
                <D:resourcetype/>
                <D:getcontenttype/>
            </D:prop>
        </D:propfind>'''

        try:
            resp = self.session.request(
                'PROPFIND', url, headers=headers, data=body, timeout=self.timeout
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            raise ConnectionError(f"WebDAV 连接失败: {e}")

        return self._parse_propfind(resp.text, path)

    def list_dir_recursive(self, path: str = '/') -> List[Dict]:
        """Recursively list all files in all subdirectories using Depth: infinity with BFS fallback."""
        url = self._build_url(path)
        headers = {'Depth': 'infinity', 'Content-Type': 'application/xml'}
        body = '''<?xml version="1.0" encoding="utf-8"?>
        <D:propfind xmlns:D="DAV:">
            <D:prop>
                <D:displayname/>
                <D:getcontentlength/>
                <D:getlastmodified/>
                <D:resourcetype/>
            </D:prop>
        </D:propfind>'''

        try:
            resp = self.session.request('PROPFIND', url, headers=headers, data=body, timeout=self.timeout)
            if resp.status_code in (200, 207):
                files = self._parse_propfind(resp.text, path)
                # Return only files (exclude directories)
                return [f for f in files if not f['is_dir']]
        except Exception as e:
            print(f"Depth: infinity failed, using BFS fallback: {e}")

        # BFS Fallback
        all_files = []
        queue = [path]
        visited = set()

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            folder_name = PurePosixPath(current.rstrip('/')).name
            if folder_name.startswith('.') or folder_name.startswith('@'):
                continue

            try:
                items = self.list_dir(current)
                for item in items:
                    if item['is_dir']:
                        queue.append(item['path'])
                    else:
                        all_files.append(item)
            except Exception as e:
                print(f"Recursive list warning on {current}: {e}")

        return all_files

    def _parse_propfind(self, xml_text: str, base_path: str) -> List[Dict]:
        """Parse PROPFIND XML response into file list."""
        items = []
        ns = {'D': 'DAV:'}

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return items

        base_clean = base_path.rstrip('/')
        base_url_path = urllib.parse.urlparse(self.base_url).path.rstrip('/')
        target_path = (base_url_path + base_clean).rstrip('/')

        for response in root.findall('.//D:response', ns):
            href_elem = response.find('D:href', ns)
            if href_elem is None:
                continue

            href_raw = unquote(href_elem.text or '').rstrip('/')
            href_path = urlparse(href_raw).path.rstrip('/')
            name = PurePosixPath(href_path).name
            if not name:
                continue

            # Skip hidden system folders/files (.stfolder, @eaDir, etc.)
            if name.startswith('.') or name.startswith('@'):
                continue

            propstat = response.find('D:propstat', ns)
            if propstat is None:
                continue

            prop = propstat.find('D:prop', ns)
            if prop is None:
                continue

            resourcetype = prop.find('D:resourcetype', ns)
            is_dir = False
            if resourcetype is not None:
                is_dir = resourcetype.find('D:collection', ns) is not None

            # Skip the target container directory itself
            if href_path == target_path:
                continue

            # Ensure the item is actually inside target_path
            if target_path and not href_path.startswith(target_path + '/'):
                continue

            size_elem = prop.find('D:getcontentlength', ns)
            size = int(size_elem.text) if size_elem is not None and size_elem.text else 0

            mtime_elem = prop.find('D:getlastmodified', ns)
            mtime = mtime_elem.text if mtime_elem is not None else ''

            if href_path.startswith(base_url_path):
                rel_path = href_path[len(base_url_path):]
            else:
                rel_path = (base_clean + '/' + name) if base_clean else ('/' + name)

            if is_dir and not rel_path.endswith('/'):
                rel_path += '/'

            items.append({
                'name': name,
                'path': rel_path,
                'is_dir': is_dir,
                'size': size,
                'mtime': mtime,
                'ext': PurePosixPath(name).suffix.lower() if not is_dir else ''
            })

        items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        return items

    def download_file(self, path: str, local_path: str,
                      progress_callback=None) -> str:
        """Download a file from WebDAV to local cache."""
        url = self._build_url(path)

        try:
            resp = self.session.get(url, stream=True, timeout=self.timeout)
            resp.raise_for_status()

            total = int(resp.headers.get('content-length', 0))
            downloaded = 0

            with open(local_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total > 0:
                            progress_callback(downloaded, total)

            return local_path

        except requests.RequestException as e:
            if os.path.exists(local_path):
                os.unlink(local_path)
            raise ConnectionError(f"下载失败: {e}")

    def get_file_stream(self, path: str, range_start: int = None,
                        range_end: int = None):
        """Get a streaming response for a file, supporting Range requests."""
        url = self._build_url(path)
        headers = {}
        if range_start is not None:
            range_str = f'bytes={range_start}-'
            if range_end is not None:
                range_str = f'bytes={range_start}-{range_end}'
            headers['Range'] = range_str

        resp = self.session.get(url, headers=headers, stream=True, timeout=self.timeout)
        resp.raise_for_status()
        return resp

    def get_file_object(self, path: str) -> WebDAVFileStream:
        """Get an on-demand file-like object for direct streaming decryption."""
        return WebDAVFileStream(self, path)

    def ensure_cached(self, remote_path: str, progress_callback=None) -> str:
        """Ensure a file is cached locally. Returns local path."""
        local_path = self.get_cached_path(remote_path)

        if os.path.exists(local_path):
            try:
                resp = self.session.head(self._build_url(remote_path), timeout=10)
                remote_size = int(resp.headers.get('content-length', 0))
                local_size = os.path.getsize(local_path)
                if remote_size > 0 and remote_size == local_size:
                    return local_path
            except Exception:
                return local_path

        return self.download_file(remote_path, local_path, progress_callback)

    def _build_url(self, path: str) -> str:
        """Build full URL from relative path."""
        if path.startswith('http'):
            return path
        path = path.lstrip('/')
        return f"{self.base_url}/{path}"

    def test_connection(self) -> bool:
        """Test if the WebDAV connection works."""
        try:
            resp = self.session.request(
                'PROPFIND',
                self.base_url + '/',
                headers={'Depth': '0'},
                timeout=10
            )
            return resp.status_code in (200, 207)
        except Exception:
            return False

    def get_evf_original_ext(self, path: str) -> str:
        """Fetch the first 70 bytes of an EVF file to extract the original extension."""
        url = self._build_url(path)
        try:
            # Send Range request to only get header
            resp = self.session.get(url, headers={'Range': 'bytes=0-69'}, timeout=5)
            if resp.status_code in (200, 206) and len(resp.content) >= 70:
                ext_bytes = resp.content[50:66]
                return ext_bytes.decode('utf-8', errors='ignore').strip('\x00').lower()
        except Exception as e:
            print(f"Error extracting ext for {path}: {e}")
            pass
        return ""
