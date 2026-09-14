"""
Image viewer widget with zoom and pan support.
"""

import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QScrollArea,
    QPushButton, QHBoxLayout, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap

from ui.password_dialog import PasswordDialog
from core.evf_format import is_evf_file
from core.stream_decoder import StreamDecoder
from PyQt6.QtCore import pyqtSignal

class ImageViewer(QWidget):
    """Image viewer with zoom and pan."""
    
    navigation_requested = pyqtSignal(str) # "next" or "prev"
    context_menu_requested = pyqtSignal(object) # point

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scale_factor = 1.0
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Toolbar
        self.toolbar = QFrame()
        self.toolbar.setObjectName("controlBar")
        toolbar_layout = QHBoxLayout(self.toolbar)
        
        self.btn_prev = QPushButton("⬅️ 上一张")
        self.btn_prev.clicked.connect(lambda: self.navigation_requested.emit("prev"))
        
        self.btn_next = QPushButton("下一张 ➡️")
        self.btn_next.clicked.connect(lambda: self.navigation_requested.emit("next"))
        
        self.btn_zoom_in = QPushButton("➕")
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        
        self.btn_zoom_out = QPushButton("➖")
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        
        self.btn_fit = QPushButton("适应窗口")
        self.btn_fit.clicked.connect(self.fit_to_window)
        
        self.label_info = QLabel("")
        
        # Add widgets
        toolbar_layout.addWidget(self.btn_prev)
        toolbar_layout.addWidget(self.btn_next)
        toolbar_layout.addWidget(self.btn_zoom_in)
        toolbar_layout.addWidget(self.btn_zoom_out)
        toolbar_layout.addWidget(self.btn_fit)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.label_info)
        
        # Scroll area for image
        self.scroll_area = QScrollArea()
        self.scroll_area.setBackgroundRole(QScrollArea.viewport(self.scroll_area).backgroundRole())
        self.scroll_area.setWidgetResizable(False) # Critical: Must be False for manual zoom (resize) to work
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setStyleSheet("background: #000000; border: none;")
        
        # Context Menu
        self.scroll_area.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.scroll_area.customContextMenuRequested.connect(self._on_context_menu)
        
        # HIDE SCROLLBARS as requested
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setScaledContents(True)
        
        self.scroll_area.setWidget(self.image_label)
        
        layout.addWidget(self.scroll_area)
        layout.addWidget(self.toolbar)

    def _on_context_menu(self, point):
        self.context_menu_requested.emit(point)
        
    def get_current_file(self):
        """Standard interface for generic handlers."""
        # Check both normal and encrypted open paths
        # We need to track current file path reliably
        if hasattr(self, '_current_path'):
            return self._current_path
        return None
    
    def open_file(self, file_path: str):
        """Open and display image file."""
        self._current_path = file_path # Track path
        if is_evf_file(file_path):
            self._open_encrypted(file_path)
        else:
            self._load_image_from_path(file_path)

    def _open_encrypted(self, file_path: str):
        """Open encrypted image."""
        password, ok = PasswordDialog.get_password_dialog(
            self,
            title="🔐 需要密码",
            message="此图片已加密，请输入密码解锁"
        )
        if not ok:
            return

    def _open_encrypted(self, file_path: str):
        """Open encrypted image with password cache."""
        
        # Try cached password first
        if hasattr(self, '_cached_password') and self._cached_password:
             try:
                 if self._try_decrypt(file_path, self._cached_password):
                     return
             except:
                 pass # Fallback to dialog
        
        # Ask user
        while True:
            password, ok = PasswordDialog.get_password_dialog(
                self,
                title="🔐 需要密码",
                message="此图片已加密，请输入密码解锁"
            )
            if not ok: return
            
            try:
                if self._try_decrypt(file_path, password):
                    self._cached_password = password # Cache success
                    return
            except Exception as e:
                # QMessageBox.warning(self, "Error", f"解密失败: {e}") 
                # Let _try_decrypt handle visual error or loop?
                # Usually dialog loop handles retry if we want, but PasswordDialog is simple.
                # Here we loop manually or just show error.
                QMessageBox.warning(self, "错误", "密码错误或文件损坏")
            
    def _try_decrypt(self, file_path, password):
        """Helper to attempt decryption."""
        from core.crypto_engine import StreamingDecryptor
        
        # Buffer to RAM
        data = bytearray()
        try:
            with StreamingDecryptor() as dec:
                dec.open(file_path, password)
                for chunk in dec.stream_all():
                    data.extend(chunk)
        except ValueError:
            return False # Wrong password
            
        # Load Image
        image = QImage()
        success = image.loadFromData(data)
        
        if success:
            self.image = image
            self.label_info.setText(f"{image.width()} x {image.height()} px (Encrypted)")
            self._scale_factor = 1.0
            self.show_image()
            self.fit_to_window()
            return True
        else:
            raise Exception("无法解码图片数据")

    def _load_image_from_path(self, path):
        """Internal load image."""
        self.image = QImage(path)
        if self.image.isNull():
            self.label_info.setText("Error loading image")
            return
        
        self._scale_factor = 1.0
        self.show_image()
        self.fit_to_window()
        
        size = self.image.size()
        self.label_info.setText(f"{size.width()} x {size.height()} px")
    
    
    def show_image(self):
        """Display the image with current scale."""
        if not hasattr(self, 'image') or self.image.isNull():
            return
            
        # Update pixmap always
        self.image_label.setPixmap(QPixmap.fromImage(self.image))
             
        # Calculate new size
        if self._scale_factor <= 0.05: self._scale_factor = 0.05
        
        original_size = self.image.size()
        new_width = int(original_size.width() * self._scale_factor)
        new_height = int(original_size.height() * self._scale_factor)
        
        # Resize Label
        self.image_label.resize(new_width, new_height)
        
        # Update Info
        percent = int(self._scale_factor * 100)
        self.label_info.setText(f"{original_size.width()}x{original_size.height()} ({percent}%)")

    def zoom_in(self):
        self.scale_image(1.25)
    
    def zoom_out(self):
        self.scale_image(0.8)
    
    def scale_image(self, factor):
        """Scale image."""
        self._scale_factor *= factor
        # Limit zoom
        if self._scale_factor < 0.05: self._scale_factor = 0.05
        if self._scale_factor > 20.0: self._scale_factor = 20.0
        
        self.show_image()
        
        # Adjust scrollbars to keep center logic?
        # Default Qt behavior might jump, but acceptable for now.


    def adjust_scrollbar(self, scrollbar, factor):
        scrollbar.setValue(int(factor * scrollbar.value() + ((factor - 1) * scrollbar.pageStep() / 2)))

    def fit_to_window(self):
        """Fit image to window."""
        if not hasattr(self, 'image') or self.image.isNull():
            return
            
        view_rect = self.scroll_area.viewport().rect()
        img_rect = self.image.rect()
        
        if img_rect.width() == 0 or img_rect.height() == 0:
            return
            
        width_ratio = view_rect.width() / img_rect.width()
        height_ratio = view_rect.height() / img_rect.height()
        
        # Determine scale to fit entire image
        self._scale_factor = min(width_ratio, height_ratio)
        
        # Don't upscale small images by default, unless user wants to? 
        # Usually fit-to-window implies shrinking large, but expanding small often desired too.
        # Let's simple fit.
        if self._scale_factor <= 0: self._scale_factor = 0.1
            
        self.show_image()
        self.label_info.setText("Fit to Window")
        
    # --- Event Handlers for Mouse ---
    
    def wheelEvent(self, event):
        """Handle mouse wheel for zoom."""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            # Control + Scroll for detailed zoom
            delta = event.angleDelta().y()
            if delta > 0:
                self.scale_image(1.1)
            else:
                self.scale_image(0.9)
        else:
            # Standard Scroll: Zoom or Pan?
            # Standard behavior is pan vertical. 
            # User requested zoom support. Let's map Wheel to Zoom if desired or Ctrl+Wheel.
            # Many image viewers use Wheel to Zoom directly.
            delta = event.angleDelta().y()
            if delta > 0:
                self.scale_image(1.25)
            else:
                self.scale_image(0.8)
            event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, '_last_mouse_pos'):
            # Pan logic
            delta = event.pos() - self._last_mouse_pos
            self._last_mouse_pos = event.pos()
            
            h_bar = self.scroll_area.horizontalScrollBar()
            v_bar = self.scroll_area.verticalScrollBar()
            
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
            
    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.CursorShape.ArrowCursor)

