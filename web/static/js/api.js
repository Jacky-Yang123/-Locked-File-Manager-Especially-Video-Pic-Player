/**
 * API wrapper with JWT authentication.
 */
const API = {
    token: localStorage.getItem('token') || null,
    
    setToken(token) {
        this.token = token;
        if (token) {
            localStorage.setItem('token', token);
        } else {
            localStorage.removeItem('token');
        }
    },

    headers() {
        const h = { 'Content-Type': 'application/json' };
        if (this.token) h['Authorization'] = `Bearer ${this.token}`;
        return h;
    },

    async get(url) {
        const separator = url.includes('?') ? '&' : '?';
        const cacheBustedUrl = `${url}${separator}_t=${Date.now()}`;
        const resp = await fetch(cacheBustedUrl, { headers: this.headers() });
        if (resp.status === 401) { this.onAuthFail(); return null; }
        return resp.json();
    },

    async post(url, data) {
        const resp = await fetch(url, {
            method: 'POST',
            headers: this.headers(),
            body: JSON.stringify(data)
        });
        if (resp.status === 401 && !url.includes('/auth/')) { this.onAuthFail(); return null; }
        return { status: resp.status, data: await resp.json() };
    },

    async put(url, data) {
        const resp = await fetch(url, {
            method: 'PUT',
            headers: this.headers(),
            body: JSON.stringify(data)
        });
        if (resp.status === 401) { this.onAuthFail(); return null; }
        return { status: resp.status, data: await resp.json() };
    },

    onAuthFail() {
        this.setToken(null);
        if (typeof App !== 'undefined') App.showPage('auth');
    },

    isLoggedIn() {
        return !!this.token;
    }
};
