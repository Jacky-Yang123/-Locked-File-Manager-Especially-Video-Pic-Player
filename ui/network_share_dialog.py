"""
Network Share Dialog - PyQt6 window for configuring and managing the LAN file sharing server.
Features: folder selection, port config, start/stop, QR code display.
"""

import socket
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QFrame, QSpinBox, QMessageBox,
    QApplication, QListWidget, QListWidgetItem, QMenu, QInputDialog,
    QCheckBox
)
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
import json
import os
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPainter, QColor, QPixmap, QFont, QImage
from core.key_derivation import derive_key, verify_password

from core.network_share_server import NetworkShareServer


class NetworkShareDialog(QDialog):
    """Dialog for configuring and controlling the network share server."""

    def __init__(self, parent=None, default_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("📡 网络共享")
        self.setMinimumSize(460, 450) # Reduced height
        self.setMaximumSize(600, 600)
        self.setStyleSheet(self._get_stylesheet())

        self._server = NetworkShareServer()
        self._default_path = default_path
        self._config_file = os.path.join(os.getcwd(), "share_configs.json")
        
        self.configs = self._load_configs()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Title
        title = QLabel("📡 局域网文件共享")
        title.setObjectName("dialogTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Description
        desc = QLabel("将文件夹共享到局域网，手机扫码即可访问和播放文件")
        desc.setObjectName("dialogDesc")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Separator
        layout.addWidget(self._create_separator())

        # Path Selection
        path_label = QLabel("共享文件夹路径")
        path_label.setObjectName("fieldLabel")
        layout.addWidget(path_label)

        path_row = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("选择要共享的文件夹...")
        self.path_input.setText(self._default_path)
        self.path_input.setReadOnly(True)
        path_row.addWidget(self.path_input, 1)

        browse_btn = QPushButton("📂 浏览")
        browse_btn.setObjectName("browseBtn")
        browse_btn.clicked.connect(self._browse_folder)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        # Port
        port_row = QHBoxLayout()
        port_label = QLabel("端口号")
        port_label.setObjectName("fieldLabel")
        port_row.addWidget(port_label)
        port_row.addStretch()

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(8080)
        self.port_spin.setFixedWidth(100)
        port_row.addWidget(self.port_spin)
        layout.addLayout(port_row)

        # Password
        pass_row = QHBoxLayout()
        pass_label = QLabel("共享密码")
        pass_label.setObjectName("fieldLabel")
        pass_row.addWidget(pass_label)
        
        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("WebDAV 连接与解密密码")
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        # Toggle-password visibility (eye) action for usability on VR/phone input
        self._pwd_visible = False
        eye_action = self._make_eye_action()
        self.pass_input.addAction(eye_action, QLineEdit.ActionPosition.TrailingPosition)
        eye_action.setToolTip("显示/隐藏密码")
        eye_action.triggered.connect(self._toggle_pwd_visibility)
        pass_row.addWidget(self.pass_input)
        layout.addLayout(pass_row)

        # HTTPS Encryption
        https_row = QHBoxLayout()
        https_label = QLabel("加密传输 (HTTPS)")
        https_label.setObjectName("fieldLabel")
        https_label.setToolTip("使用 TLS 加密局域网传输，防止路由器/他人抓包看到视频内容与密码")
        https_row.addWidget(https_label)
        https_row.addStretch()

        self.https_check = QCheckBox("✅ 已启用")
        self.https_check.setChecked(True)
        self.https_check.setToolTip("加密后访问地址为 https://ip:port。\n若播放器不支持自签名证书可取消勾选（不推荐）")
        https_row.addWidget(self.https_check)
        layout.addLayout(https_row)

        # Saved Configs Section
        config_frame = QFrame()
        config_frame.setObjectName("configFrame")
        config_layout = QVBoxLayout(config_frame)
        config_layout.setContentsMargins(0, 0, 0, 0)
        
        # Saved Configs Section
        config_frame = QFrame()
        config_frame.setObjectName("configFrame")
        config_layout = QVBoxLayout(config_frame)
        config_layout.setContentsMargins(0, 0, 0, 0)
        
        config_header = QHBoxLayout()
        self.config_section_label = QLabel("💾 保存的配置")
        config_header.addWidget(self.config_section_label)
        
        self.save_cfg_btn = QPushButton("保存当前配置")
        self.save_cfg_btn.setObjectName("actionBtn")
        self.save_cfg_btn.clicked.connect(self._save_current_config)
        config_header.addWidget(self.save_cfg_btn)
        
        self.del_cfg_btn = QPushButton("🗑️ 删除")
        self.del_cfg_btn.setObjectName("actionBtn")
        self.del_cfg_btn.clicked.connect(self._delete_selected_config)
        config_header.addWidget(self.del_cfg_btn)
        
        config_layout.addLayout(config_header)

        self.config_list = QListWidget()
        self.config_list.setFixedHeight(100)
        self.config_list.itemClicked.connect(self._load_selected_config)
        self.config_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.config_list.customContextMenuRequested.connect(self._show_config_context_menu)
        self._update_config_list()
        
        config_layout.addWidget(self.config_list)
        
        layout.addWidget(config_frame)
        layout.addWidget(self._create_separator())

        # Start/Stop Button
        self.toggle_btn = QPushButton("🚀 启动共享")
        self.toggle_btn.setObjectName("toggleBtn")
        self.toggle_btn.setFixedHeight(48)
        self.toggle_btn.clicked.connect(self._toggle_server)
        layout.addWidget(self.toggle_btn)

        # Status Section
        self.status_frame = QFrame()
        self.status_frame.setObjectName("statusFrame")
        self.status_frame.setVisible(False)
        status_layout = QVBoxLayout(self.status_frame)
        status_layout.setSpacing(12)

        self.status_label = QLabel("● 服务未启动")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(self.status_label)

        # URL Display
        self.url_label = QLabel("")
        self.url_label.setObjectName("urlLabel")
        self.url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        status_layout.addWidget(self.url_label)

        # Status Buttons Row
        status_btns = QHBoxLayout()
        
        # Copy URL Button
        self.copy_btn = QPushButton("📋 复制链接")
        self.copy_btn.setObjectName("copyBtn")
        self.copy_btn.clicked.connect(self._copy_url)
        self.copy_btn.setVisible(False)
        status_btns.addWidget(self.copy_btn)
        
        # Open Browser Button
        self.open_url_btn = QPushButton("🌐 打开浏览器")
        self.open_url_btn.setObjectName("copyBtn") # Reuse style
        self.open_url_btn.clicked.connect(self._open_browser)
        self.open_url_btn.setVisible(False)
        status_btns.addWidget(self.open_url_btn)
        
        status_layout.addLayout(status_btns)



        layout.addWidget(self.status_frame)
        layout.addStretch()

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "选择要共享的文件夹",
            self.path_input.text() or str(Path.home())
        )
        if folder:
            self.path_input.setText(folder)

    def _make_eye_action(self) -> "QAction":
        """Build a QAction with a painted eye icon (avoids emoji/encoding issues)."""
        from PyQt6.QtGui import QAction, QIcon, QPen

        # Paint a simple eye: ellipse outline + pupil dot
        pix = QPixmap(18, 18)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(180, 190, 200), 1.4)
        p.setPen(pen)
        p.setBrush(QColor(0, 0, 0, 0))
        p.drawEllipse(2, 6, 14, 7)          # almond shape
        p.setBrush(QColor(180, 190, 200))
        p.drawEllipse(8, 8, 3, 3)           # pupil
        p.end()
        action = QAction(QIcon(pix), "", self)
        return action

    def _toggle_pwd_visibility(self):
        self._pwd_visible = not self._pwd_visible
        self.pass_input.setEchoMode(
            QLineEdit.EchoMode.Normal if self._pwd_visible else QLineEdit.EchoMode.Password
        )

    def _toggle_server(self):
        if self._server.is_running:
            self._stop_server()
        else:
            self._start_server()

    def _start_server(self):
        path = self.path_input.text()
        if not path or not Path(path).is_dir():
            QMessageBox.warning(self, "错误", "请选择一个有效的文件夹路径")
            return

        port = self.port_spin.value()
        password = self.pass_input.text().strip()
        
        if not password:
            QMessageBox.warning(self, "错误", "请设置共享密码 (用于 WebDAV 连接认证与文件解密)")
            return

        try:
            url = self._server.start(path, port, password, use_https=self.https_check.isChecked())
        except Exception as e:
            QMessageBox.critical(self, "启动失败", f"无法启动服务器:\n{str(e)}")
            return

        # Update UI
        self.toggle_btn.setText("⏹ 停止共享")
        self.toggle_btn.setObjectName("toggleBtnActive")
        self.toggle_btn.setStyleSheet(self.toggle_btn.styleSheet())  # Refresh style
        self.path_input.setEnabled(False)
        self.port_spin.setEnabled(False)
        self.https_check.setEnabled(False)

        self.status_frame.setVisible(True)
        self.status_label.setText("● 服务运行中")
        self.status_label.setStyleSheet("color: #3fb950; font-weight: bold; font-size: 15px;")
        self.url_label.setText(f"<b style='font-size:18px; color:#58a6ff;'>{url}</b>"
                               f"<br><span style='color:#8b949e; font-size:12px;'>手机/VR 播放器输入上方地址（HTTPS 加密传输）</span>")
        self.copy_btn.setVisible(True)
        self.open_url_btn.setVisible(True)
        self.status_label.setStyleSheet("color: #3fb950; font-weight: bold; font-size: 15px;")
        self.url_label.setText(f"<b style='font-size:18px; color:#58a6ff;'>{url}</b>"
                               f"<br><span style='color:#8b949e; font-size:12px;'>手机/VR 播放器输入上方地址</span>")
        self.copy_btn.setVisible(True)
        self.open_url_btn.setVisible(True)

        # Force style refresh
        self.setStyleSheet(self._get_stylesheet())

    def _stop_server(self):
        self._server.stop()

        self.toggle_btn.setText("🚀 启动共享")
        self.toggle_btn.setObjectName("toggleBtn")
        self.path_input.setEnabled(True)
        self.port_spin.setEnabled(True)
        self.https_check.setEnabled(True)

        self.status_frame.setVisible(False)
        self.status_label.setText("● 服务未启动")
        self.status_label.setStyleSheet("")
        self.url_label.setText("")
        self.copy_btn.setVisible(False)
        self.open_url_btn.setVisible(False)
        self.status_label.setStyleSheet("")
        self.url_label.setText("")
        self.copy_btn.setVisible(False)
        self.open_url_btn.setVisible(False)

        self.setStyleSheet(self._get_stylesheet())

    def _copy_url(self):
        url = self._server.url
        if url:
            clipboard = QApplication.clipboard()
            clipboard.setText(url)
            self.copy_btn.setText("✅ 已复制!")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1500, lambda: self.copy_btn.setText("📋 复制链接"))

    def _open_browser(self):
        url = self._server.url
        if url:
             QDesktopServices.openUrl(QUrl(url))


    # --- Encryption & Persistence ---

    # --- Hashed Verification & Persistence ---

    def _load_configs(self) -> list:
        if not os.path.exists(self._config_file):
            return []
            
        try:
            with open(self._config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Config load error: {e}")
            return []

    def _save_configs(self):
        try:
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(self.configs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存配置失败: {e}")

    def _update_config_list(self):
        self.config_list.clear()
        for cfg in self.configs:
            legacy_path = cfg.get('path')
            if legacy_path:
                name = f"{os.path.basename(legacy_path)} (:{cfg.get('port')})"
                tooltip = f"路径: {legacy_path}\n端口: {cfg.get('port')}\n(密码已作为哈希值安全存储)"
            else:
                name = f"🔒 加密配置 (:{cfg.get('port')})"
                tooltip = f"端口: {cfg.get('port')}\n路径已加密存储，加载时输入密码解密"
            item = QListWidgetItem(name)
            item.setToolTip(tooltip)
            item.setData(Qt.ItemDataRole.UserRole, cfg)
            self.config_list.addItem(item)
            
    def _delete_selected_config(self):
        rows = self.config_list.selectedIndexes()
        if not rows:
            QMessageBox.information(self, "提示", "请先选择一个配置")
            return
            
        row = rows[0].row()
        confirm = QMessageBox.question(self, "确认删除", "确定要删除选中的配置吗？")
        if confirm == QMessageBox.StandardButton.Yes:
            self.configs.pop(row)
            self._save_configs()
            self._update_config_list()

    def _save_current_config(self):
        path = self.path_input.text()
        port = self.port_spin.value()
        pwd = self.pass_input.text()
        
        if not path or not pwd:
            QMessageBox.warning(self, "提示", "请先填写入径和密码")
            return
            
        # Hash the password
        # We need to generate a secure hash to verify against later.
        # We don't store the password itself.
        try:
            key, salt = derive_key(pwd)
            pwd_hash_hex = key.hex()
            pwd_salt_hex = salt.hex()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"密码处理失败: {e}")
            return

        # Encrypt the path with the machine key (no plaintext path on disk)
        try:
            from core.secrets_store import load_or_create_machine_key, encrypt_with_key
            key_path = os.path.join(os.path.dirname(os.path.abspath(self._config_file)), 'library.key')
            machine_key = load_or_create_machine_key(key_path)
            if not machine_key:
                QMessageBox.warning(self, "错误", "无法创建加密密钥，路径将不加密存储")
                entry = {"path": path, "port": port, "pwd_hash": pwd_hash_hex, "pwd_salt": pwd_salt_hex}
            else:
                enc_path = encrypt_with_key(machine_key, path)
                entry = {"enc_path": enc_path, "port": port, "pwd_hash": pwd_hash_hex, "pwd_salt": pwd_salt_hex}
        except Exception as e:
            QMessageBox.warning(self, "错误", f"路径加密失败: {e}")
            return
            
        # Check if exists (by path and port)
        # Verify if we should update? 
        # For simplicity, if path+port matches, we update.
        updated = False
        for i, cfg in enumerate(self.configs):
            old_path = cfg.get('path')  # legacy plaintext
            if old_path == path and cfg.get('port') == port:
                self.configs[i] = entry
                updated = True
                break
        
        if not updated:
            self.configs.append(entry)
            
        self._save_configs()
        self._update_config_list()
        QMessageBox.information(self, "成功", "配置已保存！\n路径已加密存储。\n注意：下次加载此配置时需要输入相同的密码进行验证。")

    def _load_selected_config(self, item):
        cfg = item.data(Qt.ItemDataRole.UserRole)
        
        # Check hash
        stored_hash = cfg.get('pwd_hash')
        stored_salt = cfg.get('pwd_salt')
        
        if not stored_hash or not stored_salt:
             # Legacy or broken?
             QMessageBox.warning(self, "错误", "配置数据不完整(缺少安全信息)")
             return

        # Legacy plaintext path or encrypted (new) path
        legacy_path = cfg.get('path')
        enc_path = cfg.get('enc_path')

        if not legacy_path and not enc_path:
            QMessageBox.warning(self, "错误", "配置缺少路径信息")
            return

        # Prompt for password
        display_hint = os.path.basename(legacy_path) if legacy_path else "加密配置"
        pwd, ok = QInputDialog.getText(
            self, "验证密码", 
            f"请输入为 '{display_hint}' (端口 {cfg.get('port')}) 设置的共享密码以加载:", 
            QLineEdit.EchoMode.Password
        )
        
        if not ok or not pwd:
            self.config_list.clearSelection() # Cancel selection
            return
            
        try:
            expected_key = bytes.fromhex(stored_hash)
            salt = bytes.fromhex(stored_salt)
            
            if verify_password(pwd, salt, expected_key):
                 # Resolve path: legacy plaintext, or decrypt the encrypted path (machine key)
                 resolved_path = legacy_path
                 if enc_path:
                     from core.secrets_store import decrypt_with_key, load_or_create_machine_key
                     key_path = os.path.join(os.path.dirname(os.path.abspath(self._config_file)), 'library.key')
                     machine_key = load_or_create_machine_key(key_path)
                     resolved_path = decrypt_with_key(machine_key, enc_path) if machine_key else None
                     if not resolved_path:
                         QMessageBox.warning(self, "错误", "路径解密失败（密钥或数据错误）")
                         self.config_list.clearSelection()
                         return
                 
                 self.path_input.setText(resolved_path)
                 self.port_spin.setValue(cfg.get('port', 8080))
                 self.pass_input.setText(pwd) # Fill the correct pwd
                 self.config_list.clearSelection() # Clear visual selection so user knows it's loaded
            else:
                 QMessageBox.warning(self, "错误", "密码错误！无法加载配置。")
                 self.config_list.clearSelection()
        except Exception as e:
             QMessageBox.warning(self, "错误", f"验证失败: {e}")
             self.config_list.clearSelection()

    def _show_config_context_menu(self, pos):
        item = self.config_list.itemAt(pos)
        if not item: return
        
        menu = QMenu()
        del_action = menu.addAction("删除配置")
        action = menu.exec(self.config_list.viewport().mapToGlobal(pos))
        
        if action == del_action:
            row = self.config_list.row(item)
            self.configs.pop(row)
            self._save_configs()
            self._update_config_list()

    def closeEvent(self, event):
        """Close window without stopping the server unless explicitly requested."""
        # Just close the window, don't stop the server.
        # This allows the user to close the control dialog while service remains active.
        super().closeEvent(event)

    @staticmethod
    def _create_separator() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #30363d; max-height: 1px;")
        return sep

    @staticmethod
    def _get_stylesheet() -> str:
        return """
            QDialog {
                background: #0d1117;
                color: #e6edf3;
            }
            #dialogTitle {
                font-size: 22px;
                font-weight: bold;
                color: #e6edf3;
            }
            #dialogDesc {
                font-size: 13px;
                color: #8b949e;
            }
            #fieldLabel {
                font-size: 13px;
                color: #8b949e;
                font-weight: 600;
            }
            QLineEdit {
                padding: 10px 14px;
                border: 1px solid #30363d;
                border-radius: 8px;
                background: #161b22;
                color: #e6edf3;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #58a6ff;
            }
            QSpinBox {
                padding: 8px 12px;
                border: 1px solid #30363d;
                border-radius: 8px;
                background: #161b22;
                color: #e6edf3;
                font-size: 14px;
            }
            #browseBtn {
                padding: 10px 18px;
                background: #21262d;
                border: 1px solid #30363d;
                border-radius: 8px;
                color: #e6edf3;
                font-weight: 600;
                font-size: 13px;
            }
            #browseBtn:hover {
                background: #30363d;
            }
            #toggleBtn, #toggleBtnActive {
                border: none;
                border-radius: 10px;
                font-size: 16px;
                font-weight: bold;
                color: #fff;
            }
            #toggleBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #238636, stop:1 #2ea043);
            }
            #toggleBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2ea043, stop:1 #3fb950);
            }
            #toggleBtnActive {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #b62324, stop:1 #da3633);
            }
            #toggleBtnActive:hover {
                background: #f85149;
            }
            #statusFrame {
                background: #161b22;
                border: 1px solid #30363d;
                border-radius: 10px;
                padding: 16px;
            }
            #copyBtn {
                padding: 8px 16px;
                background: #21262d;
                border: 1px solid #30363d;
                border-radius: 8px;
                color: #e6edf3;
                font-size: 13px;
            }
            #copyBtn:hover {
                background: #30363d;
            }
            #configFrame {
                background: #161b22;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 10px;
            }
            QListWidget {
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                color: #e6edf3;
            }
            #actionBtn {
                background: #21262d; border: 1px solid #30363d; border-radius: 6px; color: #e6edf3; padding: 4px 8px;
            }
        """



