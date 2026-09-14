"""
Thumbnail generation service for encrypted video files.
Supports encrypted thumbnail disk storage (.jpg.enc) for privacy.
"""
import os
import hashlib
import tempfile
import threading
from typing import Optional
from pathlib import PurePosixPath
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

from core.crypto_engine import StreamingDecryptor
from core.key_derivation import derive_key
from core.constants import SUPPORTED_VIDEO_FORMATS, SUPPORTED_IMAGE_FORMATS, NONCE_SIZE, TAG_SIZE, SALT_SIZE
from config import THUMB_DIR

THUMBNAIL_SIZE = (320, 180)  # 16:9 for mobile


def get_thumb_path(remote_path: str) -> tuple[str, str]:
    """Get plain and encrypted thumbnail file paths for a remote file."""
    file_hash = hashlib.md5(remote_path.encode('utf-8')).hexdigest()
    plain_path = os.path.join(THUMB_DIR, f"{file_hash}.jpg")
    enc_path = os.path.join(THUMB_DIR, f"{file_hash}.jpg.enc")
    return plain_path, enc_path


def has_thumbnail(remote_path: str) -> bool:
    """Check if thumbnail already exists (plain or encrypted)."""
    plain, enc = get_thumb_path(remote_path)
    return os.path.exists(plain) or os.path.exists(enc)


def save_encrypted_thumb(img_bytes: bytes, enc_path: str, password: str):
    """Encrypt and save thumbnail to disk."""
    salt = get_random_bytes(SALT_SIZE)
    key, _ = derive_key(password, salt)
    nonce = get_random_bytes(NONCE_SIZE)

    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(img_bytes)

    with open(enc_path, 'wb') as f:
        f.write(salt)
        f.write(nonce)
        f.write(tag)
        f.write(ciphertext)


def decrypt_thumb(enc_path: str, password: str) -> Optional[bytes]:
    """Decrypt an encrypted thumbnail from disk."""
    try:
        with open(enc_path, 'rb') as f:
            salt = f.read(SALT_SIZE)
            nonce = f.read(NONCE_SIZE)
            tag = f.read(TAG_SIZE)
            ciphertext = f.read()

        key, _ = derive_key(password, salt)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, tag)
    except Exception as e:
        print(f"Thumb decrypt error: {e}")
        return None


def generate_thumbnail(local_path: str, remote_path: str, password: str) -> bool:
    """
    Generate a thumbnail for an encrypted video file.
    Saves encrypted thumbnail (.jpg.enc) to disk.
    Returns True if generated or already exists.
    """
    plain_path, enc_path = get_thumb_path(remote_path)

    if os.path.exists(plain_path) or os.path.exists(enc_path):
        return True

    ext_lower = PurePosixPath(remote_path).suffix.lower()

    try:
        with StreamingDecryptor() as dec:
            try:
                dec.open(local_path, password)
            except ValueError:
                print(f"Incorrect password for {remote_path}")
                return False

            orig_ext = dec.get_original_extension().lower()

            img_bytes = None
            if orig_ext in SUPPORTED_VIDEO_FORMATS or (not orig_ext and ext_lower == '.evf'):
                img_bytes = _generate_video_thumb_bytes(dec, orig_ext or '.mp4')
            elif orig_ext in SUPPORTED_IMAGE_FORMATS:
                img_bytes = _generate_image_thumb_bytes(dec)
            elif orig_ext == '.pdf':
                img_bytes = _generate_pdf_thumb_bytes(dec)
            # Fallback: unknown formats → treat as video (common for obscure container extensions)
            if img_bytes is None and orig_ext != '':
                img_bytes = _generate_video_thumb_bytes(dec, '.mp4')

            if img_bytes:
                save_encrypted_thumb(img_bytes, enc_path, password)
                return True

    except Exception as e:
        print(f"Thumbnail generation error for {remote_path}: {e}")

    return False


