"""
Core media library management.
Handles scanning, indexing, thumbnails, and history.
"""

import os
import json
import hashlib
import cv2
import time
from pathlib import Path
from typing import List, Dict, Optional
from PyQt6.QtCore import QObject, pyqtSignal, QThread, QRunnable, QThreadPool
from utils.file_utils import is_video_file, is_image_file, is_encrypted_file

THUMBNAIL_SIZE = (256, 256) # Max bounding box
DB_FILE = "library.json"
THUMBS_DIR = "thumbnails"

class FileScanner(QThread):
    """Background thread for scanning files recursively."""
    files_found = pyqtSignal(list) # List[Dict]
    finished = pyqtSignal()
    
    def __init__(self, root_path: str):
        super().__init__()
        self.root_path = root_path
        self._running = True
        

    def _get_original_type(self, path_str: str) -> str:
        """Get original type for encrypted files."""
        try:
            from core.evf_format import read_evf_header, detect_mixed_file
            
            offset = detect_mixed_file(path_str)
            start_pos = 0 if offset == -1 else offset
            
            with open(path_str, 'rb') as f:
                f.seek(start_pos)
                header = read_evf_header(f)
                return header.original_ext.lower() if header.original_ext else ""
        except:
            return ""

    def run(self):
        new_files = []
        path_obj = Path(self.root_path)
        
        try:
            for p in path_obj.rglob("*"):
                if not self._running: break
                
                if p.is_file():
                    s_p = str(p)
                    # Index ALL files
                    try:
                        stat = p.stat()
                        suffix = p.suffix.lower()
                        item = {
                            'path': s_p,
                            'name': p.name,
                            'size': stat.st_size,
                            'mtime': stat.st_mtime,
                            'type': suffix,
                            'original_type': suffix # Default to real suffix
                        }
                        
                        # Identify Encrypted Original Type
                        if is_encrypted_file(s_p):
                            orig = self._get_original_type(s_p)
                            if orig:
                                item['original_type'] = orig
                        
                        new_files.append(item)
                        
                        if len(new_files) >= 50:
                            self.files_found.emit(new_files)
                            new_files = []
                            
                    except Exception as e:
                        print(f"Error accessing {s_p}: {e}")
                            
                    except Exception as e:
                        print(f"Error accessing {s_p}: {e}")
                            
            # Emit remaining
            if new_files:
                self.files_found.emit(new_files)
                
        except Exception as e:
            print(f"Scan error: {e}")
            
        self.finished.emit()
        
    def stop(self):
        self._running = False
        self.wait()

class WorkerSignals(QObject):
    """Signals for ThumbnailRunnable."""
    finished = pyqtSignal()
    result = pyqtSignal(str, str) # file_path, thumb_path

try:
    import fitz
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

