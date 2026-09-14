from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, 
    QPushButton, QHBoxLayout, QHeaderView, QLabel
)
from PyQt6.QtCore import Qt, QTimer
from core.access_logger import AccessLogger

class AccessLogDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Access Logs")
        self.resize(800, 500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self.logger = AccessLogger()
        self._setup_ui()
        self._load_logs()

        # Auto refresh every 5 seconds
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._load_logs)
        self.timer.start(5000)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Controls
        top_layout = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._load_logs)
        clear_btn = QPushButton("Clear Logs")
        clear_btn.clicked.connect(self._clear_logs)
        
        top_layout.addWidget(QLabel("Showing latest 100 entries"))
        top_layout.addStretch()
        top_layout.addWidget(refresh_btn)
        top_layout.addWidget(clear_btn)
        layout.addLayout(top_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Timestamp", "IP Address", "Action", "Resource"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        layout.addWidget(self.table)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)

    def _load_logs(self):
        logs = self.logger.get_logs(limit=100)
        self.table.setRowCount(0)
        
        for entry in logs:
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            # Timestamp (try to format nicely)
            ts = entry.get("timestamp", "")
            try:
                # 2023-10-27T10:00:00.123456 -> 2023-10-27 10:00:00
                dt = ts.split('.')[0].replace('T', ' ')
            except:
                dt = ts
                
            self.table.setItem(row, 0, QTableWidgetItem(dt))
            self.table.setItem(row, 1, QTableWidgetItem(entry.get("ip", "")))
            self.table.setItem(row, 2, QTableWidgetItem(entry.get("action", "")))
            # Resource stored as hash for privacy (legacy rows may have raw path)
            res = entry.get("resource_hash") or entry.get("resource", "")
            kind = entry.get("kind", "")
            display = (f"{res} ({kind})" if res else "—")
            self.table.setItem(row, 3, QTableWidgetItem(display))

    def _clear_logs(self):
        self.logger.clear_logs()
        self._load_logs()
