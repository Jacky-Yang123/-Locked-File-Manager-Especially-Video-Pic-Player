
import os
import urllib.parse
import base64
import mimetypes
import time
from typing import Dict, List, Optional, Tuple
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from io import BytesIO

from core.crypto_engine import StreamingDecryptor
from utils.file_utils import get_video_files
from utils.range_utils import parse_range_header
from utils import win_paths
from core.access_logger import AccessLogger
from core.evf_format import detect_mixed_file, MIXED_FOOTER_SIZE


def _virtual_name(real_name: str, header_ext: str) -> str:
    """Map a stored file name to the name clients should see.

    ``IMG_6304.evf`` + header ext ``.mp4``  -> ``IMG_6304.mp4``
    ``video.mp4.evf`` + ``.mp4``           -> ``video.mp4`` (no ``.mp4.mp4``)

    The extension is appended only when the stem does not already carry it, and
    the ``.evf`` / image wrapper is *always* dropped — even for a file whose
    header cannot be read — so a listing can never leak an internal name.
    """
    name = real_name
    lower = name.lower()
    if lower.endswith('.evf'):
        name = name[:-4]
    elif lower.endswith(('.jpg', '.jpeg', '.png')):
        name = os.path.splitext(name)[0]
    ext = (header_ext or '').lstrip('.').strip()
    if ext and not name.lower().endswith('.' + ext.lower()):
        name = f"{name}.{ext}"
    return name

