"""
Key derivation module using Argon2id for secure password-based key generation.
"""

from argon2.low_level import hash_secret_raw, Type
from utils.constants import (
    ARGON2_TIME_COST,
    ARGON2_MEMORY_COST,
    ARGON2_PARALLELISM,
    ARGON2_HASH_LEN,
    SALT_SIZE
)
import os


def derive_key(password: str, salt: bytes = None) -> tuple[bytes, bytes]:
    """
    Derive an encryption key from a password using Argon2id.
    
    Args:
        password: The user's password
        salt: Optional salt (generated if not provided)
    
    Returns:
        Tuple of (key, salt)
    """
    if salt is None:
        salt = os.urandom(SALT_SIZE)
    
    key = hash_secret_raw(
        secret=password.encode('utf-8'),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LEN,
        type=Type.ID
    )
    
    return key, salt


def verify_password(password: str, salt: bytes, expected_key: bytes) -> bool:
    """
    Verify if a password matches the expected key.
    
    Args:
        password: The password to verify
        salt: The salt used in key derivation
        expected_key: The expected derived key
    
    Returns:
        True if password is correct, False otherwise
    """
    derived_key, _ = derive_key(password, salt)
    return derived_key == expected_key
