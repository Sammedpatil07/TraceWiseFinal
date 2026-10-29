/**
 * Evidence Explorer Module for AO-03 TraceWise
 */

const EvidenceExplorer = {
    allEvidence: [],
    currentTypeFilter: "",
    currentSourceFilter: "",
    currentServiceFilter: "",
    currentSeverityFilter: "",
    currentIncidentFilter: "",
    currentSearch: "",

    init() {
        this.bindEvents();
    },

    bindEvents() {
        // Evidence Type filter buttons
        const typeButtons = document.querySelectorAll('.type-filter-btn');
        typeButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                typeButtons.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.currentTypeFilter = btn.dataset.type || "";
                this.renderFilteredEvidence();
            });
        });

        // Search input
        const searchInput = document.getElementById('explorer-search');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.currentSearch = e.target.value.toLowerCase().trim();
                this.renderFilteredEvidence();
            });
        }

        // Source filter
        const sourceSelect = document.getElementById('explorer-source-type');
        if (sourceSelect) {
            sourceSelect.addEventListener('change', (e) => {
                this.currentSourceFilter = e.target.value;
                this.renderFilteredEvidence();
            });
        }

        // Service filter
        const svcSelect = document.getElementById('explorer-service-filter');
        if (svcSelect) {
            svcSelect.addEventListener('change', (e) => {
                this.currentServiceFilter = e.target.value;
                this.renderFilteredEvidence();
            });
        }

        // Severity filter
        const sevSelect = document.getElementById('explorer-severity-filter');
        if (sevSelect) {
            sevSelect.addEventListener('change', (e) => {
                this.currentSeverityFilter = e.target.value;
                this.renderFilteredEvidence();
            });
        }

        // Incident filter dropdown
        const incSelect = document.getElementById('explorer-incident-filter');
        if (incSelect) {
            incSelect.addEventListener('change', (e) => {
                this.currentIncidentFilter = e.target.value;
                this.renderFilteredEvidence();
            });
        }
    },

    async loadEvidence() {
        const tbody = document.getElementById('evidence-table-body');
        if (!tbody) return;

        try {
            const res = await fetch('/api/evidence?limit=500', { credentials: 'same-origin' });
            if (!res.ok) {
                if (res.status === 401) {
                    if (window.Auth) Auth.handleUnauthorized();
                    tbody.innerHTML = `<tr><td colspan="10" class="text-center text-muted py-4"><span class="badge badge-warning">AUTHENTICATION REQUIRED</span><div class="mt-2 text-muted small">Sign in to explore raw telemetry and evidence records.</div><button class="btn btn-sm btn-primary mt-2" onclick="Auth.showLoginModal()">Sign In</button></td></tr>`;
                    return;
                }
                tbody.innerHTML = `<tr><td colspan="10" class="text-center text-danger py-4">Error loading telemetry records (HTTP ${res.status}). <button class="btn btn-xs btn-secondary ml-2" onclick="EvidenceExplorer.loadEvidence()">Retry</button></td></tr>`;
                return;
            }

            const data = await res.json();
            if (!Array.isArray(data)) {
                tbody.innerHTML = `<tr><td colspan="10" class="text-center text-danger py-4">Invalid data format for evidence records.</td></tr>`;
                return;
            }

            this.allEvidence = data;
            this.updateIncidentDropdown();
            this.renderFilteredEvidence();
        } catch (err) {
            console.error('Failed to load evidence:', err);
            tbody.innerHTML = `<tr><td colspan="10" class="text-center text-danger py-4">Error loading telemetry records. <button class="btn btn-xs btn-secondary ml-2" onclick="EvidenceExplorer.loadEvidence()">Retry</button></td></tr>`;
        }
    },

    updateIncidentDropdown() {
        const select = document.getElementById('explorer-incident-filter');
        if (!select) return;

        const currentVal = select.value;
        const incidentIds = Array.from(new Set(this.allEvidence.map(e => e.incident_id).filter(Boolean)));
        select.innerHTML = '<option value="">All Incidents</option>' +
            incidentIds.map(id => `<option value="${id}">${id}</option>`).join('');
        select.value = currentVal;
    },

    renderFilteredEvidence() {
        const tbody = document.getElementById('evidence-table-body');
        const badge = document.getElementById('explorer-count-badge');
        if (!tbody) return;

        let filtered = [...this.allEvidence];

        if (this.currentTypeFilter) {
            filtered = filtered.filter(e => (e.evidence_type || '').toUpperCase() === this.currentTypeFilter.toUpperCase());
        }

        if (this.currentSourceFilter) {
            filtered = filtered.filter(e => (e.source_type || '').toUpperCase() === this.currentSourceFilter.toUpperCase());
        }

        if (this.currentServiceFilter) {
            filtered = filtered.filter(e => (e.service || e.service_id) === this.currentServiceFilter);
        }

        if (this.currentSeverityFilter) {
            filtered = filtered.filter(e => (e.severity || '').toUpperCase() === this.currentSeverityFilter.toUpperCase());
        }

        if (this.currentIncidentFilter) {
            filtered = filtered.filter(e => e.incident_id === this.currentIncidentFilter);
        }

        if (this.currentSearch) {
            filtered = filtered.filter(e => {
                const text = `${e.id} ${e.service || e.service_id} ${e.summary} ${e.message} ${e.trace_id} ${e.deployment_id} ${e.configuration_id} ${JSON.stringify(e.details || {})}`.toLowerCase();
                return text.includes(this.currentSearch);
            });
        }

        if (badge) {
            badge.textContent = `${filtered.length} record(s)`;
        }

        if (filtered.length === 0) {
            tbody.innerHTML = `<tr><td colspan="10" class="text-center text-muted py-4">No matching telemetry records found.</td></tr>`;
            return;
        }

        tbody.innerHTML = filtered.map(ev => {
            const sevClass = (ev.severity || 'info').toLowerCase();
            const isSynthetic = ev.source_type === 'SYNTHETIC_DEMO';
            const sourceBadge = isSynthetic
                ? `<span class="badge" style="background: rgba(245, 158, 11, 0.2); color: #FBBF24;">DEMO</span>`
                : `<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #34D399;">ORGANIZER</span>`;

            const anomPercent = Math.round((ev.anomaly_score || 0) * 100);
            const timeClean = ev.timestamp ? ev.timestamp.replace('T', ' ').replace('Z', '') : '-';

            // Identifier column
            let identifier = '-';
            if (ev.trace_id) {
                identifier = `<span class="badge-id" style="font-size:0.7rem;">trace: ${ev.trace_id.slice(0, 10)}...</span>`;
            } else if (ev.deployment_id) {
                identifier = `<span class="badge-id" style="font-size:0.7rem;">deploy: ${ev.deployment_id}</span>`;
            } else if (ev.configuration_id) {
                identifier = `<span class="badge-id" style="font-size:0.7rem;">config: ${ev.configuration_id}</span>`;
            }

            return `
                <tr>
                    <td><span class="badge-id">${ev.id}</span></td>
                    <td class="small font-mono text-muted">${timeClean}</td>
                    <td><strong>${ev.service || ev.service_id}</strong></td>
                    <td><span class="badge" style="font-size: 0.7rem;">${ev.evidence_type}</span></td>
                    <td><span class="badge badge-severity ${sevClass}">${ev.severity}</span></td>
                    <td>
                        <div style="display: flex; align-items: center; gap: 6px;">
                            <div style="width: 45px; height: 5px; background: rgba(255,255,255,0.1); border-radius: 4px; overflow: hidden;">
                                <div style="width: ${anomPercent}%; height: 100%; background: ${anomPercent > 60 ? '#EF4444' : '#6366F1'};"></div>
                            </div>
                            <span class="small font-mono">${(ev.anomaly_score || 0).toFixed(2)}</span>
                        </div>
                    </td>
                    <td>${sourceBadge}</td>
                    <td style="max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                        ${ev.summary || ev.message || '-'}
                    </td>
                    <td>${identifier}</td>
                    <td>
                        <button class="btn btn-sm btn-secondary" onclick="EvidenceExplorer.showDetails('${ev.id}')">
                            Inspect
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    },

    showDetails(evidenceId) {
        let ev = this.allEvidence.find(e => e.id === evidenceId);
        if (!ev && typeof IncidentInvestigation !== 'undefined') {
            ev = IncidentInvestigation.incidentEvidenceMap.get(evidenceId);
        }

        if (!ev) {
            // Fetch dynamically from API
            fetch(`/api/evidence/${evidenceId}`, { credentials: 'same-origin' })
                .then(r => {
                    if (!r.ok) {
                        if (r.status === 403 && window.App) {
                            App.showToast('Access restricted: Raw telemetry details require Responder or Admin role.', 'warning');
                        }
                        throw new Error(`HTTP ${r.status}`);
                    }
                    return r.json();
                })
                .then(fetchedEv => {
                    if (fetchedEv && !fetchedEv.error) {
                        this.renderModalWithEvidence(fetchedEv);
                    }
                })
                .catch(err => console.warn('Evidence details fetch notice:', err.message));
            return;
        }

        this.renderModalWithEvidence(ev);
    },

    renderModalWithEvidence(ev) {
        document.getElementById('modal-evidence-id').textContent = `Evidence Record: ${ev.id}`;

        const isSynthetic = ev.source_type === 'SYNTHETIC_DEMO';
        const srcBadge = document.getElementById('modal-source-badge');
        srcBadge.textContent = isSynthetic ? 'SYNTHETIC_DEMO' : 'ORGANIZER TELEMETRY';
        srcBadge.className = isSynthetic ? 'badge badge-warning' : 'badge badge-success';

        document.getElementById('modal-service').textContent = ev.service || ev.service_id;
        document.getElementById('modal-type').textContent = ev.evidence_type;
        document.getElementById('modal-severity').textContent = ev.severity;
        document.getElementById('modal-severity').className = `badge badge-severity ${(ev.severity || 'info').toLowerCase()}`;
        document.getElementById('modal-anomaly-score').textContent = (ev.anomaly_score ?? 0).toFixed(2);
        document.getElementById('modal-timestamp').textContent = ev.timestamp || '-';
        document.getElementById('modal-summary').textContent = ev.summary || ev.message || 'No summary available.';

        // Render linkages
        const linkagesGrid = document.getElementById('modal-linkages-grid');
        const linkages = [];
        if (ev.trace_id) linkages.push(`Trace ID: ${ev.trace_id}`);
        if (ev.span_id) linkages.push(`Span ID: ${ev.span_id}`);
        if (ev.parent_span_id) linkages.push(`Parent Span: ${ev.parent_span_id}`);
        if (ev.request_id) linkages.push(`Request ID: ${ev.request_id}`);
        if (ev.deployment_id) linkages.push(`Deployment ID: ${ev.deployment_id}`);
        if (ev.configuration_id) linkages.push(`Configuration ID: ${ev.configuration_id}`);
        if (ev.metric_name) linkages.push(`Metric: ${ev.metric_name} = ${ev.metric_value}`);

        if (linkages.length > 0) {
            linkagesGrid.innerHTML = linkages.map(l => `<span class="linkage-pill">${l}</span>`).join('');
            document.getElementById('modal-linkages-section').classList.remove('hidden');
        } else {
            document.getElementById('modal-linkages-section').classList.add('hidden');
        }

        document.getElementById('modal-json').textContent = JSON.stringify(ev.details || {}, null, 2);
        document.getElementById('evidence-modal').classList.remove('hidden');
    }
};

window.EvidenceExplorer = EvidenceExplorer;
