"""
Locked Video Player - Web Edition
Flask application entry point.
"""
import os
import sys
import hashlib
import sqlite3
import threading
import time
from urllib import parse
from pathlib import PurePosixPath

# Per-user scan progress: { user_id: { is_scanning, scanned_dirs, scanned_files, current_path, started_at, error } }
scan_progress = {}
_scan_progress_lock = threading.Lock()


def _get_scan_progress(user_id):
    """Get a user's scan progress (returns a copy, never None)."""
    with _scan_progress_lock:
        return dict(scan_progress.get(user_id, {
            'is_scanning': False,
            'scanned_dirs': 0,
            'scanned_files': 0,
            'current_path': '',
            'started_at': 0,
            'error': ''
        }))


def _update_scan_progress(user_id, **kwargs):
    """Update scan progress state for a specific user."""
    with _scan_progress_lock:
        if user_id not in scan_progress:
            scan_progress[user_id] = {
                'is_scanning': False,
                'scanned_dirs': 0,
                'scanned_files': 0,
                'current_path': '',
                'started_at': 0,
                'error': ''
            }
        scan_progress[user_id].update(kwargs)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, send_from_directory, request, jsonify, g
from flask_cors import CORS

from config import HOST, PORT, DATA_DIR, DB_PATH
from services.auth import init_db, register_auth_routes, close_db, login_required, decode_token, get_db
from services.stream_service import register_stream_routes
from services.thumbnail_service import register_thumbnail_routes

app = Flask(__name__, static_folder='static', template_folder='templates')
# Restrict CORS to local network and localhost only
CORS(app, origins=[
    r"http://localhost(:\d+)?",
    r"http://127\.0\.0\.1(:\d+)?",
    r"http://192\.168\.\d+\.\d+(:\d+)?",
    r"http://10\.\d+\.\d+\.\d+(:\d+)?",
    r"http://172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+(:\d+)?"
])

# Register teardown
app.teardown_appcontext(close_db)

# Register API routes
register_auth_routes(app)
register_stream_routes(app)
register_thumbnail_routes(app)


# ─── File Browsing API ───

import concurrent.futures


