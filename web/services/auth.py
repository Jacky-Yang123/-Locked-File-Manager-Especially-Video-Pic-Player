"""
User authentication service with SQLite + JWT.
"""
import sqlite3
import bcrypt
import jwt
import time
import os
from functools import wraps
from flask import request, jsonify, g

from config import DB_PATH, JWT_SECRET, JWT_EXPIRY_HOURS


def get_db():
    """Get a database connection for the current request."""
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    """Close the database connection."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """Initialize database tables."""
    db = sqlite3.connect(DB_PATH)
    db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at REAL DEFAULT (strftime('%s', 'now'))
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS evf_metadata (
            file_hash TEXT PRIMARY KEY,
            original_ext TEXT
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS file_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            parent_path TEXT,
            name TEXT,
            path TEXT,
            is_dir BOOLEAN,
            size INTEGER,
            mtime TEXT,
            ext TEXT,
            UNIQUE(user_id, path)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            webdav_url TEXT DEFAULT '',
            webdav_username TEXT DEFAULT '',
            webdav_password TEXT DEFAULT '',
            scan_path TEXT DEFAULT '',
            storage_type TEXT DEFAULT 'nas',
            local_path TEXT DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    # Backfill new columns for databases created before this version
    try:
        db.execute("ALTER TABLE user_settings ADD COLUMN storage_type TEXT DEFAULT 'nas'")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        db.execute("ALTER TABLE user_settings ADD COLUMN local_path TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    db.commit()
    db.close()


def create_token(user_id: int, username: str) -> str:
    """Create a JWT token."""
    payload = {
        'user_id': user_id,
        'username': username,
        'exp': time.time() + JWT_EXPIRY_HOURS * 3600,
        'iat': time.time()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def login_required(f):
    """Decorator to require authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': '未登录'}), 401

        token = auth_header[7:]
        payload = decode_token(token)
        if not payload:
            return jsonify({'error': 'Token 已过期，请重新登录'}), 401

        g.user_id = payload['user_id']
        g.username = payload['username']
        return f(*args, **kwargs)
    return decorated


def register_auth_routes(app):
    """Register authentication API routes."""

    @app.route('/api/auth/register', methods=['POST'])
    def register():
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')

        if not username or not password:
            return jsonify({'error': '用户名和密码不能为空'}), 400
        if len(username) < 2:
            return jsonify({'error': '用户名至少 2 个字符'}), 400
        if len(password) < 4:
            return jsonify({'error': '密码至少 4 个字符'}), 400

        db = get_db()
        existing = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if existing:
            return jsonify({'error': '用户名已存在'}), 409

        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor = db.execute(
            'INSERT INTO users (username, password_hash) VALUES (?, ?)',
            (username, password_hash)
        )
        user_id = cursor.lastrowid
        db.execute('INSERT INTO user_settings (user_id) VALUES (?)', (user_id,))
        db.commit()

        token = create_token(user_id, username)
        return jsonify({'token': token, 'username': username}), 201

    @app.route('/api/auth/login', methods=['POST'])
    def login():
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')

        if not username or not password:
            return jsonify({'error': '用户名和密码不能为空'}), 400

        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if not user:
            return jsonify({'error': '用户名或密码错误'}), 401

        if not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            return jsonify({'error': '用户名或密码错误'}), 401

        token = create_token(user['id'], user['username'])
        return jsonify({'token': token, 'username': user['username']})

    @app.route('/api/auth/me', methods=['GET'])
    @login_required
    def me():
        return jsonify({'user_id': g.user_id, 'username': g.username})

    @app.route('/api/auth/account', methods=['PUT'])
    @login_required
    def update_account():
        data = request.get_json()
        new_username = data.get('username', '').strip()
        new_password = data.get('password', '')

        if not new_username:
            return jsonify({'error': '用户名不能为空'}), 400

        db = get_db()
        
        # Check if username exists and is not the current user
        existing = db.execute('SELECT id FROM users WHERE username = ? AND id != ?', (new_username, g.user_id)).fetchone()
        if existing:
            return jsonify({'error': '该用户名已被占用'}), 409

        if new_password:
            if len(new_password) < 4:
                return jsonify({'error': '密码至少 4 个字符'}), 400
            password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            db.execute('UPDATE users SET username = ?, password_hash = ? WHERE id = ?', (new_username, password_hash, g.user_id))
        else:
            db.execute('UPDATE users SET username = ? WHERE id = ?', (new_username, g.user_id))
            
        db.commit()
        
        # Create a new token with the updated username
        token = create_token(g.user_id, new_username)
        return jsonify({'status': 'ok', 'token': token, 'username': new_username})

    @app.route('/api/settings', methods=['GET'])
    @login_required
    def get_settings():
        db = get_db()
        settings = db.execute(
            'SELECT * FROM user_settings WHERE user_id = ?', (g.user_id,)
        ).fetchone()
        if not settings:
            return jsonify({})
        return jsonify({
            'webdav_url': settings['webdav_url'],
            'webdav_username': settings['webdav_username'],
            'webdav_password': settings['webdav_password'],
            'scan_path': settings['scan_path'],
            'storage_type': settings.get('storage_type', 'nas'),
            'local_path': settings.get('local_path', '')
        })

    @app.route('/api/settings', methods=['PUT'])
    @login_required
    def update_settings():
        data = request.get_json()
        db = get_db()

        fields = []
        values = []
        for key in ['webdav_url', 'webdav_username', 'webdav_password', 'scan_path',
                    'storage_type', 'local_path']:
            if key in data:
                fields.append(f'{key} = ?')
                values.append(data[key])

        if fields:
            values.append(g.user_id)
            db.execute(
                f'UPDATE user_settings SET {", ".join(fields)} WHERE user_id = ?',
                values
            )
            db.commit()

        return jsonify({'status': 'ok'})
