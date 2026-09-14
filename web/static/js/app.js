/**
 * Main application logic.
 */
const App = {
    currentPath: '/',
    pathHistory: [],
    files: [],
    cachedPassword: null, // Keep strictly in-memory per session - never persist to disk/storage
    isFlatMode: false,
    filterType: 'all',
    sortBy: 'name',
    sortAsc: true,
    searchQuery: '',
    selectedFile: null,
    _toastTimer: null,

    init() {
        Auth.init();
        Player.init();
        Viewer.init();
        this._initStorageTypeToggle();

        // Check login state & auto-login
        if (API.isLoggedIn()) {
            const username = localStorage.getItem('username') || '用户';
            this.onLoginSuccess(username, true);
        } else {
            this.showPage('auth');
        }

        // Bottom nav
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', () => {
                const page = item.dataset.page;
                this.showPage(page);
                document.querySelectorAll('.nav-item').forEach(n => {
                    n.classList.toggle('active', n.dataset.page === page);
                });
            });
        });

        // Dedicated Flat Mode Toggle Button
        const flatBtn = document.getElementById('btn-flat-mode');
        if (flatBtn) {
            flatBtn.addEventListener('click', async () => {
                this.isFlatMode = !this.isFlatMode;
                flatBtn.classList.toggle('active', this.isFlatMode);
                flatBtn.textContent = this.isFlatMode ? '🌐 穿透中' : '🌐 穿透子目录';
                this.showToast(this.isFlatMode ? '🌐 开启穿透模式（扫描所有子文件夹）' : '📁 已返回文件夹模式');
                await this.loadFiles(this.currentPath);
            });
        }

        // Filter, Sort & Search controls
        const filterSelect = document.getElementById('filter-type');
        if (filterSelect) {
            filterSelect.addEventListener('change', (e) => {
                this.filterType = e.target.value;
                this.applyFilterAndRender();
            });
        }

        const sortSelect = document.getElementById('sort-by');
        if (sortSelect) {
            sortSelect.addEventListener('change', (e) => {
                this.sortBy = e.target.value;
                this.applyFilterAndRender();
            });
        }

        const sortOrderBtn = document.getElementById('btn-sort-order');
        if (sortOrderBtn) {
            sortOrderBtn.addEventListener('click', () => {
                this.sortAsc = !this.sortAsc;
                sortOrderBtn.textContent = this.sortAsc ? '⬇️' : '⬆️';
                this.applyFilterAndRender();
            });
        }

        const searchInput = document.getElementById('search-input');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.searchQuery = e.target.value.toLowerCase().trim();
                this.applyFilterAndRender();
            });
        }

        // Back button
        document.getElementById('btn-back').addEventListener('click', () => this.goBack());

        // Password button
        document.getElementById('btn-password').addEventListener('click', () => {
            this.showPasswordDialog();
        });

        // Password dialog
        document.getElementById('pwd-cancel').addEventListener('click', () => {
            document.getElementById('password-dialog').classList.add('hidden');
            if (this._pwdResolve) this._pwdResolve(null);
        });
        document.getElementById('pwd-confirm').addEventListener('click', () => {
            const pwd = document.getElementById('evf-password').value;
            document.getElementById('password-dialog').classList.add('hidden');
            if (this._pwdResolve) this._pwdResolve(pwd);
        });
        document.getElementById('evf-password').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                document.getElementById('pwd-confirm').click();
            }
        });

        // Settings
        document.getElementById('btn-test-webdav').addEventListener('click', () => this.testWebDAV());
        document.getElementById('btn-save-settings').addEventListener('click', () => this.saveSettings());
        document.getElementById('btn-save-account').addEventListener('click', () => this.saveAccount());
        document.getElementById('btn-logout').addEventListener('click', () => this.logout());
    },

    setCachedPassword(pwd) {
        // Purely in-memory - no storage persistence across sessions
        this.cachedPassword = pwd;
    },

    showPage(page) {
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById(`page-${page}`).classList.add('active');

        if (page === 'settings') {
            this.loadSettings();
        }
    },

    onLoginSuccess(username, isRestore = false) {
        document.getElementById('user-badge').textContent = username;
        document.getElementById('settings-user-badge').textContent = username;
        this.showPage('main');
        if (!isRestore) {
            this.showToast(`👋 欢迎, ${username}`);
        }
        this.loadFiles('/');
    },

    // ─── File Browsing ───

    async loadFiles(path) {
        this.currentPath = path;
        const fileList = document.getElementById('file-list');
        const emptyState = document.getElementById('empty-state');
        const loadingState = document.getElementById('loading-state');

        fileList.classList.add('hidden');
        emptyState.classList.add('hidden');
        loadingState.classList.remove('hidden');

        // Show floating progress for flat mode as it might take a while
        if (this.isFlatMode) {
            this.updateProgressWidget(true, '🌐', '正在穿透子目录...', '正在扫描服务器所有文件，请稍候...', 50);
        }

        // Update Breadcrumb navigation
        this.renderBreadcrumbs(path);

        const endpoint = this.isFlatMode ? '/api/files/list_all' : '/api/files/list';
        const data = await API.get(`${endpoint}?path=${encodeURIComponent(path)}`);
        
        loadingState.classList.add('hidden');
        if (this.isFlatMode) {
            this.updateProgressWidget(false);
        }

        if (data && data.scanning) {
            emptyState.classList.remove('hidden');
            emptyState.querySelector('.empty-icon').textContent = '⏳';
            emptyState.querySelector('p').textContent = '正在构建全局索引库...';
            emptyState.querySelector('.hint').textContent = '系统正在深度扫描您的 NAS 文件，请稍候...';
            document.getElementById('scan-progress-container').classList.remove('hidden');
            this._pollScanStatus(path);
            return;
        }

        document.getElementById('scan-progress-container').classList.add('hidden');

        if (!data || data.error) {
            emptyState.classList.remove('hidden');
            emptyState.querySelector('.empty-icon').textContent = '📂';
            emptyState.querySelector('p').textContent = '还没有文件';
            emptyState.querySelector('.hint').textContent = '请先在设置中配置 WebDAV 地址';
            if (data?.error) {
                emptyState.querySelector('.hint').textContent = data.error;
            }
            return;
        }

        this.files = data.files || [];

        if (this.files.length === 0) {
            emptyState.classList.remove('hidden');
            emptyState.querySelector('.empty-icon').textContent = '📂';
            emptyState.querySelector('p').textContent = '还没有文件';
            emptyState.querySelector('.hint').textContent = '请先在设置中配置 WebDAV 地址';
            return;
        }

        this.applyFilterAndRender();
        fileList.classList.remove('hidden');
    },

    async _pollScanStatus(originalPath) {
        // Stop polling if user left flat mode or navigated away
        if (!this.isFlatMode || this.currentPath !== originalPath) {
            return;
        }

        const status = await API.get('/api/files/scan_status');
        if (!status) {
            setTimeout(() => this._pollScanStatus(originalPath), 2000);
            return;
        }

        const fill = document.getElementById('scan-progress-fill');
        const text = document.getElementById('scan-progress-text');
        const pathEl = document.getElementById('scan-progress-path');

        if (!status.is_scanning) {
            // Scan finished, reload the file list
            this.loadFiles(originalPath);
            return;
        }

        if (status.error && fill && text) {
            text.textContent = '❌ ' + status.error;
            text.style.color = 'var(--danger)';
            fill.style.width = '100%';
            fill.style.background = 'var(--danger)';
            return;
        }

        if (fill && text && pathEl) {
            // Rough percentage based on dir count, capped at 95% until done
            const pseudoPercent = Math.min(95, (status.scanned_dirs || 0) * 2);
            fill.style.width = `${pseudoPercent}%`;
            fill.style.background = '';
            text.style.color = '';
            text.textContent = `已扫描 ${status.scanned_dirs || 0} 个文件夹，发现 ${status.scanned_files || 0} 个文件`;
            pathEl.textContent = status.current_path || '';
        }

        setTimeout(() => this._pollScanStatus(originalPath), 1000);
    },

    renderBreadcrumbs(path) {
        const container = document.getElementById('breadcrumbs');
        const backBtn = document.getElementById('btn-back');
        if (!container) return;

        container.innerHTML = '';
        const parts = path.split('/').filter(Boolean);

        // Root crumb
        const rootCrumb = document.createElement('span');
        rootCrumb.className = 'crumb' + (parts.length === 0 ? ' active' : '');
        rootCrumb.textContent = '🏠 文件库';
        rootCrumb.addEventListener('click', () => this.loadFiles('/'));
        container.appendChild(rootCrumb);

        if (parts.length === 0) {
            backBtn.classList.add('hidden');
            return;
        }

        backBtn.classList.remove('hidden');

        let currentPath = '';
        parts.forEach((part, index) => {
            const sep = document.createElement('span');
            sep.className = 'separator';
            sep.textContent = '/';
            container.appendChild(sep);

            currentPath += '/' + part;
            const crumb = document.createElement('span');
            crumb.className = 'crumb' + (index === parts.length - 1 ? ' active' : '');
            crumb.textContent = decodeURIComponent(part);
            
            // capture value for closure
            const targetPath = currentPath;
            crumb.addEventListener('click', () => this.loadFiles(targetPath));
            
            container.appendChild(crumb);
        });

        // Auto scroll breadcrumb to end
        container.scrollLeft = container.scrollWidth;
    },

    applyFilterAndRender() {
        let filtered = [...this.files];

        // If in Flat Mode, hide directories
        if (this.isFlatMode) {
            filtered = filtered.filter(f => !f.is_dir);
        }

        // 1. Search Filter
        if (this.searchQuery) {
            filtered = filtered.filter(f => f.name.toLowerCase().includes(this.searchQuery));
        }

        // 2. Type Category Filter
        if (this.filterType !== 'all') {
            filtered = filtered.filter(f => {
                if (f.is_dir && !this.isFlatMode) return true; // Keep dirs in normal mode

                const ext = (f.ext || '').toLowerCase();
                const isEvf = ext === '.evf' || f.name.endsWith('.evf');
                let origExt = (f.original_ext || '').toLowerCase();
                if (origExt && !origExt.startsWith('.')) {
                    origExt = '.' + origExt;
                }
                
                const checkExt = (arr) => arr.includes(ext) || (isEvf && arr.includes(origExt));

                if (this.filterType === 'video') {
                    return checkExt(['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.mpeg', '.mpg', '.3gp', '.ts']);
                } else if (this.filterType === 'image') {
                    return checkExt(['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.ico', '.tiff', '.tif']);
                } else if (this.filterType === 'doc') {
                    return checkExt(['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']);
                } else if (this.filterType === 'text') {
                    return checkExt(['.txt', '.md', '.log', '.json', '.xml', '.ini', '.cfg', '.conf', '.py', '.js', '.css', '.html']);
                } else if (this.filterType === 'encrypted') {
                    return isEvf;
                } else if (this.filterType === 'archive') {
                    return checkExt(['.zip', '.rar', '.7z', '.tar', '.gz', '.xz', '.bz2']);
                }
                return true;
            });
        }

        // 3. Sorting
        filtered.sort((a, b) => {
            if (!this.isFlatMode) {
                if (a.is_dir && !b.is_dir) return -1;
                if (!a.is_dir && b.is_dir) return 1;
            }

            let valA, valB;
            if (this.sortBy === 'name') {
                valA = a.name.toLowerCase();
                valB = b.name.toLowerCase();
            } else if (this.sortBy === 'time') {
                valA = a.mtime || '';
                valB = b.mtime || '';
            } else if (this.sortBy === 'size') {
                valA = a.size || 0;
                valB = b.size || 0;
            }

            let cmp = 0;
            if (valA < valB) cmp = -1;
            if (valA > valB) cmp = 1;

            return this.sortAsc ? cmp : -cmp;
        });

        this.currentRenderedFiles = filtered;
        this.renderFiles(filtered);
    },

    renderFiles(files) {
        const fileList = document.getElementById('file-list');
        fileList.innerHTML = '';

        if (files.length === 0) {
            document.getElementById('empty-state').classList.remove('hidden');
            return;
        } else {
            document.getElementById('empty-state').classList.add('hidden');
        }

        // Progressive Chunked Rendering (Display items incrementally without freeze)
        const batchSize = 30;
        let index = 0;

        const renderBatch = () => {
            const end = Math.min(files.length, index + batchSize);
            const fragment = document.createDocumentFragment();

            for (; index < end; index++) {
                const file = files[index];
                const item = this.createFileItem(file, index, files);
                fragment.appendChild(item);
            }

            fileList.appendChild(fragment);

            if (index < files.length) {
                requestAnimationFrame(renderBatch);
            }
        };

        renderBatch();
    },

    createFileItem(file, index, currentList) {
        const item = document.createElement('div');
        item.className = 'file-item';
        if (file.file_hash) {
            item.id = `file-item-${file.file_hash}`;
        }
        item.addEventListener('click', () => this.onFileClick(file, index, currentList));

        const thumb = document.createElement('div');
        thumb.className = 'file-thumb';

        if (file.is_dir) {
            thumb.innerHTML = '<span class="thumb-icon folder-icon">📁</span>';
        } else if (file.has_thumbnail || (file.has_encrypted_thumbnail && this.cachedPassword)) {
            const img = document.createElement('img');
            let thumbUrl = `/api/thumbnails/${file.file_hash}?token=${encodeURIComponent(API.token)}`;
            if (this.cachedPassword) {
                thumbUrl += `&password=${encodeURIComponent(this.cachedPassword)}`;
            }
            const t = file.thumb_t || '1';
            thumbUrl += (thumbUrl.includes('?') ? '&' : '?') + `_t=${t}`;
            img.src = thumbUrl;
            img.loading = 'lazy';
            img.alt = file.name;
            thumb.appendChild(img);
        } else {
            const ext = file.ext || '';
            const isEvf = ext === '.evf' || (file.name && file.name.endsWith('.evf'));
            if (isEvf) {
                const origExt = (file.original_ext || '').toLowerCase();
                if (origExt) {
                    thumb.innerHTML = `<span class="thumb-icon">${this.getFileIcon(origExt)}</span><span class="lock-badge">EVF</span>`;
                } else {
                    thumb.innerHTML = '<span class="thumb-icon">🔒</span><span class="lock-badge">EVF</span>';
                }
            } else {
                thumb.innerHTML = `<span class="thumb-icon">${this.getFileIcon(ext)}</span>`;
            }
        }

        const nameDiv = document.createElement('div');
        nameDiv.className = 'file-name';
        const isEncrypted = file.ext === '.evf' || file.name.endsWith('.evf');
        if (isEncrypted) nameDiv.classList.add('encrypted');
        nameDiv.textContent = file.name;
        nameDiv.title = file.name;

        item.appendChild(thumb);
        item.appendChild(nameDiv);
        return item;
    },

    onFileClick(file, index, currentList) {
        if (file.is_dir) {
            this.pathHistory.push(this.currentPath);
            this.loadFiles(file.path);
            return;
        }

        const category = Viewer.getCategory(file);
        const isEvf = (file.ext === '.evf') || (file.name && file.name.endsWith('.evf'));

        if (category === 'video') {
            const playlist = (currentList || this.files).filter(f =>
                !f.is_dir && Viewer.getCategory(f) === 'video'
            );
            const playIndex = playlist.findIndex(f => f.path === file.path);
            Player.play(file, playlist, playIndex);
        } else if (category === 'image') {
            const playlist = (currentList || this.files).filter(f =>
                !f.is_dir && Viewer.getCategory(f) === 'image'
            );
            const idx = playlist.findIndex(f => f.path === file.path);
            Viewer.open(file, playlist, idx);
        } else if (category === 'pdf' || category === 'text') {
            Viewer.open(file);
        } else {
            this.showToast('ℹ️ 该类型文件暂不支持在线预览，请下载查看');
        }
    },

    async saveAccount() {
        const user = document.getElementById('set-account-user').value.trim();
        const pass = document.getElementById('set-account-pass').value;
        const status = document.getElementById('account-status');
        const btn = document.getElementById('btn-save-account');

        if (!user) {
            status.textContent = '用户名不能为空';
            status.className = 'status-msg error';
            return;
        }

        btn.disabled = true;
        status.textContent = '保存中...';
        status.className = 'status-msg';

        try {
            const data = await API.put('/api/auth/account', {
                username: user,
                password: pass
            });

            if (data && !data.error) {
                status.textContent = '✅ 账户信息更新成功';
                status.className = 'status-msg success';
                
                // Update username in UI and LocalStorage
                document.getElementById('settings-user-badge').textContent = data.username;
                localStorage.setItem('username', data.username);
                localStorage.setItem('token', data.token); // Store the new token
                
                // Clear password field
                document.getElementById('set-account-pass').value = '';
                
                // Show floating toast
                this.showToast('✅ 账户信息已更新');
            } else {
                status.textContent = data ? data.error : '保存失败';
                status.className = 'status-msg error';
            }
        } catch (e) {
            status.textContent = '保存出错: ' + e.message;
            status.className = 'status-msg error';
        } finally {
            btn.disabled = false;
        }
    },

    // ─── Download ───

    downloadTargetFile: null,

    /** Show the download-format choice dialog for any file (shared by Player & Viewer). */
    promptDownload(file) {
        if (!file) return;
        this.downloadTargetFile = file;
        const isEvf = (file.ext === '.evf') || (file.name && file.name.endsWith('.evf'));

        if (!isEvf) {
            // Plain file: direct download
            const dlUrl = `/api/files/download_encrypted?path=${encodeURIComponent(file.path)}`;
            this.downloadWithToken(dlUrl, file.name);
            return;
        }
        document.getElementById('download-choice-dialog').classList.remove('hidden');
    },

    async downloadWithToken(url, filename, extraHeaders = {}) {
        this.showToast(`⏳ 正在准备下载 ${filename}...`);
        try {
            const resp = await fetch(url, {
                headers: { 'Authorization': `Bearer ${API.token}`, ...extraHeaders }
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                this.showToast('❌ ' + (err.error || '下载失败'));
                return;
            }
            const blob = await resp.blob();
            const blobUrl = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = blobUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(blobUrl);
            this.showToast(`✅ 开始下载 ${filename}`);
        } catch (e) {
            this.showToast('❌ 下载失败');
        }
    },

    goBack() {
        if (this.pathHistory.length > 0) {
            const prev = this.pathHistory.pop();
            this.loadFiles(prev);
        } else {
            this.loadFiles('/');
        }
    },

    getFileIcon(ext) {
        const iconMap = {
            '.mp4': '🎬', '.mkv': '🎬', '.avi': '🎬', '.mov': '🎬', '.webm': '🎬',
            '.mp3': '🎵', '.flac': '🎵', '.wav': '🎵',
            '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', '.gif': '🖼️',
            '.pdf': '📄', '.txt': '📝', '.doc': '📄',
            '.zip': '📦', '.rar': '📦', '.7z': '📦',
            '.evf': '🔒'
        };
        return iconMap[ext] || '📄';
    },

    // ─── Password & Real-Time Live Thumbnail Generation ───

    _pwdResolve: null,

    askPassword(hint) {
        return new Promise((resolve) => {
            this._pwdResolve = resolve;
            document.getElementById('pwd-hint').textContent = hint || '输入加密密码';
            document.getElementById('evf-password').value = '';
            document.getElementById('password-dialog').classList.remove('hidden');
            setTimeout(() => document.getElementById('evf-password').focus(), 100);
        });
    },

    async showPasswordDialog() {
        const password = await this.askPassword('输入加密密码以解密缩略图和播放视频');
        if (!password) return;

        this.setCachedPassword(password);

        // Immediately show cached thumbnails now that we have the password
        this.loadFiles(this.currentPath);
        this.showToast('🔑 密码已设置，已缓存的缩略图即刻可见');

        // Start silent background generation for missing thumbnails
        const allPaths = this.files
            .filter(f => !f.is_dir && (f.ext === '.evf' || f.name.endsWith('.evf')))
            .map(f => f.path);

        if (allPaths.length > 0) {
            API.post('/api/thumbnails/generate_async', { paths: allPaths, password });
            // Poll for completion every 8s, refresh when done
            this._bgThumbPoller = setInterval(async () => {
                const status = await API.get('/api/thumbnails/generate_status');
                if (!status || !status.running) {
                    clearInterval(this._bgThumbPoller);
                    this._bgThumbPoller = null;
                    if (status && status.done > 0) {
                        this.loadFiles(this.currentPath);
                        this.showToast(`✅ 缩略图补充完成 (${status.done}/${status.total})`);
                    }
                }
            }, 8000);
        }
    },

    // ─── Settings ───

    async loadSettings() {
        const data = await API.get('/api/settings');
        if (data && !data.error) {
            const stype = data.storage_type || 'nas';
            document.getElementById('set-storage-type').value = stype;
            this._applyStorageTypeUI(stype);
            document.getElementById('set-webdav-url').value = data.webdav_url || '';
            document.getElementById('set-webdav-user').value = data.webdav_username || '';
            document.getElementById('set-webdav-pass').value = data.webdav_password || '';
            document.getElementById('set-local-path').value = data.local_path || '';
        }
        document.getElementById('set-account-user').value = localStorage.getItem('username') || '';
    },

    _applyStorageTypeUI(type) {
        const isLocal = type === 'local';
        document.getElementById('storage-nas-fields').classList.toggle('hidden', isLocal);
        document.getElementById('storage-local-fields').classList.toggle('hidden', !isLocal);
    },

    _initStorageTypeToggle() {
        const sel = document.getElementById('set-storage-type');
        if (!sel) return;
        sel.addEventListener('change', () => this._applyStorageTypeUI(sel.value));
    },

    async saveSettings() {
        const statusEl = document.getElementById('settings-status');
        const storageType = document.getElementById('set-storage-type').value;
        const data = {
            storage_type: storageType,
            webdav_url: document.getElementById('set-webdav-url').value.trim(),
            webdav_username: document.getElementById('set-webdav-user').value.trim(),
            webdav_password: document.getElementById('set-webdav-pass').value,
            local_path: document.getElementById('set-local-path').value.trim()
        };

        if (storageType === 'local' && !data.local_path) {
            statusEl.textContent = '❌ 请填写本地加密视频目录路径';
            statusEl.className = 'status-msg error';
            setTimeout(() => { statusEl.textContent = ''; }, 3000);
            return;
        }
        if (storageType === 'nas' && !data.webdav_url) {
            statusEl.textContent = '❌ 请填写 NAS 存储地址';
            statusEl.className = 'status-msg error';
            setTimeout(() => { statusEl.textContent = ''; }, 3000);
            return;
        }

        const result = await API.put('/api/settings', data);
        if (result && result.status === 200) {
            statusEl.textContent = '✅ 设置已保存，正在后台建立文件索引...';
            statusEl.className = 'status-msg success';
            // Auto-trigger background index scan so files show up without waiting 5 minutes
            API.post('/api/files/scan', {});
        } else {
            statusEl.textContent = '❌ 保存失败';
            statusEl.className = 'status-msg error';
        }

        setTimeout(() => { statusEl.textContent = ''; }, 3000);
    },

    async testWebDAV() {
        const statusEl = document.getElementById('settings-status');
        const storageType = document.getElementById('set-storage-type').value;

        if (storageType === 'local') {
            // Local mode: verify the folder exists via test-connection
            statusEl.textContent = '⏳ 正在检查本地目录...';
            statusEl.className = 'status-msg';
            const result = await API.post('/api/files/test-connection', {
                url: '',
                username: '',
                password: '',
                storage_type: 'local',
                local_path: document.getElementById('set-local-path').value.trim()
            });
            if (result && result.data.success) {
                statusEl.textContent = '✅ 目录可用！';
                statusEl.className = 'status-msg success';
            } else {
                statusEl.textContent = '❌ ' + (result?.data?.error || '目录不可用');
                statusEl.className = 'status-msg error';
            }
            setTimeout(() => { statusEl.textContent = ''; }, 3000);
            return;
        }

        statusEl.textContent = '⏳ 正在测试连接...';
        statusEl.className = 'status-msg';

        const result = await API.post('/api/files/test-connection', {
            url: document.getElementById('set-webdav-url').value.trim(),
            username: document.getElementById('set-webdav-user').value.trim(),
            password: document.getElementById('set-webdav-pass').value
        });

        if (result && result.data.success) {
            statusEl.textContent = '✅ 连接成功！';
            statusEl.className = 'status-msg success';
        } else {
            statusEl.textContent = '❌ ' + (result?.data?.error || '连接失败');
            statusEl.className = 'status-msg error';
        }
    },

    logout() {
        API.setToken(null);
        localStorage.removeItem('username');
        this.setCachedPassword(null);
        this.showPage('auth');
        this.showToast('已退出登录');
    },

    // ─── UI Helpers ───

    showToast(msg, duration = 2500) {
        const toast = document.getElementById('toast');
        toast.textContent = msg;
        toast.classList.remove('hidden');
        clearTimeout(this._toastTimer);
        this._toastTimer = setTimeout(() => toast.classList.add('hidden'), duration);
    },

    updateProgressWidget(show, icon = '⏳', title = '正在处理...', detail = '', percent = 0) {
        const widget = document.getElementById('floating-progress');
        if (!widget) return;
        
        if (!show) {
            widget.classList.add('hidden');
            return;
        }
        
        widget.classList.remove('hidden');
        document.getElementById('progress-icon').textContent = icon;
        document.getElementById('progress-title').textContent = title;
        document.getElementById('progress-detail').textContent = detail;
        document.getElementById('progress-bar-fill').style.width = `${percent}%`;

        // Hide dismiss button when done (icon is ✅ or ❌)
        const dismissBtn = document.getElementById('progress-dismiss');
        if (dismissBtn) {
            dismissBtn.style.display = (icon === '✅' || icon === '❌') ? 'none' : '';
        }
    },

    showDownloadOverlay(msg) {
        document.getElementById('download-status').textContent = msg || '加载中...';
        document.getElementById('download-overlay').classList.remove('hidden');
    },

    hideDownloadOverlay() {
        document.getElementById('download-overlay').classList.add('hidden');
    }
};

// ─── Bootstrap ───
document.addEventListener('DOMContentLoaded', () => App.init());

