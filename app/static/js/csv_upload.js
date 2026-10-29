/**
 * TraceWise AO-03 CSV Log Upload, Validation & Ingestion Module
 * End-to-end two-step Preview -> Validation -> Commit workflow
 */

const CsvUpload = {
    selectedFile: null,
    currentIncidentId: null,
    previewReport: null,
    isProcessing: false,

    init() {
        this.bindEvents();
    },

    bindEvents() {
        // Modal trigger buttons
        const openBtnInv = document.getElementById('btn-open-csv-upload');
        if (openBtnInv) {
            openBtnInv.addEventListener('click', () => {
                const incId = (window.IncidentInvestigation && IncidentInvestigation.currentIncidentId) || 'INC-2026-001';
                this.showModal(incId);
            });
        }

        const openBtnExp = document.getElementById('btn-explorer-csv-upload');
        if (openBtnExp) {
            openBtnExp.addEventListener('click', () => {
                const incId = (window.IncidentInvestigation && IncidentInvestigation.currentIncidentId) || 'INC-2026-001';
                this.showModal(incId);
            });
        }

        // Close / Cancel modal
        const closeBtn = document.getElementById('btn-close-csv-modal');
        if (closeBtn) closeBtn.addEventListener('click', () => this.hideModal());

        const cancelBtn = document.getElementById('btn-cancel-csv-modal');
        if (cancelBtn) cancelBtn.addEventListener('click', () => this.hideModal());

        // Target incident dropdown
        const incSelect = document.getElementById('csv-incident-select');
        if (incSelect) {
            incSelect.addEventListener('change', (e) => {
                this.currentIncidentId = e.target.value;
                const badge = document.getElementById('csv-target-incident-badge');
                if (badge) badge.textContent = this.currentIncidentId;
                if (this.selectedFile) {
                    this.validateAndPreview();
                }
            });
        }

        // Dropzone & File Input
        const dropzone = document.getElementById('csv-dropzone');
        const fileInput = document.getElementById('csv-file-input');

        if (dropzone && fileInput) {
            dropzone.addEventListener('click', () => fileInput.click());

            dropzone.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.add('dragover');
            });

            dropzone.addEventListener('dragleave', (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.remove('dragover');
            });

            dropzone.addEventListener('drop', (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.remove('dragover');
                if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                    this.handleFileSelect(e.dataTransfer.files[0]);
                }
            });

            fileInput.addEventListener('change', (e) => {
                if (e.target.files && e.target.files.length > 0) {
                    this.handleFileSelect(e.target.files[0]);
                }
            });
        }

        // File remove / replace buttons
        const removeFileBtn = document.getElementById('btn-remove-csv-file');
        if (removeFileBtn) {
            removeFileBtn.addEventListener('click', () => this.resetFileSelection());
        }

        const replaceFileBtn = document.getElementById('btn-change-csv-file');
        if (replaceFileBtn && fileInput) {
            replaceFileBtn.addEventListener('click', () => fileInput.click());
        }

        // Preview button
        const previewBtn = document.getElementById('btn-preview-csv-action');
        if (previewBtn) {
            previewBtn.addEventListener('click', () => this.validateAndPreview());
        }

        // Commit button
        const commitBtn = document.getElementById('btn-confirm-commit-csv');
        if (commitBtn) {
            commitBtn.addEventListener('click', () => this.commitUpload());
        }

        // Post-success action buttons
        const runRcaBtn = document.getElementById('btn-success-run-rca');
        if (runRcaBtn) {
            runRcaBtn.addEventListener('click', () => this.runRcaPostImport());
        }

        const successCloseBtn = document.getElementById('btn-success-close-modal');
        if (successCloseBtn) {
            successCloseBtn.addEventListener('click', () => {
                this.hideModal();
                if (window.AppNavigation) {
                    AppNavigation.navigate('tab-explorer', { pushState: true });
                }
            });
        }

        const resetUploadBtn = document.getElementById('btn-reset-csv-upload');
        if (resetUploadBtn) {
            resetUploadBtn.addEventListener('click', () => this.resetFileSelection());
        }
    },

    async showModal(incidentId = null) {
        // Enforce RBAC in UI
        const currentUser = (window.Auth && Auth.currentUser) || null;
        if (currentUser && currentUser.role === 'VIEWER') {
            App.showToast('CSV Log Ingestion is restricted to ADMIN and INCIDENT_RESPONDER roles.', 'warning');
            return;
        }

        const modal = document.getElementById('csv-upload-modal');
        if (!modal) return;

        this.currentIncidentId = incidentId || (window.IncidentInvestigation && IncidentInvestigation.currentIncidentId) || 'INC-2026-001';

        await this.populateIncidentSelector();

        const badge = document.getElementById('csv-target-incident-badge');
        if (badge) badge.textContent = this.currentIncidentId;

        // Reset state if no file chosen
        if (!this.selectedFile) {
            this.resetFileSelection();
        }

        modal.classList.remove('hidden');
    },

    hideModal() {
        const modal = document.getElementById('csv-upload-modal');
        if (modal) modal.classList.add('hidden');
    },

    async populateIncidentSelector() {
        const select = document.getElementById('csv-incident-select');
        if (!select) return;

        try {
            const res = await fetch('/api/incidents', { credentials: 'same-origin' });
            if (res.ok) {
                const incidents = await res.json();
                if (Array.isArray(incidents) && incidents.length > 0) {
                    select.innerHTML = incidents.map(i => `
                        <option value="${i.id}" ${i.id === this.currentIncidentId ? 'selected' : ''}>
                            ${i.id} — ${i.title}
                        </option>
                    `).join('');
                    if (!this.currentIncidentId) {
                        this.currentIncidentId = incidents[0].id;
                    }
                    select.value = this.currentIncidentId;
                }
            }
        } catch (e) {
            console.error('Failed to load incidents for upload modal:', e);
        }
    },

    handleFileSelect(file) {
        if (!file) return;

        const alertBanner = document.getElementById('csv-alert-banner');
        const alertMsg = document.getElementById('csv-alert-message');

        // Verify format
        const filename = file.name || '';
        if (!filename.toLowerCase().endsWith('.csv')) {
            if (alertBanner && alertMsg) {
                alertMsg.textContent = 'Invalid file type. Only standard comma-separated .csv files are supported.';
                alertBanner.classList.remove('hidden');
                alertBanner.style.display = '';
            }
            return;
        }

        // Verify size (10 MB max)
        const maxBytes = 10 * 1024 * 1024;
        if (file.size > maxBytes) {
            if (alertBanner && alertMsg) {
                alertMsg.textContent = `File size (${this.formatBytes(file.size)}) exceeds the 10 MB maximum allowed limit.`;
                alertBanner.classList.remove('hidden');
                alertBanner.style.display = '';
            }
            return;
        }

        // Clear previous alert
        if (alertBanner) {
            alertBanner.classList.add('hidden');
            alertBanner.style.display = 'none';
        }

        this.selectedFile = file;

        // Update selected file card
        const fileNameEl = document.getElementById('csv-file-name');
        const fileSizeEl = document.getElementById('csv-file-size');
        const fileCard = document.getElementById('csv-selected-file-card');
        const dropzone = document.getElementById('csv-dropzone');

        if (fileNameEl) fileNameEl.textContent = file.name;
        if (fileSizeEl) fileSizeEl.textContent = this.formatBytes(file.size);

        if (dropzone) dropzone.style.display = 'none';
        if (fileCard) {
            fileCard.classList.remove('hidden');
            fileCard.style.display = '';
        }

        // Automatically trigger server-side preview & validation
        this.validateAndPreview();
    },

    resetFileSelection() {
        this.selectedFile = null;
        this.previewReport = null;

        const fileInput = document.getElementById('csv-file-input');
        if (fileInput) fileInput.value = '';

        const dropzone = document.getElementById('csv-dropzone');
        if (dropzone) dropzone.style.display = '';

        const fileCard = document.getElementById('csv-selected-file-card');
        if (fileCard) {
            fileCard.classList.add('hidden');
            fileCard.style.display = 'none';
        }

        const alertBanner = document.getElementById('csv-alert-banner');
        if (alertBanner) {
            alertBanner.classList.add('hidden');
            alertBanner.style.display = 'none';
        }

        const progressContainer = document.getElementById('csv-progress-container');
        if (progressContainer) {
            progressContainer.classList.add('hidden');
            progressContainer.style.display = 'none';
        }

        const valSection = document.getElementById('csv-validation-section');
        if (valSection) {
            valSection.classList.add('hidden');
            valSection.style.display = 'none';
        }

        const successSection = document.getElementById('csv-success-section');
        if (successSection) {
            successSection.classList.add('hidden');
            successSection.style.display = 'none';
        }

        const commitBtn = document.getElementById('btn-confirm-commit-csv');
        if (commitBtn) {
            commitBtn.classList.add('hidden');
            commitBtn.style.display = 'none';
        }

        const previewBtn = document.getElementById('btn-preview-csv-action');
        if (previewBtn) {
            previewBtn.classList.add('hidden');
            previewBtn.style.display = 'none';
        }

        const resetUploadBtn = document.getElementById('btn-reset-csv-upload');
        if (resetUploadBtn) {
            resetUploadBtn.classList.add('hidden');
            resetUploadBtn.style.display = 'none';
        }
    },

    async validateAndPreview() {
        if (!this.selectedFile || !this.currentIncidentId) return;

        const alertBanner = document.getElementById('csv-alert-banner');
        const alertMsg = document.getElementById('csv-alert-message');
        const progressContainer = document.getElementById('csv-progress-container');
        const progressBar = document.getElementById('csv-progress-bar');
        const progressLabel = document.getElementById('csv-progress-label');
        const progressPercent = document.getElementById('csv-progress-percent');
        const valSection = document.getElementById('csv-validation-section');
        const commitBtn = document.getElementById('btn-confirm-commit-csv');
        const previewBtn = document.getElementById('btn-preview-csv-action');

        if (alertBanner) {
            alertBanner.classList.add('hidden');
            alertBanner.style.display = 'none';
        }

        if (progressContainer) {
            progressContainer.classList.remove('hidden');
            progressContainer.style.display = '';
            if (progressBar) progressBar.style.width = '45%';
            if (progressPercent) progressPercent.textContent = '45%';
            if (progressLabel) progressLabel.textContent = 'Uploading and validating CSV records...';
        }

        const formData = new FormData();
        formData.append('file', this.selectedFile);
        formData.append('incident_id', this.currentIncidentId);

        try {
            const res = await fetch(`/api/incidents/${encodeURIComponent(this.currentIncidentId)}/upload/preview`, {
                method: 'POST',
                body: formData,
                credentials: 'same-origin'
            });

            if (progressBar) progressBar.style.width = '100%';
            if (progressPercent) progressPercent.textContent = '100%';

            setTimeout(() => {
                if (progressContainer) {
                    progressContainer.classList.add('hidden');
                    progressContainer.style.display = 'none';
                }
            }, 350);

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                if (alertBanner && alertMsg) {
                    alertMsg.textContent = errData.error || `Server error during CSV validation (HTTP ${res.status}).`;
                    alertBanner.classList.remove('hidden');
                    alertBanner.style.display = '';
                }
                if (commitBtn) {
                    commitBtn.classList.add('hidden');
                    commitBtn.style.display = 'none';
                }
                return;
            }

            const report = await res.json();
            this.previewReport = report;
            this.renderValidationReport(report);

        } catch (err) {
            console.error('Validation preview error:', err);
            if (progressContainer) {
                progressContainer.classList.add('hidden');
                progressContainer.style.display = 'none';
            }
            if (alertBanner && alertMsg) {
                alertMsg.textContent = `Network error while validating CSV: ${err.message}`;
                alertBanner.classList.remove('hidden');
                alertBanner.style.display = '';
            }
        }
    },

    renderValidationReport(report) {
        const valSection = document.getElementById('csv-validation-section');
        if (!valSection) return;

        valSection.classList.remove('hidden');
        valSection.style.display = '';

        // Summary counts
        const elTotal = document.getElementById('val-total-rows');
        const elValid = document.getElementById('val-valid-rows');
        const elDup = document.getElementById('val-duplicate-rows');
        const elInv = document.getElementById('val-invalid-rows');
        const elSvc = document.getElementById('val-services-count');

        if (elTotal) elTotal.textContent = report.total_rows || 0;
        if (elValid) elValid.textContent = report.valid_count || 0;
        if (elDup) elDup.textContent = report.duplicate_count || 0;
        if (elInv) elInv.textContent = report.invalid_count || 0;
        if (elSvc) elSvc.textContent = (report.services_detected || []).length;

        // Warnings
        const warningsBox = document.getElementById('csv-warnings-container');
        const warningsList = document.getElementById('csv-warnings-list');
        if (warningsBox && warningsList) {
            if (report.warnings && report.warnings.length > 0) {
                warningsList.innerHTML = report.warnings.map(w => `<div>&bull; ${w}</div>`).join('');
                warningsBox.classList.remove('hidden');
                warningsBox.style.display = '';
            } else {
                warningsBox.classList.add('hidden');
                warningsBox.style.display = 'none';
            }
        }

        // Row Errors
        const errorsBox = document.getElementById('csv-errors-container');
        const errorCountEl = document.getElementById('csv-error-count');
        const errorsTbody = document.getElementById('csv-errors-table-body');
        if (errorsBox && errorsTbody) {
            if (report.row_errors && report.row_errors.length > 0) {
                if (errorCountEl) errorCountEl.textContent = report.row_errors.length;
                errorsTbody.innerHTML = report.row_errors.map(e => `
                    <tr>
                        <td class="font-mono text-danger font-bold">Row ${e.row}</td>
                        <td class="badge-sub">${e.field || '-'}</td>
                        <td class="text-danger">${e.error || '-'}</td>
                        <td class="font-mono text-muted small">${(e.sample || '').replace(/</g, '&lt;')}</td>
                    </tr>
                `).join('');
                errorsBox.classList.remove('hidden');
                errorsBox.style.display = '';
            } else {
                errorsBox.classList.add('hidden');
                errorsBox.style.display = 'none';
            }
        }

        // Preview Table
        const previewTbody = document.getElementById('csv-preview-table-body');
        const previewCountEl = document.getElementById('csv-preview-count');
        if (previewTbody) {
            const rows = report.preview_rows || [];
            if (previewCountEl) previewCountEl.textContent = rows.length;

            if (rows.length === 0) {
                previewTbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-3">No preview rows available.</td></tr>`;
            } else {
                previewTbody.innerHTML = rows.map(r => {
                    let statusBadge = '<span class="badge-status-valid">VALID</span>';
                    if (r.status === 'DUPLICATE') {
                        statusBadge = '<span class="badge-status-duplicate" title="Duplicate row">DUPLICATE</span>';
                    } else if (r.status === 'INVALID') {
                        statusBadge = `<span class="badge-status-invalid" title="${r.error || 'Invalid'}">INVALID</span>`;
                    }

                    return `
                        <tr>
                            <td class="font-mono text-muted">${r.row}</td>
                            <td class="font-mono small">${r.timestamp || '-'}</td>
                            <td><span class="badge badge-neutral">${r.service || 'unknown'}</span></td>
                            <td><span class="badge badge-info">${r.type || 'LOG'}</span></td>
                            <td><span class="badge badge-severity ${r.severity ? r.severity.toLowerCase() : 'info'}">${r.severity || 'INFO'}</span></td>
                            <td class="font-mono ${r.anomaly_score >= 0.7 ? 'text-danger' : (r.anomaly_score >= 0.4 ? 'text-warning' : 'text-muted')}">${(r.anomaly_score !== undefined) ? r.anomaly_score.toFixed(2) : '-'}</td>
                            <td class="text-truncate" style="max-width: 280px;" title="${(r.summary || '').replace(/"/g, '&quot;')}">${(r.summary || '-').replace(/</g, '&lt;')}</td>
                            <td>${statusBadge}</td>
                        </tr>
                    `;
                }).join('');
            }
        }

        // Commit Button Enablement
        const commitBtn = document.getElementById('btn-confirm-commit-csv');
        const previewBtn = document.getElementById('btn-preview-csv-action');

        if (commitBtn) {
            if (report.valid_count > 0) {
                commitBtn.innerHTML = `<span>&#10003;</span> Ingest ${report.valid_count} Valid Records`;
                commitBtn.classList.remove('hidden');
                commitBtn.style.display = '';
                commitBtn.disabled = false;
            } else {
                commitBtn.classList.add('hidden');
                commitBtn.style.display = 'none';
            }
        }

        if (previewBtn) {
            previewBtn.classList.remove('hidden');
            previewBtn.style.display = '';
        }
    },

    async commitUpload() {
        if (!this.selectedFile || !this.currentIncidentId) return;

        const alertBanner = document.getElementById('csv-alert-banner');
        const alertMsg = document.getElementById('csv-alert-message');
        const progressContainer = document.getElementById('csv-progress-container');
        const progressBar = document.getElementById('csv-progress-bar');
        const progressLabel = document.getElementById('csv-progress-label');
        const progressPercent = document.getElementById('csv-progress-percent');
        const commitBtn = document.getElementById('btn-confirm-commit-csv');
        const valSection = document.getElementById('csv-validation-section');
        const successSection = document.getElementById('csv-success-section');
        const resetUploadBtn = document.getElementById('btn-reset-csv-upload');

        if (commitBtn) {
            commitBtn.disabled = true;
            commitBtn.innerHTML = '<span>&#8987;</span> Committing Records...';
        }

        if (progressContainer) {
            progressContainer.classList.remove('hidden');
            progressContainer.style.display = '';
            if (progressBar) progressBar.style.width = '60%';
            if (progressPercent) progressPercent.textContent = '60%';
            if (progressLabel) progressLabel.textContent = 'Persisting evidence records and updating timeline...';
        }

        const formData = new FormData();
        formData.append('file', this.selectedFile);
        formData.append('incident_id', this.currentIncidentId);

        try {
            const res = await fetch(`/api/incidents/${encodeURIComponent(this.currentIncidentId)}/upload/commit`, {
                method: 'POST',
                body: formData,
                credentials: 'same-origin'
            });

            if (progressBar) progressBar.style.width = '100%';
            if (progressPercent) progressPercent.textContent = '100%';

            setTimeout(() => {
                if (progressContainer) {
                    progressContainer.classList.add('hidden');
                    progressContainer.style.display = 'none';
                }
            }, 300);

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                if (alertBanner && alertMsg) {
                    alertMsg.textContent = errData.error || `Commit failed with HTTP ${res.status}.`;
                    alertBanner.classList.remove('hidden');
                    alertBanner.style.display = '';
                }
                if (commitBtn) {
                    commitBtn.disabled = false;
                    commitBtn.innerHTML = '<span>&#10003;</span> Confirm & Ingest Evidence';
                }
                return;
            }

            const result = await res.json();

            // Hide validation and show success panel
            if (valSection) {
                valSection.classList.add('hidden');
                valSection.style.display = 'none';
            }
            if (commitBtn) {
                commitBtn.classList.add('hidden');
                commitBtn.style.display = 'none';
            }

            const dropzone = document.getElementById('csv-dropzone');
            if (dropzone) dropzone.style.display = 'none';

            const fileCard = document.getElementById('csv-selected-file-card');
            if (fileCard) {
                fileCard.classList.add('hidden');
                fileCard.style.display = 'none';
            }

            if (successSection) {
                const textEl = document.getElementById('csv-success-summary-text');
                const accBadge = document.getElementById('success-accepted-badge');
                const dupBadge = document.getElementById('success-duplicates-badge');
                const rejBadge = document.getElementById('success-rejected-badge');

                if (textEl) {
                    textEl.textContent = result.message || `Successfully ingested ${result.accepted_count} evidence records into incident ${this.currentIncidentId}.`;
                }
                if (accBadge) accBadge.textContent = `${result.accepted_count} Imported`;
                if (dupBadge) dupBadge.textContent = `${result.duplicate_count} Duplicates Skipped`;
                if (rejBadge) rejBadge.textContent = `${result.rejected_count} Invalid Skipped`;

                successSection.classList.remove('hidden');
                successSection.style.display = '';
            }

            if (resetUploadBtn) {
                resetUploadBtn.classList.remove('hidden');
                resetUploadBtn.style.display = '';
            }

            // Sync incident investigation evidence & timeline in the background
            if (window.IncidentInvestigation && IncidentInvestigation.selectIncident) {
                IncidentInvestigation.selectIncident(this.currentIncidentId);
            }

            // Sync evidence explorer
            if (window.EvidenceExplorer && EvidenceExplorer.loadEvidence) {
                EvidenceExplorer.loadEvidence();
            }

            // Show global toast
            if (window.App && App.showToast) {
                App.showToast(`Imported ${result.accepted_count} evidence records into ${this.currentIncidentId}.`, 'success');
            }

        } catch (err) {
            console.error('Commit error:', err);
            if (progressContainer) {
                progressContainer.classList.add('hidden');
                progressContainer.style.display = 'none';
            }
            if (alertBanner && alertMsg) {
                alertMsg.textContent = `Network error during commit: ${err.message}`;
                alertBanner.classList.remove('hidden');
                alertBanner.style.display = '';
            }
            if (commitBtn) {
                commitBtn.disabled = false;
                commitBtn.innerHTML = '<span>&#10003;</span> Confirm & Ingest Evidence';
            }
        }
    },

    runRcaPostImport() {
        this.hideModal();
        if (window.AppNavigation) {
            AppNavigation.navigate('tab-investigation', {
                incidentId: this.currentIncidentId,
                pushState: true
            });
        }
        if (window.IncidentInvestigation && IncidentInvestigation.executeRCA) {
            IncidentInvestigation.executeRCA(this.currentIncidentId, true);
        }
    },

    formatBytes(bytes) {
        if (!bytes || bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }
};

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
    CsvUpload.init();
});
