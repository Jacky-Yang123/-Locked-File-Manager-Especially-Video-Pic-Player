"""
Main window for the encrypted video player.
"""

import sys
import random
import subprocess
from typing import Optional
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QMenuBar, QMenu, QFileDialog, QListWidget, 
    QListWidgetItem, QFrame, QLabel, QSplitter,
    QApplication, QMessageBox, QStackedWidget,
    QInputDialog, QLineEdit, QTabWidget, QSystemTrayIcon
)
from PyQt6.QtCore import Qt, QMimeData, QPoint, QTimer, QSize
from PyQt6.QtGui import QAction, QKeySequence, QDragEnterEvent, QDropEvent, QIcon

from ui.video_player import VideoPlayer
from ui.widgets.audio_player import AudioPlayer
from ui.widgets.image_viewer import ImageViewer
from ui.widgets.text_viewer import TextViewer
from ui.widgets.pdf_viewer import PDFViewer
from ui.widgets.generic_handler import GenericHandler
from ui.widgets.video_context_menu import VideoContextMenu
from ui.widgets.settings_panel import SettingsPanel
from ui.widgets.media_library_view import MediaLibraryView
from ui.widgets.network_dialog import NetworkStreamDialog
from ui.network_share_dialog import NetworkShareDialog
from ui.widgets.lock_overlay import LockOverlay
from ui.widgets.standby_overlay import StandbyOverlay
from ui.access_log_dialog import AccessLogDialog
from ui.standby_password_dialog import StandbyPasswordDialog
from ui.encryption_dialog import EncryptionDialog
from ui.tools_dialog import ToolsDialog
from ui.styles import get_full_stylesheet
from core.media_library import MediaLibrary
from utils.constants import (
    APP_NAME, APP_VERSION, WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT,
    SUPPORTED_VIDEO_FORMATS, ENCRYPTED_EXTENSION
)
from utils.file_utils import (
    is_video_file, is_audio_file, is_image_file, 
    is_text_file, is_encrypted_file, is_supported_file,
    is_pdf_file, is_document_file
)
from core.evf_format import read_evf_header

