"""
Settings panel for advanced playback controls.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QSlider, QComboBox, QGroupBox, QPushButton, 
    QTabWidget, QSpinBox
)
from PyQt6.QtCore import Qt, pyqtSignal

class SettingsPanel(QWidget):
    """
    Control panel for Video, Audio, and Subtitle settings.
    Similar to PotPlayer's Control Panel.
    """
    
    brightness_changed = pyqtSignal(int) # -100 to 100
    audio_track_changed = pyqtSignal(int)
    subtitle_track_changed = pyqtSignal(int)
    subtitle_load_requested = pyqtSignal()
    sleep_timer_changed = pyqtSignal(int)
    lock_requested = pyqtSignal()
    vr_resolution_changed = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("控制面板")
        self.setWindowFlags(Qt.WindowType.Tool) # Tool window
        self.setMinimumSize(300, 400)
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_video_tab(), "视频")
        self.tabs.addTab(self._create_audio_tab(), "音频")
        self.tabs.addTab(self._create_subtitle_tab(), "字幕")
        self.tabs.addTab(self._create_tools_tab(), "工具")
        
        layout.addWidget(self.tabs)
        
    def _create_tools_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Sleep Timer
        grp_sleep = QGroupBox("睡眠定时器 (Sleep Timer)")
        sleep_layout = QVBoxLayout(grp_sleep)
        
        self.combo_sleep = QComboBox()
        self.combo_sleep.addItems(["关闭 (Off)", "10 分钟", "30 分钟", "60 分钟", "120 分钟"])
        self.combo_sleep.currentIndexChanged.connect(self._on_sleep_changed)
        sleep_layout.addWidget(self.combo_sleep)
        self.lbl_sleep_status = QLabel("状态: 未设置")
        sleep_layout.addWidget(self.lbl_sleep_status)
        
        layout.addWidget(grp_sleep)
        
        # Child Lock
        grp_security = QGroupBox("安全 (Security)")
        sec_layout = QVBoxLayout(grp_security)
        
        self.btn_lock = QPushButton("🔒 启用儿童锁 (Enable Child Lock)")
        self.btn_lock.clicked.connect(self.lock_requested.emit)
        sec_layout.addWidget(self.btn_lock)
        
        layout.addWidget(grp_security)
        
        layout.addStretch()
        return widget

    def _on_sleep_changed(self, index):
        # 0: Off, 1: 10, 2: 30, 3: 60, 4: 120
        minutes = 0
        if index == 1: minutes = 10
        elif index == 2: minutes = 30
        elif index == 3: minutes = 60
        elif index == 4: minutes = 120
        
        self.sleep_timer_changed.emit(minutes)
        if minutes > 0:
            self.lbl_sleep_status.setText(f"将在 {minutes} 分钟后关闭")
        else:
            self.lbl_sleep_status.setText("状态: 未设置")

    def _create_video_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Color Adjustment
        grp_color = QGroupBox("色彩调节")
        color_layout = QVBoxLayout(grp_color)
        
        # Brightness
        color_layout.addWidget(QLabel("亮度 (Brightness)"))
        self.slider_brightness = QSlider(Qt.Orientation.Horizontal)
        self.slider_brightness.setRange(-100, 100)
        self.slider_brightness.setValue(0)
        self.slider_brightness.valueChanged.connect(self.brightness_changed.emit)
        color_layout.addWidget(self.slider_brightness)
        
        # Contrast (Placeholder)
        color_layout.addWidget(QLabel("对比度 (Contrast) [暂不支持]"))
        self.slider_contrast = QSlider(Qt.Orientation.Horizontal)
        self.slider_contrast.setRange(-100, 100)
        self.slider_contrast.setValue(0)
        self.slider_contrast.setEnabled(False)
        color_layout.addWidget(self.slider_contrast)
        
        # Reset
        btn_reset = QPushButton("重置")
        btn_reset.clicked.connect(self._reset_video)
        color_layout.addWidget(btn_reset)
        
        # VR Settings
        grp_vr = QGroupBox("VR 设置 (VR Settings)")
        vr_layout = QVBoxLayout(grp_vr)
        
        vr_layout.addWidget(QLabel("VR 分辨率限制 (Max Resolution):"))
        self.combo_vr_res = QComboBox()
        # Items: Display Text, User Data (width)
        self.combo_vr_res.addItem("原生 (Native)", 0)
        self.combo_vr_res.addItem("4K (3840)", 3840)
        self.combo_vr_res.addItem("2K (2048)", 2048)
        self.combo_vr_res.addItem("1080p (1920)", 1920)
        self.combo_vr_res.currentIndexChanged.connect(self._on_vr_res_changed)
        vr_layout.addWidget(self.combo_vr_res)
        
        layout.addWidget(grp_vr)
        
        layout.addWidget(grp_color)
        layout.addStretch()
        return widget
        
    def _on_vr_res_changed(self, index):
        width = self.combo_vr_res.currentData()
        self.vr_resolution_changed.emit(width)
    
    def _create_audio_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Track Selection
        layout.addWidget(QLabel("音轨选择:"))
        self.combo_audio = QComboBox()
        self.combo_audio.currentIndexChanged.connect(self.audio_track_changed.emit)
        layout.addWidget(self.combo_audio)
        
        # Equalizer (Placeholder)
        layout.addWidget(QLabel("均衡器 (Equalizer) [暂不支持]"))
        
        layout.addStretch()
        return widget
        
    def _create_subtitle_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Track Selection
        layout.addWidget(QLabel("字幕选择:"))
        self.combo_subtitle = QComboBox()
        self.combo_subtitle.currentIndexChanged.connect(self.subtitle_track_changed.emit)
        layout.addWidget(self.combo_subtitle)
        
        # Load File
        btn_load = QPushButton("加载字幕文件...")
        btn_load.clicked.connect(self.subtitle_load_requested.emit)
        layout.addWidget(btn_load)
        
        # Delay
        layout.addWidget(QLabel("字幕延迟 (ms):"))
        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(-10000, 10000)
        self.spin_delay.setSingleStep(100)
        layout.addWidget(self.spin_delay)
        
        layout.addStretch()
        return widget
        
    def _reset_video(self):
        self.slider_brightness.setValue(0)
        self.slider_contrast.setValue(0)
        
    def update_audio_tracks(self, tracks):
        self.combo_audio.blockSignals(True)
        self.combo_audio.clear()
        self.combo_audio.addItems(tracks)
        self.combo_audio.blockSignals(False)
        
    def update_subtitle_tracks(self, tracks):
        self.combo_subtitle.blockSignals(True)
        self.combo_subtitle.clear()
        self.combo_subtitle.addItems(tracks)
        self.combo_subtitle.blockSignals(False)
