"""
Application configuration.
"""
import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
THUMB_DIR = os.path.join(DATA_DIR, 'thumbnails')
CACHE_DIR = os.path.join(DATA_DIR, 'cache')
DB_PATH = os.path.join(DATA_DIR, 'app.db')

# Ensure directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# Server
HOST = '0.0.0.0'
PORT = 8080

# JWT
JWT_SECRET_FILE = os.path.join(DATA_DIR, '.jwt_secret')

def get_jwt_secret():
    """Get or generate a persistent JWT secret."""
    if os.path.exists(JWT_SECRET_FILE):
        with open(JWT_SECRET_FILE, 'r') as f:
            return f.read().strip()
    secret = secrets.token_hex(32)
    with open(JWT_SECRET_FILE, 'w') as f:
        f.write(secret)
    return secret

JWT_SECRET = get_jwt_secret()
JWT_EXPIRY_HOURS = 168  # 7 days

# Stream session timeout (seconds)
STREAM_TIMEOUT = 600  # 10 minutes idle -> cleanup
