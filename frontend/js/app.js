// GridRunner - Main Alpine.js Application

document.addEventListener('alpine:init', () => {
    // Global store for app state
    Alpine.store('app', {
        authenticated: false,
        needsSetup: false,
        authEnabled: true,
        currentPage: 'dashboard',
        darkMode: false,
        loading: true,
        toasts: [],

        async init() {
            // Check auth status
            try {
                const status = await api.getAuthStatus();
                this.authenticated = status.authenticated;
                this.needsSetup = status.needs_setup;
                this.authEnabled = status.auth_enabled ?? true;

                // Load dark mode setting if authenticated
                if (this.authenticated) {
                    const settings = await api.getSettings();
                    this.darkMode = settings.dark_mode;
                    this.applyTheme();
                }
            } catch (error) {
                console.error('Init error:', error);
            }
            this.loading = false;
        },

        navigate(page) {
            this.currentPage = page;
            window.history.pushState({ page }, '', `#${page}`);
        },

        toggleDarkMode() {
            this.darkMode = !this.darkMode;
            this.applyTheme();
            api.toggleDarkMode(this.darkMode);
        },

        applyTheme() {
            document.documentElement.setAttribute('data-theme', this.darkMode ? 'dark' : 'light');
        },

        showToast(message, type = 'info') {
            const id = Date.now();
            this.toasts.push({ id, message, type });
            setTimeout(() => {
                this.toasts = this.toasts.filter(t => t.id !== id);
            }, 4000);
        },

        async logout() {
            await api.logout();
            this.authenticated = false;
        }
    });

    // Auth component
    Alpine.data('auth', () => ({
        password: '',
        confirmPassword: '',
        error: '',
        loading: false,

        async login() {
            this.error = '';
            this.loading = true;
            try {
                await api.login(this.password);
                Alpine.store('app').authenticated = true;
                Alpine.store('app').init();
            } catch (e) {
                this.error = 'Invalid password';
            }
            this.loading = false;
        },

        async setup() {
            if (this.password !== this.confirmPassword) {
                this.error = 'Passwords do not match';
                return;
            }
            if (this.password.length < 6) {
                this.error = 'Password must be at least 6 characters';
                return;
            }
            this.error = '';
            this.loading = true;
            try {
                await api.setupPassword(this.password);
                await api.login(this.password);
                Alpine.store('app').authenticated = true;
                Alpine.store('app').needsSetup = false;
            } catch (e) {
                this.error = e.message;
            }
            this.loading = false;
        }
    }));

    // Dashboard component
    Alpine.data('dashboard', () => ({
        stats: null,
        running: [],
        recent: [],
        upcoming: [],
        failures: [],
        loading: true,

        async init() {
            await this.refresh();
            // Auto-refresh: 2s when scripts are running, 10s otherwise
            this._scheduleRefresh();
        },

        _scheduleRefresh() {
            const interval = (this.running && this.running.length > 0) ? 2000 : 10000;
            this._refreshTimer = setTimeout(async () => {
                await this.refresh();
                this._scheduleRefresh();
            }, interval);
        },

        async refresh() {
            try {
                const [stats, running, recent, upcoming, failures] = await Promise.all([
                    api.getDashboardStats(),
                    api.getRunningScripts(),
                    api.getRecentRuns(10),
                    api.getUpcomingRuns(5),
                    api.getRecentFailures(24)
                ]);
                this.stats = stats;
                this.running = running;
                this.recent = recent;
                this.upcoming = upcoming;
                this.failures = failures;
            } catch (e) {
                console.error('Dashboard refresh error:', e);
            }
            this.loading = false;
        },

        formatDuration(seconds) {
            if (!seconds) return '-';
            if (seconds < 60) return `${seconds.toFixed(1)}s`;
            if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
            return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
        },

        formatDate(dateStr) {
            const date = new Date(dateStr);
            return date.toLocaleString();
        },

        getStatusBadgeClass(status) {
            const classes = {
                'success': 'badge-success',
                'failed': 'badge-error',
                'timeout': 'badge-warning',
                'killed': 'badge-warning',
                'running': 'badge-info'
            };
            return classes[status] || 'badge-neutral';
        }
    }));

    // Scripts component
    Alpine.data('scripts', () => ({
        scripts: [],
        categories: [],
        loading: true,
        showModal: false,
        editingScript: null,
        form: {
            name: '',
            description: '',
            script_type: 'python',
            path: '',
            interpreter_path: '',
            working_directory: '',
            env_vars: '',
            args: '',
            timeout: 3600,
            retry_count: 0,
            retry_delay: 60,
            category_id: null,
            notification_setting: 'on_failure',
            webhook_url: '',
            venv_path: '',
            interpreter_version: ''
        },
        scriptTypes: [
            { value: 'python', label: 'Python', icon: '🐍' },
            { value: 'bash', label: 'Bash', icon: '💻' },
            { value: 'sh', label: 'Shell (sh)', icon: '🐚' },
            { value: 'zsh', label: 'Zsh', icon: '🐚' },
            { value: 'node', label: 'Node.js', icon: '🟢' },
            { value: 'ruby', label: 'Ruby', icon: '💎' },
            { value: 'perl', label: 'Perl', icon: '🐪' },
            { value: 'php', label: 'PHP', icon: '🐘' },
            { value: 'deno', label: 'Deno', icon: '🦕' },
            { value: 'go', label: 'Go', icon: '🐹' },
            { value: 'r', label: 'R', icon: '📊' },
            { value: 'julia', label: 'Julia', icon: '📐' },
            { value: 'swift', label: 'Swift', icon: '🕊️' },
            { value: 'lua', label: 'Lua', icon: '🌙' },
            { value: 'java', label: 'Java', icon: '☕' },
            { value: 'powershell', label: 'PowerShell', icon: '⚡' },
            { value: 'executable', label: 'Executable', icon: '⚙️' },
            { value: 'other', label: 'Other', icon: '📄' }
        ],
        availableRuntimes: {},
        runtimesLoaded: false,
        detectedVenvs: [],
        showCreateVenv: false,
        newVenvPath: '',
        packages: [],
        loadingPackages: false,
        newPackage: '',
        validationResult: null,
        validating: false,
        showScheduleModal: false,
        scheduleForm: {
            script_id: null,
            schedule_type: 'interval',
            interval_value: 1,
            interval_unit: 'hours',
            cron_expression: '',
            specific_time: '09:00',
            days_of_week: [],
            enabled: true
        },
        expandedScript: null,
        scriptSchedules: {},

        async init() {
            await this.refresh();
            this.loadRuntimes();
        },

        async refresh() {
            try {
                const [scripts, categories] = await Promise.all([
                    api.getScripts(),
                    api.getCategories()
                ]);
                this.scripts = scripts;
                this.categories = categories;
            } catch (e) {
                console.error('Scripts refresh error:', e);
            }
            this.loading = false;
        },

        openCreateModal() {
            this.editingScript = null;
            this.resetForm();
            this.showModal = true;
        },

        openEditModal(script) {
            this.editingScript = script;
            this.form = {
                name: script.name,
                description: script.description || '',
                script_type: script.script_type || 'python',
                path: script.path,
                interpreter_path: script.interpreter_path || '',
                working_directory: script.working_directory || '',
                env_vars: script.env_vars ? JSON.stringify(script.env_vars) : '',
                args: script.args || '',
                timeout: script.timeout,
                retry_count: script.retry_count,
                retry_delay: script.retry_delay,
                category_id: script.category_id,
                notification_setting: script.notification_setting,
                webhook_url: script.webhook_url || '',
                venv_path: script.venv_path || '',
                interpreter_version: script.interpreter_version || ''
            };
            this.detectedVenvs = [];
            this.showCreateVenv = false;
            this.validationResult = null;
            this.loadRuntimesForType(script.script_type || 'python');
            this.showModal = true;
            this.checkDependencies();
        },

        resetForm() {
            this.form = {
                name: '',
                description: '',
                script_type: 'python',
                path: '',
                interpreter_path: '',
                working_directory: '',
                env_vars: '',
                args: '',
                timeout: 3600,
                retry_count: 0,
                retry_delay: 60,
                category_id: null,
                notification_setting: 'on_failure',
                webhook_url: '',
                venv_path: '',
                interpreter_version: ''
            };
            this.detectedVenvs = [];
            this.showCreateVenv = false;
            this.validationResult = null;
        },

        getScriptTypeInfo(type) {
            return this.scriptTypes.find(t => t.value === type) || { label: type, icon: '📄' };
        },

        async saveScript() {
            const data = { ...this.form };

            // Parse env_vars if provided
            if (data.env_vars) {
                try {
                    data.env_vars = JSON.parse(data.env_vars);
                } catch {
                    Alpine.store('app').showToast('Invalid JSON in environment variables', 'error');
                    return;
                }
            } else {
                data.env_vars = null;
            }

            try {
                if (this.editingScript) {
                    await api.updateScript(this.editingScript.id, data);
                    Alpine.store('app').showToast('Script updated successfully', 'success');
                } else {
                    await api.createScript(data);
                    Alpine.store('app').showToast('Script created successfully', 'success');
                }
                this.showModal = false;
                await this.refresh();
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        async checkDependencies() {
            this.validating = true;
            this.validationResult = null;
            try {
                const data = { ...this.form };
                if (data.env_vars) {
                    try {
                        data.env_vars = JSON.parse(data.env_vars);
                    } catch {
                        this.validationResult = { valid: false, issues: ['Invalid JSON in environment variables'] };
                        this.validating = false;
                        return;
                    }
                } else {
                    data.env_vars = null;
                }
                this.validationResult = await api.validateConfig(data);
            } catch (e) {
                this.validationResult = { valid: false, issues: [e.message] };
            }
            this.validating = false;
        },

        async deleteScript(script) {
            if (!confirm(`Delete "${script.name}"? This will also delete all schedules and run history.`)) {
                return;
            }
            try {
                await api.deleteScript(script.id);
                Alpine.store('app').showToast('Script deleted', 'success');
                await this.refresh();
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        async runScript(script) {
            try {
                const result = await api.runScript(script.id);
                Alpine.store('app').showToast(`Started: ${script.name}`, 'success');
                await this.refresh();
                // Poll until no scripts are running
                this._startRunPoll();
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        _startRunPoll() {
            if (this._runPollTimer) return;
            this._runPollTimer = setInterval(async () => {
                await this.refresh();
                const anyRunning = this.scripts.some(s => s.is_running);
                if (!anyRunning) {
                    clearInterval(this._runPollTimer);
                    this._runPollTimer = null;
                }
            }, 2000);
        },

        async toggleExpand(script) {
            if (this.expandedScript === script.id) {
                this.expandedScript = null;
            } else {
                this.expandedScript = script.id;
                // Load schedules for this script
                try {
                    const schedules = await api.getSchedules(script.id);
                    this.scriptSchedules[script.id] = schedules;
                } catch (e) {
                    console.error('Failed to load schedules:', e);
                    this.scriptSchedules[script.id] = [];
                }
            }
        },

        isExpanded(scriptId) {
            return this.expandedScript === scriptId;
        },

        openScheduleModal(script) {
            this.scheduleForm = {
                script_id: script.id,
                schedule_type: 'interval',
                interval_value: 1,
                interval_unit: 'hours',
                cron_expression: '',
                specific_time: '09:00',
                days_of_week: [],
                enabled: true
            };
            this.showScheduleModal = true;
        },

        async saveSchedule() {
            try {
                await api.createSchedule(this.scheduleForm);
                Alpine.store('app').showToast('Schedule created', 'success');
                this.showScheduleModal = false;
                // Refresh schedules
                const schedules = await api.getSchedules(this.scheduleForm.script_id);
                this.scriptSchedules[this.scheduleForm.script_id] = schedules;
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        async toggleSchedule(schedule) {
            try {
                await api.toggleSchedule(schedule.id);
                // Refresh
                const schedules = await api.getSchedules(schedule.script_id);
                this.scriptSchedules[schedule.script_id] = schedules;
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        async deleteSchedule(schedule) {
            if (!confirm('Delete this schedule?')) return;
            try {
                await api.deleteSchedule(schedule.id);
                const schedules = await api.getSchedules(schedule.script_id);
                this.scriptSchedules[schedule.script_id] = schedules;
                Alpine.store('app').showToast('Schedule deleted', 'success');
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        getHealthClass(score) {
            if (score >= 80) return 'high';
            if (score >= 50) return 'medium';
            return 'low';
        },

        hasPywebview() {
            return !!(window.pywebview && window.pywebview.api);
        },

        async browseFile(field) {
            if (!this.hasPywebview()) return;
            try {
                const path = await window.pywebview.api.browse_file();
                if (path) {
                    this.form[field] = path;
                    // Auto-detect script type from extension when browsing for script path
                    if (field === 'path') {
                        const ext = path.split('.').pop().toLowerCase();
                        const extMap = {
                            py: 'python', sh: 'bash', bash: 'bash', zsh: 'zsh',
                            js: 'node', mjs: 'node', rb: 'ruby', pl: 'perl',
                            php: 'php', go: 'go', r: 'r', R: 'r',
                            jl: 'julia', swift: 'swift', lua: 'lua',
                            java: 'java', ps1: 'powershell', ts: 'deno'
                        };
                        if (extMap[ext]) {
                            this.form.script_type = extMap[ext];
                            this.onScriptTypeChange();
                        }
                    }
                }
            } catch (e) {
                console.error('Browse file error:', e);
            }
        },

        async browseDirectory(field) {
            if (!this.hasPywebview()) return;
            try {
                const path = await window.pywebview.api.browse_directory();
                if (path) {
                    this.form[field] = path;
                }
            } catch (e) {
                console.error('Browse directory error:', e);
            }
        },

        async loadRuntimes() {
            if (this.runtimesLoaded) return;
            try {
                this.availableRuntimes = await api.getRuntimes();
                this.runtimesLoaded = true;
            } catch (e) {
                console.error('Failed to load runtimes:', e);
            }
        },

        async loadRuntimesForType(type) {
            if (this.availableRuntimes[type]) return;
            try {
                const result = await api.getRuntimes(type);
                this.availableRuntimes = { ...this.availableRuntimes, ...result };
            } catch (e) {
                console.error('Failed to load runtimes for type:', e);
            }
        },

        getRuntimesForType(type) {
            return this.availableRuntimes[type] || [];
        },

        onScriptTypeChange() {
            this.form.interpreter_path = '';
            this.form.venv_path = '';
            this.detectedVenvs = [];
            this.showCreateVenv = false;
            this.loadRuntimesForType(this.form.script_type);
        },

        async detectVenvs() {
            if (!this.form.path) {
                Alpine.store('app').showToast('Enter a script path first', 'error');
                return;
            }
            try {
                const result = await api.detectVenvs(this.form.path);
                this.detectedVenvs = result.venvs || [];
                if (this.detectedVenvs.length === 0) {
                    Alpine.store('app').showToast('No virtual environments found nearby', 'info');
                }
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        selectVenv(venv) {
            this.form.venv_path = venv.path;
        },

        async createVenv() {
            if (!this.form.interpreter_path && this.getRuntimesForType('python').length === 0) {
                Alpine.store('app').showToast('No Python interpreter selected', 'error');
                return;
            }
            const pythonPath = this.form.interpreter_path || this.getRuntimesForType('python').find(r => r.is_default)?.path;
            if (!pythonPath) {
                Alpine.store('app').showToast('Select a Python interpreter first', 'error');
                return;
            }
            if (!this.newVenvPath) {
                Alpine.store('app').showToast('Enter a path for the new environment', 'error');
                return;
            }
            try {
                const result = await api.createVenv(pythonPath, this.newVenvPath);
                this.form.venv_path = result.path;
                this.showCreateVenv = false;
                this.newVenvPath = '';
                Alpine.store('app').showToast(result.message, 'success');
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        async loadPackages(venvPath) {
            this.loadingPackages = true;
            try {
                const result = await api.getPackages(venvPath);
                this.packages = result.packages || [];
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
                this.packages = [];
            }
            this.loadingPackages = false;
        },

        async installPackage(venvPath) {
            if (!this.newPackage.trim()) return;
            try {
                await api.installPackages(venvPath, [this.newPackage.trim()]);
                Alpine.store('app').showToast(`Installed ${this.newPackage}`, 'success');
                this.newPackage = '';
                await this.loadPackages(venvPath);
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        async uninstallPackage(venvPath, pkg) {
            if (!confirm(`Uninstall ${pkg}?`)) return;
            try {
                await api.uninstallPackages(venvPath, [pkg]);
                Alpine.store('app').showToast(`Uninstalled ${pkg}`, 'success');
                await this.loadPackages(venvPath);
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        }
    }));

    // History component
    Alpine.data('history', () => ({
        runs: [],
        loading: true,
        selectedRun: null,
        filter: {
            scriptId: '',
            status: ''
        },
        limit: 50,
        offset: 0,

        async init() {
            await this.refresh();
        },

        async refresh() {
            try {
                this.runs = await api.getRuns({
                    scriptId: this.filter.scriptId || null,
                    status: this.filter.status || null,
                    limit: this.limit,
                    offset: this.offset
                });
            } catch (e) {
                console.error('History refresh error:', e);
            }
            this.loading = false;
        },

        async viewRun(run) {
            try {
                this.selectedRun = await api.getRun(run.id);
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        closeRunModal() {
            this.selectedRun = null;
        },

        async deleteRun(run) {
            if (!confirm('Delete this run record?')) return;
            try {
                await api.deleteRun(run.id);
                Alpine.store('app').showToast('Run deleted', 'success');
                await this.refresh();
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        formatDuration(seconds) {
            if (!seconds) return '-';
            if (seconds < 60) return `${seconds.toFixed(1)}s`;
            if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
            return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
        },

        formatDate(dateStr) {
            const date = new Date(dateStr);
            return date.toLocaleString();
        },

        getStatusBadgeClass(status) {
            const classes = {
                'success': 'badge-success',
                'failed': 'badge-error',
                'timeout': 'badge-warning',
                'killed': 'badge-warning',
                'running': 'badge-info'
            };
            return classes[status] || 'badge-neutral';
        },

        async applyFilter() {
            this.offset = 0;
            await this.refresh();
        }
    }));

    // Settings component
    Alpine.data('settings', () => ({
        settings: null,
        loading: true,
        saving: false,
        activeTab: 'smtp',
        cronJobs: [],
        showCronModal: false,

        async init() {
            await this.refresh();
        },

        async refresh() {
            try {
                this.settings = await api.getSettings();
            } catch (e) {
                console.error('Settings refresh error:', e);
            }
            this.loading = false;
        },

        async saveSmtp() {
            this.saving = true;
            try {
                await api.updateSmtpSettings(this.settings.smtp);
                Alpine.store('app').showToast('SMTP settings saved', 'success');
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
            this.saving = false;
        },

        async testSmtp() {
            try {
                const result = await api.testSmtp();
                if (result.success) {
                    Alpine.store('app').showToast('SMTP connection successful', 'success');
                } else {
                    Alpine.store('app').showToast(`SMTP test failed: ${result.error}`, 'error');
                }
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        async saveDigest() {
            this.saving = true;
            try {
                await api.updateDigestSettings(this.settings.digest);
                Alpine.store('app').showToast('Digest settings saved', 'success');
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
            this.saving = false;
        },

        async saveRetention() {
            this.saving = true;
            try {
                await api.updateRetentionSettings(this.settings.retention);
                Alpine.store('app').showToast('Retention settings saved', 'success');
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
            this.saving = false;
        },

        async saveNotification() {
            this.saving = true;
            try {
                await api.updateNotificationSettings(this.settings.notification);
                Alpine.store('app').showToast('Notification settings saved', 'success');
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
            this.saving = false;
        },

        async downloadBackup() {
            try {
                const blob = await api.backupConfig();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `gridrunner-backup-${new Date().toISOString().split('T')[0]}.json`;
                a.click();
                URL.revokeObjectURL(url);
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        async restoreBackup(event) {
            const file = event.target.files[0];
            if (!file) return;

            if (!confirm('This will restore configuration from the backup. Existing data may be duplicated. Continue?')) {
                return;
            }

            try {
                const result = await api.restoreConfig(file);
                Alpine.store('app').showToast(result.message, 'success');
                await this.refresh();
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        async parseCrontab() {
            try {
                this.cronJobs = await api.parseCrontab();
                this.showCronModal = true;
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        async importSelectedCronJobs() {
            const selected = this.cronJobs.filter(j => j.selected);
            if (selected.length === 0) {
                Alpine.store('app').showToast('No jobs selected', 'error');
                return;
            }

            try {
                const result = await api.importCronJobs(selected);
                Alpine.store('app').showToast(result.message, 'success');
                this.showCronModal = false;
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        async changePassword() {
            const newPassword = prompt('Enter new password (min 6 characters):');
            if (!newPassword || newPassword.length < 6) {
                Alpine.store('app').showToast('Password must be at least 6 characters', 'error');
                return;
            }

            try {
                await api.changePassword(newPassword);
                Alpine.store('app').showToast('Password changed successfully', 'success');
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        }
    }));
});

// Handle browser navigation
window.addEventListener('popstate', (event) => {
    if (event.state && event.state.page) {
        Alpine.store('app').currentPage = event.state.page;
    }
});

// Handle auth required events
window.addEventListener('auth:required', () => {
    Alpine.store('app').authenticated = false;
});

// Initialize from URL hash
document.addEventListener('DOMContentLoaded', () => {
    const hash = window.location.hash.slice(1);
    if (hash && ['dashboard', 'scripts', 'history', 'settings'].includes(hash)) {
        setTimeout(() => {
            Alpine.store('app').currentPage = hash;
        }, 100);
    }
});
