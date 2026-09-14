/**
 * Authentication UI logic.
 */
const Auth = {
    init() {
        // Tab switching
        document.querySelectorAll('.auth-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.auth-form').forEach(f => f.classList.remove('active'));
                tab.classList.add('active');
                const formId = tab.dataset.tab === 'login' ? 'form-login' : 'form-register';
                document.getElementById(formId).classList.add('active');
            });
        });

        // Login form
        document.getElementById('form-login').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('login-username').value.trim();
            const password = document.getElementById('login-password').value;
            const errorEl = document.getElementById('login-error');
            errorEl.textContent = '';

            const result = await API.post('/api/auth/login', { username, password });
            if (!result) return;

            if (result.status === 200) {
                API.setToken(result.data.token);
                localStorage.setItem('username', result.data.username);
                App.onLoginSuccess(result.data.username);
            } else {
                errorEl.textContent = result.data.error || '登录失败';
            }
        });

        // Register form
        document.getElementById('form-register').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('reg-username').value.trim();
            const password = document.getElementById('reg-password').value;
            const password2 = document.getElementById('reg-password2').value;
            const errorEl = document.getElementById('reg-error');
            errorEl.textContent = '';

            if (password !== password2) {
                errorEl.textContent = '两次密码输入不一致';
                return;
            }

            const result = await API.post('/api/auth/register', { username, password });
            if (!result) return;

            if (result.status === 201) {
                API.setToken(result.data.token);
                localStorage.setItem('username', result.data.username);
                App.onLoginSuccess(result.data.username);
            } else {
                errorEl.textContent = result.data.error || '注册失败';
            }
        });
    }
};
