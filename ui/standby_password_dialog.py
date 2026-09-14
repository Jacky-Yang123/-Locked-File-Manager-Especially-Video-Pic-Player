"""
Dialog for managing standby mode password.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QPushButton, 
    QMessageBox
)
from PyQt6.QtCore import Qt

class StandbyPasswordDialog(QDialog):
    """
    Dialog to set or change the standby password.
    Requires the old password if one is already set.
    """
    def __init__(self, media_library, parent=None):
        super().__init__(parent)
        self.library = media_library
        self._setup_ui()
        
    def _setup_ui(self):
        self.setWindowTitle("设置待机密码")
        self.setFixedWidth(400)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        self.has_pwd = self.library.has_standby_password()
        
        # Old Password
        if self.has_pwd:
            layout.addWidget(QLabel("请输入原密码:"))
            self.old_pwd = QLineEdit()
            self.old_pwd.setEchoMode(QLineEdit.EchoMode.Password)
            layout.addWidget(self.old_pwd)
        
        # New Password
        layout.addWidget(QLabel("请输入新密码:" if self.has_pwd else "请设置新密码:"))
        self.new_pwd = QLineEdit()
        self.new_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.new_pwd)
        
        # Confirm Password
        layout.addWidget(QLabel("请再次输入新密码:"))
        self.confirm_pwd = QLineEdit()
        self.confirm_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.confirm_pwd)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("保存")
        btn_save.setFixedHeight(40)
        btn_save.setStyleSheet("background-color: #3498db; color: white; border-radius: 5px;")
        btn_save.clicked.connect(self._on_save)
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(40)
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def _on_save(self):
        # 1. Verify old password if exists
        if self.has_pwd:
            old = self.old_pwd.text()
            if not self.library.verify_standby_password(old):
                QMessageBox.warning(self, "错误", "原密码错误！")
                return
        
        # 2. Check new password match
        new1 = self.new_pwd.text()
        new2 = self.confirm_pwd.text()
        
        if not new1:
            QMessageBox.warning(self, "错误", "密码不能为空！")
            return
            
        if new1 != new2:
            QMessageBox.warning(self, "错误", "两次输入的新密码不一致！")
            return
            
        # 3. Save
        self.library.set_standby_password(new1)
        QMessageBox.information(self, "成功", "待机密码设置成功！")
        self.accept()
