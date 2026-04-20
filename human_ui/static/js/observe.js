/**
 * BeakCortex Observe -- Alpine.js 觀察儀表板
 */
function observeApp() {
    return {
        // State
        tab: 'conversations',
        polling: false,
        pollInterval: 30,
        pollTimer: null,
        lastUpdated: '',

        // Data
        stats: {},
        conversations: [],
        pipelines: [],
        sessions: [],
        signalDetail: [],
        reviews: [],
        globalReviewStats: {},
        allMentions: [],
        mentionLimit: 30,

        // Sort
        sortField: 'last_timestamp',
        sortAsc: false,

        async init() {
            await this.fetchAll();
        },

        async fetchAll() {
            await Promise.all([
                this.fetchStats(),
                this.fetchConversations(),
                this.fetchPipelines(),
                this.fetchSessions(),
                this.fetchReviews(),
            ]);
            this.lastUpdated = new Date().toLocaleTimeString('zh-TW', {hour12: false});
        },

        async fetchStats() {
            try {
                const resp = await fetch('/bc/api/observe/stats');
                this.stats = await resp.json();
            } catch (e) {
                console.error('fetchStats error:', e);
            }
        },

        async fetchConversations() {
            try {
                const resp = await fetch('/bc/api/observe/conversations?limit=50');
                this.conversations = await resp.json();
                this.applySorting();
            } catch (e) {
                console.error('fetchConversations error:', e);
            }
        },

        async fetchPipelines() {
            try {
                const resp = await fetch('/bc/api/observe/pipeline-runs?limit=50');
                this.pipelines = await resp.json();
            } catch (e) {
                console.error('fetchPipelines error:', e);
            }
        },

        async fetchSessions() {
            try {
                const resp = await fetch('/bc/api/observe/session-logs?limit=50');
                this.sessions = await resp.json();
            } catch (e) {
                console.error('fetchSessions error:', e);
            }
        },

        async fetchReviews() {
            try {
                const [reviewsResp, globalResp] = await Promise.all([
                    fetch('/bc/api/observe/reviews'),
                    fetch('/bc/api/observe/reviews/global-stats'),
                ]);
                this.reviews = await reviewsResp.json();
                const globalData = await globalResp.json();
                this.globalReviewStats = globalData.stats || globalData || {};

                // 彙整所有用戶提及
                this.allMentions = [];
                for (const r of this.reviews) {
                    if (r.user_mentions) {
                        this.allMentions.push(...r.user_mentions);
                    }
                }
                // 按時間排序（新到舊）
                this.allMentions.sort((a, b) => {
                    if (!a.timestamp) return 1;
                    if (!b.timestamp) return -1;
                    return b.timestamp.localeCompare(a.timestamp);
                });
                this.totalMentions = this.allMentions.length;
            } catch (e) {
                console.error('fetchReviews error:', e);
            }
        },

        totalMentions: 0,

        async showSignals(convId) {
            try {
                const resp = await fetch(`/bc/api/observe/conversations/${convId}/signals`);
                this.signalDetail = await resp.json();
                const modal = new bootstrap.Modal(document.getElementById('signalModal'));
                modal.show();
            } catch (e) {
                console.error('showSignals error:', e);
            }
        },

        switchTab(t) {
            this.tab = t;
        },

        togglePolling() {
            this.polling = !this.polling;
            if (this.polling) {
                this.pollTimer = setInterval(() => this.fetchAll(), this.pollInterval * 1000);
            } else {
                clearInterval(this.pollTimer);
                this.pollTimer = null;
            }
        },

        // Sorting
        sortBy(field) {
            if (this.sortField === field) {
                this.sortAsc = !this.sortAsc;
            } else {
                this.sortField = field;
                this.sortAsc = false;
            }
            this.applySorting();
        },

        applySorting() {
            const f = this.sortField;
            const asc = this.sortAsc;
            this.conversations.sort((a, b) => {
                let va = a[f], vb = b[f];
                if (va == null) va = '';
                if (vb == null) vb = '';
                if (typeof va === 'number' && typeof vb === 'number') {
                    return asc ? va - vb : vb - va;
                }
                return asc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
            });
        },

        // Formatters
        formatTime(ts) {
            if (!ts) return '-';
            const d = new Date(ts);
            const mm = String(d.getMonth() + 1).padStart(2, '0');
            const dd = String(d.getDate()).padStart(2, '0');
            const hh = String(d.getHours()).padStart(2, '0');
            const mi = String(d.getMinutes()).padStart(2, '0');
            return `${mm}-${dd} ${hh}:${mi}`;
        },

        formatTokens(n) {
            if (!n) return '0';
            if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
            if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
            return String(n);
        },

        formatDuration(start, end) {
            if (!start) return '-';
            const s = new Date(start);
            const e = end ? new Date(end) : new Date();
            const sec = Math.round((e - s) / 1000);
            return this.formatSeconds(sec);
        },

        formatSeconds(sec) {
            if (!sec && sec !== 0) return '-';
            if (sec < 60) return sec + 's';
            if (sec < 3600) return Math.floor(sec / 60) + 'm ' + (sec % 60) + 's';
            const h = Math.floor(sec / 3600);
            const m = Math.floor((sec % 3600) / 60);
            return h + 'h ' + m + 'm';
        },

        shortProject(path) {
            if (!path) return '?';
            const parts = path.split('/');
            return parts[parts.length - 1] || parts[parts.length - 2] || path;
        },

        // Signal helpers
        signalColor(type) {
            const map = {
                'error': 'bg-danger',
                'tool_failure': 'bg-danger',
                'rollback': 'bg-warning text-dark',
                'retry': 'bg-warning text-dark',
                'repeated_edit': 'bg-info',
                'long_struggle': 'bg-dark',
            };
            return map[type] || 'bg-secondary';
        },

        signalPct(count) {
            const max = Math.max(...Object.values(this.stats.signal_distribution || {1: 1}));
            return Math.round((count / max) * 100);
        },

        dailyPct(count) {
            const max = Math.max(...(this.stats.daily_conversations || [{cnt: 1}]).map(d => d.cnt));
            return Math.round((count / max) * 100);
        },

        severityBadge(sev) {
            return {
                'high': 'bg-danger',
                'medium': 'bg-warning text-dark',
                'low': 'bg-secondary',
            }[sev] || 'bg-secondary';
        },

        statusBadge(status) {
            return {
                'pending': 'bg-secondary',
                'running': 'bg-primary',
                'completed': 'bg-success',
                'failed': 'bg-danger',
                'timeout': 'bg-warning text-dark',
            }[status] || 'bg-secondary';
        },

        mentionBadge(type) {
            return {
                'todo': 'bg-warning text-dark',
                'request': 'bg-primary',
                'question': 'bg-info',
                'decision': 'bg-success',
            }[type] || 'bg-secondary';
        },

        errorPct(count) {
            const vals = Object.values(this.globalReviewStats.by_error_pattern || {1: 1});
            const max = Math.max(...vals);
            return Math.round((count / max) * 100);
        },
    };
}
