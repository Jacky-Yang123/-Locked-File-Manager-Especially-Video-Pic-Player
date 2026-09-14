"""
Key derivation module using Argon2id for secure password-based key generation.
Adapted from desktop version.
"""

from argon2.low_level import hash_secret_raw, Type
from core.constants import (
    ARGON2_TIME_COST, ARGON2_MEMORY_COST,
    ARGON2_PARALLELISM, ARGON2_HASH_LEN, SALT_SIZE
)
import os


def derive_key(password: str, salt: bytes = None) -> tuple:
    """Derive an encryption key from a password using Argon2id."""
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
