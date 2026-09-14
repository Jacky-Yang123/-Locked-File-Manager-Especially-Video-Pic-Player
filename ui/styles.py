"""
Instagram-style black/white gradient theme for the video player.
Modern, minimalist design with glassmorphism effects.
"""

# Main dark theme with gradient
MAIN_STYLE = """
/* Main Window */
QMainWindow {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #0a0a0a, stop:0.3 #1a1a1a, stop:0.7 #151515, stop:1 #0d0d0d);
}

QWidget {
    color: #ffffff;
    font-family: 'Segoe UI', 'SF Pro Display', -apple-system, sans-serif;
}

/* Glassmorphism Card */
QFrame#card {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 16px;
}

/* Primary Button */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(255, 255, 255, 0.1), stop:1 rgba(255, 255, 255, 0.05));
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 10px;
    color: #ffffff;
    padding: 10px 20px;
    font-size: 14px;
    font-weight: 500;
}

QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(255, 255, 255, 0.2), stop:1 rgba(255, 255, 255, 0.1));
    border: 1px solid rgba(255, 255, 255, 0.25);
}

QPushButton:pressed {
    background: rgba(255, 255, 255, 0.25);
}

QPushButton:disabled {
    background: rgba(255, 255, 255, 0.03);
    color: rgba(255, 255, 255, 0.3);
    border: 1px solid rgba(255, 255, 255, 0.05);
}

/* Accent Button */
QPushButton#accent {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ffffff, stop:1 #e0e0e0);
    color: #0a0a0a;
    font-weight: 600;
}

QPushButton#accent:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #f0f0f0, stop:1 #d0d0d0);
}

/* Icon Button */
QPushButton#iconBtn {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 8px;
    min-width: 40px;
    min-height: 40px;
}

QPushButton#iconBtn:hover {
    background: rgba(255, 255, 255, 0.1);
}

QPushButton#iconBtn:pressed {
    background: rgba(255, 255, 255, 0.15);
}

/* Slider */
QSlider::groove:horizontal {
    height: 4px;
    background: rgba(255, 255, 255, 0.2);
    border-radius: 2px;
}

QSlider::handle:horizontal {
    width: 14px;
    height: 14px;
    margin: -5px 0;
    background: #ffffff;
    border-radius: 7px;
}

QSlider::handle:horizontal:hover {
    background: #f0f0f0;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}

QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ffffff, stop:1 #b0b0b0);
    border-radius: 2px;
}

/* Volume Slider */
QSlider#volumeSlider::groove:horizontal {
    height: 3px;
}

QSlider#volumeSlider::handle:horizontal {
    width: 12px;
    height: 12px;
    margin: -5px 0;
}

/* Progress Slider */
QSlider#progressSlider::groove:horizontal {
    height: 5px;
    background: rgba(255, 255, 255, 0.15);
}

QSlider#progressSlider::sub-page:horizontal {
    background: #ffffff;
}

/* Labels */
QLabel {
    color: #ffffff;
    font-size: 13px;
}

QLabel#title {
    font-size: 18px;
    font-weight: 600;
    color: #ffffff;
}

QLabel#subtitle {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.6);
}

QLabel#time {
    font-size: 12px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.8);
    font-family: 'SF Mono', 'Consolas', monospace;
}

/* Line Edit */
QLineEdit {
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 10px;
    padding: 12px 16px;
    color: #ffffff;
    font-size: 14px;
    selection-background-color: rgba(255, 255, 255, 0.3);
}

QLineEdit:focus {
    border: 1px solid rgba(255, 255, 255, 0.4);
    background: rgba(255, 255, 255, 0.1);
}

QLineEdit:disabled {
    background: rgba(255, 255, 255, 0.03);
    color: rgba(255, 255, 255, 0.3);
}

/* Password Field */
QLineEdit#password {
    letter-spacing: 3px;
}

/* Scroll Area */
QScrollArea {
    background: transparent;
    border: none;
}

QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 0.3);
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: rgba(255, 255, 255, 0.5);
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

/* List Widget */
QListWidget {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 8px;
    outline: none;
}

QListWidget::item {
    background: transparent;
    border-radius: 8px;
    padding: 10px 12px;
    margin: 2px 0;
    color: #ffffff;
}

QListWidget::item:hover {
    background: rgba(255, 255, 255, 0.08);
}

QListWidget::item:selected {
    background: rgba(255, 255, 255, 0.15);
}

/* Context Menu */
QMenu {
    background: rgba(30, 30, 30, 0.95);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 8px;
}

QMenu::item {
    padding: 10px 30px 10px 20px;
    border-radius: 6px;
    color: #ffffff;
}

QMenu::item:selected {
    background: rgba(255, 255, 255, 0.1);
}

QMenu::separator {
    height: 1px;
    background: rgba(255, 255, 255, 0.1);
    margin: 6px 10px;
}

/* Combo Box */
QComboBox {
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 8px;
    padding: 8px 12px;
    color: #ffffff;
    min-width: 80px;
}

QComboBox:hover {
    background: rgba(255, 255, 255, 0.12);
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid rgba(255, 255, 255, 0.6);
    margin-right: 8px;
}

QComboBox QAbstractItemView {
    background: rgba(30, 30, 30, 0.95);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    selection-background-color: rgba(255, 255, 255, 0.15);
    outline: none;
}

/* Progress Bar */
QProgressBar {
    background: rgba(255, 255, 255, 0.1);
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ffffff, stop:1 #c0c0c0);
    border-radius: 4px;
}

/* Tool Tip */
QToolTip {
    background: rgba(40, 40, 40, 0.95);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 6px;
    padding: 6px 10px;
    color: #ffffff;
    font-size: 12px;
}

/* Dialog */
QDialog {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #0a0a0a, stop:0.3 #1a1a1a, stop:0.7 #151515, stop:1 #0d0d0d);
}

/* Message Box */
QMessageBox {
    background: rgba(20, 20, 20, 0.98);
}

QMessageBox QLabel {
    color: #ffffff;
    font-size: 14px;
}

/* File Dialog */
QFileDialog {
    background: #1a1a1a;
}
"""

# Control bar specific styles
CONTROL_BAR_STYLE = """
QFrame#controlBar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(0, 0, 0, 0), stop:0.3 rgba(0, 0, 0, 0.7), stop:1 rgba(0, 0, 0, 0.95));
    border: none;
    border-radius: 0;
}
"""

# Video display area
VIDEO_FRAME_STYLE = """
QFrame#videoFrame {
    background: #000000;
    border: none;
}
"""

# Playlist sidebar
PLAYLIST_STYLE = """
QFrame#playlist {
    background: rgba(255, 255, 255, 0.03);
    border-left: 1px solid rgba(255, 255, 255, 0.08);
}

QLabel#playlistTitle {
    font-size: 14px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.9);
    padding: 16px;
}
"""

# Encryption dialog
ENCRYPTION_DIALOG_STYLE = """
QFrame#encryptionCard {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 20px;
    padding: 30px;
}

QLabel#encryptionTitle {
    font-size: 24px;
    font-weight: 700;
    color: #ffffff;
}

QLabel#encryptionSubtitle {
    font-size: 14px;
    color: rgba(255, 255, 255, 0.5);
}
"""


def get_full_stylesheet() -> str:
    """Get the complete stylesheet for the application."""
    return (
        MAIN_STYLE + 
        CONTROL_BAR_STYLE + 
        VIDEO_FRAME_STYLE + 
        PLAYLIST_STYLE + 
        ENCRYPTION_DIALOG_STYLE
    )
