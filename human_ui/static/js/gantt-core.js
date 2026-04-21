/**
 * BeakGantt.Core -- Frappe Gantt 版本抽象層 + 初始化
 *
 * Frappe Gantt 0.6.1 確認事項（2026-04-22 驗證）：
 *   - callback 名稱：date_change, progress_change, view_change（無 on_ 前綴）
 *   - dependencies 格式：逗號分隔的 task ID 字串
 *   - task 物件：_start / _end 是 Date，name / id / progress 是原始值
 *   - custom_class 會加到 <g class="bar-wrapper {custom_class}">
 *   - Arrow <path> 有 data-from / data-to 屬性（task ID）
 *   - Arrow 存放在 <g class="arrow"> 容器裡（layers.arrow）
 */
window.BeakGantt = window.BeakGantt || {};

(function(BG) {
'use strict';

BG.Core = {

    /** @type {Gantt|null} */
    _instance: null,

    /** @type {Array} 原始 tasks 資料（含 _baseline 等擴充欄位） */
    _rawTasks: [],

    /** @type {string} 目前視圖模式 */
    _viewMode: 'Day',

    /** @type {string} 白板 slug */
    _slug: '',

    /**
     * 建立 Frappe Gantt 實例
     * @param {string} selector - CSS selector
     * @param {Array} rawTasks - API 回傳的 tasks 陣列（含 _baseline 等）
     * @param {Object} handlers - { onDateChange, onProgressChange, onClick }
     * @returns {Gantt}
     */
    createGantt: function(selector, rawTasks, handlers) {
        BG.Core._rawTasks = rawTasks;

        var frappeTasks = rawTasks.map(function(t) {
            return BG.Core._toFrappeTask(t);
        });

        var options = BG.Core._buildOptions(handlers);
        BG.Core._instance = new Gantt(selector, frappeTasks, options);
        return BG.Core._instance;
    },

    /**
     * 將 API task 轉為 Frappe Gantt task 格式
     * 處理 actual 為 null 時的 fallback（用 baseline 代入 + 標記 bar-not-started）
     */
    _toFrappeTask: function(t) {
        var hasActual = !!(t.start || t.end);
        var baseline = t._baseline;

        var start, end, customClass;

        if (hasActual) {
            start = t.start || t.end;
            end = t.end || t.start;
            customClass = t.custom_class || 'bar-urgency-M';
        } else if (baseline && (baseline.start || baseline.end)) {
            start = baseline.start || baseline.end;
            end = baseline.end || baseline.start;
            customClass = 'bar-not-started';
        } else {
            var today = new Date().toISOString().slice(0, 10);
            var d3 = new Date();
            d3.setDate(d3.getDate() + 3);
            start = today;
            end = d3.toISOString().slice(0, 10);
            customClass = 'bar-not-started';
        }

        if (end < start) {
            var tmp = end; end = start; start = tmp;
        }

        return {
            id: t.id,
            name: t.name,
            start: start,
            end: end,
            progress: t.progress || 0,
            dependencies: t.dependencies || '',
            custom_class: customClass,
            _entry_id: t._entry_id,
            _urgency: t._urgency,
            _status: t._status,
            _category: t._category,
            _baseline: t._baseline,
            _delta_days: t._delta_days,
            _has_actual: hasActual,
        };
    },

    /**
     * 建構 Frappe Gantt 選項（吸收版本差異）
     * @private
     */
    _buildOptions: function(handlers) {
        handlers = handlers || {};

        return {
            // Frappe Gantt 0.6.1 事件名稱（無 on_ 前綴）
            date_change: function(task, start, end) {
                if (handlers.onDateChange) {
                    handlers.onDateChange(task, start, end);
                }
            },
            progress_change: function(task, progress) {
                if (handlers.onProgressChange) {
                    handlers.onProgressChange(task, progress);
                }
            },
            view_mode: BG.Core._viewMode,
            date_format: 'YYYY-MM-DD',
            popup_trigger: 'click',
            custom_popup_html: function(task) {
                return BG.Core._buildPopup(task);
            },
        };
    },

    /**
     * 建構 popup HTML
     * @private
     */
    _buildPopup: function(task) {
        var startStr = task._start ? task._start.toISOString().slice(0, 10) : '-';
        var endStr = task._end ? task._end.toISOString().slice(0, 10) : '-';
        var baseline = task._baseline;
        var progress = task.progress || 0;

        var h = [];
        h.push('<div style="padding:12px;min-width:240px;font-size:12px;">');
        h.push('<div style="font-size:14px;font-weight:600;margin-bottom:8px;">' +
               task.name + '</div>');

        // 狀態 + 進度
        var statusLabel = {not_started: '尚未開始', in_progress: '進行中', completed: '已完成'};
        var sl = statusLabel[task._status] || task._status || '-';
        h.push('<div style="margin-bottom:6px;">');
        h.push('<span style="color:#495057;">狀態: </span>' + sl);
        if (task._has_actual && progress > 0) {
            h.push(' &nbsp; <span style="color:#495057;">進度: </span>' + progress + '%');
        }
        h.push('</div>');

        // 實際日期
        h.push('<table style="font-size:11px;color:#6c757d;border-spacing:0 2px;">');
        if (task._has_actual) {
            h.push('<tr><td style="padding-right:8px;color:#495057;">實際:</td>' +
                   '<td>' + startStr + ' ~ ' + endStr + '</td></tr>');
        } else {
            h.push('<tr><td colspan="2" style="color:#adb5bd;">尚未開始（顯示原計畫）</td></tr>');
        }

        // 原計畫
        if (baseline && (baseline.start || baseline.end)) {
            h.push('<tr><td style="padding-right:8px;color:#495057;">原計畫:</td>' +
                   '<td>' + (baseline.start || '?') + ' ~ ' + (baseline.end || '?') + '</td></tr>');
        }
        h.push('</table>');

        // 偏差
        if (task._delta_days !== null && task._delta_days !== undefined && task._delta_days !== 0) {
            var delta = task._delta_days;
            var dColor = delta > 0 ? 'var(--bs-danger, #dc3545)' : 'var(--bs-success, #198754)';
            var dText = delta > 0 ? ('逾期 ' + delta + ' 天') : ('提前 ' + Math.abs(delta) + ' 天');
            h.push('<div style="margin-top:6px;font-weight:600;color:' + dColor + ';">' + dText + '</div>');
        }

        // 分類
        if (task._category) {
            h.push('<div style="font-size:10px;color:#adb5bd;margin-top:6px;border-top:1px solid #eee;padding-top:4px;">' +
                   task._category + '</div>');
        }

        h.push('</div>');
        return h.join('');
    },

    /**
     * 切換視圖模式
     */
    setViewMode: function(mode) {
        BG.Core._viewMode = mode;
        if (BG.Core._instance) {
            BG.Core._instance.change_view_mode(mode);
        }
    },

    /**
     * 取得 raw task by ID
     */
    getRawTask: function(taskId) {
        for (var i = 0; i < BG.Core._rawTasks.length; i++) {
            if (BG.Core._rawTasks[i].id === taskId) {
                return BG.Core._rawTasks[i];
            }
        }
        return null;
    }
};

})(window.BeakGantt);
