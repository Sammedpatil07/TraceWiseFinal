/**
 * Incident Investigation View Module for AO-03 TraceWise
 * Strictly adheres to: "EVIDENCE BEFORE EXPLANATION"
 */

let scoreChartInstance = null;

const IncidentInvestigation = {
    currentIncidentId: null,
    currentIncident: null,
    incidentEvidenceMap: new Map(),
    candidatesList: [],
    selectedCandidate: null,
    timelineList: [],
    graphData: null,

    init() {
        this.bindEvents();
    },

    bindEvents() {
        const select = document.getElementById('select-incident');
        if (select) {
            select.addEventListener('change', (e) => {
                this.selectIncident(e.target.value);
            });
        }

        const runBtn = document.getElementById('btn-run-rca');
        if (runBtn) {
            runBtn.addEventListener('click', () => {
                if (this.currentIncidentId) {
                    this.executeRCA(this.currentIncidentId, true);
                }
            });
        }

        const runDeterministicBtn = document.getElementById('btn-run-rca-no-llm');
        if (runDeterministicBtn) {
            runDeterministicBtn.addEventListener('click', () => {
                if (this.currentIncidentId) {
                    this.executeRCA(this.currentIncidentId, false);
                }
            });
        }
    },

    async populateIncidentDropdown(selectedId = null) {
        const select = document.getElementById('select-incident');
        if (!select) return;

        try {
            const res = await fetch('/api/incidents', { credentials: 'same-origin' });
            if (!res.ok) {
                if (res.status === 401 && window.Auth) Auth.handleUnauthorized();
                select.innerHTML = '<option value="">Sign in required</option>';
                return;
            }
            const incidents = await res.json();
            if (!Array.isArray(incidents) || incidents.length === 0) {
                select.innerHTML = '<option value="">No incidents available</option>';
                this.currentIncidentId = null;
                return;
            }

            select.innerHTML = incidents.map(i => `
                <option value="${i.id}">${i.id} — ${i.title}</option>
            `).join('');

            const targetId = selectedId || this.currentIncidentId || incidents[0].id;
            select.value = targetId;
            await this.selectIncident(targetId);
        } catch (err) {
            console.error('Failed to populate incidents dropdown:', err);
        }
    },

    async selectIncident(incidentId) {
        if (!incidentId) return;
        this.currentIncidentId = incidentId;

        const select = document.getElementById('select-incident');
        if (select && select.value !== incidentId) {
            select.value = incidentId;
        }

        if (this.currentAbortController) {
            this.currentAbortController.abort();
        }
        this.currentAbortController = new AbortController();
        const signal = this.currentAbortController.signal;

        try {
            // Concurrent parallel retrieval of incident, evidence, topology, and RCA
            const [res, evRes, graphRes, rcaRes] = await Promise.all([
                fetch(`/api/incidents/${incidentId}`, { credentials: 'same-origin', signal }),
                fetch(`/api/incidents/${incidentId}/evidence`, { credentials: 'same-origin', signal }),
                fetch(`/api/incidents/${incidentId}/graph`, { credentials: 'same-origin', signal }),
                fetch(`/api/incidents/${incidentId}/rca`, { credentials: 'same-origin', signal })
            ]);

            if (signal.aborted) return;
            if (res.status === 401 || evRes.status === 401) {
                if (window.Auth) Auth.handleUnauthorized();
                return;
            }
            if (!res.ok) {
                App.showToast(`Incident ${incidentId} not found.`, 'error');
                return;
            }
            this.currentIncident = await res.json();

            let evList = [];
            if (evRes.ok) {
                const data = await evRes.json();
                if (Array.isArray(data)) evList = data;
            }
            this.incidentEvidenceMap.clear();
            evList.forEach(e => this.incidentEvidenceMap.set(e.id, e));
            this.renderIncidentBanner(this.currentIncident, evList.length);

            if (graphRes.ok) {
                this.graphData = await graphRes.json();
                this.renderTopologyDiagram();
            }

            if (rcaRes.ok) {
                const rcaData = await rcaRes.json();
                if (rcaData.run && rcaData.run.status === 'INSUFFICIENT_EVIDENCE') {
                    this.renderInsufficientEvidence({
                        reason: rcaData.run.llm_hypothesis || 'Available telemetry does not provide sufficient evidence to identify a reliable root cause.',
                        candidates: rcaData.candidates || [],
                        timeline: rcaData.timeline || []
                    });
                } else if (rcaData.candidates && rcaData.candidates.length > 0) {
                    this.renderRCAResults(rcaData);
                } else {
                    this.resetInvestigationViews();
                }
            } else {
                this.resetInvestigationViews();
            }
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.error('Error selecting incident:', err);
            App.showToast('Failed to load incident investigation details.', 'error');
        }
    },

    renderIncidentBanner(inc, telemetryCount) {
        document.getElementById('inv-incident-id').textContent = inc.id;
        document.getElementById('inv-incident-title').textContent = inc.title;
        document.getElementById('inv-incident-desc').textContent = inc.description || 'No description provided.';

        const sevBadge = document.getElementById('inv-incident-severity');
        sevBadge.textContent = inc.severity;
        sevBadge.className = `badge badge-severity ${(inc.severity || 'info').toLowerCase()}`;

        const statusBadge = document.getElementById('inv-incident-status');
        statusBadge.textContent = inc.status;
        statusBadge.className = `badge badge-status ${(inc.status || '').toLowerCase()}`;

        const invBadge = document.getElementById('inv-investigation-badge');
        const invStatus = inc.investigation_status || 'PENDING';
        if (invStatus === 'SUCCESS' || invStatus === 'ANALYZED') {
            invBadge.textContent = 'ANALYSIS COMPLETE';
            invBadge.className = 'badge badge-success';
        } else if (invStatus === 'INSUFFICIENT_EVIDENCE') {
            invBadge.textContent = 'INSUFFICIENT EVIDENCE';
            invBadge.className = 'badge badge-warning';
        } else {
            invBadge.textContent = 'PENDING ANALYSIS';
            invBadge.className = 'badge badge-info';
        }

        const affServicesContainer = document.getElementById('inv-affected-services');
        affServicesContainer.innerHTML = (inc.affected_services || []).map(s => `
            <span class="service-pill">${s}</span>
        `).join('') || '<span class="text-muted small">None specified</span>';

        document.getElementById('inv-time-started').textContent = inc.started_at ? inc.started_at.replace('T', ' ').replace('Z', ' UTC') : '-';
        document.getElementById('inv-duration').textContent = App.calculateDuration(inc.started_at, inc.resolved_at);
        document.getElementById('inv-telemetry-count').textContent = `${telemetryCount} record(s)`;
    },

    resetInvestigationViews() {
        document.getElementById('insufficient-evidence-banner').classList.add('hidden');
        document.getElementById('why-this-cause-card').classList.add('hidden');
        document.getElementById('candidates-container').innerHTML = `
            <div class="text-center text-muted py-4">Click "Run Root Cause Analysis" to correlate telemetry and identify candidate causes.</div>
        `;
        document.getElementById('candidates-count-badge').textContent = '0 candidates';
        document.getElementById('supporting-evidence-list').innerHTML = `<div class="text-muted small">No supporting evidence linked yet.</div>`;
        document.getElementById('contradicting-evidence-list').innerHTML = `<div class="text-muted small">No contradicting evidence observed.</div>`;
        document.getElementById('supporting-count-badge').textContent = '0 records';
        document.getElementById('contradicting-count-badge').textContent = '0 records';
        document.getElementById('timeline-container').innerHTML = `
            <div class="text-center text-muted py-4">Click "Run Root Cause Analysis" to generate the incident timeline.</div>
        `;
        document.getElementById('timeline-count-badge').textContent = '0 events';

        // Reset AI panel
        document.getElementById('ai-incident-summary').textContent = 'Run RCA to generate summary...';
        document.getElementById('ai-most-likely-cause').textContent = 'Awaiting analysis...';
        document.getElementById('ai-why-text').textContent = '';
        document.getElementById('ai-supporting-citations').innerHTML = '<span class="text-muted small">None cited</span>';
        document.getElementById('ai-contradicting-citations').innerHTML = '<span class="text-muted small">None cited</span>';
        document.getElementById('ai-alternative-causes').innerHTML = '<div class="text-muted small">No alternatives evaluated yet.</div>';
        document.getElementById('ai-timeline-interp').textContent = '-';
        document.getElementById('ai-unknowns').textContent = '-';

        if (scoreChartInstance) {
            scoreChartInstance.destroy();
            scoreChartInstance = null;
        }

        this.renderTopologyDiagram();
    },

    async executeRCA(incidentId, triggerLLM = true) {
        if (this.isAnalyzing) return;
        this.isAnalyzing = true;
        const runBtn = document.getElementById('btn-run-rca');
        const runDetBtn = document.getElementById('btn-run-rca-no-llm');
        if (runBtn) { runBtn.disabled = true; runBtn.textContent = 'Analyzing...'; }
        if (runDetBtn) { runDetBtn.disabled = true; }

        App.showToast('Executing deterministic Root Cause Analysis...', 'info');
        try {
            const res = await fetch(`/api/incidents/${incidentId}/analyze`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ trigger_llm: triggerLLM })
            });

            if (!res.ok) {
                if (res.status === 401 && window.Auth) Auth.handleUnauthorized();
                const errData = await res.json().catch(() => ({}));
                const errMsg = errData.error || errData.message || `Server returned HTTP ${res.status}`;
                throw new Error(errMsg);
            }

            const data = await res.json();

            // Refresh cached evidence in case new records were parsed
            const evRes = await fetch(`/api/incidents/${incidentId}/evidence`, { credentials: 'same-origin' });
            if (evRes.ok) {
                const evList = await evRes.json();
                if (Array.isArray(evList)) {
                    this.incidentEvidenceMap.clear();
                    evList.forEach(e => this.incidentEvidenceMap.set(e.id, e));
                }
            }

            // Reload topology to update suspected root highlights
            await this.loadIncidentGraph(incidentId);

            if (data.status === 'INSUFFICIENT_EVIDENCE' || data.is_insufficient_evidence) {
                this.renderInsufficientEvidence(data);
                App.showToast('Analysis completed: Insufficient evidence.', 'warning');
            } else {
                this.renderRCAResults({
                    top_candidate: data.top_candidate,
                    candidates: data.ranked_candidates,
                    timeline: data.timeline,
                    run: {
                        llm_summary: data.llm_hypothesis,
                        llm_status: data.llm_hypothesis ? 'AVAILABLE' : 'DISABLED',
                        status: data.status,
                    }
                });
                App.showToast('RCA completed successfully!', 'success');
            }

            // Update header banner badge
            const invBadge = document.getElementById('inv-investigation-badge');
            if (data.status === 'INSUFFICIENT_EVIDENCE') {
                invBadge.textContent = 'INSUFFICIENT EVIDENCE';
                invBadge.className = 'badge badge-warning';
            } else {
                invBadge.textContent = 'ANALYSIS COMPLETE';
                invBadge.className = 'badge badge-success';
            }

            // Refresh dashboard counts
            App.loadStats();
        } catch (err) {
            console.error('RCA failed:', err);
            App.showToast('Failed to run RCA: ' + err.message, 'error');
        } finally {
            this.isAnalyzing = false;
            const runBtn = document.getElementById('btn-run-rca');
            const runDetBtn = document.getElementById('btn-run-rca-no-llm');
            if (runBtn) { runBtn.disabled = false; runBtn.textContent = 'Run Root Cause Analysis'; }
            if (runDetBtn) { runDetBtn.disabled = false; }
        }
    },

    renderInsufficientEvidence(data) {
        const insBanner = document.getElementById('insufficient-evidence-banner');
        insBanner.classList.remove('hidden');

        const evidenceCount = this.incidentEvidenceMap.size;
        document.getElementById('insufficient-available-text').textContent =
            `${evidenceCount} normalized telemetry record(s) available for incident '${this.currentIncidentId}'.`;

        document.getElementById('insufficient-missing-text').textContent =
            "No correlated configuration changes, high-severity deployments, or sustained cross-service metric anomalies above threshold.";

        document.getElementById('insufficient-reason-text').textContent =
            data.reason || 'Top candidate Evidence Score is below the 0.35 threshold. Telemetry is sparse or uncoordinated.';

        // Render inconclusive candidates if any were produced
        const candidates = data.candidates || data.ranked_candidates || [];
        const insecCandSection = document.getElementById('insufficient-candidates-section');
        const insecCandList = document.getElementById('insufficient-candidates-list');

        if (candidates.length > 0) {
            insecCandSection.classList.remove('hidden');
            insecCandList.innerHTML = candidates.map(c => `
                <span class="service-pill" style="border-color: rgba(245, 158, 11, 0.4); background: rgba(245, 158, 11, 0.1);">
                    ${c.title} (Score: ${(c.evidence_score || 0).toFixed(2)})
                </span>
            `).join('');
        } else {
            insecCandSection.classList.add('hidden');
        }

        // Render timeline if available
        const timeline = data.timeline || [];
        this.renderTimeline(timeline);

        // Hide Why This Cause and Reset Candidates Container
        document.getElementById('why-this-cause-card').classList.add('hidden');
        document.getElementById('candidates-container').innerHTML = `
            <div class="text-center text-warning py-3">
                <strong>UNKNOWN / INSUFFICIENT EVIDENCE</strong>
                <p class="text-muted small mt-1">Telemetry lacks causal linkage to establish a verified root cause.</p>
            </div>
        `;
        document.getElementById('candidates-count-badge').textContent = '0 candidates';
        document.getElementById('supporting-evidence-list').innerHTML = `<div class="text-muted small">No verified supporting evidence.</div>`;
        document.getElementById('contradicting-evidence-list').innerHTML = `<div class="text-muted small">No contradicting evidence observed.</div>`;
        document.getElementById('supporting-count-badge').textContent = '0 records';
        document.getElementById('contradicting-count-badge').textContent = '0 records';

        // Render AI explanation if present or default
        this.renderAIHypothesis({
            incident_summary: this.currentIncident?.description || '',
            most_likely_cause: 'UNKNOWN / INSUFFICIENT EVIDENCE',
            confidence_explanation: data.reason || 'Telemetry score below 0.35 threshold.',
            supporting_evidence: [],
            contradicting_evidence: [],
            alternative_causes: [],
            timeline_interpretation: 'Telemetry blips occurred without sustained propagation.',
            unknowns: 'Insufficient telemetry density across dependencies.',
            hypothesis_status: 'INCONCLUSIVE'
        });
    },

    renderRCAResults(data) {
        document.getElementById('insufficient-evidence-banner').classList.add('hidden');

        this.candidatesList = data.candidates || (data.ranked_candidates || []);
        const topCandidate = data.top_candidate || this.candidatesList[0];
        this.timelineList = data.timeline || [];

        // 1. Render Ranked Candidates
        this.renderCandidates(this.candidatesList, topCandidate?.id);

        // 2. Select and Render Top Candidate ("WHY THIS CAUSE?", Supporting, Contradicting)
        if (topCandidate) {
            this.selectCandidate(topCandidate);
        }

        // 3. Render Timeline
        this.renderTimeline(this.timelineList);

        // 4. Render Topology
        this.renderTopologyDiagram();

        // 5. Render AI Hypothesis (STRICTLY AFTER deterministic results)
        const hypothesis = data.run?.llm_summary;
        this.renderAIHypothesis(hypothesis, topCandidate);
    },

    renderCandidates(candidates, selectedCandidateId) {
        const container = document.getElementById('candidates-container');
        const badge = document.getElementById('candidates-count-badge');
        if (!container) return;

        badge.textContent = `${candidates.length} candidate(s)`;

        if (candidates.length === 0) {
            container.innerHTML = `<div class="text-center text-muted py-3">No candidate causes generated.</div>`;
            return;
        }

        container.innerHTML = candidates.map(c => {
            const isSelected = c.id === selectedCandidateId;
            const scorePercent = Math.round((c.evidence_score || 0) * 100);
            const scoreClass = (c.evidence_score >= 0.7) ? '#10B981' : ((c.evidence_score >= 0.4) ? '#F59E0B' : '#6B7280');
            const supportingCount = (c.supporting_evidence_ids || []).length;
            const contradictingCount = (c.contradicting_evidence_ids || []).length;

            return `
                <div class="candidate-item ${isSelected ? 'top-ranked active' : ''}" 
                     id="cand-card-${c.id}" 
                     onclick="IncidentInvestigation.onCandidateClicked('${c.id}')"
                     style="cursor: pointer;">
                    <div class="candidate-header">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span class="candidate-rank-badge">#${c.rank}</span>
                            <span class="badge" style="background: rgba(99,102,241,0.2); color:#A5B4FC;">${c.candidate_type}</span>
                            <strong style="color: #FFFFFF;">${c.service_id || c.service}</strong>
                        </div>
                        <span class="badge ${c.rank === 1 ? 'stat-badge success' : 'stat-badge info'}">
                            ${c.rank === 1 ? 'TOP CAUSE' : 'ALTERNATIVE'}
                        </span>
                    </div>

                    <div class="candidate-title" style="margin-top: 6px;">${c.title}</div>
                    <div class="candidate-desc">${c.description}</div>

                    <!-- Progress Bar for Evidence Score -->
                    <div class="score-progress-bar-container" style="margin-top: 8px;">
                        <span style="color: var(--text-secondary); width: 120px; font-size: 0.75rem;">Evidence Score:</span>
                        <div class="score-progress-bar" style="flex: 1;">
                            <div class="score-fill" style="width: ${scorePercent}%; background: ${scoreClass};"></div>
                        </div>
                        <span style="font-weight: 700; color: #FFFFFF; font-family: var(--font-mono); font-size: 0.85rem; width: 45px; text-align: right;">
                            ${(c.evidence_score || 0).toFixed(2)}
                        </span>
                    </div>

                    <!-- Counts of Supporting & Contradicting Evidence -->
                    <div class="candidate-evidence-counts mt-2" style="display: flex; gap: 1rem; font-size: 0.75rem;">
                        <span class="text-success">&#10003; ${supportingCount} supporting record(s)</span>
                        <span class="${contradictingCount > 0 ? 'text-warning' : 'text-muted'}">
                            &#9888; ${contradictingCount} contradiction(s)
                        </span>
                    </div>
                </div>
            `;
        }).join('');
    },

    onCandidateClicked(candidateId) {
        const candidate = this.candidatesList.find(c => c.id === candidateId);
        if (!candidate) return;

        // Highlight selected candidate card
        document.querySelectorAll('.candidate-item').forEach(el => el.classList.remove('active'));
        const activeEl = document.getElementById(`cand-card-${candidateId}`);
        if (activeEl) activeEl.classList.add('active');

        this.selectCandidate(candidate);
    },

    selectCandidate(candidate) {
        this.selectedCandidate = candidate;

        // 1. Render "WHY THIS CAUSE?"
        this.renderWhyThisCause(candidate);

        // 2. Render Supporting Evidence
        this.renderSupportingEvidence(candidate);

        // 3. Render Contradicting Evidence
        this.renderContradictingEvidence(candidate);

        // 4. Update topology highlighting suspected root
        if (candidate.service_id) {
            this.updateTopologyRoot(candidate.service_id);
        }
    },

    renderWhyThisCause(candidate) {
        const card = document.getElementById('why-this-cause-card');
        card.classList.remove('hidden');

        document.getElementById('why-cause-title').textContent = `WHY THIS CAUSE? — #${candidate.rank} ${candidate.title}`;
        document.getElementById('why-cause-subtitle').textContent = `Multi-factor score attribution for '${candidate.service_id}'`;
        document.getElementById('why-cause-score-badge').textContent = `Evidence Score: ${(candidate.evidence_score || 0).toFixed(3)}`;

        const factors = candidate.contributing_factors || candidate.scoring_breakdown || {};

        // Prepare labels & values
        const factorDefinitions = [
            { key: 'temporal_precedence', label: 'Temporal Precedence' },
            { key: 'anomaly_magnitude', label: 'Anomaly Magnitude' },
            { key: 'error_correlation', label: 'Error Correlation' },
            { key: 'trace_correlation', label: 'Trace Correlation' },
            { key: 'deployment_proximity', label: 'Deployment Proximity' },
            { key: 'configuration_proximity', label: 'Configuration Proximity' },
            { key: 'blast_radius', label: 'Blast Radius' },
            { key: 'dependency_relevance', label: 'Dependency Relevance' },
        ];

        // Filter to factors actually present in the data
        const activeFactors = factorDefinitions.filter(f => factors[f.key] !== undefined);
        const chartLabels = activeFactors.map(f => f.label);
        const chartValues = activeFactors.map(f => factors[f.key]);

        // Render Chart.js
        const ctx = document.getElementById('scoreChart');
        if (ctx) {
            if (scoreChartInstance) {
                scoreChartInstance.destroy();
            }
            scoreChartInstance = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: chartLabels,
                    datasets: [{
                        label: 'Factor Score',
                        data: chartValues,
                        backgroundColor: chartValues.map(v => v >= 0.7 ? 'rgba(255, 97, 41, 0.85)' : (v >= 0.4 ? 'rgba(255, 113, 69, 0.75)' : 'rgba(255, 255, 255, 0.18)')),
                        borderColor: chartValues.map(v => v >= 0.7 ? '#FF6129' : (v >= 0.4 ? '#FF7145' : 'rgba(255, 255, 255, 0.35)')),
                        borderWidth: 1,
                        borderRadius: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 1.0,
                            grid: { color: 'rgba(255, 255, 255, 0.05)' },
                            ticks: { color: '#9CA3AF', font: { size: 10 } }
                        },
                        x: {
                            grid: { display: false },
                            ticks: { color: '#D1D5DB', font: { size: 10 } }
                        }
                    },
                    plugins: {
                        legend: { display: false }
                    }
                }
            });
        }

        // Render Checklist of Contributing Factors
        const checklist = document.getElementById('scoring-factors-list');
        checklist.innerHTML = activeFactors.map(f => {
            const val = factors[f.key] || 0;
            const isSignificant = val > 0.3;
            return `
                <div class="factor-check-item ${isSignificant ? 'active' : ''}">
                    <div style="display: flex; align-items: center; gap: 6px;">
                        <span class="${isSignificant ? 'text-success' : 'text-muted'}">${isSignificant ? '&#10003;' : '&#8226;'}</span>
                        <span class="factor-check-name">${f.label}</span>
                    </div>
                    <span class="factor-check-val">${val.toFixed(2)}</span>
                </div>
            `;
        }).join('');
    },

    renderSupportingEvidence(candidate) {
        const container = document.getElementById('supporting-evidence-list');
        const badge = document.getElementById('supporting-count-badge');
        const supportingIds = candidate.supporting_evidence_ids || [];

        badge.textContent = `${supportingIds.length} record(s)`;

        if (supportingIds.length === 0) {
            container.innerHTML = `<div class="text-muted small py-2">No verified supporting evidence.</div>`;
            return;
        }

        container.innerHTML = supportingIds.map(eid => {
            const ev = this.incidentEvidenceMap.get(eid) || {
                id: eid,
                service: candidate.service_id,
                evidence_type: 'TELEMETRY',
                severity: 'INFO',
                timestamp: '-',
                summary: 'Verified ground-truth evidence record',
                details: {}
            };

            return this.renderExpandableEvidenceCard(ev, 'success');
        }).join('');
    },

    renderContradictingEvidence(candidate) {
        const container = document.getElementById('contradicting-evidence-list');
        const badge = document.getElementById('contradicting-count-badge');
        const contradictingIds = candidate.contradicting_evidence_ids || [];

        badge.textContent = `${contradictingIds.length} record(s)`;

        if (contradictingIds.length === 0) {
            container.innerHTML = `
                <div class="text-muted small py-2">
                    No contradicting evidence found in the supplied telemetry.
                </div>
            `;
            return;
        }

        container.innerHTML = contradictingIds.map(eid => {
            const ev = this.incidentEvidenceMap.get(eid) || {
                id: eid,
                service: candidate.service_id,
                evidence_type: 'TELEMETRY',
                severity: 'INFO',
                timestamp: '-',
                summary: 'Telemetry diverges from candidate expectation',
                details: {}
            };

            return this.renderExpandableEvidenceCard(ev, 'warning');
        }).join('');
    },

    renderExpandableEvidenceCard(ev, variant = 'success') {
        const sevClass = (ev.severity || 'info').toLowerCase();
        const timeClean = ev.timestamp ? ev.timestamp.replace('T', ' ').replace('Z', '') : '-';
        const isSynthetic = ev.source_type === 'SYNTHETIC_DEMO';

        return `
            <div class="evidence-card-expandable" id="ev-card-${ev.id}">
                <div class="evidence-summary-row" onclick="IncidentInvestigation.toggleEvidenceCard('${ev.id}')">
                    <div class="evidence-summary-main">
                        <div class="evidence-summary-header">
                            <span class="badge-id" style="font-size: 0.75rem;">${ev.id}</span>
                            <span class="badge badge-severity ${sevClass}">${ev.severity}</span>
                            <span class="badge" style="font-size: 0.68rem;">${ev.evidence_type}</span>
                            <strong style="color: #FFFFFF; font-size: 0.8rem;">${ev.service || ev.service_id}</strong>
                            <span class="small font-mono text-muted" style="margin-left: auto;">${timeClean}</span>
                        </div>
                        <div class="evidence-summary-text">${ev.summary || ev.message || 'Evidence details'}</div>
                    </div>
                    <button class="evidence-toggle-btn" type="button" aria-label="Expand details">
                        Details &#9662;
                    </button>
                </div>
                <div class="evidence-drawer">
                    <!-- CLAIM -> EVIDENCE -> SOURCE Proof Chain -->
                    <div class="proof-chain-container" style="margin-bottom: 0.85rem; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,97,41,0.25); border-radius: var(--radius-sm); padding: 0.75rem;">
                        <div style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.78rem;">
                            <span class="badge" style="background: rgba(255,97,41,0.2); color:#FF7145; font-size: 0.65rem;">CLAIM</span>
                            <strong style="color: #FFFFFF;">${this.selectedCandidate?.title || 'Root Cause Candidate'}</strong>
                        </div>
                        <div style="color: var(--text-muted); font-size: 0.72rem; margin: 0.25rem 0 0.25rem 1.4rem;">&#8659; proven by verified evidence &#8659;</div>
                        <div style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.78rem;">
                            <span class="badge" style="background: rgba(16,185,129,0.3); color:#34D399; font-size: 0.65rem;">EVIDENCE</span>
                            <span style="color: #D1D5DB;">Record <code>${ev.id}</code> on service <strong>${ev.service || ev.service_id}</strong> (${ev.evidence_type}, Anomaly: ${(ev.anomaly_score ?? 0).toFixed(2)})</span>
                        </div>
                        <div style="color: var(--text-muted); font-size: 0.72rem; margin: 0.25rem 0 0.25rem 1.4rem;">&#8659; derived from telemetry source &#8659;</div>
                        <div style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.78rem;">
                            <span class="badge" style="background: rgba(245,158,11,0.3); color:#FBBF24; font-size: 0.65rem;">SOURCE</span>
                            <span style="color: #9CA3AF;">${isSynthetic ? 'SYNTHETIC_DEMO (Isolated Test Fixture)' : 'ORGANIZER TELEMETRY (Production Telemetry Ingestion)'} ${ev.source_file ? '&bull; ' + ev.source_file : ''}</span>
                        </div>
                    </div>

                    <div class="evidence-drawer-grid">
                        <div class="drawer-field">
                            <span class="drawer-label">Anomaly Score:</span>
                            <span class="drawer-val">${(ev.anomaly_score ?? 0).toFixed(2)}</span>
                        </div>
                        <div class="drawer-field">
                            <span class="drawer-label">Source Tag:</span>
                            <span class="drawer-val">${isSynthetic ? 'SYNTHETIC_DEMO' : 'ORGANIZER'}</span>
                        </div>
                        ${ev.trace_id ? `
                            <div class="drawer-field">
                                <span class="drawer-label">Trace ID:</span>
                                <span class="drawer-val">${ev.trace_id}</span>
                            </div>
                        ` : ''}
                        ${ev.deployment_id ? `
                            <div class="drawer-field">
                                <span class="drawer-label">Deployment ID:</span>
                                <span class="drawer-val">${ev.deployment_id}</span>
                            </div>
                        ` : ''}
                        ${ev.configuration_id ? `
                            <div class="drawer-field">
                                <span class="drawer-label">Configuration ID:</span>
                                <span class="drawer-val">${ev.configuration_id}</span>
                            </div>
                        ` : ''}
                    </div>
                    <div>
                        <span class="drawer-label">Payload & Attributes:</span>
                        <pre class="code-block" style="margin-top: 4px; max-height: 180px;">${JSON.stringify(ev.details || {}, null, 2)}</pre>
                    </div>
                </div>
            </div>
        `;
    },

    toggleEvidenceCard(evidenceId) {
        const card = document.getElementById(`ev-card-${evidenceId}`);
        if (!card) return;
        const isOpen = card.classList.contains('open');
        card.classList.toggle('open');
        const btn = card.querySelector('.evidence-toggle-btn');
        if (btn) {
            btn.innerHTML = isOpen ? 'Details &#9662;' : 'Collapse &#9652;';
        }
    },

    renderTimeline(timeline) {
        const container = document.getElementById('timeline-container');
        const badge = document.getElementById('timeline-count-badge');
        if (!container) return;

        badge.textContent = `${timeline.length} event(s)`;

        if (timeline.length === 0) {
            container.innerHTML = `<div class="text-center text-muted py-3">No chronological timeline events recorded.</div>`;
            return;
        }

        container.innerHTML = timeline.map((t, idx) => {
            const cleanTime = t.timestamp ? t.timestamp.replace('T', ' ').replace('Z', '') : '-';
            const eventType = t.event_type || 'EVENT';

            return `
                <div class="timeline-node" id="tl-node-${idx}" onclick="IncidentInvestigation.onTimelineEventClicked('${t.evidence_id}', ${idx})">
                    <div class="timeline-dot ${eventType}"></div>
                    <div class="timeline-content">
                        <div class="timeline-meta">
                            <span class="font-mono text-muted">${cleanTime}</span>
                            <span class="badge" style="font-size: 0.65rem;">${eventType}</span>
                            <strong style="color: #FF7145;">${t.service_id || t.service}</strong>
                        </div>
                        <div class="timeline-summary">${t.summary || t.event}</div>
                        <div style="margin-top: 6px;">
                            <span class="badge-id" style="font-size: 0.7rem;">
                                Evidence: ${t.evidence_id} &#10138; Inspect
                            </span>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    },

    onTimelineEventClicked(evidenceId, nodeIndex) {
        document.querySelectorAll('.timeline-node').forEach(n => n.classList.remove('highlighted'));
        const node = document.getElementById(`tl-node-${nodeIndex}`);
        if (node) node.classList.add('highlighted');

        // Show modal for evidence
        EvidenceExplorer.showDetails(evidenceId);
    },

    async loadIncidentGraph(incidentId) {
        try {
            const res = await fetch(`/api/incidents/${incidentId}/graph`, { credentials: 'same-origin' });
            if (res.ok) {
                this.graphData = await res.json();
            }
        } catch (err) {
            console.error('Failed to load incident graph:', err);
        }
    },

    updateTopologyRoot(rootServiceId) {
        if (!this.graphData || !this.graphData.nodes) return;
        this.graphData.suspected_root = rootServiceId;
        this.graphData.nodes.forEach(n => {
            n.is_root = (n.id === rootServiceId);
        });
        this.renderTopologyDiagram();
    },

    onServiceNodeClicked(serviceId) {
        document.querySelectorAll('.svg-node').forEach(el => el.classList.remove('selected-node'));
        const clickedNode = document.getElementById(`topo-node-${serviceId}`);
        if (clickedNode) clickedNode.classList.add('selected-node');

        const relatedEv = Array.from(this.incidentEvidenceMap.values()).filter(
            e => (e.service || e.service_id) === serviceId
        );

        const candidate = this.candidatesList.find(c => (c.service_id || c.service) === serviceId);
        if (candidate) {
            this.onCandidateClicked(candidate.id);
            App.showToast(`Selected candidate #${candidate.rank} for '${serviceId}' (${relatedEv.length} telemetry records).`, 'info');
        } else if (relatedEv.length > 0) {
            App.showToast(`Service '${serviceId}': ${relatedEv.length} telemetry record(s) found.`, 'info');
            EvidenceExplorer.showDetails(relatedEv[0].id);
        } else {
            App.showToast(`Service '${serviceId}': No telemetry anomalies recorded for this incident.`, 'info');
        }
    },

    renderTopologyDiagram() {
        const container = document.getElementById('topology-container');
        const badge = document.getElementById('topology-nodes-badge');
        if (!container) return;

        if (!this.graphData || !this.graphData.nodes || this.graphData.nodes.length === 0) {
            container.innerHTML = `<div class="text-center text-muted py-4">Dependency information unavailable for this incident.</div>`;
            badge.textContent = '0 nodes';
            return;
        }

        const nodes = this.graphData.nodes;
        const edges = this.graphData.edges || [];
        badge.textContent = `${nodes.length} nodes`;

        // SVG Dimensions
        const width = container.clientWidth || 460;
        const height = Math.max(300, nodes.length * 45);

        // Group nodes by tier or assign layered positions
        const tiers = { ingress: [], core: [], security: [], worker: [], other: [] };
        nodes.forEach(n => {
            const t = n.tier || 'other';
            if (tiers[t]) tiers[t].push(n);
            else tiers.other.push(n);
        });

        const activeTiers = Object.keys(tiers).filter(k => tiers[k].length > 0);
        const nodePositions = new Map();

        activeTiers.forEach((tierName, tierIdx) => {
            const tierNodes = tiers[tierName];
            const y = ((tierIdx + 1) / (activeTiers.length + 1)) * height;
            tierNodes.forEach((n, idx) => {
                const x = ((idx + 1) / (tierNodes.length + 1)) * width;
                nodePositions.set(n.id, { x, y, node: n });
            });
        });

        // Generate Edge SVG Paths
        let edgeSvg = '';
        edges.forEach(e => {
            const p1 = nodePositions.get(e.source);
            const p2 = nodePositions.get(e.target);
            if (p1 && p2) {
                const midY = (p1.y + p2.y) / 2;
                edgeSvg += `
                    <path d="M ${p1.x} ${p1.y} C ${p1.x} ${midY}, ${p2.x} ${midY}, ${p2.x} ${p2.y}" 
                          stroke="rgba(255, 97, 41, 0.45)" 
                          stroke-width="${e.critical ? 2 : 1}" 
                          fill="none" 
                          marker-end="url(#topo-arrow)"/>
                `;
            }
        });

        // Generate Node SVG Elements
        let nodeSvg = '';
        nodes.forEach(n => {
            const pos = nodePositions.get(n.id);
            if (!pos) return;

            let fillColor = 'rgba(24, 21, 20, 0.9)';
            let strokeColor = 'rgba(255, 255, 255, 0.12)';
            let roleBadge = '';

            if (n.is_root) {
                fillColor = 'rgba(252, 59, 0, 0.22)';
                strokeColor = '#FC3B00';
                roleBadge = '<span style="color:#FC3B00; font-size:10px;">★ ROOT CAUSE</span>';
            } else if (n.is_affected) {
                fillColor = 'rgba(255, 113, 69, 0.18)';
                strokeColor = '#FF7145';
                roleBadge = '<span style="color:#FF7145; font-size:10px;">▲ AFFECTED</span>';
            } else if (n.is_upstream) {
                fillColor = 'rgba(255, 97, 41, 0.14)';
                strokeColor = '#FF6129';
                roleBadge = '<span style="color:#FF6129; font-size:10px;">↑ CALLER</span>';
            }

            nodeSvg += `
                <g class="svg-node" id="topo-node-${n.id}" onclick="IncidentInvestigation.onServiceNodeClicked('${n.id}')" transform="translate(${pos.x}, ${pos.y})" style="cursor: pointer;">
                    <rect x="-65" y="-22" width="130" height="44" rx="22" 
                          fill="${fillColor}" stroke="${strokeColor}" stroke-width="${n.is_root ? 2.5 : 1.5}" />
                    <text x="0" y="-3" text-anchor="middle" fill="#FFFFFF" font-size="12" font-weight="600" font-family="var(--font-sans)">
                        ${n.label || n.id}
                    </text>
                    <text x="0" y="13" text-anchor="middle" fill="${n.is_root ? '#FC3B00' : (n.is_affected ? '#FF7145' : '#71717A')}" font-size="9" font-family="var(--font-mono)">
                        ${n.is_root ? '★ SUSPECTED ROOT' : (n.is_affected ? '▲ AFFECTED' : n.id)}
                    </text>
                </g>
            `;
        });

        container.innerHTML = `
            <svg class="topo-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet">
                <defs>
                    <marker id="topo-arrow" viewBox="0 0 10 10" refX="28" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                        <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(255, 97, 41, 0.75)" />
                    </marker>
                </defs>
                ${edgeSvg}
                ${nodeSvg}
            </svg>
        `;
    },

    renderAIHypothesis(hypothesis, topCandidate) {
        const noticeBox = document.getElementById('ai-unavailable-notice');
        const contentBody = document.getElementById('ai-content-body');
        const statusBadge = document.getElementById('ai-status-badge');

        if (!hypothesis) {
            noticeBox.classList.remove('hidden');
            contentBody.classList.add('hidden');
            statusBadge.textContent = 'OFFLINE';
            statusBadge.className = 'badge badge-warning';
            return;
        }

        noticeBox.classList.add('hidden');
        contentBody.classList.remove('hidden');

        statusBadge.textContent = hypothesis.hypothesis_status || 'HYPOTHESIS';
        statusBadge.className = 'badge badge-info';

        document.getElementById('ai-incident-summary').textContent = hypothesis.incident_summary || this.currentIncident?.description || '';
        document.getElementById('ai-most-likely-cause').textContent = hypothesis.most_likely_cause || (topCandidate ? topCandidate.title : 'Unknown');
        document.getElementById('ai-why-text').textContent = hypothesis.confidence_explanation || (topCandidate ? topCandidate.description : '');

        // Clickable Supporting Evidence Citations
        const supportingCitations = hypothesis.supporting_evidence || [];
        const supCitContainer = document.getElementById('ai-supporting-citations');
        if (supportingCitations.length === 0) {
            supCitContainer.innerHTML = '<span class="text-muted small">None cited in hypothesis</span>';
        } else {
            supCitContainer.innerHTML = supportingCitations.map(eid => `
                <span class="badge-id" style="cursor: pointer; background: rgba(16, 185, 129, 0.15); border-color: rgba(16, 185, 129, 0.4);" 
                      onclick="EvidenceExplorer.showDetails('${eid}')">
                    &#10003; ${eid}
                </span>
            `).join('');
        }

        // Clickable Contradicting Evidence Citations
        const contradictingCitations = hypothesis.contradicting_evidence || [];
        const conCitContainer = document.getElementById('ai-contradicting-citations');
        if (contradictingCitations.length === 0) {
            conCitContainer.innerHTML = '<span class="text-muted small">None cited in hypothesis</span>';
        } else {
            conCitContainer.innerHTML = contradictingCitations.map(eid => `
                <span class="badge-id" style="cursor: pointer; background: rgba(245, 158, 11, 0.15); border-color: rgba(245, 158, 11, 0.4);" 
                      onclick="EvidenceExplorer.showDetails('${eid}')">
                    &#9888; ${eid}
                </span>
            `).join('');
        }

        // Alternatives Considered
        const alternatives = hypothesis.alternative_causes || [];
        const altContainer = document.getElementById('ai-alternative-causes');
        if (alternatives.length === 0) {
            altContainer.innerHTML = '<div class="text-muted small">No alternative causes rejected.</div>';
        } else {
            altContainer.innerHTML = alternatives.map(a => `
                <div class="ai-alternative-item">
                    <strong>${a.cause || a.service || 'Alternative'}</strong>: ${a.reason_rejected || 'Lower causal evidence score.'}
                </div>
            `).join('');
        }

        // Timeline interpretation & Unknowns
        document.getElementById('ai-timeline-interp').textContent = hypothesis.timeline_interpretation || 'Events followed causal topological sequence.';
        document.getElementById('ai-unknowns').textContent = hypothesis.unknowns || 'None recorded.';
    }
};

window.IncidentInvestigation = IncidentInvestigation;