class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        self._playlist: list[str] = []
        self._current_index = -1
        
        # Core Components
        self.media_library = MediaLibrary()
        
        # State
        self._loop_mode = "Off" # Off, One, All, Shuffle
        self._always_on_top = False
        self._frameless = False
        self._aspect_ratio = "Original"
        
        self._setup_ui()
        self._setup_menu()
        self._setup_context_menu()
        self._setup_settings_panel()
        self._setup_standby()
        self._setup_shortcuts()
        self._apply_style()
    
    def _setup_settings_panel(self):
        self.settings_panel = SettingsPanel(self)
        self.settings_panel.hide()
        
        # Connect settings signals
        self.settings_panel.brightness_changed.connect(self._on_brightness_changed)
        self.settings_panel.audio_track_changed.connect(self._on_audio_track_changed)
        self.settings_panel.subtitle_track_changed.connect(self._on_subtitle_track_changed)
        self.settings_panel.subtitle_load_requested.connect(self._load_subtitle_file)
        self.settings_panel.sleep_timer_changed.connect(self._on_sleep_timer_changed)
        self.settings_panel.lock_requested.connect(self._on_lock_requested)
        self.settings_panel.vr_resolution_changed.connect(self._on_vr_resolution_changed)
        
        # Sleep Timer
        self._sleep_timer = QTimer(self)
        self._sleep_timer.timeout.connect(self._on_sleep_timeout)
        
        # Lock Overlay
        self.lock_overlay = LockOverlay(self)
        self.lock_overlay.hide()

    def _setup_standby(self):
        """Setup standby mode components."""
        self.standby_overlay = StandbyOverlay(self.media_library, self)
        self.standby_overlay.hide()
        self.standby_overlay.unlocked.connect(self._on_standby_unlocked)
        
    def _on_standby_unlocked(self):
        """Resume state after unlocking from standby."""
        # Privacy-first: don't auto-resume playback after unlock
        pass

    def _enter_standby(self):
        """Trigger standby mode."""
        if not self.media_library.has_standby_password():
            res = QMessageBox.question(
                self, "设置密码", 
                "尚未设置待机密码。是否现在设置？\n(如果不设置，将无法进入待机模式以保护隐私)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if res == QMessageBox.StandardButton.Yes:
                self._show_standby_password_dialog()
            return

        # 1. FORCE stop ALL media widgets for privacy (not just current)
        self._stop_all_media_for_standby()
        
        # 2. Switch to neutral view BEFORE showing overlay
        self.stack.setCurrentWidget(self.library_view)
        
        # 3. Show overlay
        self.standby_overlay.setGeometry(self.rect())
        self.standby_overlay.show()
        self.standby_overlay.raise_()
        
        # 4. Force focus to overlay's password input for usability
        self.standby_overlay.setFocus()
        self.standby_overlay.pwd_input.setFocus()
        
        # 5. Hide Network Share Dialog for privacy
        if hasattr(self, '_network_share_dialog') and self._network_share_dialog.isVisible():
            self._network_share_dialog.hide()
        
    def _stop_all_media_for_standby(self):
        """Forcefully stop ALL media widgets to prevent any background playback."""
        # Stop video player completely
        try:
            self.video_player.stop()
        except: pass
        
        # Stop audio player
        try:
            self.audio_player.stop()
        except: pass
        
        # Clear image viewer
        try:
            if hasattr(self.image_viewer, 'clear'):
                self.image_viewer.clear()
        except: pass

    def _show_standby_password_dialog(self):
        dialog = StandbyPasswordDialog(self.media_library, self)
        dialog.exec()
        
    def _on_sleep_timer_changed(self, minutes):
        self._sleep_timer.stop()
        if minutes > 0:
            self._sleep_timer.start(minutes * 60 * 1000)
            
    def _on_sleep_timeout(self):
        self._stop_current()
        QApplication.quit()
        
    def _on_lock_requested(self):
        code, ok = QInputDialog.getText(
            self, "设置 PIN", "请输入解锁 PIN 码:", 
            QLineEdit.EchoMode.Password
        )
        if ok and code:
            self.lock_overlay.set_pin(code)
            self.lock_overlay.show()
            self.lock_overlay.raise_()
            self.lock_overlay.setGeometry(self.rect())

    def resizeEvent(self, event):
        if hasattr(self, 'lock_overlay') and self.lock_overlay.isVisible():
            self.lock_overlay.setGeometry(self.rect())
        if hasattr(self, 'standby_overlay') and self.standby_overlay.isVisible():
            self.standby_overlay.setGeometry(self.rect())
        super().resizeEvent(event)

    def _on_vr_resolution_changed(self, width):
        if self.stack.currentWidget() == self.video_player:
            self.video_player.set_vr_resolution(width)

    def _on_brightness_changed(self, value):
        if self.stack.currentWidget() == self.video_player:
            self.video_player.set_brightness(value)
            
    def _on_audio_track_changed(self, index):
        if self.stack.currentWidget() == self.video_player:
            # Index 0 might be "Auto" or first track. 
            # PotPlayer usually lists tracks.
            self.video_player.set_audio_track(index)
            
    def _on_subtitle_track_changed(self, index):
        if self.stack.currentWidget() == self.video_player:
            self.video_player.set_subtitle_track(index)
            
    def _load_subtitle_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载字幕", "", "Subtitle Files (*.srt *.ass *.ssa *.sub)")
        if path:
            # QtMultimedia doesn't easily support loading external subs dynamically 
            # without resetting media or using native features.
            # We will use setSource with QMediaContent if needed, or notify user.
            # Actually QMediaPlayer setSource can't attach sub easily.
            # But we can try URL sidecar if named same.
            QMessageBox.information(self, "Info", "External subtitle loading requires restarting playback with subtitle file in same directory for now.")

    def _update_settings_tracks(self):
        if self.stack.currentWidget() == self.video_player:
            a_tracks = self.video_player.get_audio_tracks()
            s_tracks = self.video_player.get_subtitle_tracks()
            self.settings_panel.update_audio_tracks(a_tracks)
            self.settings_panel.update_subtitle_tracks(s_tracks)

    def _setup_ui(self):
        """Setup the main window UI."""
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.resize(1400, 800)
        
        self.setAcceptDrops(True)
        
        # System Tray
        self._setup_tray()
        
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Viewer Area (Stacked)
        self.stack = QStackedWidget()
        
        # 0: Video
        self.video_player = VideoPlayer()
        self.video_player.media_changed.connect(self._on_media_changed)
        self.video_player.playback_finished.connect(self._on_playback_finished)
        self.video_player.context_menu_requested.connect(self._show_context_menu)
        self.video_player.tracks_changed.connect(self._update_settings_tracks)
        self.video_player.next_requested.connect(self._play_next_manual)
        self.video_player.prev_requested.connect(self._play_previous)
        self.stack.addWidget(self.video_player)
        
        # 1: Audio
        self.audio_player = AudioPlayer()
        self.audio_player.media_changed.connect(self._on_media_changed)
        self.audio_player.playback_finished.connect(self._on_playback_finished)
        self.audio_player.context_menu_requested.connect(self._show_context_menu)
        self.stack.addWidget(self.audio_player)
        
        # 2: Image
        self.image_viewer = ImageViewer()
        self.image_viewer.navigation_requested.connect(self._on_image_navigation)
        self.image_viewer.context_menu_requested.connect(self._show_context_menu)
        self.stack.addWidget(self.image_viewer)
        
        # 3: Text
        self.text_viewer = TextViewer()
        self.stack.addWidget(self.text_viewer)
        
        # 4: Generic
        self.generic_handler = GenericHandler()
        self.stack.addWidget(self.generic_handler)
        
        # 5: PDF Viewer
        self.pdf_viewer = PDFViewer()
        self.stack.addWidget(self.pdf_viewer)
        
        # 6: Media Library
        self.library_view = MediaLibraryView(self.media_library)
        self.library_view.file_selected.connect(self._on_library_file_selected)
        self.stack.addWidget(self.library_view)
        
        # Default view: Library
        self.stack.setCurrentWidget(self.library_view)
        
        # Playlist/Favorites Panel
        self.right_panel = QFrame()
        self.right_panel.setObjectName("playlist")
        self.right_panel.setFixedWidth(280)
        
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        
        self.playlist_tabs = QTabWidget()
        self.playlist_tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab { background: #2b2b2b; color: #aaa; padding: 8px 16px; }
            QTabBar::tab:selected { background: #3d3d3d; color: white; border-bottom: 2px solid #3498db; }
        """)
        
        # 1. Play Queue
        self.playlist_widget = QListWidget()
        self.playlist_widget.setStyleSheet("background-color: transparent; border: none;")
        self.playlist_widget.itemDoubleClicked.connect(self._on_playlist_item_double_clicked)
        self.playlist_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_widget.customContextMenuRequested.connect(self._show_playlist_menu)
        self.playlist_widget.setIconSize(QSize(48, 32))
        self.playlist_widget.setSpacing(2)
        
        # 2. Favorites
        self.favorites_widget = QListWidget()
        self.favorites_widget.setStyleSheet("background-color: transparent; border: none;")
        self.favorites_widget.itemDoubleClicked.connect(self._on_favorite_item_double_clicked)
        self.favorites_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.favorites_widget.customContextMenuRequested.connect(self._show_favorites_menu)
        self.favorites_widget.setIconSize(QSize(48, 32))
        self.favorites_widget.setSpacing(2)
        
        self.playlist_tabs.addTab(self.playlist_widget, "播放列表")
        self.playlist_tabs.addTab(self.favorites_widget, "收藏夹 (Favorites)")
        
        right_layout.addWidget(self.playlist_tabs)
        
        splitter.addWidget(self.stack)
        splitter.addWidget(self.right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        
        layout.addWidget(splitter)
        
        # Init Favorites
        self._refresh_favorites_ui()
    
    def _setup_tray(self):
        """Setup system tray icon."""
        from PyQt6.QtWidgets import QSystemTrayIcon, QStyle
        from PyQt6.QtGui import QIcon
        
        self.tray_icon = QSystemTrayIcon(self)
        
        # Use standard icon if app icon not available
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        self.tray_icon.setIcon(icon)
        
        # Tray menu
        tray_menu = QMenu()
        restore_action = QAction("显示主窗口", self)
        restore_action.triggered.connect(self.showNormal)
        tray_menu.addAction(restore_action)
        
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(QApplication.quit)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()
        
    def _on_tray_activated(self, reason):
        from PyQt6.QtWidgets import QSystemTrayIcon
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide() # Minimizes to tray if clicked while visible
            else:
                self.showNormal()
                self.activateWindow()

    def changeEvent(self, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized:
                # User Minimize -> Auto Standby
                self._enter_standby()
                QTimer.singleShot(0, self.hide)
        super().changeEvent(event)
        
    def closeEvent(self, event):
        # Ensure tray is removed
        if hasattr(self, 'tray_icon'):
            self.tray_icon.hide()
        super().closeEvent(event)
        
    def _setup_menu(self):
        menubar = self.menuBar()
        menubar.setStyleSheet("""
            QMenuBar {
                background: rgba(0, 0, 0, 0.8);
                color: white;
                padding: 4px;
            }
            QMenuBar::item:selected {
                background: rgba(255, 255, 255, 0.1);
            }
        """)
        
        # File menu
        file_menu = menubar.addMenu("文件")
        
        open_action = QAction("打开文件...", self)
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.triggered.connect(self._open_file_dialog)
        file_menu.addAction(open_action)
        
        net_action = QAction("打开网络流...", self)
        net_action.setShortcut(QKeySequence("Ctrl+U"))
        net_action.triggered.connect(self._open_network_stream)
        file_menu.addAction(net_action)

        settings_action = QAction("控制面板 (Settings)", self)
        settings_action.setShortcut(QKeySequence("F7"))
        settings_action.triggered.connect(self._show_settings)
        file_menu.addAction(settings_action)
        
        # Network Share Action
        share_action = QAction("📡 网络共享...", self)
        share_action.setShortcut("Ctrl+Shift+N")
        share_action.triggered.connect(self._show_network_share)
        file_menu.addAction(share_action)
        
        open_folder_action = QAction("打开文件夹...", self)
        open_folder_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        open_folder_action.triggered.connect(self._open_folder)
        file_menu.addAction(open_folder_action)
        
        file_menu.addSeparator()
        
        encrypt_action = QAction("🔐 加密文件...", self)
        encrypt_action.setShortcut(QKeySequence("Ctrl+E"))
        encrypt_action.triggered.connect(self._show_encryption_dialog)
        file_menu.addAction(encrypt_action)
        
        decrypt_action = QAction("🔓 解密文件...", self)
        decrypt_action.setShortcut(QKeySequence("Ctrl+D"))
        decrypt_action.triggered.connect(self._show_decryption_dialog)
        file_menu.addAction(decrypt_action)
        
        new_win_action = QAction("新窗口", self)
        new_win_action.setShortcut(QKeySequence("Ctrl+N"))
        new_win_action.triggered.connect(self._new_window)
        file_menu.addAction(new_win_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("退出", self)
        exit_action.setShortcut(QKeySequence("Alt+F4"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Tools menu (New)
        tools_menu = menubar.addMenu("工具")
        
        enc_tools_action = QAction("🔐 加密工具箱...", self)
        enc_tools_action.setShortcut("F6")
        enc_tools_action.triggered.connect(self._show_tools_dialog)
        tools_menu.addAction(enc_tools_action)
        
        # Security menu (New)
        security_menu = menubar.addMenu("安全")
        
        standby_action = QAction("🌙 进入待机模式", self)
        standby_action.setShortcut(QKeySequence("Ctrl+Alt+L"))
        standby_action.triggered.connect(self._enter_standby)
        security_menu.addAction(standby_action)
        
        pwd_action = QAction("🔑 设置/修改待机密码...", self)
        pwd_action.triggered.connect(self._show_standby_password_dialog)
        security_menu.addAction(pwd_action)

        security_menu.addSeparator()

        log_action = QAction("📋 查看访问日志", self)
        log_action.triggered.connect(self._show_access_logs)
        security_menu.addAction(log_action)
        
        # Playback menu
        playback_menu = menubar.addMenu("播放")
        
        play_action = QAction("播放/暂停", self)
        play_action.setShortcut(QKeySequence("Space"))
        play_action.triggered.connect(self._toggle_play_current)
        playback_menu.addAction(play_action)
        
        # View menu
        view_menu = menubar.addMenu("视图")
        
        fullscreen_action = QAction("全屏", self)
        fullscreen_action.setShortcut(QKeySequence("F"))
        fullscreen_action.triggered.connect(self._toggle_fullscreen_current)
        view_menu.addAction(fullscreen_action)
        
        library_action = QAction("媒体库", self)
        library_action.setShortcut(QKeySequence("Ctrl+L"))
        library_action.triggered.connect(self._show_library)
        view_menu.addAction(library_action)
        
        view_menu.addSeparator()
        
        self.unlock_thumbs_action = QAction("🔓 解锁缩略图...", self)
        self.unlock_thumbs_action.setCheckable(True)
        self.unlock_thumbs_action.triggered.connect(self._toggle_thumbnail_unlock)
        view_menu.addAction(self.unlock_thumbs_action)
        
        # Help
        help_menu = menubar.addMenu("帮助")
        help_menu.addAction("关于", self._show_about)

    def _toggle_thumbnail_unlock(self, checked):
        if checked:
            # Unlock
            from ui.password_dialog import PasswordDialog
            password, ok = PasswordDialog.get_password_dialog(
                self, 
                "输入密码", 
                "请输入密码以预览加密文件缩略图:"
            )
            
            if ok and password:
                self.media_library.set_thumbnail_password(password)
                self.unlock_thumbs_action.setText("🔐 锁定缩略图")
                # Trigger refresh?
                # We need to tell library to rescan or re-gen thumbs.
                # Currently scanner triggers gen.
                # Maybe just a method to retry failed thumbs?
                # Or just rescan current folder view?
                if self.stack.currentWidget() == self.library_view:
                    pass # User likely needs to rescan or we implement "retry all enc thumbs"
            else:
                self.unlock_thumbs_action.setChecked(False)
        else:
            # Lock
            self.media_library.set_thumbnail_password(None)
            self.unlock_thumbs_action.setText("🔓 解锁缩略图...")

    def _setup_context_menu(self):
        """Setup video context menu."""
        self.context_menu = VideoContextMenu(self)
        
        # Connect signals
        self.context_menu.open_file_requested.connect(self._open_file_dialog)
        self.context_menu.open_folder_requested.connect(self._open_folder)
        self.context_menu.encryption_requested.connect(self._show_encryption_dialog)
        self.context_menu.decryption_requested.connect(self._show_decryption_dialog)
        
        self.context_menu.play_pause_requested.connect(self._toggle_play_current)
        self.context_menu.stop_requested.connect(self._stop_current)
        self.context_menu.prev_requested.connect(self._play_previous)
        self.context_menu.next_requested.connect(self._play_next_manual) # Manual next
        
        self.context_menu.loop_mode_changed.connect(self._set_loop_mode)
        self.context_menu.speed_changed.connect(self._set_speed)
        
        self.context_menu.aspect_ratio_changed.connect(self._set_aspect_ratio)
        self.context_menu.rotate_changed.connect(self._rotate_video) # Placeholder
        
        self.context_menu.always_on_top_toggled.connect(self._toggle_always_on_top)
        self.context_menu.frameless_toggled.connect(self._toggle_frameless)
        self.context_menu.new_window_requested.connect(self._new_window)
        
    def _setup_shortcuts(self):
        pass
    
    def _apply_style(self):
        self.setStyleSheet(get_full_stylesheet())
    
    def _open_file_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "打开文件", "", "All Files (*.*)")
        if files:
            for f in files: self._add_to_playlist(f)
            self._play_file(files[0])
            
    def _open_network_stream(self):
        dialog = NetworkStreamDialog(self)
        if dialog.exec():
            url = dialog.get_url()
            if url:
                self._play_file(url)
            
    def _open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "打开文件夹")
        if folder:
            self._add_folder_recursive(folder)
            if self.playlist_widget.count() > 0:
                # Play first if nothing playing
                if self._current_index == -1:
                    first = self.playlist_widget.item(0).data(Qt.ItemDataRole.UserRole)
                    self._play_file(first)

    def _add_folder_recursive(self, folder_path):
        from utils.file_utils import is_supported_file, is_encrypted_file
        for file in Path(folder_path).rglob("*"):
             if file.is_file():
                 path = str(file)
                 if is_supported_file(path) or is_encrypted_file(path):
                     self._add_to_playlist(path)

    def _add_to_playlist(self, path: str):
        if path in self._playlist: return
        self._playlist.append(path)
        self._add_to_playlist_ui(path)
    

            
    def toggle_fullscreen_mode(self, enable: bool):
        """
        Toggle immersive fullscreen mode:
        - Hide sidebars/panels
        - Hide window chrome
        """
        if enable:
            self.showFullScreen()
            # Hide UI elements
            if hasattr(self, 'left_sidebar'): self.left_sidebar.hide()
            if hasattr(self, 'right_panel'): self.right_panel.hide()
            if self.menuBar(): self.menuBar().hide()
            if hasattr(self, 'splitter'): self.splitter.setHandleWidth(0)
        else:
            self.showNormal()
            # Restore UI elements
            if hasattr(self, 'left_sidebar'): self.left_sidebar.show()
            if hasattr(self, 'right_panel'): self.right_panel.show()
            if self.menuBar(): self.menuBar().show()
            if hasattr(self, 'splitter'): self.splitter.setHandleWidth(2) # Default?

    def _play_file(self, path: str):
        """Open/Play a file."""
        self._current_playing_path = path # Track for context navigation
        
        # Add to history
        self.media_library.add_history(path)
        
        if path in self._playlist:
            self._current_index = self._playlist.index(path)
            self.playlist_widget.setCurrentRow(self._current_index)
            
        # Also highlight in Favorite if visible
        try:
             # Sync highlight in favorites if active
             if self.playlist_tabs.currentIndex() == 1:
                 # Search items
                 items = self.favorites_widget.findItems(Path(path).name, Qt.MatchFlag.MatchContains)
                 for it in items:
                     if it.data(Qt.ItemDataRole.UserRole) == path:
                         self.favorites_widget.setCurrentItem(it)
                         break
        except: pass
        
        # Determine target widget FIRST
        target_widget = None
        is_enc = False
        
        try:
            # Network Stream
            if "://" in path:
                target_widget = self.video_player
            else:
                if is_encrypted_file(path):
                    is_enc = True
                    # Need to peek header to know type
                    from core.evf_format import read_evf_header, detect_mixed_file
                    offset = detect_mixed_file(path)
                    start_pos = 0 if offset == -1 else offset
                    
                    with open(path, 'rb') as f:
                        f.seek(start_pos)
                        header = read_evf_header(f)
                        ext = header.original_ext
                        name = f"dummy{ext}"
                        
                        if is_video_file(name): target_widget = self.video_player
                        elif is_audio_file(name): target_widget = self.audio_player
                        elif is_image_file(name): target_widget = self.image_viewer
                        elif is_pdf_file(name): target_widget = self.pdf_viewer
                        elif is_text_file(name): target_widget = self.text_viewer
                        else: target_widget = self.generic_handler
                else:
                    if is_video_file(path): target_widget = self.video_player
                    elif is_audio_file(path): target_widget = self.audio_player
                    elif is_image_file(path): target_widget = self.image_viewer
                    elif is_pdf_file(path): target_widget = self.pdf_viewer
                    elif is_text_file(path): target_widget = self.text_viewer
                    else: target_widget = self.generic_handler
            
            # Smart Stop: Only stop non-target widgets
            # If target is video_player, don't stop it here, let video_player.open_file handle it internally
            # This prevents "Double Stop" which causes FFmpeg interruption errors.
            
            if target_widget != self.video_player: self.video_player.stop()
            if target_widget != self.audio_player: self.audio_player.stop()
            # Image/Text viewers don't really have 'stop' state that matters much, but good practice
            
            if target_widget:
                self.stack.setCurrentWidget(target_widget)
                if hasattr(target_widget, 'load_file'): # generic
                    target_widget.load_file(path)
                else:
                    # open_file will handle internal stop/reset
                    target_widget.open_file(path)
                    
                # Apply current settings if video
                if target_widget == self.video_player:
                    self.video_player.set_aspect_ratio(self._aspect_ratio)
                    
        except Exception as e:
            print(f"Play Error: {e}")
            self.stack.setCurrentWidget(self.generic_handler)
            self.generic_handler.load_file(path, "Error")

    def _play_previous(self):
        current_list = self._get_current_paths_context()
        if not current_list: return
        
        current_path = getattr(self, '_current_playing_path', None)
        idx = 0
        if current_path and current_path in current_list:
            idx = current_list.index(current_path)
        
        new_index = idx - 1
        if new_index < 0:
            if self._loop_mode == "All":
                new_index = len(current_list) - 1
            else:
                return # Stop at start
                
        self._play_file(current_list[new_index])
            
    def _play_next(self):
        """Auto advance based on loop mode."""
        current_list = self._get_current_paths_context()
        if not current_list: return
        
        if self._loop_mode == "One":
            current_widget = self.stack.currentWidget()
            if hasattr(current_widget, 'restart'):
                current_widget.restart()
            else:
                current_path = getattr(self, '_current_playing_path', None)
                if current_path: self._play_file(current_path)
            return
        
        if self._loop_mode == "Shuffle":
            random_idx = random.randint(0, len(current_list)-1)
            self._play_file(current_list[random_idx])
            return

        current_path = getattr(self, '_current_playing_path', None)
        idx = 0
        if current_path and current_path in current_list:
            idx = current_list.index(current_path)

        new_index = idx + 1
        if new_index >= len(current_list):
            if self._loop_mode == "All":
                new_index = 0
            else:
                return # Stop at end
        
        self._play_file(current_list[new_index])

    def _play_next_manual(self):
        """User clicked next."""
        # For manual next, we usually ignore 'One' loop mode and just go next
        if not self._playlist: return
        
        new_index = self._current_index + 1
        if new_index >= len(self._playlist):
            new_index = 0 # Wrap manual
            
        self._play_file(self._playlist[new_index])

    def _on_playlist_item_double_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path: self._play_file(path)
        
    def _on_library_file_selected(self, path):
        """Handle file selection from library with playlist sync."""
        # 1. Get ordered list from library view
        # This ensures 'Next' follows the visual order (Sort/Filter)
        paths = self.library_view.get_visible_paths()
        
        if paths:
            # Update Playlist
            self._playlist = paths
            self._current_index = -1
            if path in self._playlist:
                self._current_index = self._playlist.index(path)
            
            # Update Playlist UI
            self.playlist_widget.clear()
            # Optimization: If list is huge (1000+), adding all widget items is slow.
            # But user wants to see the list?
            # Let's add them. If too slow, we can lazy load or just show current context.
            # For now, add all to reflect "Current Playlist"
            # Limit to 500 for performance? Or just full list.
            # Let's try full list.
            
            # Bulk add is faster?
            # self.playlist_widget.addItems(...) but we need icons and data.
            # Let's just add items.
            
            # To avoid freezing UI on large libraries, maybe just set internal playlist
            # and only populate UI for a window?
            # Or just add them. Python is slow but Qt C++ is fast.
            # Let's limit UI update if > 2000 items?
            
            if len(paths) < 2000:
                self.playlist_widget.setUpdatesEnabled(False)
                for p in paths:
                    self._add_to_playlist_ui(p)
                self.playlist_widget.setUpdatesEnabled(True)
                
                if self._current_index >= 0:
                    self.playlist_widget.setCurrentRow(self._current_index)
            else:
                # Too many items, just show current one + hint?
                self.playlist_widget.clear()
                self._add_to_playlist_ui(path) # Just show current
                
        self._play_file(path)

    # --- Favorites Logic ---
    def _refresh_favorites_ui(self):
        self.favorites_widget.clear()
        favs = self.media_library.get_favorites()
        for path in favs:
            if Path(path).exists():
                self._add_to_list_widget(self.favorites_widget, path)
                
    def _add_to_list_widget(self, widget: QListWidget, path: str):
        """Generic add with thumbnail support."""
        from utils.file_utils import is_encrypted_file, is_video_file, is_audio_file, is_image_file, is_text_file
        
        # Determine Icon
        icon = QIcon.fromTheme("text-x-generic")
        text_icon = "📄"
        
        if is_encrypted_file(path): text_icon = "🔒"
        elif is_video_file(path): text_icon = "🎬"
        elif is_audio_file(path): text_icon = "🎵"
        elif is_image_file(path): text_icon = "🖼️"
        elif is_text_file(path): text_icon = "📝"
            
        # Try to load thumbnail
        import hashlib
        try:
            file_hash = hashlib.md5(path.encode('utf-8')).hexdigest()
            loaded_icon = None
            if hasattr(self, 'library_view') and file_hash in self.library_view._pixmap_cache:
                loaded_icon = QIcon(self.library_view._pixmap_cache[file_hash])
            if not loaded_icon:
                thumb_path = Path("thumbnails") / f"{file_hash}.jpg"
                if thumb_path.exists():
                    loaded_icon = QIcon(str(thumb_path))
            if loaded_icon: icon = loaded_icon
        except: pass

        filename = Path(path).name
        item = QListWidgetItem()
        if not icon.isNull(): item.setIcon(icon)
        
        display_text = filename if (not icon.isNull() and icon.name() == "") else f"{text_icon} {filename}"
        # Wait, if icon is generic theme icon, its name() might not be empty?
        # Simpler: If we loaded a custom pixmap (loaded_icon), use clean text.
        # Otherwise use text_icon prefix.
        
        # Correct logic:
        # Check if we actually loaded a custom thumb? 
        # The code above sets loaded_icon.
        # Re-check loaded_icon variable availability? No, local scope.
        # Let's rely on checking if it was not generic. 
        # But for robustness, let's just pass a flag?
        # Refactoring `_add_to_playlist_ui` might be better but I'm inlining here to avoid breaking existing.
        # Wait, I can replace `_add_to_playlist_ui` with this method?
        # Yes.
        
        item.setText(display_text) # Temporary approximation
        item.setData(Qt.ItemDataRole.UserRole, path)
        widget.addItem(item)

    def _on_favorite_item_double_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        # SET CONTEXT TO FAVORITES
        self._current_context = "favorites" 
        self._play_file(path)

    def _on_playlist_item_double_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        # SET CONTEXT TO PLAYLIST
        self._current_context = "playlist"
        if path: self._play_file(path)
        
    def _add_to_playlist_ui(self, path):
         self._add_to_list_widget(self.playlist_widget, path)

    def _show_favorites_menu(self, point):
        item = self.favorites_widget.itemAt(point)
        if not item: return
        path = item.data(Qt.ItemDataRole.UserRole)
        
        menu = QMenu()
        play_act = QAction("播放", self)
        play_act.triggered.connect(lambda: self._on_favorite_item_double_clicked(item))
        menu.addAction(play_act)
        
        del_act = QAction("❌ 移除收藏", self)
        del_act.triggered.connect(lambda: self._remove_favorite(path))
        menu.addAction(del_act)
        
        menu.exec(self.favorites_widget.mapToGlobal(point))
        
    def _remove_favorite(self, path):
        self.media_library.remove_favorite(path)
        self._refresh_favorites_ui()

    def _add_current_to_favorite(self):
        """Add currently playing file to favorites."""
        current_widget = self.stack.currentWidget()
        path = None
        if hasattr(current_widget, 'get_current_file'):
            path = current_widget.get_current_file()
            
        if path:
            self.media_library.add_favorite(path)
            self._refresh_favorites_ui()
            # Flash status?
            self.tray_icon.showMessage(
                "收藏成功", 
                f"已添加到收藏夹:\n{Path(path).name}", 
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )

    # --- Updated Navigation Logic for Context ---
    def _get_current_paths_context(self):
        """Return the active list of paths based on context."""
        ctx = getattr(self, '_current_context', 'playlist')
        
        # If user explicitly selected the other tab, maybe switch context?
        # But clicking is explicit. Tab switching is viewing.
        # User requested: "If under Favorites label [tab], next/prev from favorites."
        # This implies Tab Visibility dictates context?
        # "If in favorites tag [tab]" -> Yes. 
        # So check active tab index?
        if self.playlist_tabs.currentIndex() == 1: # Favorites Tab Active
            return self.media_library.get_favorites()
        else:
            return self._playlist # Default Playlist

    # ... Now update _on_image_navigation and _play_next/prev to use this ...

        
    def _on_image_navigation(self, direction):
        """Handle Next/Prev image request."""
        # Use context-aware list
        current_list = self._get_current_paths_context()
        if not current_list: return
        
        # Find current index in this list
        # Current widget has path?
        current_path = self.image_viewer.image_path if hasattr(self.image_viewer, 'image_path') else None
        # Actually Image Viewer might not expose path property directly? 
        # But _play_file sets it? No, generic file opening.
        # We need to know current file path reliably.
        # self._playlist logic used _current_index. 
        # But if we switch context, _current_index might be wrong for that list.
        # Better to search pattern.
        
        # Let's track `self._current_file_path` globally in _play_file?
        # Creating a property or using widget getter is best.
        # Let's assume user just played something.
        
        # Fallback: Searching in list for current selection if we don't track it.
        # But wait, `_play_file` sets `_current_index` for `_playlist`. 
        # If we are in Favorites context, we should find index in Favorites.
        
        # Simpler: Get current played path.
        path = None
        if hasattr(self.image_viewer, 'current_path'): # I should add this property to image viewer
            path = self.image_viewer.current_path
        
        # If not, try finding it?
        # Actually, let's update `_play_file` to set `self._current_playing_path`.
        if hasattr(self, '_current_playing_path'):
            path = self._current_playing_path
            
        start_idx = 0
        if path and path in current_list:
            start_idx = current_list.index(path)
            
        count = len(current_list)
        step = 1 if direction == "next" else -1
        
        idx = start_idx
        found = False
        
        for _ in range(count):
            idx = (idx + step) % count
            candidate_path = current_list[idx]
            
            is_candidate = False
            if is_image_file(candidate_path): is_candidate = True
            elif is_encrypted_file(candidate_path):
                 # Fast type check
                 try:
                    with open(candidate_path, 'rb') as f:
                         from core.evf_format import read_evf_header
                         h = read_evf_header(f)
                         if is_image_file(f"x{h.original_ext}"):
                             is_candidate = True
                 except: pass
            
            if is_candidate:
                self._play_file(candidate_path)
                found = True
                break
                
        if not found:
            # Maybe show message "No more images"
            pass

    def _show_playlist_menu(self, point):
        # Could implement playlist context menu here
        pass

    def _on_media_changed(self, name):
        self.setWindowTitle(f"{name} - {APP_NAME}")
        
    def _on_playback_finished(self):
        self._play_next()
        
    def _show_encryption_dialog(self):
        dialog = EncryptionDialog(self)
        dialog.exec()
        
    def _show_decryption_dialog(self):
        from ui.decryption_dialog import DecryptionDialog
        dialog = DecryptionDialog(self)
        dialog.exec()
        
    def _show_about(self):
        QMessageBox.about(self, "About", f"{APP_NAME} v{APP_VERSION}")
        
    def _show_settings(self):
        self._update_settings_tracks()
        self.settings_panel.show()
        self.settings_panel.raise_()
        self.settings_panel.activateWindow()

    def _show_library(self):
        self._stop_current() # Auto-stop current playback
        self.stack.setCurrentWidget(self.library_view)

    def _toggle_play_current(self):
        current = self.stack.currentWidget()
        if hasattr(current, "toggle_play"): current.toggle_play()
            
    def _stop_current(self):
        current = self.stack.currentWidget()
        if hasattr(current, "stop"): current.stop()
        # Return to Library
        self.stack.setCurrentWidget(self.library_view)

    def _show_network_share(self):
        """Show the network share configuration dialog."""
        if not hasattr(self, '_network_share_dialog'):
            self._network_share_dialog = NetworkShareDialog(self)
        self._network_share_dialog.show()
        self._network_share_dialog.raise_()
        self._network_share_dialog.activateWindow()

    def _toggle_fullscreen_current(self):
        current = self.stack.currentWidget()
        if hasattr(current, "toggle_fullscreen"):
            current.toggle_fullscreen()
        else:
            if self.isFullScreen(): self.showNormal()
            else: self.showFullScreen()
            
    # Context Menu Handlers
    def _show_context_menu(self, point):
        # Update menu state
        self.context_menu.update_states(
            self._loop_mode, 
            self._aspect_ratio, 
            self._always_on_top,
            self._frameless
        )
        
        # Populate Bookmarks
        self.context_menu.bookmarks_menu.clear()
        # Populate Bookmarks
        self.context_menu.bookmarks_menu.clear()
        self.context_menu.bookmarks_menu.addAction("⭐ 加入收藏").triggered.connect(self._add_current_to_favorite)
        self.context_menu.bookmarks_menu.addSeparator()
        self.context_menu.bookmarks_menu.addAction("添加书签").triggered.connect(self._add_bookmark_current)
        self.context_menu.bookmarks_menu.addSeparator()
        
        current_file = None
        current_widget = self.stack.currentWidget()
        if hasattr(current_widget, 'get_current_file'):
            current_file = current_widget.get_current_file()
            
        if current_file:
            bookmarks = self.media_library.get_bookmarks(current_file)
            from utils.file_utils import format_time
            if bookmarks:
                for pos in bookmarks:
                    time_str = format_time(pos // 1000)
                    self.context_menu.bookmarks_menu.addAction(f"书签 @ {time_str}").triggered.connect(
                        lambda checked, p=pos: self._seek_current(p)
                    )
            else:
                self.context_menu.bookmarks_menu.addAction("无书签").setEnabled(False)
        else:
             self.context_menu.bookmarks_menu.addAction("未播放文件").setEnabled(False)

        from PyQt6.QtGui import QCursor
        self.context_menu.exec(QCursor.pos())

    def _add_bookmark_current(self):
        current_widget = self.stack.currentWidget()
        if hasattr(current_widget, 'get_current_file'):
            path = current_widget.get_current_file()
            # Need position. VideoPlayer has _player.position() but we need to expose it or use control bar logic?
            # VideoPlayer binds position to control bar.
            # But simpler: VideoPlayer.get_position()
            # Let's check VideoPlayer. It has _player.position() but no public getter?
            # It has _on_position_changed.
            # I can rely on ControlBar? Or just access _player if I'm brave.
            # Better: add get_position() to VideoPlayer/AudioPlayer.
            # For now I will access `_player.position()` if available
            pos = 0
            if hasattr(current_widget, '_player') and current_widget._player:
                pos = current_widget._player.position()
                
            if path and pos > 0:
                self.media_library.add_bookmark(path, pos)
                QMessageBox.information(self, "书签", "书签已添加")

    def _seek_current(self, pos):
        current_widget = self.stack.currentWidget()
        if hasattr(current_widget, 'seek'):
            current_widget.seek(pos)

    def _set_loop_mode(self, mode):
        self._loop_mode = mode
        
    def _set_speed(self, speed):
        current = self.stack.currentWidget()
        if hasattr(current, "set_speed"): current.set_speed(speed)
        
    def _set_aspect_ratio(self, ratio):
        self._aspect_ratio = ratio
        if self.stack.currentWidget() == self.video_player:
            self.video_player.set_aspect_ratio(ratio)
            
    def _rotate_video(self, deg):
        # Placeholder
        QMessageBox.information(self, "Info", "Video rotation not supported in this renderer.")

    def _toggle_always_on_top(self, enabled):
        self._always_on_top = enabled
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        
    def _toggle_frameless(self, enabled):
        self._frameless = enabled
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowType.FramelessWindowHint
        else:
            flags &= ~Qt.WindowType.FramelessWindowHint
        self.setWindowFlags(flags)
        self.show()
        
    def _new_window(self):
        """Launch new instance."""
        import subprocess
        import sys
        subprocess.Popen([sys.executable, "main.py"])

    # Drag & Drop
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        
    def dropEvent(self, event: QDropEvent):
        # Check modifiers
        modifiers = event.modifiers()
        add_only = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        
        first_file = None
        count = 0
        
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if Path(path).exists():
                if Path(path).is_dir():
                    self._add_folder_recursive(path) # Shallow or recursive? Recursive now.
                else:
                    self._add_to_playlist(path)
                    if not first_file: first_file = path
                count += 1
                
        if not add_only and first_file:
            self._play_file(first_file)

    def closeEvent(self, event):
        """Cleanup resources on close."""
        # Stop network share if running
        if hasattr(self, '_network_share_dialog'):
            self._network_share_dialog.close()
        
        # Stop any active playback
        self.video_player.stop()
        self.audio_player.stop()
        
        super().closeEvent(event)

    def keyPressEvent(self, event):
        current = self.stack.currentWidget()
        key = event.key()
        if key == Qt.Key.Key_Space:
            self._toggle_play_current()
        elif key == Qt.Key.Key_Left:
             if hasattr(current, "seek_relative"): current.seek_relative(-5000)
        elif key == Qt.Key.Key_Right:
             if hasattr(current, "seek_relative"): current.seek_relative(5000)
        elif key == Qt.Key.Key_Escape and self.isFullScreen():
             self.showNormal()
        super().keyPressEvent(event)
    def _show_access_logs(self):
        dialog = AccessLogDialog(self)
        dialog.exec()
    def _show_decryption_dialog(self):
        # We can use the new tools dialog's decrypt tab or keep old one.
        # Let's redirect to new tools dialog -> Decrypt tab
        self._show_tools_dialog(tab_index=2)
        
    def _show_encryption_dialog(self):
        # Use new tools dialog -> Encrypt tab
        self._show_tools_dialog(tab_index=0)

    def _show_tools_dialog(self, tab_index=0):
        # Tools Dialog
        if not hasattr(self, '_tools_dialog') or not self._tools_dialog.isVisible():
            self._tools_dialog = ToolsDialog(self)
        
        # If it's a QAction trigger, tab_index might be False/Checked, so check type
        if isinstance(tab_index, bool): 
            tab_index = 0
            
        self._tools_dialog.tabs.setCurrentIndex(tab_index)
        self._tools_dialog.show()
        self._tools_dialog.raise_()
        self._tools_dialog.activateWindow()
        
    def _show_access_logs(self):
        dialog = AccessLogDialog(self)
        dialog.exec()
        
    def _show_network_share(self):
        if not hasattr(self, '_network_share_dialog'):
             self._network_share_dialog = NetworkShareDialog(self)
        self._network_share_dialog.show()
        self._network_share_dialog.raise_()
        self._network_share_dialog.activateWindow()

    def _show_settings(self):
        self.settings_panel.show()
        self.settings_panel.raise_()
        
    def _show_library(self):
        self.stack.setCurrentWidget(self.library_view)
        
    def _show_about(self):
        QMessageBox.about(self, "关于", "Locked Video Player\nVersion 1.0")
        
    def _new_window(self):
        # Launch new instance
        subprocess.Popen([sys.executable, "main.py"])
