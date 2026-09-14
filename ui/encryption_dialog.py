"""
Encryption dialog for encrypting video files.
"""

import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QFrame, QFileDialog, QProgressBar,
    QListWidget, QListWidgetItem, QCheckBox, QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from pathlib import Path
from typing import Optional, List, Tuple

from core.crypto_engine import EncryptionEngine
from ui.password_dialog import PasswordDialog
from utils.file_utils import (
    get_encrypted_output_path, is_video_file, is_image_file, 
    is_archive_file, is_supported_file, is_encrypted_file, ensure_dir
)
from utils.constants import SUPPORTED_VIDEO_FORMATS


class EncryptionWorker(QThread):
    """Worker thread for encryption tasks."""
    
    progress = pyqtSignal(str, int, int)  # filename, current, total
    file_progress = pyqtSignal(int, int)  # bytes processed, total bytes
    finished = pyqtSignal(list)  # results
    error = pyqtSignal(str)
    
    def __init__(self, files: List[Tuple[str, Optional[str]]], output_folder: str, password: str, delete_source: bool = False):
        super().__init__()
        self.files = files # List of (path, root_base)
        self.output_folder = output_folder
        self.password = password
        self.delete_source = delete_source
    
    def run(self):
        """Run encryption in background."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from PyQt6.QtCore import QMutex
        
        engine = EncryptionEngine()
        results = []
        
        # Max threads based on CPU
        max_workers = min(os.cpu_count() or 4, 8)
        
        mutex = QMutex()
        completed = 0
        total = len(self.files)
        
        def encrypt_single(index, file_path, root_base):
            nonlocal completed
            filename = Path(file_path).name
            
            try:
                # Calculate output path preserving structure if root_base exists
                if self.output_folder:
                    if root_base:
                        try:
                            rel_path = Path(file_path).relative_to(root_base)
                            target_dir = Path(self.output_folder) / rel_path.parent
                            ensure_dir(str(target_dir))
                            output_path = get_encrypted_output_path(file_path, str(target_dir))
                        except ValueError:
                            output_path = get_encrypted_output_path(file_path, self.output_folder)
                    else:
                        output_path = get_encrypted_output_path(file_path, self.output_folder)
                else:
                    output_path = get_encrypted_output_path(file_path, None)

                # Only emit byte progress if single threaded or primary? 
                # Too much signal traffic invalidates performance gains.
                # Pass None for callback to disable file-level progress in parallel
                engine.encrypt_file(
                    file_path, 
                    output_path, 
                    self.password,
                    None # Disable fine-grained progress for speed
                )
                
                if self.delete_source and Path(output_path).exists():
                    os.remove(file_path)
                    
                mutex.lock()
                completed += 1
                # Emit main progress
                self.progress.emit(filename, completed, total)
                mutex.unlock()
                
                return (filename, True, output_path, file_path, root_base)
            except Exception as e:
                mutex.lock()
                completed += 1
                self.progress.emit(filename, completed, total)
                mutex.unlock()
                return (filename, False, str(e), file_path, root_base)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {
                executor.submit(encrypt_single, i, f[0], f[1]): f 
                for i, f in enumerate(self.files)
            }
            
            for future in as_completed(future_to_file):
                results.append(future.result())
        
        self.finished.emit(results)


class EncryptionDialog(QDialog):
    """Dialog for encrypting video files."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._files = [] # Stores keys (paths) to check duplicates
        self._task_list = [] # Stores (path, root_base) tuples
        self._output_folder = ""
        self._worker: Optional[EncryptionWorker] = None
        self._setup_ui()
        self.setModal(True)
        self.setMinimumSize(600, 500)
    
    def _setup_ui(self):
        """Setup the dialog UI."""
        self.setWindowTitle("加密文件")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Title
        title = QLabel("🔒 加密文件")
        title.setObjectName("encryptionTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        subtitle = QLabel("选择文件或文件夹进行加密，支持所有格式")
        subtitle.setObjectName("encryptionSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # File/Folder selection
        btn_layout = QHBoxLayout()
        
        self.btn_add_files = QPushButton("📁 添加文件")
        self.btn_add_files.clicked.connect(self._add_files)
        
        self.btn_add_folder = QPushButton("📂 添加文件夹")
        self.btn_add_folder.clicked.connect(self._add_folder)
        
        self.btn_clear = QPushButton("🗑️ 清空列表")
        self.btn_clear.clicked.connect(self._clear_files)
        
        btn_layout.addWidget(self.btn_add_files)
        btn_layout.addWidget(self.btn_add_folder)
        btn_layout.addWidget(self.btn_clear)
        
        # Filters and Options
        opt_layout = QHBoxLayout()
        
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["所有文件 (*.*)", "视频文件 (Video)", "图片文件 (Image)", "压缩包 (Archive)"])
        self.filter_combo.setToolTip("添加文件夹时的筛选类型")
        
        self.chk_recursive = QCheckBox("包含子文件夹")
        self.chk_recursive.setChecked(True)
        
        self.chk_delete = QCheckBox("加密后删除源文件")
        
        opt_layout.addWidget(QLabel("筛选:"))
        opt_layout.addWidget(self.filter_combo)
        opt_layout.addWidget(self.chk_recursive)
        opt_layout.addWidget(self.chk_delete)
        opt_layout.addStretch()
        
        # File list
        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(200)
        
        # Output folder selection
        output_layout = QHBoxLayout()
        
        self.output_label = QLabel("输出文件夹: (默认原目录)")
        self.output_label.setObjectName("subtitle")
        
        self.btn_output = QPushButton("选择输出位置")
        self.btn_output.clicked.connect(self._select_output)
        
        output_layout.addWidget(self.output_label, 1)
        output_layout.addWidget(self.btn_output)
        
        # Progress
        self.progress_label = QLabel("")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_label.hide()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        
        self.file_progress = QProgressBar()
        self.file_progress.hide()
        
        # Action buttons
        action_layout = QHBoxLayout()
        
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_encrypt = QPushButton("🔐 开始加密")
        self.btn_encrypt.setObjectName("accent")
        self.btn_encrypt.clicked.connect(self._start_encryption)
        
        action_layout.addStretch()
        action_layout.addWidget(self.btn_cancel)
        action_layout.addWidget(self.btn_encrypt)
        
        # Assemble
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(btn_layout)
        layout.addLayout(opt_layout)
        layout.addWidget(self.file_list)
        layout.addLayout(output_layout)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.file_progress)
        layout.addLayout(action_layout)
    
    def _add_files(self):
        """Add files."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择文件",
            "",
            "所有文件 (*.*)"
        )
        
        for file in files:
            path = str(Path(file))
            # Skip if already encrypted
            if is_encrypted_file(path):
                continue
                
            if path not in self._files:
                self._files.append(path)
                self._task_list.append((path, None)) # File has no root base implies flat
                
                item = QListWidgetItem(f"📄 {Path(file).name}")
                item.setData(Qt.ItemDataRole.UserRole, path)
                self.file_list.addItem(item)
    
    def _add_folder(self):
        """Add files from folder with filter."""
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if not folder:
            return
            
        recursive = self.chk_recursive.isChecked()
        filter_idx = self.filter_combo.currentIndex()
        # 0: All, 1: Video, 2: Image, 3: Archive
        
        root_path = Path(folder)
        iterator = root_path.rglob("*") if recursive else root_path.iterdir()
        
        count = 0
        for file in iterator:
            if file.is_file():
                path = str(file)
                
                # Skip if already encrypted
                if is_encrypted_file(path):
                    continue
                
                # Check filter
                match = True
                if filter_idx == 1: # Video
                    match = is_video_file(path)
                elif filter_idx == 2: # Image
                    match = is_image_file(path)
                elif filter_idx == 3: # Archive
                    match = is_archive_file(path)
                
                if match and path not in self._files:
                    self._files.append(path)
                    self._task_list.append((path, str(root_path))) # Store root for relative path
                    
                    item = QListWidgetItem(f"📄 {file.name}")
                    item.setData(Qt.ItemDataRole.UserRole, path)
                    self.file_list.addItem(item)
                    count += 1
                    
        if count == 0:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "提示", "未找到符合条件的文件")

    def _clear_files(self):
        """Clear the file list."""
        self._files.clear()
        self._task_list.clear()
        self.file_list.clear()

    def _select_output(self):
        """Select output folder."""
        folder = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        if folder:
            self._output_folder = folder
            self.output_label.setText(f"输出文件夹: {folder}")
    
    def _start_encryption(self):
        """Start the encryption process."""
        if not self._task_list:
            return
        
        # ... (rest same, update worker init)
        
        if not self._output_folder:
            # Default to same folder as first file
            # If structure preservation is used, this logic is tricky? 
            # worker checks output_folder. If None, it uses same parent.
            # But if a whole folder is added, users might expect in-place encryption?
            # Yes, if no output selected, encrypt in-place (next to original).
            self._output_folder = "" # Ensure empty string if None

        # Get password
        password, ok = PasswordDialog.get_new_password(
            self,
            title="设置加密密码",
            message="此密码用于加密和解密视频文件，请牢记"
        )
        
        if not ok:
            return
        
        # Disable UI
        self.btn_add_files.setEnabled(False)
        self.btn_add_folder.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.btn_output.setEnabled(False)
        self.btn_encrypt.setEnabled(False)
        self.filter_combo.setEnabled(False)
        self.chk_recursive.setEnabled(False)
        
        # Show progress
        self.progress_label.show()
        self.progress_bar.show()
        self.progress_bar.setMaximum(len(self._task_list))
        self.progress_bar.setValue(0)
        self.file_progress.show()
        
        # Start worker
        delete_source = self.chk_delete.isChecked()
        self._worker = EncryptionWorker(self._task_list, self._output_folder, password, delete_source)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_progress.connect(self._on_file_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()
    
    def _on_progress(self, filename: str, current: int, total: int):
        """Handle progress update."""
        self.progress_label.setText(f"正在加密: {filename} ({current}/{total})")
        self.progress_bar.setValue(current)
    
    def _on_file_progress(self, current: int, total: int):
        """Handle file progress update."""
        self.file_progress.setMaximum(total)
        self.file_progress.setValue(current)
    
    def _on_finished(self, results: list):
        """Handle encryption finished."""
        self.progress_label.hide() # progress_label text replaced by dialog
        self.file_progress.hide()
        
        # Reset UI state first
        self.btn_add_files.setEnabled(True)
        self.btn_add_folder.setEnabled(True)
        self.btn_clear.setEnabled(True)
        self.btn_output.setEnabled(True)
        self.btn_encrypt.setEnabled(True)
        self.filter_combo.setEnabled(True)
        self.chk_recursive.setEnabled(True)
        self.btn_encrypt.show() # In case hidden
        self.btn_cancel.setText("取消")
        
        from ui.widgets.result_report_dialog import ResultReportDialog
        dlg = ResultReportDialog(results, self)
        if dlg.exec():
            # Retry requested
            retry_list = dlg.retry_items
            if retry_list:
                # Reload UI with failed items
                self._clear_files()
                for path, root in retry_list:
                    if path not in self._files:
                        self._files.append(path)
                        self._task_list.append((path, root))
                        item = QListWidgetItem(f"📄 {Path(path).name}")
                        item.setData(Qt.ItemDataRole.UserRole, path)
                        self.file_list.addItem(item)
                
                # Auto start? Or let user click?
                # User click is safer.
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(self, "重试", f"已重新加载 {len(retry_list)} 个失败文件，请检查设置后点击加密。")

