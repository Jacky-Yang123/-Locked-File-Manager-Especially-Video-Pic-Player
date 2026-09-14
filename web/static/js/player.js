/**
 * Video Player controller.
 */
const Player = {
    video: null,
    overlay: null,
    currentSessionId: null,
    controlsTimeout: null,
    playlist: [],       // Array of file objects
    currentIndex: -1,

    init() {
        this.video = document.getElementById('video-element');
        this.overlay = document.getElementById('player-overlay');

        // Control buttons
        document.getElementById('player-close').addEventListener('click', () => this.close());
        document.getElementById('btn-play').addEventListener('click', () => this.togglePlay());
        document.getElementById('btn-rewind').addEventListener('click', () => this.seek(-10));
        document.getElementById('btn-forward').addEventListener('click', () => this.seek(10));
        document.getElementById('btn-prev').addEventListener('click', () => this.playPrev());
        document.getElementById('btn-next').addEventListener('click', () => this.playNext());
        document.getElementById('btn-fullscreen').addEventListener('click', () => this.toggleFullscreen());

        const dlBtn = document.getElementById('btn-download');
        if (dlBtn) {
            dlBtn.addEventListener('click', () => {
                if (!this.currentFile) return;
                App.promptDownload(this.currentFile);
            });
        }

        // Download choice modal listeners (shared by Player and Viewer via App.downloadTargetFile)
        document.getElementById('btn-choice-cancel').addEventListener('click', () => {
            document.getElementById('download-choice-dialog').classList.add('hidden');
        });

        document.getElementById('btn-choice-dl-enc').addEventListener('click', () => {
            document.getElementById('download-choice-dialog').classList.add('hidden');
            const file = App.downloadTargetFile;
            if (file) {
                const dlUrl = `/api/files/download_encrypted?path=${encodeURIComponent(file.path)}`;
                App.downloadWithToken(dlUrl, file.name);
            }
        });

        document.getElementById('btn-choice-dl-dec').addEventListener('click', async () => {
            document.getElementById('download-choice-dialog').classList.add('hidden');
            const file = App.downloadTargetFile;
            if (file) {
                let pwd = App.cachedPassword;
                if (!pwd) {
                    pwd = await App.askPassword('输入加密密码以解密下载文件');
                    if (!pwd) return;
                    App.setCachedPassword(pwd);
                }
                // Password sent via header, NOT in URL (avoids leaking into logs/history)
                const dlUrl = `/api/files/download_decrypted?path=${encodeURIComponent(file.path)}`;
                App.downloadWithToken(dlUrl, file.name.replace('.evf', ''), { 'X-EVF-Password': pwd });
            }
        });

        // Progress bar
        const progressBar = document.getElementById('progress-bar');
        progressBar.addEventListener('input', () => {
            if (this.video.duration) {
                this.video.currentTime = (progressBar.value / 1000) * this.video.duration;
            }
        });

        // Video events
        this.video.addEventListener('timeupdate', () => this.updateProgress());
        this.video.addEventListener('play', () => this.updatePlayButton(true));
        this.video.addEventListener('pause', () => this.updatePlayButton(false));
        this.video.addEventListener('ended', () => this.playNext());
        this.video.addEventListener('loadedmetadata', () => {
            document.getElementById('time-total').textContent = this.formatTime(this.video.duration);
        });

        // Auto-hide controls
        this.overlay.addEventListener('click', (e) => {
            if (e.target === this.video || e.target.classList.contains('player-container')) {
                this.toggleControls();
            }
        });

        // Touch gesture support for seeking
        let touchStartX = 0;
        let touchStartTime = 0;
        this.video.addEventListener('touchstart', (e) => {
            touchStartX = e.touches[0].clientX;
            touchStartTime = this.video.currentTime;
        }, { passive: true });

        this.video.addEventListener('touchend', (e) => {
            const deltaX = e.changedTouches[0].clientX - touchStartX;
            if (Math.abs(deltaX) > 50) {
                // Swipe: 100px = 10s
                const seekAmount = (deltaX / 100) * 10;
                this.video.currentTime = Math.max(0, touchStartTime + seekAmount);
                App.showToast(`${seekAmount > 0 ? '+' : ''}${Math.round(seekAmount)}s`);
            }
        }, { passive: true });
    },

    async play(file, playlist, index) {
        this.playlist = playlist || [];
        this.currentIndex = index >= 0 ? index : -1;
        this.currentFile = file;

        const isEncrypted = file.ext === '.evf' || file.name.endsWith('.evf');

        if (isEncrypted) {
            // Need password
            let password = App.cachedPassword;
            if (!password) {
                password = await App.askPassword('输入密码以播放: ' + file.name);
                if (!password) return;
            }

            App.showDownloadOverlay('正在准备视频...');

            try {
                const result = await API.post('/api/stream/open', {
                    path: file.path,
                    password: password
                });

                App.hideDownloadOverlay();

                if (!result || result.status !== 200) {
                    const errMsg = result?.data?.error || '打开失败';
                    if (errMsg.includes('密码')) {
                        App.setCachedPassword(null);
                        App.showToast('❌ 密码错误');
                        // Retry with new password
                        password = await App.askPassword('密码错误，请重新输入');
                        if (password) {
                            App.setCachedPassword(password);
                            return this.play(file, playlist, index);
                        }
                    } else {
                        App.showToast('❌ ' + errMsg);
                    }
                    return;
                }

                // Password was correct, cache it
                App.setCachedPassword(password);

                this.currentSessionId = result.data.session_id;
                const videoUrl = `/api/stream/${this.currentSessionId}/video?token=${encodeURIComponent(API.token)}`;

                this.showPlayer(file.name);
                this.video.src = videoUrl;
                this.video.load();
                this.video.play().catch(() => {});

            } catch (err) {
                App.hideDownloadOverlay();
                App.showToast('❌ 网络错误');
            }
        } else {
            // Non-encrypted video — play directly via raw proxy (Range supported)
            this.currentSessionId = null;
            const videoUrl = `/api/files/raw?path=${encodeURIComponent(file.path)}&token=${encodeURIComponent(API.token)}`;
            this.showPlayer(file.name);
            this.video.src = videoUrl;
            this.video.load();
            this.video.play().catch(() => {});
        }
    },

    showPlayer(title) {
        document.getElementById('player-title').textContent = title;
        this.overlay.classList.remove('hidden');
        this.resetControls();
        this.showControls();
    },

    close() {
        this.video.pause();
        this.video.src = '';
        this.overlay.classList.add('hidden');

        // Close stream session
        if (this.currentSessionId) {
            API.post(`/api/stream/${this.currentSessionId}/close`, {});
            this.currentSessionId = null;
        }

        clearTimeout(this.controlsTimeout);
    },

    togglePlay() {
        if (this.video.paused) {
            this.video.play().catch(() => {});
        } else {
            this.video.pause();
        }
    },

    seek(seconds) {
        this.video.currentTime = Math.max(0, this.video.currentTime + seconds);
        App.showToast(`${seconds > 0 ? '+' : ''}${seconds}s`);
        this.showControls();
    },

    playPrev() {
        if (this.currentIndex > 0) {
            const prevFile = this.playlist[this.currentIndex - 1];
            if (prevFile && !prevFile.is_dir) {
                this.close();
                setTimeout(() => this.play(prevFile, this.playlist, this.currentIndex - 1), 200);
            }
        } else {
            App.showToast('已经是第一个了');
        }
    },

    playNext() {
        if (this.currentIndex < this.playlist.length - 1) {
            const nextFile = this.playlist[this.currentIndex + 1];
            if (nextFile && !nextFile.is_dir) {
                this.close();
                setTimeout(() => this.play(nextFile, this.playlist, this.currentIndex + 1), 200);
            }
        } else {
            App.showToast('已经是最后一个了');
        }
    },

    toggleFullscreen() {
        if (!document.fullscreenElement) {
            this.overlay.requestFullscreen?.() ||
            this.overlay.webkitRequestFullscreen?.();
        } else {
            document.exitFullscreen?.() ||
            document.webkitExitFullscreen?.();
        }
    },

    updateProgress() {
        if (!this.video.duration) return;
        const progress = (this.video.currentTime / this.video.duration) * 1000;
        document.getElementById('progress-bar').value = progress;
        document.getElementById('time-current').textContent = this.formatTime(this.video.currentTime);
    },

    updatePlayButton(isPlaying) {
        document.getElementById('btn-play').textContent = isPlaying ? '⏸' : '▶';
    },

    resetControls() {
        document.getElementById('progress-bar').value = 0;
        document.getElementById('time-current').textContent = '00:00';
        document.getElementById('time-total').textContent = '00:00';
        this.updatePlayButton(false);
    },

    showControls() {
        this.overlay.classList.remove('controls-hidden');
        clearTimeout(this.controlsTimeout);
        this.controlsTimeout = setTimeout(() => {
            if (!this.video.paused) {
                this.overlay.classList.add('controls-hidden');
            }
        }, 4000);
    },

    toggleControls() {
        if (this.overlay.classList.contains('controls-hidden')) {
            this.showControls();
        } else {
            this.overlay.classList.add('controls-hidden');
        }
    },

    formatTime(seconds) {
        if (!seconds || isNaN(seconds)) return '00:00';
        seconds = Math.floor(seconds);
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = seconds % 60;
        if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
        return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    }
};
