/**
 * BeakCortex Orchestrator Dashboard -- Alpine.js Component
 */
function dashboard() {
    return {
        // Data
        stats: {},
        tasks: [],
        taskTotal: 0,
        detail: null,
        expandedId: null,

        // Polling
        polling: true,
        pollInterval: 5,
        _timer: null,

        // Filters & Sort
        filterStatus: '',
        sortField: 'created_at',
        sortAsc: false,

        // Display
        lastUpdated: '',

        statusDefs: [
            { key: 'pending',    label: 'Pending',    color: '#6c757d' },
            { key: 'dispatched', label: 'Dispatched', color: '#0d6efd' },
            { key: 'running',    label: 'Running',    color: '#0dcaf0' },
            { key: 'completed',  label: 'Completed',  color: '#198754' },
            { key: 'failed',     label: 'Failed',     color: '#dc3545' },
            { key: 'timeout',    label: 'Timeout',    color: '#fd7e14' },
            { key: 'cancelled',  label: 'Cancelled',  color: '#adb5bd' },
        ],

        async init() {
            await this.refresh();
            this.startPolling();
        },

        async refresh() {
            await Promise.all([this.fetchStats(), this.fetchTasks()]);
            this.lastUpdated = new Date().toLocaleTimeString('zh-TW', { hour12: false });
        },

        async fetchStats() {
            try {
                const resp = await fetch('/bc/api/orchestrator/stats');
                this.stats = await resp.json();
            } catch (e) {
                console.error('fetchStats error:', e);
            }
        },

        async fetchTasks() {
            try {
                let url = '/bc/api/orchestrator/tasks?per_page=100';
                if (this.filterStatus) url += '&status=' + this.filterStatus;
                const resp = await fetch(url);
                const data = await resp.json();
                this.tasks = data.items || [];
                this.taskTotal = data.total || 0;

                // report_count is included in list API response
                for (const t of this.tasks) {
                    t._report_count = t.report_count ?? 0;
                }
            } catch (e) {
                console.error('fetchTasks error:', e);
            }
        },

        async fetchDetail(taskId) {
            try {
                const resp = await fetch('/bc/api/orchestrator/tasks/' + taskId);
                this.detail = await resp.json();
            } catch (e) {
                console.error('fetchDetail error:', e);
                this.detail = null;
            }
        },

        // Polling control
        startPolling() {
            this.stopPolling();
            if (this.polling) {
                this._timer = setInterval(() => this.refresh(), this.pollInterval * 1000);
            }
        },

        stopPolling() {
            if (this._timer) {
                clearInterval(this._timer);
                this._timer = null;
            }
        },

        togglePolling() {
            this.polling = !this.polling;
            if (this.polling) {
                this.refresh();
                this.startPolling();
            } else {
                this.stopPolling();
            }
        },

        // Filter & Sort
        toggleFilter(status) {
            this.filterStatus = this.filterStatus === status ? '' : status;
            this.fetchTasks();
        },

        sortBy(field) {
            if (this.sortField === field) {
                this.sortAsc = !this.sortAsc;
            } else {
                this.sortField = field;
                this.sortAsc = false;
            }
        },

        sortIcon(field) {
            if (this.sortField !== field) return '\u2195';
            return this.sortAsc ? '\u2191' : '\u2193';
        },

        get sortedTasks() {
            const arr = [...this.tasks];
            const f = this.sortField;
            const asc = this.sortAsc;
            arr.sort((a, b) => {
                let va = a[f] ?? '';
                let vb = b[f] ?? '';
                if (typeof va === 'string') va = va.toLowerCase();
                if (typeof vb === 'string') vb = vb.toLowerCase();
                if (va < vb) return asc ? -1 : 1;
                if (va > vb) return asc ? 1 : -1;
                return 0;
            });
            return arr;
        },

        // Expand/collapse
        toggleExpand(taskId) {
            if (this.expandedId === taskId) {
                this.expandedId = null;
                this.detail = null;
            } else {
                this.expandedId = taskId;
                this.fetchDetail(taskId);
            }
        },

        // Formatters
        statusClass(status) {
            return 'badge-' + (status || 'pending');
        },

        fmtTime(iso) {
            if (!iso) return '-';
            const d = new Date(iso);
            return d.toLocaleString('zh-TW', {
                month: '2-digit', day: '2-digit',
                hour: '2-digit', minute: '2-digit', second: '2-digit',
                hour12: false,
            });
        },

        elapsed(task) {
            if (!task.dispatched_at) return '-';
            const start = new Date(task.dispatched_at);
            const end = task.completed_at ? new Date(task.completed_at) : new Date();
            const secs = Math.floor((end - start) / 1000);
            if (secs < 60) return secs + 's';
            const mins = Math.floor(secs / 60);
            const remSecs = secs % 60;
            if (mins < 60) return mins + 'm' + (remSecs ? remSecs + 's' : '');
            const hrs = Math.floor(mins / 60);
            const remMins = mins % 60;
            return hrs + 'h' + (remMins ? remMins + 'm' : '');
        },
    };
}
