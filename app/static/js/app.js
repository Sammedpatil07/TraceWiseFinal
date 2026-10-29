/**
 * Main Application Orchestrator for AO-03 TraceWise
 * Evidence-First Incident Intelligence
 * Single Source of Truth for Role-Isolated Navigation & History State Machine
 */

const AppNavigation = {
    currentTab: null,
    currentIncidentId: null,

    // Authoritative Permitted Views per RBAC Role
    PERMITTED_TABS: {
        ADMIN: ['tab-dashboard', 'tab-investigation', 'tab-explorer', 'tab-evaluation', 'tab-admin'],
        INCIDENT_RESPONDER: ['tab-dashboard', 'tab-investigation', 'tab-explorer', 'tab-evaluation'],
        VIEWER: ['tab-dashboard', 'tab-investigation', 'tab-explorer', 'tab-evaluation']
    },

    isTabPermitted(tabId, role) {
        if (!role) return false;
        const normalizedRole = String(role).toUpperCase();
        const allowed = this.PERMITTED_TABS[normalizedRole] || [];
        return allowed.includes(tabId);
    },

    parseHash(hash) {
        if (!hash || hash === '#' || hash === '#/') {
            return { view: 'dashboard', incidentId: null };
        }
        const clean = hash.replace(/^#\/?/, '');
        const [viewPart, queryPart] = clean.split('?');
        const view = viewPart || 'dashboard';
        let incidentId = null;
        if (queryPart) {
            const params = new URLSearchParams(queryPart);
            incidentId = params.get('incident_id');
        }
        return { view, incidentId };
    },

    initHistory() {
        window.addEventListener('popstate', (e) => {
            const currentUser = (window.Auth && Auth.currentUser) || (typeof Auth !== 'undefined' ? Auth.currentUser : null);
            if (!currentUser) {
                this.showUnauthenticatedGate();
                history.replaceState(null, '', '#/login');
                return;
            }

            const parsed = this.parseHash(window.location.hash);
            const targetTabId = `tab-${parsed.view}`;

            if (this.isTabPermitted(targetTabId, currentUser.role)) {
                this.navigate(targetTabId, {
                    incidentId: parsed.incidentId || this.currentIncidentId,
                    pushState: false,
                    replaceState: false,
                    forceRefresh: false
                });
            } else {
                // Blocked destination for this role (e.g. Responder clicking Back to an Admin URL)
                App.showToast(`Restricted: '${parsed.view}' is unavailable for role ${currentUser.role}.`, 'warning');
                this.navigate('tab-dashboard', { pushState: false, replaceState: true });
            }
        });
    },

    showUnauthenticatedGate() {
        document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
        const unauthGate = document.getElementById('tab-unauthenticated');
        if (unauthGate) unauthGate.classList.add('active');

        document.querySelectorAll('.nav-tab').forEach(btn => {
            btn.classList.remove('active');
            btn.setAttribute('aria-selected', 'false');
        });

        // Eliminate desync: Never allow user profile or ADMIN nav tab to coexist with unauthenticated gate
        const badge = document.getElementById('user-profile-badge');
        if (badge) {
            badge.classList.add('hidden');
            badge.style.display = 'none';
        }
        const showLoginBtn = document.getElementById('btn-show-login');
        if (showLoginBtn) {
            showLoginBtn.classList.remove('hidden');
            showLoginBtn.style.display = '';
        }
        const adminNavBtn = document.getElementById('nav-btn-admin');
        if (adminNavBtn) {
            adminNavBtn.classList.add('hidden');
            adminNavBtn.style.display = 'none';
        }
        const demoLoadBtn = document.getElementById('btn-load-demo');
        if (demoLoadBtn) {
            demoLoadBtn.classList.add('hidden');
            demoLoadBtn.style.display = 'none';
        }
        const resetBtn = document.getElementById('btn-reset-data');
        if (resetBtn) {
            resetBtn.classList.add('hidden');
            resetBtn.style.display = 'none';
        }
        const usernameSpan = document.getElementById('nav-username');
        if (usernameSpan) usernameSpan.textContent = '';
        const roleSpan = document.getElementById('nav-user-role');
        if (roleSpan) {
            roleSpan.textContent = '';
            roleSpan.className = 'badge';
        }

        this.currentTab = 'tab-unauthenticated';
    },

    navigateFromCurrentHash() {
        const hash = window.location.hash;
        if (!hash || hash === '#/login') {
            return this.navigate('tab-dashboard', { replaceState: true });
        }
        const parsed = this.parseHash(hash);
        const targetTabId = `tab-${parsed.view}`;
        const user = (window.Auth && Auth.currentUser) || (typeof Auth !== 'undefined' ? Auth.currentUser : null);

        if (user && this.isTabPermitted(targetTabId, user.role)) {
            return this.navigate(targetTabId, { incidentId: parsed.incidentId, replaceState: true });
        }
        return this.navigate('tab-dashboard', { replaceState: true });
    },

    navigate(tabId, options = {}) {
        const { incidentId = null, pushState = true, replaceState = false, forceRefresh = false } = options;
        const user = (window.Auth && Auth.currentUser) || (typeof Auth !== 'undefined' ? Auth.currentUser : null);

        if (!user) {
            this.showUnauthenticatedGate();
            if (window.Auth && typeof Auth.showLoginModal === 'function') {
                Auth.showLoginModal();
            }
            return false;
        }

        // Verify destination permission against authoritative role
        if (!this.isTabPermitted(tabId, user.role)) {
            App.showToast(`Access Restricted: '${tabId.replace('tab-', '')}' requires Admin permissions.`, 'error');
            if (this.currentTab !== 'tab-dashboard') {
                this.navigate('tab-dashboard', { pushState: false, replaceState: true });
            }
            return false;
        }

        // 1. Synchronously update nav tab buttons (instant first-click response)
        document.querySelectorAll('.nav-tab').forEach(btn => {
            const isActive = btn.dataset.tab === tabId;
            btn.classList.toggle('active', isActive);
            btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });

        // 2. Synchronously update tab panes
        document.querySelectorAll('.tab-pane').forEach(pane => {
            pane.classList.toggle('active', pane.id === tabId);
        });

        const prevTab = this.currentTab;
        this.currentTab = tabId;

        if (incidentId) {
            this.currentIncidentId = incidentId;
        }

        // 3. Update Browser History State
        const viewSlug = tabId.replace('tab-', '');
        let urlHash = `#/${viewSlug}`;
        if (this.currentIncidentId && (tabId === 'tab-investigation' || tabId === 'tab-explorer')) {
            urlHash += `?incident_id=${encodeURIComponent(this.currentIncidentId)}`;
        }

        const historyState = {
            tabId,
            incidentId: this.currentIncidentId,
            role: user.role
        };

        if (pushState && window.location.hash !== urlHash) {
            history.pushState(historyState, '', urlHash);
        } else if (replaceState) {
            history.replaceState(historyState, '', urlHash);
        }

        // 4. Trigger View Data Loading
        this.loadViewData(tabId, prevTab, forceRefresh);
        return true;
    },

    loadViewData(tabId, prevTab, forceRefresh = false) {
        if (tabId === 'tab-dashboard') {
            if (forceRefresh || !App.allIncidents || App.allIncidents.length === 0) {
                App.loadDashboard();
            }
        } else if (tabId === 'tab-investigation') {
            const targetId = this.currentIncidentId || (window.IncidentInvestigation ? IncidentInvestigation.currentIncidentId : null);
            if (window.IncidentInvestigation) {
                IncidentInvestigation.populateIncidentDropdown(targetId);
            }
        } else if (tabId === 'tab-explorer') {
            if (window.EvidenceExplorer) {
                if (this.currentIncidentId) {
                    EvidenceExplorer.currentIncidentFilter = this.currentIncidentId;
                    const incSelect = document.getElementById('explorer-incident-filter');
                    if (incSelect) incSelect.value = this.currentIncidentId;
                }
                EvidenceExplorer.loadEvidence();
            }
        } else if (tabId === 'tab-evaluation') {
            App.loadEvaluation();
        } else if (tabId === 'tab-admin') {
            if (window.Auth && Auth.currentUser && Auth.currentUser.role === 'ADMIN') {
                Auth.loadUsers();
                Auth.loadAuditLogs();
            }
        }
    }
};

window.AppNavigation = AppNavigation;

const App = {
    allIncidents: [],
    allServices: [],
    isInitialized: false,

    init() {
        if (this.isInitialized) return;
        this.isInitialized = true;

        this.bindNavigation();
        this.bindGlobalActions();
        this.bindIncidentFilters();
        this.bindModal();
        AppNavigation.initHistory();

        // Initialize sub-modules without triggering remote fetches yet
        if (window.EvidenceExplorer && typeof EvidenceExplorer.init === 'function') {
            EvidenceExplorer.init();
        }
        if (window.IncidentInvestigation && typeof IncidentInvestigation.init === 'function') {
            IncidentInvestigation.init();
        }

        // Initialize Authentication gate
        if (window.Auth && typeof Auth.init === 'function') {
            Auth.init();
        }
    },

    bindNavigation() {
        // Event delegation on nav tabs container for reliable first-click responsiveness
        const navContainer = document.querySelector('.nav-tabs');
        if (navContainer) {
            navContainer.addEventListener('click', (e) => {
                const btn = e.target.closest('.nav-tab');
                if (!btn || btn.classList.contains('disabled')) return;
                e.preventDefault();
                const targetTabId = btn.dataset.tab;
                if (targetTabId) {
                    AppNavigation.navigate(targetTabId);
                }
            });
        }
    },

    bindGlobalActions() {
        const loadDemoBtn = document.getElementById('btn-load-demo');
        if (loadDemoBtn) {
            loadDemoBtn.addEventListener('click', async () => {
                if (!window.Auth || !Auth.currentUser || Auth.currentUser.role !== 'ADMIN') {
                    this.showToast('Restricted: Loading demonstration fixtures requires Admin role.', 'warning');
                    return;
                }
                try {
                    const res = await fetch('/api/demo/load', { method: 'POST', credentials: 'same-origin' });
                    const data = await res.json();
                    if (!res.ok) {
                        this.showToast(data.error || 'Failed to load demo fixtures.', 'error');
                        return;
                    }
                    this.showToast(data.message, 'success');
                    await this.loadAllData();
                } catch (err) {
                    this.showToast('Failed to load demo fixtures.', 'error');
                }
            });
        }

        const resetBtn = document.getElementById('btn-reset-data');
        if (resetBtn) {
            resetBtn.addEventListener('click', async () => {
                if (!window.Auth || !Auth.currentUser || Auth.currentUser.role !== 'ADMIN') {
                    this.showToast('Restricted: Data reset requires Admin role.', 'warning');
                    return;
                }
                if (!confirm('Are you sure you want to clear all telemetry records and analysis runs?')) return;
                try {
                    const res = await fetch('/api/demo/reset', { method: 'POST', credentials: 'same-origin' });
                    const data = await res.json();
                    if (!res.ok) {
                        this.showToast(data.error || 'Failed to reset data.', 'error');
                        return;
                    }
                    this.showToast(data.message, 'info');
                    await this.loadAllData();
                } catch (err) {
                    this.showToast('Failed to reset data.', 'error');
                }
            });
        }

        const refreshDashBtn = document.getElementById('btn-refresh-dashboard');
        if (refreshDashBtn) {
            refreshDashBtn.addEventListener('click', () => {
                this.loadDashboard();
                this.showToast('Dashboard refreshed.', 'info');
            });
        }

        const refreshEvalBtn = document.getElementById('btn-refresh-eval');
        if (refreshEvalBtn) {
            refreshEvalBtn.addEventListener('click', () => {
                this.loadEvaluation();
                this.showToast('Evaluation data refreshed.', 'info');
            });
        }
    },

    bindIncidentFilters() {
        const searchInput = document.getElementById('filter-incident-search');
        if (searchInput) {
            searchInput.addEventListener('input', () => this.renderFilteredIncidents());
        }

        const sevSelect = document.getElementById('filter-incident-severity');
        if (sevSelect) {
            sevSelect.addEventListener('change', () => this.renderFilteredIncidents());
        }

        const statusSelect = document.getElementById('filter-incident-status');
        if (statusSelect) {
            statusSelect.addEventListener('change', () => this.renderFilteredIncidents());
        }

        const svcSelect = document.getElementById('filter-incident-service');
        if (svcSelect) {
            svcSelect.addEventListener('change', () => this.renderFilteredIncidents());
        }

        const sortSelect = document.getElementById('sort-incident-time');
        if (sortSelect) {
            sortSelect.addEventListener('change', () => this.renderFilteredIncidents());
        }
    },

    bindModal() {
        const modal = document.getElementById('evidence-modal');
        const closeBtn = document.getElementById('btn-close-modal');

        if (closeBtn && modal) {
            closeBtn.addEventListener('click', () => {
                modal.classList.add('hidden');
            });
            modal.addEventListener('click', (e) => {
                if (e.target === modal) modal.classList.add('hidden');
            });
            window.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') modal.classList.add('hidden');
            });
        }
    },

    async loadAllData() {
        await this.loadDashboard();
        if (window.IncidentInvestigation && typeof IncidentInvestigation.populateIncidentDropdown === 'function') {
            await IncidentInvestigation.populateIncidentDropdown(AppNavigation.currentIncidentId);
        }
        if (window.EvidenceExplorer && typeof EvidenceExplorer.loadEvidence === 'function') {
            await EvidenceExplorer.loadEvidence();
        }
    },

    async loadDashboard() {
        const currentUser = (window.Auth && Auth.currentUser) || (typeof Auth !== 'undefined' ? Auth.currentUser : null);
        if (!currentUser) return;
        await Promise.all([
            this.loadStats(),
            this.loadServicesList(),
            this.loadIncidents()
        ]);
    },

    async loadStats() {
        try {
            const res = await fetch('/api/stats', { credentials: 'same-origin' });
            if (!res.ok) {
                if (res.status === 401) {
                    if (window.Auth) Auth.handleUnauthorized();
                    ['stat-total-incidents', 'stat-active-incidents', 'stat-resolved-incidents',
                     'stat-total-evidence', 'stat-total-services', 'stat-total-investigations'].forEach(id => {
                        const el = document.getElementById(id);
                        if (el) el.textContent = '—';
                    });
                    return;
                }
                return;
            }
            const data = await res.json();

            document.getElementById('stat-total-incidents').textContent = data.total_incidents ?? 0;
            document.getElementById('stat-active-incidents').textContent = data.active_incidents ?? 0;
            document.getElementById('stat-resolved-incidents').textContent = data.resolved_incidents ?? 0;
            document.getElementById('stat-total-evidence').textContent = data.evidence_count ?? 0;
            document.getElementById('stat-total-services').textContent = data.services_count ?? 0;
            document.getElementById('stat-total-investigations').textContent = data.investigations_count ?? 0;
        } catch (err) {
            console.error('Failed to load stats:', err);
        }
    },

    async loadServicesList() {
        try {
            const res = await fetch('/api/services', { credentials: 'same-origin' });
            if (!res.ok) {
                if (res.status === 401 && window.Auth) Auth.handleUnauthorized();
                return;
            }
            const data = await res.json();
            if (!Array.isArray(data)) return;
            this.allServices = data;

            const svcSelect = document.getElementById('filter-incident-service');
            if (svcSelect) {
                const currentVal = svcSelect.value;
                svcSelect.innerHTML = '<option value="">All Services</option>' +
                    this.allServices.map(s => `<option value="${s.id}">${s.name || s.id}</option>`).join('');
                svcSelect.value = currentVal;
            }

            const expSvcSelect = document.getElementById('explorer-service-filter');
            if (expSvcSelect) {
                const currentVal = expSvcSelect.value;
                expSvcSelect.innerHTML = '<option value="">All Services</option>' +
                    this.allServices.map(s => `<option value="${s.id}">${s.name || s.id}</option>`).join('');
                expSvcSelect.value = currentVal;
            }
        } catch (err) {
            console.error('Failed to load services list:', err);
        }
    },

    async loadIncidents() {
        const tbody = document.getElementById('incidents-table-body');
        if (!tbody) return;

        try {
            const res = await fetch('/api/incidents', { credentials: 'same-origin' });
            if (!res.ok) {
                if (res.status === 401) {
                    if (window.Auth) Auth.handleUnauthorized();
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="9" class="text-center py-4 text-muted">
                                <span class="badge badge-warning">AUTHENTICATION REQUIRED</span>
                                <div class="mt-2 text-muted small">Please sign in to view incident telemetry from Supabase.</div>
                                <button class="btn btn-sm btn-primary mt-2" onclick="Auth.showLoginModal()">Sign In</button>
                            </td>
                        </tr>
                    `;
                    return;
                }
                tbody.innerHTML = `<tr><td colspan="9" class="text-center text-danger py-4">Error connecting to incidents API (HTTP ${res.status}). <button class="btn btn-xs btn-secondary ml-2" onclick="App.loadIncidents()">Retry</button></td></tr>`;
                return;
            }

            const data = await res.json();
            if (!Array.isArray(data)) {
                tbody.innerHTML = `<tr><td colspan="9" class="text-center text-danger py-4">Invalid data received from incidents API. <button class="btn btn-xs btn-secondary ml-2" onclick="App.loadIncidents()">Retry</button></td></tr>`;
                return;
            }

            this.allIncidents = data;
            this.renderFilteredIncidents();
        } catch (err) {
            console.error('Failed to load incidents:', err);
            tbody.innerHTML = `<tr><td colspan="9" class="text-center text-danger py-4">Error connecting to incidents API. <button class="btn btn-xs btn-secondary ml-2" onclick="App.loadIncidents()">Retry</button></td></tr>`;
        }
    },

    renderFilteredIncidents() {
        const tbody = document.getElementById('incidents-table-body');
        if (!tbody) return;

        const searchQuery = (document.getElementById('filter-incident-search')?.value || '').toLowerCase().trim();
        const sevFilter = document.getElementById('filter-incident-severity')?.value || '';
        const statusFilter = document.getElementById('filter-incident-status')?.value || '';
        const svcFilter = document.getElementById('filter-incident-service')?.value || '';
        const sortOrder = document.getElementById('sort-incident-time')?.value || 'desc';

        let filtered = [...this.allIncidents];

        if (searchQuery) {
            filtered = filtered.filter(inc => {
                const text = `${inc.id} ${inc.title} ${inc.description} ${(inc.affected_services || []).join(' ')}`.toLowerCase();
                return text.includes(searchQuery);
            });
        }

        if (sevFilter) {
            filtered = filtered.filter(inc => (inc.severity || '').toUpperCase() === sevFilter.toUpperCase());
        }

        if (statusFilter) {
            filtered = filtered.filter(inc => (inc.status || '').toUpperCase() === statusFilter.toUpperCase());
        }

        if (svcFilter) {
            filtered = filtered.filter(inc => (inc.affected_services || []).includes(svcFilter));
        }

        // Sort by started_at
        filtered.sort((a, b) => {
            const timeA = new Date(a.started_at || 0).getTime();
            const timeB = new Date(b.started_at || 0).getTime();
            return sortOrder === 'asc' ? timeA - timeB : timeB - timeA;
        });

        if (filtered.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="9" class="text-center text-muted py-4">
                        No matching incidents found.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = filtered.map(inc => {
            const sevClass = (inc.severity || 'info').toLowerCase();
            const statusClass = (inc.status || '').toLowerCase();
            const servicesPills = (inc.affected_services || []).map(s => `
                <span class="service-pill">${s}</span>
            `).join('') || '<span class="text-muted small">None</span>';

            const started = inc.started_at ? inc.started_at.replace('T', ' ').replace('Z', '') : '-';
            const duration = this.calculateDuration(inc.started_at, inc.resolved_at);

            // Investigation status badge
            let invBadge = `<span class="badge badge-neutral">PENDING</span>`;
            if (inc.investigation_status === 'SUCCESS' || inc.investigation_status === 'ANALYZED') {
                invBadge = `<span class="badge badge-success">&#10003; ANALYZED</span>`;
            } else if (inc.investigation_status === 'INSUFFICIENT_EVIDENCE') {
                invBadge = `<span class="badge badge-warning">&#9888; UNKNOWN / INSUFFICIENT</span>`;
            }

            return `
                <tr style="cursor: pointer;" onclick="App.navigateToInvestigation('${inc.id}')">
                    <td><span class="badge-id">${inc.id}</span></td>
                    <td>
                        <strong style="color: #FFFFFF;">${inc.title}</strong>
                        <div class="text-muted small" style="max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            ${inc.description || 'No description'}
                        </div>
                    </td>
                    <td class="small font-mono text-muted">${started}</td>
                    <td><span class="badge badge-neutral">${duration}</span></td>
                    <td><div class="pill-group">${servicesPills}</div></td>
                    <td><span class="badge badge-severity ${sevClass}">${inc.severity}</span></td>
                    <td><span class="badge badge-status ${statusClass}">${inc.status}</span></td>
                    <td>${invBadge}</td>
                    <td>
                        <button class="btn btn-sm btn-primary" onclick="event.stopPropagation(); App.navigateToInvestigation('${inc.id}')">
                            Investigate &#10138;
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    },

    calculateDuration(startedAt, resolvedAt) {
        if (!startedAt) return '-';
        const start = new Date(startedAt.replace('Z', '+00:00'));
        if (isNaN(start.getTime())) return '-';

        const end = resolvedAt ? new Date(resolvedAt.replace('Z', '+00:00')) : new Date();
        const diffMs = Math.max(0, end.getTime() - start.getTime());
        const mins = Math.floor(diffMs / 60000);
        const hours = Math.floor(mins / 60);

        if (!resolvedAt) {
            return hours > 0 ? `${hours}h ${mins % 60}m (ongoing)` : `${mins}m (ongoing)`;
        }

        if (hours > 0) {
            return `${hours}h ${mins % 60}m`;
        }
        return `${mins}m`;
    },

    navigateToInvestigation(incidentId) {
        AppNavigation.navigate('tab-investigation', { incidentId, pushState: true });
    },

    async loadEvaluation() {
        const tbody = document.getElementById('evaluation-table-body');
        if (!tbody) return;

        try {
            const res = await fetch('/api/evaluation', { credentials: 'same-origin' });
            if (!res.ok) {
                if (res.status === 401) {
                    if (window.Auth) Auth.handleUnauthorized();
                    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4"><span class="badge badge-warning">AUTHENTICATION REQUIRED</span><div class="mt-2 text-muted small">Sign in to view evaluation and benchmark metrics.</div><button class="btn btn-sm btn-primary mt-2" onclick="Auth.showLoginModal()">Sign In</button></td></tr>`;
                    return;
                }
                tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger py-4">Error loading evaluation results (HTTP ${res.status}).</td></tr>`;
                return;
            }
            const data = await res.json();

            // Benchmark metrics
            const metrics = data.metrics || {};
            const isGroundTruthLoaded = Boolean(data.ground_truth_loaded);

            const setMetric = (id, val) => {
                const el = document.getElementById(id);
                if (el) el.textContent = val;
            };

            setMetric('metric-top1', isGroundTruthLoaded && metrics.top1_accuracy !== null ? `${metrics.top1_accuracy}%` : 'Pending organizer ground truth');
            setMetric('metric-top3', isGroundTruthLoaded && metrics.top3_accuracy !== null ? `${metrics.top3_accuracy}%` : 'Pending organizer ground truth');
            setMetric('metric-mrr', isGroundTruthLoaded && metrics.mrr !== null ? metrics.mrr.toFixed(3) : 'Pending organizer ground truth');
            setMetric('metric-unknown', isGroundTruthLoaded && metrics.unknown_detection_accuracy !== null ? `${metrics.unknown_detection_accuracy}%` : 'Pending organizer ground truth');
            setMetric('metric-coverage', metrics.evidence_coverage ? `${metrics.evidence_coverage}%` : '100%');
            if (metrics.mean_analysis_time_ms) {
                setMetric('metric-time', `~${Math.round(metrics.mean_analysis_time_ms)}ms`);
            }

            // Populate table rows
            const records = data.results || [];
            if (records.length === 0) {
                tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">No benchmark evaluation records available.</td></tr>`;
                return;
            }

            tbody.innerHTML = records.map(r => {
                let statusBadge = '<span class="badge badge-neutral">PENDING</span>';
                if (r.status === 'SUCCESS' || r.status === 'ANALYZED') {
                    statusBadge = '<span class="badge badge-success">&#10003; ANALYZED</span>';
                } else if (r.status === 'INSUFFICIENT_EVIDENCE') {
                    statusBadge = '<span class="badge badge-warning">&#9888; UNKNOWN</span>';
                }

                const topCand = r.top_candidate;
                const topCauseTitle = topCand ? topCand.title : '<span class="text-muted">None identified</span>';
                const scoreText = topCand ? `<span class="badge-score">${(topCand.evidence_score || 0).toFixed(3)}</span>` : '-';
                const analyzedTime = r.analyzed_at ? r.analyzed_at.replace('T', ' ').slice(0, 19) : '-';

                return `
                    <tr>
                        <td><span class="badge-id">${r.incident_id}</span></td>
                        <td><strong>${r.incident_title}</strong></td>
                        <td><span class="font-mono">${r.evidence_count ?? 0}</span></td>
                        <td>${statusBadge}</td>
                        <td>${topCauseTitle}</td>
                        <td>${scoreText}</td>
                        <td class="small font-mono text-muted">${analyzedTime}</td>
                        <td>
                            <button class="btn btn-sm btn-secondary" onclick="App.navigateToInvestigation('${r.incident_id}')">
                                View RCA
                            </button>
                        </td>
                    </tr>
                `;
            }).join('');
        } catch (err) {
            console.error('Failed to load evaluation data:', err);
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger py-4">Error loading evaluation results.</td></tr>`;
        }
    },

    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;

        container.appendChild(toast);
        setTimeout(() => {
            toast.remove();
        }, 3500);
    }
};

window.App = App;
window.AppNavigation = AppNavigation;

// Start application on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    App.init();
});
