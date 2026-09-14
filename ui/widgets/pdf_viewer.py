"""
PDF Viewer widget for viewing PDF documents.
Requires PyMuPDF (fitz) for PDF rendering.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QLabel, QFrame, QSpinBox, QSlider,
    QMessageBox, QComboBox, QMenu, QApplication,
    QInputDialog
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QRect, QUrl, QTimer

from PyQt6.QtGui import (
    QImage, QPixmap, QPainter, QPen, QBrush, QColor, 
    QDesktopServices, QCursor
)

from ui.password_dialog import PasswordDialog
from core.evf_format import is_evf_file
from core.stream_decoder import StreamDecoder
from core.crypto_engine import StreamingDecryptor
import tempfile
import os


try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False



class PDFPageLabel(QLabel):
    """Interactive label for PDF pages."""
    
    # Signals
    link_clicked = pyqtSignal(str)
    content_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        
        self.pdf_page = None  # fitz.Page
        self.zoom_level = 1.0
        self.matrix = None    # fitz.Matrix
        
        # Selection
        self.start_pos = None
        self.current_pos = None
        self.selection_rect = None # QRect
        
        # Modes
        self.editing_mode = False
        
    def set_page(self, page, zoom):
        """Set current page and zoom."""
        self.pdf_page = page
        self.zoom_level = zoom
        self.matrix = fitz.Matrix(zoom * 2, zoom * 2) # 2x for display quality
        self.start_pos = None
        self.current_pos = None
        self.selection_rect = None
        self.update()

    def set_editing_mode(self, enabled: bool):
        self.editing_mode = enabled
        if enabled:
            self.setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Check links first (only if provided and NOT in edit mode?)
            # Actually if editing, we probably don't want to follow links, we want to select text over link.
            if not self.editing_mode and self._check_link(event.pos()):
                return
            
            # Start selection
            self.start_pos = event.pos()
            self.current_pos = event.pos()
            self.selection_rect = None
            self.update()
            
    def mouseMoveEvent(self, event):
        # Update cursor for links
        if not self.start_pos: # Hovering
            if not self.editing_mode and self._is_over_link(event.pos()):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                 if self.editing_mode:
                     self.setCursor(Qt.CursorShape.IBeamCursor)
                 else:
                     self.setCursor(Qt.CursorShape.CrossCursor) # Default for selection
            return

        # Dragging selection
        self.current_pos = event.pos()
        self.selection_rect = QRect(self.start_pos, self.current_pos).normalized()
        self.update()
        
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.start_pos:
            
            # If in Edit Mode, trigger Edit Dialog immediately on release
            if self.editing_mode and self.selection_rect and self.selection_rect.width() > 5:
                self._handle_text_edit()
                self.start_pos = None
                return

            # Show context menu if selection exists (View Mode)
            if self.selection_rect and self.selection_rect.width() > 5 and self.selection_rect.height() > 5:
                self._show_context_menu(event.globalPosition().toPoint())
            
            self.start_pos = None
            # Keep selection visible until next click? Or clear?
            # Let's keep it until clicked elsewhere usually.
            # But simpler logic: clear on next press.

    def paintEvent(self, event):
        super().paintEvent(event)
        
        # Draw Selection
        if self.selection_rect:
            painter = QPainter(self)
            color = QColor(255, 0, 0, 80) if self.editing_mode else QColor(0, 120, 215, 80)
            painter.setPen(QPen(color, 1))
            painter.setBrush(QBrush(color)) # Semi-transparent fill
            painter.drawRect(self.selection_rect)
            
    def _is_over_link(self, pos) -> bool:
        if not self.pdf_page or not self.matrix: return False
        
        # Map label pos back to PDF coordinates
        # The matrix scales PDF point to Label point (Pixmap point)
        # So we need inverse transformation
        inv_matrix = ~self.matrix
        pdf_point = fitz.Point(pos.x(), pos.y()) * inv_matrix
        
        # Check links on page
        # load_links() returns list of dictionaries
        for link in self.pdf_page.get_links():
            # 'from': rect
            if fitz.Rect(link['from']).contains(pdf_point):
                return True
                
        return False

    def _check_link(self, pos) -> bool:
        if not self.pdf_page or not self.matrix: return False
        
        inv_matrix = ~self.matrix
        pdf_point = fitz.Point(pos.x(), pos.y()) * inv_matrix
        
        for link in self.pdf_page.get_links():
            if fitz.Rect(link['from']).contains(pdf_point):
                if 'uri' in link:
                    # External URL
                    QDesktopServices.openUrl(QUrl(link['uri']))
                    return True
                elif 'page' in link:
                    # Internal Jump - Emit signal or handle?
                    # We need access to parent viewer to change page
                    # For now just print or ignore
                    # Or emit signal
                    # self.link_clicked.emit(str(link['page'])) # need logic
                    pass
        return False

    def _get_pdf_rect(self, qrect: QRect) -> fitz.Rect:
        """Convert QRect selection to PDF coordinates."""
        if not self.matrix: return fitz.Rect()
        
        # Inverse transform
        inv = ~self.matrix
        
        x0, y0 = qrect.left(), qrect.top()
        x1, y1 = qrect.right(), qrect.bottom()
        
        p0 = fitz.Point(x0, y0) * inv
        p1 = fitz.Point(x1, y1) * inv
        
        return fitz.Rect(p0, p1)

    def _handle_text_edit(self):
        """Handle Redact & Replace workflow."""
        if not self.pdf_page or not self.selection_rect: return
        
        pdf_rect = self._get_pdf_rect(self.selection_rect)
        
        # 1. Extract existing text
        current_text = self.pdf_page.get_text("text", clip=pdf_rect).strip()
        
        # 2. Show Dialog
        new_text, ok = QInputDialog.getMultiLineText(
            self, "Edit Text", "Edit Content:", current_text
        )
        
        if ok: # User confirmed change (even if empty to delete)
            try:
                # 3. Redact (Erase)
                self.pdf_page.add_redact_annot(pdf_rect)
                self.pdf_page.apply_redactions()
                
                # 4. Insert New Text (if not empty)
                if new_text:
                    # Simple insertion. 
                    fontsize = max(8, min(72, pdf_rect.height * 0.8)) # Rough heuristic
                    
                    self.pdf_page.insert_textbox(
                        pdf_rect, 
                        new_text, 
                        fontsize=fontsize, 
                        fontname="helv", # Default font
                        color=(0, 0, 0)
                    )
                
                # 5. Trigger Re-render
                self.content_changed.emit()
                
            except Exception as e:
                QMessageBox.critical(self, "Edit Error", f"Failed to modify PDF: {e}")

    def _show_context_menu(self, global_pos):
        menu = QMenu(self)
        
        copy_text_act = menu.addAction("📄 Copy Text")
        copy_img_act = menu.addAction("🖼️ Copy Image")
        menu.addSeparator()
        highlight_act = menu.addAction("🖍️ Highlight")
        
        action = menu.exec(global_pos)
        
        if not self.pdf_page or not self.selection_rect: return
        
        pdf_rect = self._get_pdf_rect(self.selection_rect)
        
        if action == copy_text_act:
            text = self.pdf_page.get_text("text", clip=pdf_rect)
            QApplication.clipboard().setText(text)
            
        elif action == copy_img_act:
             # Get pixmap of selection
             pix = self.pdf_page.get_pixmap(clip=pdf_rect, matrix=fitz.Matrix(2, 2))
             # Convert to QImage/KB
             img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
             QApplication.clipboard().setImage(img)
             
        elif action == highlight_act:
            # Annotate
            self.pdf_page.add_highlight_annot(pdf_rect)
            self.content_changed.emit()


class PDFViewer(QWidget):
    """PDF viewer with page navigation and zoom."""
    
    # Signal emitted when a PDF file path is loaded
    file_loaded = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pdf_doc = None
        self._current_page = 0
        self._total_pages = 0
        self._zoom_level = 1.0
        self._current_path = None
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Page display area with scroll
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #2d2d2d;
                border: none;
            }
        """)
        
        # Replace QLabel with Custom Interactive Label
        self.page_label = PDFPageLabel()
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setStyleSheet("background-color: transparent;")
        self.page_label.content_changed.connect(self._render_page)
        
        # Important: Need container widge to center label if resizable?
        # QScrollArea with AlignmentCenter handles it usually for QLabel.
        # But PDFPageLabel needs to resize to pixmap.
        
        self.scroll_area.setWidget(self.page_label)
        
        # Placeholder for when no PDF is loaded or PyMuPDF is missing
        self.placeholder = QLabel()
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if not HAS_PYMUPDF:
            self.placeholder.setText("⚠️ PDF viewing requires PyMuPDF\n\nInstall with: pip install pymupdf")
        else:
            self.placeholder.setText("📄 No PDF loaded")
        self.placeholder.setStyleSheet("""
            QLabel {
                color: #888888;
                font-size: 18px;
                background-color: #1a1a1a;
            }
        """)
        
        # Toolbar
        self.toolbar = QFrame()
        self.toolbar.setObjectName("controlBar")
        self.toolbar.setStyleSheet("""
            QFrame#controlBar {
                background-color: #252525;
                border-top: 1px solid #3a3a3a;
                padding: 8px;
            }
            QPushButton {
                background-color: #3a3a3a;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                color: #e0e0e0;
                min-width: 30px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #666666;
            }
            QPushButton:checked {
                 background-color: #e0e0e0;
                 color: #252525;
            }
            QLabel {
                color: #e0e0e0;
            }
            QSpinBox, QComboBox {
                background-color: #3a3a3a;
                border: 1px solid #4a4a4a;
                border-radius: 4px;
                padding: 4px;
                color: #e0e0e0;
            }
        """)
        
        toolbar_layout = QHBoxLayout(self.toolbar)
        toolbar_layout.setContentsMargins(10, 5, 10, 5)
        
        # Navigation buttons
        self.btn_first = QPushButton("⏮")
        self.btn_first.setToolTip("First Page")
        self.btn_first.clicked.connect(self._go_first)
        
        self.btn_prev = QPushButton("◀")
        self.btn_prev.setToolTip("Previous Page")
        self.btn_prev.clicked.connect(self._go_prev)
        
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.valueChanged.connect(self._on_page_spin)
        
        self.page_count_label = QLabel("/ 1")
        
        self.btn_next = QPushButton("▶")
        self.btn_next.setToolTip("Next Page")
        self.btn_next.clicked.connect(self._go_next)
        
        self.btn_last = QPushButton("⏭")
        self.btn_last.setToolTip("Last Page")
        self.btn_last.clicked.connect(self._go_last)
        
        # Zoom controls
        self.btn_zoom_out = QPushButton("−")
        self.btn_zoom_out.setToolTip("Zoom Out")
        self.btn_zoom_out.clicked.connect(lambda: self._set_zoom(self._zoom_level - 0.25))
        
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.addItems(["10%", "25%", "50%", "75%", "100%", "125%", "150%", "175%", "200%"])
        self.zoom_combo.setCurrentText("100%")
        self.zoom_combo.currentTextChanged.connect(self._on_zoom_combo) # Check if this signals on edit
        self.zoom_combo.lineEdit().returnPressed.connect(self._on_zoom_manual) # Handle manual entry

        
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setToolTip("Zoom In")
        self.btn_zoom_in.clicked.connect(lambda: self._set_zoom(self._zoom_level + 0.25))
        
        self.btn_fit_width = QPushButton("Fit Width")
        self.btn_fit_width.clicked.connect(self._fit_width)
        
        # Edit Toggle
        self.btn_edit = QPushButton("✏️ Edit")
        self.btn_edit.setCheckable(True)
        self.btn_edit.setToolTip("Enable Text Editing Mode")
        self.btn_edit.clicked.connect(self._toggle_edit_mode)
        
        self.btn_save = QPushButton("💾 Save")
        self.btn_save.setToolTip("Save Changes")
        self.btn_save.clicked.connect(self._save_changes)
        
        # Scroll Mode Toggle
        self.btn_scroll_mode = QPushButton("📜 Scroll Mode")
        self.btn_scroll_mode.setCheckable(True)
        self.btn_scroll_mode.setToolTip("Toggle Continuous Scroll")
        self.btn_scroll_mode.clicked.connect(self._toggle_scroll_mode)
        
        # Add widgets to toolbar
        toolbar_layout.addWidget(self.btn_first)
        toolbar_layout.addWidget(self.btn_prev)
        toolbar_layout.addWidget(self.page_spin)
        toolbar_layout.addWidget(self.page_count_label)
        toolbar_layout.addWidget(self.btn_next)
        toolbar_layout.addWidget(self.btn_last)
        toolbar_layout.addSpacing(20)
        toolbar_layout.addWidget(self.btn_zoom_out)
        toolbar_layout.addWidget(self.zoom_combo)
        toolbar_layout.addWidget(self.btn_zoom_in)
        toolbar_layout.addWidget(self.btn_fit_width)
        toolbar_layout.addSpacing(20)
        toolbar_layout.addWidget(self.btn_scroll_mode) # New
        toolbar_layout.addWidget(self.btn_edit) 
        toolbar_layout.addWidget(self.btn_save)
        toolbar_layout.addStretch()
        
        # Layout
        layout.addWidget(self.placeholder)
        layout.addWidget(self.scroll_area)
        layout.addWidget(self.toolbar)
        
        # Multi-page container (Lazy init)
        self.multipage_widget = QWidget()
        self.multipage_layout = QVBoxLayout(self.multipage_widget)
        self.multipage_layout.setSpacing(10)
        self.multipage_layout.setContentsMargins(10, 10, 10, 10)
        self.multipage_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        
        # Initial state
        self.scroll_area.hide()
        self.toolbar.hide()
        self._update_nav_buttons()
        
        # Scroll handling for lazy loading
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll)

    def _toggle_scroll_mode(self, checked: bool):
        """Toggle between single page and continuous scroll."""
        # Cleanly take current widget to prevent deletion
        if self.scroll_area.widget():
            self.scroll_area.takeWidget()
            
        if checked:
            # Switch to Continuous
            self.scroll_area.setWidget(self.multipage_widget)
            self.page_label.hide()
            self.multipage_widget.show()
            
            # Update Nav State (Enable all, logic handles mode)
            self.btn_first.setEnabled(True)
            self.btn_prev.setEnabled(True)
            self.btn_next.setEnabled(True)
            self.btn_last.setEnabled(True)
            self.page_spin.setEnabled(True)
            
            self._render_continuous()
            
            # Scroll to current page after layout
            QTimer.singleShot(200, lambda: self._scroll_to_page(self._current_page))
            
        else:
            # Switch to Single
            self.scroll_area.setWidget(self.page_label)
            self.multipage_widget.hide()
            self.page_label.show()
            
            # Enable nav
            self._update_nav_buttons()
            self.page_spin.setEnabled(True)
            
            self._render_page()

    def _scroll_to_page(self, page_index):
        """Scroll to specific page in continuous mode."""
        if not self.btn_scroll_mode.isChecked() or page_index >= self.multipage_layout.count():
            return
            
        item = self.multipage_layout.itemAt(page_index)
        if item and item.widget():
            # Scroll to widget
            self.scroll_area.ensureWidgetVisible(item.widget(), 0, 0)
            # Or verticalScrollBar().setValue(item.widget().y())

    def _update_nav_buttons(self):
        """Update navigation button states."""
        at_first = self._current_page == 0
        at_last = self._total_pages > 0 and self._current_page >= self._total_pages - 1
        
        self.btn_first.setEnabled(not at_first)
        self.btn_prev.setEnabled(not at_first)
        self.btn_next.setEnabled(not at_last)
        self.btn_last.setEnabled(not at_last)
    
    # Navigation methods
    def _go_first(self):
        self._current_page = 0
        self.page_spin.setValue(1)
        if self.btn_scroll_mode.isChecked():
            self._scroll_to_page(0)
            self._update_nav_buttons()
        else:
            self._render_page()
            self._update_nav_buttons()
    
    def _go_prev(self):
        if self._current_page > 0:
            self._current_page -= 1
            self.page_spin.setValue(self._current_page + 1)
            
            if self.btn_scroll_mode.isChecked():
                self._scroll_to_page(self._current_page)
            else:
                self._render_page()
            self._update_nav_buttons()
    
    def _go_next(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self.page_spin.setValue(self._current_page + 1)
            
            if self.btn_scroll_mode.isChecked():
                self._scroll_to_page(self._current_page)
            else:
                self._render_page()
            self._update_nav_buttons()
    
    def _go_last(self):
        self._current_page = self._total_pages - 1
        self.page_spin.setValue(self._total_pages)
        
        if self.btn_scroll_mode.isChecked():
            self._scroll_to_page(self._current_page)
        else:
            self._render_page()
        self._update_nav_buttons()

    def _on_page_spin(self, value):

        """Handle page spinbox change."""
        if value - 1 == self._current_page: return
        
        self._current_page = value - 1
        
        if self.btn_scroll_mode.isChecked():
            self._scroll_to_page(self._current_page)
            # Nav buttons always enabled in scroll mode, but update consistency?
            # _update_nav_buttons checks begin/end.
            self._update_nav_buttons()
        else:
             self._render_page()
             self._update_nav_buttons()
    
    # Zoom methods
    def _set_zoom(self, zoom: float):
        self._zoom_level = max(0.1, min(5.0, zoom))
        
        # Don't overwrite text if user is typing?
        current_text = self.zoom_combo.currentText()
        new_text = f"{int(self._zoom_level * 100)}%"
        if current_text != new_text:
             self.zoom_combo.blockSignals(True)
             self.zoom_combo.setCurrentText(new_text)
             self.zoom_combo.blockSignals(False)
        
        if self.btn_scroll_mode.isChecked():
            # Re-layout continuous
            self._render_continuous()
        else:
            self._render_page()

    def _render_page(self):
        """Render current page."""
        if not self._pdf_doc or self._current_page >= self._total_pages:
            return
        
        try:
            page = self._pdf_doc[self._current_page]
            
            # Calculate zoom matrix
            zoom_matrix = fitz.Matrix(self._zoom_level * 2, self._zoom_level * 2)  # 2x for better quality
            
            # Render to pixmap
            pix = page.get_pixmap(matrix=zoom_matrix)
            
            # Convert to QImage
            # Check alpha channel - valid PDF pages might not have alpha
            fmt = QImage.Format.Format_RGB888 if pix.n == 3 else QImage.Format.Format_RGBA8888
            
            img = QImage(
                pix.samples,
                pix.width,
                pix.height,
                pix.stride,
                fmt
            )
            
            # Set pixmap to label
            pixmap = QPixmap.fromImage(img)
            
            self.page_label.setPixmap(pixmap)
            self.page_label.resize(pixmap.size())
            
            # Pass page object for interaction
            self.page_label.set_page(page, self._zoom_level)
            
        except Exception as e:
            print(f"Error rendering page: {e}")

    def _render_continuous(self):

        """Render all pages in continuous layout."""
        if not self._pdf_doc: return
        
        # Clear existing
        while self.multipage_layout.count():
            item = self.multipage_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        # Populate with placeholders (Lazy)
        for i in range(self._total_pages):
            page = self._pdf_doc[i]
            rect = page.rect
            width = rect.width * self._zoom_level
            height = rect.height * self._zoom_level
            
            lbl = PDFPageLabel() 
            lbl.setFixedSize(int(width), int(height))
            lbl.setStyleSheet("background-color: white; border: 1px solid #ccc;")
            lbl.page_index = i 
            
            self.multipage_layout.addWidget(lbl)
            
        # Trigger lazy load
        QTimer.singleShot(100, self._on_scroll)

    def _on_scroll(self):
        """Handle scroll event for lazy loading."""
        if not self.btn_scroll_mode.isChecked(): return
        
        scroll_y = self.scroll_area.verticalScrollBar().value()
        viewport_h = self.scroll_area.viewport().height()
        center_y = scroll_y + (viewport_h / 2)
        
        processed_center = False
        
        for i in range(self.multipage_layout.count()):
            item = self.multipage_layout.itemAt(i)
            widget = item.widget()
            if not widget: continue
            
            y = widget.y()
            h = widget.height()
            
            # Check overlap logic
            # Load if visible
            if (y + h > scroll_y - 800) and (y < scroll_y + viewport_h + 800):
                if not getattr(widget, 'loaded', False):
                    self._load_page_content(widget, i)
            else:
                 # Unload if hidden
                 if getattr(widget, 'loaded', False):
                     widget.clear()
                     widget.setText(f"Page {i+1}")
                     widget.loaded = False
            
            # Update current page based on center
            if not processed_center:
                if y <= center_y <= y + h:
                    self._update_current_page_no_scroll(i)
                    processed_center = True

    def _update_current_page_no_scroll(self, index):
        """Update internal page index without triggering render."""
        if self._current_page != index:
            self._current_page = index
            self.page_spin.blockSignals(True)
            self.page_spin.setValue(index + 1)
            self.page_spin.blockSignals(False)
            self.page_count_label.setText(f"/ {self._total_pages}")


    def _load_page_content(self, lbl: PDFPageLabel, index: int):
        """Render content for a single page label."""
        try:
            page = self._pdf_doc[index]
            zoom_matrix = fitz.Matrix(self._zoom_level * 2, self._zoom_level * 2)
            pix = page.get_pixmap(matrix=zoom_matrix)
            
            fmt = QImage.Format.Format_RGB888 if pix.n == 3 else QImage.Format.Format_RGBA8888
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
            pixmap = QPixmap.fromImage(img)
            
            # Display at 50% scale (since render 2x)? 
            # Logic in _render_page was: setPixmap(pixmap), resize(pixmap.size()).
            # But here `lbl` has fixed size based on zoom level.
            # If we render 2x, pixmap is 2x size. 
            # We should setScaledContents(True)?
            # Or render at exact 1x zoom?
            # Standard: Render match display size.
            
            # In _render_continuous loop we setFixedSize(width, height) using self._zoom_level.
            # So lets render at self._zoom_level * 2 for quality, then scale down?
            # QPixmap.scaled? Expensive.
            # Better: Render at exact size needed?
            # HighDPI: Render at Device Pixel Ratio.
            # Let's just render at 2x and setScaledContents(True).
            
            lbl.setScaledContents(True)
            lbl.setPixmap(pixmap)
            lbl.set_page(page, self._zoom_level) # Enable interaction
            lbl.loaded = True
            
        except Exception as e:
            print(f"Lazy render error p{index}: {e}")

    # Override Zoom to handle both modes
    def _set_zoom(self, zoom: float):
        self._zoom_level = max(0.1, min(5.0, zoom))
        
        # Don't overwrite text if user is typing?
        current_text = self.zoom_combo.currentText()
        new_text = f"{int(self._zoom_level * 100)}%"
        if current_text != new_text:
             self.zoom_combo.blockSignals(True)
             self.zoom_combo.setCurrentText(new_text)
             self.zoom_combo.blockSignals(False)
        
        if self.btn_scroll_mode.isChecked():
            # Re-layout continuous
            self._render_continuous()
        else:
            self._render_page()

    def _on_zoom_combo(self, text):
        """Handle zoom combo change."""
        try:
            # Clean text
            clean_text = text.replace('%', '').strip()
            zoom = float(clean_text) / 100.0
            self._set_zoom(zoom)
        except ValueError:
            pass
            
    def _on_zoom_manual(self):
        """Handle manual zoom entry."""
        self._on_zoom_combo(self.zoom_combo.currentText())

    def _fit_width(self):
        """Fit zoom to page width."""
        if not self._pdf_doc: return
        try:
            # Use current page or first page
            page = self._pdf_doc[self._current_page]
            # Get viewport width
            # Note: scrollbar might take space, subtract a safe margin
            view_width = self.scroll_area.viewport().width() - 25
            if view_width <= 0: return
            
            zoom = view_width / page.rect.width
            self._set_zoom(zoom)
        except Exception:
            pass

    def _toggle_edit_mode(self, checked: bool):
        """Toggle text editing mode."""
        self.page_label.set_editing_mode(checked)
        if checked:
            self.btn_edit.setText("🛑 Stop Editing")
            self.btn_edit.setChecked(True)
        else:
            self.btn_edit.setText("✏️ Edit")
            self.btn_edit.setChecked(False)

    def _save_changes(self):
        """Save PDF changes."""
        if not self._pdf_doc or not self._current_path: return
        
        try:
            if self._pdf_doc.can_save_incrementally():
                 self._pdf_doc.save(self._current_path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
            else:
                 self._pdf_doc.save(self._current_path, encryption=fitz.PDF_ENCRYPT_KEEP)
                 
            QMessageBox.information(self, "Saved", "PDF saved successfully.")
            
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save: {e}")

    # Class-level cache for last successful password
    _last_password = None

    def load_file(self, path: str):
        """Load a PDF file (handling encryption)."""
        self.close_pdf()
        self._current_path = path

        if not HAS_PYMUPDF:
             self.placeholder.setText("⚠️ PyMuPDF not installed")
             self.placeholder.show()
             return

        try:
            # Check if encrypted (EVF)
            if is_evf_file(path):
                password = None
                ok = False
                
                # Try cached password first if available
                if PDFViewer._last_password:
                    try:
                         # Attempt silent open with cached password
                         self._try_load_encrypted(path, PDFViewer._last_password)
                         return # Success!
                    except Exception:
                        # Failed, prompt user
                        pass
                
                # Prompt loop? Or just simple prompt.
                # If cached failed, we prompt.
                while True:
                    password, ok = PasswordDialog.get_password_dialog(self, "Unlock PDF", "Enter password for encrypted PDF:")
                    if not ok:
                        self.placeholder.setText("Password required")
                        self.placeholder.show()
                        return
                    
                    try:
                        self._try_load_encrypted(path, password)
                        # Success - Cache it
                        PDFViewer._last_password = password
                        return
                    except Exception as e:
                        QMessageBox.warning(self, "Error", f"Failed to decrypt: {e}\nPlease try again.")
                        # Loop to try again
            
            else:
                # Normal PDF
                self._pdf_doc = fitz.open(path)
                self._post_load_setup(path)
                
        except Exception as e:
            print(f"PDF Load Error: {e}")
            self.placeholder.setText(f"Error loading PDF:\n{e}")
            self.placeholder.show()

    def _try_load_encrypted(self, path, password):
        """Helper to attempt decryption and loading."""
        # Decrypt to temp
        temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        temp_path = temp_file.name
        temp_file.close() # Close to allow write
        
        decryptor = StreamingDecryptor()
        try:
            decryptor.open(path, password)
            with open(temp_path, 'wb') as f:
                for chunk in decryptor.stream_all():
                    f.write(chunk)
        except Exception as e:
            # Cleanup on fail
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            decryptor.close()
            raise e # Propagate error
            
        decryptor.close()
        
        # Open with fitz
        try:
            self._pdf_doc = fitz.open(temp_path)
            self._temp_path = temp_path # Store for cleanup
            self._post_load_setup(path)
        except Exception as e:
             if os.path.exists(temp_path):
                os.unlink(temp_path)
             raise e

    def _post_load_setup(self, path):
        """Common setup after _pdf_doc is ready."""
        self._total_pages = self._pdf_doc.page_count
        self._current_page = 0
        self._total_pages = max(1, self._total_pages)
        
        # UI
        self.page_count_label.setText(f"/ {self._total_pages}")
        self.page_spin.blockSignals(True)
        self.page_spin.setMaximum(self._total_pages)
        self.page_spin.setValue(1)
        self.page_spin.blockSignals(False)
        
        self.placeholder.hide()
        self.scroll_area.show()
        self.toolbar.show()
        self._update_nav_buttons()
        
        # Render
        if self.btn_scroll_mode.isChecked():
            self._render_continuous()
        else:
            self._render_page()
            
        self.file_loaded.emit(path)

    def close_pdf(self):
        """Close current PDF."""
        if self._pdf_doc:
            self._pdf_doc.close()
            self._pdf_doc = None
            
        # Clean up temp file
        if hasattr(self, '_temp_path') and self._temp_path:
            if os.path.exists(self._temp_path):
                try:
                    os.unlink(self._temp_path)
                except Exception: pass
            self._temp_path = None
            
        self.page_label.clear()
        self.placeholder.show()
        self.scroll_area.hide()
        self.toolbar.hide()

    def closeEvent(self, event):
        """Handle widget close."""
        self.close_pdf()
        super().closeEvent(event)
