"""
Text viewer widget.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QHBoxLayout, 
    QPushButton, QLabel, QFrame, QComboBox, QMessageBox
)
from PyQt6.QtGui import QFont

from ui.password_dialog import PasswordDialog
from core.evf_format import is_evf_file
from core.stream_decoder import StreamDecoder

class TextViewer(QWidget):
    """Text viewer with markdown support."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Toolbar
        self.toolbar = QFrame()
        self.toolbar.setObjectName("controlBar")
        toolbar_layout = QHBoxLayout(self.toolbar)
        
        self.font_combo = QComboBox()
        self.font_combo.addItems(["12", "14", "16", "18", "24"])
        self.font_combo.setCurrentText("14")
        self.font_combo.currentTextChanged.connect(self._change_font_size)
        
        self.mode_btn = QPushButton("Markdown View")
        self.mode_btn.setCheckable(True)
        self.mode_btn.toggled.connect(self._toggle_mode)
        
        self.edit_btn = QPushButton("✏️ Edit")
        self.edit_btn.setCheckable(True)
        self.edit_btn.toggled.connect(self._toggle_edit_mode)
        
        self.save_btn = QPushButton("💾 Save")
        self.save_btn.clicked.connect(self._save_file)
        self.save_btn.setEnabled(False)
        
        toolbar_layout.addWidget(QLabel("Font Size:"))
        toolbar_layout.addWidget(self.font_combo)
        toolbar_layout.addWidget(self.mode_btn)
        toolbar_layout.addSpacing(20)
        toolbar_layout.addWidget(self.edit_btn)
        toolbar_layout.addWidget(self.save_btn)
        toolbar_layout.addStretch()
        
        # Text Editor
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #e0e0e0;
                border: none;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 14px;
                padding: 20px;
            }
        """)
        self.text_edit.textChanged.connect(self._on_text_changed)
        
        # Track file path and modified state
        self._current_path = None
        self._is_modified = False
        self._is_encrypted = False
        
        layout.addWidget(self.text_edit)
        layout.addWidget(self.toolbar)
    
    def open_file(self, file_path: str):
        """Open text file."""
        self._is_modified = False
        self.save_btn.setEnabled(False)
        self.edit_btn.setChecked(False)
        
        if is_evf_file(file_path):
            self._is_encrypted = True
            self._current_path = file_path
            self._open_encrypted(file_path)
        else:
            self._is_encrypted = False
            self._current_path = file_path
            self._load_text_from_path(file_path)

    def _open_encrypted(self, file_path: str):
        """Open encrypted text."""
        password, ok = PasswordDialog.get_password_dialog(
            self,
            title="🔐 需要密码",
            message="此文本已加密，请输入密码解锁"
        )
        if not ok:
            return

        try:
            import tempfile
            from core.crypto_engine import EncryptionEngine
            from core.evf_format import read_evf_header
            
            # Get original extension from header
            with open(file_path, 'rb') as f:
                header = read_evf_header(f)
            original_ext = header.original_ext or '.txt'
            
            # Create temp file with correct extension
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=original_ext)
            temp_path = temp_file.name
            temp_file.close()
            
            # Decrypt to temp file
            engine = EncryptionEngine()
            engine.decrypt_file(file_path, temp_path, password)
            
            # Store temp path for cleanup
            self._temp_file_path = temp_path
            
            is_md = original_ext.lower() in ['.md', '.markdown']
            self._load_text_from_path(temp_path, is_md=is_md)
            
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to decrypt text: {e}")

    def _load_text_from_path(self, file_path: str, is_md=False):
        """Load text from file."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                self.content = f.read()
                
            self.text_edit.setPlainText(self.content)
            
            # Auto-enable markdown for .md
            if is_md or file_path.lower().endswith('.md'):
                self.mode_btn.setChecked(True)
                self.text_edit.setMarkdown(self.content)
            else:
                self.mode_btn.setChecked(False)
                
        except Exception as e:
            self.text_edit.setPlainText(f"Error loading file: {str(e)}")
    
    def _change_font_size(self, size_str):
        font = self.text_edit.font()
        font.setPointSize(int(size_str))
        self.text_edit.setFont(font)
    
    def _toggle_mode(self, checked):
        if not hasattr(self, 'content'):
            return
            
        if checked:
            self.text_edit.setMarkdown(self.content)
            self.mode_btn.setText("Plain Text View")
        else:
            self.text_edit.setPlainText(self.content)
            self.mode_btn.setText("Markdown View")
    
    def _toggle_edit_mode(self, checked):
        """Toggle between view and edit mode."""
        self.text_edit.setReadOnly(not checked)
        if checked:
            self.edit_btn.setText("👁️ View")
            # Disable markdown mode while editing - need plain text
            if self.mode_btn.isChecked():
                self.mode_btn.setChecked(False)
            self.mode_btn.setEnabled(False)
        else:
            self.edit_btn.setText("✏️ Edit")
            self.mode_btn.setEnabled(True)
    
    def _on_text_changed(self):
        """Track text modifications."""
        if not self.text_edit.isReadOnly():
            self._is_modified = True
            self.save_btn.setEnabled(True and not self._is_encrypted)
    
    def _save_file(self):
        """Save the current text to file."""
        if not self._current_path or self._is_encrypted:
            QMessageBox.warning(
                self, "Cannot Save",
                "Cannot save encrypted files directly. Decrypt first."
            )
            return
        
        try:
            content = self.text_edit.toPlainText()
            with open(self._current_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            self.content = content
            self._is_modified = False
            self.save_btn.setEnabled(False)
            QMessageBox.information(self, "Saved", f"File saved successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file: {e}")
