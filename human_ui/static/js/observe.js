/**
 * BeakBroodNest Observe -- Alpine.js 觀察儀表板
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

        // Backlog state
        backlogSubTab: 'active',
        backlogFilters: { source: '', owner: '', project: '', atomTypes: [] },
        backlogRows: [],
        backlogCounts: { active: 0, blocked: 0, archived: 0 },
        backlogProjects: [],
        backlogSort: { field: 'updated_at', asc: false },
        backlogTaskSchema: null,
        atomEdit: {
            visible: false,
            saving: false,
            atom_id: null,
            title: '',
            lifecycle: '',
            owner: '',
            vitality_score: null,
            content: '',
            content_json: null,
            editor: null,
            modal: null,
        },

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
                const resp = await fetch('/beakbroodnest/api/observe/stats');
                this.stats = await resp.json();
            } catch (e) {
                console.error('fetchStats error:', e);
            }
        },

        async fetchConversations() {
            try {
                const resp = await fetch('/beakbroodnest/api/observe/conversations?limit=50');
                this.conversations = await resp.json();
                this.applySorting();
            } catch (e) {
                console.error('fetchConversations error:', e);
            }
        },

        async fetchPipelines() {
            try {
                const resp = await fetch('/beakbroodnest/api/observe/pipeline-runs?limit=50');
                this.pipelines = await resp.json();
            } catch (e) {
                console.error('fetchPipelines error:', e);
            }
        },

        async fetchSessions() {
            try {
                const resp = await fetch('/beakbroodnest/api/observe/session-logs?limit=50');
                this.sessions = await resp.json();
            } catch (e) {
                console.error('fetchSessions error:', e);
            }
        },

        async fetchReviews() {
            try {
                const [reviewsResp, globalResp] = await Promise.all([
                    fetch('/beakbroodnest/api/observe/reviews'),
                    fetch('/beakbroodnest/api/observe/reviews/global-stats'),
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
                const resp = await fetch(`/beakbroodnest/api/observe/conversations/${convId}/signals`);
                this.signalDetail = await resp.json();
                const modal = new bootstrap.Modal(document.getElementById('signalModal'));
                modal.show();
            } catch (e) {
                console.error('showSignals error:', e);
            }
        },

        switchTab(t) {
            this.tab = t;
            if (t === 'backlog') {
                this.openBacklog();
            }
        },

        async openBacklog() {
            await this.loadBacklogCounts();
            // 第一次進 Backlog 時用 last_active_canvas_slug 預設選中對應 canvas
            if (!this._backlogDefaultApplied) {
                this._backlogDefaultApplied = true;
                try {
                    const resp = await fetch('/beakbroodnest/api/preferences/last_active_canvas_slug');
                    const data = await resp.json();
                    const slug = data && data.value;
                    if (slug) {
                        const proj = this.backlogProjects.find(p => p.slug === slug);
                        if (proj) {
                            this.backlogFilters.project = String(proj.id);
                        }
                    }
                } catch (e) {
                    console.error('讀 last_active_canvas_slug 失敗:', e);
                }
            }
            await this.loadBacklog();
            this.loadTaskSchema();
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

        // ==========================================================
        // Backlog 待辦清單
        // ==========================================================

        async loadBacklogCounts() {
            try {
                const resp = await fetch('/beakbroodnest/api/observe/backlog/counts');
                const data = await resp.json();
                this.backlogCounts = data.counts || { active: 0, blocked: 0, archived: 0 };
                this.backlogProjects = data.projects || [];
            } catch (e) {
                console.error('loadBacklogCounts error:', e);
            }
        },

        async loadBacklog() {
            const params = new URLSearchParams();
            params.set('tab', this.backlogSubTab);
            if (this.backlogFilters.source) params.set('source', this.backlogFilters.source);
            if (this.backlogFilters.owner) params.set('owner', this.backlogFilters.owner);
            if (this.backlogFilters.project) params.set('project', this.backlogFilters.project);
            if (this.backlogFilters.atomTypes.length > 0) {
                params.set('atom_type', this.backlogFilters.atomTypes.join(','));
            }
            try {
                const resp = await fetch('/beakbroodnest/api/observe/backlog?' + params.toString());
                this.backlogRows = await resp.json();
            } catch (e) {
                console.error('loadBacklog error:', e);
                this.backlogRows = [];
            }
        },

        async loadTaskSchema() {
            if (this.backlogTaskSchema) return;
            try {
                const resp = await fetch('/beakbroodnest/api/entry-schemas');
                if (resp.ok) {
                    const schemas = await resp.json();
                    this.backlogTaskSchema = schemas.find(s => s.code === 'task') || null;
                }
            } catch (e) {
                console.error('loadTaskSchema error:', e);
            }
        },

        switchBacklogSubTab(t) {
            this.backlogSubTab = t;
            this.loadBacklog();
        },

        sortBacklog(field) {
            if (this.backlogSort.field === field) {
                this.backlogSort.asc = !this.backlogSort.asc;
            } else {
                this.backlogSort.field = field;
                this.backlogSort.asc = false;
            }
        },

        sortedBacklogRows() {
            const f = this.backlogSort.field;
            const asc = this.backlogSort.asc;
            return [...this.backlogRows].sort((a, b) => {
                let va = a[f], vb = b[f];
                if (va == null) va = '';
                if (vb == null) vb = '';
                if (typeof va === 'number' && typeof vb === 'number') {
                    return asc ? va - vb : vb - va;
                }
                return asc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
            });
        },

        formatBacklogState(r) {
            if (r.source === 'atom') {
                return r.lifecycle || '-';
            }
            return r.entry_status || '未開始';
        },

        async openBacklogItem(r) {
            if (r.source === 'entry') {
                await this.openEntryEdit(r);
            } else {
                await this.openAtomEdit(r);
            }
        },

        async openEntryEdit(r) {
            if (!this.backlogTaskSchema) {
                await this.loadTaskSchema();
            }
            if (!this.backlogTaskSchema) {
                alert('無法載入 task schema');
                return;
            }
            // 取得完整 entry 資料(含 field_values)
            let entry;
            try {
                const resp = await fetch('/beakbroodnest/api/entries/' + r.entry_id);
                if (!resp.ok) throw new Error('GET entry failed');
                entry = await resp.json();
            } catch (e) {
                console.error('GET entry error:', e);
                alert('讀取 entry 失敗');
                return;
            }
            if (typeof window.openEntryModal !== 'function') {
                alert('openEntryModal 未載入');
                return;
            }
            const self = this;
            window.openEntryModal({
                schema: this.backlogTaskSchema,
                schemaCode: 'task',
                rawText: entry.raw_text || '',
                fieldValues: entry.field_values || {},
                mode: 'edit',
                onSave: async ({ rawText, fieldValues }) => {
                    try {
                        const resp = await fetch('/beakbroodnest/api/entries/' + r.entry_id, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                raw_text: rawText,
                                field_values: fieldValues,
                            }),
                        });
                        if (!resp.ok) {
                            const err = await resp.json().catch(() => ({}));
                            alert('儲存失敗: ' + (err.error || resp.status));
                            return;
                        }
                        await self.loadBacklog();
                        await self.loadBacklogCounts();
                    } catch (e) {
                        console.error('save entry error:', e);
                        alert('儲存失敗: ' + e.message);
                    }
                },
            });
        },

        async openAtomEdit(r) {
            // 取得完整 atom 資料
            let atom;
            try {
                const resp = await fetch('/beakbroodnest/api/atoms/' + r.atom_id);
                if (!resp.ok) throw new Error('GET atom failed');
                atom = await resp.json();
            } catch (e) {
                console.error('GET atom error:', e);
                alert('讀取 atom 失敗');
                return;
            }
            this.atomEdit.atom_id = atom.id;
            this.atomEdit.title = atom.title || '';
            this.atomEdit.lifecycle = atom.lifecycle || 'active';
            this.atomEdit.owner = atom.owner || '';
            this.atomEdit.vitality_score = atom.vitality_score;
            this.atomEdit.content = atom.content || '';
            this.atomEdit.content_json = atom.content_json || null;
            this.atomEdit.saving = false;

            // 顯示 modal
            const modalEl = document.getElementById('atomEditModal');
            if (!this.atomEdit.modal) {
                this.atomEdit.modal = new bootstrap.Modal(modalEl);
            }
            this.atomEdit.modal.show();

            // 等 modal 顯示後 mount CardEditor
            const self = this;
            modalEl.addEventListener('shown.bs.modal', function onceShown() {
                modalEl.removeEventListener('shown.bs.modal', onceShown);
                if (typeof window.CardEditor !== 'function') {
                    alert('CardEditor 未載入');
                    return;
                }
                if (self.atomEdit.editor) {
                    self.atomEdit.editor.destroy();
                }
                self.atomEdit.editor = new window.CardEditor();
                const editorEl = document.getElementById('atomEditEditor');
                editorEl.innerHTML = '';
                self.atomEdit.editor.create(editorEl, {
                    content: self.atomEdit.content,
                    contentJson: self.atomEdit.content_json,
                });
            }, { once: true });
        },

        closeAtomEdit() {
            if (this.atomEdit.editor) {
                this.atomEdit.editor.destroy();
                this.atomEdit.editor = null;
            }
            if (this.atomEdit.modal) {
                this.atomEdit.modal.hide();
            }
        },

        async saveAtomEdit() {
            if (!this.atomEdit.editor) {
                alert('編輯器未初始化');
                return;
            }
            this.atomEdit.saving = true;
            try {
                const editor = this.atomEdit.editor.editor;
                const markdown = editor.storage.markdown
                    ? editor.storage.markdown.getMarkdown()
                    : '';
                const json = editor.getJSON();
                const payload = {
                    title: this.atomEdit.title,
                    lifecycle: this.atomEdit.lifecycle,
                    content: markdown,
                    content_json: json,
                    force_owner_override: this.atomEdit.owner !== 'ethan',
                };
                const resp = await fetch('/beakbroodnest/api/atoms/' + this.atomEdit.atom_id, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    alert('儲存失敗: ' + (err.error || resp.status));
                    return;
                }
                this.closeAtomEdit();
                await this.loadBacklog();
                await this.loadBacklogCounts();
            } catch (e) {
                console.error('save atom error:', e);
                alert('儲存失敗: ' + e.message);
            } finally {
                this.atomEdit.saving = false;
            }
        },
    };
}
