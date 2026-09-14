"""
Network Share Server - HTTP server for LAN file sharing and streaming.
Provides a mobile-friendly web interface for browsing, playing video (including
encrypted .evf files with password caching), and VR panoramic video playback.
"""

import os
import sys
import json
import uuid
import base64
import socket
import ssl
import mimetypes
import threading
import hashlib
import urllib.parse
from pathlib import Path
from typing import Optional, Dict
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from core.crypto_engine import StreamingDecryptor
from core.webdav_server import WebDAVRequestHandler
from core.evf_format import read_evf_header, detect_mixed_file
from core.key_derivation import derive_key
from core.access_logger import AccessLogger
from utils.file_utils import (
    is_video_file, is_image_file, is_audio_file,
    is_text_file, is_encrypted_file, is_pdf_file, is_document_file
)
from utils.constants import ENCRYPTED_EXTENSION
from utils.range_utils import parse_range_header
from Crypto.Cipher import AES

# Background thumbnail generation state (shared with the PC app's thumbnails cache)
_bg_thumb_state = {"running": False, "done": 0, "total": 0}
_bg_thumb_lock = threading.Lock()


def _generate_one_thumbnail(abs_path: str, password: str) -> str:
    """Generate (or reuse) a thumbnail for a local file using the PC app's own
    ThumbnailRunnable logic — writes into the SAME thumbnails cache directory.
    Returns the thumb path ('' on failure)."""
    try:
        from core.media_library import ThumbnailRunnable
        tr = ThumbnailRunnable(abs_path, password)
        result = tr._generate(abs_path)
        return result or ""
    except Exception:
        return ""


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Thread-per-request HTTP server."""
    daemon_threads = True
    allow_reuse_address = True


class NetworkShareServer:
    """
    Manages the HTTP file sharing server lifecycle.
    """

    def __init__(self):
        self._server: Optional[ThreadedHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._root_path: str = ""
        self._port: int = 0
        self._ip: str = ""
        self._use_https: bool = False

        # Security: password cache and streaming tokens
        # _cached_passwords: list of passwords tried successfully (most recent first)
        self._cached_passwords: list[str] = []
        # _stream_tokens: token -> {"path": str, "password": str, "decryptor": StreamingDecryptor}
        self._stream_tokens: Dict[str, dict] = {}
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def url(self) -> str:
        if self._ip and self._port:
            scheme = "https" if self._use_https else "http"
            return f"{scheme}://{self._ip}:{self._port}"
        return ""

    @property
    def use_https(self) -> bool:
        return self._use_https

    @property
    def port(self) -> int:
        return self._port

    @property
    def ip(self) -> str:
        return self._ip

    def start(self, root_path: str, port: int = 8080, password: str = "", use_https: bool = False) -> str:
        """Start the server. Returns the URL.
        use_https=True wraps the socket with TLS using the bundled self-signed
        certificate, so the LAN traffic (including credentials and decrypted
        video stream) is encrypted end-to-end."""
        if self._server:
            self.stop()

        self._root_path = os.path.abspath(root_path)
        self._ip = self._get_local_ip()
        self._use_https = use_https

        if not password:
             # If no password provided, maybe default or error?
             # User UI forces password. CLI might not.
             # Warn or proceed?
             # WebDAV needs authentication.
             pass

        server_instance = self

        class RequestHandler(WebDAVRequestHandler):
            def log_message(self, format, *args):
                pass  # Suppress logs

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path
                params = urllib.parse.parse_qs(parsed.query)

                # Public endpoints: login page, static assets, auth — no auth required
                public = (
                    path in ("/", "") or path.startswith("/static/")
                    or path == "/api/auth/login" or path == "/favicon.ico"
                )
                if not public and not self._authenticate():
                    return

                if path == "/" or path == "":
                    self._serve_index(server_instance)
                elif path.startswith("/static/"):
                    self._serve_static(path)
                elif path == "/player":
                    self._serve_player_page(server_instance, params)
                elif path.startswith("/api/"):
                    # API Dispatch
                    if path == "/api/files/list":
                        self._api_files_list(server_instance, params)
                    elif path == "/api/files/list_all":
                        self._api_files_list_all(server_instance, params)
                    elif path == "/api/files/raw":
                        self._api_files_raw(server_instance, params)
                    elif path == "/api/files/download_encrypted":
                        self._api_download(server_instance, params, decrypted=False)
                    elif path == "/api/files/download_decrypted":
                        self._api_download(server_instance, params, decrypted=True)
                    elif path == "/api/files/scan":
                        self._api_send_json({"status": "scan_started"})
                    elif path == "/api/files/scan_status":
                        self._api_send_json({"is_scanning": False, "scanned_dirs": 0, "scanned_files": 0, "current_path": "", "error": "", "started_at": None})
                    elif path == "/api/thumbnails/generate_status":
                        self._api_generate_thumb_status()
                    elif path.startswith("/api/thumbnails/"):
                        self._api_thumbnail_by_hash(server_instance, path, params)
                    elif path == "/api/stream/open":
                        self._api_stream_open(server_instance)
                    elif path.startswith("/api/preview/"):
                        self._api_preview_pdf(server_instance, path, params)
                    elif path.startswith("/api/stream/") and path.endswith("/video"):
                        self._api_stream_video(server_instance, path, params)
                    elif path.startswith("/api/stream/") and path.endswith("/close"):
                        self._api_stream_close(server_instance, path)
                    elif path == "/api/auth/login":
                        self._api_auth_login()
                    elif path == "/api/auth/account":
                        self._api_send_json({"username": "admin"})
                    elif path == "/api/settings":
                        self._api_send_json({"storage_type": "local", "webdav_url": "", "webdav_username": "", "webdav_password": "", "local_path": "", "scan_path": ""})
                    elif path == "/api/files":
                        self._serve_file_list(server_instance, params)
                    elif path == "/api/file":
                        self._serve_file(server_instance, params)
                    elif path == "/api/stream":
                        self._serve_stream(server_instance, params)
                    elif path == "/api/thumbnail":
                        self._serve_thumbnail(server_instance, params)
                    elif path == "/api/nav":
                        self._handle_nav(server_instance, params)
                    else:
                        self.send_error(404)
                elif path == "/favicon.ico":
                    self.send_response(204)
                    self.end_headers()
                else:
                    # WebDAV File Serving (Video/Encrypted)
                    super().do_GET()

            def do_POST(self):
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path

                # /api/auth/login is public; everything else requires auth
                if path != "/api/auth/login" and not self._authenticate():
                    return

                if path == "/api/unlock":
                    self._handle_unlock(server_instance)
                elif path == "/api/try_cached":
                    self._handle_try_cached(server_instance)
                elif path == "/api/stream/open":
                    self._api_stream_open(server_instance)
                elif path.startswith("/api/stream/") and path.endswith("/close"):
                    self._api_stream_close(server_instance, path)
                elif path == "/api/auth/login":
                    self._api_auth_login()
                elif path == "/api/files/scan":
                    self._api_send_json({"status": "scan_started"})
                elif path == "/api/thumbnails/generate_async":
                    self._api_generate_thumbnails(server_instance)
                else:
                    self.send_error(404)

            def do_PUT(self):
                # Web UI saves settings/account — accept and no-op on the share server
                if not self._authenticate():
                    return
                self._api_send_json({"status": "ok"})

            # --- API Handlers ---

            def _handle_nav(self, srv, params):
                """Handle next/prev file navigation."""
                current_path = params.get("path", [""])[0]
                direction = params.get("dir", ["next"])[0] # next or prev
                
                if not current_path:
                    self.send_error(400)
                    return

                # Resolve parent dir
                rel_dir = os.path.dirname(current_path)
                abs_dir = srv._resolve_safe_path(rel_dir)
                
                if not abs_dir or not os.path.isdir(abs_dir):
                    self.send_error(404)
                    return

                # Get sorted file list
                try:
                    files = []
                    for entry in sorted(os.scandir(abs_dir), key=lambda e: e.name.lower()):
                        if not entry.is_file(): continue
                        
                        # Virtualize
                        name = self._virtualize_name(entry.name, entry.path)
                        
                        # Check if supported media
                        if (is_video_file(name) or is_encrypted_file(name) or 
                            is_image_file(name) or is_audio_file(name)):
                            files.append(name)
                except:
                    self.send_error(500)
                    return

                # Find current index
                current_name = os.path.basename(current_path)
                try:
                    idx = files.index(current_name)
                except ValueError:
                    # Current file not found? Start from 0
                    idx = 0

                # Calc next index
                if direction == "next":
                    next_idx = (idx + 1) % len(files)
                else:
                    next_idx = (idx - 1 + len(files)) % len(files)

                next_name = files[next_idx]
                # Virtualize name/path
                display_name = next_name
                if display_name.endswith('.evf'):
                    display_name = display_name[:-4]
                
                next_rel_path = os.path.join(rel_dir, display_name).replace("\\", "/")

                self._send_json({
                    "path": next_rel_path,
                    "name": display_name,
                    "is_encrypted": is_encrypted_file(next_name)
                })

            def _serve_index(self, srv):
                html = _get_frontend_html()
                self._send_html(html)
                AccessLogger().log_access(self.client_address[0], "VISIT", "Root")

            def _serve_player_page(self, srv, params):
                html = _get_player_html()
                self._send_html(html)

            def _serve_file_list(self, srv, params):
                rel_path = params.get("path", [""])[0]
                abs_path = self._resolve_safe_path(srv, rel_path)
                if abs_path is None:
                    self.send_error(403, "Access denied")
                    return

                if not os.path.isdir(abs_path):
                    self.send_error(404, "Directory not found")
                    return

                items = []
                try:
                    for entry in sorted(os.scandir(abs_path), key=lambda e: (not e.is_dir(), e.name.lower())):
                        item_rel_dir = rel_path
                        
                        # Virtualize
                        display_name = entry.name
                        if not entry.is_dir():
                            display_name = self._virtualize_name(entry.name, entry.path)
                        
                        display_path = (os.path.join(item_rel_dir, display_name) if item_rel_dir else display_name).replace("\\", "/")

                        info = {
                            "name": display_name,
                            "path": display_path,
                            "is_dir": entry.is_dir(),
                        }
                        if not entry.is_dir():
                            try:
                                stat = entry.stat()
                                info["size"] = stat.st_size
                            except:
                                info["size"] = 0
                            
                            info["is_encrypted"] = is_encrypted_file(entry.path)
                            
                            # For encrypted files, get original size and type
                            if info["is_encrypted"]:
                                try:
                                    # Handle mixed file offset
                                    offset = detect_mixed_file(entry.path)
                                    start_pos = 0 if offset == -1 else offset
                                    
                                    with open(entry.path, 'rb') as f:
                                        f.seek(start_pos)
                                        header = read_evf_header(f)
                                        info["size"] = header.original_size
                                        info["original_ext"] = header.original_ext
                                        dummy = f"x{header.original_ext}"
                                        info["is_video"] = is_video_file(dummy)
                                        info["is_image"] = is_image_file(dummy)
                                        info["is_audio"] = is_audio_file(dummy)
                                        info["is_pdf"] = is_pdf_file(dummy)
                                        info["is_text"] = is_text_file(dummy)
                                except:
                                    pass
                            else:
                                info["is_video"] = is_video_file(entry.name)
                                info["is_image"] = is_image_file(entry.name)
                                info["is_audio"] = is_audio_file(entry.name)
                                info["is_pdf"] = is_pdf_file(entry.name)
                                info["is_text"] = is_text_file(entry.name)
                            
                            # Add thumbnail URL if applicable
                            if not entry.is_dir() and (info.get("is_video") or info.get("is_image") or info.get("is_encrypted")):
                                info["thumbnail_url"] = f"/api/thumb?path={urllib.parse.quote(info['path'])}"
                        items.append(info)
                except Exception as e:
                    self.send_error(500, str(e))
                    return

                self._send_json(items)

            def _serve_file(self, srv, params):
                """Serve a normal (non-encrypted) file with Range support."""
                rel_path = params.get("path", [""])[0]
                abs_path = self._resolve_safe_path(srv, rel_path)
                if abs_path is None or not os.path.isfile(abs_path):
                    self.send_error(404)
                    return

                if is_encrypted_file(abs_path):
                    self.send_error(403, "Use /api/stream for encrypted files")
                    return

                file_size = os.path.getsize(abs_path)
                mime_type = mimetypes.guess_type(abs_path)[0] or "application/octet-stream"

                # Range request handling (suffix ranges included)
                range_header = self.headers.get("Range")
                span = parse_range_header(range_header, file_size)
                if span is None:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.end_headers()
                    return
                start, end = span
                length = end - start + 1

                self.send_response(206 if range_header else 200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                self.send_header("Access-Control-Allow-Origin", "*")
                if range_header:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.end_headers()

                try:
                    with open(abs_path, "rb") as f:
                        f.seek(start)
                        remaining = length
                        buf_size = 64 * 1024
                        while remaining > 0:
                            chunk = f.read(min(buf_size, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except Exception:
                    pass
                
                AccessLogger().log_access(self.client_address[0], "ACCESS", os.path.basename(abs_path))


            def _serve_stream(self, srv, params):
                """Serve encrypted file stream using token."""
                token = params.get("token", [""])[0]

                with srv._lock:
                    session = srv._stream_tokens.get(token)

                if not session:
                    self.send_error(403, "Invalid or expired token")
                    return

                abs_path = session["path"]
                password = session["password"]

                if not os.path.isfile(abs_path):
                    self.send_error(404)
                    return

                # Create a new decryptor for this request (thread-safe)
                try:
                    dec = StreamingDecryptor()
                    header = dec.open(abs_path, password)
                except ValueError:
                    self.send_error(403, "Password no longer valid")
                    return
                except Exception as e:
                    self.send_error(500, str(e))
                    return

                total_size = dec.get_decrypted_size()
                original_ext = dec.get_original_extension() or ".mp4"
                mime_type = mimetypes.guess_type(f"file{original_ext}")[0] or "video/mp4"
                chunk_size = header.chunk_size

                # Range request (suffix ranges included)
                range_header = self.headers.get("Range")
                span = parse_range_header(range_header, total_size)
                if span is None:
                    dec.close()
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{total_size}")
                    self.end_headers()
                    return
                start, end = span
                length = end - start + 1

                self.send_response(206 if range_header else 200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                self.send_header("Access-Control-Allow-Origin", "*")
                if range_header:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
                self.end_headers()

                try:
                    current_pos = start
                    while current_pos <= end:
                        chunk_idx = current_pos // chunk_size
                        chunk_offset = current_pos % chunk_size

                        chunk_data = dec.get_chunk_data(chunk_idx)
                        if not chunk_data:
                            break

                        available = len(chunk_data) - chunk_offset
                        send_amt = min(available, end - current_pos + 1)
                        if send_amt <= 0:
                            break

                        self.wfile.write(chunk_data[chunk_offset:chunk_offset + send_amt])
                        current_pos += send_amt
                except Exception:
                    pass
                finally:
                    dec.close()

            def _serve_thumbnail(self, srv, params):
                """Serve thumbnail for a file if available (with on-the-fly decryption)."""
                rel_path = params.get("path", [""])[0]
                abs_path = self._resolve_safe_path(srv, rel_path)
                if abs_path is None:
                    self.send_error(404)
                    return

                # Resolve virtual path to real path
                found, real_path = self._resolve_virtual_file(abs_path)
                if found:
                    abs_path = real_path

                # Normalize path for consistent hashing
                abs_path = os.path.normpath(os.path.abspath(abs_path))
                file_hash = hashlib.md5(abs_path.encode("utf-8")).hexdigest()
                
                # Try finding thumbnail in various locations
                thumb_dir = os.path.join(os.getcwd(), "thumbnails")
                thumb_path_normal = os.path.join(thumb_dir, f"{file_hash}.jpg")
                thumb_path_enc = os.path.join(thumb_dir, f"{file_hash}.jpg.enc")

                if os.path.exists(thumb_path_normal):
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "max-age=86400")
                    self.end_headers()
                    with open(thumb_path_normal, "rb") as f:
                        self.wfile.write(f.read())
                elif os.path.exists(thumb_path_enc):
                    # Try decrypting on the fly
                    try:
                        with open(thumb_path_enc, "rb") as f:
                            salt = f.read(16)
                            nonce = f.read(12)
                            tag = f.read(16)
                            ciphertext = f.read()

                        key, _ = derive_key(srv.password, salt)
                        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
                        plain_bytes = cipher.decrypt_and_verify(ciphertext, tag)

                        self.send_response(200)
                        self.send_header("Content-Type", "image/jpeg")
                        self.send_header("Cache-Control", "max-age=86400")
                        self.end_headers()
                        self.wfile.write(plain_bytes)
                    except Exception:
                        # Decryption failed or wrong password
                        self.send_response(204)
                        self.end_headers()
                else:
                    self.send_response(204)
                    self.end_headers()

            def _handle_unlock(self, srv):
                """Handle password submission for encrypted file."""
                try:
                    content_len = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(content_len).decode("utf-8"))
                except:
                    self.send_error(400)
                    return

                rel_path = body.get("path", "")
                password = body.get("password", "")

                abs_path = self._resolve_safe_path(srv, rel_path)
                if abs_path is None or not os.path.isfile(abs_path):
                    self.send_error(404)
                    return

                if not is_encrypted_file(abs_path):
                    self.send_error(400, "Not an encrypted file")
                    return

                # Try to decrypt
                try:
                    dec = StreamingDecryptor()
                    dec.open(abs_path, password)
                    original_ext = dec.get_original_extension()
                    dec.close()
                except ValueError:
                    self._send_json({"success": False, "error": "密码错误"})
                    return
                except Exception as e:
                    self._send_json({"success": False, "error": str(e)})
                    return

                # Password is correct - cache it and create token
                with srv._lock:
                    if password not in srv._cached_passwords:
                        srv._cached_passwords.insert(0, password)
                        # Keep max 10 cached passwords
                        srv._cached_passwords = srv._cached_passwords[:10]

                    token = str(uuid.uuid4())
                    srv._stream_tokens[token] = {
                        "path": abs_path,
                        "password": password,
                    }

                self._send_json({
                    "success": True,
                    "token": token,
                    "original_ext": original_ext or "",
                })

            def _handle_try_cached(self, srv):
                """Try cached passwords for an encrypted file."""
                try:
                    content_len = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(content_len).decode("utf-8"))
                except:
                    self.send_error(400)
                    return

                rel_path = body.get("path", "")
                abs_path = self._resolve_safe_path(srv, rel_path)
                if abs_path is None or not os.path.isfile(abs_path):
                    self.send_error(404)
                    return

                if not is_encrypted_file(abs_path):
                    self.send_error(400, "Not an encrypted file")
                    return

                # Try each cached password
                with srv._lock:
                    passwords_to_try = list(srv._cached_passwords)

                for password in passwords_to_try:
                    try:
                        dec = StreamingDecryptor()
                        dec.open(abs_path, password)
                        original_ext = dec.get_original_extension()
                        dec.close()

                        # Success! Create token
                        with srv._lock:
                            token = str(uuid.uuid4())
                            srv._stream_tokens[token] = {
                                "path": abs_path,
                                "password": password,
                            }

                        self._send_json({
                            "success": True,
                            "token": token,
                            "original_ext": original_ext or "",
                        })
                        return
                    except:
                        continue

                # No cached password worked
                self._send_json({"success": False})

            # --- Helpers ---

            def _virtualize_name(self, filename: str, abs_path: str) -> str:
                """Compute the virtualized name for a file."""
                name_lower = filename.lower()
                is_evf = name_lower.endswith('.evf')
                is_mixed = False
                
                if name_lower.endswith(('.jpg', '.jpeg', '.png')):
                     try:
                         if detect_mixed_file(abs_path) != -1:
                             is_mixed = True
                     except:
                         pass
                
                if not (is_evf or is_mixed):
                    return filename
                
                base = filename
                if is_evf: base = base[:-4]
                else: base = os.path.splitext(base)[0]
                
                try:
                    start_pos = 0
                    if is_mixed:
                         start_pos = detect_mixed_file(abs_path)
                         if start_pos == -1: return base # Should not happen if checked above
                    
                    with open(abs_path, 'rb') as f:
                        f.seek(start_pos)
                        h = read_evf_header(f)
                        o_ext = (h.original_ext or "").lstrip('.')
                        if o_ext and not base.lower().endswith('.' + o_ext.lower()):
                            return f"{base}.{o_ext}"
                except:
                    pass
                return base

            def _resolve_safe_path(self, srv, rel_path: str) -> Optional[str]:
                """Resolve relative path ensuring it's within root.
                Tolerates leading slashes (web UI paths like '/folder/file.mp4')."""
                if not rel_path:
                    return srv._root_path
                # Strip leading separators so virtual '/x' maps to root-relative 'x'
                stripped = rel_path.lstrip('/\\')
                if not stripped:
                    return srv._root_path
                # Normalize and prevent path traversal
                clean = os.path.normpath(stripped)
                if clean.startswith("..") or os.path.isabs(clean) or os.path.splitdrive(clean)[0]:
                    return None
                root = os.path.realpath(srv._root_path)
                abs_path = os.path.realpath(os.path.join(root, clean))
                # Verify it's still under root (separator-aware, so a sibling
                # directory such as "<root>_evil" cannot slip through)
                if abs_path != root and not abs_path.startswith(root + os.sep):
                    return None
                return abs_path

            def _send_json(self, data):
                content = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)

            def _send_html(self, html):
                content = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def _api_json(self, data, status=200):
                content = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)

            def _api_send_json(self, data):
                self._api_json(data, 200)

            def _serve_static(self, path):
                """Serve web/static assets for the embedded web UI."""
                rel = path[len("/static/"):].replace("/", os.sep)
                base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                web_static = os.path.normpath(os.path.join(base_dir, "web", "static"))
                full = os.path.normpath(os.path.join(web_static, rel))
                if not (full == web_static or full.startswith(web_static + os.sep)) or not os.path.isfile(full):
                    self.send_error(404)
                    return
                ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(os.path.getsize(full)))
                self.end_headers()
                with open(full, "rb") as f:
                    while True:
                        chunk = f.read(64 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)

            def _thumb_dir(self):
                return os.path.join(os.getcwd(), "thumbnails")

            def _file_hash_of(self, abs_path: str) -> str:
                return hashlib.md5(os.path.normpath(os.path.abspath(abs_path)).encode("utf-8")).hexdigest()

            def _api_files_list(self, srv, params):
                """Web-style directory listing: {files:[...], current_path}."""
                rel_path = params.get("path", [""])[0]
                abs_path = self._resolve_safe_path(srv, rel_path)
                if abs_path is None or not os.path.isdir(abs_path):
                    self._api_json({"error": "目录不存在", "files": []})
                    return
                items = []
                try:
                    for entry in sorted(os.scandir(abs_path), key=lambda e: (not e.is_dir(), e.name.lower())):
                        if entry.name.startswith('.') or entry.name.startswith('@'):
                            continue
                        display_name = entry.name
                        real_path = entry.path
                        if not entry.is_dir():
                            display_name = self._virtualize_name(entry.name, entry.path)
                        display_path = (os.path.join(rel_path, display_name) if rel_path else display_name).replace("\\", "/")
                        file_hash = self._file_hash_of(real_path)
                        thumb_dir = self._thumb_dir()
                        info = {
                            "name": display_name,
                            "path": display_path,
                            "is_dir": entry.is_dir(),
                            "size": 0,
                            "ext": os.path.splitext(display_name)[1].lower() if not entry.is_dir() else "",
                            "file_hash": file_hash,
                            "has_thumbnail": os.path.exists(os.path.join(thumb_dir, f"{file_hash}.jpg")),
                            "has_encrypted_thumbnail": os.path.exists(os.path.join(thumb_dir, f"{file_hash}.jpg.enc")),
                        }
                        if not entry.is_dir():
                            try:
                                info["size"] = entry.stat().st_size
                            except Exception:
                                pass
                            # EVF: read original extension from header
                            if is_encrypted_file(entry.path):
                                try:
                                    offset = detect_mixed_file(entry.path)
                                    start_pos = 0 if offset == -1 else offset
                                    with open(entry.path, 'rb') as f:
                                        f.seek(start_pos)
                                        h = read_evf_header(f)
                                        info["original_ext"] = h.original_ext or ""
                                except Exception:
                                    pass
                        items.append(info)
                except Exception:
                    pass
                self._api_json({"files": items, "current_path": rel_path})

            def _api_files_list_all(self, srv, params):
                """Web-style flat listing: all files recursively (real-time os.walk)."""
                files = []
                thumb_dir = self._thumb_dir()
                try:
                    for dirpath, dirnames, filenames in os.walk(srv._root_path):
                        dirnames[:] = [d for d in dirnames if not d.startswith('.') and not d.startswith('@')]
                        rel_dir = os.path.relpath(dirpath, srv._root_path).replace("\\", "/")
                        for fname in filenames:
                            if fname.startswith('.'):
                                continue
                            full = os.path.join(dirpath, fname)
                            display_name = self._virtualize_name(fname, full)
                            display_path = (rel_dir + "/" + display_name) if rel_dir != "." else display_name
                            file_hash = self._file_hash_of(full)
                            try:
                                fsize = os.path.getsize(full)
                            except Exception:
                                fsize = 0
                            files.append({
                                "name": display_name,
                                "path": display_path,
                                "is_dir": False,
                                "size": fsize,
                                "ext": os.path.splitext(display_name)[1].lower(),
                                "file_hash": file_hash,
                                "has_thumbnail": os.path.exists(os.path.join(thumb_dir, f"{file_hash}.jpg")),
                                "has_encrypted_thumbnail": os.path.exists(os.path.join(thumb_dir, f"{file_hash}.jpg.enc")),
                            })
                            if is_encrypted_file(full):
                                try:
                                    offset = detect_mixed_file(full)
                                    start_pos = 0 if offset == -1 else offset
                                    with open(full, 'rb') as f:
                                        f.seek(start_pos)
                                        h = read_evf_header(f)
                                        files[-1]["original_ext"] = h.original_ext or ""
                                except Exception:
                                    pass
                except Exception:
                    pass
                self._api_json({"files": files})

            def _api_thumbnail_by_hash(self, srv, path, params):
                """Serve thumbnail by md5 hash (web UI format): /api/thumbnails/<hash>?password=..."""
                file_hash = path.split("/")[-1].split("?")[0]
                thumb_dir = self._thumb_dir()
                plain = os.path.join(thumb_dir, f"{file_hash}.jpg")
                enc = os.path.join(thumb_dir, f"{file_hash}.jpg.enc")
                user_password = params.get("password", [""])[0]

                def _send_image(data):
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "max-age=86400")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

                if os.path.exists(plain):
                    with open(plain, "rb") as f:
                        _send_image(f.read())
                    return

                if os.path.exists(enc):
                    try:
                        with open(enc, "rb") as f:
                            salt = f.read(16)
                            nonce = f.read(12)
                            tag = f.read(16)
                            ciphertext = f.read()
                        for pwd in [user_password, srv.password]:
                            if not pwd:
                                continue
                            try:
                                key, _ = derive_key(pwd, salt)
                                cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
                                _send_image(cipher.decrypt_and_verify(ciphertext, tag))
                                return
                            except Exception:
                                continue
                    except Exception:
                        pass
                    self.send_response(204)
                    self.end_headers()
                    return

                self.send_response(204)
                self.end_headers()

            def _api_stream_open(self, srv):
                """Web-style stream open: POST {path, password} -> {session_id: token}"""
                try:
                    content_len = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(content_len).decode("utf-8"))
                except Exception:
                    self._api_json({"error": "参数错误"}, 400)
                    return
                rel_path = body.get("path", "")
                password = body.get("password", "")
                abs_path = self._resolve_safe_path(srv, rel_path)
                if abs_path is None:
                    self._api_json({"error": "路径无效"}, 400)
                    return
                found, real_path = self._resolve_virtual_file(abs_path)
                if found:
                    abs_path = real_path
                if not os.path.isfile(abs_path):
                    self._api_json({"error": "文件不存在"}, 404)
                    return
                try:
                    dec = StreamingDecryptor()
                    header = dec.open(abs_path, password)
                except ValueError:
                    self._api_json({"error": "密码错误或文件损坏"}, 403)
                    return
                except Exception as e:
                    self._api_json({"error": str(e)}, 500)
                    return
                token = uuid.uuid4().hex
                session = {"path": abs_path, "password": password, "decryptor": None, "pdf_path": None}
                # PDF: dump decrypted content to a temp file for PyMuPDF rendering
                orig_ext = (header.original_ext or "").lower()
                if orig_ext == ".pdf":
                    try:
                        import tempfile
                        tf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                        pdf_path = tf.name
                        for chunk in dec.stream_all():
                            tf.write(chunk)
                        tf.close()
                        session["pdf_path"] = pdf_path
                    except Exception:
                        session["pdf_path"] = None
                dec.close()
                with srv._lock:
                    srv._stream_tokens[token] = session
                self._api_json({"session_id": token})

            def _api_stream_video(self, srv, path, params):
                """Web-style stream video: /api/stream/<sid>/video (sid is the session token)."""
                parts = path.split("/")
                sid = parts[3] if len(parts) > 3 else ""
                self._serve_stream(srv, {"token": [sid]})

            def _api_stream_close(self, srv, path):
                parts = path.split("/")
                sid = parts[3] if len(parts) > 3 else ""
                with srv._lock:
                    session = srv._stream_tokens.pop(sid, None)
                if session and session.get("pdf_path"):
                    try:
                        os.unlink(session["pdf_path"])
                    except Exception:
                        pass
                self._api_json({"status": "ok"})

            def _api_preview_pdf(self, srv, path, params):
                """Web-style encrypted PDF preview: /api/preview/<sid>/pdf/info | /pdf/page/<n>"""
                parts = path.split("/")
                if len(parts) < 5:
                    self._api_json({"error": "参数错误"}, 400)
                    return
                sid = parts[3]
                sub = parts[4:]  # ['pdf','info'] or ['pdf','page','3']
                with srv._lock:
                    session = srv._stream_tokens.get(sid)
                if not session:
                    self._api_json({"error": "会话失效"}, 403)
                    return
                pdf_path = session.get("pdf_path")
                if not pdf_path or not os.path.exists(pdf_path):
                    self._api_json({"error": "PDF 未就绪"}, 404)
                    return

                try:
                    import fitz
                    doc = fitz.open(pdf_path)
                except Exception as e:
                    self._api_json({"error": f"PDF 打开失败: {e}"}, 500)
                    return

                try:
                    if sub[:2] == ["pdf", "info"]:
                        page = doc[0]
                        self._api_json({
                            "page_count": doc.page_count,
                            "width": page.rect.width,
                            "height": page.rect.height,
                        })
                        return
                    if len(sub) == 3 and sub[0] == "pdf" and sub[1] == "page":
                        n = int(sub[2])
                        zoom = float(params.get("zoom", ["2"])[0])
                        if n < 0 or n >= doc.page_count:
                            self._api_json({"error": "页码越界"}, 400)
                            return
                        page = doc[n]
                        mat = fitz.Matrix(zoom, zoom)
                        pix = page.get_pixmap(matrix=mat)
                        data = pix.tobytes("jpeg")
                        self.send_response(200)
                        self.send_header("Content-Type", "image/jpeg")
                        self.send_header("Cache-Control", "max-age=86400")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return
                    self._api_json({"error": "未知操作"}, 400)
                finally:
                    doc.close()

            def _api_generate_thumbnails(self, srv):
                """Real background thumbnail generation using the PC app's cache.
                POST {paths: [virtual paths], password} -> {status: started|already_running}"""
                try:
                    content_len = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(content_len).decode("utf-8"))
                except Exception:
                    body = {}
                paths = body.get("paths", [])
                password = body.get("password", "")
                if not paths or not password:
                    self._api_json({"error": "路径和密码不能为空"}, 400)
                    return

                global _bg_thumb_state
                with _bg_thumb_lock:
                    if _bg_thumb_state["running"]:
                        self._api_json({"status": "already_running"})
                        return
                    _bg_thumb_state["running"] = True
                    _bg_thumb_state["done"] = 0
                    _bg_thumb_state["total"] = len(paths)

                def _run():
                    try:
                        for p in paths:
                            try:
                                abs_path = self._resolve_safe_path(srv, p)
                                if abs_path:
                                    found, real_path = self._resolve_virtual_file(abs_path)
                                    if found:
                                        abs_path = real_path
                                    if os.path.isfile(abs_path):
                                        _generate_one_thumbnail(abs_path, password)
                            except Exception:
                                pass
                            with _bg_thumb_lock:
                                _bg_thumb_state["done"] += 1
                    finally:
                        with _bg_thumb_lock:
                            _bg_thumb_state["running"] = False

                threading.Thread(target=_run, daemon=True).start()
                self._api_json({"status": "started"})

            def _api_generate_thumb_status(self):
                with _bg_thumb_lock:
                    st = {
                        "running": _bg_thumb_state["running"],
                        "done": _bg_thumb_state["done"],
                        "total": _bg_thumb_state["total"],
                    }
                self._api_json(st)

            def _api_auth_login(self):
                """Web-style login: {username, password} -> {token: base64(user:pass)}"""
                try:
                    content_len = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(content_len).decode("utf-8"))
                except Exception:
                    body = {}
                username = body.get("username", "admin")
                password = body.get("password", "")
                import hmac as _hmac
                if _hmac.compare_digest(password, self.server.password):
                    token = base64.b64encode(f"{username}:{password}".encode()).decode()
                    self._api_json({"token": token, "username": username})
                else:
                    self._api_json({"error": "密码错误"}, 401)

            def _api_files_raw(self, srv, params):
                """Serve a non-encrypted file directly (web /api/files/raw), with Range support."""
                rel_path = params.get("path", [""])[0]
                abs_path = self._resolve_safe_path(srv, rel_path)
                if abs_path is None:
                    self.send_error(404)
                    return
                found, real_path = self._resolve_virtual_file(abs_path)
                if found:
                    abs_path = real_path
                if not os.path.isfile(abs_path):
                    self.send_error(404)
                    return
                if is_encrypted_file(abs_path):
                    self.send_error(403, "加密文件请用解密下载")
                    return
                ctype = mimetypes.guess_type(abs_path)[0] or "application/octet-stream"
                total_size = os.path.getsize(abs_path)

                range_header = self.headers.get("Range")
                span = parse_range_header(range_header, total_size)
                if span is None:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{total_size}")
                    self.end_headers()
                    return
                start, end = span
                length = end - start + 1
                if range_header:
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
                else:
                    self.send_response(200)

                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                with open(abs_path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)

            def _api_download(self, srv, params, decrypted):
                """Web-style download: encrypted (raw .evf) or decrypted (needs X-EVF-Password)."""
                rel_path = params.get("path", [""])[0]
                abs_path = self._resolve_safe_path(srv, rel_path)
                if abs_path is None:
                    self.send_error(404)
                    return
                found, real_path = self._resolve_virtual_file(abs_path)
                if found:
                    abs_path = real_path
                if not os.path.isfile(abs_path):
                    self.send_error(404)
                    return
                fname = os.path.basename(abs_path)

                if not decrypted:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Disposition", f'attachment; filename="{urllib.parse.quote(fname)}"')
                    self.send_header("Content-Length", str(os.path.getsize(abs_path)))
                    self.end_headers()
                    with open(abs_path, "rb") as f:
                        while True:
                            chunk = f.read(64 * 1024)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    return

                password = self.headers.get("X-EVF-Password", "")
                if not password:
                    self.send_error(400, "缺少解密密码")
                    return
                try:
                    dec = StreamingDecryptor()
                    header = dec.open(abs_path, password)
                except ValueError:
                    self.send_error(403, "密码错误")
                    return
                orig_ext = header.original_ext or ".mp4"
                out_name = os.path.splitext(fname)[0] + orig_ext
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{urllib.parse.quote(out_name)}"')
                self.send_header("Content-Length", str(header.original_size))
                self.end_headers()
                try:
                    for chunk in dec.stream_all():
                        self.wfile.write(chunk)
                except Exception:
                    pass
                finally:
                    dec.close()

        # Find available port
        actual_port = port
        for attempt in range(10):
            try:
                self._server = ThreadedHTTPServer(("0.0.0.0", actual_port), RequestHandler)
                break
            except OSError:
                actual_port = port + attempt + 1
                if attempt == 9:
                    raise RuntimeError(f"Cannot find available port near {port}")

        self._port = actual_port
        self._server.password = password
        self._server.root_directory = self._root_path

        # TLS wrap with bundled self-signed certificate (generated at build time)
        if self._use_https:
            base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            cert_file = os.path.join(base_dir, 'assets', 'lockedshare_cert.pem')
            key_file = os.path.join(base_dir, 'assets', 'lockedshare_key.pem')
            if os.path.exists(cert_file) and os.path.exists(key_file):
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.minimum_version = ssl.TLSVersion.TLSv1_2
                ctx.load_cert_chain(cert_file, key_file)
                self._server.socket = ctx.wrap_socket(self._server.socket, server_side=True)
            else:
                # Certificates missing — fall back to plain HTTP with a warning
                self._use_https = False
                print("[NetworkShare] WARNING: TLS certificates missing, falling back to HTTP")

        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        return self.url

    def stop(self):
        """Stop the server and clean up."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

        # Clean up stream tokens / decryptors
        with self._lock:
            self._stream_tokens.clear()
            self._cached_passwords.clear()

        self._port = 0

    @staticmethod
    def _get_local_ip() -> str:
        """Get the local LAN IP address."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"


# =============================================================================
#  EMBEDDED FRONTEND HTML
# =============================================================================

def _get_frontend_html() -> str:
    """Return the FULL web-edition UI (embedded from web/ frontend)."""
    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    idx_path = os.path.join(base_dir, "web", "templates", "index.html")
    try:
        with open(idx_path, "r", encoding="utf-8") as f:
            html = f.read()
        # Strip Flask template vars (?v={{ v }})
        import re as _re
        html = _re.sub(r"\?v=\{\{\s*v\s*\}\}", "", html)
        html = html.replace("{{ v }}", "")
        return html
    except Exception as e:
        return f"<html><body><h3>Web UI 加载失败: {e}</h3></body></html>"


def _get_player_html() -> str:
    """Return the media viewer page HTML with premium design and multi-format support."""
    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes, viewport-fit=cover">
<title>查看资源</title>
<style>
:root {
    --bg: #000;
    --surface: rgba(22, 22, 26, 0.85);
    --accent: #007aff;
    --border: rgba(255, 255, 255, 0.1);
    --text: #fff;
    --text-dim: rgba(255, 255, 255, 0.6);
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, sans-serif;
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

/* --- Header --- */
.viewer-header {
    display: flex;
    align-items: center;
    padding: 12px 16px;
    background: var(--surface);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-bottom: 1px solid var(--border);
    z-index: 100;
    position: absolute;
    top: 0; left: 0; right: 0;
    justify-content: space-between;
}

.header-left { display: flex; align-items: center; flex: 1; overflow: hidden; }
.back-btn { background: none; border: none; color: var(--accent); font-size: 20px; cursor: pointer; padding-right: 15px; }

.title {
    font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text);
}

.header-actions { display: flex; align-items: center; gap: 15px; }
.action-btn { background: none; border: none; font-size: 20px; cursor: pointer; color: var(--text); padding: 5px; opacity: 0.8; }
.action-btn:hover { opacity: 1; }

.ext-menu {
    position: absolute; top: 60px; right: 10px;
    background: rgba(30, 30, 30, 0.95);
    backdrop-filter: blur(20px);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 10px;
    display: none;
    flex-direction: column;
    gap: 8px;
    z-index: 200;
    min-width: 150px;
}
.ext-menu a {
    display: block; color: var(--text); text-decoration: none;
    padding: 10px; background: rgba(255,255,255,0.05);
    border-radius: 8px; font-size: 13px; text-align: center;
}
#imageContainer {
    width: 100%; height: 100%;
    display: none;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    touch-action: none;
}
#viewerImage {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    transition: transform 0.1s ease-out;
    transform-origin: center center;
    will-change: transform;
}

/* PDF */
#pdfContainer { width: 100%; height: 100%; display: none; }
iframe { width: 100%; height: 100%; border: none; background: #eee; }

/* Text */
#textContainer {
    width: 100%; height: 100%;
    display: none;
    padding: 24px;
    overflow-y: auto;
    font-family: "SF Mono", "Fira Code", monospace;
    font-size: 14px;
    line-height: 1.6;
    color: #ccc;
    background: #111;
}

/* VR Player (A-Frame) */
#vrContainer { position: absolute; top:0; left:0; width:100%; height:100%; display:none; }

/* --- Controls Overlay --- */
/* --- Header Actions --- */
.header-actions { display: flex; align-items: center; gap: 15px; }

/* --- Ext Menu --- */
.ext-menu {
    position: absolute; top: 60px; right: 10px;
    background: rgba(30, 30, 30, 0.95);
    backdrop-filter: blur(20px);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 10px;
    display: none;
    flex-direction: column;
    gap: 8px;
    z-index: 200;
    min-width: 150px;
}
.ext-menu a {
    display: block; color: var(--text); text-decoration: none;
    padding: 10px; background: rgba(255,255,255,0.05);
    border-radius: 8px; font-size: 13px; text-align: center;
}

/* Hide UI Logic */
.hide-ui .viewer-header { transform: translateY(-100%); }

/* --- Custom Player Controls (web-style) --- */
.player-controls {
    position: absolute;
    left: 0; right: 0; bottom: 0;
    background: linear-gradient(to top, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.5) 60%, transparent 100%);
    padding: 30px 16px 14px;
    z-index: 120;
    transition: opacity 0.3s ease, transform 0.3s ease;
}
.player-controls.hidden-controls {
    opacity: 0;
    pointer-events: none;
    transform: translateY(20px);
}
.pc-progress-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
}
.pc-time {
    font-size: 12px;
    color: rgba(255,255,255,0.85);
    font-variant-numeric: tabular-nums;
    min-width: 44px;
    text-align: center;
}
.pc-bar {
    flex: 1;
    -webkit-appearance: none;
    appearance: none;
    height: 4px;
    border-radius: 2px;
    background: rgba(255,255,255,0.25);
    outline: none;
    cursor: pointer;
}
.pc-bar::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 14px; height: 14px;
    border-radius: 50%;
    background: #fff;
    border: none;
    box-shadow: 0 1px 4px rgba(0,0,0,0.4);
}
.pc-buttons {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 18px;
}
.pc-btn {
    background: none;
    border: none;
    color: #fff;
    font-size: 20px;
    cursor: pointer;
    padding: 6px 8px;
    opacity: 0.85;
    line-height: 1;
    border-radius: 8px;
}
.pc-btn:hover { opacity: 1; background: rgba(255,255,255,0.12); }
.pc-btn-main { font-size: 28px; }

/* A-Frame specific */
.a-enter-vr { bottom: 120px !important; }
</style>
<script src="https://aframe.io/releases/1.6.0/aframe.min.js"></script>
</head>
<body onclick="toggleUI(event)">

<div class="viewer-header">
    <div class="header-left">
        <button class="back-btn" onclick="history.back()">❮</button>
        <div class="title" id="fileTitle">资源查看</div>
    </div>
    <div class="header-actions">
        <button class="action-btn" id="vrBtn" onclick="toggleVR()" style="display:none">🥽</button>
        <button class="action-btn" id="extBtn" onclick="toggleExtMenu()" style="display:none">🚀</button>
        <button class="action-btn" id="copyBtn" onclick="copyLink()">🔗</button>
    </div>
</div>

<div id="extMenu" class="ext-menu"></div>

<div class="content-area">
    <!-- Video Player -->
    <video id="videoPlayer" playsinline autoplay webkit-playsinline></video>

    <!-- Custom Player Controls (web-style) -->
    <div id="playerControls" class="player-controls">
        <div class="pc-progress-row">
            <span id="timeCurrent" class="pc-time">00:00</span>
            <input type="range" id="progressBar" class="pc-bar" min="0" max="1000" step="1" value="0">
            <span id="timeTotal" class="pc-time">00:00</span>
        </div>
        <div class="pc-buttons">
            <button class="pc-btn" id="btnPrev" title="上一个">⏮</button>
            <button class="pc-btn" id="btnRewind" title="后退10秒">⏪</button>
            <button class="pc-btn pc-btn-main" id="btnPlay" title="播放/暂停">▶</button>
            <button class="pc-btn" id="btnForward" title="前进10秒">⏩</button>
            <button class="pc-btn" id="btnNext" title="下一个">⏭</button>
            <button class="pc-btn" id="btnFullscreen" title="全屏">⛶</button>
        </div>
    </div>

    <!-- Image Viewer -->
    <div id="imageContainer">
        <img id="viewerImage" src="" alt="preview">
    </div>

    <!-- PDF Viewer -->
    <div id="pdfContainer">
        <iframe id="pdfFrame" src=""></iframe>
    </div>

    <!-- Text Viewer -->
    <div id="textContainer"></div>

    <!-- VR Container -->
    <div id="vrContainer"></div>
</div>

<!-- Controls Removed for Native Player -->

<script>
const params = new URLSearchParams(window.location.search);
const src = params.get("src") || "";
const name = params.get("name") || "未知文件";
const type = params.get("type") || "other";

document.getElementById("fileTitle").textContent = name;

// Mode State
const MODES = ["", "180", "360"];
let currentModeIdx = 0;
const video = document.getElementById("videoPlayer");
let scene = null;

function init() {
    setupUIByMode();
    resetUITimer();
    
    // Zoom Logic for Images
    initImageZoom();
    
    if (type === "video") {
        video.src = src;
        video.controls = false; // Custom controls (web-style)
        video.setAttribute("playsinline", ""); 
        setupExternalLinks();
        initPlayerControls();
    } else if (type === "image") {
        document.getElementById("viewerImage").src = src;
    } else if (type === "pdf") {
        // Add #view=FitH for scrolling
        document.getElementById("pdfFrame").src = src + "#view=FitH";
    } else if (type === "text") {
        loadText(src);
    }
}

// --- Web-style Player Controls ---
let playlist = [];
let currentIndex = -1;
let controlsTimer = null;

function initPlayerControls() {
    const bar = document.getElementById("progressBar");
    const controls = document.getElementById("playerControls");

    // Control buttons
    document.getElementById("btnPlay").addEventListener("click", togglePlay);
    document.getElementById("btnRewind").addEventListener("click", () => seekBy(-10));
    document.getElementById("btnForward").addEventListener("click", () => seekBy(10));
    document.getElementById("btnPrev").addEventListener("click", playPrev);
    document.getElementById("btnNext").addEventListener("click", playNext);
    document.getElementById("btnFullscreen").addEventListener("click", toggleFullscreen);

    // Seek bar
    bar.addEventListener("input", () => {
        if (video.duration) {
            video.currentTime = (bar.value / 1000) * video.duration;
        }
    });

    // Video events
    video.addEventListener("timeupdate", updateProgress);
    video.addEventListener("play", () => {
        document.getElementById("btnPlay").textContent = "⏸";
        showControls();
    });
    video.addEventListener("pause", () => {
        document.getElementById("btnPlay").textContent = "▶";
    });
    video.addEventListener("ended", playNext);
    video.addEventListener("loadedmetadata", () => {
        document.getElementById("timeTotal").textContent = formatTime(video.duration);
    });

    // Tap on video toggles controls
    video.addEventListener("click", toggleControlsVisibility);

    // Touch swipe to seek (100px = 10s)
    let touchStartX = 0, touchStartTime = 0;
    video.addEventListener("touchstart", (e) => {
        touchStartX = e.touches[0].clientX;
        touchStartTime = video.currentTime;
    }, { passive: true });
    video.addEventListener("touchend", (e) => {
        const deltaX = e.changedTouches[0].clientX - touchStartX;
        if (Math.abs(deltaX) > 50) {
            const seekAmount = (deltaX / 100) * 10;
            video.currentTime = Math.max(0, touchStartTime + seekAmount);
        }
    }, { passive: true });

    // Build playlist from the current directory for prev/next
    buildPlaylist();
    showControls();
}

function buildPlaylist() {
    const dir = params.get("dir") || "";
    fetch("/api/files?path=" + encodeURIComponent(dir)).then(r => r.json()).then(data => {
        if (!Array.isArray(data)) return;
        playlist = data.filter(f => !f.is_dir && (f.is_video || (f.name && /[.](mp4|mkv|mov|avi|webm|m4v)$/i.test(f.name))));
        const target = params.get("path") || "";
        currentIndex = playlist.findIndex(f => f.path === target);
    }).catch(() => {});
}

function togglePlay() {
    if (video.paused) { video.play().catch(() => {}); }
    else { video.pause(); }
}

function seekBy(seconds) {
    video.currentTime = Math.max(0, video.currentTime + seconds);
    showControls();
}

function playIndex(idx) {
    if (idx < 0 || idx >= playlist.length) return;
    const f = playlist[idx];
    const vsrc = "/" + f.path.replace(/^[/]+/, "");
    currentIndex = idx;
    video.src = vsrc;
    video.load();
    video.play().catch(() => {});
    document.getElementById("fileTitle").textContent = f.name;
}

function playPrev() {
    if (currentIndex > 0) playIndex(currentIndex - 1);
}

function playNext() {
    if (currentIndex < playlist.length - 1) playIndex(currentIndex + 1);
}

function toggleFullscreen() {
    if (!document.fullscreenElement) {
        (document.documentElement.requestFullscreen && document.documentElement.requestFullscreen()) ||
        (document.documentElement.webkitRequestFullscreen && document.documentElement.webkitRequestFullscreen());
    } else {
        document.exitFullscreen && document.exitFullscreen();
    }
}

function updateProgress() {
    if (!video.duration) return;
    document.getElementById("progressBar").value = (video.currentTime / video.duration) * 1000;
    document.getElementById("timeCurrent").textContent = formatTime(video.currentTime);
}

function formatTime(sec) {
    if (!sec || isNaN(sec)) return "00:00";
    sec = Math.floor(sec);
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h > 0) return h + ":" + String(m).padStart(2,"0") + ":" + String(s).padStart(2,"0");
    return String(m).padStart(2,"0") + ":" + String(s).padStart(2,"0");
}

function showControls() {
    document.getElementById("playerControls").classList.remove("hidden-controls");
    clearTimeout(controlsTimer);
    controlsTimer = setTimeout(() => {
        if (!video.paused) {
            document.getElementById("playerControls").classList.add("hidden-controls");
        }
    }, 4000);
}

function toggleControlsVisibility() {
    const controls = document.getElementById("playerControls");
    if (controls.classList.contains("hidden-controls")) showControls();
    else controls.classList.add("hidden-controls");
}

function setupUIByMode() {
    const vPlayer = document.getElementById("videoPlayer");
    const iCont = document.getElementById("imageContainer");
    const pCont = document.getElementById("pdfContainer");
    const tCont = document.getElementById("textContainer");

    vPlayer.style.display = type === "video" ? "block" : "none";
    document.getElementById("vrBtn").style.display = type === "video" ? "block" : "none";
    
    iCont.style.display = type === "image" ? "flex" : "none";
    pCont.style.display = type === "pdf" ? "block" : "none";
    tCont.style.display = type === "text" ? "block" : "none";
}

// --- Zoom Logic ---
function initImageZoom() {
    const img = document.getElementById("viewerImage");
    const container = document.getElementById("imageContainer");
    let scale = 1, lastScale = 1;
    let pointX = 0, pointY = 0, startX = 0, startY = 0, isPanning = false;

    // Scroll zoom
    container.addEventListener("wheel", (e) => {
        e.preventDefault();
        const delta = e.deltaY > 0 ? -0.1 : 0.1;
        scale = Math.min(Math.max(1, scale + delta), 5);
        applyTransform();
    }, { passive: false });

    // Touch Pinch
    let initialDist = null;
    container.addEventListener("touchstart", (e) => {
        if (e.touches.length === 2) {
            initialDist = Math.hypot(e.touches[0].pageX - e.touches[1].pageX, e.touches[0].pageY - e.touches[1].pageY);
        } else if (e.touches.length === 1) {
            isPanning = true;
            startX = e.touches[0].pageX - pointX;
            startY = e.touches[0].pageY - pointY;
        }
    });

    container.addEventListener("touchmove", (e) => {
        if (e.touches.length === 2 && initialDist) {
            e.preventDefault();
            const currDist = Math.hypot(e.touches[0].pageX - e.touches[1].pageX, e.touches[0].pageY - e.touches[1].pageY);
            const delta = (currDist / initialDist);
            scale = Math.min(Math.max(1, lastScale * delta), 5);
            applyTransform();
        } else if (e.touches.length === 1 && isPanning) {
            pointX = e.touches[0].pageX - startX;
            pointY = e.touches[0].pageY - startY;
            applyTransform();
        }
    }, { passive: false });

    container.addEventListener("touchend", () => {
        lastScale = scale;
        isPanning = false;
    });

    function applyTransform() {
        img.style.transform = `translate(${pointX}px, ${pointY}px) scale(${scale})`;
    }
}

// --- Text Loader ---
async function loadText(url) {
    const div = document.getElementById("textContainer");
    try {
        const r = await fetch(url);
        const txt = await r.text();
        div.textContent = txt;
    } catch(e) { div.textContent = "加载文本内容失败"; }
}

// --- External Links ---
function setupExternalLinks() {
    const absUrl = new URL(src, window.location.origin).href;
    const menu = document.getElementById("extMenu");
    menu.innerHTML = `
        <a href="vlc://${absUrl}">Open in VLC</a>
        <a href="nplayer-${absUrl}">Open in nPlayer</a>
        <a href="potplayer://${absUrl}">Open in PotPlayer</a>
    `;
    document.getElementById("extBtn").style.display = "block";
}

function toggleExtMenu() {
    const m = document.getElementById("extMenu");
    m.style.display = m.style.display === "none" ? "flex" : "none";
    if(m.style.display === "flex") {
        setTimeout(() => m.style.display = "none", 5000);
    }
}

function copyLink(e) {
    if (e) e.stopPropagation();
    const absUrl = new URL(src, window.location.origin).href;
    navigator.clipboard.writeText(absUrl).then(() => alert("链接已复制"));
}

function toggleVR(e) {
    if (e) e.stopPropagation();
    cycleVR(e);
}

function cycleVR(e) {
    if (e) e.stopPropagation();
    currentModeIdx = (currentModeIdx + 1) % MODES.length;
    const mode = MODES[currentModeIdx];
    const btn = document.getElementById("vrBtn");
    btn.textContent = mode === "180" ? "🥽180" : mode === "360" ? "🌐360" : "🥽";
    
    if (mode === "") {
        document.getElementById("vrContainer").style.display = "none";
        video.style.opacity = "1";
        if (scene) { scene.parentNode.removeChild(scene); scene = null; }
    } else {
        document.getElementById("vrContainer").style.display = "block";
        video.style.opacity = "0";
        initVR(mode);
    }
}

function initVR(mode) {
    const cont = document.getElementById("vrContainer");
    cont.innerHTML = `
        <a-scene embedded style="width:100%;height:100%;">
            <a-videosphere src="#videoPlayer" rotation="0 -90 0" 
                           theta-length="${mode==='180' ? 180 : 360}" 
                           repeat="${mode==='180' ? '0.5 1' : '1 1'}">
            </a-videosphere>
            <a-camera look-controls="reverseMouseDrag: true"></a-camera>
        </a-scene>
    `;
    scene = cont.querySelector("a-scene");
}

// --- UI Toggle ---
let uiTimer;
function toggleUI(e) {
    if (["BUTTON","INPUT","A"].includes(e.target.tagName)) return;
    document.body.classList.toggle("hide-ui");
    if (!document.body.classList.contains("hide-ui")) resetUITimer();
}
function resetUITimer() {
    clearTimeout(uiTimer);
    uiTimer = setTimeout(() => document.body.classList.add("hide-ui"), 5000);
}

init();
</script>
</body>
</html>'''
