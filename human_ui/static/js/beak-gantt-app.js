/**
 * BeakGantt -- BeakCortex Project Dashboard 整合
 *
 * 從 /api/project/<slug>/beak-gantt 載入資料，
 * 拖拉變更自動寫回 DB，支援 undo 1 步。
 * 支援三種 summary mode: summary-bar / no-bar / outline-only
 */
(function() {
    'use strict';

    var SLUG = '';
    var _gantt = null;

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

    function _endDateForDb(dateStr) {
        if (!dateStr) return '';
        var d = new Date(dateStr);
        d.setDate(d.getDate() - 1);
        return d.toISOString().slice(0, 10);
    }

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

    function _patchTask(taskId, body) {
        return fetch('/beakcortex/api/project/' + SLUG + '/beak-gantt/' + taskId, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        })
        .then(function(r) { return r.json(); })
        .then(function(resp) {
            if (resp.ok) _toast('Saved');
            else _toast('Error: ' + (resp.error || 'unknown'), true);
            return resp;
        })
        .catch(function() { _toast('Network error', true); });
    }

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

    window.initBeakGantt = function(slug) {
        SLUG = slug;

        if (!_gantt) {
            _gantt = BeakGanttChart.create('#beak-gantt-container', {
                gridWidth: 560,
                viewMode: 'day',
                summaryMode: 'summary-bar',
                summaryBarColor: '#266ACF',
                noBarBgColor: '#3A9CFD',
                outlineColors: {
                    card: '#3A9CFD',
                    taskColors: ['#F0F0FF', '#F7FFF5', '#F0F9FF'],
                },
                customColumns: [],
                customData: {},

                onTaskUpdate: function(task, changes) {
                    if (!task._entry_id) return;
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
                    task._prev_start = body.actual_start || task._prev_start;
                    task._prev_end = body.actual_end || task._prev_end;
                    task._prev_progress = body.progress || task._prev_progress;
                },

                onTaskCreate: function(parentId) {
                    var today = new Date().toISOString().slice(0, 10);
                    fetch('/beakcortex/api/project/' + SLUG + '/beak-gantt', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ text: 'New Task', parent: parentId, start_date: today, duration: 3 }),
                    })
                    .then(function(r) { return r.json(); })
                    .then(function(resp) {
                        if (resp.ok) { _toast('Created task #' + resp.tid); _loadData(); }
                        else _toast('Create error', true);
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
                        if (resp.ok) { _toast('Deleted ' + resp.deleted.length + ' item(s)'); _loadData(); }
                        else _toast('Delete error', true);
                    })
                    .catch(function() { _toast('Network error', true); });
                },

                onTaskReorder: function(taskId, newParentId, newIndex) {
                    _toast('Reorder: #' + taskId + ' -> parent #' + newParentId);
                },
            });
        }

        // Wrap parse to prep prev values
        var origParse = _gantt.parse.bind(_gantt);
        _gantt.parse = function(data) {
            var tasks = data.tasks || data.data || [];
            for (var i = 0; i < tasks.length; i++) {
                var t = tasks[i];
                t._prev_start = t.start_date || '';
                t._prev_end = t.end_date || '';
                t._prev_progress = String(Math.round((t.progress || 0) * 100));
            }
            origParse(data);
        };

        _loadData();
        _updateUndoBtn();
    };

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

    window.setBeakGanttView = function(mode) {
        if (_gantt) _gantt.setViewMode(mode);
        document.querySelectorAll('#bk-gantt-panel .bk-view-pill').forEach(function(el) {
            el.classList.toggle('active', el.dataset.view === mode);
        });
    };

    window.beakGanttExpand = function(open) {
        if (_gantt) open ? _gantt.expandAll() : _gantt.collapseAll();
    };

    window.setBeakGanttLayout = function(mode) {
        if (_gantt) _gantt.setLayout(mode);
        document.querySelectorAll('#bk-gantt-panel .bk-view-pill[data-lay]').forEach(function(el) {
            el.classList.toggle('active', el.dataset.lay === mode);
        });
    };

    window.setBeakGanttSummaryMode = function(mode) {
        if (_gantt) _gantt.setSummaryMode(mode);
        document.querySelectorAll('#bk-gantt-panel .bk-view-pill[data-smode]').forEach(function(el) {
            el.classList.toggle('active', el.dataset.smode === mode);
        });
    };

    // ---- Color persistence (DB via API) ----

    var _COLORS_API = '/beakcortex/api/beak-gantt/colors';
    var _cachedColors = null;

    function _loadColorsFromServer(cb) {
        fetch(_COLORS_API)
            .then(function(r) { return r.json(); })
            .then(function(data) { _cachedColors = data; if (cb) cb(data); })
            .catch(function() { if (cb) cb(null); });
    }

    function _saveColorsToServer(colors, cb) {
        fetch(_COLORS_API, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(colors),
        })
        .then(function(r) { return r.json(); })
        .then(function(resp) { if (cb) cb(resp.ok); })
        .catch(function() { if (cb) cb(false); });
    }

    function _applyColorsToGantt(colors) {
        if (!_gantt || !colors) return;
        _gantt._opts.summaryBarColor = colors.summaryBarColor;
        _gantt._opts.noBarBgColor = colors.noBarBgColor;
        _gantt._opts.outlineColors = {
            card: colors.outlineCard,
            taskColors: colors.taskColors.slice(),
        };
        _gantt.render();
    }

    function _populatePanel(colors) {
        var g = function(id) { return document.getElementById(id); };
        g('bk-clr-summary').value = colors.summaryBarColor;
        g('bk-clr-nobar').value = colors.noBarBgColor;
        g('bk-clr-ol-card').value = colors.outlineCard;
        g('bk-clr-ol-t1').value = colors.taskColors[0] || '#F0F0FF';
        g('bk-clr-ol-t2').value = colors.taskColors[1] || '#F7FFF5';
        var has3 = colors.taskColors.length >= 3;
        g('bk-clr-ol-t3-on').checked = has3;
        g('bk-clr-ol-t3').disabled = !has3;
        g('bk-clr-ol-t3').value = has3 ? colors.taskColors[2] : '#F0F9FF';
    }

    function _readPanel() {
        var g = function(id) { return document.getElementById(id); };
        var tc = [g('bk-clr-ol-t1').value, g('bk-clr-ol-t2').value];
        if (g('bk-clr-ol-t3-on').checked) tc.push(g('bk-clr-ol-t3').value);
        return {
            summaryBarColor: g('bk-clr-summary').value,
            noBarBgColor: g('bk-clr-nobar').value,
            outlineCard: g('bk-clr-ol-card').value,
            taskColors: tc,
        };
    }

    window.toggleColorPanel = function() {
        var panel = document.getElementById('bk-color-panel');
        var showing = panel.style.display !== 'none';
        if (showing) {
            panel.style.display = 'none';
        } else {
            if (_cachedColors) {
                _populatePanel(_cachedColors);
                panel.style.display = '';
            } else {
                _loadColorsFromServer(function(colors) {
                    if (colors) _populatePanel(colors);
                    panel.style.display = '';
                });
            }
        }
    };

    window.applyGanttColors = function() {
        var colors = _readPanel();
        _cachedColors = colors;
        _applyColorsToGantt(colors);
        _saveColorsToServer(colors, function(ok) {
            _toast(ok ? '配色已儲存' : '儲存失敗', !ok);
        });
    };

    window.resetGanttColors = function() {
        _loadColorsFromServer(function(defaults) {
            // 從 API 取得預設值（後端定義的 _DEFAULT_GANTT_COLORS）
            // 清除 DB 中的自訂值 -> 存回預設
            if (!defaults) return;
            _cachedColors = defaults;
            _populatePanel(defaults);
            _applyColorsToGantt(defaults);
            _toast('已還原預設配色');
        });
    };

    // 色3 checkbox toggle
    document.addEventListener('DOMContentLoaded', function() {
        var cb = document.getElementById('bk-clr-ol-t3-on');
        if (cb) cb.addEventListener('change', function() {
            document.getElementById('bk-clr-ol-t3').disabled = !this.checked;
        });
    });

    // 啟動時從 DB 載入配色
    var _origInitForColors = window.initBeakGantt;
    window.initBeakGantt = function(slug) {
        _origInitForColors(slug);
        _loadColorsFromServer(function(colors) {
            if (colors) {
                _cachedColors = colors;
                _applyColorsToGantt(colors);
            }
        });
    };
})();
