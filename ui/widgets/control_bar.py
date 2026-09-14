"""
Custom control bar with playback controls.
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, 
    QSlider, QLabel, QComboBox, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QFont

from utils.file_utils import format_time
from utils.constants import PLAYBACK_SPEEDS


class ControlBar(QFrame):
    """Video player control bar with modern design."""
    
    # Signals
    play_pause_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    seek_requested = pyqtSignal(int)  # position in ms
    volume_changed = pyqtSignal(int)  # 0-100
    mute_clicked = pyqtSignal()
    speed_changed = pyqtSignal(float)
    fullscreen_clicked = pyqtSignal()
    backward_clicked = pyqtSignal()
    forward_clicked = pyqtSignal()
    screenshot_clicked = pyqtSignal()
    vr_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("controlBar")
        self._duration = 0
        self._is_seeking = False
        self._is_muted = False
        self._is_playing = False
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the control bar UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 20)
        layout.setSpacing(12)
        
        # Progress bar row
        progress_layout = QHBoxLayout()
        progress_layout.setSpacing(12)
        
        self.time_current = QLabel("00:00")
        self.time_current.setObjectName("time")
        self.time_current.setFixedWidth(60)
        
        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setObjectName("progressSlider")
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.sliderPressed.connect(self._on_seek_start)
        self.progress_slider.sliderReleased.connect(self._on_seek_end)
        self.progress_slider.sliderMoved.connect(self._on_seek_move)
        
        self.time_total = QLabel("00:00")
        self.time_total.setObjectName("time")
        self.time_total.setFixedWidth(60)
        self.time_total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        progress_layout.addWidget(self.time_current)
        progress_layout.addWidget(self.progress_slider, 1)
        progress_layout.addWidget(self.time_total)
        
        # Controls row
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)
        
        # Left controls
        left_controls = QHBoxLayout()
        left_controls.setSpacing(4)
        
        self.btn_backward = QPushButton("⏪")
        self.btn_backward.setObjectName("iconBtn")
        self.btn_backward.setToolTip("后退 5秒 (←)")
        self.btn_backward.clicked.connect(self.backward_clicked.emit)
        
        self.btn_play = QPushButton("▶")
        self.btn_play.setObjectName("iconBtn")
        self.btn_play.setToolTip("播放/暂停 (Space)")
        self.btn_play.setStyleSheet("font-size: 20px;")
        self.btn_play.clicked.connect(self.play_pause_clicked.emit)
        
        self.btn_forward = QPushButton("⏩")
        self.btn_forward.setObjectName("iconBtn")
        self.btn_forward.setToolTip("前进 5秒 (→)")
        self.btn_forward.clicked.connect(self.forward_clicked.emit)
        
        self.btn_stop = QPushButton("⏹")
        self.btn_stop.setObjectName("iconBtn")
        self.btn_stop.setToolTip("停止")
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        
        left_controls.addWidget(self.btn_backward)
        left_controls.addWidget(self.btn_play)
        left_controls.addWidget(self.btn_forward)
        left_controls.addWidget(self.btn_stop)
        
        # Center - Volume
        volume_layout = QHBoxLayout()
        volume_layout.setSpacing(8)
        
        self.btn_mute = QPushButton("🔊")
        self.btn_mute.setObjectName("iconBtn")
        self.btn_mute.setToolTip("静音 (M)")
        self.btn_mute.clicked.connect(self._on_mute_click)
        
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("volumeSlider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(self.volume_changed.emit)
        
        self.volume_label = QLabel("100%")
        self.volume_label.setObjectName("subtitle")
        self.volume_label.setFixedWidth(40)
        
        volume_layout.addWidget(self.btn_mute)
        volume_layout.addWidget(self.volume_slider)
        volume_layout.addWidget(self.volume_label)
        
        # Right controls
        right_controls = QHBoxLayout()
        right_controls.setSpacing(8)
        
        # Speed selector
        self.speed_combo = QComboBox()
        self.speed_combo.setFixedWidth(80)
        for speed in PLAYBACK_SPEEDS:
            self.speed_combo.addItem(f"{speed}x", speed)
        self.speed_combo.setCurrentIndex(PLAYBACK_SPEEDS.index(1.0))
        self.speed_combo.currentIndexChanged.connect(self._on_speed_change)
        
        self.btn_screenshot = QPushButton("📷")
        self.btn_screenshot.setObjectName("iconBtn")
        self.btn_screenshot.setToolTip("截图 (Ctrl+S)")
        self.btn_screenshot.clicked.connect(self.screenshot_clicked.emit)
        
        self.btn_fullscreen = QPushButton("⛶")
        self.btn_fullscreen.setObjectName("iconBtn")
        self.btn_fullscreen.setToolTip("全屏 (F)")
        self.btn_fullscreen.setStyleSheet("font-size: 18px;")
        self.btn_fullscreen.clicked.connect(self.fullscreen_clicked.emit)
        
        self.btn_vr = QPushButton("🥽")
        self.btn_vr.setObjectName("iconBtn")
        self.btn_vr.setCheckable(True)
        self.btn_vr.setToolTip("VR 模式 (Side-by-Side)")
        self.btn_vr.clicked.connect(self.vr_clicked.emit)
        
        right_controls.addWidget(self.btn_vr)
        right_controls.addWidget(self.speed_combo)
        right_controls.addWidget(self.btn_screenshot)
        right_controls.addWidget(self.btn_fullscreen)
        
        # Assemble controls row
        controls_layout.addLayout(left_controls)
        controls_layout.addStretch()
        controls_layout.addLayout(volume_layout)
        controls_layout.addStretch()
        controls_layout.addLayout(right_controls)
        
        layout.addLayout(progress_layout)
        layout.addLayout(controls_layout)
    
    def _on_seek_start(self):
        """Handle seek start."""
        self._is_seeking = True
    
    def _on_seek_end(self):
        """Handle seek end."""
        self._is_seeking = False
        position = int((self.progress_slider.value() / 1000) * self._duration)
        self.seek_requested.emit(position)
    
    def _on_seek_move(self, value):
        """Handle seek move."""
        position = int((value / 1000) * self._duration)
        self.time_current.setText(format_time(position // 1000))
    
    def _on_mute_click(self):
        """Handle mute button click."""
        self._is_muted = not self._is_muted
        self.btn_mute.setText("🔇" if self._is_muted else "🔊")
        self.mute_clicked.emit()
    
    def _on_speed_change(self, index):
        """Handle speed change."""
        speed = self.speed_combo.currentData()
        self.speed_changed.emit(speed)
    
    def set_playing(self, is_playing: bool):
        """Update play button state."""
        self._is_playing = is_playing
        self.btn_play.setText("⏸" if is_playing else "▶")
    
    def set_duration(self, duration_ms: int):
        """Set the total duration."""
        self._duration = duration_ms
        self.time_total.setText(format_time(duration_ms // 1000))
    
    def set_position(self, position_ms: int):
        """Set the current position."""
        if not self._is_seeking and self._duration > 0:
            progress = int((position_ms / self._duration) * 1000)
            self.progress_slider.setValue(progress)
            self.time_current.setText(format_time(position_ms // 1000))
    
    def set_volume(self, volume: int):
        """Set the volume display."""
        self.volume_slider.setValue(volume)
        self.volume_label.setText(f"{volume}%")
    
    def set_muted(self, muted: bool):
        """Set the mute state."""
        self._is_muted = muted
        self.btn_mute.setText("🔇" if muted else "🔊")
    
    def reset(self):
        """Reset the control bar."""
        self._duration = 0
        self._is_seeking = False
        self.progress_slider.setValue(0)
        self.time_current.setText("00:00")
        self.time_total.setText("00:00")
        self.set_playing(False)
