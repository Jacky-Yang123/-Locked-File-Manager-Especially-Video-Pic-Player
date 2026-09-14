"""
Child lock overlay widget.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, 
    QInputDialog, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette

class LockOverlay(QWidget):
    """
    Overlay that blocks user interaction when Child Lock is active.
    """
    unlocked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pin = "0000"
        self._setup_ui()
        
    def _setup_ui(self):
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 200))
        self.setPalette(pal)
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        lbl_icon = QLabel("🔒")
        lbl_icon.setStyleSheet("font-size: 80px;")
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        lbl_text = QLabel("儿童锁已启用 (Child Lock Active)")
        lbl_text.setStyleSheet("font-size: 24px; color: white; font-weight: bold;")
        lbl_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        btn_unlock = QPushButton("点击解锁 (Click to Unlock)")
        btn_unlock.setFixedWidth(200)
        btn_unlock.setMinimumHeight(50)
        btn_unlock.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.2);
                border: 2px solid white;
                color: white;
                font-size: 16px;
                border-radius: 25px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.4);
            }
        """)
        btn_unlock.clicked.connect(self._try_unlock)
        
        layout.addWidget(lbl_icon)
        layout.addWidget(lbl_text)
        layout.addSpacing(40)
        layout.addWidget(btn_unlock)
        
    def set_pin(self, pin):
        self.pin = pin
        
    def _try_unlock(self):
        text, ok = QInputDialog.getText(
            self, "解锁", "请输入 PIN 码:", 
            QLineEdit.EchoMode.Password
        )
        if ok:
            if text == self.pin:
                self.unlocked.emit()
                self.hide()
            else:
                QMessageBox.warning(self, "错误", "PIN 码错误")
                
    def mousePressEvent(self, event):
        # Consume event
        pass
    
    def keyPressEvent(self, event):
        # Consume event
        pass
