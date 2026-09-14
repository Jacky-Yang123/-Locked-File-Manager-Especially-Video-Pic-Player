/**
 * Universal file viewer: images, PDF (page-flip + swipe + zoom), text.
 * Encrypted files (.evf) are decrypted via stream session;
 * plain files are proxied via /api/files/raw.
 */
const Viewer = {
    overlay: null,
    content: null,
    titleEl: null,
    pageInfoEl: null,

    mode: null,          // 'image' | 'pdf' | 'text'
    sessionId: null,     // stream session for encrypted files
    rawUrl: null,        // direct url for plain files
    currentFile: null,
    imagePlaylist: null, // [file, ...] for image prev/next navigation
    imageIndex: -1,

    // PDF state
    pageCount: 0,
    currentPage: 0,
    pdfMode: 'flip',     // 'flip' (single page) | 'scroll' (continuous vertical)
    pageCache: new Map(),     // pageNum -> HTMLImageElement (kept in memory, never released)
    pageLoading: new Set(),   // pageNums currently being fetched
    PRELOAD_AHEAD: 3,         // pages to preload ahead of current
    PRELOAD_BEHIND: 1,        // pages to keep loaded behind current
    scrollBound: false,

    // Zoom/pan state (image & pdf)
    scale: 1,
    tx: 0,
    ty: 0,
    _drag: null,         // {startX, startY, baseTx, baseTy}
    _pinch: null,        // {startDist, baseScale}
    _swipe: null,        // {startY, startX, time} for page flip on vertical/horizontal swipe

    VIDEO_EXTS: ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.mpeg', '.mpg', '.3gp', '.ts'],
    IMAGE_EXTS: ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.ico', '.tiff', '.tif'],
    TEXT_EXTS: ['.txt', '.md', '.log', '.json', '.xml', '.ini', '.cfg', '.conf', '.py', '.js', '.css', '.html', '.srt', '.ass', '.yaml', '.yml', '.csv'],

    init() {
        this.overlay = document.getElementById('viewer-overlay');
        this.content = document.getElementById('viewer-content');
        this.titleEl = document.getElementById('viewer-title');
        this.pageInfoEl = document.getElementById('viewer-page-info');

        document.getElementById('viewer-close').addEventListener('click', () => this.close());
        document.getElementById('viewer-download').addEventListener('click', () => {
            if (this.currentFile) App.promptDownload(this.currentFile);
        });
        document.getElementById('viewer-zoom-in').addEventListener('click', () => this.zoomBy(1.25));
        document.getElementById('viewer-zoom-out').addEventListener('click', () => this.zoomBy(0.8));
        document.getElementById('viewer-prev-page').addEventListener('click', () => this.goPage(this.currentPage - 1));
        document.getElementById('viewer-next-page').addEventListener('click', () => this.goPage(this.currentPage + 1));
        document.getElementById('viewer-mode-toggle').addEventListener('click', () => this._togglePdfMode());
        document.getElementById('viewer-prev-image').addEventListener('click', () => this._navigateImage(-1));
        document.getElementById('viewer-next-image').addEventListener('click', () => this._navigateImage(1));

        // Wheel zoom
        this.content.addEventListener('wheel', (e) => {
            if (this.mode !== 'image' && this.mode !== 'pdf') return;
            // In PDF scroll mode: plain wheel scrolls pages natively; Ctrl+wheel zooms
            if (this.mode === 'pdf' && this.pdfMode === 'scroll' && !e.ctrlKey) {
                return; // let browser scroll
            }
            e.preventDefault();
            this.zoomBy(e.deltaY < 0 ? 1.15 : 0.87);
        }, { passive: false });

        // Mouse drag pan
        this.content.addEventListener('mousedown', (e) => {
            if (this.mode !== 'image' && this.mode !== 'pdf') return;
            if (this.mode === 'pdf' && this.pdfMode === 'scroll') return; // scroll mode uses native scrollbars
            if (this.scale <= 1) return;
            this._drag = { startX: e.clientX, startY: e.clientY, baseTx: this.tx, baseTy: this.ty };
            e.preventDefault();
        });
        window.addEventListener('mousemove', (e) => {
            if (!this._drag) return;
            this.tx = this._drag.baseTx + (e.clientX - this._drag.startX);
            this.ty = this._drag.baseTy + (e.clientY - this._drag.startY);
            this._applyTransform();
        });
        window.addEventListener('mouseup', () => { this._drag = null; });

        // Touch: pinch zoom / drag pan / swipe page-flip
        this.content.addEventListener('touchstart', (e) => {
            if (e.touches.length === 2) {
                const d = Math.hypot(
                    e.touches[0].clientX - e.touches[1].clientX,
                    e.touches[0].clientY - e.touches[1].clientY
                );
                this._pinch = { startDist: d, baseScale: this.scale };
                this._swipe = null;
            } else if (e.touches.length === 1) {
                this._swipe = {
                    startX: e.touches[0].clientX,
                    startY: e.touches[0].clientY,
                    baseTx: this.tx,
                    baseTy: this.ty,
                    moved: false
                };
            }
        }, { passive: true });

        this.content.addEventListener('touchmove', (e) => {
            if (this._pinch && e.touches.length === 2) {
                e.preventDefault();
                const d = Math.hypot(
                    e.touches[0].clientX - e.touches[1].clientX,
                    e.touches[0].clientY - e.touches[1].clientY
                );
                this.scale = Math.max(0.5, Math.min(8, this._pinch.baseScale * (d / this._pinch.startDist)));
                if (this.mode === 'pdf' && this.pdfMode === 'scroll') {
                    this._applyScrollZoom();
                } else {
                    this._applyTransform();
                }
            } else if (this._swipe && e.touches.length === 1 && this.scale > 1 && !(this.mode === 'pdf' && this.pdfMode === 'scroll')) {
                // Pan when zoomed in (flip/image modes only; scroll mode uses native scroll)
                this.tx = this._swipe.baseTx + (e.touches[0].clientX - this._swipe.startX);
                this.ty = this._swipe.baseTy + (e.touches[0].clientY - this._swipe.startY);
                this._swipe.moved = true;
                this._applyTransform();
            } else if (this._swipe) {
                this._swipe.moved = true;
            }
        }, { passive: false });

        this.content.addEventListener('touchend', (e) => {
            if (this._pinch) { this._pinch = null; return; }
            if (!this._swipe || !this._swipe.moved) { this._swipe = null; return; }
            const dx = e.changedTouches[0].clientX - this._swipe.startX;
            const dy = e.changedTouches[0].clientY - this._swipe.startY;
            this._swipe = null;

            // Only flip pages when not zoomed in, and only in flip mode
            if (this.scale > 1.05) return;
            if (this.mode === 'pdf' && this.pdfMode === 'flip') {
                // Vertical swipe (up = next, down = prev) or horizontal
                if (Math.abs(dy) > 60 && Math.abs(dy) > Math.abs(dx)) {
                    this.goPage(this.currentPage + (dy < 0 ? 1 : -1));
                } else if (Math.abs(dx) > 60) {
                    this.goPage(this.currentPage + (dx < 0 ? 1 : -1));
                }
            }
        }, { passive: true });

        // Keyboard
        document.addEventListener('keydown', (e) => {
            if (this.overlay.classList.contains('hidden')) return;
            if (e.key === 'Escape') this.close();
            if (this.mode === 'pdf') {
                if (this.pdfMode === 'flip') {
                    if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === 'PageDown' || e.key === ' ') {
                        e.preventDefault();
                        this.goPage(this.currentPage + 1);
                    }
                    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp' || e.key === 'PageUp') {
                        e.preventDefault();
                        this.goPage(this.currentPage - 1);
                    }
                }
            }
            if (e.key === '+' || e.key === '=') this.zoomBy(1.25);
            if (e.key === '-') this.zoomBy(0.8);
        });
    },

    /** Decide category from file object (uses original_ext for .evf). */
    getCategory(file) {
        let ext = (file.ext || '').toLowerCase();
        const isEvf = ext === '.evf' || (file.name && file.name.endsWith('.evf'));
        if (isEvf) {
            ext = (file.original_ext || '').toLowerCase();
            if (ext && !ext.startsWith('.')) ext = '.' + ext;
        }
        if (this.VIDEO_EXTS.includes(ext)) return 'video';
        if (this.IMAGE_EXTS.includes(ext)) return 'image';
        if (ext === '.pdf') return 'pdf';
        if (this.TEXT_EXTS.includes(ext)) return 'text';
        return 'other';
    },

    /** Entry point: open a file in the appropriate viewer. */
    async open(file, playlist, index) {
        const category = this.getCategory(file);
        const isEvf = (file.ext === '.evf') || (file.name && file.name.endsWith('.evf'));
        this.currentFile = file;
        this.imagePlaylist = playlist || null;
        this.imageIndex = (index >= 0) ? index : -1;

        if (category === 'image' || category === 'pdf' || category === 'text') {
            this.mode = category;
        } else {
            App.showToast('ℹ️ 该类型暂不支持在线预览，请下载查看');
            return;
        }

        App.showDownloadOverlay('正在准备预览...');

        try {
            if (isEvf) {
                // Need decryption via stream session
                let password = App.cachedPassword;
                if (!password) {
                    App.hideDownloadOverlay();
                    password = await App.askPassword('输入密码以预览: ' + file.name);
                    if (!password) return;
                    App.showDownloadOverlay('正在准备预览...');
                }

                let result = await API.post('/api/stream/open', { path: file.path, password });
                if (!result || result.status !== 200) {
                    App.hideDownloadOverlay();
                    const errMsg = result?.data?.error || '打开失败';
                    if (errMsg.includes('密码')) {
                        App.setCachedPassword(null);
                        App.showToast('❌ 密码错误');
                        password = await App.askPassword('密码错误，请重新输入');
                        if (password) {
                            App.setCachedPassword(password);
                            return this.open(file);
                        }
                    } else {
                        App.showToast('❌ ' + errMsg);
                    }
                    return;
                }
                App.setCachedPassword(password);
                this.sessionId = result.data.session_id;
                this.rawUrl = `/api/stream/${this.sessionId}/video?token=${encodeURIComponent(API.token)}`;
            } else {
                // Plain file via raw proxy
                this.sessionId = null;
                this.rawUrl = `/api/files/raw?path=${encodeURIComponent(file.path)}&token=${encodeURIComponent(API.token)}`;
            }

            this._showOverlay(file.name);

            if (this.mode === 'image') {
                this._loadImage();
            } else if (this.mode === 'pdf') {
                await this._loadPdf();
            } else if (this.mode === 'text') {
                await this._loadText();
            }

            App.hideDownloadOverlay();
        } catch (err) {
            App.hideDownloadOverlay();
            App.showToast('❌ 预览失败: ' + (err.message || err));
        }
    },

    _showOverlay(title) {
        this.titleEl.textContent = title;
        this.overlay.classList.remove('hidden');
        this.content.innerHTML = '';
        this.content.classList.remove('scroll-mode');
        this.content.style.touchAction = 'none';
        this.scale = 1; this.tx = 0; this.ty = 0;
        this.currentPage = 0; this.pageCount = 0;
        this.pdfMode = 'flip';
        this.pageCache.clear();
        this.pageLoading.clear();
        this._pageAspect = null;
        this.scrollBound = false;
        this._updateToolbar();
    },

    _updateToolbar() {
        const isPdf = this.mode === 'pdf';
        const isImage = this.mode === 'image';
        const isEncryptedPdf = isPdf && !!this.sessionId;
        const canZoom = this.mode === 'image' || (this.mode === 'pdf' && isEncryptedPdf);

        document.getElementById('viewer-zoom-in').classList.toggle('hidden', !canZoom);
        document.getElementById('viewer-zoom-out').classList.toggle('hidden', !canZoom);
        document.getElementById('viewer-prev-page').classList.toggle('hidden', !isEncryptedPdf);
        document.getElementById('viewer-next-page').classList.toggle('hidden', !isEncryptedPdf);
        document.getElementById('viewer-mode-toggle').classList.toggle('hidden', !isEncryptedPdf);

        // Image navigation arrows
        const hasImageList = isImage && this.imagePlaylist && this.imagePlaylist.length > 1;
        document.getElementById('viewer-prev-image').classList.toggle('hidden', !hasImageList);
        document.getElementById('viewer-next-image').classList.toggle('hidden', !hasImageList);

        this.pageInfoEl.classList.toggle('hidden', !isEncryptedPdf);

        // Mode toggle icon: 📄 = currently flip (tap for scroll), 📜 = currently scroll (tap for flip)
        if (isEncryptedPdf) {
            document.getElementById('viewer-mode-toggle').textContent = this.pdfMode === 'flip' ? '📄' : '📜';
            document.getElementById('viewer-mode-toggle').title = this.pdfMode === 'flip' ? '切换为滑动模式' : '切换为翻页模式';
            this.pageInfoEl.textContent = `${this.currentPage + 1} / ${this.pageCount || '?'}`;
        }
    },

    // ─── Image ───

    _loadImage() {
        const img = document.createElement('img');
        img.className = 'viewer-img';
        img.src = this.rawUrl;
        img.alt = this.titleEl.textContent;
        img.draggable = false;
        this.content.innerHTML = '';
        this.content.appendChild(img);
        this._applyTransform();
    },

    // ─── PDF ───

    async _loadPdf() {
        if (this.sessionId) {
            // Encrypted PDF: rendered server-side via PyMuPDF
            const info = await API.get(`/api/preview/${this.sessionId}/pdf/info?token=${encodeURIComponent(API.token)}`);
            if (!info || info.error) {
                App.showToast('❌ ' + (info?.error || 'PDF 打开失败'));
                this.close();
                return;
            }
            this.pageCount = info.page_count;
            this._renderPdfPage(0);
        } else {
            // Plain PDF: let browser render it in an iframe (native viewer with page nav + zoom)
            this.pageCount = 0;
            const frame = document.createElement('iframe');
            frame.className = 'viewer-pdf-frame';
            frame.src = this.rawUrl;
            this.content.innerHTML = '';
            this.content.appendChild(frame);
            this._updateToolbar();
        }
    },

    /** Fetch (or get from cache) a page's <img> element. Cached pages are never released. */
    _loadPageImg(pageNum) {
        if (this.pageCache.has(pageNum)) {
            return Promise.resolve(this.pageCache.get(pageNum));
        }
        if (this.pageLoading.has(pageNum)) {
            // Already in-flight: wait for it
            return new Promise((resolve) => {
                const check = setInterval(() => {
                    if (this.pageCache.has(pageNum)) {
                        clearInterval(check);
                        resolve(this.pageCache.get(pageNum));
                    }
                }, 100);
            });
        }

        this.pageLoading.add(pageNum);
        return new Promise((resolve, reject) => {
            const img = document.createElement('img');
            img.className = 'viewer-img viewer-pdf-page';
            img.draggable = false;
            img.dataset.pageNum = pageNum;
            img.onload = () => {
                this.pageLoading.delete(pageNum);
                this.pageCache.set(pageNum, img);
                // Learn page aspect ratio from first loaded page to size placeholders
                if (!this._pageAspect && img.naturalWidth > 0) {
                    this._pageAspect = img.naturalHeight / img.naturalWidth;
                    this._updateSlotPlaceholders();
                }
                resolve(img);
            };
            img.onerror = () => {
                this.pageLoading.delete(pageNum);
                reject(new Error('page load failed'));
            };
            img.src = `/api/preview/${this.sessionId}/pdf/page/${pageNum}?token=${encodeURIComponent(API.token)}&zoom=2`;
        });
    },

    /** Resize not-yet-loaded slots using the learned page aspect ratio (stabilizes scrollbar). */
    _updateSlotPlaceholders() {
        if (!this._pageAspect) return;
        const scroller = this.content.querySelector('.pdf-scroll-container');
        if (!scroller) return;
        const estHeight = Math.round(scroller.clientWidth * this._pageAspect);
        scroller.querySelectorAll('.pdf-scroll-slot').forEach(slot => {
            if (slot.querySelector('.pdf-slot-hint')) {
                slot.style.minHeight = estHeight + 'px';
            }
        });
    },

    /** Preload pages around the current one (keeps previously loaded pages in memory). */
    _preloadAround(pageNum) {
        const start = Math.max(0, pageNum - this.PRELOAD_BEHIND);
        const end = Math.min(this.pageCount - 1, pageNum + this.PRELOAD_AHEAD);
        for (let i = start; i <= end; i++) {
            if (!this.pageCache.has(i) && !this.pageLoading.has(i)) {
                this._loadPageImg(i).catch(() => {});
            }
        }
    },

    /** Flip mode: show a single cached page; switch is instant once cached (no black flash). */
    _renderPdfPage(pageNum) {
        this.currentPage = Math.max(0, Math.min(pageNum, this.pageCount - 1));
        this.scale = 1; this.tx = 0; this.ty = 0;

        // Flip-mode container holds all loaded pages side by side; only current is visible
        let container = this.content.querySelector('.pdf-flip-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'pdf-flip-container';
            this.content.innerHTML = '';
            this.content.appendChild(container);
        }

        const target = this.pageCache.get(this.currentPage);
        if (target) {
            // Instant switch: hide others, show target — no refetch, no black flash
            container.querySelectorAll('.viewer-pdf-page').forEach(el => {
                el.style.display = (el === target) ? 'block' : 'none';
            });
            if (target.parentNode !== container) container.appendChild(target);
            this._applyTransform();
        } else {
            // First load of this page: show a subtle loading hint without clearing existing page
            this._loadPageImg(this.currentPage).then((img) => {
                if (this.mode !== 'pdf' || this.pdfMode !== 'flip') return;
                if (this.currentPage !== parseInt(img.dataset.pageNum)) return;
                container.querySelectorAll('.viewer-pdf-page').forEach(el => {
                    el.style.display = (el === img) ? 'block' : 'none';
                });
                if (img.parentNode !== container) container.appendChild(img);
                this._applyTransform();
            }).catch(() => App.showToast('❌ 页面加载失败'));
        }

        this._preloadAround(this.currentPage);
        this._updateToolbar();
    },

    /** Scroll mode: continuous vertical stack of pages with lazy loading. */
    _enterScrollMode() {
        this.pdfMode = 'scroll';
        this.scale = 1; this.tx = 0; this.ty = 0;
        this.content.classList.add('scroll-mode');
        this.content.style.touchAction = 'pan-y';   // let browser handle vertical scroll
        this.content.innerHTML = '';

        const scroller = document.createElement('div');
        scroller.className = 'pdf-scroll-container';
        this.content.appendChild(scroller);

        // Scroll listener: update page info as user scrolls
        scroller.addEventListener('scroll', () => {
            if (this.mode !== 'pdf' || this.pdfMode !== 'scroll') return;
            this._onScrollUpdate(scroller);
        });

        // Create slots for ALL pages upfront; images load progressively in background
        // (browser queues same-origin requests automatically, ~6 concurrent)
        for (let i = 0; i < this.pageCount; i++) {
            this._appendScrollPage(scroller, i);
        }

        // Jump to current page after layout
        setTimeout(() => {
            const target = scroller.querySelector(`[data-page-slot="${this.currentPage}"]`);
            if (target) target.scrollIntoView({ block: 'start' });
        }, 50);

        this._updateToolbar();
    },

    /** Append a page slot (placeholder -> real image when loaded) to the scroll container. */
    _appendScrollPage(scroller, pageNum) {
        if (scroller.querySelector(`[data-page-slot="${pageNum}"]`)) return;

        // Keep slots in order
        const slot = document.createElement('div');
        slot.className = 'pdf-scroll-slot';
        slot.dataset.pageSlot = pageNum;
        slot.innerHTML = `<div class="pdf-slot-hint">第 ${pageNum + 1} 页 加载中...</div>`;

        // Insert in correct order
        const slots = Array.from(scroller.querySelectorAll('.pdf-scroll-slot'));
        const next = slots.find(s => parseInt(s.dataset.pageSlot) > pageNum);
        if (next) scroller.insertBefore(slot, next);
        else scroller.appendChild(slot);

        this._loadPageImg(pageNum).then((img) => {
            if (this.mode !== 'pdf') return;
            slot.innerHTML = '';
            img.style.display = 'block';
            img.classList.add('pdf-scroll-img');
            slot.appendChild(img);
            this._applyScrollZoom();
        }).catch(() => {
            slot.innerHTML = `<div class="pdf-slot-hint" style="color:var(--danger)">第 ${pageNum + 1} 页加载失败</div>`;
        });
    },

    _onScrollUpdate(scroller) {
        // Update current page indicator based on which slot is nearest the top
        const slots = scroller.querySelectorAll('.pdf-scroll-slot');
        let best = this.currentPage;
        let bestDist = Infinity;
        const mid = scroller.scrollTop + scroller.clientHeight / 3;
        slots.forEach(s => {
            const d = Math.abs(s.offsetTop - mid);
            if (d < bestDist) { bestDist = d; best = parseInt(s.dataset.pageSlot); }
        });
        if (best !== this.currentPage) {
            this.currentPage = best;
            this._updateToolbar();
        }
    },

    /** Navigate to prev/next image in playlist. */
    async _navigateImage(dir) {
        if (!this.imagePlaylist) return;
        const next = this.imageIndex + dir;
        if (next < 0 || next >= this.imagePlaylist.length) {
            App.showToast(dir < 0 ? '已经是第一张了' : '已经是最后一张了');
            return;
        }
        App.showDownloadOverlay('正在准备下一张...');
        try {
            await this.open(this.imagePlaylist[next], this.imagePlaylist, next);
        } finally {
            App.hideDownloadOverlay();
        }
    },

    _togglePdfMode() {
        if (this.mode !== 'pdf' || !this.sessionId) return;
        if (this.pdfMode === 'flip') {
            this._enterScrollMode();
            App.showToast('📜 滑动模式：上下滚动浏览');
        } else {
            this.pdfMode = 'flip';
            this.content.classList.remove('scroll-mode');
            this.content.style.touchAction = 'none';
            this._renderPdfPage(this.currentPage);
            App.showToast('📄 翻页模式');
        }
    },

    goPage(n) {
        if (this.mode !== 'pdf' || !this.sessionId) return;
        if (n < 0 || n >= this.pageCount) {
            App.showToast(n < 0 ? '已经是第一页了' : '已经是最后一页了');
            return;
        }
        if (this.pdfMode === 'scroll') {
            const scroller = this.content.querySelector('.pdf-scroll-container');
            if (scroller) {
                let target = scroller.querySelector(`[data-page-slot="${n}"]`);
                if (!target) {
                    this._appendScrollPage(scroller, n);
                    target = scroller.querySelector(`[data-page-slot="${n}"]`);
                }
                this.currentPage = n;
                if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                this._updateToolbar();
            }
        } else {
            this._renderPdfPage(n);
        }
    },

    // ─── Text ───

    async _loadText() {
        const resp = await fetch(this.rawUrl);
        if (!resp.ok) {
            App.showToast('❌ 文本加载失败');
            this.close();
            return;
        }
        let text = await resp.text();
        // Limit display size for huge files
        if (text.length > 500 * 1024) {
            text = text.slice(0, 500 * 1024) + '\n\n... (文件过大，仅显示前 500KB)';
        }
        const pre = document.createElement('pre');
        pre.className = 'viewer-text';
        pre.textContent = text;
        this.content.innerHTML = '';
        this.content.appendChild(pre);
    },

    // ─── Zoom & Pan ───

    zoomBy(factor) {
        if (this.mode !== 'image' && this.mode !== 'pdf') return;
        this.scale = Math.max(0.5, Math.min(8, this.scale * factor));
        if (this.mode === 'pdf' && this.pdfMode === 'scroll') {
            this._applyScrollZoom();
        } else {
            this._applyTransform();
        }
    },

    _applyTransform() {
        const img = this.content.querySelector('.viewer-img:not(.pdf-scroll-img)');
        if (img) {
            img.style.transform = `translate(${this.tx}px, ${this.ty}px) scale(${this.scale})`;
        }
    },

    /** Scroll-mode zoom: scale every page's width; browser reflows naturally. */
    _applyScrollZoom() {
        const imgs = this.content.querySelectorAll('.pdf-scroll-img');
        const widthPct = Math.round(this.scale * 100);
        imgs.forEach(img => { img.style.width = widthPct + '%'; });
    },

    // ─── Close ───

    close() {
        this.overlay.classList.add('hidden');
        this.content.innerHTML = '';
        this.pageCache.clear();
        this.pageLoading.clear();
        if (this.sessionId) {
            API.post(`/api/stream/${this.sessionId}/close`, {});
            this.sessionId = null;
        }
        this.rawUrl = null;
        this.mode = null;
        this.currentFile = null;
        this.imagePlaylist = null;
        this.imageIndex = -1;
        this._drag = null;
        this._pinch = null;
        this._swipe = null;
    }
};