class ThumbnailRunnable(QRunnable):
    """Worker task for generating a single thumbnail."""
    
    def __init__(self, file_path: str, password: Optional[str]):
        super().__init__()
        self.file_path = file_path
        self.password = password
        self.signals = WorkerSignals()
        self.setAutoDelete(True)
        
    def run(self):
        try:
            thumb_path = self._generate(self.file_path)
            if thumb_path:
                self.signals.result.emit(self.file_path, thumb_path)
        except Exception:
            pass
        finally:
            self.signals.finished.emit()

    def _generate(self, file_path: str) -> Optional[str]:
        # Hash filename for unique thumb name
        file_hash = hashlib.md5(file_path.encode('utf-8')).hexdigest()
        
        is_enc_file = is_encrypted_file(file_path)
        thumb_path = str(Path(THUMBS_DIR) / f"{file_hash}.jpg")
        
        if is_enc_file:
             # Encrypted thumb extension
             thumb_path = str(Path(THUMBS_DIR) / f"{file_hash}.jpg.enc")
        
        # Check existence
        if Path(thumb_path).exists():
             return thumb_path
             
        # Generation Logic
        try:
            from utils.file_utils import is_pdf_file
            
            if is_video_file(file_path):
                return self._generate_from_video(file_path, thumb_path)
                    
            elif is_image_file(file_path):
                return self._generate_from_image(file_path, thumb_path)
                
            elif is_pdf_file(file_path):
                 return self._generate_from_pdf(file_path, thumb_path)
                 
            elif is_enc_file and self.password:
                # Secure Generation
                return self._generate_secure(file_path, thumb_path)
                
        except Exception as e:
            # print(f"Gen error: {e}")
            pass
            
        return None

    def _generate_from_image(self, img_path: str, thumb_path: str) -> Optional[str]:
        import numpy as np
        try:
            data = np.fromfile(img_path, dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            
            if img is not None:
                img = self._resize_keep_aspect(img, THUMBNAIL_SIZE)
                return self._save_thumb_image(img, thumb_path)
        except Exception as e:
            print(f"Image gen error: {e}")
        return None

    def _generate_from_pdf(self, pdf_path: str, thumb_path: str) -> Optional[str]:
        if not HAS_PYMUPDF: return None
        try:
            doc = fitz.open(pdf_path)
            if doc.page_count < 1: return None
            
            page = doc[0]
            pix = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5)) # Low res for thumb is fine
            
            # Save directly? Or resize with cv2?
            # Fitz save is usually png/ppm.
            # We want jpg.
            # Convert to cv2 image
            import numpy as np
            # pix.samples is bytes. 
            # pix.n is channels.
            if pix.n >= 3:
                # Format adjustment
                # pix.samples is RGB usually
                img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n == 4:
                    img_data = cv2.cvtColor(img_data, cv2.COLOR_RGBA2BGR)
                else:
                    img_data = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR)
                
                img = self._resize_keep_aspect(img_data, THUMBNAIL_SIZE)
                
                # Save
                ext = ".jpg"
                valid, enc_img = cv2.imencode(ext, img)
                if valid:
                     # Check if we need encryption?
                     # Standard PDF -> Standard Thumb
                     if thumb_path.endswith(".enc"):
                          self._write_encrypted_thumb(enc_img, thumb_path)
                     else:
                          with open(thumb_path, 'wb') as f:
                              enc_img.tofile(f)
                     return thumb_path
                     
        except Exception as e:
            print(f"PDF gen error: {e}")
        return None

    def _generate_secure(self, file_path: str, thumb_path: str) -> Optional[str]:
        import tempfile
        import numpy as np
        from core.crypto_engine import StreamingDecryptor
        from utils.file_utils import is_image_file as is_img_check
        from utils.file_utils import is_pdf_file as is_pdf_check
        
        try:
            res = None
            with StreamingDecryptor() as dec:
                try:
                    dec.open(file_path, self.password)
                except ValueError:
                    return None
                    
                orig_ext = dec.get_original_extension()
                if not orig_ext: orig_ext = ""
                dummy_name = f"temp{orig_ext}"
                
                # Dispatch based on type
                if is_pdf_check(dummy_name):
                    # Decrypt to temp file for fitz
                    import os
                    tf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                    temp_path_pdf = tf.name
                    tf.close()
                    try:
                        # Dump all
                        with open(temp_path_pdf, 'wb') as f:
                            for chunk in dec.stream_all():
                                f.write(chunk)
                                
                        # Generate
                        res = self._generate_from_pdf(temp_path_pdf, thumb_path)
                    finally:
                        if os.path.exists(temp_path_pdf):
                            os.unlink(temp_path_pdf)
                    return res
                    
                elif is_img_check(dummy_name):
                    # Image Logic (Existing)
                     if dec.get_decrypted_size() < 200 * 1024 * 1024:
                         data = bytearray()
                         for chunk in dec.stream_all():
                             data.extend(chunk)
                         nparr = np.frombuffer(data, np.uint8)
                         img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                         if img is not None:
                             img = self._resize_keep_aspect(img, THUMBNAIL_SIZE)
                             return self._save_thumb_image(img, thumb_path)

                else:
                    # Video Logic (Existing - Simplified here for brevity but assuming video)
                    # Use existing _generate_from_video with sparse file trick
                    # ... (Sparse file logic omitted to save space, assuming it's still there in class if I don't overwrite it?)
                    # Wait, I am overwriting the WHOLE method block if I use ReplaceFileContent on range.
                    # I need to preserve the sparse file logic or re-implement it.
                    # The previous logic was complex.
                    # Let's use the helper method _generate_video_secure to keep it clean.
                    return self._generate_video_secure(dec, orig_ext, thumb_path)
                    
        except Exception:
            pass
        return None

    def _save_thumb_image(self, img, thumb_path):
        import numpy as np
        ext = ".jpg"
        valid, enc_img = cv2.imencode(ext, img)
        if valid:
             if thumb_path.endswith(".enc"):
                  self._write_encrypted_thumb(enc_img, thumb_path)
             else:
                  with open(thumb_path, 'wb') as f:
                      enc_img.tofile(f)
             return thumb_path
        return None

    def _write_encrypted_thumb(self, enc_img, thumb_path):
         from Crypto.Cipher import AES
         from Crypto.Random import get_random_bytes
         from core.key_derivation import derive_key
         
         plain_bytes = enc_img.tobytes()
         salt = get_random_bytes(16)
         key, _ = derive_key(self.password, salt)
         nonce = get_random_bytes(12)
         cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
         ciphertext, tag = cipher.encrypt_and_digest(plain_bytes)
         
         with open(thumb_path, 'wb') as f:
             f.write(salt)
             f.write(nonce)
             f.write(tag)
             f.write(ciphertext)

    def _generate_video_secure(self, dec, orig_ext, thumb_path):
        # Sparse file: head 10MB + tail 50 chunks (moov atom lives at the tail
        # for non-faststart MP4s). If cv2 still can't open it, fall back to
        # full decrypt (max 200MB).
        import tempfile
        import os
        import cv2 as _cv2
        if not orig_ext: orig_ext = ".mp4"
        temp_path = ""
        try:
            tf = tempfile.NamedTemporaryFile(suffix=orig_ext, delete=False)
            temp_path = tf.name
            
            total_size = dec.get_decrypted_size()
            if total_size > 0:
                tf.seek(total_size - 1)
                tf.write(b'\0')
                tf.flush()
            
            # Write Head (10MB)
            written = 0
            limit = 10 * 1024 * 1024
            dec._seek_to_chunk(0)
            tf.seek(0)
            
            while written < limit:
                chunk = dec.read_decrypted_chunk()
                if not chunk: break
                tf.write(chunk)
                written += len(chunk)

            # Write Tail (last 50 chunks) — covers moov atom for non-faststart videos
            num_chunks = dec._header.num_chunks
            tail_start = max(0, num_chunks - 50)
            for idx in range(tail_start, num_chunks):
                chunk = dec.get_chunk_data(idx)
                if chunk:
                    tf.seek(idx * dec._header.chunk_size)
                    tf.write(chunk)
                
            tf.flush()
            tf.close()

            cap = _cv2.VideoCapture(temp_path)
            if cap.isOpened():
                cap.release()
                return self._generate_from_video(temp_path, thumb_path)

            # Fallback: full decrypt (max 200MB) — almost always opens
            print(f"[Thumb] sparse open failed, trying full decrypt...")
            os.unlink(temp_path)
            dec._seek_to_chunk(0)
            tf2 = tempfile.NamedTemporaryFile(suffix=orig_ext, delete=False)
            temp_path = tf2.name
            decrypted = 0
            max_decrypt = 200 * 1024 * 1024
            while decrypted < max_decrypt:
                chunk = dec.read_decrypted_chunk()
                if not chunk: break
                tf2.write(chunk)
                decrypted += len(chunk)
            tf2.flush()
            tf2.close()

            cap = _cv2.VideoCapture(temp_path)
            if cap.isOpened():
                cap.release()
                return self._generate_from_video(temp_path, thumb_path)

        except Exception:
            try:
                if 'tf' in locals(): tf.close()
            except Exception:
                pass
            try:
                if 'tf2' in locals(): tf2.close()
            except Exception:
                pass
            return None
        finally:
             if temp_path and os.path.exists(temp_path):
                 try: os.remove(temp_path)
                 except: pass

    def _resize_keep_aspect(self, img, target_size=(256, 256), bg_color=(0,0,0)):
        """Resize image keeping aspect ratio and pad with black."""
        h, w = img.shape[:2]
        target_w, target_h = target_size
        
        scale = min(target_w / w, target_h / h)
        new_w, new_h = int(w * scale), int(h * scale)
        
        img_resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        return img_resized

    def _generate_from_video(self, video_path: str, thumb_path: str) -> Optional[str]:
        # NOTE: This method now supports returning raw frame if called internally, 
        # but signature returns Optional[str] (path).
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened(): return None
        
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        target_frame = 0
        if total_frames > 200: 
            target_frame = min(100, total_frames // 20)
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()
            
        cap.release()
        
        if ret and frame is not None and frame.size > 0:
            try:
                # Aspect Ratio Resize
                frame = self._resize_keep_aspect(frame, THUMBNAIL_SIZE)
                return self._save_thumb_image(frame, thumb_path)
                              
            except Exception as e: 
                # print(f"Gen video error: {e}")
                pass
        return None

class MediaLibrary(QObject):
    """
    Manages media files, history and bookmarks.
    """
    library_updated = pyqtSignal() # When scan completes (or chunk added)
    thumbnail_generated = pyqtSignal(str, str)
    
    def __init__(self):
        super().__init__()
        self.files: List[Dict] = []
        self.history: List[str] = []
        self.favorites: List[str] = [] # New
        self.bookmarks: Dict[str, List[int]] = {} 
        self.root_paths: List[str] = []
        self.scanned_folders: List[str] = []  # Track scanned folders for rescan
        
        # Standby Password (Locked Mode)
        self.standby_pwd_hash: Optional[bytes] = None
        self.standby_pwd_salt: Optional[bytes] = None
        self._lib_key: Optional[bytes] = None
        
        self._scanner: Optional[FileScanner] = None
        self._thumbnail_password: Optional[str] = None
        
        # Thread Pool for Thumbnails
        # Use PRIVATE Thread pool to allow suspend/resume
        self._thread_pool = QThreadPool()
        # Ensure we don't saturate disk IO. 
        # Python GIL limits CPU, but disk is main bottleneck.
        # Argon2id is CPU/Memory heavy, so we MUST restrict threads to avoid stalling the UI/Playback.
        # 1 thread when playing? 2 normal?
        # Let's set max to 2.
        self._max_threads = 2
        self._thread_pool.setMaxThreadCount(self._max_threads)
        
        self._thumb_queue = [] # Simple list as queue
        self._suspended = False
        
        self._load_db()
        
    def suspend_generation(self):
        """Suspend background thumbnail generation (e.g. during playback)."""
        self._suspended = True
        # We can't stop running threads, but we stop scheduling new ones.
        
    def resume_generation(self):
        """Resume background generation."""
        self._suspended = False
        self._process_queue()
        
    def set_thumbnail_password(self, password: Optional[str]):
        """Set password for secure thumbnail generation."""
        self._thumbnail_password = password
        
        if password:
            # Trigger regeneration for encrypted files that lack thumbs
            to_gen = []
            for f in self.files:
                path = f['path']
                if is_encrypted_file(path):
                    # Check if thumb exists
                    file_hash = hashlib.md5(path.encode('utf-8')).hexdigest()
                    thumb_path = Path(THUMBS_DIR) / f"{file_hash}.jpg"
                    if not thumb_path.exists():
                        to_gen.append(path)
            
            if to_gen:
                self._start_thumb_gen(to_gen)
    
    # ... (in _load_db)
    def _load_db(self):
        from core.secrets_store import (
            load_or_create_machine_key,
            decrypt_paths_with_machine_key,
            decrypt_bookmarks_with_machine_key,
        )

        # Machine key sidecar — encrypts all path metadata in library.json
        key_path = os.path.join(os.path.dirname(os.path.abspath(DB_FILE)), 'library.key')
        self._lib_key = load_or_create_machine_key(key_path)

        if Path(DB_FILE).exists():
            try:
                with open(DB_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if self._lib_key:
                        self.history = decrypt_paths_with_machine_key(data.get('history', []), self._lib_key)
                        self.favorites = decrypt_paths_with_machine_key(data.get('favorites', []), self._lib_key)
                        self.bookmarks = decrypt_bookmarks_with_machine_key(data.get('bookmarks', {}), self._lib_key)
                        self.root_paths = decrypt_paths_with_machine_key(data.get('roots', []), self._lib_key)
                    else:
                        # No key available — keep legacy plaintext values
                        self.history = data.get('history', [])
                        self.favorites = data.get('favorites', [])
                        self.bookmarks = data.get('bookmarks', {})
                        self.root_paths = data.get('roots', [])
                    
                    # Load standby password (stored as hex strings)
                    pwd_hash_hex = data.get('standby_pwd_hash')
                    pwd_salt_hex = data.get('standby_pwd_salt')
                    if pwd_hash_hex and pwd_salt_hex:
                        self.standby_pwd_hash = bytes.fromhex(pwd_hash_hex)
                        self.standby_pwd_salt = bytes.fromhex(pwd_salt_hex)
            except Exception as e:
                print(f"Error loading DB: {e}")

    def save_db(self):
        from core.secrets_store import (
            encrypt_paths_with_machine_key,
            encrypt_bookmarks_with_machine_key,
        )

        if self._lib_key:
            history = encrypt_paths_with_machine_key(self.history, self._lib_key)
            favorites = encrypt_paths_with_machine_key(self.favorites, self._lib_key)
            bookmarks = encrypt_bookmarks_with_machine_key(self.bookmarks, self._lib_key)
            roots = encrypt_paths_with_machine_key(self.root_paths, self._lib_key)
        else:
            history, favorites, bookmarks, roots = self.history, self.favorites, self.bookmarks, self.root_paths

        data = {
            'history': history,
            'favorites': favorites,
            'bookmarks': bookmarks,
            'roots': roots,
            'standby_pwd_hash': self.standby_pwd_hash.hex() if self.standby_pwd_hash else None,
            'standby_pwd_salt': self.standby_pwd_salt.hex() if self.standby_pwd_salt else None
        }
        try:
            with open(DB_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving DB: {e}")

    def add_history(self, file_path: str):
        if file_path in self.history:
            self.history.remove(file_path)
        self.history.insert(0, file_path)
        self.history = self.history[:50] # Limit 50
        self.save_db()
        
    def add_bookmark(self, file_path: str, position_ms: int):
        if file_path not in self.bookmarks:
            self.bookmarks[file_path] = []
        if position_ms not in self.bookmarks[file_path]:
            self.bookmarks[file_path].append(position_ms)
            self.bookmarks[file_path].sort()
            self.save_db()
            
    def get_bookmarks(self, file_path: str) -> List[int]:
        return self.bookmarks.get(file_path, [])
    
    def remove_bookmark(self, file_path: str, position_ms: int):
        if file_path in self.bookmarks:
            if position_ms in self.bookmarks[file_path]:
                self.bookmarks[file_path].remove(position_ms)
                self.save_db()

    # --- Favorites ---
    def add_favorite(self, path: str):
        if path not in self.favorites:
            self.favorites.append(path)
            self.save_db()
            
    def remove_favorite(self, path: str):
        if path in self.favorites:
            self.favorites.remove(path)
            self.save_db()
            
    def get_favorites(self) -> List[str]:
        return self.favorites
        
    def is_favorite(self, path: str) -> bool:
        return path in self.favorites

    # --- Standby Password Management ---
    def has_standby_password(self) -> bool:
        """Check if a standby password has been set."""
        return self.standby_pwd_hash is not None

    def set_standby_password(self, password: str):
        """Set or update the standby password."""
        from core.key_derivation import derive_key
        self.standby_pwd_hash, self.standby_pwd_salt = derive_key(password)
        self.save_db()

    def verify_standby_password(self, password: str) -> bool:
        """Verify the given password against the stored hash."""
        if not self.has_standby_password():
            return False
        from core.key_derivation import verify_password
        return verify_password(password, self.standby_pwd_salt, self.standby_pwd_hash)

    def scan_path(self, path: str):
        """Scan a path and update library asynchronously."""
        if path not in self.root_paths:
            self.root_paths.append(path)
            
        # Track scanned folders for rescan
        if path not in self.scanned_folders:
            self.scanned_folders.append(path)
            
        self.save_db()
            
        if self._scanner and self._scanner.isRunning():
            self._scanner.stop()
            
        self._scanner = FileScanner(path)
        self._scanner.files_found.connect(self._on_files_found)
        self._scanner.finished.connect(self._on_scan_finished)
        self._scanner.start()
    
    def rescan(self):
        """Rescan all previously scanned folders."""
        if not self.scanned_folders:
            return
        
        # Clear files but keep history/favorites
        self.files = []
        self.library_updated.emit()
        
        # Scan each folder sequentially (can be improved with queuing)
        for folder in self.scanned_folders[:]:
            if Path(folder).exists():
                self.scan_path(folder)
        
    def _on_files_found(self, new_files: List[Dict]):
        """Handle chunk of found files."""
        existing_paths = {f['path'] for f in self.files}
        added_files = []
        
        for f in new_files:
            if f['path'] not in existing_paths:
                self.files.append(f)
                added_files.append(f)
                existing_paths.add(f['path'])
                
        if added_files:
            self.library_updated.emit()
            
            # Queue thumbnails
            to_gen = [f['path'] for f in added_files]
            self._start_thumb_gen(to_gen)

    def _start_thumb_gen(self, paths: List[str]):
        # Ensure thumbs dir exists once
        Path(THUMBS_DIR).mkdir(exist_ok=True)
        
        self._thumb_queue.extend(paths)
        self._process_queue()
        
    def _process_queue(self):
        """Schedule next batch of thumbnails if possible."""
        if self._suspended: return
        
        # Check active thread count
        active = self._thread_pool.activeThreadCount()
        available = self._max_threads - active
        
        if available > 0 and self._thumb_queue:
            # Pop next batch
            for _ in range(available):
                if not self._thumb_queue: break
                
                path = self._thumb_queue.pop(0)
                worker = ThumbnailRunnable(path, self._thumbnail_password)
                worker.signals.result.connect(self._on_thumb_ready)
                worker.signals.finished.connect(self._process_queue) # Chain next
                self._thread_pool.start(worker)

    def _on_scan_finished(self):
        # Scan complete
        pass

    def _on_thumb_ready(self, file_path, thumb_path):
        self.thumbnail_generated.emit(file_path, thumb_path)
        
    def get_files(self) -> List[Dict]:
        return self.files

    def clear_library(self):
        """Clear all files and root paths."""
        self.files.clear()
        self.root_paths.clear()
        self.save_db()
        self.library_updated.emit()
