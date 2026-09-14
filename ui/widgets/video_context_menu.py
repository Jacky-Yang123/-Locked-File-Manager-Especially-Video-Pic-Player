"""
Comprehensive context menu for the video player (PotPlayer style).
"""

from PyQt6.QtWidgets import QMenu
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtCore import Qt, pyqtSignal

class VideoContextMenu(QMenu):
    """
    Advanced context menu with submenus for Playback, Video, Audio, Window, etc.
    """
    
    # Signals for actions that need to be handled by controller
    open_file_requested = pyqtSignal()
    open_folder_requested = pyqtSignal()
    encryption_requested = pyqtSignal()
    decryption_requested = pyqtSignal()
    
    play_pause_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    prev_requested = pyqtSignal()
    next_requested = pyqtSignal()
    
    loop_mode_changed = pyqtSignal(str) # "Off", "One", "All", "Shuffle"
    speed_changed = pyqtSignal(float)
    
    aspect_ratio_changed = pyqtSignal(str) # "Original", "16:9", "4:3", "Fill"
    rotate_changed = pyqtSignal(int) # 0, 90, 180, 270
    
    always_on_top_toggled = pyqtSignal(bool)
    frameless_toggled = pyqtSignal(bool)
    new_window_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_actions()
        
    def _setup_actions(self):
        """Setup menu actions."""
        # --- Open ---
        open_menu = self.addMenu("打开 (Open)")
        open_menu.addAction("打开文件...").triggered.connect(self.open_file_requested.emit)
        open_menu.addAction("打开文件夹...").triggered.connect(self.open_folder_requested.emit)
        open_menu.addSeparator()
        open_menu.addAction("加密文件...").triggered.connect(self.encryption_requested.emit)
        open_menu.addAction("解密文件...").triggered.connect(self.decryption_requested.emit)
        
        self.addSeparator()
        
        # --- Playback ---
        self.addAction("播放/暂停").triggered.connect(self.play_pause_requested.emit)
        self.addAction("停止").triggered.connect(self.stop_requested.emit)
        
        nav_menu = self.addMenu("导航 (Navigate)")
        nav_menu.addAction("上一个").triggered.connect(self.prev_requested.emit)
        nav_menu.addAction("下一个").triggered.connect(self.next_requested.emit)
        
        # Loop Mode
        loop_menu = self.addMenu("循环 (Loop)")
        loop_group = QActionGroup(self)
        
        self.loop_off = loop_menu.addAction("关闭循环")
        self.loop_off.setCheckable(True)
        self.loop_off.setData("Off")
        self.loop_off.triggered.connect(lambda: self.loop_mode_changed.emit("Off"))
        loop_group.addAction(self.loop_off)
        
        self.loop_one = loop_menu.addAction("单曲循环")
        self.loop_one.setCheckable(True)
        self.loop_one.setData("One")
        self.loop_one.triggered.connect(lambda: self.loop_mode_changed.emit("One"))
        loop_group.addAction(self.loop_one)
        
        self.loop_all = loop_menu.addAction("列表循环")
        self.loop_all.setCheckable(True)
        self.loop_all.setData("All")
        self.loop_all.triggered.connect(lambda: self.loop_mode_changed.emit("All"))
        loop_group.addAction(self.loop_all)
        
        self.loop_shuffle = loop_menu.addAction("随机播放")
        self.loop_shuffle.setCheckable(True)
        self.loop_shuffle.setData("Shuffle")
        self.loop_shuffle.triggered.connect(lambda: self.loop_mode_changed.emit("Shuffle"))
        loop_group.addAction(self.loop_shuffle)
        
        self.loop_off.setChecked(True) # Default
        
        # Speed
        speed_menu = self.addMenu("速度 (Speed)")
        speeds = [0.5, 1.0, 1.5, 2.0]
        for s in speeds:
            speed_menu.addAction(f"{s}x").triggered.connect(lambda checked, x=s: self.speed_changed.emit(x))
            
        self.addSeparator()
        
        # --- Video ---
        video_menu = self.addMenu("视频 (Video)")
        
        # Aspect Ratio
        ar_menu = video_menu.addMenu("宽高比 (Aspect Ratio)")
        ar_group = QActionGroup(self)
        
        for ar in ["Original", "16:9", "4:3", "Fill"]:
            act = ar_menu.addAction(ar)
            act.setCheckable(True)
            act.setData(ar)
            act.triggered.connect(lambda checked, x=ar: self.aspect_ratio_changed.emit(x))
            ar_group.addAction(act)
            if ar == "Original": act.setChecked(True)
            
        # Rotate
        rot_menu = video_menu.addMenu("旋转 (Rotate)")
        rot_group = QActionGroup(self)
        for deg in [0, 90, 180, 270]:
            act = rot_menu.addAction(f"{deg}°")
            act.setCheckable(True)
            act.setData(deg)
            act.triggered.connect(lambda checked, x=deg: self.rotate_changed.emit(x))
            rot_group.addAction(act)
            if deg == 0: act.setChecked(True)
            
        self.addSeparator()
        
        # --- Window ---
        window_menu = self.addMenu("窗口 (Window)")
        
        self.act_top = window_menu.addAction("置顶显示 (Always on Top)")
        self.act_top.setCheckable(True)
        self.act_top.toggled.connect(self.always_on_top_toggled.emit)
        
        self.act_frameless = window_menu.addAction("无边框模式 (Frameless)")
        self.act_frameless.setCheckable(True)
        self.act_frameless.toggled.connect(self.frameless_toggled.emit)
        
        window_menu.addSeparator()
        window_menu.addAction("新窗口 (New Window)").triggered.connect(self.new_window_requested.emit)
        
        # --- Bookmarks ---
        self.bookmarks_menu = self.addMenu("书签 (Bookmarks)")
        # This will be populated dynamically by MainWindow
        
        self.addSeparator()
        self.addAction("关于 (About)...") # Connect manually if needed

    def update_states(self, loop_mode, aspect_ratio, always_on_top, frameless):
        """Update check states based on current app state."""
        # Loop
        for act in self.findChildren(QAction):
            if act.data() == loop_mode:
                act.setChecked(True)
            if act.data() == aspect_ratio:
                act.setChecked(True)
                
        self.act_top.setChecked(always_on_top)
        self.act_frameless.setChecked(frameless)
