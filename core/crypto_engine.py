"""
Encryption engine for video files using AES-256-GCM.
Provides secure encryption and decryption with chunked processing.
"""

import os
from pathlib import Path
from typing import Callable, Optional, Generator
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

from core.key_derivation import derive_key
from core.evf_format import (
    write_evf_header,
    read_evf_header,
    EVFHeader,
    get_encrypted_chunk_size,
    EVFHeader,
    get_encrypted_chunk_size,
    detect_mixed_file
)
from utils.constants import CHUNK_SIZE, NONCE_SIZE, TAG_SIZE
import threading


class EncryptionEngine:
    """
    Handles encryption and decryption of video files using AES-256-GCM.
    """
    
    def __init__(self):
        self._key: Optional[bytes] = None
        self._salt: Optional[bytes] = None
    
    def encrypt_file(
        self,
        input_path: str,
        output_path: str,
        password: str,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        """
        Encrypt a video file.
        
        Args:
            input_path: Path to the input video file
            output_path: Path for the encrypted output file
            password: Encryption password
            progress_callback: Optional callback(current_bytes, total_bytes)
        
        Returns:
            True if encryption successful, False otherwise
        """
        try:
            input_file = Path(input_path)
            if not input_file.exists():
                raise FileNotFoundError(f"Input file not found: {input_path}")
            
            original_size = input_file.stat().st_size
            original_ext = input_file.suffix
            
            # Derive encryption key
            key, salt = derive_key(password)
            
            # Calculate number of chunks
            num_chunks = (original_size + CHUNK_SIZE - 1) // CHUNK_SIZE
            
            with open(input_path, 'rb') as infile, open(output_path, 'wb') as outfile:
                # Write header
                write_evf_header(
                    outfile,
                    salt=salt,
                    chunk_size=CHUNK_SIZE,
                    original_size=original_size,
                    original_ext=original_ext,
                    num_chunks=num_chunks
                )
                
                # Encrypt chunks
                bytes_processed = 0
                while True:
                    chunk = infile.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    
                    # Generate unique nonce for each chunk
                    nonce = get_random_bytes(NONCE_SIZE)
                    
                    # Encrypt chunk
                    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
                    ciphertext, tag = cipher.encrypt_and_digest(chunk)
                    
                    # Write: nonce + ciphertext + tag
                    outfile.write(nonce)
                    outfile.write(ciphertext)
                    outfile.write(tag)
                    
                    bytes_processed += len(chunk)
                    if progress_callback:
                        progress_callback(bytes_processed, original_size)
            
            return True
            
        except Exception as e:
            # Clean up partial output on error
            if Path(output_path).exists():
                Path(output_path).unlink()
            raise e
    
    def decrypt_chunk(self, chunk_data: bytes, key: bytes) -> bytes:
        """
        Decrypt a single chunk of data.
        
        Args:
            chunk_data: Encrypted chunk data (nonce + ciphertext + tag)
            key: Decryption key
        
        Returns:
            Decrypted data
        """
        nonce = chunk_data[:NONCE_SIZE]
        tag = chunk_data[-TAG_SIZE:]
        ciphertext = chunk_data[NONCE_SIZE:-TAG_SIZE]
        
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        
        return plaintext
    
    def encrypt_folder(
        self,
        folder_path: str,
        output_folder: str,
        password: str,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> list[tuple[str, bool, str]]:
        """
        Encrypt all video files in a folder.
        
        Args:
            folder_path: Path to folder containing videos
            output_folder: Path for encrypted output files
            password: Encryption password
            progress_callback: Optional callback(filename, current_file, total_files)
        
        Returns:
            List of (filename, success, error_message) tuples
        """
        from utils.file_utils import get_video_files, get_encrypted_output_path, ensure_dir
        
        video_files = get_video_files(folder_path)
        if not video_files:
            return []
        
        ensure_dir(output_folder)
        results = []
        
        for i, video_path in enumerate(video_files):
            filename = Path(video_path).name
            if progress_callback:
                progress_callback(filename, i + 1, len(video_files))
            
            try:
                output_path = get_encrypted_output_path(video_path, output_folder)
                self.encrypt_file(video_path, output_path, password)
                results.append((filename, True, ""))
            except Exception as e:
                results.append((filename, False, str(e)))
        
        return results
    
    def decrypt_file(
        self,
        input_path: str,
        output_path: str,
        password: str,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        """
        Decrypt a video file.
        
        Args:
            input_path: Path to the encrypted video file
            output_path: Path for the decrypted output file
            password: Decryption password
            progress_callback: Optional callback(current_bytes, total_bytes)
        
        Returns:
            True if decryption successful, False otherwise
        """
        try:
            input_file = Path(input_path)
            if not input_file.exists():
                raise FileNotFoundError(f"Input file not found: {input_path}")
            
            # Check mixed
            offset = detect_mixed_file(input_path)
            start_pos = 0 if offset == -1 else offset

            with open(input_path, 'rb') as infile:
                infile.seek(start_pos)
                header = read_evf_header(infile)
                
                # Derive key
                key, _ = derive_key(password, header.salt)
                
                # Check password with first chunk
                try:
                    # Save position
                    pos = infile.tell()
                    
                    encrypted_size = get_encrypted_chunk_size(header.chunk_size)
                    # Last chunk handling for size check would be complex here, 
                    # but we can just try to read one chunk.
                    # If file is empty (just header), we succeed (nothing to decrypt).
                    if header.num_chunks > 0:
                        # For verification we just read enough for one full chunk or less
                        # Actually we need exact chunk boundary to decrypt correctly.
                        # However, for 'decrypt_file', we iterate all chunks anyway.
                        # The stream_all loop below handles decryption and will fail on tag mismatch.
                        pass
                except Exception:
                    pass
                
                with open(output_path, 'wb') as outfile:
                    infile.seek(start_pos + header.HEADER_SIZE)
                    
                    for i in range(header.num_chunks):
                        # Determine chunk size
                        if i == header.num_chunks - 1:
                            remaining = header.original_size % header.chunk_size
                            if remaining == 0:
                                remaining = header.chunk_size
                            chunk_enc_size = NONCE_SIZE + remaining + TAG_SIZE
                        else:
                            chunk_enc_size = get_encrypted_chunk_size(header.chunk_size)
                        
                        chunk_data = infile.read(chunk_enc_size)
                        if not chunk_data:
                            break # Should not happen if header is correct
                            
                        # Decrypt
                        try:
                            plaintext = self.decrypt_chunk(chunk_data, key)
                        except ValueError:
                            # Tag mismatch usually means wrong password
                            raise ValueError("Incorrect password or corrupted file")
                            
                        outfile.write(plaintext)
                        
                        if progress_callback:
                            current_output_size = outfile.tell()
                            progress_callback(current_output_size, header.original_size)
                            
            return True
            
        except Exception as e:
            # Clean up
            if Path(output_path).exists():
                Path(output_path).unlink()
            raise e

    def decrypt_folder(
        self,
        folder_path: str,
        output_folder: str,
        password: str,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> list[tuple[str, bool, str]]:
        """
        Decrypt all .evf files in a folder.
        """
        from utils.file_utils import get_encrypted_files, ensure_dir
        
        enc_files = get_encrypted_files(folder_path)
        if not enc_files:
            return []
            
        ensure_dir(output_folder)
        results = []
        
        for i, file_path in enumerate(enc_files):
            filename = Path(file_path).name
            if progress_callback:
                progress_callback(filename, i + 1, len(enc_files))
            
            try:
                # Determine output filename. 
                # We need to peek header to get original extension? 
                # Or just allow decrypt_file to handle it?
                # decrypt_file takes output_path.
                # Let's peek header here to generate correct output path.
                with open(file_path, 'rb') as f:
                    header = read_evf_header(f)
                    
                original_name = Path(file_path).stem # remove .evf?
                # Actually evf file is name.mp4.evf usually?
                # Let's check how we named them.
                # encrypt_file: output_path passed in.
                # get_encrypted_output_path: adds .evf
                # So original name is usually filename w/o .evf
                
                # But safer to use header's original_ext
                base_name = Path(file_path).stem # "video.mp4" (if file was video.mp4.evf)
                # If file was just "video.evf", stem is "video".
                # We should append original_ext if not present?
                
                out_name = base_name
                if not out_name.endswith(header.original_ext):
                    # If stem doesn't have extension, add it
                     # Be careful if base_name already has it.
                     pass 
                
                # Actually simplest is:
                # If input is "video.mp4.evf", output should be "video.mp4" in output dir.
                if filename.endswith(".evf"):
                    out_name = filename[:-4]
                else:
                    out_name = filename + "_decrypted" + header.original_ext
                    
                output_path = str(Path(output_folder) / out_name)
                
                self.decrypt_file(file_path, output_path, password)
                results.append((filename, True, ""))
            except Exception as e:
                results.append((filename, False, str(e)))
                
        return results


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
        self._start_offset = 0 # Offset where EVF data begins (0 for normal, >0 for mixed)
        self._lock = threading.Lock()
    
    def open(self, source, password: str) -> EVFHeader:
        """
        Open an encrypted file or stream for streaming decryption.
        
        Args:
            source: Path (str) or File-like object
            password: Decryption password
        """
        if isinstance(source, str):
            # User shared detection logic
            from core.evf_format import detect_mixed_file
            offset = detect_mixed_file(source)
            self._start_offset = offset if offset != -1 else 0
            
            self._file = open(source, 'rb')
            self._is_local = True
            
            # Initial seek to start of EVF data
            self._file.seek(self._start_offset)
        else:
            self._file = source
            self._is_local = False
            
            # Check for mixed file (offset) on file object
            try:
                self._file.seek(0, 2) # Seek end
                size = self._file.tell()
                
                # Check footer
                from core.evf_format import MIXED_MAGIC, MIXED_FOOTER_SIZE
                if size > MIXED_FOOTER_SIZE:
                    self._file.seek(-MIXED_FOOTER_SIZE, 2)
                    offset_bytes = self._file.read(8)
                    magic_len = len(MIXED_MAGIC)
                    magic = self._file.read(magic_len)
                    
                    # Check magic against constant 
                    if magic == MIXED_MAGIC:
                        offset = struct.unpack('<Q', offset_bytes)[0]
                        if 0 <= offset < size:
                            self._start_offset = offset
                            self._file.seek(self._start_offset)
                        else:
                            self._start_offset = 0
                            self._file.seek(0)
                    else:
                        self._start_offset = 0
                        self._file.seek(0)
                else:
                    self._start_offset = 0
                    self._file.seek(0)
                    
            except Exception:
                self._start_offset = 0
                self._file.seek(0)
             
        self._header = read_evf_header(self._file)
        
        # Derive key from password and stored salt
        self._key, _ = derive_key(password, self._header.salt)
        
        # Verify password by trying to decrypt first chunk
        try:
            first_chunk = self._read_encrypted_chunk(0)
            if first_chunk:
                self._decrypt_chunk(first_chunk)
        except Exception:
            self.close()
            raise ValueError("Incorrect password")
        
        # Reset to beginning (relative to offset)
        self._current_chunk = 0
        self._seek_to_chunk(0)
        
        return self._header
    
    def _read_encrypted_chunk(self, chunk_index: int) -> Optional[bytes]:
        """Read an encrypted chunk from the file."""
        if chunk_index >= self._header.num_chunks:
            return None
        
        # Calculate chunk size (last chunk may be smaller)
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
        # Calculate offset directly (O(1))
        # All chunks before this one are full size
        enc_chunk_size = get_encrypted_chunk_size(self._header.chunk_size)
        enc_chunk_size = get_encrypted_chunk_size(self._header.chunk_size)
        offset = self._start_offset + EVFHeader.HEADER_SIZE + (chunk_index * enc_chunk_size)
        
        self._file.seek(offset)
        self._current_chunk = chunk_index
        
    def get_chunk_data(self, chunk_index: int) -> Optional[bytes]:
        """Random access: Read and decrypt a specific chunk."""
        with self._lock:
            if chunk_index >= self._header.num_chunks:
                return None
            
            # Save current position to restore? 
            # For HTTP server we might not care about sequential state if we always seek.
            # But let's be safe or just set _current_chunk.
            self._seek_to_chunk(chunk_index)
            # Use internal methods to avoid double-locking if I used public ones (but read_decrypted_chunk is public? No, it's used inside).
            # Actually read_decrypted_chunk is public.
            # But it doesn't use lock.
            return self.read_decrypted_chunk()
    
    def read_decrypted_chunk(self) -> Optional[bytes]:
        """Read and decrypt the next chunk."""
        chunk_data = self._read_encrypted_chunk(self._current_chunk)
        if chunk_data is None:
            return None
        
        decrypted = self._decrypt_chunk(chunk_data)
        self._current_chunk += 1
        return decrypted
    
    def stream_all(self) -> Generator[bytes, None, None]:
        """Generator that yields all decrypted chunks."""
        self._seek_to_chunk(0)
        while True:
            chunk = self.read_decrypted_chunk()
            if chunk is None:
                break
            yield chunk
    
    def get_decrypted_size(self) -> int:
        """Get the original (decrypted) file size."""
        return self._header.original_size if self._header else 0
    
    def get_original_extension(self) -> str:
        """Get the original file extension."""
        return self._header.original_ext if self._header else ""
    
    def close(self) -> None:
        """Close the file and clear sensitive data."""
        if self._file:
            self._file.close()
            self._file = None
        self._key = None
        self._header = None
        self._header = None
        self._current_chunk = 0
        self._start_offset = 0
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
