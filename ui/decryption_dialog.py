"""
Decryption dialog for decrypting video files.
"""

import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QFrame, QFileDialog, QProgressBar,
    QListWidget, QListWidgetItem, QCheckBox, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QWaitCondition, QMutex
from pathlib import Path
from typing import Optional, List, Tuple

from core.crypto_engine import EncryptionEngine
from ui.password_dialog import PasswordDialog
from utils.file_utils import get_encrypted_files, is_encrypted_file, ensure_dir

class DecryptionWorker(QThread):
    """Worker thread for decryption tasks."""
    
    progress = pyqtSignal(str, int, int)  # filename, current, total
    file_progress = pyqtSignal(int, int)  # bytes processed, total bytes
    finished = pyqtSignal(list)  # results
    error = pyqtSignal(str)
    
    # Request password from UI: (filename)
    password_requested = pyqtSignal(str) 
    
    def __init__(self, files: List[Tuple[str, Optional[str]]], output_folder: str, initial_password: str, delete_source: bool = False):
        super().__init__()
        self.files = files # List of (path, root_base)
        self.output_folder = output_folder
        self.password = initial_password
        self.delete_source = delete_source
        
        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._new_password = None
        self._abort_file = False
    
    def provide_password(self, password: Optional[str]):
        """Called by UI to provide requested password."""
        self._mutex.lock()
        self._new_password = password
        self._cond.wakeAll()
        self._mutex.unlock()
    
    def run(self):
        """Run decryption in background."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        engine = EncryptionEngine()
        results = []
        max_workers = min(os.cpu_count() or 4, 8)
        
        completed = 0
        total = len(self.files)
        
        # Local mutex for progress update only (run_mutex) vs self._mutex for password
        # Actually self._mutex is fine if used carefully. Let's use QMutex for progress stats.
        progress_mutex = QMutex()
        
        def decrypt_single(file_path, root_base):
            nonlocal completed
            filename = Path(file_path).name
            
            # Helper to update progress
            def update_progress():
                nonlocal completed
                progress_mutex.lock()
                completed += 1
                self.progress.emit(filename, completed, total)
                progress_mutex.unlock()

            # Attempt loop
            # Use current password (snapshot)
            # Accessing self.password needs care? Strings are immutable, atomic read is fine in Python.
            current_password = self.password
            
            while True:
                try:
                    # Logic to determine output name:
                    from core.evf_format import read_evf_header
                    # Read header
                    try:
                        with open(file_path, 'rb') as f:
                            header = read_evf_header(f)
                            orig_ext = header.original_ext
                    except Exception as e:
                        raise e
                    
                    # Fix extension logic
                    p_file = Path(file_path)
                    base_name = p_file.stem
                    if orig_ext and not base_name.lower().endswith(orig_ext.lower()):
                        out_name = base_name + orig_ext
                    else:
                        out_name = base_name
                        if orig_ext and not out_name.endswith(orig_ext):
                             out_name += orig_ext
                    
                    # Calculate output path preserving structure
                    if self.output_folder:
                        if root_base:
                            try:
                                rel_path = Path(file_path).relative_to(root_base)
                                target_dir = Path(self.output_folder) / rel_path.parent
                                ensure_dir(str(target_dir))
                                output_path = str(target_dir / out_name)
                            except ValueError:
                                output_path = str(Path(self.output_folder) / out_name)
                        else:
                            output_path = str(Path(self.output_folder) / out_name)
                    else:
                         output_path = str(Path(file_path).parent / out_name)
                    
                    # Attempt decryption
                    engine.decrypt_file(
                        file_path, 
                        output_path, 
                        current_password,
                        None # Disable file progress
                    )
                    
                    # Update global password if successful and different?
                    if current_password != self.password:
                         self.password = current_password
                    
                    if self.delete_source and Path(output_path).exists():
                        try:
                            os.remove(file_path)
                        except: pass
                        
                    update_progress()
                    return (filename, True, output_path, file_path, root_base)
                    
                except ValueError as ve:
                    # Password error
                    # SIGNAL MAIN THREAD
                    self.password_requested.emit(filename)
                    
                    # WAIT
                    self._mutex.lock()
                    self._new_password = None
                    self._cond.wait(self._mutex)
                    user_pass = self._new_password
                    self._mutex.unlock()
                    
                    if user_pass:
                        current_password = user_pass
                    else:
                        update_progress()
                        return (filename, False, "Skipped by user or wrong password", file_path, root_base)
                        
                except Exception as e:
                    update_progress()
                    return (filename, False, str(e), file_path, root_base)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {
                executor.submit(decrypt_single, f[0], f[1]): f 
                for f in self.files
            }
            
            for future in as_completed(future_to_file):
                results.append(future.result())
        
        self.finished.emit(results)


class DecryptionDialog(QDialog):
    """Dialog for decrypting video files."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._files = []
        self._task_list = [] # (path, root_base)
        self._output_folder = ""
        self._worker: Optional[DecryptionWorker] = None
        self._setup_ui()
        self.setModal(True)
        self.setMinimumSize(600, 500)
    
    def _setup_ui(self):
        """Setup UI components."""
        self.setWindowTitle("批量文件解密 (Batch Decryption)")
        layout = QVBoxLayout(self)
        
        # File List
        list_layout = QVBoxLayout()
        list_layout.addWidget(QLabel("已选择文件:"))
        self.file_list = QListWidget()
        list_layout.addWidget(self.file_list)
        layout.addLayout(list_layout)
        
        # Buttons Area
        btn_layout = QHBoxLayout()
        
        self.btn_add_files = QPushButton("添加文件")
        self.btn_add_files.clicked.connect(self._add_files)
        
        self.btn_add_folder = QPushButton("添加文件夹")
        self.btn_add_folder.clicked.connect(self._add_folder)
        
        self.btn_clear = QPushButton("清空")
        self.btn_clear.clicked.connect(self._clear_files)
        
        btn_layout.addWidget(self.btn_add_files)
        btn_layout.addWidget(self.btn_add_folder)
        btn_layout.addWidget(self.btn_clear)
        layout.addLayout(btn_layout)
        
        # Options
        opts_layout = QVBoxLayout()
        
        self.chk_recursive = QCheckBox("递归扫描子文件夹")
        self.chk_recursive.setChecked(True)
        opts_layout.addWidget(self.chk_recursive)
        
        self.chk_delete = QCheckBox("解密后删除源文件")
        opts_layout.addWidget(self.chk_delete)
        
        # Output Folder
        out_layout = QHBoxLayout()
        self.output_label = QLabel("输出文件夹: [与源文件相同]")
        self.output_label.setWordWrap(True)
        self.btn_output = QPushButton("更改...")
        self.btn_output.clicked.connect(self._select_output)
        
        out_layout.addWidget(self.output_label, 1)
        out_layout.addWidget(self.btn_output)
        opts_layout.addLayout(out_layout)
        
        layout.addLayout(opts_layout)
        
        # Progress
        self.progress_label = QLabel("")
        self.progress_label.hide()
        layout.addWidget(self.progress_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        self.file_progress = QProgressBar()
        self.file_progress.hide()
        self.file_progress.setTextVisible(False)
        self.file_progress.setFixedHeight(5)
        layout.addWidget(self.file_progress)
        
        # Action Buttons
        action_layout = QHBoxLayout()
        action_layout.addStretch()
        
        self.btn_cancel = QPushButton("取消") # Close
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_decrypt = QPushButton("开始解密")
        self.btn_decrypt.clicked.connect(self._start_decryption)
        self.btn_decrypt.setStyleSheet("background-color: #2E8B57; color: white; font-weight: bold; padding: 6px 12px;")
        
        action_layout.addWidget(self.btn_cancel)
        action_layout.addWidget(self.btn_decrypt)
        
        layout.addLayout(action_layout)

    def _add_files(self):
        """Add files."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择加密文件",
            "",
            "加密视频 (*.evf);;所有文件 (*.*)"
        )
        
        for file in files:
            file_p = str(Path(file))
            if is_encrypted_file(file_p) and file_p not in self._files:
                self._files.append(file_p)
                self._task_list.append((file_p, None))
                item = QListWidgetItem(f"🔒 {Path(file).name}")
                item.setData(Qt.ItemDataRole.UserRole, file_p)
                self.file_list.addItem(item)
    
    def _add_folder(self):
        """Add all files from a folder."""
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            root_path = Path(folder)
            recursive = self.chk_recursive.isChecked()
            
            # Manual walk to capture root logic
            if recursive:
                iterator = root_path.rglob("*")
            else:
                iterator = root_path.iterdir()
                
            enc_files = []
            for file in iterator:
                if file.is_file():
                    p = str(file)
                    if is_encrypted_file(p):
                        enc_files.append(p)
            
            for file in enc_files:
                if file not in self._files:
                    self._files.append(file)
                    self._task_list.append((file, str(root_path))) # Capture root!
                    
                    item = QListWidgetItem(f"🔒 {Path(file).name}")
                    item.setData(Qt.ItemDataRole.UserRole, file)
                    self.file_list.addItem(item)
    
    def _clear_files(self):
        """Clear the file list."""
        self._files.clear()
        self._task_list.clear()
        self.file_list.clear()
        
    # ... _select_output, _start ...

    
    def _select_output(self):
        """Select output folder."""
        folder = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        if folder:
            self._output_folder = folder
            self.output_label.setText(f"输出文件夹: {folder}")
    
    def _start_decryption(self):
        """Start the decryption process."""
        if not self._files:
            return
        
        # Output folder default
        if not self._output_folder:
            self._output_folder = str(Path(self._files[0]).parent)
        
        # Get password
        password, ok = PasswordDialog.get_password_dialog(
            self,
            title="输入解密密码",
            message="请输入文件加密时设置的密码:"
        )
        
        if not ok or not password:
            return
        
        # Disable UI
        self.btn_add_files.setEnabled(False)
        self.btn_add_folder.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.btn_output.setEnabled(False)
        self.btn_decrypt.setEnabled(False)
        
        # Show progress
        self.progress_label.show()
        self.progress_bar.show()
        self.progress_bar.setMaximum(len(self._files))
        self.progress_bar.setValue(0)
        self.file_progress.show()
        
        # Start worker
        delete_source = self.chk_delete.isChecked()
        self._worker = DecryptionWorker(self._task_list, self._output_folder, password, delete_source)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_progress.connect(self._on_file_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.password_requested.connect(self._on_password_requested)
        self._worker.start()
    
    def _on_password_requested(self, filename: str):
        """
        Handle password request from worker (wrong password encountered).
        """
        password, ok = PasswordDialog.get_password_dialog(
            self,
            title="密码错误",
            message=f"文件 '{filename}' 解密失败，密码错误。\n请输入该文件的正确密码 (取消则跳过此文件):"
        )
        
        if ok and password:
            self._worker.provide_password(password)
        else:
            self._worker.provide_password(None) # Signal skip
    
    def _on_progress(self, filename: str, current: int, total: int):
        """Handle progress update."""
        self.progress_label.setText(f"正在解密: {filename} ({current}/{total})")
        self.progress_bar.setValue(current)
    
    def _on_file_progress(self, current: int, total: int):
        """Handle file progress update."""
        self.file_progress.setMaximum(total)
        self.file_progress.setValue(current)
    
    def _on_finished(self, results: list):
        """Handle decryption finished."""
        self.progress_label.hide()
        self.file_progress.hide()
        
        # Reset UI state
        self.btn_add_files.setEnabled(True)
        self.btn_add_folder.setEnabled(True)
        self.btn_clear.setEnabled(True)
        self.btn_output.setEnabled(True)
        self.btn_decrypt.setEnabled(True)
        self.btn_decrypt.show()
        self.btn_cancel.setText("取消")
        
        from ui.widgets.result_report_dialog import ResultReportDialog
        dlg = ResultReportDialog(results, self)
        if dlg.exec():
            # Retry requested
            retry_list = dlg.retry_items
            if retry_list:
                self._clear_files()
                for path, root in retry_list:
                    if path not in self._files:
                        self._files.append(path)
                        self._task_list.append((path, root))
                        item = QListWidgetItem(f"🔒 {Path(path).name}")
                        item.setData(Qt.ItemDataRole.UserRole, path)
                        self.file_list.addItem(item)
                
                QMessageBox.information(self, "重试", f"已重新加载 {len(retry_list)} 个失败文件，请检查密码后点击解密。")
