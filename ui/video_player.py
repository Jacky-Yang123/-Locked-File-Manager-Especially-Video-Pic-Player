"""
Video player widget with PyQt6 native multimedia backend.
"""

import sys
import os
from typing import Optional
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFrame, QLabel,
    QFileDialog, QMessageBox, QApplication, QGraphicsOpacityEffect, QHBoxLayout,
    QPushButton, QStyle
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QUrl
from PyQt6.QtGui import QPixmap, QColor, QPalette
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink
from PyQt6.QtMultimediaWidgets import QVideoWidget

from ui.widgets.control_bar import ControlBar
from ui.widgets.vr_gl_widget import VRGLWidget
from ui.password_dialog import PasswordDialog
from core.evf_format import is_evf_file
from core.stream_decoder import StreamDecoder
from utils.file_utils import format_time
from core.remote_stream import RemoteFileReader
from core.evf_format import MIXED_MAGIC


class VideoPlayer(QWidget):
    """Video player widget with PyQt6 native multimedia backend."""
    
    # Signals
    media_changed = pyqtSignal(str)  # filename
    playback_finished = pyqtSignal()
    context_menu_requested = pyqtSignal(object) # point
    tracks_changed = pyqtSignal()
    next_requested = pyqtSignal()
    prev_requested = pyqtSignal()
    playback_state_changed = pyqtSignal(QMediaPlayer.PlaybackState)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._player: Optional[QMediaPlayer] = None
        self._audio_output: Optional[QAudioOutput] = None
        self._video_sink: Optional[QVideoSink] = None
        self._stream_decoder: Optional[StreamDecoder] = None
        self._current_file: Optional[str] = None
        self._is_encrypted = False
        self._is_fullscreen = False
        self._cached_password: Optional[str] = None
        
        self._brightness = 0 # -100 to 100
        
        self._setup_player()
        self._setup_ui()
    
    def _setup_player(self):
        """Initialize media player."""
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        
        # VR Sink
        self._video_sink = QVideoSink()
        self._video_sink.videoFrameChanged.connect(self._on_video_frame)
        
        # Connect signals
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._player.errorOccurred.connect(self._on_error)
        self._player.tracksChanged.connect(self._on_tracks_changed)
    
    def _setup_ui(self):
        """Setup the player UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Container for video and overlay
        self.video_container = QWidget()
        self.video_container.setStyleSheet("background: #000000;")
        container_layout = QVBoxLayout(self.video_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        
        # Video widget (2D)
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumSize(640, 360)
        self.video_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.video_widget.customContextMenuRequested.connect(self.context_menu_requested.emit)
        
        self._player.setVideoOutput(self.video_widget)
        
        # VR Widget (OpenGL)
        self.vr_widget = VRGLWidget()
        self.vr_widget.hide()
        
        # Overlay for brightness (simulated)
        self.overlay = QFrame(self.video_widget)
        self.overlay.setStyleSheet("background-color: black;")
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.overlay.hide()
        
        # Placeholder (overlay)
        self.placeholder = QLabel("🎬 拖放视频文件或点击打开")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet("""
            color: rgba(255, 255, 255, 0.4);
            font-size: 18px;
            background: transparent;
        """)
        self.placeholder.setParent(self.video_widget)
        
        container_layout.addWidget(self.video_widget)
        container_layout.addWidget(self.vr_widget)
        
        # New: Prev/Next Buttons wrapping ControlBar
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(5,0,5,5)

        self.btn_prev = QPushButton()
        self.btn_prev.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward))
        self.btn_prev.setFixedSize(40, 30)
        self.btn_prev.setToolTip("上一个")
        self.btn_prev.clicked.connect(self._request_prev)

        self.btn_next = QPushButton()
        self.btn_next.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward))
        self.btn_next.setFixedSize(40, 30)
        self.btn_next.setToolTip("下一个")
        self.btn_next.clicked.connect(self._request_next)
        
        self.control_bar = ControlBar()
        self.control_bar.play_pause_clicked.connect(self.toggle_play)
        self.control_bar.stop_clicked.connect(self.stop)
        self.control_bar.seek_requested.connect(self.seek)
        self.control_bar.volume_changed.connect(self.set_volume)
        self.control_bar.mute_clicked.connect(self.toggle_mute)
        self.control_bar.speed_changed.connect(self.set_speed)
        self.control_bar.fullscreen_clicked.connect(self.toggle_fullscreen)
        self.control_bar.backward_clicked.connect(lambda: self.seek_relative(-5000))
        self.control_bar.forward_clicked.connect(lambda: self.seek_relative(5000))
        self.control_bar.screenshot_clicked.connect(self.take_screenshot)
        self.control_bar.vr_clicked.connect(self._toggle_vr)
        
        btn_layout.addWidget(self.btn_prev)
        btn_layout.addWidget(self.control_bar)
        btn_layout.addWidget(self.btn_next)
        
        layout.addWidget(self.video_container, 1)
        layout.addLayout(btn_layout)
        
        # This wrapper approach is safe.


    def _on_video_frame(self, frame):
        if self.vr_widget.isVisible():
            self.vr_widget.on_frame(frame)
        
    def _toggle_vr(self):
        """Toggle VR mode with stability safeguards."""
        is_vr = self.control_bar.btn_vr.isChecked()
        
        # Stability: Pause playback before switching output
        player_was_playing = self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if player_was_playing:
            self._player.pause()
            
        # Give backend a moment to stabilize (optional but safe)
        QApplication.processEvents()
        
        if is_vr:
            self.video_widget.hide()
            self.vr_widget.show()
            self._player.setVideoOutput(self._video_sink)
            # Default to 180 SBS mode (Mode 1)
            self.vr_widget.set_mode(1) 
        else:
            self.vr_widget.hide()
            self.video_widget.show()
            self._player.setVideoOutput(self.video_widget)
            
        # Resume if it was playing
        if player_was_playing:
            self._player.play()
            
        # Refocus for mouse events
        if is_vr:
            self.vr_widget.setFocus()
            
    def _on_position_changed(self, position: int):
        self.control_bar.set_position(position)
    
    def _on_duration_changed(self, duration: int):
        self.control_bar.set_duration(duration)
    
    def _on_state_changed(self, state: QMediaPlayer.PlaybackState):
        is_playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.control_bar.set_playing(is_playing)
        if is_playing:
            self.placeholder.hide()
    
    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.playback_finished.emit()
        elif status == QMediaPlayer.MediaStatus.LoadedMedia:
            self.placeholder.hide()
            
    def _on_tracks_changed(self):
        self.tracks_changed.emit()
            
    def _on_error(self, error, error_string):
        if error != QMediaPlayer.Error.NoError:
            # QMessageBox.warning(self, "播放错误", f"无法播放视频: {error_string}")
            print(f"Player Error: {error_string}")
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.placeholder.setGeometry(self.video_widget.rect())
        self.overlay.setGeometry(self.video_widget.rect())

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_fullscreen()
            event.accept()
    
    def open_file(self, file_path: str) -> bool:
        # Clean up previous playback properly
        self._cleanup_previous()
        
        # Check if URL
        if "://" in file_path:
            return self._open_url(file_path)
            
        if not Path(file_path).exists(): return False
        
        self._current_file = file_path
        self._is_encrypted = is_evf_file(file_path)
        
        if self._is_encrypted:
            return self._open_encrypted(file_path)
        else:
            return self._open_normal(file_path)
    
    def _cleanup_previous(self):
        """Cleanly shut down previous playback to avoid FFmpeg race conditions."""
        # 1. Stop the player first (stops requesting data)
        if self._player:
            self._player.stop()
        
        # 2. Clear source BEFORE shutting down stream decoder
        #    This ensures the player won't try to read from a closing stream
        if self._player:
            self._player.setSource(QUrl())
        
        # 3. Now safely close the stream decoder
        if self._stream_decoder:
            try:
                self._stream_decoder.close()
            except: pass
            self._stream_decoder = None
        
        # 4. Reset UI
        self.control_bar.reset()
        self.placeholder.show()
        self.placeholder.setGeometry(self.video_widget.rect())
            
    def _open_url(self, url: str) -> bool:
        # Check if it might be an encrypted/mixed file
        lower_url = url.lower()
        is_potential_enc = False
        
        if lower_url.endswith('.evf'):
            is_potential_enc = True
        elif lower_url.endswith(('.jpg', '.jpeg', '.png')):
            # Probe for mixed signature
            try:
                # Use RemoteFileReader to check footer efficiently
                reader = RemoteFileReader(url)
                reader.seek(0, 2)
                size = reader.tell()
                if size > 18:
                    reader.seek(-10, 2)
                    magic = reader.read(10)
                    if magic == MIXED_MAGIC:
                        is_potential_enc = True
                reader.close()
            except:
                pass
                
        if is_potential_enc:
            self._current_file = url
            self._is_encrypted = True
            return self._open_encrypted(url)
            
        try:
            self._player.setSource(QUrl(url))
            self.placeholder.hide()
            self.media_changed.emit(url)
            self._current_file = url
            self.play()
            return True
        except Exception as e:
            print(f"Error opening URL: {e}")
            return False
            
    def _open_normal(self, file_path: str) -> bool:
        try:
            self._player.setSource(QUrl.fromLocalFile(file_path))
            self.placeholder.hide()
            self.media_changed.emit(Path(file_path).name)
            self.play()
            return True
        except Exception as e:
            print(f"Error opening file: {e}")
            return False
    
    def _open_encrypted(self, file_path: str) -> bool:
        # Try cached password first
        if self._cached_password:
            try:
                if self._try_open_with_password(file_path, self._cached_password):
                    return True
            except Exception as e:
                # Only clear cache if it's definitely a wrong password (auth error)
                # Don't clear on transient errors (stream setup, timeout, etc.)
                err_msg = str(e).lower()
                if '密码' in err_msg or 'password' in err_msg or 'tag' in err_msg or 'decrypt' in err_msg or 'mac' in err_msg:
                    self._cached_password = None
                else:
                    # Transient error - retry once more
                    try:
                        if self._try_open_with_password(file_path, self._cached_password):
                            return True
                    except:
                        self._cached_password = None

        # Ask user
        first_attempt = True
        while True:
            password, ok = PasswordDialog.get_password_dialog(
                self,
                title="🔐 需要密码",
                message="此视频已加密，请输入密码解锁" if first_attempt else "密码错误，请重试"
            )
            if not ok: return False
            
            try:
                if self._try_open_with_password(file_path, password):
                    self._cached_password = password
                    return True
            except Exception as e:
                first_attempt = False
                # Only show error for definite failures
                err_msg = str(e).lower()
                if '超时' in err_msg or 'timeout' in err_msg:
                    QMessageBox.warning(self, "错误", "解密超时，请重试")
                else:
                    QMessageBox.warning(self, "错误", "密码错误或无法解密")
                
    def _try_open_with_password(self, file_path: str, password: str) -> bool:
        try:
            self._stream_decoder = StreamDecoder()
            
            # Handle Remote vs Local
            if "://" in file_path:
                source = RemoteFileReader(file_path)
                stream_path = self._stream_decoder.open(source, password)
            else:
                stream_path = self._stream_decoder.open(file_path, password)
                
            if not self._stream_decoder.wait_for_ready(): raise Exception("解密超时")
            
            # stream_path is now a http URL
            self._player.setSource(QUrl(stream_path))
            self.placeholder.hide()
            self.media_changed.emit(f"🔒 {Path(file_path).name}")
            self.play()
            return True
        except Exception:
            if self._stream_decoder:
                self._stream_decoder.close()
                self._stream_decoder = None
            raise # Re-raise to let caller handle
    
    def play(self):
        if self._player: self._player.play()
    
    def pause(self):
        if self._player: self._player.pause()
    
    def toggle_play(self):
        if not self._player: return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause()
        else:
            self.play()
    
    def stop(self):
        """Stop playback and clean up all resources."""
        if self._player:
            self._player.stop()
            self._player.setSource(QUrl())
        if self._stream_decoder:
            try:
                self._stream_decoder.close()
            except: pass
            self._stream_decoder = None
        self.control_bar.reset()
        self.placeholder.show()
        self.placeholder.setGeometry(self.video_widget.rect())
        self._current_file = None
        self._is_encrypted = False
    
    def seek(self, position_ms: int):
        if self._player: self._player.setPosition(position_ms)
    
    def seek_relative(self, offset_ms: int):
        if self._player:
            current = self._player.position()
            self.seek(max(0, current + offset_ms))
    
    def set_volume(self, volume: int):
        if self._audio_output:
            self._audio_output.setVolume(volume / 100.0)
            self.control_bar.set_volume(volume)
    
    def toggle_mute(self):
        if self._audio_output:
            muted = self._audio_output.isMuted()
            self._audio_output.setMuted(not muted)
            self.control_bar.set_muted(not muted)
    
    def set_speed(self, speed: float):
        if self._player: self._player.setPlaybackRate(speed)
    
    def toggle_fullscreen(self):
        self._is_fullscreen = not self._is_fullscreen
        
        # 1. Notify MainWindow to hide/show its UI (Sidebars, etc)
        parent = self.window()
        if hasattr(parent, 'toggle_fullscreen_mode'):
            parent.toggle_fullscreen_mode(self._is_fullscreen)
        else:
            # Fallback
            if self._is_fullscreen: parent.showFullScreen()
            else: parent.showNormal()
            
        # 2. Toggle internal UI (ControlBar, Prev/Next buttons)
        if self._is_fullscreen:
            # Hide controls for immersion
            self.control_bar.hide()
            self.btn_prev.hide()
            self.btn_next.hide()
            # Make video container black background explicit? Already set.
            # Hide cursor?
            # self.setCursor(Qt.CursorShape.BlankCursor)
        else:
            # Restore
            self.control_bar.show()
            self.btn_prev.show()
            self.btn_next.show()
            # self.setCursor(Qt.CursorShape.ArrowCursor)
    
    def take_screenshot(self):
        if not self._current_file: return
        QMessageBox.information(self, "截图", "截图功能需要暂停视频后使用系统截图工具")
    
    def set_aspect_ratio(self, ratio_str: str):
        if ratio_str == "16:9":
            self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        elif ratio_str == "Fill":
            self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.IgnoreAspectRatio)
        else:
            self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)

    def set_vr_resolution(self, width: int):
        """Set VR rendering resolution limit. 0=Native."""
        if self.vr_widget:
            self.vr_widget.set_max_resolution(width)

    def get_current_file(self) -> Optional[str]:
        return self._current_file
    
    def is_playing(self) -> bool:
        if self._player: return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        return False
    
    def get_volume(self) -> int:
        if self._audio_output: return int(self._audio_output.volume() * 100)
        return 100
        
    # --- Advanced Features ---
    
    def restart(self):
        """Restart playback from beginning."""
        if self._player:
            self._player.setPosition(0)
            self._player.play()

    def set_brightness(self, value):
        """Set brightness (-100 to 100). 0 is normal."""
        self._brightness = value
        
        # Simulated brightness using semi-transparent overlay
        # >0: White overlay
        # <0: Black overlay
        
        opacity = abs(value) / 100.0 * 0.8 # Max 80% opacity to not hide completely
        
        if value == 0:
            self.overlay.hide()
        elif value > 0:
            self.overlay.setStyleSheet("background-color: white;")
            effect = QGraphicsOpacityEffect(self.overlay)
            effect.setOpacity(opacity)
            self.overlay.setGraphicsEffect(effect)
            self.overlay.show()
            self.overlay.setGeometry(self.video_widget.rect())
        else:
            self.overlay.setStyleSheet("background-color: black;")
            effect = QGraphicsOpacityEffect(self.overlay)
            effect.setOpacity(opacity)
            self.overlay.setGraphicsEffect(effect)
            self.overlay.show()
            self.overlay.setGeometry(self.video_widget.rect())
            
    def get_audio_tracks(self):
        """Get list of audio tracks."""
        # Qt6 Multimedia: audioTracks() returns list of metadata
        if not self._player: return []
        return [str(i) for i in range(len(self._player.audioTracks()))] # Identify by index/desc

    def set_audio_track(self, index):
        if not self._player: return
        self._player.setActiveAudioTrack(index)
        
    def get_subtitle_tracks(self):
        if not self._player: return []
        return [str(i) for i in range(len(self._player.subtitleTracks()))]

    def set_subtitle_track(self, index):
        if not self._player: return
        self._player.setActiveSubtitleTrack(index)

    def _request_next(self):
        self.next_requested.emit()

    def _request_prev(self):
        self.prev_requested.emit()
