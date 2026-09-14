"""
EVF (Encrypted Video File) format handler.
Adapted from desktop version for web server use.
"""

import struct
import os
from dataclasses import dataclass
from typing import BinaryIO
from core.constants import EVF_MAGIC, EVF_VERSION, SALT_SIZE, NONCE_SIZE, TAG_SIZE


@dataclass
class EVFHeader:
    """EVF file header information."""
    magic: bytes
    version: int
    salt: bytes
    chunk_size: int
    original_size: int
    original_ext: str
    num_chunks: int

    HEADER_SIZE = 4 + 2 + 32 + 4 + 8 + 16 + 4  # 70 bytes


def read_evf_header(file: BinaryIO) -> EVFHeader:
    """Read and parse EVF header from file."""
    magic = file.read(4)
    if magic != EVF_MAGIC:
        raise ValueError("Not a valid EVF file")

    version = struct.unpack('<H', file.read(2))[0]
    if version > EVF_VERSION:
        raise ValueError(f"Unsupported EVF version: {version}")

    salt = file.read(SALT_SIZE)
    chunk_size = struct.unpack('<I', file.read(4))[0]
    original_size = struct.unpack('<Q', file.read(8))[0]
    ext_bytes = file.read(16)
    original_ext = ext_bytes.rstrip(b'\x00').decode('utf-8')
    num_chunks = struct.unpack('<I', file.read(4))[0]

    return EVFHeader(
        magic=magic, version=version, salt=salt,
        chunk_size=chunk_size, original_size=original_size,
        original_ext=original_ext, num_chunks=num_chunks
    )


def is_evf_file(file_path: str) -> bool:
    """Check if a file is a valid EVF file by reading its magic bytes."""
    try:
        with open(file_path, 'rb') as f:
            magic = f.read(4)
            return magic == EVF_MAGIC
    except (IOError, OSError):
        return False


def get_encrypted_chunk_size(original_chunk_size: int) -> int:
    """Get the size of an encrypted chunk including nonce and tag."""
    return NONCE_SIZE + original_chunk_size + TAG_SIZE


# --- Mixed Format Support ---
MIXED_MAGIC = b"ALOCKED_MIX"
MIXED_FOOTER_SIZE = 19  # 8 bytes offset + 11 bytes magic


def detect_mixed_file(file_path: str) -> int:
    """
    Check if file is a mixed EVF/Image file.
    Returns the offset of EVF data start if found, else -1.
    """
    try:
        size = os.path.getsize(file_path)
        if size < MIXED_FOOTER_SIZE + EVFHeader.HEADER_SIZE:
            return -1

        with open(file_path, 'rb') as f:
            f.seek(-11, os.SEEK_END)
            magic = f.read(11)
            if magic != MIXED_MAGIC:
                return -1

            f.seek(-MIXED_FOOTER_SIZE, os.SEEK_END)
            offset_bytes = f.read(8)
            offset = struct.unpack('<Q', offset_bytes)[0]

            if offset >= size or offset < 0:
                return -1

            return offset
    except Exception:
        return -1
