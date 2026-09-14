import urllib.request
import urllib.error
from io import BytesIO

class RemoteFileReader:
    """
    A file-like object that reads from a remote URL using HTTP Range requests.
    Supports read(), seek(), tell(), close().
    """
    def __init__(self, url):
        self._url = url
        self._pos = 0
        self._size = self._get_size()
        
    def _get_size(self):
        try:
            req = urllib.request.Request(self._url, method='HEAD')
            with urllib.request.urlopen(req) as response:
                return int(response.headers.get('Content-Length', 0))
        except:
            return 0

    def read(self, size=-1):
        if size == -1:
            size = self._size - self._pos
            
        if size <= 0: return b""
        
        start = self._pos
        end = start + size - 1
        
        if start >= self._size: return b""
        
        headers = {"Range": f"bytes={start}-{end}"}
        req = urllib.request.Request(self._url, headers=headers)
        
        try:
            with urllib.request.urlopen(req) as response:
                data = response.read()
                self._pos += len(data)
                return data
        except Exception as e:
            print(f"Remote read error: {e}")
            return b""
            
    def seek(self, offset, whence=0):
        if whence == 0:
            self._pos = offset
        elif whence == 1:
            self._pos += offset
        elif whence == 2:
            self._pos = self._size + offset
            
    def tell(self):
        return self._pos
        
    def close(self):
        pass
