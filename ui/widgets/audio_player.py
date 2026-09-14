"""
Audio player widget with visualization.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QUrl
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

from ui.widgets.control_bar import ControlBar
from ui.password_dialog import PasswordDialog
from core.evf_format import is_evf_file
from core.stream_decoder import StreamDecoder
from pathlib import Path

class AudioPlayer(QWidget):
    """Audio player with visualization placeholder."""
    
    media_changed = pyqtSignal(str)
    playback_finished = pyqtSignal()
    context_menu_requested = pyqtSignal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_player()
        self._setup_ui()
    
    def _setup_player(self):
        """Initialize media player."""
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
    
    def _setup_ui(self):
        """Setup UI."""
        layout = QVBoxLayout(self)
        
        # Visualizer Area
        self.visualizer = QLabel("🎵 Music")
        self.visualizer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.visualizer.setStyleSheet("""
            background-color: #111;
            color: #444;
            font-size: 48px;
            font-weight: bold;
            border-radius: 20px;
        """)
        
        self.visualizer.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.visualizer.customContextMenuRequested.connect(self.context_menu_requested.emit)
        
        # Song Info
        self.label_title = QLabel("Top Title")
        self.label_title.setObjectName("title")
        self.label_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Controls
        self.control_bar = ControlBar()
        self.control_bar.play_pause_clicked.connect(self.toggle_play)
        self.control_bar.stop_clicked.connect(self.stop)
        self.control_bar.seek_requested.connect(self.seek)
        self.control_bar.volume_changed.connect(self.set_volume)
        self.control_bar.mute_clicked.connect(self.toggle_mute)
        self.control_bar.speed_changed.connect(self.set_speed)
        
        # Hide video specific controls
        self.control_bar.btn_fullscreen.hide()
        self.control_bar.btn_screenshot.hide()
        
        layout.addWidget(self.visualizer, 1)
        layout.addWidget(self.label_title)
        layout.addWidget(self.control_bar)
    
    def open_file(self, file_path: str):
        """Open audio file."""
        self.stop()
        
        path = Path(file_path)
        self.label_title.setText(path.name)
        
        if is_evf_file(file_path):
            self._open_encrypted(file_path)
        else:
            self._player.setSource(QUrl.fromLocalFile(file_path))
            self.media_changed.emit(path.name)
            self.play()

    def _open_encrypted(self, file_path: str):
        """Open encrypted audio."""
        password, ok = PasswordDialog.get_password_dialog(
            self,
            title="🔐 需要密码",
            message="此音频已加密，请输入密码解锁"
        )
        if not ok:
            return

        try:
            self._stream_decoder = StreamDecoder()
            stream_path = self._stream_decoder.open(file_path, password)
            
            if not self._stream_decoder.wait_for_ready():
                 raise Exception("解密超时")
            
            self._player.setSource(QUrl.fromLocalFile(stream_path))
            self.media_changed.emit(f"🔒 {Path(file_path).name}")
            self.play()
            
        except Exception as e:
            self.label_title.setText(f"Error: {str(e)}")

    def play(self):
        if self._player: self._player.play()
        
    def pause(self):
        if self._player: self._player.pause()
        
    def stop(self):
        if self._player: self._player.stop()
        if hasattr(self, '_stream_decoder') and self._stream_decoder:
            self._stream_decoder.close()
            self._stream_decoder = None
        self.control_bar.reset()
        
    def toggle_play(self):
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause()
        else:
            self.play()
            
    def seek(self, position_ms):
        self._player.setPosition(position_ms)
        
    def set_volume(self, volume):
        self._audio_output.setVolume(volume / 100.0)
        self.control_bar.set_volume(volume)
        
    def toggle_mute(self):
        muted = self._audio_output.isMuted()
        self._audio_output.setMuted(not muted)
        self.control_bar.set_muted(not muted)
        
    def set_speed(self, speed):
        self._player.setPlaybackRate(speed)
        
    def restart(self):
        if self._player:
            self._player.setPosition(0)
            self._player.play()
        
    def _on_position_changed(self, pos):
        self.control_bar.set_position(pos)
        
    def _on_duration_changed(self, dur):
        self.control_bar.set_duration(dur)
        
    def _on_state_changed(self, state):
        self.control_bar.set_playing(state == QMediaPlayer.PlaybackState.PlayingState)
        
    def _on_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.playback_finished.emit()