class WebDAVRequestHandler(BaseHTTPRequestHandler):
    """
    A lightweight WebDAV request handler for serving encrypted video files.
    Supports:
    - PROPFIND: Listing files (mapping .evf to virtual extensions).
    - GET: Streaming decrypted content (with Range support).
    - HEAD: File metadata.
    - OPTIONS: Capabilities.
    - DELETE: Delete files (maps virtual names back to real .evf files).
    
    Authentication: Basic Auth (matched against server.password).
    """

    server_version = "LockedServer/1.0"

    # Brute-force protection: track failed attempts per client IP
    _failed_attempts: Dict[str, list] = {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Allow', 'OPTIONS, GET, HEAD, PROPFIND, DELETE')
        self.send_header('DAV', '1')
        self.send_header('MS-Author-Via', 'DAV')
        self.send_header('Server', 'LockedServer/1.0')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def _authenticate(self):
        auth_header = self.headers.get('Authorization')
        if not auth_header:
            # <video>/<img> tags cannot set headers — accept ?token= (base64 user:pass)
            from urllib.parse import urlparse, parse_qs
            query_token = parse_qs(urlparse(self.path).query).get('token', [None])[0]
            if query_token:
                import hmac as _hmac
                try:
                    decoded = base64.b64decode(query_token).decode('utf-8')
                    _, password = decoded.split(':', 1)
                    if _hmac.compare_digest(password, self.server.password):
                        return True
                except Exception:
                    pass
            self._send_auth_request()
            return False

        # Rate limit: 5 failed attempts → 15s lockout per IP
        import time as _time
        ip = self.client_address[0]
        now = _time.time()
        self._failed_attempts.setdefault(ip, [])
        self._failed_attempts[ip] = [t for t in self._failed_attempts[ip] if now - t < 60]
        if len(self._failed_attempts[ip]) >= 5:
            self.send_error(429, "Too Many Requests")
            return False

        try:
            auth_type, encoded = auth_header.split(' ', 1)
            # Accept both Basic and Bearer (web UI sends Bearer base64(user:pass))
            if auth_type.lower() not in ('basic', 'bearer'):
                self._send_auth_request()
                return False

            decoded = base64.b64decode(encoded).decode('utf-8')
            username, password = decoded.split(':', 1)

            # Constant-time comparison to prevent timing attacks
            import hmac as _hmac
            if _hmac.compare_digest(password, self.server.password):
                # success — clear this IP's failure history
                self._failed_attempts.pop(ip, None)
                return True
            else:
                self._failed_attempts[ip].append(now)
                self._send_auth_request()
                return False
        except Exception:
            self._send_auth_request()
            return False

    def _send_auth_request(self):
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="LockedShare"')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_DELETE(self):
        """Handle WebDAV DELETE: map virtual name (e.g. abc.mp4) back to real file (abc.evf) and delete it."""
        if not self._authenticate():
            return

        path = self._get_local_path(self.path)
        if path is None:
            self.send_error(403, "Forbidden")
            return

        # Resolve virtual name (abc.mp4) to real file (abc.evf / mixed image)
        found, real_path = self._resolve_virtual_file(path)

        if not found or not os.path.exists(real_path):
            self.send_error(404, "File not found")
            return

        # Double check the real path is also within root (paranoia)
        if not self._within_root(real_path):
            self.send_error(403, "Forbidden")
            return

        try:
            if win_paths.is_dir(real_path):
                import shutil
                shutil.rmtree(win_paths.to_extended(real_path))
            else:
                os.remove(win_paths.to_extended(real_path))

            self.send_response(204)
            self.send_header('Content-Length', '0')
            self.end_headers()
            AccessLogger().log_access(self.client_address[0], "DELETE", urllib.parse.unquote(self.path))
        except PermissionError:
            self.send_error(423, "Locked")
        except Exception as e:
            self.send_error(500, f"Delete failed: {e}")

    def do_PROPFIND(self):
        if not self._authenticate():
            return

        depth = self.headers.get('Depth', '1')
        path = self._get_local_path(self.path)
        if path is None:
            self.send_error(403, "Forbidden")
            return

        # Virtual resolution for PROPFIND root
        found, real_path = self._resolve_virtual_file(path)
        if not found or not os.path.exists(real_path):
            self.send_error(404, "File not found")
            return

        self.send_response(207, 'Multi-Status')
        self.send_header('Content-Type', 'application/xml; charset="utf-8"')
        self.send_header('DAV', '1')
        self.send_header('Server', 'LockedServer/1.0')
        
        # Generate XML response.  Use the query-stripped path so a ?token= or
        # ?query suffix can never leak into the generated hrefs.
        request_root = urllib.parse.urlparse(self.path).path
        xml_content = self._generate_propfind_xml(real_path, depth, request_root)
        xml_bytes = xml_content.encode('utf-8')
        
        self.send_header('Content-Length', str(len(xml_bytes)))
        self.end_headers()
        self.wfile.write(xml_bytes)
        
        # Log Access
        AccessLogger().log_access(self.client_address[0], "BROWSE", urllib.parse.unquote(self.path))

    def do_HEAD(self):
        if not self._authenticate():
            return
        self._handle_get_head(method='HEAD')

    def do_GET(self):
        if not self._authenticate():
            return
        self._handle_get_head(method='GET')

    def _handle_get_head(self, method='GET'):
        path = self._get_local_path(self.path)
        if path is None:
            self.send_error(403, "Forbidden")
            return

        found, real_path = self._resolve_virtual_file(path)
        
        if not found:
            self.send_error(404, "File not found")
            return

        try:
            file_stats = win_paths.stat(real_path)
            if file_stats is None:
                self.send_error(404, "File not found")
                return
            file_size = file_stats.st_size
            last_modified = self.date_time_string(file_stats.st_mtime)
            mime_type, _ = mimetypes.guess_type(path) # Use requested path
            if not mime_type:
                mime_type = 'application/octet-stream'

            decryptor = None
            # Check for mixed file or EVF
            mixed_offset = detect_mixed_file(real_path)
            is_encrypted_request = real_path.endswith('.evf') or mixed_offset != -1
            
            if is_encrypted_request:
                try:
                    decryptor = StreamingDecryptor()
                    # StreamingDecryptor automatically handles mixed file offsets now
                    header = decryptor.open(real_path, self.server.password)
                    file_size = header.original_size
                    # We serve decrypted stream, so mime type is original
                    if header.original_ext:
                        mime_type = mimetypes.guess_type(f"file{header.original_ext}")[0] or mime_type
                except Exception as e:
                    self.log_error(f"Decryption failed: {e}")
                    self.send_error(403, "Decryption failed or wrong password")
                    if decryptor: decryptor.close()
                    return

            # Range handling — parse_range_header understands suffix ranges
            # (bytes=-N), which players use to read a trailing moov atom.
            range_header = self.headers.get('Range')
            span = parse_range_header(range_header, file_size)
            if span is None:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{file_size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                if decryptor: decryptor.close()
                return
            start, end = span
            length = end - start + 1

            self.send_response(206 if range_header else 200)
            self.send_header('Content-Type', mime_type)
            self.send_header('Content-Length', str(length))
            self.send_header('Accept-Ranges', 'bytes')
            if range_header:
                self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
            self.send_header('Last-Modified', last_modified)
            self.end_headers()

            if method == 'HEAD':
                if decryptor: decryptor.close()
                return

            # Stream content
            try:
                if decryptor:
                    self._stream_decrypted_range(decryptor, start, length, self.wfile, header)
                else:
                    f = win_paths.open_binary(real_path)
                    if f is None:
                        return
                    with f:
                        f.seek(start)
                        bytes_sent = 0
                        while bytes_sent < length:
                            chunk_size = min(64*1024, length - bytes_sent)
                            chunk = f.read(chunk_size)
                            if not chunk: break
                            self.wfile.write(chunk)
                            bytes_sent += len(chunk)

                # Log generic GET success (streaming start)
                AccessLogger().log_access(self.client_address[0], "DOWNLOAD/STREAM", urllib.parse.unquote(self.path))
            except (ConnectionResetError, BrokenPipeError):
                pass 
            except Exception as e:
                self.log_error(f"Streaming error: {e}")
            finally:
                if decryptor: decryptor.close()

        except OSError:
            self.send_error(404, "File not found")

    def _stream_decrypted_range(self, decryptor, start_byte, length, output_stream, header):
        chunk_size = header.chunk_size
        start_chunk_idx = start_byte // chunk_size
        end_chunk_idx = (start_byte + length - 1) // chunk_size
        
        bytes_sent = 0
        
        for i in range(start_chunk_idx, end_chunk_idx + 1):
            chunk_data = decryptor.get_chunk_data(i)
            if not chunk_data:
                break
                
            chunk_start_in_file = i * chunk_size
            
            # Intersection of [chunk_start_in_file, chunk_end_in_file] AND [start_byte, start_byte + length]
            # Relative to chunk:
            slice_start = max(0, start_byte - chunk_start_in_file)
            slice_end = min(len(chunk_data), (start_byte + length) - chunk_start_in_file)
            
            if slice_start < slice_end:
                 data_to_send = chunk_data[slice_start:slice_end]
                 output_stream.write(data_to_send)
                 bytes_sent += len(data_to_send)

    def _get_local_path(self, request_path) -> Optional[str]:
        """Map a request path onto a local path inside the share root.

        The query string is dropped first (``/a.mp4?token=x`` used to be joined
        verbatim and produced a guaranteed 404), then the decoded path is
        normalised and checked against the share root so ``..`` / drive-letter
        tricks cannot escape.  Returns ``None`` when the target is outside the
        share root.
        """
        raw = urllib.parse.urlparse(request_path).path
        raw = urllib.parse.unquote(raw)
        rel = raw.lstrip('/').replace('/', os.sep)
        if not rel:
            return os.path.realpath(self.server.root_directory)
        # Reject absolute paths and drive-relative names (C:foo)
        if os.path.isabs(rel) or os.path.splitdrive(rel)[0]:
            return None
        candidate = os.path.realpath(os.path.join(self.server.root_directory, rel))
        if not self._within_root(candidate):
            return None
        return candidate

    def _within_root(self, path: str) -> bool:
        """True when *path* resolves to something inside the share root.

        Symlinks are resolved first, so a link pointing outside the share is
        rejected.  The plain ``abspath`` form is accepted as a fallback because
        ``realpath`` can fail on very long Windows paths, and dropping a real
        entry would silently shorten a directory listing.
        """
        if not path:
            return False
        try:
            root_real = os.path.realpath(self.server.root_directory)
            root_abs = os.path.abspath(self.server.root_directory)
        except (OSError, ValueError):
            return False
        for base in (root_real, root_abs):
            try:
                resolved = os.path.realpath(path)
            except (OSError, ValueError):
                try:
                    resolved = os.path.abspath(path)
                except (OSError, ValueError):
                    continue
            if resolved == base or resolved.startswith(base + os.sep):
                return True
        return False

    def _resolve_virtual_file(self, path):
        # Direct exists
        if os.path.exists(path):
            return True, path
            
        # Virtual mapping
        parent = os.path.dirname(path)
        target_name = os.path.basename(path).lower()
        if not target_name: return False, ""
        
        if os.path.isdir(parent):
            try:
                for entry in win_paths.scandir(parent):
                    if not entry.is_file(): continue
                    if not self._within_root(entry.path): continue
                    
                    name_lower = entry.name.lower()
                    is_evf = name_lower.endswith('.evf')
                    
                    # Check mixed
                    is_mixed = False
                    if name_lower.endswith(('.jpg', '.jpeg', '.png')):
                         # Optimization: only check header if we are looking for a virtual file match
                         # which implies target_name != entry.name
                         if name_lower != target_name:
                             if detect_mixed_file(entry.path) != -1:
                                 is_mixed = True
                    
                    if not (is_evf or is_mixed): continue
                    
                    # Compute virtual name
                    v_name = entry.name
                    o_ext = ""
                    if is_evf: 
                        v_name = v_name[:-4]
                    else:
                        v_name = os.path.splitext(v_name)[0] # Strip .jpg
                        
                    # Try to read header to get actual extension
                    try:
                        from core.evf_format import read_evf_header
                        # For mixed files, we need offset. 
                        # detect_mixed_file returns offset.
                        # We can use StreamingDecryptor or manual read.
                        start_pos = 0
                        if is_mixed:
                            start_pos = detect_mixed_file(entry.path)
                            if start_pos == -1: continue 
                            
                        fh = win_paths.open_binary(entry.path)
                        if fh is not None:
                            with fh as f:
                                f.seek(start_pos)
                                h = read_evf_header(f)
                                o_ext = h.original_ext or ""
                    except:
                        pass

                    # Always expose the virtual name (never the raw .evf one) and
                    # never double-append an extension already present, so the
                    # listed href is exactly what _handle_get_head can resolve.
                    v_name = _virtual_name(entry.name, o_ext)

                    # Accept the name we advertise, and also the raw stored name
                    # so URLs cached by a client before the rename keep working.
                    if v_name.lower() == target_name or entry.name.lower() == target_name:
                         return True, entry.path

            except:
                pass
                
        return False, ""

    def _generate_propfind_xml(self, local_path, depth, request_path_root):
        import datetime
        from xml.sax.saxutils import escape as xml_escape
        import hashlib
        
        def format_iso8601(ts):
            return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            
        is_dir = os.path.isdir(local_path)
        request_path_root = request_path_root.replace('\\', '/')
        if is_dir and not request_path_root.endswith('/'):
            request_path_root += '/'
        
        xml = ['<?xml version="1.0" encoding="utf-8"?>']
        xml.append('<D:multistatus xmlns:D="DAV:">')
        
        def add_file(path_stat, href):
            path = path_stat['path']
            is_collection = path_stat['is_dir']
            
            # Use href basename as display name to ensure consistency
            display_name = urllib.parse.unquote(os.path.basename(href.rstrip('/')))
            if not display_name and href.strip('/') == '':
                display_name = '/'
            
            # Ensure directory href has trailing slash
            if is_collection and not href.endswith('/'):
                href += '/'
                
            xml.append(' <D:response>')
            xml.append(f'  <D:href>{xml_escape(href)}</D:href>')
            xml.append('  <D:propstat>')
            xml.append('   <D:prop>')
            xml.append(f'    <D:displayname>{xml_escape(display_name)}</D:displayname>')
            
            if is_collection:
                xml.append('    <D:resourcetype><D:collection/></D:resourcetype>')
                xml.append('    <D:getcontenttype>httpd/unix-directory</D:getcontenttype>')
            else:
                xml.append('    <D:resourcetype/>')
                # Content length for files only.  For encrypted payloads the
                # *decrypted* size is what a player will see, so report that.
                content_length = path_stat.get('virtual_size') or path_stat['size']
                original_ext = path_stat.get('virtual_ext') or ""
                xml.append(f'    <D:getcontentlength>{content_length}</D:getcontentlength>')
                
                # MIME Type — prefer the real (decrypted) payload's extension.
                content_type = None
                if original_ext:
                    content_type = mimetypes.guess_type(f"file{original_ext}")[0]
                if not content_type:
                    content_type = mimetypes.guess_type(display_name)[0]
                if not content_type:
                    content_type = 'application/octet-stream'
                xml.append(f'    <D:getcontenttype>{content_type}</D:getcontenttype>')
            
            xml.append(f'    <D:getlastmodified>{self.date_time_string(path_stat["mtime"])}</D:getlastmodified>')
            xml.append(f'    <D:creationdate>{format_iso8601(path_stat["ctime"])}</D:creationdate>')
            
            # getetag
            etag = hashlib.md5(f"{path}-{path_stat['mtime']}-{path_stat['size']}".encode()).hexdigest()
            xml.append(f'    <D:getetag>"{etag}"</D:getetag>')
            xml.append('    <D:supportedlock/>')
            
            xml.append('   </D:prop>')
            xml.append('   <D:status>HTTP/1.1 200 OK</D:status>')
            xml.append('  </D:propstat>')
            xml.append(' </D:response>')

        def inspect_encrypted(child_path, is_evf, is_mixed):
            """Return (virtual_size, ext) for an encrypted / mixed file, or None."""
            from core.evf_format import read_evf_header
            start_pos = 0
            if is_mixed:
                start_pos = detect_mixed_file(child_path)
                if start_pos == -1:
                    return None
            fh = win_paths.open_binary(child_path)
            if fh is None:
                return None
            try:
                with fh as f:
                    f.seek(start_pos)
                    h = read_evf_header(f)
                    return h.original_size, (h.original_ext or "")
            except Exception:
                return None

        # Add root
        st = win_paths.stat(local_path)
        if st is None:
            return ""
        root_stat = {
            'path': local_path,
            'size': st.st_size,
            'ctime': st.st_ctime,
            'mtime': st.st_mtime,
            'is_dir': is_dir
        }
        add_file(root_stat, request_path_root)

        if is_dir and depth != '0':
            entries = win_paths.scandir(local_path)
            # Sort entries: folders first, then alphabetical
            try:
                entries = sorted(entries, key=lambda e: (not e.is_dir(), e.name.lower()))
            except OSError:
                pass

            for entry in entries:
                # One unreadable entry must never blank out the whole folder —
                # this is what made deep directories show up empty.
                try:
                    if not self._within_root(entry.path):
                        continue
                    c_st = win_paths.entry_stat(entry)
                    if c_st is None:
                        continue

                    child_path = win_paths.entry_path(entry)

                    # Virtualize name for HREF
                    c_name = entry.name
                    name_lower = c_name.lower()
                    is_dir_entry = entry.is_dir()

                    virtual_size = None
                    virtual_ext = ""

                    if not is_dir_entry:
                        is_evf = name_lower.endswith('.evf')
                        is_mixed = False
                        if name_lower.endswith(('.jpg', '.jpeg', '.png')):
                            if detect_mixed_file(child_path) != -1:
                                is_mixed = True

                        if is_evf or is_mixed:
                            info = inspect_encrypted(child_path, is_evf, is_mixed)
                            if info:
                                virtual_size, virtual_ext = info
                            c_name = _virtual_name(entry.name, virtual_ext)

                    # Correctly join child href with quoting only the new component
                    parent_href = request_path_root.rstrip('/')
                    child_href = f"{parent_href}/{urllib.parse.quote(c_name)}"

                    c_stat = {
                        'path': child_path,
                        'size': c_st.st_size,
                        'ctime': c_st.st_ctime,
                        'mtime': c_st.st_mtime,
                        'is_dir': is_dir_entry,
                        'virtual_size': virtual_size,
                        'virtual_ext': virtual_ext,
                    }
                    add_file(c_stat, child_href)
                except Exception:
                    # Skip the offending entry and keep the rest of the listing.
                    continue

        xml.append('</D:multistatus>')
        return "".join(xml)

