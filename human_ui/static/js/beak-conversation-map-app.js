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

            init: function() {
                this.loadTraces();
            },

            loadTraces: function() {
                var self = this;
                self.loadingTraces = true;
                self.errorMsg = '';
                var url = '/beakbroodnest/api/conversation-map/traces?limit=30';
                if (self.projectPath) {
                    url += '&project_path=' + encodeURIComponent(self.projectPath);
                }
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

            selectTrace: function(traceId) {
                var self = this;
                if (self.loadingTrace) return;
                self.selectedTraceId = traceId;
                self.loadingTrace = true;
                self.errorMsg = '';
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
                        var el = document.getElementById('beak-cm-container');
                        if (!el) return;
                        if (!self._chart) {
                            self._chart = BeakConversationMapChart.create(el, {});
                        }
                        self._chart.drawTraceMode(data.turns);
                    })
                    .catch(function(e) {
                        self.errorMsg = '載入 trace 失敗: ' + e.message;
                        self.loadingTrace = false;
                    });
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