def _generate_pdf_thumb_bytes(dec: StreamingDecryptor) -> Optional[bytes]:
    import fitz  # PyMuPDF
    import tempfile
    import cv2
    import numpy as np
    
    tf = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    temp_path = tf.name
    try:
        dec._seek_to_chunk(0)
        while True:
            chunk = dec.read_decrypted_chunk()
            if not chunk:
                break
            tf.write(chunk)
        tf.flush()
        tf.close()
        
        doc = fitz.open(temp_path)
        if len(doc) > 0:
            page = doc.load_page(0)
            # scale down to reduce memory
            pix = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5))
            
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            if pix.n == 4:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            elif pix.n == 1:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            elif pix.n == 3:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                
            # resize to thumbnail
            h, w = img.shape[:2]
            scale = min(320 / w, 320 / h)
            new_w, new_h = int(w * scale), int(h * scale)
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
            
            success, buffer = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if success:
                return buffer.tobytes()
        return None
    except Exception as e:
        print(f"PDF thumb error: {e}")
        return None
    finally:
        if os.path.exists(temp_path):
            try: os.unlink(temp_path)
            except: pass


def _generate_video_thumb_bytes(dec: StreamingDecryptor, orig_ext: str) -> Optional[bytes]:
    """Generate thumbnail bytes from encrypted video.
    Phase 1: sparse file (head 10MB + tail 50 chunks) — fast, works for ~95% of files.
    Phase 2: full decrypt (max 200MB) — fallback when sparse cv2 open fails."""
    import cv2

    temp_path = ''
    try:
        tf = tempfile.NamedTemporaryFile(suffix=orig_ext, delete=False)
        temp_path = tf.name

        total_size = dec.get_decrypted_size()
        if total_size > 0:
            tf.seek(total_size - 1)
            tf.write(b'\0')
            tf.flush()

        # Phase 1: Sparse file (10MB head + 50 chunks tail)
        written = 0
        head_limit = 10 * 1024 * 1024
        dec._seek_to_chunk(0)
        tf.seek(0)
        while written < head_limit:
            chunk = dec.read_decrypted_chunk()
            if not chunk:
                break
            tf.write(chunk)
            written += len(chunk)

        num_chunks = dec._header.num_chunks
        tail_start_chunk = max(0, num_chunks - 50)
        for idx in range(tail_start_chunk, num_chunks):
            chunk = dec.get_chunk_data(idx)
            if chunk:
                offset = idx * dec._header.chunk_size
                tf.seek(offset)
                tf.write(chunk)

        tf.flush()
        tf.close()

        cap = cv2.VideoCapture(temp_path)
        if cap.isOpened():
            result = _capture_video_frame(cap)
            cap.release()
            if result:
                return result

        # Phase 2: Fallback — full decrypt (max 200MB)
        print(f"Video thumb: sparse file failed for {dec._header.original_ext}, trying full decrypt...")
        os.unlink(temp_path)
        dec._seek_to_chunk(0)

        tf2 = tempfile.NamedTemporaryFile(suffix=orig_ext, delete=False)
        temp_path = tf2.name
        decrypted = 0
        max_decrypt = 200 * 1024 * 1024
        while decrypted < max_decrypt:
            chunk = dec.read_decrypted_chunk()
            if not chunk:
                break
            tf2.write(chunk)
            decrypted += len(chunk)
        tf2.flush()
        tf2.close()

        cap = cv2.VideoCapture(temp_path)
        if cap.isOpened():
            result = _capture_video_frame(cap)
            cap.release()
            if result:
                return result

    except Exception as e:
        print(f"Video thumb extraction error: {e}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

    return None


def _capture_video_frame(cap) -> Optional[bytes]:
    """Extract a frame from an open cv2 VideoCapture, encode as JPEG."""
    import cv2
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_candidates = [0]
    if total_frames > 20:
        frame_candidates = [
            min(100, total_frames // 20),
            min(300, total_frames // 10),
            0
        ]
    frame = None
    for target_frame in frame_candidates:
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, candidate = cap.read()
        if ret and candidate is not None and candidate.size > 0:
            frame = candidate
            break
    if frame is not None and frame.size > 0:
        frame = _resize_keep_aspect(frame, THUMBNAIL_SIZE)
        ret, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ret:
            return buf.tobytes()
    return None


def _generate_image_thumb_bytes(dec: StreamingDecryptor) -> Optional[bytes]:
    """Generate thumbnail bytes from encrypted image."""
    import cv2
    import numpy as np

    try:
        if dec.get_decrypted_size() > 200 * 1024 * 1024:
            return None  # Skip huge images

        data = bytearray()
        for chunk in dec.stream_all():
            data.extend(chunk)

        nparr = np.frombuffer(data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is not None:
            img = _resize_keep_aspect(img, THUMBNAIL_SIZE)
            ret, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ret:
                return buf.tobytes()

    except Exception as e:
        print(f"Image thumb extraction error: {e}")

    return None


def _resize_keep_aspect(img, target_size=(320, 180)):
    """Resize image keeping aspect ratio."""
    import cv2
    h, w = img.shape[:2]
    target_w, target_h = target_size
    scale = min(target_w / w, target_h / h)
    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
    return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)


# Background generation state: { "running": bool, "done": int, "total": int }
_bg_gen_state = {}
_bg_gen_lock = threading.Lock()


def register_thumbnail_routes(app):
    """Register thumbnail API routes (all auth-protected)."""
    from services.auth import login_required, decode_token, get_db
    from flask import g

    @app.route('/api/thumbnails/generate_async', methods=['POST'])
    @login_required
    def generate_thumbnails_async():
        """Start background thumbnail generation. Returns immediately. Poll /api/thumbnails/generate_status."""
        from services.storage_client import get_storage_client
        from flask import request as req

        data = req.get_json()
        paths = data.get('paths', [])
        password = data.get('password', '')

        if not paths or not password:
            return {'error': '路径和密码不能为空'}, 400

        db = get_db()
        settings = db.execute(
            'SELECT * FROM user_settings WHERE user_id = ?', (g.user_id,)
        ).fetchone()
        if not settings:
            return {'error': '请先配置存储地址'}, 400
        if not isinstance(settings, dict):
            settings = dict(settings)
        if not (settings.get('webdav_url') or settings.get('local_path')):
            return {'error': '请先配置存储地址'}, 400

        global _bg_gen_state
        key = str(g.user_id)
        with _bg_gen_lock:
            if _bg_gen_state.get(key, {}).get('running'):
                return {'status': 'already_running'}
            _bg_gen_state[key] = {'running': True, 'done': 0, 'total': len(paths)}

        webdav_url = settings.get('webdav_url') or ''
        webdav_username = settings.get('webdav_username') or ''
        webdav_password = settings.get('webdav_password') or ''
        storage_type = settings.get('storage_type') or 'nas'
        local_path = settings.get('local_path') or ''

        def _run():
            client = get_storage_client(webdav_url, webdav_username, webdav_password,
                                        storage_type=storage_type, local_path=local_path)
            for i, p in enumerate(paths):
                plain_path, enc_path = get_thumb_path(p)
                if os.path.exists(plain_path) or os.path.exists(enc_path):
                    with _bg_gen_lock:
                        _bg_gen_state[key]['done'] = i + 1
                    continue
                try:
                    source = client.get_file_object(p)
                    generate_thumbnail(source, p, password)
                except Exception:
                    pass
                with _bg_gen_lock:
                    _bg_gen_state[key]['done'] = i + 1
            with _bg_gen_lock:
                _bg_gen_state[key] = {'running': False, 'done': len(paths), 'total': len(paths)}

        threading.Thread(target=_run, daemon=True).start()
        return {'status': 'started'}

    @app.route('/api/thumbnails/generate_status', methods=['GET'])
    @login_required
    def generate_thumbnails_status():
        key = str(g.user_id)
        with _bg_gen_lock:
            state = dict(_bg_gen_state.get(key, {'running': False, 'done': 0, 'total': 0}))
        return state

    @app.route('/api/thumbnails/<file_hash>', methods=['GET'])
    def get_thumbnail(file_hash):
        from flask import send_from_directory, Response, request as req

        # <img src> can't send Authorization header, so accept token via query param
        token = req.args.get('token', '')
        auth_header = req.headers.get('Authorization', '')
        if not token and auth_header.startswith('Bearer '):
            token = auth_header[7:]
        if not token or not decode_token(token):
            return {'error': '未登录或 Token 已过期'}, 401

        plain_path = os.path.join(THUMB_DIR, f"{file_hash}.jpg")
        enc_path = os.path.join(THUMB_DIR, f"{file_hash}.jpg.enc")

        # 1. Plain thumbnail
        if os.path.exists(plain_path):
            return send_from_directory(THUMB_DIR, f"{file_hash}.jpg", mimetype='image/jpeg')

        # 2. Encrypted thumbnail
        if os.path.exists(enc_path):
            password = req.args.get('password', '') or req.headers.get('X-EVF-Password', '')
            if password:
                decrypted = decrypt_thumb(enc_path, password)
                if decrypted:
                    return Response(decrypted, mimetype='image/jpeg', headers={
                        'Cache-Control': 'private, max-age=86400'
                    })

        return {'error': 'Not found or incorrect password'}, 404

