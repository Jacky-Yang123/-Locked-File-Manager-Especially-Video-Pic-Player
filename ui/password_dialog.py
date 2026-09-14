"""
Password input dialog with modern design.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class PasswordDialog(QDialog):
    """Modern password input dialog."""
    
    def __init__(self, parent=None, title: str = "输入密码", 
                 message: str = "请输入解密密码", confirm: bool = False):
        super().__init__(parent)
        self._confirm = confirm
        self._setup_ui(title, message)
        self.setModal(True)
        self.setFixedSize(400, 280 if confirm else 220)
    
    def _setup_ui(self, title: str, message: str):
        """Setup the dialog UI."""
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 8px;
            }
            QLabel { color: #eee; }
            QLineEdit { 
                padding: 8px; 
                background: #1a1a1a; 
                border: 1px solid #444; 
                border-radius: 4px; 
                color: white; 
            }
            QPushButton {
                padding: 6px 12px;
                background: #444;
                color: white;
                border-radius: 4px;
                border: none;
            }
            QPushButton#accent {
                background: #3498db;
            }
            QPushButton:hover { background: #555; }
            QPushButton#accent:hover { background: #2980b9; }
        """)

        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Card container
        card = QFrame()
        card.setObjectName("encryptionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(30, 30, 30, 30)
        card_layout.setSpacing(20)
        
        # Title
        title_label = QLabel(title)
        title_label.setObjectName("encryptionTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Message
        message_label = QLabel(message)
        message_label.setObjectName("encryptionSubtitle")
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        
        # Password input
        self.password_input = QLineEdit()
        self.password_input.setObjectName("password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("输入密码...")
        self.password_input.returnPressed.connect(self._on_submit)
        
        # Confirm password input (optional)
        if self._confirm:
            self.confirm_input = QLineEdit()
            self.confirm_input.setObjectName("password")
            self.confirm_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirm_input.setPlaceholderText("确认密码...")
            self.confirm_input.returnPressed.connect(self._on_submit)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setObjectName("accent")
        self.btn_ok.clicked.connect(self._on_submit)
        
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_ok)
        
        # Error label
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #ff6b6b; font-size: 12px;")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.hide()
        
        # Assemble
        card_layout.addWidget(title_label)
        card_layout.addWidget(message_label)
        card_layout.addWidget(self.password_input)
        if self._confirm:
            card_layout.addWidget(self.confirm_input)
        card_layout.addWidget(self.error_label)
        card_layout.addLayout(btn_layout)
        
        layout.addWidget(card)
        
        # Focus password input
        self.password_input.setFocus()
    
    def _on_submit(self):
        """Handle submit."""
        password = self.password_input.text()
        
        if not password:
            self._show_error("请输入密码")
            return
        
        if len(password) < 4:
            self._show_error("密码至少需要4个字符")
            return
        
        if self._confirm:
            confirm = self.confirm_input.text()
            if password != confirm:
                self._show_error("两次输入的密码不一致")
                return
        
        self.accept()
    
    def _show_error(self, message: str):
        """Show error message."""
        self.error_label.setText(message)
        self.error_label.show()
    
    def get_password(self) -> str:
        """Get the entered password."""
        return self.password_input.text()
    
    @staticmethod
    def get_password_dialog(parent=None, title: str = "输入密码",
                           message: str = "请输入解密密码") -> tuple[str, bool]:
        """
        Static method to show password dialog and get result.
        
        Returns:
            Tuple of (password, accepted)
        """
        dialog = PasswordDialog(parent, title, message)
        result = dialog.exec()
        return dialog.get_password(), result == QDialog.DialogCode.Accepted
    
    @staticmethod
    def get_new_password(parent=None, title: str = "设置密码",
                        message: str = "请设置加密密码") -> tuple[str, bool]:
        """
        Static method to show password dialog with confirmation.
        
        Returns:
            Tuple of (password, accepted)
        """
        dialog = PasswordDialog(parent, title, message, confirm=True)
        result = dialog.exec()
        return dialog.get_password(), result == QDialog.DialogCode.Accepted
