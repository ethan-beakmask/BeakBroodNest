/**
 * BeakGantt -- BeakCortex Project Dashboard 整合
 *
 * 從 /api/project/<slug>/beak-gantt 載入資料，
 * 拖拉變更自動寫回 DB，支援 undo 1 步。
 */
(function() {
    'use strict';

    var SLUG = '';
    var _gantt = null;
    var _undoStack = [];  // [{taskId, field, oldValue}, ...]
    var MAX_UNDO = 1;

    function _toast(msg, isError) {
        var area = document.getElementById('toast-area');
        if (!area) return;
        var el = document.createElement('div');
        el.className = 'toast-msg' + (isError ? ' error' : '');
        el.textContent = msg;
        area.appendChild(el);
        requestAnimationFrame(function() { el.classList.add('show'); });
        setTimeout(function() {
            el.classList.remove('show');
            setTimeout(function() { el.remove(); }, 300);
        }, 2500);
    }

    /** end_date 從 BeakGantt 轉回 DB：減一天（BeakGantt end 是 exclusive） */
    function _endDateForDb(dateStr) {
        if (!dateStr) return '';
        var d = new Date(dateStr);
        d.setDate(d.getDate() - 1);
        return d.toISOString().slice(0, 10);
    }

    /** 存 undo 紀錄（task 操作透過 gantt.pushUndo） */
    function _pushUndo(taskId, changes, oldValues) {
        if (_gantt) _gantt.pushUndo({ type: 'task', taskId: taskId, changes: changes, oldValues: oldValues });
        _updateUndoBtn();
    }

    function _updateUndoBtn() {
        var btn = document.getElementById('bk-undo-btn');
        var has = _gantt && _gantt.hasUndo();
        if (btn) {
            btn.disabled = !has;
            btn.style.opacity = has ? '1' : '0.4';
        }
    }

    /** PATCH 到 server */
    function _patchTask(taskId, body) {
        return fetch('/beakcortex/api/project/' + SLUG + '/beak-gantt/' + taskId, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        })
        .then(function(r) { return r.json(); })
        .then(function(resp) {
            if (resp.ok) {
                _toast('Saved');
            } else {
                _toast('Error: ' + (resp.error || 'unknown'), true);
            }
            return resp;
        })
        .catch(function() { _toast('Network error', true); });
    }

    /** 載入資料 */
    function _loadData() {
        fetch('/beakcortex/api/project/' + SLUG + '/beak-gantt')
            .then(function(r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function(data) {
                _gantt.clearAll();
                _gantt.parse(data);
                _toast('Loaded ' + (data.tasks || []).length + ' tasks');
            })
            .catch(function(e) {
                console.error('BeakGantt load error:', e);
                _toast('Load failed', true);
            });
    }

    /** 公開入口 */
    window.initBeakGantt = function(slug) {
        SLUG = slug;

        if (!_gantt) {
            _gantt = BeakGanttChart.create('#beak-gantt-container', {
                gridWidth: 560,
                viewMode: 'day',
                customColumns: [
                    { key: 'category', label: '分類', width: 60 },
                    { key: 'planned_start', label: '預計開始', width: 82 },
                    { key: 'actual_end', label: '實際結束', width: 82 },
                ],
                customData: {},  // 動態填充

                onTaskUpdate: function(task, changes) {
                    if (!task._entry_id) return;

                    // 收集 old values 供 undo
                    var oldValues = {};
                    var body = {};

                    if (changes.start_date !== undefined) {
                        oldValues.actual_start = task._prev_start || '';
                        body.actual_start = changes.start_date + 'T00:00';
                    }
                    if (changes.end_date !== undefined) {
                        oldValues.actual_end = task._prev_end || '';
                        body.actual_end = _endDateForDb(changes.end_date) + 'T00:00';
                    }
                    if (changes.progress !== undefined) {
                        oldValues.progress = task._prev_progress || '0';
                        body.progress = String(Math.round(changes.progress * 100));
                        if (changes.progress >= 1) body.status = 'done';
                        else if (changes.progress > 0) body.status = 'in_progress';
                        else body.status = 'pending';
                    }

                    _pushUndo(task.id, body, oldValues);
                    _patchTask(task.id, body);

                    // 記錄當前值供下次 undo
                    task._prev_start = body.actual_start || task._prev_start;
                    task._prev_end = body.actual_end || task._prev_end;
                    task._prev_progress = body.progress || task._prev_progress;
                },

                onTaskCreate: function(parentId) {
                    var today = new Date().toISOString().slice(0, 10);
                    fetch('/beakcortex/api/project/' + SLUG + '/beak-gantt', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            text: 'New Task',
                            parent: parentId,
                            start_date: today,
                            duration: 3,
                        }),
                    })
                    .then(function(r) { return r.json(); })
                    .then(function(resp) {
                        if (resp.ok) {
                            _toast('Created task #' + resp.tid);
                            _loadData();
                        } else {
                            _toast('Create error', true);
                        }
                    })
                    .catch(function() { _toast('Network error', true); });
                },

                onLinkCreate: function(sourceId, targetId) {
                    fetch('/beakcortex/api/project/' + SLUG + '/beak-gantt/link', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({source: sourceId, target: targetId}),
                    })
                    .then(function(r) { return r.json(); })
                    .then(function(resp) {
                        if (resp.ok) _toast('Link saved');
                        else _toast('Link error', true);
                        _updateUndoBtn();
                    })
                    .catch(function() { _toast('Network error', true); });
                },

                onLinkDelete: function(sourceId, targetId) {
                    fetch('/beakcortex/api/project/' + SLUG + '/beak-gantt/link', {
                        method: 'DELETE',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({source: sourceId, target: targetId}),
                    })
                    .then(function(r) { return r.json(); })
                    .then(function(resp) {
                        if (resp.ok) _toast('Link deleted');
                        else _toast('Delete link error', true);
                        _updateUndoBtn();
                    })
                    .catch(function() { _toast('Network error', true); });
                },

                onTaskDelete: function(taskId, removedIds) {
                    fetch('/beakcortex/api/project/' + SLUG + '/beak-gantt/' + taskId, {
                        method: 'DELETE',
                    })
                    .then(function(r) { return r.json(); })
                    .then(function(resp) {
                        if (resp.ok) {
                            _toast('Deleted ' + resp.deleted.length + ' item(s)');
                            _loadData();
                        } else {
                            _toast('Delete error', true);
                        }
                    })
                    .catch(function() { _toast('Network error', true); });
                },

                onTaskReorder: function(taskId, newParentId, newIndex) {
                    _toast('Reorder: #' + taskId + ' -> parent #' + newParentId);
                },
            });
        }

        // 初始化時記錄 prev values + 建構 customData
        var origParse = _gantt.parse.bind(_gantt);
        _gantt.parse = function(data) {
            var tasks = data.tasks || data.data || [];
            var cd = {};
            for (var i = 0; i < tasks.length; i++) {
                var t = tasks[i];
                t._prev_start = t.start_date || '';
                t._prev_end = t.end_date || '';
                t._prev_progress = String(Math.round((t.progress || 0) * 100));
                // 建構 customData
                cd[t.id] = {
                    category: t._category || '',
                    planned_start: (t._planned_start || '').replace('T', ' ').slice(0, 16),
                    actual_end: (t._actual_end || '').replace('T', ' ').slice(0, 16),
                };
            }
            _gantt._opts.customData = cd;
            origParse(data);
        };

        _loadData();
        _undoStack = [];
        _updateUndoBtn();
    };

    /** Undo: 退回上一步（支援 task + link） */
    window.beakGanttUndo = function() {
        if (!_gantt || !_gantt.hasUndo()) return;
        var result = _gantt.undo();
        if (!result) return;
        _updateUndoBtn();

        if (result.type === 'task' && result.oldValues) {
            _patchTask(result.taskId, result.oldValues).then(function() {
                _toast('Undo');
                _loadData();
            });
        } else if (result.type === 'link_undo_create' || result.type === 'link_undo_delete') {
            _toast('Undo: ' + result.type);
        }
    };

    /** View mode 切換 */
    window.setBeakGanttView = function(mode) {
        if (_gantt) _gantt.setViewMode(mode);
        document.querySelectorAll('#bk-gantt-panel .bk-view-pill').forEach(function(el) {
            el.classList.toggle('active', el.dataset.view === mode);
        });
    };

    /** 展開/收合 */
    window.beakGanttExpand = function(open) {
        if (_gantt) open ? _gantt.expandAll() : _gantt.collapseAll();
    };

    /** Layout 切換 */
    window.setBeakGanttLayout = function(mode) {
        if (_gantt) _gantt.setLayout(mode);
        document.querySelectorAll('#bk-gantt-panel .bk-view-pill[data-lay]').forEach(function(el) {
            el.classList.toggle('active', el.dataset.lay === mode);
        });
    };
})();
