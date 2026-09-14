"""
Dialog to show encryption/decryption results with Retry capability.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, 
    QListWidgetItem, QPushButton, QWidget
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon, QColor, QBrush
from pathlib import Path

class ResultReportDialog(QDialog):
    def __init__(self, results, parent=None):
        """
        results: list of tuples (filename, success, msg_or_path, source_path, root_base)
        """
        super().__init__(parent)
        self.results = results
        self.retry_items = [] # List of (source_path, root_base)
        self._setup_ui()
        self.resize(600, 500)
        
    def _setup_ui(self):
        self.setWindowTitle("任务报告")
        layout = QVBoxLayout(self)
        
        # Header
        success_count = sum(1 for r in self.results if r[1])
        fail_count = len(self.results) - success_count
        
        header = QLabel(f"处理完成。成功: {success_count}，失败: {fail_count}")
        header.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {'#4CAF50' if fail_count == 0 else '#F44336'};")
        layout.addWidget(header)
        
        if fail_count > 0:
             hint = QLabel("提示: 双击列表项可打开所在文件夹。点击“重试失败项”可重新尝试。")
             hint.setStyleSheet("color: #888;")
             layout.addWidget(hint)
        
        # List
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)
        
        for res in self.results:
            # Unpack
            # (filename, success, output_path_or_msg, source_path, root_base)
            if len(res) >= 5:
                filename, success, msg, src, root = res
            else:
                # Fallback for old calls if any
                filename, success, msg = res[:3]
                src, root = None, None
                
            item = QListWidgetItem()
            
            if success:
                item.setText(f"✅ {filename}")
                item.setToolTip(f"输出: {msg}")
                # item.setForeground(QBrush(QColor("#4CAF50")))
            else:
                item.setText(f"❌ {filename} - {msg}")
                item.setToolTip(f"错误: {msg}\n源文件: {src}")
                item.setForeground(QBrush(QColor("#F44336")))
                
            item.setData(Qt.ItemDataRole.UserRole, src) # Source path for logic
            self.list_widget.addItem(item)
            
        self.list_widget.itemDoubleClicked.connect(self._on_item_dbl_click)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.reject)
        
        self.btn_retry = QPushButton("🔄 重试失败项")
        self.btn_retry.setObjectName("accent")
        self.btn_retry.clicked.connect(self._on_retry)
        
        if fail_count == 0:
            self.btn_retry.hide()
            
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_close)
        btn_layout.addWidget(self.btn_retry)
        
        layout.addLayout(btn_layout)
        
    def _on_item_dbl_click(self, item):
        img_path = item.data(Qt.ItemDataRole.UserRole)
        if img_path:
            folder = Path(img_path).parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
            
    def _on_retry(self):
        # Collect failed items
        for res in self.results:
            if not res[1]: # Failed
                if len(res) >= 5:
                    src, root = res[3], res[4]
                    self.retry_items.append((src, root))
        
        self.accept()
