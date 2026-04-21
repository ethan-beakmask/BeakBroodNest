/**
 * BeakGantt.Dependency -- 依賴違反視覺後處理
 *
 * 功能：
 * - 掃描 Frappe Gantt SVG 中的 arrow path
 * - 比對 actual_end vs actual_start 判斷違反
 * - 違反的 arrow 變紅（stroke + 粗度）
 * - 在箭頭中段加紅三角 icon + hover tooltip
 *
 * 監聽策略：
 * - MutationObserver 監聽 svg.gantt，50ms debounce
 * - view mode 切換時手動 disconnect / reconnect
 *
 * Frappe Gantt 0.6.1 的 arrow 結構：
 *   <g class="arrow">            ← layers.arrow 容器
 *     <path data-from="70" data-to="71" d="..." />
 *   </g>
 */
window.BeakGantt = window.BeakGantt || {};

(function(BG) {
'use strict';

var VIOLATION_CLASS = 'dep-violated';
var MARKER_CLASS = 'dep-violation-marker';
var TOOLTIP_CLASS = 'dep-violation-tooltip';
var DEBOUNCE_MS = 50;

var _observer = null;
var _debounceTimer = null;
var _svgEl = null;

BG.Dependency = {

    /**
     * 啟動依賴違反偵測
     * @param {Element} containerEl - #frappe-gantt 容器
     */
    init: function(containerEl) {
        _svgEl = containerEl.querySelector('svg.gantt');
        if (!_svgEl) return;

        BG.Dependency.scan();
        _startObserver();
    },

    /**
     * 掃描所有 arrow path，標記違反
     */
    scan: function() {
        if (!_svgEl) return;

        _clearMarkers();

        var paths = _svgEl.querySelectorAll('path[data-from][data-to]');
        for (var i = 0; i < paths.length; i++) {
            _checkArrow(paths[i]);
        }
    },

    /**
     * 暫停監聽（view mode 切換前呼叫）
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
     * 重新啟動（view mode 切換後呼叫）
     * @param {Element} containerEl
     */
    reconnect: function(containerEl) {
        BG.Dependency.disconnect();
        _svgEl = containerEl.querySelector('svg.gantt');
        if (!_svgEl) return;

        BG.Dependency.scan();
        _startObserver();
    }
};


/**
 * 檢查單一 arrow 是否違反依賴
 * @private
 */
function _checkArrow(pathEl) {
    var fromId = pathEl.getAttribute('data-from');
    var toId = pathEl.getAttribute('data-to');

    var fromTask = BG.Core.getRawTask(fromId);
    var toTask = BG.Core.getRawTask(toId);

    if (!fromTask || !toTask) return;

    var violation = _detectViolation(fromTask, toTask);

    // 清除舊狀態
    pathEl.classList.remove(VIOLATION_CLASS);
    _removeMarkerFor(pathEl);

    if (violation) {
        pathEl.classList.add(VIOLATION_CLASS);
        _addViolationMarker(pathEl, violation.message);
    }
}


/**
 * 偵測依賴違反：from.actual_end > to.actual_start
 * @private
 * @returns {Object|null} { message } 或 null
 */
function _detectViolation(fromTask, toTask) {
    // 只在雙方都有 actual 時才判斷
    var fromEnd = fromTask.end;
    var toStart = toTask.start;

    if (!fromEnd || !toStart || !fromTask._has_actual || !toTask._has_actual) {
        return null;
    }

    if (fromEnd > toStart) {
        return {
            message: fromTask.name + ' 實際結束 (' + fromEnd + ') ' +
                     '晚於 ' + toTask.name + ' 實際開始 (' + toStart + ')'
        };
    }
    return null;
}


/**
 * 在 arrow path 中段加紅三角 + tooltip
 * @private
 */
function _addViolationMarker(pathEl, message) {
    var svg = _svgEl;
    if (!svg) return;

    // 取 path 中點座標
    var totalLen = pathEl.getTotalLength();
    if (!totalLen) return;
    var midPoint = pathEl.getPointAtLength(totalLen * 0.5);

    // 紅三角 (polygon)
    var ns = 'http://www.w3.org/2000/svg';
    var tri = document.createElementNS(ns, 'polygon');
    var cx = midPoint.x;
    var cy = midPoint.y;
    var s = 6; // 半邊長
    tri.setAttribute('points',
        (cx) + ',' + (cy - s) + ' ' +
        (cx - s) + ',' + (cy + s) + ' ' +
        (cx + s) + ',' + (cy + s)
    );
    tri.setAttribute('fill', 'var(--bs-danger, #dc3545)');
    tri.setAttribute('class', MARKER_CLASS);
    tri.setAttribute('data-arrow-from', pathEl.getAttribute('data-from'));
    tri.setAttribute('data-arrow-to', pathEl.getAttribute('data-to'));
    tri.style.cursor = 'default';
    tri.style.pointerEvents = 'all';

    // Tooltip (SVG title 元素)
    var title = document.createElementNS(ns, 'title');
    title.textContent = message;
    tri.appendChild(title);

    // 插入到 arrow 層級（path 的父元素）
    var parent = pathEl.parentElement || svg;
    parent.appendChild(tri);
}


/**
 * 清除所有違反標記
 * @private
 */
function _clearMarkers() {
    if (!_svgEl) return;
    var markers = _svgEl.querySelectorAll('.' + MARKER_CLASS);
    for (var i = 0; i < markers.length; i++) {
        markers[i].remove();
    }
    var violated = _svgEl.querySelectorAll('.' + VIOLATION_CLASS);
    for (var i = 0; i < violated.length; i++) {
        violated[i].classList.remove(VIOLATION_CLASS);
    }
}


/**
 * 移除特定 arrow 的標記
 * @private
 */
function _removeMarkerFor(pathEl) {
    if (!_svgEl) return;
    var from = pathEl.getAttribute('data-from');
    var to = pathEl.getAttribute('data-to');
    var markers = _svgEl.querySelectorAll(
        '.' + MARKER_CLASS +
        '[data-arrow-from="' + from + '"]' +
        '[data-arrow-to="' + to + '"]'
    );
    for (var i = 0; i < markers.length; i++) {
        markers[i].remove();
    }
}


/**
 * 啟動 MutationObserver 監聽 SVG 變動
 * @private
 */
function _startObserver() {
    if (!_svgEl || _observer) return;

    _observer = new MutationObserver(function() {
        if (_debounceTimer) clearTimeout(_debounceTimer);
        _debounceTimer = setTimeout(function() {
            BG.Dependency.scan();
        }, DEBOUNCE_MS);
    });

    _observer.observe(_svgEl, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['d', 'transform'],
    });
}

})(window.BeakGantt);
