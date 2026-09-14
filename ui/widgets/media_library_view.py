"""
Media library UI widget.
"""
import os
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, 
    QListWidgetItem, QPushButton, QLineEdit, QLabel,
    QFileDialog, QTabWidget, QComboBox, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QUrl, QRunnable, QThreadPool, pyqtSlot, QObject, QTimer
from PyQt6.QtGui import QIcon, QPixmap, QDesktopServices, QAction
from pathlib import Path
from core.media_library import MediaLibrary
from utils.file_utils import (
    is_video_file, is_image_file, is_archive_file, is_encrypted_file,
    is_document_file, is_text_file, is_pdf_file
)

class LoaderSignals(QObject):
    result = pyqtSignal(str, QPixmap) # hash, pixmap

class ThumbnailLoader(QRunnable):
    """Async loader for encrypted thumbnails."""
    def __init__(self, enc_path, password, file_hash):
        super().__init__()
        self.enc_path = enc_path
        self.password = password
        self.file_hash = file_hash
        self.signals = LoaderSignals()
        self.setAutoDelete(True)
        
    def run(self):
        try:
            with open(self.enc_path, 'rb') as f:
                salt = f.read(16)
                nonce = f.read(12)
                tag = f.read(16)
                ciphertext = f.read()
                
            from Crypto.Cipher import AES
            from core.key_derivation import derive_key
            
            key, _ = derive_key(self.password, salt)
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            plaintext = cipher.decrypt_and_verify(ciphertext, tag)
            
            pixmap = QPixmap()
            pixmap.loadFromData(plaintext)
            if not pixmap.isNull():
                self.signals.result.emit(self.file_hash, pixmap)
        except Exception as e:
            # print(f"Load error: {e}")
            pass

class PlaintextThumbLoader(QRunnable):
    """Async loader for plaintext thumbnails (Phase 2 optimization)."""
    def __init__(self, path, file_hash):
        super().__init__()
        self.path = path
        self.file_hash = file_hash
        self.signals = LoaderSignals()
        self.setAutoDelete(True)
        
    def run(self):
        try:
            pixmap = QPixmap(self.path)
            if not pixmap.isNull():
                self.signals.result.emit(self.file_hash, pixmap)
        except Exception:
            pass

