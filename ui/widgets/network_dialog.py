"""
Network stream dialog.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, 
    QPushButton, QHBoxLayout, QComboBox
)

class NetworkStreamDialog(QDialog):
    """Dialog to open network stream URL."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("打开网络流 (Open Network Stream)")
        self.setMinimumWidth(400)
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("请输入网络 URL (Enter Network URL):"))
        self.url_input = QComboBox()
        self.url_input.setEditable(True)
        # Add some samples
        self.url_input.addItem("http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4")
        self.url_input.addItem("rtsp://")
        self.url_input.addItem("http://")
        layout.addWidget(self.url_input)
        
        layout.addWidget(QLabel("支持 HTTP, HLS, RTSP 等协议。\n(Supports HTTP, HLS, RTSP)"))
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_play = QPushButton("播放 (Play)")
        self.btn_play.setDefault(True)
        self.btn_play.clicked.connect(self.accept)
        
        self.btn_cancel = QPushButton("取消 (Cancel)")
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.btn_play)
        btn_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(btn_layout)
        
    def get_url(self):
        return self.url_input.currentText().strip()
