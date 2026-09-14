"""
Streaming decryption service for web video playback.
Manages stream sessions and serves decrypted video via HTTP Range requests.
"""
import os
import uuid
import time
import threading
import hashlib
from typing import Optional, Dict
from flask import Response, request

from core.crypto_engine import StreamingDecryptor
from core.evf_format import read_evf_header, detect_mixed_file, EVFHeader
from core.constants import ENCRYPTED_EXTENSION, SUPPORTED_VIDEO_FORMATS
from config import STREAM_TIMEOUT


def _has_settings(settings) -> bool:
    """True when the user has configured either a NAS or a local folder."""
    if not settings:
        return False
    if not isinstance(settings, dict):
        settings = dict(settings)
    return bool(settings.get('webdav_url')) or bool(settings.get('local_path'))


def _client_for_settings(settings):
    """Build the storage client from a user_settings row (supports local + NAS)."""
    from services.storage_client import get_storage_client
    if not isinstance(settings, dict):
        settings = dict(settings)
    return get_storage_client(
        settings.get('webdav_url') or '',
        settings.get('webdav_username') or '',
        settings.get('webdav_password') or '',
        storage_type=settings.get('storage_type') or 'nas',
        local_path=settings.get('local_path') or ''
    )


class StreamSession:
    """A single streaming session for one file."""

    def __init__(self, local_path: str, password: str, remote_path: str = ''):
        self.session_id = str(uuid.uuid4())
        self.local_path = local_path
        self.remote_path = remote_path
        self.password = password
        self.decryptor = StreamingDecryptor()
        self.header: Optional[EVFHeader] = None
        self.created_at = time.time()
        self.last_access = time.time()
        self.lock = threading.Lock()

    def open(self) -> dict:
        """Open the encrypted file and verify password."""
        self.header = self.decryptor.open(self.local_path, self.password)
        return {
            'session_id': self.session_id,
            'original_ext': self.header.original_ext,
            'original_size': self.header.original_size,
            'duration_hint': None  # Could parse from moov atom later
        }

    def get_mime_type(self) -> str:
        """Get MIME type based on original extension."""
        ext = (self.header.original_ext or '.mp4').lower()
        mime_map = {
            '.mp4': 'video/mp4',
            '.mkv': 'video/x-matroska',
            '.webm': 'video/webm',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
            '.wmv': 'video/x-ms-wmv',
            '.flv': 'video/x-flv',
            '.m4v': 'video/mp4',
            '.ts': 'video/mp2t',
            '.3gp': 'video/3gpp',
            # Images
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.webp': 'image/webp',
            '.ico': 'image/x-icon',
            '.tiff': 'image/tiff',
            '.tif': 'image/tiff',
            # Documents
            '.pdf': 'application/pdf',
            # Text
            '.txt': 'text/plain; charset=utf-8',
            '.md': 'text/plain; charset=utf-8',
            '.log': 'text/plain; charset=utf-8',
            '.json': 'application/json; charset=utf-8',
            '.xml': 'text/xml; charset=utf-8',
            '.ini': 'text/plain; charset=utf-8',
            '.cfg': 'text/plain; charset=utf-8',
            '.conf': 'text/plain; charset=utf-8',
            '.py': 'text/plain; charset=utf-8',
            '.js': 'text/plain; charset=utf-8',
            '.css': 'text/plain; charset=utf-8',
            '.html': 'text/plain; charset=utf-8',
            '.srt': 'text/plain; charset=utf-8',
            '.ass': 'text/plain; charset=utf-8',
        }
        return mime_map.get(ext, 'application/octet-stream')

    def serve_range(self, range_header: str = None) -> Response:
        """Serve decrypted content with Range support."""
        self.last_access = time.time()
        total_size = self.header.original_size
        chunk_size = self.header.chunk_size

        start = 0
        end = total_size - 1

        if range_header:
            try:
                _, r = range_header.split('=')
                start_str, end_str = r.split('-')
                if start_str and end_str:
                    start = int(start_str)
                    end = int(end_str)
                elif start_str:
                    start = int(start_str)
                elif end_str:
                    suffix_len = int(end_str)
                    start = max(0, total_size - suffix_len)
            except Exception:
                pass

        if start >= total_size:
            return Response(status=416)

        end = min(end, total_size - 1)
        length = end - start + 1

        def generate():
            current_pos = start
            try:
                while current_pos <= end:
                    chunk_idx = current_pos // chunk_size
                    chunk_offset = current_pos % chunk_size

                    with self.lock:
                        chunk_data = self.decryptor.get_chunk_data(chunk_idx)

                    if not chunk_data:
                        break

                    available = len(chunk_data) - chunk_offset
                    send_amt = min(available, end - current_pos + 1)
                    if send_amt <= 0:
                        break

                    yield chunk_data[chunk_offset:chunk_offset + send_amt]
                    current_pos += send_amt
            except Exception:
                pass

        status = 206 if range_header else 200
        headers = {
            'Content-Type': self.get_mime_type(),
            'Accept-Ranges': 'bytes',
            'Content-Length': str(length),
            'Content-Range': f'bytes {start}-{end}/{total_size}',
            'Cache-Control': 'no-cache',
        }

        return Response(generate(), status=status, headers=headers)

    def close(self):
        """Clean up resources."""
        try:
            self.decryptor.close()
        except Exception:
            pass
        # Clean up cached PDF temp file
        temp_path = getattr(self, '_pdf_temp_path', None)
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass


