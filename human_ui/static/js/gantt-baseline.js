/**
 * BeakGantt.Baseline -- 基線對比 SVG 後處理
 *
 * 在 Frappe Gantt 渲染完成後，為每個 bar-wrapper 注入 baseline 參考條。
 *
 * 視覺規格：
 * - 4px 高，位於 actual bar 正下方
 * - stroke="#9ca3af" 透明度 0.6，虛線 stroke-dasharray="4,2"
 * - actual 為 null 時改用實線（表示「原計畫待執行」）
 * - actual 與 baseline 完全相等時不畫（避免視覺雜訊）
 * - baseline_start > baseline_end 不畫，加 icon
 * - 偏差標籤 +2d / -1d 在 actual 右端外 8px
 *
 * MutationObserver 策略：
 * - injection flag (_bgInjecting) 防止自觸發迴圈
 * - 監聽 svg.gantt，50ms debounce
 */
window.BeakGantt = window.BeakGantt || {};

(function(BG) {
'use strict';

var BASELINE_CLASS = 'bg-baseline-rect';
var DELTA_CLASS = 'bg-delta-label';
var WARN_CLASS = 'bg-baseline-warn';
var NS = 'http://www.w3.org/2000/svg';
var DEBOUNCE_MS = 50;

var _observer = null;
var _debounceTimer = null;
var _svgEl = null;
var _bgInjecting = false;  // injection flag 防 MutationObserver 自觸發

BG.Baseline = {

    /**
     * 啟動 baseline 渲染
     * @param {Element} containerEl - #frappe-gantt 容器
     */
    init: function(containerEl) {
        _svgEl = containerEl.querySelector('svg.gantt');
        if (!_svgEl) return;

        BG.Baseline.render();
        _startObserver();
    },

    /**
     * 掃描所有 bar-wrapper，注入 baseline 層
     */
    render: function() {
        if (!_svgEl) return;

        _bgInjecting = true;
        _clearAll();

        var wrappers = _svgEl.querySelectorAll('.bar-wrapper');
        for (var i = 0; i < wrappers.length; i++) {
            _processWrapper(wrappers[i]);
        }

        _bgInjecting = false;
    },

    /**
     * 清除所有 baseline 元素
     */
    clear: function() {
        _bgInjecting = true;
        _clearAll();
        _bgInjecting = false;
    },

    /**
     * 暫停監聽
     */
    disconnect: function() {
        if (_observer) {
            _observer.disconnect();
            _observer = null;
        }
        if (_debounceTimer) {
            clearTimeout(_debounceTimer);
            _debounceTimer = null;
        }
    },

    /**
     * 重新啟動
     * @param {Element} containerEl
     */
    reconnect: function(containerEl) {
        BG.Baseline.disconnect();
        _svgEl = containerEl.querySelector('svg.gantt');
        if (!_svgEl) return;

        BG.Baseline.render();
        _startObserver();
    }
};


/**
 * 處理單一 bar-wrapper
 * @private
 */
function _processWrapper(wrapper) {
    var taskId = wrapper.getAttribute('data-id');
    if (!taskId) return;

    var rawTask = BG.Core.getRawTask(taskId);
    if (!rawTask) return;

    var baseline = rawTask._baseline;
    if (!baseline || (!baseline.start && !baseline.end)) return;

    // 邊界案例：baseline 倒置
    if (baseline.start && baseline.end && baseline.start > baseline.end) {
        _addWarningIcon(wrapper, baseline);
        return;
    }

    // 邊界案例：actual 與 baseline 完全相等 → 不畫
    if (_baselineEqualsActual(rawTask)) return;

    var actualBar = wrapper.querySelector('rect.bar');
    if (!actualBar) return;

    _drawBaselineRect(wrapper, actualBar, rawTask);
    _drawDeltaLabel(wrapper, actualBar, rawTask);
}


/**
 * 判斷 baseline 是否與 actual 完全相等
 * @private
 */
function _baselineEqualsActual(task) {
    var bl = task._baseline;
    if (!bl) return false;
    var aStart = task.start;
    var aEnd = task.end;
    if (!aStart && !aEnd) return false;  // actual 為 null，不算相等
    return bl.start === aStart && bl.end === aEnd;
}


/**
 * 繪製 baseline 參考條
 * @private
 */
function _drawBaselineRect(wrapper, actualBar, task) {
    var bl = task._baseline;
    var hasActual = !!(task.start || task.end);

    // 從 Frappe Gantt 的 actual bar 反推時間刻度
    var ganttEl = _svgEl;
    var ganttInst = BG.Core._instance;
    if (!ganttInst) return;

    var blX = _dateToX(bl.start, ganttInst);
    var blEndX = _dateToX(bl.end, ganttInst);
    if (blX === null || blEndX === null) return;

    var blWidth = blEndX - blX;
    if (blWidth < 1) blWidth = 2;

    // baseline 條的 Y 位置：actual bar 下方 2px
    var barY = parseFloat(actualBar.getAttribute('y')) || 0;
    var barH = parseFloat(actualBar.getAttribute('height')) || 20;
    var blY = barY + barH + 2;
    var blH = 4;

    var rect = document.createElementNS(NS, 'rect');
    rect.setAttribute('class', BASELINE_CLASS);
    rect.setAttribute('x', blX);
    rect.setAttribute('y', blY);
    rect.setAttribute('width', blWidth);
    rect.setAttribute('height', blH);
    rect.setAttribute('rx', 1);
    rect.setAttribute('ry', 1);
    rect.setAttribute('fill', 'none');
    rect.setAttribute('stroke', '#9ca3af');
    rect.setAttribute('stroke-opacity', '0.6');

    if (hasActual) {
        // actual 存在：虛線
        rect.setAttribute('stroke-dasharray', '4,2');
    } else {
        // actual null：實線（原計畫待執行）
        rect.setAttribute('stroke-width', '1.5');
    }

    // SVG title for tooltip
    var title = document.createElementNS(NS, 'title');
    title.textContent = '原計畫: ' + (bl.start || '?') + ' ~ ' + (bl.end || '?');
    rect.appendChild(title);

    // 插入到 bar-wrapper 的 bar-group 裡
    var barGroup = wrapper.querySelector('g.bar-group') || wrapper;
    barGroup.appendChild(rect);
}


/**
 * 繪製偏差標籤 (+2d / -1d)
 * @private
 */
function _drawDeltaLabel(wrapper, actualBar, task) {
    var delta = task._delta_days;
    if (delta === null || delta === undefined || delta === 0) return;

    var barX = parseFloat(actualBar.getAttribute('x')) || 0;
    var barW = parseFloat(actualBar.getAttribute('width')) || 0;
    var barY = parseFloat(actualBar.getAttribute('y')) || 0;
    var barH = parseFloat(actualBar.getAttribute('height')) || 20;

    var text = document.createElementNS(NS, 'text');
    text.setAttribute('class', DELTA_CLASS);
    text.setAttribute('x', barX + barW + 8);
    text.setAttribute('y', barY + barH / 2 + 3);
    text.setAttribute('font-size', '10');
    text.setAttribute('font-family', 'Consolas, monospace');
    text.setAttribute('font-weight', '600');

    if (delta > 0) {
        text.textContent = '+' + delta + 'd';
        text.setAttribute('fill', 'var(--bs-danger, #dc3545)');
    } else {
        text.textContent = delta + 'd';
        text.setAttribute('fill', 'var(--bs-success, #198754)');
    }

    var barGroup = wrapper.querySelector('g.bar-group') || wrapper;
    barGroup.appendChild(text);
}


/**
 * baseline 倒置時加警告 icon
 * @private
 */
function _addWarningIcon(wrapper, baseline) {
    var actualBar = wrapper.querySelector('rect.bar');
    if (!actualBar) return;

    var barX = parseFloat(actualBar.getAttribute('x')) || 0;
    var barY = parseFloat(actualBar.getAttribute('y')) || 0;
    var barH = parseFloat(actualBar.getAttribute('height')) || 20;

    // 12x12 warning triangle 在 bar 左端
    var text = document.createElementNS(NS, 'text');
    text.setAttribute('class', WARN_CLASS);
    text.setAttribute('x', barX - 16);
    text.setAttribute('y', barY + barH / 2 + 4);
    text.setAttribute('font-size', '12');
    text.setAttribute('fill', '#f59e0b');
    text.setAttribute('cursor', 'default');
    text.setAttribute('pointer-events', 'all');
    // 使用 Unicode warning sign（非 emoji）
    text.textContent = '\u26A0';

    var title = document.createElementNS(NS, 'title');
    title.textContent = '原計畫日期有誤: ' + (baseline.start || '?') + ' ~ ' + (baseline.end || '?');
    text.appendChild(title);

    var barGroup = wrapper.querySelector('g.bar-group') || wrapper;
    barGroup.appendChild(text);
}


/**
 * 將日期字串轉為 Frappe Gantt SVG 的 X 座標
 * @private
 *
 * Frappe Gantt 0.6.1 的座標系：
 *   x = (date - gantt_start) / step * column_width
 *   step 是每個 column 代表的毫秒數
 */
function _dateToX(dateStr, ganttInst) {
    if (!dateStr || !ganttInst) return null;

    var d = new Date(dateStr + 'T00:00:00');
    if (isNaN(d.getTime())) return null;

    var ganttStart = ganttInst.gantt_start;
    if (!ganttStart) return null;

    var opts = ganttInst.options;
    var columnWidth = opts.column_width || 38;
    var step = opts.step || 24;  // hours per column

    // 時間差（毫秒） → 小時 → columns → pixels
    var diffMs = d.getTime() - ganttStart.getTime();
    var diffHours = diffMs / (1000 * 60 * 60);
    var x = (diffHours / step) * columnWidth;

    return x;
}


/**
 * 清除所有 baseline 元素
 * @private
 */
function _clearAll() {
    if (!_svgEl) return;
    var els = _svgEl.querySelectorAll(
        '.' + BASELINE_CLASS + ', .' + DELTA_CLASS + ', .' + WARN_CLASS
    );
    for (var i = 0; i < els.length; i++) {
        els[i].remove();
    }
}


/**
 * 啟動 MutationObserver
 * @private
 */
function _startObserver() {
    if (!_svgEl || _observer) return;

    _observer = new MutationObserver(function() {
        // injection flag：自己注入的 DOM 變動不觸發重繪
        if (_bgInjecting) return;

        if (_debounceTimer) clearTimeout(_debounceTimer);
        _debounceTimer = setTimeout(function() {
            BG.Baseline.render();
        }, DEBOUNCE_MS);
    });

    _observer.observe(_svgEl, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['d', 'transform', 'x', 'width'],
    });
}

})(window.BeakGantt);