class MediaLibraryView(QWidget):
    """Media library view with thumbnails and file management."""
    
    file_selected = pyqtSignal(str) # Path
    
    
    def __init__(self, library: MediaLibrary, parent=None):
        super().__init__(parent)
        self.library = library
        self._current_filter_type = "All" # All, Video, Image, Archive, Encrypted
        # Cache for thumbnails: hash -> QPixmap
        self._pixmap_cache = {} 
        self._loading_hashes = set()
        
        # Pre-cache existing thumbnail hashes for fast lookup
        self._existing_thumb_hashes = set()
        self._existing_enc_thumb_hashes = set()
        self._refresh_thumb_index()
        
        # PRE-CACHE FALLBACK ICONS (Phase 1 Optimization)
        self._fallback_icons = {}
        self._init_fallback_icons()
        
        # Batch Loading State
        self._pending_files = []
        self._batch_timer = QTimer(self)
        self._batch_timer.setInterval(0) # Process immediately when event loop is free
        self._batch_timer.timeout.connect(self._process_batch)
        
        # Dedicated Thread Pool for Thumbnail Loading
        # Prevents starvation of QThreadPool.globalInstance() which QtMultimedia uses!
        self._thumb_load_pool = QThreadPool()
        self._thumb_load_pool.setMaxThreadCount(4) # Limit concurrent disk reads/decryptions
        
        self._setup_ui()
        
        # Connect signals
        self.library.library_updated.connect(self._refresh_view)
        self.library.thumbnail_generated.connect(self._update_thumbnail)
        
        # Defer initial refresh slightly to let UI show
        QTimer.singleShot(100, self._refresh_view)

    def _refresh_thumb_index(self):
        """Scan thumbnails directory once and cache existing hashes."""
        thumb_dir = Path("thumbnails")
        if thumb_dir.exists():
            self._existing_thumb_hashes = set()
            self._existing_enc_thumb_hashes = set()
            for p in thumb_dir.iterdir():
                name = p.name
                if name.endswith('.jpg.enc'):
                    self._existing_enc_thumb_hashes.add(name[:-8]) # Remove .jpg.enc
                elif name.endswith('.jpg'):
                    self._existing_thumb_hashes.add(name[:-4]) # Remove .jpg

    def _init_fallback_icons(self):
        """Pre-load all fallback icons once."""
        assets_dir = Path(__file__).parent.parent.parent / "assets"
        
        # Standard icons
        self._fallback_icons['video'] = QIcon.fromTheme("video-x-generic")
        self._fallback_icons['image'] = QIcon.fromTheme("image-x-generic")
        self._fallback_icons['lock'] = QIcon.fromTheme("system-lock-screen")
        self._fallback_icons['generic'] = QIcon.fromTheme("application-x-generic")
        
        # Custom placeholders (load once, scale once)
        icon_size = QSize(256, 144)
        
        pdf_path = assets_dir / "placeholder_pdf.png"
        if pdf_path.exists():
            pm = QPixmap(str(pdf_path)).scaled(icon_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self._fallback_icons['pdf'] = QIcon(pm)
        else:
            self._fallback_icons['pdf'] = QIcon.fromTheme("application-pdf")
            
        text_path = assets_dir / "placeholder_text.png"
        if text_path.exists():
            pm = QPixmap(str(text_path)).scaled(icon_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self._fallback_icons['text'] = QIcon(pm)
        else:
            self._fallback_icons['text'] = QIcon.fromTheme("text-x-generic")
            
        archive_path = assets_dir / "placeholder_archive.png"
        if archive_path.exists():
            pm = QPixmap(str(archive_path)).scaled(icon_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self._fallback_icons['archive'] = QIcon(pm)
        else:
            self._fallback_icons['archive'] = QIcon.fromTheme("package-x-generic")
            
        generic_path = assets_dir / "placeholder_generic.png"
        if generic_path.exists():
            pm = QPixmap(str(generic_path)).scaled(icon_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self._fallback_icons['generic'] = QIcon(pm)

    # ... _setup_ui ...
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Toolbar
        toolbar = QHBoxLayout()
        
        self.btn_scan = QPushButton("📂 扫描文件夹")
        self.btn_scan.clicked.connect(self._scan_folder)
        
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["全部文件", "视频文件", "图片文件", "文档/PDF", "文本文件", "加密文件", "压缩包/其他"])
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索文件名...")
        self.search_input.textChanged.connect(self._filter_list)
        
        # Sorting
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["按时间", "按名称", "按类型", "按大小"])
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        
        self.btn_sort_order = QPushButton("⬇️") # Default Descending
        self.btn_sort_order.setCheckable(True)
        self.btn_sort_order.setToolTip("切换升序/降序")
        self.btn_sort_order.setMaximumWidth(40)
        self.btn_sort_order.clicked.connect(self._on_sort_order_changed)
        
        self.btn_clear = QPushButton("🗑️ 清空库")
        self.btn_clear.clicked.connect(self._clear_library)
        
        self.btn_refresh = QPushButton("🔄 刷新")
        self.btn_refresh.setToolTip("重新扫描已扫描的文件夹")
        self.btn_refresh.clicked.connect(self._refresh_library)
        
        toolbar.addWidget(self.btn_scan)
        toolbar.addWidget(self.btn_clear)
        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(self.filter_combo)
        toolbar.addWidget(self.sort_combo)
        toolbar.addWidget(self.btn_sort_order)
        toolbar.addWidget(self.search_input)
        
        layout.addLayout(toolbar)
        
        # Tabs (All, Recent)
        self.tabs = QTabWidget()
        
        # All Files
        self.list_all = QListWidget()
        self.list_all.setViewMode(QListWidget.ViewMode.IconMode)
        self.list_all.setIconSize(QSize(256, 144)) # Updated size
        self.list_all.setGridSize(QSize(270, 180))
        self.list_all.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list_all.setSpacing(10)
        self.list_all.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_all.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_all.customContextMenuRequested.connect(self._show_context_menu)
        self.list_all.setStyleSheet("QListWidget { background: transparent; border: none; } "
                                   "QListWidget::item { color: white; } "
                                   "QListWidget::item:selected { background: rgba(255,255,255,0.1); border-radius: 5px; }")
        
        self.tabs.addTab(self.list_all, "全部文件")
        
        # Recent
        self.list_recent = QListWidget()
        self.list_recent.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tabs.addTab(self.list_recent, "最近播放")
        
        layout.addWidget(self.tabs)
        
    def _scan_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择要扫描的文件夹")
        if folder:
            self.library.scan_path(folder)

    def _clear_library(self):
        """Clear library with confirmation."""
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, 
            "清空媒体库", 
            "确定要清空媒体库吗？\n这将移除所有文件的索引记录（不会删除实际文件）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.library.clear_library()
    
    def _refresh_library(self):
        """Refresh library by rescanning all previously scanned folders."""
        if not self.library.scanned_folders:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "刷新", "没有已扫描的文件夹。请先扫描一个文件夹。")
            return
        self.library.rescan()
            
    def _create_thumbnail_item(self, path: str, name: str, fallback_icon: QIcon, file_hash: str, priority: int = 0) -> QListWidgetItem:
        """Create a list item with thumbnail. Uses pre-computed hash.
        
        Args:
            priority: 0=low (default), 1=high (video/image)
        """
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(Qt.ItemDataRole.UserRole + 1, file_hash)
        item.setToolTip(name)
        item.setText(name)
        
        # 1. Check memory cache first (fastest)
        if file_hash in self._pixmap_cache:
            item.setIcon(QIcon(self._pixmap_cache[file_hash]))
            return item
        
        # 2. Check if thumbnail exists on disk (using pre-indexed sets)
        has_enc_thumb = file_hash in self._existing_enc_thumb_hashes
        has_plain_thumb = file_hash in self._existing_thumb_hashes
        
        # 3. Queue async load if thumbnail exists (with priority)
        if has_enc_thumb and self.library._thumbnail_password:
            if file_hash not in self._loading_hashes:
                self._loading_hashes.add(file_hash)
                enc_path = str(Path("thumbnails") / f"{file_hash}.jpg.enc")
                loader = ThumbnailLoader(enc_path, self.library._thumbnail_password, file_hash)
                loader.signals.result.connect(self._on_thumb_loaded)
                self._thumb_load_pool.start(loader, priority)
            item.setIcon(fallback_icon)
            return item
            
        elif has_plain_thumb:
            if file_hash not in self._loading_hashes:
                self._loading_hashes.add(file_hash)
                plain_path = str(Path("thumbnails") / f"{file_hash}.jpg")
                loader = PlaintextThumbLoader(plain_path, file_hash)
                loader.signals.result.connect(self._on_thumb_loaded)
                self._thumb_load_pool.start(loader, priority)
            item.setIcon(fallback_icon)
            return item
        
        # 4. No thumbnail exists - use fallback
        item.setIcon(fallback_icon)
        return item
        
    def _on_thumb_loaded(self, file_hash, pixmap):
        """Async callback when thumb is ready."""
        if file_hash in self._loading_hashes:
            self._loading_hashes.remove(file_hash)
            
        self._pixmap_cache[file_hash] = pixmap
        
        # Update visible items
        for i in range(self.list_all.count()):
            item = self.list_all.item(i)
            if item.data(Qt.ItemDataRole.UserRole + 1) == file_hash:
                item.setIcon(QIcon(pixmap))
                
    def _refresh_view(self):
        self.list_all.clear()
        self._batch_timer.stop()
        self._pending_files = []
        self._loading_hashes.clear()
        
        # Refresh thumbnail index for fast disk-existence checks
        self._refresh_thumb_index()
        
        files = self.library.get_files()
        search_text = self.search_input.text().lower()
        
        # Pre-filter to prepared list
        to_load = []
        for f in files:
            name = f['name']
            path = f['path']
            
            if not self._check_type_filter(f): continue
            if search_text and search_text not in name.lower(): continue
            
            to_load.append(f)
            
        # Sort
        sort_idx = self.sort_combo.currentIndex()
        reverse = not self.btn_sort_order.isChecked() 
        is_desc = not self.btn_sort_order.isChecked()
        
        def sort_key(item):
            if sort_idx == 0: # Time
                return item.get('mtime', 0)
            elif sort_idx == 1: # Name
                return item['name'].lower()
            elif sort_idx == 2: # Type
                return item['type'] # Strict suffix sorting as requested
            elif sort_idx == 3: # Size
                return item['size']
            return 0
            
        to_load.sort(key=sort_key, reverse=is_desc)
            
        self._pending_files = to_load
        self._batch_timer.start()
        
    def _process_batch(self):
        """Process a chunk of files (optimized)."""
        import hashlib
        BATCH_SIZE = 50 # Increased batch size for speed
        
        if not self._pending_files:
            self._batch_timer.stop()
            return
        
        # Track current list position for priority ordering
        current_position = self.list_all.count()
        
        count = 0
        while self._pending_files and count < BATCH_SIZE:
            f = self._pending_files.pop(0)
            name = f['name']
            path = f['path']
            
            # Pre-compute hash ONCE
            file_hash = f.get('file_hash') # Check if scanner pre-computed it
            if not file_hash:
                file_hash = hashlib.md5(path.encode('utf-8')).hexdigest()
            
            # Determine Fallback Icon using PRE-CACHED icons
            fallback = self._fallback_icons.get('generic')
            display_name = name
            
            if is_encrypted_file(path):
                # Virtualize Name for Mixed Files
                orig = f.get('original_type', '')
                if orig:
                    name_lower = name.lower()
                    # Case 1: Mixed File (Image Extension -> Original Extension)
                    if name_lower.endswith(('.jpg', '.jpeg', '.png')):
                         # Remove image extension and append original
                         base = os.path.splitext(name)[0]
                         display_name = f"{base}{orig}"
                    # Case 2: EVF File (Remove .evf, append original if missing)
                    elif name_lower.endswith('.evf'):
                        base = name[:-4]
                        if not base.lower().endswith(orig.lower()):
                            display_name = f"{base}{orig}"
                        else:
                            display_name = base
                            
                fallback = self._fallback_icons.get('lock', fallback)
                display_name = "🔒 " + display_name
                
                if self.library._thumbnail_password:
                    # Determine icon based on original type
                    if orig:
                        dummy = f"dummy{orig}"
                        if is_pdf_file(dummy):
                            fallback = self._fallback_icons.get('pdf', fallback)
                        elif is_text_file(dummy):
                            fallback = self._fallback_icons.get('text', fallback)
                        elif is_archive_file(dummy):
                            fallback = self._fallback_icons.get('archive', fallback)
                        elif is_video_file(dummy):
                            fallback = self._fallback_icons.get('video', fallback)
                        elif is_image_file(dummy):
                            fallback = self._fallback_icons.get('image', fallback)
                    
                    # Determine display name (already virtualized above)
                    name = display_name
                    
                    if self.filter_combo.currentIndex() == 5:
                         # For "Encrypted" filter, show type hint
                         if orig:
                             type_name = "未知"
                             dummy = f"x{orig}"
                             if is_video_file(dummy): type_name = "视频"
                             elif is_image_file(dummy): type_name = "图片"
                             elif is_archive_file(dummy): type_name = "压缩包"
                             elif is_pdf_file(dummy): type_name = "PDF"
                             elif is_text_file(dummy): type_name = "文本"
                             name += f" ({type_name})" # Simplified, don't repeat ext
                        
            elif is_video_file(path):
                fallback = self._fallback_icons.get('video', fallback)
            elif is_image_file(path):
                fallback = self._fallback_icons.get('image', fallback)
            elif is_pdf_file(path):
                fallback = self._fallback_icons.get('pdf', fallback)
            elif is_text_file(path):
                fallback = self._fallback_icons.get('text', fallback)
            elif is_archive_file(path):
                fallback = self._fallback_icons.get('archive', fallback)
            
            # Calculate priority combining type priority and position
            # QThreadPool: higher priority = processed first
            # Base priority: video/image=10000, others=0
            # Position offset: items earlier in list get higher offset (10000 - position)
            # Final: earlier video/image items load first, then later video/images, then others in order
            type_priority = 0
            orig_type = f.get('original_type', '')
            if is_video_file(path) or is_image_file(path):
                type_priority = 10000
            elif is_encrypted_file(path) and orig_type:
                dummy = f"x{orig_type}"
                if is_video_file(dummy) or is_image_file(dummy):
                    type_priority = 10000
            
            # Position priority: items at top of sorted list should load first
            # Clamp to prevent negative priorities
            position_priority = max(0, 10000 - current_position)
            priority = type_priority + position_priority
            
            # Create item with PRE-COMPUTED hash and PRIORITY
            item = self._create_thumbnail_item(path, name, fallback, file_hash, priority)
            self.list_all.addItem(item)
            current_position += 1
            count += 1
            
    def _check_type_filter(self, file_data: dict) -> bool:
        """Check if file matches current filter."""
        path = file_data['path']
        original_type = file_data.get('original_type', "")
        
        # Helper to check extension based on path OR original_type
        def is_type(checker_func, p, orig_t):
            if checker_func(p): return True
            # Check original type if encrypted
            if orig_t and checker_func(f"dummy{orig_t}"): return True
            return False

        idx = self.filter_combo.currentIndex()
        if idx == 0: return True # All
        
        if idx == 1: # Video
            return is_type(is_video_file, path, original_type)
            
        if idx == 2: # Image
            return is_type(is_image_file, path, original_type)
            
        if idx == 3: # Documents/PDF
            return is_type(is_pdf_file, path, original_type) or is_type(is_document_file, path, original_type)
            
        if idx == 4: # Text files
            return is_type(is_text_file, path, original_type)
            
        if idx == 5: # Encrypted (Strictly encrypted files)
            return is_encrypted_file(path)
            
        if idx == 6: # Archive/Other (Everything else)
            is_vid = is_type(is_video_file, path, original_type)
            is_img = is_type(is_image_file, path, original_type)
            is_doc = is_type(is_document_file, path, original_type)
            is_txt = is_type(is_text_file, path, original_type)
            return not (is_vid or is_img or is_doc or is_txt)
            
        return True
 
    def _on_filter_changed(self):
        self._refresh_view()
        
    def _on_sort_changed(self):
        self._refresh_view()
        
    def _on_sort_order_changed(self):
        is_asc = self.btn_sort_order.isChecked()
        self.btn_sort_order.setText("⬆️" if is_asc else "⬇️")
        self._refresh_view()
        
    def _filter_list(self, text):
        self._refresh_view() # Re-run full filter including search
            
    def _update_thumbnail(self, file_path, thumb_path):
        # Update: Trigger async load if encrypted
        import hashlib
        file_hash = hashlib.md5(file_path.encode('utf-8')).hexdigest()
        
        # If cache hit, update? Assuming cache is stale if generator ran.
        # If generator ran, it means we didn't have it or updated it.
        # But generator saves to disk. We need to load it.
        
        enc_thumb_path = Path("thumbnails") / f"{file_hash}.jpg.enc"
        
        if enc_thumb_path.exists() and self.library._thumbnail_password:
             if file_hash not in self._loading_hashes:
                 self._loading_hashes.add(file_hash)
                 loader = ThumbnailLoader(str(enc_thumb_path), self.library._thumbnail_password, file_hash)
                 loader.signals.result.connect(self._on_thumb_loaded)
                 self._thumb_load_pool.start(loader)
        
        elif Path(thumb_path).exists():
             pixmap = QPixmap(str(thumb_path))
             if not pixmap.isNull():
                 self._pixmap_cache[file_hash] = pixmap
                 # Update items
                 for i in range(self.list_all.count()):
                     item = self.list_all.item(i)
                     if item.data(Qt.ItemDataRole.UserRole + 1) == file_hash:
                         item.setIcon(QIcon(pixmap))
        
    def _on_item_double_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path: return
        
        # Check if supported internal type (video, image, text, document, encrypted)
        if (is_video_file(path) or is_image_file(path) or is_encrypted_file(path) or
            is_text_file(path) or is_document_file(path) or is_pdf_file(path)):
             self.file_selected.emit(path)
        else:
             # System open for other files
             QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _show_context_menu(self, pos):
        item = self.list_all.itemAt(pos)
        if not item: return
        
        path = item.data(Qt.ItemDataRole.UserRole)
        
        menu = QMenu()
        
        # Open with submenu
        open_with_menu = menu.addMenu("📂 打开方式")
        
        open_internal = QAction("🎬 内部打开", self)
        open_internal.triggered.connect(lambda: self._on_item_double_clicked(item))
        open_with_menu.addAction(open_internal)
        
        open_system = QAction("🌐 系统默认", self)
        open_system.triggered.connect(lambda: self._open_with_system(path))
        open_with_menu.addAction(open_system)
        
        open_choose = QAction("▶️ 选择程序...", self)
        open_choose.triggered.connect(lambda: self._open_with_choose(path))
        open_with_menu.addAction(open_choose)
        
        menu.addSeparator()
        
        # Detect type
        if is_encrypted_file(path):
            decrypt_act = QAction("🔓 解密...", self)
            decrypt_act.triggered.connect(lambda: self._call_decrypt(path))
            menu.addAction(decrypt_act)
        else:
            encrypt_act = QAction("🔐 加密...", self)
            encrypt_act.triggered.connect(lambda: self._call_encrypt(path))
            menu.addAction(encrypt_act)
            
        menu.addSeparator()
        reveal_act = QAction("📁 在资源管理器中显示", self)
        reveal_act.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent))))
        menu.addAction(reveal_act)
        
        menu.exec(self.list_all.mapToGlobal(pos))
    
    def _open_with_system(self, path: str):
        """Open file with system default application."""
        # For encrypted files, decrypt to temp first
        if is_encrypted_file(path):
            password = self.library._thumbnail_password
            if not password:
                from ui.password_dialog import PasswordDialog
                password, ok = PasswordDialog.get_password_dialog(self, "🔐 需要密码", "请输入密码以打开此文件")
                if not ok:
                    return
            
            try:
                import tempfile
                from core.crypto_engine import EncryptionEngine
                from core.evf_format import read_evf_header
                
                with open(path, 'rb') as f:
                    header = read_evf_header(f)
                original_ext = header.original_ext or ''
                
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=original_ext)
                temp_path = temp_file.name
                temp_file.close()
                
                engine = EncryptionEngine()
                engine.decrypt_file(path, temp_path, password)
                
                QDesktopServices.openUrl(QUrl.fromLocalFile(temp_path))
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", f"Failed to decrypt: {e}")
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
    
    def _open_with_choose(self, path: str):
        """Open 'Open With' dialog on Windows."""
        import os
        import subprocess
        
        target_path = path
        
        # For encrypted files, decrypt first
        if is_encrypted_file(path):
            password = self.library._thumbnail_password
            if not password:
                from ui.password_dialog import PasswordDialog
                password, ok = PasswordDialog.get_password_dialog(self, "🔐 需要密码", "请输入密码以打开此文件")
                if not ok:
                    return
            
            try:
                import tempfile
                from core.crypto_engine import EncryptionEngine
                from core.evf_format import read_evf_header
                
                with open(path, 'rb') as f:
                    header = read_evf_header(f)
                original_ext = header.original_ext or ''
                
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=original_ext)
                target_path = temp_file.name
                temp_file.close()
                
                engine = EncryptionEngine()
                engine.decrypt_file(path, target_path, password)
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", f"Failed to decrypt: {e}")
                return
        
        # Windows: Use rundll32 to show Open With dialog
        if os.name == 'nt':
            subprocess.Popen(['rundll32', 'shell32.dll,OpenAs_RunDLL', target_path])
        else:
            # Fallback to xdg-open or open on other platforms
            QDesktopServices.openUrl(QUrl.fromLocalFile(target_path))
        
    def _call_encrypt(self, path):
        # Open Encryption Dialog pre-filled?
        # Requires MainWindow to handle or exposing method?
        # Better signal?
        # For simple access, let's signal parent or use QDialog directly if imports allowed.
        # Signal is cleaner.
        # But we are in a widget.
        # Let's import EncryptionDialog here?
        from ui.encryption_dialog import EncryptionDialog
        dial = EncryptionDialog(self)
        dial._files.append(path)
        dial._task_list.append((path, None)) # Fix: Populate task list
        # Add to list widget manually
        item = QListWidgetItem(f"📄 {Path(path).name}")
        item.setData(Qt.ItemDataRole.UserRole, path)
        dial.file_list.addItem(item)
        dial.exec()

    def _call_decrypt(self, path):
        from ui.decryption_dialog import DecryptionDialog
        dial = DecryptionDialog(self)
        dial._files.append(path)
        dial._task_list.append((path, None)) # Fix: Populate task list for worker
        item = QListWidgetItem(f"🔒 {Path(path).name}")
        item.setData(Qt.ItemDataRole.UserRole, path)
        dial.file_list.addItem(item)
        dial.exec()

    def showEvent(self, event):
        # Refresh recent
        self._refresh_recent()
        super().showEvent(event)
        
    def _refresh_recent(self):
        self.list_recent.clear()
        for path in self.library.history:
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.list_recent.addItem(item)
            
    def get_visible_paths(self) -> list[str]:
        """Get list of paths currently visible in the active list widget."""
        # Check active tab
        current_list = self.list_all if self.tabs.currentIndex() == 0 else self.list_recent
        paths = []
        for i in range(current_list.count()):
            item = current_list.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                paths.append(path)
        return paths