class StreamManager:
    """Manages all active stream sessions."""

    def __init__(self):
        self._sessions: Dict[str, StreamSession] = {}
        self._lock = threading.Lock()
        # Start cleanup thread
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def create_session(self, local_path: str, password: str,
                       remote_path: str = '') -> StreamSession:
        """Create a new stream session."""
        session = StreamSession(local_path, password, remote_path)
        info = session.open()

        with self._lock:
            self._sessions[session.session_id] = session

        return session

    def get_session(self, session_id: str) -> Optional[StreamSession]:
        """Get an active session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.last_access = time.time()
            return session

    def close_session(self, session_id: str):
        """Close and remove a session."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session:
                session.close()

    def _cleanup_loop(self):
        """Periodically clean up expired sessions."""
        while True:
            time.sleep(60)
            now = time.time()
            expired = []

            with self._lock:
                for sid, session in self._sessions.items():
                    if now - session.last_access > STREAM_TIMEOUT:
                        expired.append(sid)

                for sid in expired:
                    session = self._sessions.pop(sid, None)
                    if session:
                        session.close()


# Global stream manager
stream_manager = StreamManager()


def register_stream_routes(app):
    """Register streaming API routes (all auth-protected)."""
    from services.auth import login_required, get_db
    from flask import g

    @app.route('/api/stream/open', methods=['POST'])
    @login_required
    def stream_open():
        data = request.get_json()
        remote_path = data.get('path', '')
        password = data.get('password', '')

        if not remote_path or not password:
            return {'error': '文件路径和密码不能为空'}, 400

        # Get user's WebDAV settings
        db = get_db()
        settings = db.execute(
            'SELECT * FROM user_settings WHERE user_id = ?', (g.user_id,)
        ).fetchone()

        if not _has_settings(settings):
            return {'error': '请先配置存储地址'}, 400

        client = _client_for_settings(settings)

        try:
            # If already cached locally, use local file for max speed
            cached_path = client.get_cached_path(remote_path)
            if os.path.exists(cached_path):
                source = cached_path
            else:
                # Direct stream (Instant - no download wait!)
                source = client.get_file_object(remote_path)
        except Exception as e:
            return {'error': f'连接存储失败: {e}'}, 500

        try:
            session = stream_manager.create_session(source, password, remote_path)
            return {
                'session_id': session.session_id,
                'original_ext': session.header.original_ext,
                'original_size': session.header.original_size,
                'mime_type': session.get_mime_type()
            }
        except ValueError as e:
            return {'error': f'密码错误: {e}'}, 403
        except Exception as e:
            return {'error': f'打开文件失败: {e}'}, 500

    @app.route('/api/stream/<session_id>/video', methods=['GET'])
    def stream_video(session_id):
        # <video src> can't send Authorization header, so accept token via query param
        from services.auth import decode_token
        token = request.args.get('token', '')
        auth_header = request.headers.get('Authorization', '')
        if not token and auth_header.startswith('Bearer '):
            token = auth_header[7:]
        if not token or not decode_token(token):
            return {'error': '未登录或 Token 已过期'}, 401

        session = stream_manager.get_session(session_id)
        if not session:
            return {'error': '流会话不存在或已过期'}, 404

        range_header = request.headers.get('Range')
        return session.serve_range(range_header)

    @app.route('/api/stream/<session_id>/close', methods=['POST'])
    @login_required
    def stream_close(session_id):
        stream_manager.close_session(session_id)
        return {'status': 'ok'}

    # ─── Document Preview (PDF page rendering via PyMuPDF) ───

    def _auth_request():
        """Accept token via query param (for <img>) or Authorization header."""
        from services.auth import decode_token
        token = request.args.get('token', '')
        auth_header = request.headers.get('Authorization', '')
        if not token and auth_header.startswith('Bearer '):
            token = auth_header[7:]
        return bool(token and decode_token(token))

    def _get_pdf_doc(session):
        """Decrypt full PDF to a temp file (cached on session) and open with fitz."""
        import fitz
        import tempfile
        if getattr(session, '_pdf_temp_path', None) and os.path.exists(session._pdf_temp_path):
            return fitz.open(session._pdf_temp_path)

        tf = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        temp_path = tf.name
        try:
            dec = session.decryptor
            with session.lock:
                dec._seek_to_chunk(0)
                while True:
                    chunk = dec.read_decrypted_chunk()
                    if not chunk:
                        break
                    tf.write(chunk)
            tf.flush()
            tf.close()
            session._pdf_temp_path = temp_path
            return fitz.open(temp_path)
        except Exception:
            try:
                tf.close()
                os.unlink(temp_path)
            except Exception:
                pass
            raise

    @app.route('/api/preview/<session_id>/pdf/info', methods=['GET'])
    def pdf_info(session_id):
        if not _auth_request():
            return {'error': '未登录或 Token 已过期'}, 401
        session = stream_manager.get_session(session_id)
        if not session:
            return {'error': '会话不存在或已过期'}, 404
        try:
            doc = _get_pdf_doc(session)
            page_count = len(doc)
            doc.close()
            return {'page_count': page_count}
        except Exception as e:
            return {'error': f'PDF 打开失败: {e}'}, 500

    @app.route('/api/preview/<session_id>/pdf/page/<int:page_num>', methods=['GET'])
    def pdf_page(session_id, page_num):
        if not _auth_request():
            return {'error': '未登录或 Token 已过期'}, 401
        session = stream_manager.get_session(session_id)
        if not session:
            return {'error': '会话不存在或已过期'}, 404
        try:
            import fitz
            doc = _get_pdf_doc(session)
            if page_num < 0 or page_num >= len(doc):
                doc.close()
                return {'error': '页码超出范围'}, 404
            page = doc.load_page(page_num)
            # Render at 2x for decent quality; frontend handles zoom
            zoom = float(request.args.get('zoom', 2.0))
            zoom = max(0.5, min(zoom, 4.0))
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            img_bytes = pix.tobytes('jpeg', jpg_quality=85)
            doc.close()
            return Response(img_bytes, mimetype='image/jpeg', headers={
                'Cache-Control': 'private, max-age=3600'
            })
        except Exception as e:
            return {'error': f'PDF 渲染失败: {e}'}, 500
