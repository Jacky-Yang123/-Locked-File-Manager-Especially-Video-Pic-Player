"""
Generic file handler widget.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, 
    QFrame, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from pathlib import Path
import shutil

class GenericHandler(QWidget):
    """Generic handler for unsupported file types."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_file = None
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup UI."""
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)
        
        # Icon
        self.icon_label = QLabel("📦")
        self.icon_label.setStyleSheet("font-size: 80px;")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # File Name
        self.name_label = QLabel("Unknown File")
        self.name_label.setObjectName("title")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Info
        self.info_label = QLabel("Preview not available for this file type.")
        self.info_label.setObjectName("subtitle")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Export Button
        self.btn_export = QPushButton("📤 导出/另存为...")
        self.btn_export.setFixedWidth(200)
        self.btn_export.setObjectName("accent")
        self.btn_export.clicked.connect(self.export_file)
        
        layout.addWidget(self.icon_label)
        layout.addWidget(self.name_label)
        layout.addWidget(self.info_label)
        layout.addWidget(self.btn_export, 0, Qt.AlignmentFlag.AlignCenter)
    
    def load_file(self, file_path: str, original_ext: str = ""):
        """Load file info."""
        self.current_file = file_path
        self.original_ext = original_ext
        
        path = Path(file_path)
        self.name_label.setText(path.name)
        
        size = path.stat().st_size
        from utils.file_utils import format_size
        size_str = format_size(size)
        
        self.info_label.setText(f"Size: {size_str}\nType: {original_ext or path.suffix}")
    
    def export_file(self):
        """Export the file."""
        if not self.current_file:
            return
            
        default_name = Path(self.current_file).name
        # If it's a temp file processing an encrypted file, it might have weird name
        # But load_file passes the temp path usually.
        # Ideally we pass the Original Filename if it was encrypted.
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "另存为",
            default_name
        )
        
        if file_path:
            try:
                shutil.copy2(self.current_file, file_path)
                QMessageBox.information(self, "Success", f"File saved to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save file:\n{str(e)}")
