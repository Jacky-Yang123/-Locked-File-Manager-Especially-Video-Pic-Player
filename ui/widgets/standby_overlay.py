"""
Standby mode overlay widget.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit, 
    QPushButton, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QColor, QPalette, QFont

class StandbyOverlay(QWidget):
    """
    Full-screen overlay for standby mode. 
    Hides all UI content and requires a password to unlock.
    """
    unlocked = pyqtSignal()
    
    def __init__(self, media_library, parent=None):
        super().__init__(parent)
        self.library = media_library
        self._setup_ui()
        
    def _setup_ui(self):
        # Semi-transparent black background
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 255))
        self.setPalette(pal)
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(30)
        
        # Icon
        self.lbl_icon = QLabel("🔒")
        self.lbl_icon.setStyleSheet("font-size: 120px; color: #3498db;")
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Title
        self.lbl_title = QLabel("已进入待机模式")
        self.lbl_title.setStyleSheet("font-size: 32px; color: white; font-weight: bold;")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Subtitle
        self.lbl_sub = QLabel("请输入密码以解锁")
        self.lbl_sub.setStyleSheet("font-size: 18px; color: #888;")
        self.lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Password Input
        self.pwd_input = QLineEdit()
        self.pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd_input.setPlaceholderText("待机密码")
        self.pwd_input.setFixedWidth(300)
        self.pwd_input.setFixedHeight(45)
        self.pwd_input.setStyleSheet("""
            QLineEdit {
                background-color: #2b2b2b;
                border: 2px solid #3d3d3d;
                border-radius: 8px;
                color: white;
                padding: 0 15px;
                font-size: 16px;
            }
            QLineEdit:focus {
                border-color: #3498db;
            }
        """)
        self.pwd_input.returnPressed.connect(self._try_unlock)
        
        # Unlock Button
        self.btn_unlock = QPushButton("解锁 (Unlock)")
        self.btn_unlock.setFixedWidth(300)
        self.btn_unlock.setFixedHeight(45)
        self.btn_unlock.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_unlock.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #1c5980;
            }
        """)
        self.btn_unlock.clicked.connect(self._try_unlock)
        
        layout.addStretch()
        layout.addWidget(self.lbl_icon)
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_sub)
        layout.addWidget(self.pwd_input)
        layout.addWidget(self.btn_unlock)
        layout.addStretch()

    def showEvent(self, event):
        """Prepare UI when overlay is shown."""
        self.pwd_input.clear()
        # Ensure this widget can receive focus and keyboard input
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.pwd_input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.pwd_input.setFocus()
        self.activateWindow()
        self.raise_()
        super().showEvent(event)
        # Deferred focus set to ensure it takes effect after event processing
        QTimer = __import__('PyQt6.QtCore', fromlist=['QTimer']).QTimer
        QTimer.singleShot(100, self.pwd_input.setFocus)
        
    def _try_unlock(self):
        password = self.pwd_input.text()
        if not password:
            return
            
        if self.library.verify_standby_password(password):
            self.unlocked.emit()
            self.hide()
        else:
            QMessageBox.warning(self, "错误", "密码错误，请重试。")
            self.pwd_input.clear()
            self.pwd_input.setFocus()
            
    def mousePressEvent(self, event):
        # Consume clicks to prevent interaction with underlying widgets
        self.pwd_input.setFocus()
        event.accept()
    
    def keyPressEvent(self, event):
        # Ignore key events primarily, except for Enter which is handled by QLineEdit
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self._try_unlock()
        super().keyPressEvent(event)
