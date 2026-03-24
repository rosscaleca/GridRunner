// API Client for GridRunner

const API_BASE = '/api';

class ApiClient {
    constructor() {
        this.baseUrl = API_BASE;
    }

    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        const config = {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            },
            credentials: 'include',
            ...options,
        };

        if (config.body && typeof config.body === 'object') {
            config.body = JSON.stringify(config.body);
        }

        try {
            const response = await fetch(url, config);

            if (response.status === 401) {
                window.dispatchEvent(new CustomEvent('auth:required'));
                throw new Error('Authentication required');
            }

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || `HTTP ${response.status}`);
            }

            // Check if response is JSON
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                return await response.json();
            }

            return await response.text();
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }

    // Auth endpoints
    async getAuthStatus() {
        return this.request('/auth/status');
    }

    async login(password) {
        return this.request('/auth/login', {
            method: 'POST',
            body: { password },
        });
    }

    async logout() {
        return this.request('/auth/logout', { method: 'POST' });
    }

    async setupPassword(password) {
        return this.request('/auth/setup', {
            method: 'POST',
            body: { password },
        });
    }

    async changePassword(password) {
        return this.request('/auth/change-password', {
            method: 'POST',
            body: { password },
        });
    }

    // Scripts endpoints
    async getScripts(categoryId = null) {
        const params = categoryId ? `?category_id=${categoryId}` : '';
        return this.request(`/scripts${params}`);
    }

    async getScript(id) {
        return this.request(`/scripts/${id}`);
    }

    async createScript(data) {
        return this.request('/scripts', {
            method: 'POST',
            body: data,
        });
    }

    async updateScript(id, data) {
        return this.request(`/scripts/${id}`, {
            method: 'PUT',
            body: data,
        });
    }

    async deleteScript(id) {
        return this.request(`/scripts/${id}`, { method: 'DELETE' });
    }

    async runScript(id) {
        return this.request(`/scripts/${id}/run`, { method: 'POST' });
    }

    async killScript(scriptId, runId) {
        return this.request(`/scripts/${scriptId}/kill?run_id=${runId}`, {
            method: 'POST',
        });
    }

    async validateScript(id) {
        return this.request(`/scripts/${id}/validate`);
    }

    async validateConfig(data) {
        return this.request('/scripts/validate-config', {
            method: 'POST',
            body: data,
        });
    }

    async getScriptHealth(id) {
        return this.request(`/scripts/${id}/health`);
    }

    // Runtimes endpoints
    async getRuntimes(scriptType = null) {
        const params = scriptType ? `?script_type=${encodeURIComponent(scriptType)}` : '';
        return this.request(`/runtimes${params}`);
    }

    async refreshRuntimes() {
        return this.request('/runtimes/refresh', { method: 'POST' });
    }

    // Environments endpoints
    async detectVenvs(path) {
        return this.request(`/environments/detect?path=${encodeURIComponent(path)}`);
    }

    async createVenv(pythonPath, venvPath) {
        return this.request('/environments/create', {
            method: 'POST',
            body: { python_path: pythonPath, venv_path: venvPath },
        });
    }

    async getPackages(venvPath) {
        return this.request(`/environments/packages?venv_path=${encodeURIComponent(venvPath)}`);
    }

    async installPackages(venvPath, packages) {
        return this.request('/environments/packages/install', {
            method: 'POST',
            body: { venv_path: venvPath, packages },
        });
    }

    async uninstallPackages(venvPath, packages) {
        return this.request('/environments/packages/uninstall', {
            method: 'POST',
            body: { venv_path: venvPath, packages },
        });
    }

    // Categories endpoints
    async getCategories() {
        return this.request('/scripts/categories/');
    }

    async createCategory(data) {
        return this.request('/scripts/categories/', {
            method: 'POST',
            body: data,
        });
    }

    async deleteCategory(id) {
        return this.request(`/scripts/categories/${id}`, { method: 'DELETE' });
    }

    // Schedules endpoints
    async getSchedules(scriptId = null) {
        const params = scriptId ? `?script_id=${scriptId}` : '';
        return this.request(`/schedules${params}`);
    }

    async getSchedule(id) {
        return this.request(`/schedules/${id}`);
    }

    async createSchedule(data) {
        return this.request('/schedules', {
            method: 'POST',
            body: data,
        });
    }

    async updateSchedule(id, data) {
        return this.request(`/schedules/${id}`, {
            method: 'PUT',
            body: data,
        });
    }

    async deleteSchedule(id) {
        return this.request(`/schedules/${id}`, { method: 'DELETE' });
    }

    async toggleSchedule(id) {
        return this.request(`/schedules/${id}/toggle`, { method: 'POST' });
    }

    // Runs endpoints
    async getRuns(options = {}) {
        const params = new URLSearchParams();
        if (options.scriptId) params.set('script_id', options.scriptId);
        if (options.status) params.set('status', options.status);
        if (options.limit) params.set('limit', options.limit);
        if (options.offset) params.set('offset', options.offset);

        const query = params.toString();
        return this.request(`/runs${query ? `?${query}` : ''}`);
    }

    async getRun(id) {
        return this.request(`/runs/${id}`);
    }

    async deleteRun(id) {
        return this.request(`/runs/${id}`, { method: 'DELETE' });
    }

    async cleanupOldRuns(days) {
        return this.request(`/runs/cleanup/old?days=${days}`, { method: 'DELETE' });
    }

    async cleanupExcessRuns(maxPerScript) {
        return this.request(`/runs/cleanup/excess?max_per_script=${maxPerScript}`, {
            method: 'POST',
        });
    }

    streamRunOutput(runId, onMessage, onError, onComplete) {
        const eventSource = new EventSource(`${this.baseUrl}/runs/${runId}/stream`);

        eventSource.addEventListener('output', (event) => {
            const data = JSON.parse(event.data);
            onMessage(data);

            if (data.status !== 'running') {
                eventSource.close();
                if (onComplete) onComplete(data);
            }
        });

        eventSource.onerror = (error) => {
            eventSource.close();
            if (onError) onError(error);
        };

        return eventSource;
    }

    // Dashboard endpoints
    async getDashboardStats() {
        return this.request('/dashboard/stats');
    }

    async getRunningScripts() {
        return this.request('/dashboard/running');
    }

    async getRecentRuns(limit = 10) {
        return this.request(`/dashboard/recent?limit=${limit}`);
    }

    async getUpcomingRuns(limit = 10) {
        return this.request(`/dashboard/upcoming?limit=${limit}`);
    }

    async getRecentFailures(hours = 24) {
        return this.request(`/dashboard/failures?hours=${hours}`);
    }

    async getActivityChart(days = 7) {
        return this.request(`/dashboard/activity?days=${days}`);
    }

    // Settings endpoints
    async getSettings() {
        return this.request('/settings');
    }

    async updateSmtpSettings(data) {
        return this.request('/settings/smtp', {
            method: 'PUT',
            body: data,
        });
    }

    async updateDigestSettings(data) {
        return this.request('/settings/digest', {
            method: 'PUT',
            body: data,
        });
    }

    async updateRetentionSettings(data) {
        return this.request('/settings/retention', {
            method: 'PUT',
            body: data,
        });
    }

    async updateNotificationSettings(data) {
        return this.request('/settings/notification', {
            method: 'PUT',
            body: data,
        });
    }

    async toggleDarkMode(enabled) {
        return this.request(`/settings/dark-mode?enabled=${enabled}`, {
            method: 'PUT',
        });
    }

    async testSmtp() {
        return this.request('/settings/smtp/test', { method: 'POST' });
    }

    async backupConfig() {
        const response = await fetch(`${this.baseUrl}/settings/backup`, {
            credentials: 'include',
        });
        return response.blob();
    }

    async restoreConfig(file) {
        const formData = new FormData();
        formData.append('file', file);

        return fetch(`${this.baseUrl}/settings/restore`, {
            method: 'POST',
            body: formData,
            credentials: 'include',
        }).then(r => r.json());
    }

    async getServiceStatus() {
        return this.request('/settings/service/status');
    }

    // Cron endpoints
    async parseCrontab() {
        return this.request('/cron/parse');
    }

    async importCronJobs(jobs) {
        return this.request('/cron/import', {
            method: 'POST',
            body: { jobs },
        });
    }

    async validateCronExpression(expression) {
        return this.request(`/cron/validate-expression?expression=${encodeURIComponent(expression)}`, {
            method: 'POST',
        });
    }
}

// Export singleton instance
window.api = new ApiClient();
