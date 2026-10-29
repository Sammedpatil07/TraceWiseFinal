/**
 * TraceWise Authentication & Role-Based Access Control (RBAC) Module
 * Handles session management, role enforcement, user administration, and audit trails.
 */

const Auth = {
    currentUser: null,
    isInitialized: false,
    eventsBound: false,

    async init() {
        if (this.isInitialized) return;
        this.isInitialized = true;
        this.bindEvents();
        await this.checkAuth();
    },

    bindEvents() {
        if (this.eventsBound) return;
        this.eventsBound = true;

        // Sign in button in header & hero section
        const showLoginBtn = document.getElementById('btn-show-login');
        if (showLoginBtn) {
            showLoginBtn.addEventListener('click', () => {
                this.showLoginModal();
            });
        }

        const heroSignInBtn = document.getElementById('btn-hero-sign-in');
        if (heroSignInBtn) {
            heroSignInBtn.addEventListener('click', () => {
                this.showLoginModal();
            });
        }

        // Close login modal button
        const closeLoginBtn = document.getElementById('login-modal-close');
        if (closeLoginBtn) {
            closeLoginBtn.addEventListener('click', () => {
                this.hideLoginModal();
            });
        }

        // Toggle password visibility
        const togglePwBtn = document.getElementById('btn-toggle-password');
        const pwInput = document.getElementById('login-password');
        const pwIcon = document.getElementById('pw-toggle-icon');
        if (togglePwBtn && pwInput) {
            togglePwBtn.addEventListener('click', () => {
                const isPassword = pwInput.type === 'password';
                pwInput.type = isPassword ? 'text' : 'password';
                if (pwIcon) {
                    pwIcon.innerHTML = isPassword ? '&#128584;' : '&#128065;';
                }
                togglePwBtn.setAttribute('aria-label', isPassword ? 'Hide password' : 'Show password');
            });
        }

        // Login form submit
        const loginForm = document.getElementById('login-form');
        if (loginForm) {
            loginForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const username = document.getElementById('login-username').value.trim();
                const password = document.getElementById('login-password').value;
                await this.login(username, password);
            });
        }

        // Quick demo login buttons (credential-free role switching)
        const quickBtns = document.querySelectorAll('.quick-login-btn');
        quickBtns.forEach(btn => {
            btn.addEventListener('click', async () => {
                const role = btn.dataset.role;
                if (role) {
                    await this.demoLogin(role);
                }
            });
        });

        // Logout button
        const logoutBtn = document.getElementById('btn-logout');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', async () => {
                await this.logout();
            });
        }

        // Admin Tab: Provision User toggle
        const toggleCreateBtn = document.getElementById('btn-toggle-create-user');
        const createCard = document.getElementById('create-user-card');
        if (toggleCreateBtn && createCard) {
            toggleCreateBtn.addEventListener('click', () => {
                createCard.classList.toggle('hidden');
            });
        }

        const cancelCreateBtn = document.getElementById('btn-cancel-create-user');
        if (cancelCreateBtn && createCard) {
            cancelCreateBtn.addEventListener('click', () => {
                createCard.classList.add('hidden');
                document.getElementById('create-user-form').reset();
            });
        }

        // Admin Tab: Create User submit
        const createUserForm = document.getElementById('create-user-form');
        if (createUserForm) {
            createUserForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                await this.handleCreateUser();
            });
        }

        // Admin Tab: Audit log refresh and filter
        const refreshAuditBtn = document.getElementById('btn-refresh-audit');
        if (refreshAuditBtn) {
            refreshAuditBtn.addEventListener('click', () => {
                this.loadAuditLogs();
            });
        }

        const auditFilter = document.getElementById('audit-filter-action');
        if (auditFilter) {
            auditFilter.addEventListener('change', () => {
                this.loadAuditLogs();
            });
        }
    },

    showLoginModal() {
        const modal = document.getElementById('login-modal');
        if (modal) {
            modal.classList.remove('hidden');
            modal.style.display = 'flex';
            const alertBox = document.getElementById('login-alert-box');
            if (alertBox) {
                alertBox.classList.add('hidden');
                alertBox.style.display = 'none';
            }
            const alertText = document.getElementById('login-alert-text');
            if (alertText) alertText.textContent = '';
            const usernameInput = document.getElementById('login-username');
            if (usernameInput) {
                setTimeout(() => usernameInput.focus(), 50);
            }
        }
    },

    hideLoginModal() {
        const modal = document.getElementById('login-modal');
        if (modal) {
            modal.classList.add('hidden');
            modal.style.display = 'none';
        }
    },

    async checkAuth() {
        try {
            const res = await fetch('/api/auth/me', { credentials: 'same-origin' });
            if (res.ok) {
                const data = await res.json();
                if (data.authenticated && data.user) {
                    this.currentUser = data.user;
                    this.applyRoleUI(this.currentUser);
                    this.hideLoginModal();
                    if (window.AppNavigation) {
                        AppNavigation.navigateFromCurrentHash();
                    }
                    return true;
                }
            }
            this.currentUser = null;
            this.applyRoleUI(null);
            if (window.AppNavigation) {
                AppNavigation.showUnauthenticatedGate();
            }
            // Prompt user to sign in if not authenticated
            this.showLoginModal();
            return false;
        } catch (err) {
            console.error('Error checking auth session:', err);
            this.currentUser = null;
            this.applyRoleUI(null);
            if (window.AppNavigation) {
                AppNavigation.showUnauthenticatedGate();
            }
            this.showLoginModal();
            return false;
        }
    },

    async login(username, password) {
        const alertBox = document.getElementById('login-alert-box');
        const alertText = document.getElementById('login-alert-text');
        const submitBtn = document.getElementById('btn-login-submit');

        if (alertBox) {
            alertBox.classList.add('hidden');
            alertBox.style.display = 'none';
        }
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Authenticating...';
        }

        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });

            const data = await res.json();

            if (!res.ok) {
                if (alertBox && alertText) {
                    alertText.textContent = data.error || 'Authentication failed. Please verify credentials.';
                    alertBox.classList.remove('hidden');
                    alertBox.style.display = 'flex';
                }
                return;
            }

            this.currentUser = data.user;
            this.applyRoleUI(this.currentUser);
            this.hideLoginModal();

            if (window.App && typeof App.showToast === 'function') {
                App.showToast(`Signed in as ${this.currentUser.username} (${this.currentUser.role})`, 'success');
            }

            if (window.App && typeof App.loadAllData === 'function') {
                App.loadAllData();
            }

            if (window.AppNavigation) {
                AppNavigation.navigate('tab-dashboard', { replaceState: true });
            }
        } catch (err) {
            console.error('Login error:', err);
            if (alertBox && alertText) {
                alertText.textContent = 'Network or system error during authentication.';
                alertBox.classList.remove('hidden');
                alertBox.style.display = 'flex';
            }
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Authenticate & Enter';
            }
        }
    },

    async demoLogin(role) {
        try {
            const res = await fetch('/api/auth/demo-login', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role })
            });

            const data = await res.json();
            if (!res.ok) {
                if (window.App) App.showToast(data.error || 'Demo login failed.', 'error');
                return;
            }

            this.currentUser = data.user;
            this.applyRoleUI(this.currentUser);
            this.hideLoginModal();

            if (window.App && typeof App.showToast === 'function') {
                App.showToast(`Signed in as ${this.currentUser.username} (${this.currentUser.role})`, 'success');
            }

            if (window.App && typeof App.loadAllData === 'function') {
                App.loadAllData();
            }

            if (window.AppNavigation) {
                AppNavigation.navigate('tab-dashboard', { replaceState: true });
            }
        } catch (err) {
            console.error('Demo login error:', err);
            if (window.App) App.showToast('Network error during demo login.', 'error');
        }
    },

    async logout() {
        try {
            await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
        } catch (err) {
            console.warn('Logout API call error:', err);
        }

        this.currentUser = null;
        this.applyRoleUI(null);

        if (window.App) {
            App.allIncidents = [];
            App.allServices = [];
            ['stat-total-incidents', 'stat-active-incidents', 'stat-resolved-incidents',
             'stat-total-evidence', 'stat-total-services', 'stat-total-investigations'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = '—';
            });
            const tbody = document.getElementById('incidents-table-body');
            if (tbody) tbody.innerHTML = '';
        }

        if (window.AppNavigation) {
            try {
                history.replaceState(null, '', '#/login');
            } catch (e) {}
            AppNavigation.showUnauthenticatedGate();
        }

        if (window.App && typeof App.showToast === 'function') {
            App.showToast('Signed out successfully.', 'info');
        }

        this.showLoginModal();
    },

    handleUnauthorized() {
        if (this.currentUser) {
            console.warn('Session expired or unauthorized request detected.');
            this.currentUser = null;
            this.applyRoleUI(null);
            if (window.App && typeof App.showToast === 'function') {
                App.showToast('Session expired. Please sign in again.', 'warning');
            }
            this.showLoginModal();
        } else {
            this.applyRoleUI(null);
        }
    },

    applyRoleUI(user) {
        const badge = document.getElementById('user-profile-badge');
        const showLoginBtn = document.getElementById('btn-show-login');
        const usernameSpan = document.getElementById('nav-username');
        const roleSpan = document.getElementById('nav-user-role');
        const adminNavBtn = document.getElementById('nav-btn-admin');
        const demoLoadBtn = document.getElementById('btn-load-demo');
        const resetBtn = document.getElementById('btn-reset-data');
        const runRcaBtn = document.getElementById('btn-run-rca');

        if (!user) {
            if (badge) { badge.classList.add('hidden'); badge.style.display = 'none'; }
            if (showLoginBtn) { showLoginBtn.classList.remove('hidden'); showLoginBtn.style.display = ''; }
            if (adminNavBtn) { adminNavBtn.classList.add('hidden'); adminNavBtn.style.display = 'none'; }
            if (demoLoadBtn) { demoLoadBtn.classList.add('hidden'); demoLoadBtn.style.display = 'none'; }
            if (resetBtn) { resetBtn.classList.add('hidden'); resetBtn.style.display = 'none'; }
            if (usernameSpan) usernameSpan.textContent = '';
            if (roleSpan) {
                roleSpan.textContent = '';
                roleSpan.className = 'badge';
            }
            if (window.AppNavigation) {
                AppNavigation.showUnauthenticatedGate();
            }
            return;
        }

        // Show authenticated user badge
        if (badge) { badge.classList.remove('hidden'); badge.style.display = 'flex'; }
        if (showLoginBtn) { showLoginBtn.classList.add('hidden'); showLoginBtn.style.display = 'none'; }
        if (usernameSpan) usernameSpan.textContent = user.username;

        if (roleSpan) {
            roleSpan.textContent = user.role.replace('_', ' ');
            roleSpan.className = 'badge';
            if (user.role === 'ADMIN') {
                roleSpan.classList.add('badge-purple');
            } else if (user.role === 'INCIDENT_RESPONDER') {
                roleSpan.classList.add('badge-blue');
            } else {
                roleSpan.classList.add('badge-teal');
            }
        }

        // Admin-only Navigation Tab
        if (adminNavBtn) {
            if (user.role === 'ADMIN') {
                adminNavBtn.classList.remove('hidden');
                adminNavBtn.style.display = 'flex';
            } else {
                adminNavBtn.classList.add('hidden');
                adminNavBtn.style.display = 'none';
            }
        }

        // If non-admin user is on tab-admin, navigate away to dashboard
        if (user.role !== 'ADMIN') {
            const adminTab = document.getElementById('tab-admin');
            if (adminTab && adminTab.classList.contains('active')) {
                if (window.AppNavigation) {
                    AppNavigation.navigate('tab-dashboard', { replaceState: true });
                }
            }
        }

        // Role-based action adjustments
        if (user.role === 'ADMIN') {
            if (demoLoadBtn) { demoLoadBtn.classList.remove('hidden'); demoLoadBtn.style.display = ''; demoLoadBtn.disabled = false; demoLoadBtn.style.opacity = '1'; demoLoadBtn.title = 'Load synthetic demonstration fixtures'; }
            if (resetBtn) { resetBtn.classList.remove('hidden'); resetBtn.style.display = ''; resetBtn.disabled = false; resetBtn.style.opacity = '1'; resetBtn.title = 'Clear local telemetry'; }
            if (runRcaBtn) { runRcaBtn.disabled = false; runRcaBtn.title = 'Run Root Cause Analysis'; }
        } else if (user.role === 'INCIDENT_RESPONDER') {
            if (demoLoadBtn) { demoLoadBtn.classList.add('hidden'); demoLoadBtn.style.display = 'none'; demoLoadBtn.disabled = true; demoLoadBtn.style.opacity = '0.5'; demoLoadBtn.title = 'Demo ingestion restricted to Admin role'; }
            if (resetBtn) { resetBtn.classList.add('hidden'); resetBtn.style.display = 'none'; resetBtn.disabled = true; resetBtn.style.opacity = '0.5'; resetBtn.title = 'Data reset restricted to Admin role'; }
            if (runRcaBtn) { runRcaBtn.disabled = false; runRcaBtn.title = 'Run Root Cause Analysis'; }
        } else {
            // VIEWER role (Read-only)
            if (demoLoadBtn) { demoLoadBtn.classList.add('hidden'); demoLoadBtn.style.display = 'none'; demoLoadBtn.disabled = true; demoLoadBtn.style.opacity = '0.5'; demoLoadBtn.title = 'Demo ingestion restricted to Admin role'; }
            if (resetBtn) { resetBtn.classList.add('hidden'); resetBtn.style.display = 'none'; resetBtn.disabled = true; resetBtn.style.opacity = '0.5'; resetBtn.title = 'Data reset restricted to Admin role'; }
            if (runRcaBtn) { runRcaBtn.disabled = true; runRcaBtn.title = 'Viewer role: Read-only access to existing investigations'; }
        }
    },

    // ================= ADMIN USER MANAGEMENT =================

    async loadUsers() {
        const tbody = document.getElementById('admin-users-table-body');
        const countBadge = document.getElementById('admin-user-count');
        if (!tbody) return;

        tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-3">Loading system users...</td></tr>';

        try {
            const res = await fetch('/api/admin/users', { credentials: 'same-origin' });
            if (!res.ok) {
                if (res.status === 401) {
                    this.handleUnauthorized();
                    return;
                }
                if (res.status === 403) {
                    tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-3">Forbidden: Admin permissions required.</td></tr>';
                } else {
                    tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-3">Failed to load user accounts.</td></tr>';
                }
                return;
            }

            const users = await res.json();
            if (countBadge) countBadge.textContent = `${users.length} Users`;

            if (users.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-3">No registered users found.</td></tr>';
                return;
            }

            tbody.innerHTML = users.map(u => {
                const roleBadge = u.role === 'ADMIN' ? 'badge-purple' : (u.role === 'INCIDENT_RESPONDER' ? 'badge-blue' : 'badge-teal');
                const statusBadge = u.is_active ? 'badge-success' : 'badge-danger';
                const statusText = u.is_active ? 'Active' : 'Disabled';
                const createdDate = u.created_at ? new Date(u.created_at).toLocaleString() : '-';

                return `
                    <tr>
                        <td class="font-mono small text-muted">${u.id.substring(0, 8)}...</td>
                        <td><strong>${this.escapeHtml(u.username)}</strong></td>
                        <td><span class="badge ${roleBadge}">${u.role.replace('_', ' ')}</span></td>
                        <td><span class="badge ${statusBadge}">${statusText}</span></td>
                        <td class="text-muted small">${this.escapeHtml(u.email || 'None')}</td>
                        <td class="text-muted small">${createdDate}</td>
                        <td>
                            <select class="filter-select select-xs" onchange="Auth.changeRole('${u.id}', this.value)">
                                <option value="ADMIN" ${u.role === 'ADMIN' ? 'selected' : ''}>ADMIN</option>
                                <option value="INCIDENT_RESPONDER" ${u.role === 'INCIDENT_RESPONDER' ? 'selected' : ''}>INCIDENT_RESPONDER</option>
                                <option value="VIEWER" ${u.role === 'VIEWER' ? 'selected' : ''}>VIEWER</option>
                            </select>
                        </td>
                        <td>
                            <button class="btn btn-xs ${u.is_active ? 'btn-danger-outline' : 'btn-secondary'}"
                                    onclick="Auth.toggleStatus('${u.id}', ${!u.is_active})">
                                ${u.is_active ? 'Disable' : 'Enable'}
                            </button>
                        </td>
                    </tr>
                `;
            }).join('');
        } catch (err) {
            console.error('Error loading users:', err);
            tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-3">Network error loading users.</td></tr>';
        }
    },

    async handleCreateUser() {
        const username = document.getElementById('new-username').value.trim();
        const password = document.getElementById('new-password').value;
        const role = document.getElementById('new-role').value;
        const email = document.getElementById('new-email').value.trim();

        if (!username || !password || !role) {
            if (window.App) App.showToast('Please fill all required fields.', 'error');
            return;
        }

        try {
            const res = await fetch('/api/admin/users', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, role, email })
            });

            const data = await res.json();
            if (!res.ok) {
                if (window.App) App.showToast(data.error || 'Failed to provision user.', 'error');
                return;
            }

            if (window.App) App.showToast(`User ${username} provisioned successfully!`, 'success');
            document.getElementById('create-user-form').reset();
            document.getElementById('create-user-card').classList.add('hidden');
            await this.loadUsers();
            await this.loadAuditLogs();
        } catch (err) {
            console.error('Create user error:', err);
            if (window.App) App.showToast('Network error provisioning user.', 'error');
        }
    },

    async changeRole(userId, newRole) {
        try {
            const res = await fetch(`/api/admin/users/${userId}/role`, {
                method: 'PUT',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role: newRole })
            });

            const data = await res.json();
            if (!res.ok) {
                if (window.App) App.showToast(data.error || 'Failed to update user role.', 'error');
                await this.loadUsers();
                return;
            }

            if (window.App) App.showToast(`Updated role to ${newRole}`, 'success');
            await this.loadUsers();
            await this.loadAuditLogs();
        } catch (err) {
            console.error('Change role error:', err);
            if (window.App) App.showToast('Network error updating role.', 'error');
        }
    },

    async toggleStatus(userId, newStatus) {
        try {
            const res = await fetch(`/api/admin/users/${userId}/status`, {
                method: 'PUT',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_active: newStatus })
            });

            const data = await res.json();
            if (!res.ok) {
                if (window.App) App.showToast(data.error || 'Failed to update user status.', 'error');
                return;
            }

            if (window.App) App.showToast(`User status updated to ${newStatus ? 'Active' : 'Disabled'}`, 'success');
            await this.loadUsers();
            await this.loadAuditLogs();
        } catch (err) {
            console.error('Toggle status error:', err);
            if (window.App) App.showToast('Network error updating user status.', 'error');
        }
    },

    // ================= ADMIN AUDIT LOGS =================

    async loadAuditLogs() {
        const tbody = document.getElementById('admin-audit-table-body');
        const filterSelect = document.getElementById('audit-filter-action');
        if (!tbody) return;

        const actionFilter = filterSelect ? filterSelect.value : '';
        const url = actionFilter ? `/api/admin/audit-logs?action=${encodeURIComponent(actionFilter)}` : '/api/admin/audit-logs';

        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">Loading audit records...</td></tr>';

        try {
            const res = await fetch(url, { credentials: 'same-origin' });
            if (!res.ok) {
                if (res.status === 401) {
                    this.handleUnauthorized();
                    return;
                }
                if (res.status === 403) {
                    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-danger py-3">Forbidden: Admin permissions required.</td></tr>';
                } else {
                    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-danger py-3">Failed to load audit records.</td></tr>';
                }
                return;
            }

            const logs = await res.json();
            if (logs.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">No audit records found matching criteria.</td></tr>';
                return;
            }

            tbody.innerHTML = logs.map(l => {
                const timeStr = l.timestamp ? new Date(l.timestamp).toLocaleTimeString() : '-';
                const resultBadge = l.result === 'SUCCESS' ? 'badge-success' : 'badge-danger';

                let actionBadge = 'badge-info';
                if (l.action === 'LOGIN') actionBadge = 'badge-success';
                else if (l.action.includes('FAILED') || l.action.includes('UNAUTHORIZED')) actionBadge = 'badge-danger';
                else if (l.action === 'RUN_RCA') actionBadge = 'badge-warning';
                else if (l.action.includes('USER') || l.action.includes('ROLE')) actionBadge = 'badge-purple';

                let metaStr = '-';
                if (l.metadata && Object.keys(l.metadata).length > 0) {
                    metaStr = `<code class="small font-mono">${this.escapeHtml(JSON.stringify(l.metadata))}</code>`;
                }

                const resourceStr = l.resource_id ? `${l.resource_type || ''}: ${l.resource_id}` : (l.resource_type || '-');

                return `
                    <tr>
                        <td class="font-mono small text-muted">${timeStr}</td>
                        <td><strong>${this.escapeHtml(l.user_id || 'anonymous')}</strong></td>
                        <td><span class="badge badge-purple">${this.escapeHtml(l.role || 'NONE')}</span></td>
                        <td><span class="badge ${actionBadge}">${this.escapeHtml(l.action)}</span></td>
                        <td class="small font-mono">${this.escapeHtml(resourceStr)}</td>
                        <td><span class="badge ${resultBadge}">${this.escapeHtml(l.result)}</span></td>
                        <td class="small">${metaStr}</td>
                    </tr>
                `;
            }).join('');
        } catch (err) {
            console.error('Error loading audit logs:', err);
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-danger py-3">Network error loading audit logs.</td></tr>';
        }
    },

    escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }
};

window.Auth = Auth;

// Initialize Auth on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    Auth.init();
});
