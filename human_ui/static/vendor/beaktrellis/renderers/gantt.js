/**
 * Gantt 渲染器
 * 在表格欄位內繪製甘特圖色條 + SVG overlay 依賴箭頭 + Today 標線
 *
 * 支援：
 * - 計劃/實際雙層色條（依 urgency 著色）
 * - SVG overlay 依賴箭頭（blocks 關係，紅色虛線）
 * - Today 垂直標線
 * - 自適應時間刻度（日/週/月）
 * - onBarClick / onDependencyClick 回呼擴充點
 * - Virtual Scroll 模式下只繪製可見範圍
 *
 * 架構：
 * - GanttRenderer.create(opts) 回傳 column renderer function
 * - 同時註冊 'gantt' tree renderer（委派 lines-dom 繪製樹線 + 加掛 gantt overlay）
 * - 載入順序：beak-tree-model.js -> beak-trellis.js -> beak-tree-lines-dom.js -> gantt.js
 */
'use strict';

var GanttRenderer = (function() {

    var DAY_MS = 86400000;
    var svgNS = 'http://www.w3.org/2000/svg';

    // ========== 工廠函式 ==========

    /**
     * 建立 Gantt 欄位渲染器
     * @param {Object} options
     * @param {string}   [options.plannedStartField='planned_start']
     * @param {string}   [options.plannedEndField='planned_end']
     * @param {string}   [options.actualStartField='actual_start']
     * @param {string}   [options.actualEndField='actual_end']
     * @param {string}   [options.statusField='status']
     * @param {string}   [options.urgencyField='urgency']
     * @param {string}   [options.blocksField='blocks']
     * @param {number}   [options.barHeight=12]
     * @param {boolean}  [options.showToday=true]
     * @param {Object}   [options.colorMap]
     * @param {Function} [options.onBarClick]          - (node, barType, event)
     * @param {Function} [options.onDependencyClick]   - (fromNode, toNode, event)
     * @returns {Function} column renderer function
     */
    function create(options) {
        var opts = Object.assign({
            plannedStartField: 'planned_start',
            plannedEndField:   'planned_end',
            actualStartField:  'actual_start',
            actualEndField:    'actual_end',
            statusField:       'status',
            urgencyField:      'urgency',
            blocksField:       'blocks',
            barHeight:         12,
            showToday:         true,
            colorMap: {
                H:    '#dc2626',
                M:    '#f59e0b',
                L:    '#6c757d',
                done: '#198754'
            },
            onBarClick: null,
            onDependencyClick: null
        }, options || {});

        var _cachedRange = null;
        var _cacheKey = '';

        // ---------- 時間範圍計算 ----------

        function computeRange(grid) {
            if (!grid) return null;
            var nodes = grid._flatNodes;
            var key = nodes.length + ':' + (nodes.length > 0 ? nodes[0].id + ',' + nodes[nodes.length - 1].id : '');
            if (key === _cacheKey && _cachedRange) return _cachedRange;

            var minTime = Infinity;
            var maxTime = -Infinity;
            var now = Date.now();

            grid._nodeMap.forEach(function(node) {
                var d = node.data;
                var fields = [
                    d[opts.plannedStartField],
                    d[opts.plannedEndField],
                    d[opts.actualStartField],
                    d[opts.actualEndField]
                ];
                for (var i = 0; i < fields.length; i++) {
                    if (fields[i]) {
                        var t = new Date(fields[i]).getTime();
                        if (!isNaN(t)) {
                            if (t < minTime) minTime = t;
                            if (t > maxTime) maxTime = t;
                        }
                    }
                }
            });

            if (opts.showToday) {
                if (now < minTime) minTime = now;
                if (now > maxTime) maxTime = now;
            }

            if (minTime >= maxTime) {
                maxTime = minTime + DAY_MS;
            }

            var padding = (maxTime - minTime) * 0.05;
            minTime -= padding;
            maxTime += padding;

            _cachedRange = { min: minTime, max: maxTime, span: maxTime - minTime };
            _cacheKey = key;
            return _cachedRange;
        }

        // ---------- 格式化工具 ----------

        function formatDateTime(ts) {
            var d = new Date(ts);
            var mm = String(d.getMonth() + 1).padStart(2, '0');
            var dd = String(d.getDate()).padStart(2, '0');
            var hh = String(d.getHours()).padStart(2, '0');
            var mi = String(d.getMinutes()).padStart(2, '0');
            return mm + '/' + dd + ' ' + hh + ':' + mi;
        }

        function getBarColor(node) {
            var status = node.data[opts.statusField];
            if (status === 'done') return opts.colorMap.done;
            var urgency = node.data[opts.urgencyField];
            return opts.colorMap[urgency] || opts.colorMap.M;
        }

        // ---------- 刻度線（cell 內背景） ----------

        function drawTickLines(track, range) {
            var spanDays = range.span / DAY_MS;
            var tickInterval;
            if (spanDays <= 7) {
                tickInterval = DAY_MS;
            } else if (spanDays <= 30) {
                tickInterval = 7 * DAY_MS;
            } else {
                tickInterval = 30 * DAY_MS;
            }

            var firstTick = Math.ceil(range.min / tickInterval) * tickInterval;
            for (var t = firstTick; t <= range.max; t += tickInterval) {
                var pct = ((t - range.min) / range.span) * 100;
                var tick = document.createElement('div');
                tick.className = 'bt-gantt-tick';
                tick.style.left = pct + '%';
                track.appendChild(tick);
            }
        }

        // ---------- Cell 渲染函式 ----------

        function renderer(cellValue, node, col, grid) {
            if (grid) renderer._gridRef = grid;

            var container = document.createElement('div');
            container.className = 'bt-gantt-cell';

            var ps = node.data[opts.plannedStartField];
            var pe = node.data[opts.plannedEndField];

            if (!ps && !pe) {
                container.innerHTML = '<span class="bt-gantt-nodata">--</span>';
                return container;
            }

            var gridRef = grid || renderer._gridRef;
            var range = gridRef ? computeRange(gridRef) : null;
            if (!range) {
                container.innerHTML = '<span class="bt-gantt-nodata">--</span>';
                return container;
            }

            var now = Date.now();
            var color = getBarColor(node);

            var track = document.createElement('div');
            track.className = 'bt-gantt-track';

            drawTickLines(track, range);

            // --- Planned bar ---
            if (ps && pe) {
                var psTs = new Date(ps).getTime();
                var peTs = new Date(pe).getTime();
                if (!isNaN(psTs) && !isNaN(peTs) && peTs >= psTs) {
                    var pLeft = ((psTs - range.min) / range.span) * 100;
                    var pWidth = ((peTs - psTs) / range.span) * 100;
                    if (pWidth < 0.5) pWidth = 0.5;
                    if (pLeft < 0) { pWidth += pLeft; pLeft = 0; }
                    if (pLeft + pWidth > 100) pWidth = 100 - pLeft;
                    if (pWidth < 0) pWidth = 0;

                    var pBar = document.createElement('div');
                    pBar.className = 'bt-gantt-bar bt-gantt-bar-planned';
                    pBar.style.left = pLeft + '%';
                    pBar.style.width = pWidth + '%';
                    pBar.style.height = opts.barHeight + 'px';
                    pBar.style.background = color;
                    pBar.title = 'Planned: ' + formatDateTime(psTs) + ' ~ ' + formatDateTime(peTs);

                    if (opts.onBarClick) {
                        pBar.style.cursor = 'pointer';
                        pBar.style.pointerEvents = 'auto';
                        (function(n) {
                            pBar.addEventListener('click', function(e) {
                                e.stopPropagation();
                                opts.onBarClick(n, 'planned', e);
                            });
                        })(node);
                    }

                    track.appendChild(pBar);
                }
            }

            // --- Actual bar ---
            var as = node.data[opts.actualStartField];
            var ae = node.data[opts.actualEndField];
            var status = node.data[opts.statusField];

            if (as) {
                var asTs = new Date(as).getTime();
                var aeTs;
                if (ae) {
                    aeTs = new Date(ae).getTime();
                } else if (status === 'in_progress') {
                    aeTs = now;
                } else {
                    aeTs = asTs;
                }

                if (!isNaN(asTs) && !isNaN(aeTs) && aeTs >= asTs) {
                    var aLeft = ((asTs - range.min) / range.span) * 100;
                    var aWidth = ((aeTs - asTs) / range.span) * 100;
                    if (aWidth < 0.5) aWidth = 0.5;
                    if (aLeft < 0) { aWidth += aLeft; aLeft = 0; }
                    if (aLeft + aWidth > 100) aWidth = 100 - aLeft;
                    if (aWidth < 0) aWidth = 0;

                    var aBar = document.createElement('div');
                    aBar.className = 'bt-gantt-bar bt-gantt-bar-actual';
                    aBar.style.left = aLeft + '%';
                    aBar.style.width = aWidth + '%';
                    aBar.style.height = opts.barHeight + 'px';
                    aBar.style.background = color;

                    var aeLabel = ae ? formatDateTime(aeTs) : 'now';
                    aBar.title = 'Actual: ' + formatDateTime(asTs) + ' ~ ' + aeLabel +
                        ' [' + (status || '-') + ']';

                    if (opts.onBarClick) {
                        aBar.style.cursor = 'pointer';
                        aBar.style.pointerEvents = 'auto';
                        (function(n) {
                            aBar.addEventListener('click', function(e) {
                                e.stopPropagation();
                                opts.onBarClick(n, 'actual', e);
                            });
                        })(node);
                    }

                    track.appendChild(aBar);
                }
            }

            // --- Today line (cell 內薄線) ---
            if (opts.showToday && now >= range.min && now <= range.max) {
                var todayPct = ((now - range.min) / range.span) * 100;
                var todayEl = document.createElement('div');
                todayEl.className = 'bt-gantt-today-cell';
                todayEl.style.left = todayPct + '%';
                track.appendChild(todayEl);
            }

            container.appendChild(track);
            return container;
        }

        // ---------- 公開 API ----------

        renderer._isGantt = true;
        renderer._gridRef = null;
        renderer._opts = opts;
        renderer._computeRange = computeRange;

        renderer.setGrid = function(grid) {
            renderer._gridRef = grid;
        };

        renderer.resetCache = function() {
            _cachedRange = null;
            _cacheKey = '';
        };

        renderer.computeRange = function(grid) {
            return computeRange(grid || renderer._gridRef);
        };

        renderer.drawOverlay = function(grid) {
            _drawGanttOverlay(grid || renderer._gridRef, opts, computeRange);
        };

        renderer.createScaleHeader = function(grid) {
            return _createScaleHeader(grid || renderer._gridRef, opts, computeRange);
        };

        return renderer;
    }

    // ========== SVG Overlay: 依賴箭頭 + Today 全高標線 ==========

    // ---------- SVG 共用工具 ----------

    /**
     * 取得或建立 gantt overlay 所需的 wrapper + SVG + arrowhead marker
     * @returns {{ svg, markerId, wrapper }} 或 null
     */
    function _setupOverlaySvg(targetTable) {
        var wrapper = targetTable.parentElement;
        if (!wrapper || (!wrapper.classList.contains('bt-gantt-wrapper') &&
                         !wrapper.classList.contains('bt-dom-wrapper'))) {
            wrapper = document.createElement('div');
            wrapper.className = 'bt-gantt-wrapper';
            wrapper.style.position = 'relative';
            targetTable.parentNode.insertBefore(wrapper, targetTable);
            wrapper.appendChild(targetTable);
        }

        var old = wrapper.querySelector('.bt-gantt-overlay');
        if (old) old.remove();

        var svg = document.createElementNS(svgNS, 'svg');
        svg.setAttribute('class', 'bt-gantt-overlay');
        svg.style.cssText =
            'position:absolute;top:0;left:0;' +
            'width:' + targetTable.offsetWidth + 'px;' +
            'height:' + targetTable.offsetHeight + 'px;' +
            'pointer-events:none;z-index:5;overflow:visible;';
        wrapper.appendChild(svg);

        var markerId = 'bt-gantt-arrow-' + Math.random().toString(36).substr(2, 6);
        var defs = document.createElementNS(svgNS, 'defs');
        var marker = document.createElementNS(svgNS, 'marker');
        marker.setAttribute('id', markerId);
        marker.setAttribute('viewBox', '0 0 10 7');
        marker.setAttribute('refX', '10');
        marker.setAttribute('refY', '3.5');
        marker.setAttribute('markerWidth', '8');
        marker.setAttribute('markerHeight', '6');
        marker.setAttribute('orient', 'auto');
        var arrowPath = document.createElementNS(svgNS, 'path');
        arrowPath.setAttribute('d', 'M0,0 L10,3.5 L0,7 Z');
        arrowPath.setAttribute('fill', '#dc2626');
        marker.appendChild(arrowPath);
        defs.appendChild(marker);
        svg.appendChild(defs);

        return { svg: svg, markerId: markerId, wrapper: wrapper };
    }

    /**
     * 繪製 Today 全高標線
     */
    function _drawTodayLine(svg, range, tdLeft, tdWidth, tableHeight) {
        var now = Date.now();
        if (now < range.min || now > range.max) return;

        var todayPct = (now - range.min) / range.span;
        var todayX = tdLeft + todayPct * tdWidth;

        var todayLine = document.createElementNS(svgNS, 'line');
        todayLine.setAttribute('x1', todayX);
        todayLine.setAttribute('y1', '0');
        todayLine.setAttribute('x2', todayX);
        todayLine.setAttribute('y2', tableHeight);
        todayLine.setAttribute('stroke', '#dc2626');
        todayLine.setAttribute('stroke-width', '1');
        todayLine.setAttribute('stroke-dasharray', '4,2');
        svg.appendChild(todayLine);

        var label = document.createElementNS(svgNS, 'text');
        label.setAttribute('x', todayX);
        label.setAttribute('y', '12');
        label.setAttribute('text-anchor', 'middle');
        label.setAttribute('fill', '#dc2626');
        label.setAttribute('font-size', '10');
        label.setAttribute('font-weight', 'bold');
        label.setAttribute('font-family', 'Consolas, monospace');
        label.textContent = 'TODAY';
        svg.appendChild(label);
    }

    /**
     * 繪製單條依賴箭頭（肘形紅色虛線）
     */
    function _drawArrowPath(svg, markerId, fromX, fromY, toX, toY, opts, fromNode, toNode) {
        var d;
        if (Math.abs(fromY - toY) < 2) {
            d = 'M' + fromX + ',' + fromY + ' L' + toX + ',' + toY;
        } else {
            var midX = fromX + 8;
            d = 'M' + fromX + ',' + fromY +
                ' L' + midX + ',' + fromY +
                ' L' + midX + ',' + toY +
                ' L' + toX + ',' + toY;
        }

        if (opts.onDependencyClick) {
            // 視覺線（細線，不接收事件）
            var visPath = document.createElementNS(svgNS, 'path');
            visPath.setAttribute('d', d);
            visPath.setAttribute('stroke', '#dc2626');
            visPath.setAttribute('stroke-width', '1.5');
            visPath.setAttribute('stroke-dasharray', '4,2');
            visPath.setAttribute('fill', 'none');
            visPath.setAttribute('marker-end', 'url(#' + markerId + ')');
            visPath.style.pointerEvents = 'none';
            svg.appendChild(visPath);

            // 寬透明點擊區
            var hitPath = document.createElementNS(svgNS, 'path');
            hitPath.setAttribute('d', d);
            hitPath.setAttribute('stroke', 'transparent');
            hitPath.setAttribute('stroke-width', '6');
            hitPath.setAttribute('fill', 'none');
            hitPath.style.pointerEvents = 'stroke';
            hitPath.style.cursor = 'pointer';
            (function(fN, tN) {
                hitPath.addEventListener('click', function(e) {
                    opts.onDependencyClick(fN, tN, e);
                });
            })(fromNode, toNode);
            svg.appendChild(hitPath);
        } else {
            var path = document.createElementNS(svgNS, 'path');
            path.setAttribute('d', d);
            path.setAttribute('stroke', '#dc2626');
            path.setAttribute('stroke-width', '1.5');
            path.setAttribute('stroke-dasharray', '4,2');
            path.setAttribute('fill', 'none');
            path.setAttribute('marker-end', 'url(#' + markerId + ')');
            svg.appendChild(path);
        }
    }

    // ========== 非 VS 模式 overlay ==========

    function _drawGanttOverlay(grid, opts, computeRange) {
        if (!grid) return;

        // VS 模式分支
        if (grid.options.virtualScroll && grid._vsState) {
            _drawGanttOverlayVS(grid, opts, computeRange);
            return;
        }

        var targetTable = grid._rightTableEl || grid._tableEl;
        var targetTbody = grid._rightTbodyEl || grid._tbodyEl;
        if (!targetTable || !targetTbody) return;

        var ganttColId = _findGanttColId(grid);
        if (!ganttColId) return;

        var range = computeRange(grid);
        if (!range) return;

        var setup = _setupOverlaySvg(targetTable);
        if (!setup) return;
        var svg = setup.svg;
        var markerId = setup.markerId;

        // 收集可見列的 gantt cell 位置（非 VS：用 row.offsetTop）
        var rows = targetTbody.querySelectorAll('tr.bt-row');
        var cellMap = {};

        for (var r = 0; r < rows.length; r++) {
            var row = rows[r];
            var nodeId = row.dataset.id;
            var ganttTd = row.querySelector('td[data-column-id="' + ganttColId + '"]');
            if (ganttTd) {
                cellMap[nodeId] = {
                    midY: row.offsetTop + row.offsetHeight / 2,
                    tdLeft: ganttTd.offsetLeft,
                    tdWidth: ganttTd.offsetWidth
                };
            }
        }

        // Today 標線
        if (opts.showToday) {
            var anyKey = Object.keys(cellMap)[0];
            if (anyKey) {
                var ref = cellMap[anyKey];
                _drawTodayLine(svg, range, ref.tdLeft, ref.tdWidth, targetTable.offsetHeight);
            }
        }

        // 依賴箭頭
        var flatNodes = grid._flatNodes;
        for (var fi = 0; fi < flatNodes.length; fi++) {
            var node = flatNodes[fi];
            var blocks = node.data[opts.blocksField];
            if (!blocks || !Array.isArray(blocks) || blocks.length === 0) continue;

            var fromInfo = cellMap[node.id];
            if (!fromInfo) continue;

            var fromX = _barEdgeX(node, fromInfo, range, opts, 'right');
            if (fromX === null) continue;

            for (var bi = 0; bi < blocks.length; bi++) {
                var targetId = String(blocks[bi]);
                var toInfo = cellMap[targetId];
                if (!toInfo) continue;

                var targetNode = grid._nodeMap.get(targetId);
                if (!targetNode) continue;

                var toX = _barEdgeX(targetNode, toInfo, range, opts, 'left');
                if (toX === null) continue;

                _drawArrowPath(svg, markerId, fromX, fromInfo.midY, toX, toInfo.midY,
                    opts, node, targetNode);
            }
        }
    }

    // ========== VS 模式 overlay ==========

    /**
     * Virtual Scroll 模式：用 _vsYOffsets 數學座標計算列位置，
     * 不依賴 row.offsetTop（受 spacer row 影響不可靠）。
     * 參考 beak-tree-lines-dom.js 的 _drawMainTreeLinesVS。
     */
    function _drawGanttOverlayVS(grid, opts, computeRange) {
        var targetTable = grid._rightTableEl || grid._tableEl;
        var targetTbody = grid._rightTbodyEl || grid._tbodyEl;
        if (!targetTable || !targetTbody) return;

        var state = grid._vsState;
        if (!state) return;

        var rowHeight = grid.options.rowHeight || 26;
        var startIdx = state.startIdx;
        var endIdx = Math.min(state.endIdx, grid._flatNodes.length);
        var flatNodes = grid._flatNodes;

        var ganttColId = _findGanttColId(grid);
        if (!ganttColId) return;

        var range = computeRange(grid);
        if (!range) return;

        var setup = _setupOverlaySvg(targetTable);
        if (!setup) return;
        var svg = setup.svg;
        var markerId = setup.markerId;

        // 從 DOM 取得第一個可見列的 offsetTop（spacer 之後的錨點）
        var dataRows = targetTbody.querySelectorAll('tr.bt-row');
        if (dataRows.length === 0) return;
        var firstRowTop = dataRows[0].offsetTop;

        // 從第一個可見列取得 gantt TD 的水平位置（所有列的欄位位置一致）
        var firstGanttTd = dataRows[0].querySelector('td[data-column-id="' + ganttColId + '"]');
        if (!firstGanttTd) return;
        var tdLeft = firstGanttTd.offsetLeft;
        var tdWidth = firstGanttTd.offsetWidth;

        // 使用 _vsYOffsets 累計偏移計算 Y 座標，支援 root 列不同高度
        var yOffsets = grid._vsYOffsets;
        var rootRowH = grid._vsRootRowHeight || rowHeight;

        function getRowH(idx) {
            return (flatNodes[idx].level === 0) ? rootRowH : rowHeight;
        }

        function midY(idx) {
            if (yOffsets) {
                return firstRowTop + (yOffsets[idx] - yOffsets[startIdx]) + getRowH(idx) / 2;
            }
            return firstRowTop + (idx - startIdx) * rowHeight + rowHeight / 2;
        }

        // 用 _flatIndexMap 做 O(1) 節點索引查詢
        var indexMap = grid._flatIndexMap;

        // 建立可見節點的 cellInfo（用數學座標，不用 DOM 量測）
        var cellMap = {};
        for (var i = startIdx; i < endIdx && i < flatNodes.length; i++) {
            var nd = flatNodes[i];
            cellMap[nd.id] = {
                midY: midY(i),
                tdLeft: tdLeft,
                tdWidth: tdWidth
            };
        }

        // Today 標線
        if (opts.showToday) {
            _drawTodayLine(svg, range, tdLeft, tdWidth, targetTable.offsetHeight);
        }

        // 依賴箭頭（只繪製 from 和 to 都在可見範圍內的）
        for (var i = startIdx; i < endIdx && i < flatNodes.length; i++) {
            var node = flatNodes[i];
            var blocks = node.data[opts.blocksField];
            if (!blocks || !Array.isArray(blocks) || blocks.length === 0) continue;

            var fromInfo = cellMap[node.id];
            if (!fromInfo) continue;

            var fromX = _barEdgeX(node, fromInfo, range, opts, 'right');
            if (fromX === null) continue;

            for (var bi = 0; bi < blocks.length; bi++) {
                var targetId = String(blocks[bi]);

                // O(1) 查詢目標節點是否在可見範圍
                var targetIdx = indexMap ? indexMap.get(targetId) : undefined;
                if (targetIdx === undefined || targetIdx < startIdx || targetIdx >= endIdx) continue;

                var targetNode = grid._nodeMap.get(targetId);
                if (!targetNode) continue;

                var toInfo = cellMap[targetId];
                if (!toInfo) continue;

                var toX = _barEdgeX(targetNode, toInfo, range, opts, 'left');
                if (toX === null) continue;

                _drawArrowPath(svg, markerId, fromX, fromInfo.midY, toX, toInfo.midY,
                    opts, node, targetNode);
            }
        }
    }

    /**
     * 找到 gantt column 的 ID
     */
    function _findGanttColId(grid) {
        var cols = grid.options.columns;
        for (var i = 0; i < cols.length; i++) {
            if (cols[i].renderer && cols[i].renderer._isGantt) {
                return cols[i].id;
            }
        }
        return null;
    }

    /**
     * 計算色條邊緣的 X 座標（相對於 table）
     * side: 'left' | 'right'
     */
    function _barEdgeX(node, cellInfo, range, opts, side) {
        var ps = node.data[opts.plannedStartField];
        var pe = node.data[opts.plannedEndField];
        var as = node.data[opts.actualStartField];
        var ae = node.data[opts.actualEndField];
        var status = node.data[opts.statusField];
        var now = Date.now();

        var start, end;

        // 實際色條優先
        if (as) {
            start = new Date(as).getTime();
            if (ae) {
                end = new Date(ae).getTime();
            } else if (status === 'in_progress') {
                end = now;
            } else {
                end = start;
            }
        } else if (ps && pe) {
            start = new Date(ps).getTime();
            end = new Date(pe).getTime();
        } else {
            return null;
        }

        if (isNaN(start) || isNaN(end)) return null;

        var pct = (side === 'right')
            ? (end - range.min) / range.span
            : (start - range.min) / range.span;

        return cellInfo.tdLeft + pct * cellInfo.tdWidth;
    }

    // ========== 時間刻度標頭 ==========

    function _createScaleHeader(grid, opts, computeRange) {
        if (!grid) return document.createElement('div');
        var range = computeRange(grid);
        if (!range) return document.createElement('div');

        var container = document.createElement('div');
        container.className = 'bt-gantt-scale';

        var spanDays = range.span / DAY_MS;
        var tickInterval;

        if (spanDays <= 7) {
            tickInterval = DAY_MS;
        } else if (spanDays <= 30) {
            tickInterval = 7 * DAY_MS;
        } else {
            tickInterval = 30 * DAY_MS;
        }

        var firstTick = Math.ceil(range.min / tickInterval) * tickInterval;

        for (var t = firstTick; t <= range.max; t += tickInterval) {
            var pct = ((t - range.min) / range.span) * 100;
            var d = new Date(t);
            var label;
            if (spanDays > 30) {
                label = (d.getMonth() + 1) + '月';
            } else {
                label = String(d.getMonth() + 1).padStart(2, '0') + '/' +
                        String(d.getDate()).padStart(2, '0');
            }

            var tick = document.createElement('span');
            tick.className = 'bt-gantt-scale-tick';
            tick.style.left = pct + '%';
            tick.textContent = label;
            container.appendChild(tick);
        }

        return container;
    }

    // ========== 註冊 tree renderer ==========

    var _linesDom = null;

    function _getLinesDom() {
        if (_linesDom) return _linesDom;
        if (typeof BeakTrellis !== 'undefined' && BeakTrellis.renderers && BeakTrellis.renderers['lines-dom']) {
            _linesDom = BeakTrellis.renderers['lines-dom'];
        } else if (typeof BeakTree !== 'undefined' && BeakTree.renderers && BeakTree.renderers['lines-dom']) {
            _linesDom = BeakTree.renderers['lines-dom'];
        }
        return _linesDom;
    }

    var ganttTreeRenderer = {
        renderTreeCell: function(node, ancestors, grid) {
            var ld = _getLinesDom();
            if (ld && ld.renderTreeCell) {
                return ld.renderTreeCell(node, ancestors, grid);
            }
            var span = document.createElement('span');
            span.className = 'bt-label';
            span.textContent = node.label;
            return span;
        },
        afterRender: function(grid) {
            // 委派 lines-dom 繪製樹線
            var ld = _getLinesDom();
            if (ld && ld.afterRender) {
                ld.afterRender(grid);
            }

            // 繪製 gantt overlay（在 lines-dom 的 rAF 之後）
            requestAnimationFrame(function() {
                var cols = grid.options.columns;
                for (var i = 0; i < cols.length; i++) {
                    if (cols[i].renderer && cols[i].renderer._isGantt) {
                        cols[i].renderer._gridRef = grid;
                        cols[i].renderer.drawOverlay(grid);
                    }
                }
            });
        }
    };

    if (typeof BeakTrellis !== 'undefined' && BeakTrellis.registerRenderer) {
        BeakTrellis.registerRenderer('gantt', ganttTreeRenderer);
    }
    if (typeof BeakTree !== 'undefined' && BeakTree.registerRenderer) {
        BeakTree.registerRenderer('gantt', ganttTreeRenderer);
    }

    return { create: create };

})();