def _sync_index_to_db(db, user_id, files):
    """Upsert scanned files into file_index. Old entries are NOT deleted.
    This ensures a partial scan (e.g. SMB credit exhaustion) does not wipe the index.
    A full successful scan will overwrite all entries with fresh data."""
    for f in files:
        parent_path = '/'
        p = f['path'].strip('/')
        if '/' in p:
            parent_path = '/' + p.rsplit('/', 1)[0]
        db.execute('''
            INSERT OR REPLACE INTO file_index (user_id, parent_path, name, path, is_dir, size, mtime, ext)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            parent_path,
            f['name'],
            f['path'],
            1 if f['is_dir'] else 0,
            f.get('size', 0),
            f.get('mtime', '') or f.get('last_modified', ''),
            f.get('ext', '')
        ))
    db.commit()


def _do_scan_and_sync(client, db, user_id):
    """Scan storage (preferring fast Depth:infinity for WebDAV) and sync to DB
    with real-time progress updates."""

    try:
        # Count top-level dirs first for a rough total estimate
        try:
            top_items = client.list_dir('/')
            dir_count = sum(1 for it in top_items if it['is_dir'])
            file_count = sum(1 for it in top_items if not it['is_dir'])
            _update_scan_progress(
                user_id,
                scanned_dirs=1,
                scanned_files=file_count,
                current_path='/',
            )
        except Exception as top_err:
            print(f"[Scan] Top-level list failed: {top_err}")
            import traceback; traceback.print_exc()
            _update_scan_progress(user_id, error=f'连接NAS根目录失败: {top_err}')
            return

        # Phase 1: fast scan via list_dir_recursive (WebDAV Depth:infinity)
        try:
            print(f"[Scan] Starting recursive scan...")
            files = client.list_dir_recursive('/')
            print(f"[Scan] Recursive scan done, found {len(files)} files")
        except Exception as rec_err:
            print(f"[Scan] list_dir_recursive failed: {rec_err}, falling back to BFS")
            import traceback; traceback.print_exc()
            # Phase 1b: BFS fallback with progress
            files = []
            queue = ['/']
            visited = set()
            err_count = 0
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                _update_scan_progress(user_id, current_path=current, scanned_dirs=len(visited))
                try:
                    items = client.list_dir(current)
                    for item in items:
                        if item['is_dir']:
                            queue.append(item['path'])
                        else:
                            files.append(item)
                            _update_scan_progress(user_id, scanned_files=len(files))
                except Exception as e:
                    err_count += 1
                    if 'credits' in str(e).lower() and err_count <= 1:
                        print(f"[Scan] SMB credits exhausted, reduce load or increase NAS max credits")
                    elif err_count <= 3:
                        _update_scan_progress(user_id, error=f'扫描目录失败: {current}')
                        print(f"[Scan] Warning on {current}: {e}")

        if not files:
            _update_scan_progress(user_id, error='未发现任何文件，请检查 NAS 连接和路径')
            return

        # Phase 2: enrich metadata and sync to DB (show batch progress)
        total = len(files)
        batch_size = 100
        for i in range(0, total, batch_size):
            batch = files[i:i + batch_size]
            _update_scan_progress(
                user_id,
                current_path=f'写入数据库... {min(i + batch_size, total)}/{total}',
                scanned_files=min(i + batch_size, total),
            )

            # enrich first chunk (run full enrichment on first batch)
            if i == 0:
                enrich_files_with_metadata(files, client, db)

        _sync_index_to_db(db, user_id, files)
        print(f"[Scan] Synced {total} files to index for user {user_id}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        _update_scan_progress(user_id, error=str(e))
    finally:
        _update_scan_progress(user_id, is_scanning=False, current_path='')

def enrich_files_with_metadata(files, client, db):
    evf_files = [f for f in files if not f['is_dir'] and f['name'].endswith('.evf')]
    if not evf_files:
        return

    for f in evf_files:
        f['file_hash'] = hashlib.md5(f['path'].encode('utf-8')).hexdigest()

    hashes = [f['file_hash'] for f in evf_files]
    if not hashes:
        return
        
    placeholders = ','.join('?' * len(hashes))
    rows = db.execute(f'SELECT file_hash, original_ext FROM evf_metadata WHERE file_hash IN ({placeholders})', hashes).fetchall()
    cache = {row['file_hash']: row['original_ext'] for row in rows}

    missing_files = [f for f in evf_files if f['file_hash'] not in cache]
    
    if missing_files:
        def fetch_meta(f):
            ext = client.get_evf_original_ext(f['path'])
            return f['file_hash'], ext

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            results = list(executor.map(fetch_meta, missing_files))
        
        db.executemany('INSERT OR IGNORE INTO evf_metadata (file_hash, original_ext) VALUES (?, ?)', results)
        db.commit()

        for h, e in results:
            cache[h] = e

    for f in evf_files:
        f['original_ext'] = cache.get(f['file_hash'], '')

def _client_for(settings):
    """Build the storage client from a user_settings row (supports local + NAS)."""
    from services.storage_client import get_storage_client
    if not isinstance(settings, dict):
        settings = dict(settings)  # sqlite3.Row -> dict
    return get_storage_client(
        settings.get('webdav_url') or '',
        settings.get('webdav_username') or '',
        settings.get('webdav_password') or '',
        storage_type=settings.get('storage_type') or 'nas',
        local_path=settings.get('local_path') or ''
    )


def _has_storage(settings) -> bool:
    """True when the user has configured either a NAS or a local folder."""
    if not settings:
        return False
    if not isinstance(settings, dict):
        settings = dict(settings)
    return bool(settings.get('webdav_url')) or bool(settings.get('local_path'))

@app.route('/api/files/list', methods=['GET'])
@login_required
def list_files():
    """List files from WebDAV real-time."""
    path = request.args.get('path', '/')

    db = get_db()
    settings = db.execute(
        'SELECT * FROM user_settings WHERE user_id = ?', (g.user_id,)
    ).fetchone()

    if not _has_storage(settings):
        return jsonify({'error': '请先配置存储地址', 'files': []}), 400

    client = _client_for(settings)

    try:
        files = client.list_dir(path)
        for f in files:
            if not f['is_dir']:
                file_hash = hashlib.md5(f['path'].encode('utf-8')).hexdigest()
                f['file_hash'] = file_hash
                f['has_thumbnail'] = os.path.exists(
                    os.path.join(DATA_DIR, 'thumbnails', f'{file_hash}.jpg')
                )
                f['has_encrypted_thumbnail'] = os.path.exists(
                    os.path.join(DATA_DIR, 'thumbnails', f'{file_hash}.jpg.enc')
                )
        enrich_files_with_metadata(files, client, db)
        return jsonify({'files': files, 'current_path': path})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'files': []}), 500

@app.route('/api/files/list_all', methods=['GET'])
@login_required
def list_all_files():
    """List all files (excluding dirs) recursively from local SQLite file_index."""
    path = request.args.get('path', '/')
    db = get_db()
    
    if path == '/':
        like_path = '%'
    else:
        like_path = path + '/%'
        
    rows = db.execute(
        'SELECT * FROM file_index WHERE user_id = ? AND (path LIKE ? OR parent_path = ?) AND is_dir = 0 ORDER BY name ASC',
        (g.user_id, like_path, path)
    ).fetchall()
    
    user_progress = _get_scan_progress(g.user_id)
    if len(rows) == 0 and user_progress['is_scanning']:
        return jsonify({'scanning': True})
    
    files = []
    for r in rows:
        f = dict(r)
        f['is_dir'] = False
        file_hash = hashlib.md5(f['path'].encode('utf-8')).hexdigest()
        f['file_hash'] = file_hash
        f['has_thumbnail'] = os.path.exists(
            os.path.join(DATA_DIR, 'thumbnails', f'{file_hash}.jpg')
        )
        f['has_encrypted_thumbnail'] = os.path.exists(
            os.path.join(DATA_DIR, 'thumbnails', f'{file_hash}.jpg.enc')
        )
        ext_row = db.execute('SELECT original_ext FROM evf_metadata WHERE file_hash = ?', (file_hash,)).fetchone()
        if ext_row:
            f['original_ext'] = ext_row['original_ext']
        else:
            f['original_ext'] = ''
        files.append(f)
        
    return jsonify({'files': files, 'current_path': path})

@app.route('/api/files/scan', methods=['POST'])
@login_required
def scan_index():
    """Trigger an async NAS scan; returns immediately. Poll /api/files/scan_status for progress."""
    db = get_db()
    settings = db.execute(
        'SELECT * FROM user_settings WHERE user_id = ?', (g.user_id,)
    ).fetchone()

    if not _has_storage(settings):
        return jsonify({'error': '请先配置存储地址'}), 400

    # Avoid duplicate scans
    if _get_scan_progress(g.user_id)['is_scanning']:
        return jsonify({'status': 'already_scanning'})

    settings_dict = dict(settings)
    user_id = g.user_id

    def _async_scan():
        with app.app_context():
            thread_db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
            thread_db.row_factory = sqlite3.Row
            try:
                client = _client_for(settings_dict)
                _update_scan_progress(
                    user_id,
                    is_scanning=True,
                    scanned_dirs=0,
                    scanned_files=0,
                    current_path='/',
                    started_at=time.time(),
                    error=''
                )
                _do_scan_and_sync(client, thread_db, user_id)
            except Exception as e:
                import traceback
                traceback.print_exc()
                _update_scan_progress(user_id, error=str(e), is_scanning=False, current_path='')
            finally:
                thread_db.close()

    threading.Thread(target=_async_scan, daemon=True).start()
    return jsonify({'status': 'scan_started'})


def run_background_scanner():
    """Background thread to automatically update the media library index every 5 minutes."""
    time.sleep(3)  # Let SMB/WebDAV sessions stabilize before first scan
    while True:
        try:
            with app.app_context():
                db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
                db.row_factory = sqlite3.Row

                users = db.execute('SELECT * FROM user_settings').fetchall()
                for user in users:
                    if not _has_storage(user):
                        continue
                    _update_scan_progress(
                        user['user_id'],
                        is_scanning=True,
                        scanned_dirs=0,
                        scanned_files=0,
                        current_path='/',
                        started_at=time.time(),
                        error=''
                    )
                    try:
                        client = _client_for(user)
                        _do_scan_and_sync(client, db, user['user_id'])
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                        _update_scan_progress(user['user_id'], error=str(e), is_scanning=False, current_path='')
                db.close()
        except Exception:
            import traceback
            traceback.print_exc()
        time.sleep(300)  # Sleep AFTER the scan

threading.Thread(target=run_background_scanner, daemon=True).start()


@app.route('/api/files/download_encrypted', methods=['GET'])
@login_required
def download_encrypted():
    """Stream raw encrypted .evf file to browser for download."""
    path = request.args.get('path', '')
    if not path:
        return jsonify({'error': '路径不能为空'}), 400

    db = get_db()
    settings = db.execute(
        'SELECT * FROM user_settings WHERE user_id = ?', (g.user_id,)
    ).fetchone()

    if not _has_storage(settings):
        return jsonify({'error': '请先配置 WebDAV 地址'}), 400

    client = _client_for(settings)

    filename = os.path.basename(path)
    try:
        # Use file-object API (works for both WebDAV and SMB)
        file_obj = client.get_file_object(path)

        def generate():
            try:
                while True:
                    chunk = file_obj.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    file_obj.close()
                except Exception:
                    pass

        return app.response_class(
            generate(),
            mimetype='application/octet-stream',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        return jsonify({'error': f'下载失败: {e}'}), 500


@app.route('/api/files/download_decrypted', methods=['GET'])
@login_required
def download_decrypted():
    """Stream decrypted video file to browser for download."""
    path = request.args.get('path', '')
    # Password via header (avoids leaking into URL/logs/history)
    password = request.headers.get('X-EVF-Password', '')

    if not path or not password:
        return jsonify({'error': '路径和密码不能为空'}), 400

    db = get_db()
    settings = db.execute(
        'SELECT * FROM user_settings WHERE user_id = ?', (g.user_id,)
    ).fetchone()

    if not _has_storage(settings):
        return jsonify({'error': '请先配置 WebDAV 地址'}), 400

    client = _client_for(settings)

    try:
        source = client.get_file_object(path)
        from core.crypto_engine import StreamingDecryptor
        dec = StreamingDecryptor()
        header = dec.open(source, password)
        orig_ext = header.original_ext or '.mp4'
        base_name = os.path.basename(path)
        if base_name.endswith('.evf'):
            base_name = base_name[:-4]
        out_filename = base_name if base_name.endswith(orig_ext) else (base_name + orig_ext)

        def generate():
            try:
                for chunk in dec.stream_all():
                    yield chunk
            finally:
                dec.close()

        return app.response_class(
            generate(),
            mimetype='application/octet-stream',
            headers={
                'Content-Disposition': f'attachment; filename="{out_filename}"',
                'Content-Length': str(header.original_size)
            }
        )
    except ValueError:
        return jsonify({'error': '解密密码错误'}), 403
    except Exception as e:
        return jsonify({'error': f'解密失败: {e}'}, 500)


@app.route('/api/files/raw', methods=['GET'])
def raw_file():
    """Stream a non-encrypted file for inline preview (images, text, PDF)."""
    # <img>/iframe can't send Authorization header, so accept token via query param
    from services.auth import decode_token
    token = request.args.get('token', '')
    auth_header = request.headers.get('Authorization', '')
    if not token and auth_header.startswith('Bearer '):
        token = auth_header[7:]
    payload = decode_token(token) if token else None
    if not payload:
        return jsonify({'error': '未登录或 Token 已过期'}), 401
    g.user_id = payload['user_id']

    path = request.args.get('path', '')
    if not path:
        return jsonify({'error': '路径不能为空'}), 400

    db = get_db()
    settings = db.execute(
        'SELECT * FROM user_settings WHERE user_id = ?', (g.user_id,)
    ).fetchone()

    if not _has_storage(settings):
        return jsonify({'error': '请先配置存储地址'}), 400

    client = _client_for(settings)

    ext = os.path.splitext(path)[1].lower()
    mime_map = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
        '.gif': 'image/gif', '.bmp': 'image/bmp', '.webp': 'image/webp',
        '.pdf': 'application/pdf',
        '.txt': 'text/plain; charset=utf-8', '.md': 'text/plain; charset=utf-8',
        '.log': 'text/plain; charset=utf-8', '.json': 'application/json; charset=utf-8',
        '.xml': 'text/xml; charset=utf-8', '.py': 'text/plain; charset=utf-8',
        '.js': 'text/plain; charset=utf-8', '.css': 'text/plain; charset=utf-8',
        '.html': 'text/plain; charset=utf-8', '.ini': 'text/plain; charset=utf-8',
        '.srt': 'text/plain; charset=utf-8',
    }
    mimetype = mime_map.get(ext, 'application/octet-stream')

    try:
        # Use file-object API (works for both WebDAV and SMB)
        file_obj = client.get_file_object(path)

        def generate():
            try:
                while True:
                    chunk = file_obj.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    file_obj.close()
                except Exception:
                    pass

        return app.response_class(
            generate(),
            mimetype=mimetype,
            headers={'Content-Disposition': f'inline; filename="{os.path.basename(path)}"'}
        )
    except Exception as e:
        return jsonify({'error': f'读取失败: {e}'}), 500


@app.route('/api/files/test-connection', methods=['POST'])
@login_required
def test_webdav():
    """Test storage connection (WebDAV/SMB or local folder)."""
    body = request.get_json(silent=True) or {}
    url = body.get('url', '')
    username = body.get('username', '')
    password = body.get('password', '')
    storage_type = body.get('storage_type', '')
    local_path = body.get('local_path', '')

    if storage_type == 'local':
        if not local_path:
            return jsonify({'success': False, 'error': '请填写本地目录路径'})
        from services.storage_client import get_storage_client
        client = get_storage_client('', '', '', storage_type='local', local_path=local_path)
        ok = client.test_connection()
        return jsonify({
            'success': ok,
            'error': '' if ok else f'目录不可用或不存在: {local_path}'
        })

    if not url:
        return jsonify({'success': False, 'error': 'URL 不能为空'})

    from services.storage_client import get_storage_client
    client = get_storage_client(url, username, password)
    success = client.test_connection()

    return jsonify({
        'success': success,
        'error': '' if success else '无法连接到 WebDAV 服务器'
    })


@app.route('/api/files/scan_status', methods=['GET'])
@login_required
def get_scan_status():
    """Return current user's index scan progress."""
    return jsonify(_get_scan_progress(g.user_id))


from flask import render_template
import time


@app.after_request
def add_cache_control(response):
    """Disable HTML and static asset caching so browser always fetches updated app."""
    if request.path == '/' or request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


# ─── SPA Entry Point ───

@app.route('/')
def index():
    return render_template('index.html', v=int(time.time()))


@app.route('/favicon.ico')
def favicon():
    return '', 204


# ─── Main ───

if __name__ == '__main__':
    # Fix Windows console encoding
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    init_db()
    print(f"\n  [Locked Video Player - Web Edition]")
    print(f"  ------------------------------------")
    print(f"  Server: http://{HOST}:{PORT}")
    print(f"  Data:   {DATA_DIR}")
    print(f"  Press Ctrl+C to stop.\n")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)

