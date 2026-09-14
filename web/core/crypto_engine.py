"""
Streaming decryptor for encrypted video files.
Adapted from desktop version - removed all PyQt6/GUI dependencies.
"""

import threading
from typing import Optional
from Crypto.Cipher import AES

from core.key_derivation import derive_key
from core.evf_format import (
    read_evf_header, EVFHeader,
    get_encrypted_chunk_size, detect_mixed_file
)
from core.constants import NONCE_SIZE, TAG_SIZE


class StreamingDecryptor:
    """
    Provides streaming decryption for encrypted video playback.
    Decrypts chunks on-the-fly without storing decrypted data on disk.
    """

    def __init__(self):
        self._file = None
        self._header: Optional[EVFHeader] = None
        self._key: Optional[bytes] = None
        self._current_chunk = 0
        self._start_offset = 0
        self._lock = threading.Lock()

    def open(self, source, password: str) -> EVFHeader:
        """
        Open an encrypted file for streaming decryption.
        Args:
            source: Path (str) or File-like object
            password: Decryption password
        """
        if isinstance(source, str):
            offset = detect_mixed_file(source)
            self._start_offset = offset if offset != -1 else 0
            self._file = open(source, 'rb')
            self._file.seek(self._start_offset)
        else:
            self._file = source
            self._start_offset = 0

        self._header = read_evf_header(self._file)
        self._key, _ = derive_key(password, self._header.salt)

        # Verify password by trying to decrypt first chunk
        try:
            first_chunk = self._read_encrypted_chunk(0)
            if first_chunk:
                self._decrypt_chunk(first_chunk)
        except Exception:
            self.close()
            raise ValueError("Incorrect password")

        self._current_chunk = 0
        self._seek_to_chunk(0)
        return self._header

    def _read_encrypted_chunk(self, chunk_index: int) -> Optional[bytes]:
        """Read an encrypted chunk from the file."""
        if chunk_index >= self._header.num_chunks:
            return None

        if chunk_index == self._header.num_chunks - 1:
            remaining = self._header.original_size % self._header.chunk_size
            if remaining == 0:
                remaining = self._header.chunk_size
            encrypted_size = NONCE_SIZE + remaining + TAG_SIZE
        else:
            encrypted_size = get_encrypted_chunk_size(self._header.chunk_size)

        return self._file.read(encrypted_size)

    def _decrypt_chunk(self, chunk_data: bytes) -> bytes:
        """Decrypt a chunk of data."""
        nonce = chunk_data[:NONCE_SIZE]
        tag = chunk_data[-TAG_SIZE:]
        ciphertext = chunk_data[NONCE_SIZE:-TAG_SIZE]

        cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, tag)

    def _seek_to_chunk(self, chunk_index: int) -> None:
        """Seek to a specific chunk in the file."""
        enc_chunk_size = get_encrypted_chunk_size(self._header.chunk_size)
        offset = self._start_offset + EVFHeader.HEADER_SIZE + (chunk_index * enc_chunk_size)
        self._file.seek(offset)
        self._current_chunk = chunk_index

    def get_chunk_data(self, chunk_index: int) -> Optional[bytes]:
        """Random access: Read and decrypt a specific chunk."""
        with self._lock:
            if chunk_index >= self._header.num_chunks:
                return None
            self._seek_to_chunk(chunk_index)
            return self.read_decrypted_chunk()

    def read_decrypted_chunk(self) -> Optional[bytes]:
        """Read and decrypt the next chunk."""
        chunk_data = self._read_encrypted_chunk(self._current_chunk)
        if chunk_data is None:
            return None
        decrypted = self._decrypt_chunk(chunk_data)
        self._current_chunk += 1
        return decrypted

    def stream_all(self):
        """Generator that yields all decrypted chunks."""
        self._seek_to_chunk(0)
        while True:
            chunk = self.read_decrypted_chunk()
            if chunk is None:
                break
            yield chunk

    def get_decrypted_size(self) -> int:
        return self._header.original_size if self._header else 0

    def get_original_extension(self) -> str:
        return self._header.original_ext if self._header else ""

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None
        self._key = None
        self._header = None
        self._current_chunk = 0
        self._start_offset = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
