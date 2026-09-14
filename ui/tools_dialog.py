import os
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFileDialog, QTabWidget, QWidget, 
                             QLineEdit, QProgressBar, QMessageBox, QComboBox, QCheckBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from core.crypto_engine import EncryptionEngine
from core.evf_format import EVFHeader, detect_mixed_file, MIXED_MAGIC, MIXED_FOOTER_SIZE
import struct

class WorkerThread(QThread):
    progress = pyqtSignal(int, int, str, str) # current, total, type ('file' or 'batch'), msg
    finished = pyqtSignal(bool, str)

    def __init__(self, func, *args):
        super().__init__()
        self.func = func
        self.args = args

    def run(self):
        try:
            self.func(*self.args, progress_callback=self.report_progress)
            self.finished.emit(True, "操作成功")
        except Exception as e:
            self.finished.emit(False, str(e))

    def report_progress(self, current, total, type="file", msg=""):
        self.progress.emit(current, total, type, msg)

class ToolsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔐 加密工具箱")
        self.setMinimumSize(500, 450)
        
        layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_encrypt_tab(), "常规加密 (单文件)")
        self.tabs.addTab(self._create_batch_encrypt_tab(), "批量加密 (文件夹)")
        self.tabs.addTab(self._create_mixed_tab(), "混图加密 (单文件)")
        self.tabs.addTab(self._create_batch_mixed_tab(), "批量混图 (文件夹)")
        self.tabs.addTab(self._create_decrypt_tab(), "解密/提取 (单文件)")
        self.tabs.addTab(self._create_batch_decrypt_tab(), "批量解密 (文件夹)")
        
        layout.addWidget(self.tabs)
        
        # Status Label
        self.status_label = QLabel("就绪")
        layout.addWidget(self.status_label)
        
        # Batch Progress Bar
        self.batch_progress = QProgressBar()
        self.batch_progress.setFormat("总进度: %p% (%v/%m)")
        self.batch_progress.setVisible(False)
        layout.addWidget(self.batch_progress)
        
        # File Progress Bar
        self.file_progress = QProgressBar()
        self.file_progress.setVisible(False)
        layout.addWidget(self.file_progress)
        
        self.engine = EncryptionEngine()

    def _create_encrypt_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Input
        file_layout = QHBoxLayout()
        self.enc_input = QLineEdit()
        self.enc_input.setPlaceholderText("选择要加密的视频文件...")
        btn = QPushButton("浏览")
        btn.clicked.connect(lambda: self._browse_file(self.enc_input))
        file_layout.addWidget(self.enc_input)
        file_layout.addWidget(btn)
        layout.addLayout(file_layout)
        
        # Password
        self.enc_pwd = QLineEdit()
        self.enc_pwd.setPlaceholderText("设置加密密码")
        self.enc_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.enc_pwd)
        
        # Action
        action_btn = QPushButton("🔒 开始加密 (.evf)")
        action_btn.clicked.connect(self._start_standard_encrypt)
        layout.addWidget(action_btn)
        layout.addStretch()
        return widget

    def _create_batch_encrypt_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        label = QLabel("批量将文件夹内的文件加密为 .evf 格式。")
        label.setWordWrap(True)
        layout.addWidget(label)
        
        # Source Folder
        f_layout = QHBoxLayout()
        self.batch_enc_src = QLineEdit()
        self.batch_enc_src.setPlaceholderText("选择要加密的文件夹...")
        f_btn = QPushButton("浏览文件夹")
        f_btn.clicked.connect(lambda: self._browse_folder(self.batch_enc_src))
        f_layout.addWidget(self.batch_enc_src)
        f_layout.addWidget(f_btn)
        layout.addLayout(f_layout)
        
        # File Types
        type_label = QLabel("选择要加密的文件类型:")
        layout.addWidget(type_label)
        
        type_layout = QHBoxLayout()
        self.cb_video = QCheckBox("视频")
        self.cb_video.setChecked(True)
        self.cb_image = QCheckBox("图片")
        self.cb_audio = QCheckBox("音频")
        self.cb_pdf = QCheckBox("PDF")
        self.cb_archive = QCheckBox("压缩包")
        self.cb_text = QCheckBox("文本")
        self.cb_other = QCheckBox("其他(未加密文件)")
        
        type_layout.addWidget(self.cb_video)
        type_layout.addWidget(self.cb_image)
        type_layout.addWidget(self.cb_audio)
        type_layout.addWidget(self.cb_pdf)
        type_layout.addWidget(self.cb_archive)
        type_layout.addWidget(self.cb_text)
        type_layout.addWidget(self.cb_other)
        layout.addLayout(type_layout)
        
        # Password
        self.batch_enc_pwd = QLineEdit()
        self.batch_enc_pwd.setPlaceholderText("设置加密密码")
        self.batch_enc_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.batch_enc_pwd)
        
        # Delete Original Checkbox
        self.batch_enc_del = QCheckBox("处理成功后删除原文件 (安全校验大小)")
        layout.addWidget(self.batch_enc_del)
        
        # Action
        action_btn = QPushButton("🔒 开始批量加密")
        action_btn.clicked.connect(self._start_batch_encrypt)
        layout.addWidget(action_btn)
        layout.addStretch()
        return widget
        
    def _create_batch_mixed_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        label = QLabel("批量将文件夹内的视频/EVF文件隐藏到同一张图片中。")
        label.setWordWrap(True)
        layout.addWidget(label)
        
        # Source Folder
        f_layout = QHBoxLayout()
        self.batch_src = QLineEdit()
        self.batch_src.setPlaceholderText("1. 选择包含视频/EVF的文件夹...")
        f_btn = QPushButton("浏览文件夹")
        f_btn.clicked.connect(lambda: self._browse_folder(self.batch_src))
        f_layout.addWidget(self.batch_src)
        f_layout.addWidget(f_btn)
        layout.addLayout(f_layout)
        
        # Cover Image
        i_layout = QHBoxLayout()
        self.batch_img = QLineEdit()
        self.batch_img.setPlaceholderText("2. 选择通用封面图片...")
        i_btn = QPushButton("浏览图片")
        i_btn.clicked.connect(lambda: self._browse_file(self.batch_img, "Images (*.jpg *.jpeg *.png)"))
        i_layout.addWidget(self.batch_img)
        i_layout.addWidget(i_btn)
        layout.addLayout(i_layout)
        
        # Password (Optional)
        self.batch_pwd = QLineEdit()
        self.batch_pwd.setPlaceholderText("设置加密密码 (仅用于未加密的视频)")
        self.batch_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.batch_pwd)
        
        # Delete Original Checkbox
        self.batch_mix_del = QCheckBox("处理成功后删除原文件 (安全校验大小)")
        layout.addWidget(self.batch_mix_del)
        
        # Action
        action_btn = QPushButton("🚀 开始批量混图")
        action_btn.clicked.connect(self._start_batch_mixed)
        layout.addWidget(action_btn)
        layout.addStretch()
        return widget

    def _create_mixed_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        label = QLabel("将加密视频隐藏在普通图片中，表面是图片，实际可播放。")
        label.setWordWrap(True)
        layout.addWidget(label)
        
        # Video Input
        v_layout = QHBoxLayout()
        self.mix_video = QLineEdit()
        self.mix_video.setPlaceholderText("1. 选择视频源文件...")
        v_btn = QPushButton("浏览视频")
        v_btn.clicked.connect(lambda: self._browse_file(self.mix_video, "Videos (*.mp4 *.mkv *.mov *.avi)"))
        v_layout.addWidget(self.mix_video)
        v_layout.addWidget(v_btn)
        layout.addLayout(v_layout)
        
        # Image Input
        i_layout = QHBoxLayout()
        self.mix_image = QLineEdit()
        self.mix_image.setPlaceholderText("2. 选择伪装图片 (封面)...")
        i_btn = QPushButton("浏览图片")
        i_btn.clicked.connect(lambda: self._browse_file(self.mix_image, "Images (*.jpg *.jpeg *.png)"))
        i_layout.addWidget(self.mix_image)
        i_layout.addWidget(i_btn)
        layout.addLayout(i_layout)
        
        # Password
        self.mix_pwd = QLineEdit()
        self.mix_pwd.setPlaceholderText("设置加密密码")
        self.mix_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.mix_pwd)
        
        # Action
        action_btn = QPushButton("🖼️ 生成混图文件 (.jpg)")
        action_btn.clicked.connect(self._start_mixed_encrypt)
        layout.addWidget(action_btn)
        layout.addStretch()
        return widget
        
    def _browse_folder(self, line_edit):
        path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if path:
            line_edit.setText(path)

    def _create_decrypt_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Input
        file_layout = QHBoxLayout()
        self.dec_input = QLineEdit()
        self.dec_input.setPlaceholderText("选择加密文件 (.evf 或 混图.jpg)...")
        btn = QPushButton("浏览")
        btn.clicked.connect(lambda: self._browse_file(self.dec_input, "Encrypted (*.evf *.jpg *.jpeg *.png)"))
        file_layout.addWidget(self.dec_input)
        file_layout.addWidget(btn)
        layout.addLayout(file_layout)
        
        # Password
        self.dec_pwd = QLineEdit()
        self.dec_pwd.setPlaceholderText("输入解密密码")
        self.dec_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.dec_pwd)
        
        # Actions
        btn_layout = QHBoxLayout()
        
        dec_btn = QPushButton("🔓 解密还原")
        dec_btn.clicked.connect(self._start_decrypt)
        btn_layout.addWidget(dec_btn)
        
        extract_btn = QPushButton("📤 提取EVF (仅混图)")
        extract_btn.clicked.connect(self._start_extract)
        btn_layout.addWidget(extract_btn)
        
        layout.addLayout(btn_layout)
        layout.addStretch()
        return widget

    def _create_batch_decrypt_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        label = QLabel("批量解密文件夹内的加密视频或混图，恢复为原始文件。")
        label.setWordWrap(True)
        layout.addWidget(label)
        
        # Source Folder
        f_layout = QHBoxLayout()
        self.batch_dec_src = QLineEdit()
        self.batch_dec_src.setPlaceholderText("选择包含 .evf 或混图 .jpg 的文件夹...")
        f_btn = QPushButton("浏览文件夹")
        f_btn.clicked.connect(lambda: self._browse_folder(self.batch_dec_src))
        f_layout.addWidget(self.batch_dec_src)
        f_layout.addWidget(f_btn)
        layout.addLayout(f_layout)
        
        # Password
        self.batch_dec_pwd = QLineEdit()
        self.batch_dec_pwd.setPlaceholderText("输入解密密码")
        self.batch_dec_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.batch_dec_pwd)
        
        # Delete Original Checkbox
        self.batch_dec_del = QCheckBox("处理成功后删除原文件 (安全校验大小)")
        layout.addWidget(self.batch_dec_del)
        
        # Action
        action_btn = QPushButton("🔓 开始批量解密")
        action_btn.clicked.connect(self._start_batch_decrypt)
        layout.addWidget(action_btn)
        layout.addStretch()
        return widget

    def _browse_file(self, line_edit, filter="All Files (*)"):
        path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", filter)
        if path:
            line_edit.setText(path)

    def _toggle_ui(self, enable):
        self.tabs.setEnabled(enable)
        if enable:
            self.batch_progress.setVisible(False)
            self.file_progress.setVisible(False)
        else:
            self.batch_progress.setVisible(True)
            self.batch_progress.setValue(0)
            self.file_progress.setVisible(True)
            self.file_progress.setValue(0)

    # ... (other methods) ...
    
    def _run_worker(self, func, *args):
        self._toggle_ui(False)
        self.thread = WorkerThread(func, *args)
        self.thread.progress.connect(self._update_progress)
        self.thread.finished.connect(self._on_finished)
        self.thread.start()
        
    def _update_progress(self, current, total, type, msg):
        if msg:
            self.status_label.setText(msg)
            
        if type == "batch":
            self.batch_progress.setMaximum(total)
            self.batch_progress.setValue(current)
        else:
            self.file_progress.setMaximum(total)
            self.file_progress.setValue(current)

    # --- Logic ---
    
    def safe_delete_original(self, original_path, generated_path, operation_type):
        try:
            if not os.path.exists(generated_path):
                return False
            gen_size = os.path.getsize(generated_path)
            orig_size = os.path.getsize(original_path)
            
            should_delete = False
            if operation_type == 'encrypt':
                # EVF size is always larger than original due to headers and tags
                if gen_size >= orig_size and gen_size > 0:
                    should_delete = True
            elif operation_type == 'mixed':
                if gen_size > orig_size and gen_size > 0:
                    should_delete = True
            elif operation_type == 'decrypt':
                # Decrypted file must be smaller or equal, and > 0
                if orig_size >= gen_size and gen_size > 0:
                    should_delete = True
                    
            if should_delete:
                os.remove(original_path)
                return True
        except Exception as e:
            print(f"Failed to safe delete {original_path}: {e}")
        return False

    def _start_standard_encrypt(self):
        input_path = self.enc_input.text()
        pwd = self.enc_pwd.text()
        if not input_path or not os.path.exists(input_path):
            QMessageBox.warning(self, "错误", "请选择有效的文件")
            return
        if not pwd:
            QMessageBox.warning(self, "错误", "请输入密码")
            return
            
        output_path, _ = QFileDialog.getSaveFileName(self, "保存为", input_path + ".evf", "Encrypted Video (*.evf)")
        if not output_path:
            return

        self._run_worker(self.engine.encrypt_file, input_path, output_path, pwd)

    def _start_batch_encrypt(self):
        src_folder = self.batch_enc_src.text()
        pwd = self.batch_enc_pwd.text()
        delete_orig = self.batch_enc_del.isChecked()
        
        if not src_folder or not os.path.exists(src_folder):
            QMessageBox.warning(self, "错误", "请选择有效的源文件夹")
            return
        if not pwd:
            QMessageBox.warning(self, "错误", "请输入密码")
            return
            
        # Determine selected extensions
        exts = set()
        if self.cb_video.isChecked():
            exts.update(['.mp4', '.mkv', '.mov', '.avi', '.webm', '.flv'])
        if self.cb_image.isChecked():
            exts.update(['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.heic'])
        if self.cb_audio.isChecked():
            exts.update(['.mp3', '.wav', '.flac', '.aac', '.m4a', '.ogg'])
        if self.cb_pdf.isChecked():
            exts.add('.pdf')
        if self.cb_archive.isChecked():
            exts.update(['.zip', '.rar', '.7z', '.tar', '.gz'])
        if self.cb_text.isChecked():
            exts.update(['.txt', '.md', '.json', '.xml', '.csv'])
            
        include_other = self.cb_other.isChecked()
            
        if not exts and not include_other:
            QMessageBox.warning(self, "错误", "至少选择一种文件类型")
            return
            
        self._run_worker(self._process_batch_encrypt, src_folder, pwd, delete_orig, exts, include_other)

    def _process_batch_encrypt(self, src_folder, pwd, delete_orig, exts, include_other, progress_callback=None):
        files = []
        for root, dirs, filenames in os.walk(src_folder):
            for f in filenames:
                path = os.path.join(root, f)
                ext = os.path.splitext(f)[1].lower()
                # Exclude already encrypted formats
                if ext == '.evf':
                    continue
                if ext in exts or (include_other and ext not in exts):
                    from core.evf_format import detect_mixed_file
                    if detect_mixed_file(path) == -1:
                        files.append(path)
        
        if not files:
            raise Exception("文件夹内没有找到符合条件的文件")
            
        processed_count = 0
        total_files = len(files)
        
        for i, file_path in enumerate(files):
            filename = os.path.basename(file_path)
            if progress_callback:
                progress_callback(i, total_files, type="batch", msg=f"正在递归加密 ({i+1}/{total_files}): {filename}")
                
            try:
                # Output in place: base_no_ext.evf
                dir_name = os.path.dirname(file_path)
                base_name = os.path.splitext(filename)[0]
                output_path = os.path.join(dir_name, base_name + ".evf")
                
                # Check for name collision
                if output_path == file_path:
                    output_path = file_path + ".new.evf"

                # Wrapper for file progress
                def file_progress_cb(c, t):
                    if progress_callback:
                        progress_callback(c, t, type="file")
                
                # Encrypt
                self.engine.encrypt_file(file_path, output_path, pwd, progress_callback=file_progress_cb)
                
                if delete_orig:
                    self.safe_delete_original(file_path, output_path, 'encrypt')
                    
                processed_count += 1
                
            except Exception as e:
                print(f"Failed to encrypt {filename}: {e}")
                pass
                
        if processed_count == 0:
            raise Exception("没有文件处理成功")

    def _start_mixed_encrypt(self):
        video_path = self.mix_video.text()
        image_path = self.mix_image.text()
        pwd = self.mix_pwd.text()
        
        if not all([video_path, image_path, pwd]):
            QMessageBox.warning(self, "提示", "请填写所有字段")
            return
            
        output_path, _ = QFileDialog.getSaveFileName(self, "保存混图", image_path, "Images (*.jpg *.png)")
        if not output_path:
            return
            
        self._run_worker(self._process_mixed, video_path, image_path, output_path, pwd)

    def _start_batch_mixed(self):
        src_folder = self.batch_src.text()
        cover_img = self.batch_img.text()
        pwd = self.batch_pwd.text()
        delete_orig = self.batch_mix_del.isChecked()
        
        if not src_folder or not os.path.exists(src_folder):
            QMessageBox.warning(self, "错误", "请选择有效的源文件夹")
            return
        if not cover_img or not os.path.exists(cover_img):
            QMessageBox.warning(self, "错误", "请选择有效的封面图片")
            return
            
        self._run_worker(self._process_batch_mixed, src_folder, cover_img, pwd, delete_orig)

    def _process_batch_mixed(self, src_folder, cover_img, pwd, delete_orig, progress_callback=None):
        from utils.file_utils import get_video_files
        import shutil
        
        # 1. Get all supported files recursively
        files = []
        for root, dirs, filenames in os.walk(src_folder):
            for f in filenames:
                path = os.path.join(root, f)
                # Accepts video files or already encrypted .evf files
                if f.lower().endswith(('.mp4', '.mkv', '.mov', '.avi', '.evf')):
                    files.append(path)
        
        if not files:
            raise Exception("文件夹内没有找到支持的视频或EVF文件")
            
        # Read cover image once
        with open(cover_img, 'rb') as f:
            cover_data = f.read()
            
        processed_count = 0
        total_files = len(files)
        
        for i, file_path in enumerate(files):
            filename = os.path.basename(file_path)
            if progress_callback:
                progress_callback(i, total_files, type="batch", msg=f"正在递归混图 ({i+1}/{total_files}): {filename}")
                
            try:
                # Determine source for mixing
                evf_path = file_path
                temp_created = False
                dir_name = os.path.dirname(file_path)
                
                # Wrapper for file progress
                def file_progress_cb(c, t):
                    if progress_callback:
                        progress_callback(c, t, type="file")
                
                # If video, encrypt first
                if not file_path.lower().endswith('.evf'):
                    if not pwd:
                        raise Exception(f"文件 {filename} 需要密码进行加密")
                    
                    temp_evf = os.path.join(dir_name, f"temp_{i}_{filename}.evf")
                    self.engine.encrypt_file(file_path, temp_evf, pwd, progress_callback=file_progress_cb)
                    evf_path = temp_evf
                    temp_created = True
                else:
                    # If already EVF, just report full progress for this file
                    if progress_callback:
                        s = os.path.getsize(file_path)
                        progress_callback(s, s, type="file")
                
                # Determine output name (.jpg)
                base_name = filename
                if base_name.lower().endswith('.evf'):
                    base_name = base_name[:-4]
                if base_name.lower().endswith(('.mp4', '.mkv', '.mov', '.avi')):
                    base_name = os.path.splitext(base_name)[0]
                    
                output_path = os.path.join(dir_name, base_name + ".jpg")
                
                # Mix Logic
                with open(evf_path, 'rb') as f_evf:
                    evf_data = f_evf.read()
                    
                offset = len(cover_data)
                
                with open(output_path, 'wb') as f_out:
                    f_out.write(cover_data)
                    f_out.write(evf_data)
                    # Footer
                    f_out.write(struct.pack('<Q', offset))
                    f_out.write(MIXED_MAGIC)
                    
                # Cleanup temp
                if temp_created and os.path.exists(evf_path):
                    os.remove(evf_path)
                    
                if delete_orig:
                    self.safe_delete_original(file_path, output_path, 'mixed')
                    
                processed_count += 1
                
            except Exception as e:
                print(f"Failed to process {filename}: {e}")
                pass
                
        if processed_count == 0:
            raise Exception("所有文件处理失败，请检查密码或文件格式")

    def _start_decrypt(self):
        input_path = self.dec_input.text()
        pwd = self.dec_pwd.text()
        
        if not input_path or not pwd:
            return
            
        # Determine output name
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        output_path, _ = QFileDialog.getSaveFileName(self, "解密为", base_name + "_decrypted.mp4", "Video Files (*.mp4 *.mkv *.mov)")
        if not output_path:
            return
            
        self._run_worker(self.engine.decrypt_file, input_path, output_path, pwd)
        
    def _start_extract(self):
        input_path = self.dec_input.text()
        
        offset = detect_mixed_file(input_path)
        if offset < 0:
            QMessageBox.warning(self, "错误", "这不是一个有效的混图加密文件")
            return
            
        output_path, _ = QFileDialog.getSaveFileName(self, "提取为", input_path + ".evf", "Encrypted Video (*.evf)")
        if not output_path:
            return
            
        # Extract logic
        self._run_worker(self._process_extract, input_path, output_path, offset)

    def _start_batch_decrypt(self):
        src_folder = self.batch_dec_src.text()
        pwd = self.batch_dec_pwd.text()
        delete_orig = self.batch_dec_del.isChecked()
        
        if not src_folder or not os.path.exists(src_folder):
            QMessageBox.warning(self, "错误", "请选择有效的源文件夹")
            return
        if not pwd:
            QMessageBox.warning(self, "错误", "请输入密码")
            return
            
        self._run_worker(self._process_batch_decrypt, src_folder, pwd, delete_orig)

    def _process_batch_decrypt(self, src_folder, pwd, delete_orig, progress_callback=None):
        files = []
        for root, dirs, filenames in os.walk(src_folder):
            for f in filenames:
                path = os.path.join(root, f)
                # Accepts .evf or potential mixed files (.jpg, .png, .jpeg)
                if f.lower().endswith(('.evf', '.jpg', '.jpeg', '.png')):
                    files.append(path)
        
        if not files:
            raise Exception("文件夹内没有找到支持的文件 (.evf, .jpg, .png)")
            
        processed_count = 0
        total_files = len(files)
        
        for i, file_path in enumerate(files):
            filename = os.path.basename(file_path)
            if progress_callback:
                progress_callback(i, total_files, type="batch", msg=f"正在递归解密 ({i+1}/{total_files}): {filename}")
                
            try:
                # Need to read header to get original extension
                from core.evf_format import read_evf_header, detect_mixed_file
                
                offset = detect_mixed_file(file_path)
                # If it's an image but offset is -1, it's not a mixed file, skip.
                if file_path.lower().endswith(('.jpg', '.jpeg', '.png')) and offset == -1:
                    continue
                    
                start_pos = 0 if offset == -1 else offset
                
                # Check header to extract extension
                with open(file_path, 'rb') as f:
                    f.seek(start_pos)
                    header = read_evf_header(f)
                    
                original_ext = header.original_ext
                if not original_ext:
                    original_ext = ".mp4"
                    
                # output name in same dir
                dir_name = os.path.dirname(file_path)
                base_name = filename
                if base_name.lower().endswith(('.evf', '.jpg', '.jpeg', '.png')):
                    base_name = os.path.splitext(base_name)[0]
                    
                output_path = os.path.join(dir_name, base_name + original_ext)
                
                # Wrapper for file progress
                def file_progress_cb(c, t):
                    if progress_callback:
                        progress_callback(c, t, type="file")
                
                # Decrypt file
                success = self.engine.decrypt_file(file_path, output_path, pwd, progress_callback=file_progress_cb)
                if success:
                    if delete_orig:
                        self.safe_delete_original(file_path, output_path, 'decrypt')
                    processed_count += 1
                
            except Exception as e:
                print(f"Failed to decrypt {filename}: {e}")
                pass
                
        if processed_count == 0:
            raise Exception("没有文件被成功解密，请检查密码或文件格式。")

    def _process_extract(self, input_path, output_path, offset, progress_callback=None):
        total_size = os.path.getsize(input_path)
        # Size of EVF data = Total - Offset - Footer
        evf_size = total_size - offset - MIXED_FOOTER_SIZE
        
        with open(input_path, 'rb') as f_in, open(output_path, 'wb') as f_out:
            f_in.seek(offset)
            written = 0
            chunk_size = 64 * 1024
            while written < evf_size:
                to_read = min(chunk_size, evf_size - written)
                data = f_in.read(to_read)
                if not data: break
                f_out.write(data)
                written += len(data)
                if progress_callback:
                    progress_callback(written, evf_size, type="file")

    def _run_worker(self, func, *args):
        self._toggle_ui(False)
        self.thread = WorkerThread(func, *args)
        self.thread.progress.connect(self._update_progress)
        self.thread.finished.connect(self._on_finished)
        self.thread.start()
        
    def _update_progress(self, current, total, type, msg):
        if msg:
            self.status_label.setText(msg)
            
        if type == "batch":
            self.batch_progress.setMaximum(total)
            self.batch_progress.setValue(current)
        else:
            self.file_progress.setMaximum(total)
            self.file_progress.setValue(current)
            
    def _on_finished(self, success, msg):
        self._toggle_ui(True)
        if success:
            QMessageBox.information(self, "成功", msg)
            self.status_label.setText(msg)
        else:
            QMessageBox.critical(self, "失败", msg)
            self.status_label.setText("操作失败")
