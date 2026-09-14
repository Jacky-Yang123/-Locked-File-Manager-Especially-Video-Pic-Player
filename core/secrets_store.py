"""
Secrets store — encrypt sensitive path strings (play history, bookmarks, share
config paths) so that metadata stays hidden even if the config files leak.

Two key schemes:
1. Machine key (random 32 bytes in a sidecar file) — used for library.json
2. Password-derived key (Argon2id) — used for share configs (path + password bound)

Encrypted string format:  enc:<nonce_hex>:<tag_hex>:<ciphertext_hex>
"""
import os
import hashlib
import secrets
from typing import Optional

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

from core.key_derivation import derive_key

PREFIX = "enc:"


def load_or_create_machine_key(key_path: str) -> Optional[bytes]:
    """Load a machine-level 32-byte random key from a sidecar file (create if missing).
    Returns None if the key file cannot be created (e.g. read-only dir)."""
    try:
        if os.path.exists(key_path):
            with open(key_path, 'rb') as f:
                key = f.read()
                if len(key) == 32:
                    return key
        # Create fresh key
        key = secrets.token_bytes(32)
        tmp = key_path + ".tmp"
        with open(tmp, 'wb') as f:
            f.write(key)
        os.replace(tmp, key_path)
        return key
    except Exception as e:
        print(f"[secrets_store] machine key unavailable: {e}")
        return None


def encrypt_with_key(key: bytes, plaintext: str) -> str:
    """Encrypt a string with AES-256-GCM. Returns 'enc:nonce:tag:ct' hex format."""
    nonce = get_random_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode('utf-8'))
    return f"{PREFIX}{nonce.hex()}:{tag.hex()}:{ciphertext.hex()}"


def decrypt_with_key(key: bytes, token: str) -> Optional[str]:
    """Decrypt a string produced by encrypt_with_key. Returns None on any failure."""
    if not token or not token.startswith(PREFIX):
        return None
    try:
        body = token[len(PREFIX):]
        nonce_hex, tag_hex, ct_hex = body.split(':', 2)
        nonce = bytes.fromhex(nonce_hex)
        tag = bytes.fromhex(tag_hex)
        ct = bytes.fromhex(ct_hex)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ct, tag).decode('utf-8')
    except Exception:
        return None


def encrypt_paths_with_machine_key(data: list, key: bytes) -> list:
    """Encrypt every string entry in a list of paths."""
    return [encrypt_with_key(key, p) for p in data]


def decrypt_paths_with_machine_key(data: list, key: bytes) -> list:
    """Decrypt a list of paths. Plain-text entries are kept (legacy compatibility)."""
    out = []
    for entry in data:
        if isinstance(entry, str) and entry.startswith(PREFIX):
            dec = decrypt_with_key(key, entry)
            if dec:
                out.append(dec)
        else:
            out.append(entry)  # legacy plaintext
    return out


def encrypt_bookmarks_with_machine_key(bookmarks: dict, key: bytes) -> dict:
    """Encrypt bookmark dict {path: [positions]}."""
    return {encrypt_with_key(key, p): v for p, v in bookmarks.items()}


def decrypt_bookmarks_with_machine_key(bookmarks: dict, key: bytes) -> dict:
    out = {}
    for p, v in bookmarks.items():
        if isinstance(p, str) and p.startswith(PREFIX):
            dec = decrypt_with_key(key, p)
            if dec:
                out[dec] = v
        else:
            out[p] = v
    return out


def encrypt_path_with_password(path: str, password: str) -> str:
    """Encrypt a share-config path bound to the share password (Argon2id-derived key).
    Format: encp:<salt>:<nonce>:<tag>:<ciphertext>  (salt included so decrypt uses same key)"""
    key, salt = derive_key(password)
    nonce = get_random_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(path.encode('utf-8'))
    return f"encp:{salt.hex()}:{nonce.hex()}:{tag.hex()}:{ciphertext.hex()}"


def decrypt_path_with_password(token: str, password: str) -> Optional[str]:
    """Decrypt a share-config path using the share password (salt comes from the token)."""
    if not token or not token.startswith("encp:"):
        return None
    try:
        salt_hex, nonce_hex, tag_hex, ct_hex = token[len("encp:"):].split(':', 3)
        salt = bytes.fromhex(salt_hex)
        key, _ = derive_key(password, salt)
        nonce = bytes.fromhex(nonce_hex)
        tag = bytes.fromhex(tag_hex)
        ct = bytes.fromhex(ct_hex)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ct, tag).decode('utf-8')
    except Exception:
        return None


def sha256_short(resource: str, length: int = 12) -> str:
    """Short stable hash of a resource string for logs (privacy)."""
    return hashlib.sha256(resource.encode('utf-8')).hexdigest()[:length]
