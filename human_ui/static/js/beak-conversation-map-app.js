/**
 * BeakConversationMap -- Alpine.js 外殼
 * 掛載於 observe.html 的「對話拓樸」sub-tab
 */
(function() {
    'use strict';

    window.beakCMApp = function() {
        return {
            traces: [],
            selectedTraceId: null,
            loadingTraces: false,
            loadingTrace: false,
            projectPath: '',
            errorMsg: '',
            _chart: null,
            // 點選 node 後展示用
            selectedTurn: null,
            loadingTurnFull: false,
            wrapContent: false,  // 詳情內容是否自動折行 (預設不折,水平捲動)
            // trace summary
            traceSummary: null,
            // trace 清單 filter & pagination
            limit: 100,
            filterWithAgent: true,
            filterWithCcp: false,
            filterOnlyUnanswered: false,
            filterMinTurns: 0,

            init: function() {
                this.loadTraces();
            },

            loadTraces: function(append) {
                var self = this;
                self.loadingTraces = true;
                self.errorMsg = '';
                var params = ['limit=' + self.limit];
                if (self.projectPath) params.push('project_path=' + encodeURIComponent(self.projectPath));
                if (self.filterWithAgent) params.push('with_agent=1');
                if (self.filterWithCcp) params.push('with_ccp=1');
                if (self.filterOnlyUnanswered) params.push('only_unanswered=1');
                if (self.filterMinTurns > 0) params.push('min_turns=' + self.filterMinTurns);
                var url = '/beakbroodnest/api/conversation-map/traces?' + params.join('&');
                fetch(url)
                    .then(function(r) {
                        if (!r.ok) throw new Error('HTTP ' + r.status);
                        return r.json();
                    })
                    .then(function(data) {
                        self.traces = Array.isArray(data) ? data : [];
                        self.loadingTraces = false;
                    })
                    .catch(function(e) {
                        self.errorMsg = '載入 traces 失敗: ' + e.message;
                        self.loadingTraces = false;
                    });
            },

            loadMore: function() {
                this.limit += 100;
                this.loadTraces();
            },

            applyFilters: function() {
                this.limit = 100;
                this.loadTraces();
            },

            selectTrace: function(traceId) {
                var self = this;
                if (self.loadingTrace) return;
                self.selectedTraceId = traceId;
                self.loadingTrace = true;
                self.errorMsg = '';
                self.selectedTurn = null;
                self.traceSummary = null;
                fetch('/beakbroodnest/api/conversation-map/trace/' + encodeURIComponent(traceId))
                    .then(function(r) {
                        if (!r.ok) throw new Error('HTTP ' + r.status);
                        return r.json();
                    })
                    .then(function(data) {
                        self.loadingTrace = false;
                        if (data.error) { self.errorMsg = data.error; return; }
                        if (!data.turns || data.turns.length === 0) {
                            self.errorMsg = '此 trace 無 turn 資料';
                            return;
                        }
                        self.traceSummary = self.computeSummary(data.turns);
                        var el = document.getElementById('beak-cm-container');
                        if (!el) return;
                        if (!self._chart) {
                            self._chart = BeakConversationMapChart.create(el, {});
                        }
                        self._chart.drawTraceMode(data.turns, function(turn) {
                            self.onNodeClick(turn);
                        });
                    })
                    .catch(function(e) {
                        self.errorMsg = '載入 trace 失敗: ' + e.message;
                        self.loadingTrace = false;
                    });
            },

            computeSummary: function(turns) {
                var actorSet = {}, hasAgent = false, hasAssistant = false, hasSidechain = false;
                for (var i=0;i<turns.length;i++) {
                    var a = turns[i].actor_id || (turns[i].role === 'user' ? 'human' : 'cc-main');
                    actorSet[a] = (actorSet[a]||0)+1;
                    if (/^cc-main:agent:/.test(a)) hasAgent = true;
                    if (turns[i].span_kind === 'assistant_message') hasAssistant = true;
                    if (turns[i].is_sidechain) hasSidechain = true;
                }
                var actors = Object.keys(actorSet).map(function(k){return {name:k,count:actorSet[k]};});
                actors.sort(function(a,b){return b.count - a.count;});
                return {
                    actors: actors,
                    actorCount: actors.length,
                    turnCount: turns.length,
                    hasAgent: hasAgent,
                    hasAssistant: hasAssistant,
                    hasSidechain: hasSidechain,
                };
            },

            onNodeClick: function(turn) {
                // 先放入截斷版的內容（已隨 trace 一起回來）
                this.selectedTurn = Object.assign({}, turn);
                // 若有更完整內容（content_full_len > content.length），lazy load 全文
                var truncated = (turn.content_full_len || 0) > (turn.content || '').length;
                if (!truncated) return;
                var self = this;
                self.loadingTurnFull = true;
                fetch('/beakbroodnest/api/conversation-map/turn/' + encodeURIComponent(turn.id))
                    .then(function(r){ return r.ok ? r.json() : null; })
                    .then(function(full){
                        self.loadingTurnFull = false;
                        if (full && self.selectedTurn && self.selectedTurn.id === turn.id) {
                            self.selectedTurn.content = full.content || self.selectedTurn.content;
                            self.selectedTurn.tool_params = full.tool_params || self.selectedTurn.tool_params;
                            self.selectedTurn.content_full_len = (full.content || '').length;
                        }
                    })
                    .catch(function(){ self.loadingTurnFull = false; });
            },

            closeNode: function() { this.selectedTurn = null; },

            actorBadgeClass: function(actor) {
                if (!actor) return 'bg-secondary';
                if (actor === 'human') return 'bg-secondary';
                if (actor === 'cc-main') return 'bg-primary';
                if (/^cc-main:agent:/.test(actor)) return 'bg-info text-dark';
                if (/^cc-p:/.test(actor)) return 'text-white';
                if (actor === 'hook') return 'bg-warning text-dark';
                return 'bg-light text-dark';
            },

            formatToolParams: function(p) {
                if (!p) return '';
                try { return JSON.stringify(p, null, 2); }
                catch(e) { return String(p); }
            },

            formatTime: function(ts) {
                if (!ts) return '-';
                try {
                    return new Date(ts).toLocaleString('zh-TW', {
                        month: '2-digit', day: '2-digit',
                        hour: '2-digit', minute: '2-digit',
                    });
                } catch(e) { return String(ts).slice(0, 16); }
            },

            shortTraceId: function(id) {
                if (!id) return '-';
                return id.length > 8 ? id.slice(0, 8) + '…' : id;
            },
        };
    };

})();
