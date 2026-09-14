"""
EVF (Encrypted Video File) format handler.

File format structure:
+------------------+
|  Magic: "EVF1"   |  4 bytes
+------------------+
|  Version         |  2 bytes (uint16, little-endian)
+------------------+
|  Salt            |  32 bytes
+------------------+
|  Chunk Size      |  4 bytes (uint32, little-endian)
+------------------+
|  Original Size   |  8 bytes (uint64, little-endian)
+------------------+
|  Original Ext    |  16 bytes (padded with nulls)
+------------------+
|  Num Chunks      |  4 bytes (uint32, little-endian)
+------------------+
|  Chunk Data      |  Variable (each chunk: 12-byte nonce + encrypted data + 16-byte tag)
+------------------+
"""

import struct
import os
from dataclasses import dataclass
from typing import BinaryIO
from utils.constants import EVF_MAGIC, EVF_VERSION, SALT_SIZE, NONCE_SIZE, TAG_SIZE


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
    
    # Header size calculation
    HEADER_SIZE = 4 + 2 + 32 + 4 + 8 + 16 + 4  # 70 bytes


def write_evf_header(
    file: BinaryIO,
    salt: bytes,
    chunk_size: int,
    original_size: int,
    original_ext: str,
    num_chunks: int
) -> None:
    """Write EVF header to file."""
    # Magic bytes
    file.write(EVF_MAGIC)
    
    # Version (2 bytes, little-endian)
    file.write(struct.pack('<H', EVF_VERSION))
    
    # Salt (32 bytes)
    file.write(salt)
    
    # Chunk size (4 bytes, little-endian)
    file.write(struct.pack('<I', chunk_size))
    
    # Original file size (8 bytes, little-endian)
    file.write(struct.pack('<Q', original_size))
    
    # Original extension (16 bytes, padded with nulls)
    ext_bytes = original_ext.encode('utf-8')[:16].ljust(16, b'\x00')
    file.write(ext_bytes)
    
    # Number of chunks (4 bytes, little-endian)
    file.write(struct.pack('<I', num_chunks))


def read_evf_header(file: BinaryIO) -> EVFHeader:
    """Read and parse EVF header from file."""
    # Magic bytes
    magic = file.read(4)
    if magic != EVF_MAGIC:
        raise ValueError("Not a valid EVF file")
    
    # Version
    version = struct.unpack('<H', file.read(2))[0]
    if version > EVF_VERSION:
        raise ValueError(f"Unsupported EVF version: {version}")
    
    # Salt
    salt = file.read(SALT_SIZE)
    
    # Chunk size
    chunk_size = struct.unpack('<I', file.read(4))[0]
    
    # Original size
    original_size = struct.unpack('<Q', file.read(8))[0]
    
    # Original extension
    ext_bytes = file.read(16)
    original_ext = ext_bytes.rstrip(b'\x00').decode('utf-8')
    
    # Number of chunks
    num_chunks = struct.unpack('<I', file.read(4))[0]
    
    return EVFHeader(
        magic=magic,
        version=version,
        salt=salt,
        chunk_size=chunk_size,
        original_size=original_size,
        original_ext=original_ext,
        num_chunks=num_chunks
    )


def is_evf_file(file_path: str) -> bool:
    """Check if a file is a valid EVF file by reading its magic bytes."""
    try:
        with open(file_path, 'rb') as f:
            magic = f.read(4)
            return magic == EVF_MAGIC
    except (IOError, OSError):
        return False


def get_chunk_offset(header: EVFHeader, chunk_index: int) -> int:
    """Calculate the file offset for a specific chunk."""
    # Each encrypted chunk has: nonce (12) + encrypted_data (chunk_size) + tag (16)
    encrypted_chunk_size = NONCE_SIZE + header.chunk_size + TAG_SIZE
    return EVFHeader.HEADER_SIZE + (chunk_index * encrypted_chunk_size)


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
    Format: [Image] [EVF] [Offset(8)] [Magic(11)]
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
