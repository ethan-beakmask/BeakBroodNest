/**
 * BeakTrellis Split Pane Plugin
 * 將 Tree 欄與資料欄分為左右兩面板，各自水平捲動，垂直同步
 *
 * 功能：
 *   - 左面板 (Checkbox + Tree)：人工拖拉寬度，過寬時出現水平 scrollbar
 *   - 右面板 (資料欄)：欄位多時水平 scrollbar，垂直 scrollbar
 *   - 面板分隔線拖曳調整寬度
 *   - 欄位標題拖曳換位
 *   - 列高自動同步
 *
 * 使用方式：
 *   載入此檔（在 treegrid.js 之後），並設定 options.splitPane = true
 */
'use strict';

(function() {

    // ========== 工具函式 ==========

    function _el(tag, cls) {
        var el = document.createElement(tag);
        if (cls) el.className = cls;
        return el;
    }

    /**
     * Binary search: 在累計 Y 偏移陣列中找到指定 Y 位置所在的列索引
     * yOffsets[i] = 第 i 列的頂部 Y 座標; yOffsets[totalRows] = 總高度
     * 回傳最大的 i 使得 yOffsets[i] <= y
     */
    function _vsFindRowAtY(yOffsets, y, totalRows) {
        if (totalRows === 0) return 0;
        if (y <= 0) return 0;
        if (y >= yOffsets[totalRows]) return totalRows - 1;
        var lo = 0, hi = totalRows;
        while (lo < hi) {
            var mid = (lo + hi) >>> 1;
            if (yOffsets[mid] <= y) {
                lo = mid + 1;
            } else {
                hi = mid;
            }
        }
        return Math.max(0, lo - 1);
    }

    // ========== Split Pane 完整渲染 ==========

    BeakTrellis.prototype._renderSplitPane = function() {
        this._computeFlatNodes();
        this.container.innerHTML = '';
        this.container.style.display = '';   // 清除 inline display，避免覆蓋 CSS class 的 flex
        this.container.classList.add('bt-container', 'bt-split');

        // Virtual Scroll 分支
        if (this.options.virtualScroll) {
            this._renderSplitPaneVS();
            return;
        }

        var self = this;
        var hasCheckbox = this.options.columns.some(function(c) { return c.type === 'checkbox'; });

        // === 左面板 ===
        var leftPane = _el('div', 'bt-pane-left');
        if (this._leftPaneWidth) {
            leftPane.style.width = this._leftPaneWidth + 'px';
        }

        var leftTable = _el('table', 'bt-table bt-table-left');

        // 左表頭
        var leftThead = document.createElement('thead');
        var leftHR = document.createElement('tr');

        if (hasCheckbox) {
            var thCb = _el('th', 'bt-th bt-th-checkbox');
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.className = 'bt-checkbox-all';
            cb.addEventListener('change', function() {
                cb.checked ? self.checkAll() : self.uncheckAll();
            });
            thCb.appendChild(cb);
            leftHR.appendChild(thCb);
        }

        var thTree = _el('th', 'bt-th bt-th-tree');
        var thTreeContent = _el('span', 'bt-th-content');
        thTreeContent.textContent = 'Tree';
        thTree.appendChild(thTreeContent);
        if (this.options.showExpandCollapseButtons) {
            this._appendExpandCollapseButtons(thTree);
        }
        leftHR.appendChild(thTree);

        leftThead.appendChild(leftHR);
        leftTable.appendChild(leftThead);

        // 左表身
        var leftTbody = document.createElement('tbody');
        for (var i = 0; i < this._flatNodes.length; i++) {
            leftTbody.appendChild(this._createLeftRow(this._flatNodes[i], hasCheckbox));
        }
        leftTable.appendChild(leftTbody);

        // 左表尾
        if (Object.keys(this.options.aggregates).length > 0) {
            var leftTfoot = document.createElement('tfoot');
            var leftFR = _el('tr', 'bt-footer-row');
            if (hasCheckbox) leftFR.appendChild(_el('td', 'bt-td bt-td-footer'));
            leftFR.appendChild(_el('td', 'bt-td bt-td-footer'));
            leftTfoot.appendChild(leftFR);
            leftTable.appendChild(leftTfoot);
        }

        leftPane.appendChild(leftTable);

        // === 分隔線 ===
        var splitter = _el('div', 'bt-splitter');

        // === 右面板 ===
        var rightPane = _el('div', 'bt-pane-right');

        var rightTable = _el('table', 'bt-table bt-table-right');

        // 右表頭
        var rightThead = document.createElement('thead');
        var rightHR = document.createElement('tr');
        this._buildRightHeaders(rightHR);
        rightThead.appendChild(rightHR);
        rightTable.appendChild(rightThead);

        // 右表身
        var rightTbody = document.createElement('tbody');
        for (var i = 0; i < this._flatNodes.length; i++) {
            rightTbody.appendChild(this._createRightRow(this._flatNodes[i]));
        }
        rightTable.appendChild(rightTbody);

        // 右表尾
        if (Object.keys(this.options.aggregates).length > 0) {
            rightTable.appendChild(this._createRightFooter());
        }

        rightPane.appendChild(rightTable);

        // === 組裝 ===
        this.container.appendChild(leftPane);
        this.container.appendChild(splitter);
        this.container.appendChild(rightPane);

        // === 儲存參照 ===
        this._leftPane = leftPane;
        this._rightPane = rightPane;
        this._splitter = splitter;
        this._leftTableEl = leftTable;
        this._rightTableEl = rightTable;
        this._leftTbodyEl = leftTbody;
        this._rightTbodyEl = rightTbody;
        this._tableEl = leftTable;    // 向後相容 (tree-lines-dom overlay)
        this._tbodyEl = leftTbody;

        // === 互動設定 ===
        this._setupScrollSync();
        this._setupSplitterDrag(splitter, leftPane);
        this._setupRowSync();

        // === 後處理 ===
        requestAnimationFrame(function() {
            self._syncRowHeights();
            if (self._renderer && self._renderer.afterRender) {
                self._renderer.afterRender(self);
            }
        });
    };

    // ========== Split Pane 局部刷新 ==========

    BeakTrellis.prototype._refreshSplitPane = function() {
        this._computeFlatNodes();

        // Virtual Scroll 分支
        if (this.options.virtualScroll && this._vsState) {
            this._refreshSplitPaneVS();
            return;
        }

        var self = this;
        var hasCheckbox = this.options.columns.some(function(c) { return c.type === 'checkbox'; });

        // 重建左 tbody
        var newLeftTbody = document.createElement('tbody');
        for (var i = 0; i < this._flatNodes.length; i++) {
            newLeftTbody.appendChild(this._createLeftRow(this._flatNodes[i], hasCheckbox));
        }
        this._leftTableEl.replaceChild(newLeftTbody, this._leftTbodyEl);
        this._leftTbodyEl = newLeftTbody;
        this._tbodyEl = newLeftTbody;  // 向後相容

        // 重建右 tbody
        var newRightTbody = document.createElement('tbody');
        for (var i = 0; i < this._flatNodes.length; i++) {
            newRightTbody.appendChild(this._createRightRow(this._flatNodes[i]));
        }
        this._rightTableEl.replaceChild(newRightTbody, this._rightTbodyEl);
        this._rightTbodyEl = newRightTbody;

        // 後處理
        requestAnimationFrame(function() {
            self._syncRowHeights();
            if (self._renderer && self._renderer.afterRender) {
                self._renderer.afterRender(self);
            }
        });

        // 更新 footer
        this._refreshSplitFooter(hasCheckbox);

        // 更新全選 checkbox
        this._refreshHeaderCheckbox();
    };

    // ========== 左列 (Checkbox + Tree) ==========

    BeakTrellis.prototype._createLeftRow = function(node, hasCheckbox) {
        var self = this;
        var tr = _el('tr', 'bt-row bt-level-' + node.level);
        tr.dataset.id = node.id;

        if (this.options.rowClassFn) {
            var extraClass = this.options.rowClassFn(node);
            if (extraClass) tr.className += ' ' + extraClass;
        }

        if (this._checkedSet.has(node.id)) {
            tr.classList.add('bt-row-checked');
        }

        // Checkbox
        if (hasCheckbox) {
            var tdCb = _el('td', 'bt-td bt-td-checkbox');
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.className = 'bt-checkbox';
            cb.dataset.id = node.id;

            var state = this.getCheckState(node.id);
            cb.checked = (state === 'checked');
            cb.indeterminate = (state === 'indeterminate');

            cb.addEventListener('change', function(e) {
                e.stopPropagation();
                self.toggleCheck(node.id);
            });
            tdCb.appendChild(cb);
            tr.appendChild(tdCb);
        }

        // Tree cell
        var tdTree = _el('td', 'bt-td bt-td-tree');
        var ancestors = this.getAncestors(node.id);

        if (this._renderer && this._renderer.renderTreeCell) {
            var content = this._renderer.renderTreeCell(node, ancestors, this);
            if (typeof content === 'string') {
                tdTree.innerHTML = content;
            } else if (content instanceof HTMLElement) {
                tdTree.appendChild(content);
            }
        }

        if (node.children.length > 0) {
            tdTree.classList.add('bt-has-children');
            tdTree.addEventListener('click', function(e) {
                if (e.target.classList.contains('bt-toggle') || e.target === tdTree) {
                    self.toggle(node.id);
                }
            });
        }

        tr.appendChild(tdTree);

        // 列點擊
        tr.addEventListener('click', function(e) {
            if (e.target.tagName === 'INPUT') return;
            if (self.options.onRowClick) {
                self.options.onRowClick(node.id, node, e);
            }
        });

        return tr;
    };

    // ========== 右列 (資料欄) ==========

    BeakTrellis.prototype._createRightRow = function(node) {
        var self = this;
        var tr = _el('tr', 'bt-row bt-level-' + node.level);
        tr.dataset.id = node.id;

        if (this.options.rowClassFn) {
            var extraClass = this.options.rowClassFn(node);
            if (extraClass) tr.className += ' ' + extraClass;
        }

        if (this._checkedSet.has(node.id)) {
            tr.classList.add('bt-row-checked');
        }

        var cols = this.options.columns;
        for (var i = 0; i < cols.length; i++) {
            var col = cols[i];
            if (col.type === 'checkbox') continue;

            var td = _el('td', 'bt-td bt-td-data');
            td.dataset.columnId = col.id;

            var cellValue = node.data[col.id];

            if (col.renderer && typeof col.renderer === 'function') {
                var content = col.renderer(cellValue, node, col, this);
                if (typeof content === 'string') {
                    td.innerHTML = content;
                } else if (content instanceof HTMLElement) {
                    td.appendChild(content);
                }
            } else {
                td.textContent = (cellValue !== undefined && cellValue !== null)
                    ? String(cellValue) : '';
            }

            tr.appendChild(td);
        }

        // 列點擊
        tr.addEventListener('click', function(e) {
            if (e.target.tagName === 'INPUT') return;
            if (self.options.onRowClick) {
                self.options.onRowClick(node.id, node, e);
            }
        });

        return tr;
    };

    // ========== 右表頭 (排序 + 拖寬 + 拖曳換位) ==========

    BeakTrellis.prototype._buildRightHeaders = function(headerRow) {
        var self = this;
        var dataCols = this._getDataColumns();

        for (var idx = 0; idx < dataCols.length; idx++) {
            (function(col, colIdx) {
                var th = _el('th', 'bt-th');
                th.dataset.columnId = col.id;
                th.dataset.colIdx = colIdx;
                if (col.width) th.style.width = col.width;

                // 標題文字 + 排序指示
                var thContent = _el('span', 'bt-th-content');
                thContent.textContent = col.label || col.id;

                if (col.sortable !== false && col.type !== 'timeline') {
                    thContent.classList.add('bt-sortable');
                    var sortIcon = _el('span', 'bt-sort-icon');
                    if (self._sortColumnId === col.id) {
                        sortIcon.textContent = self._sortAsc ? ' [A]' : ' [D]';
                    }
                    thContent.appendChild(sortIcon);
                }
                th.appendChild(thContent);

                // 欄寬拖曳 handle
                if (col.resizable !== false) {
                    var resizer = _el('span', 'bt-resizer');
                    resizer.addEventListener('mousedown', function(e) {
                        e.stopPropagation();
                        self._startResize(e, th, col);
                    });
                    th.appendChild(resizer);
                }

                // 拖曳換位 + 點擊排序（整合在同一個 mousedown）
                th.addEventListener('mousedown', function(e) {
                    if (e.target.closest('.bt-resizer')) return;
                    if (e.button !== 0) return;
                    e.preventDefault();

                    var startX = e.clientX;
                    var startY = e.clientY;
                    var dragging = false;

                    var onMove = function(me) {
                        var dx = me.clientX - startX;
                        var dy = me.clientY - startY;
                        if (!dragging && (Math.abs(dx) + Math.abs(dy)) > 5) {
                            dragging = true;
                            self._initColumnDrag(th, col, colIdx);
                        }
                        if (dragging) {
                            self._updateColumnDrag(me);
                        }
                    };

                    var onUp = function() {
                        document.removeEventListener('mousemove', onMove);
                        document.removeEventListener('mouseup', onUp);

                        if (dragging) {
                            self._endColumnDrag();
                        } else {
                            // 未拖曳 → 觸發排序
                            if (col.sortable !== false && col.type !== 'timeline') {
                                self._toggleSort(col.id);
                            }
                        }
                    };

                    document.addEventListener('mousemove', onMove);
                    document.addEventListener('mouseup', onUp);
                });

                headerRow.appendChild(th);
            })(dataCols[idx], idx);
        }
    };

    // ========== 右表尾 ==========

    BeakTrellis.prototype._createRightFooter = function() {
        var tfoot = document.createElement('tfoot');
        var tr = _el('tr', 'bt-footer-row');
        var dataCols = this._getDataColumns();

        for (var i = 0; i < dataCols.length; i++) {
            var col = dataCols[i];
            var td = _el('td', 'bt-td bt-td-footer');
            td.dataset.columnId = col.id;

            var aggDef = this.options.aggregates[col.id];
            if (aggDef) {
                var ops = Array.isArray(aggDef) ? aggDef : [aggDef];
                var parts = [];
                for (var j = 0; j < ops.length; j++) {
                    var result = this.aggregate(col.id, ops[j]);
                    if (result !== null) {
                        var label = ops[j].startsWith('topN') ? 'Top' : ops[j].toUpperCase();
                        if (Array.isArray(result)) {
                            parts.push(label + ': ' + result.join(', '));
                        } else if (typeof result === 'number') {
                            parts.push(label + ': ' + (Number.isInteger(result) ? result : result.toFixed(2)));
                        }
                    }
                }
                td.innerHTML = parts.join('<br>');
            }

            tr.appendChild(td);
        }

        tfoot.appendChild(tr);
        return tfoot;
    };

    BeakTrellis.prototype._refreshSplitFooter = function(hasCheckbox) {
        if (Object.keys(this.options.aggregates).length === 0) return;

        // 右表尾
        var oldFoot = this._rightTableEl.querySelector('tfoot');
        if (oldFoot) {
            this._rightTableEl.replaceChild(this._createRightFooter(), oldFoot);
        }
    };

    // ========== 列高同步 ==========

    BeakTrellis.prototype._syncRowHeights = function() {
        if (this.options.virtualScroll) return; // 固定列高，不需同步
        if (!this._leftTbodyEl || !this._rightTbodyEl) return;

        var leftRows = this._leftTbodyEl.querySelectorAll('tr');
        var rightRows = this._rightTbodyEl.querySelectorAll('tr');
        var len = Math.min(leftRows.length, rightRows.length);

        // 先重設高度，讓瀏覽器計算自然高度
        for (var i = 0; i < len; i++) {
            leftRows[i].style.height = '';
            rightRows[i].style.height = '';
        }

        // 讀取自然高度後設定為 max
        for (var i = 0; i < len; i++) {
            var maxH = Math.max(leftRows[i].offsetHeight, rightRows[i].offsetHeight);
            leftRows[i].style.height = maxH + 'px';
            rightRows[i].style.height = maxH + 'px';
        }

        // 同步表頭高度
        var leftTH = this._leftTableEl.querySelector('thead tr');
        var rightTH = this._rightTableEl.querySelector('thead tr');
        if (leftTH && rightTH) {
            leftTH.style.height = '';
            rightTH.style.height = '';
            var hMax = Math.max(leftTH.offsetHeight, rightTH.offsetHeight);
            leftTH.style.height = hMax + 'px';
            rightTH.style.height = hMax + 'px';
        }

        // 同步表尾高度
        var leftFR = this._leftTableEl.querySelector('tfoot tr');
        var rightFR = this._rightTableEl.querySelector('tfoot tr');
        if (leftFR && rightFR) {
            leftFR.style.height = '';
            rightFR.style.height = '';
            var fMax = Math.max(leftFR.offsetHeight, rightFR.offsetHeight);
            leftFR.style.height = fMax + 'px';
            rightFR.style.height = fMax + 'px';
        }
    };

    // ========== 垂直捲動同步 ==========

    BeakTrellis.prototype._setupScrollSync = function() {
        var self = this;
        var leftPane = this._leftPane;
        var rightPane = this._rightPane;
        if (!leftPane || !rightPane) return;

        // 右面板捲動 → 同步左面板 + VS 更新
        rightPane.addEventListener('scroll', function() {
            leftPane.scrollTop = rightPane.scrollTop;
            if (self.options.virtualScroll) {
                self._vsOnScroll();
            }
        });

        // 左面板滑鼠滾輪 → 轉發到右面板
        leftPane.addEventListener('wheel', function(e) {
            rightPane.scrollTop += e.deltaY;
            rightPane.scrollLeft += e.deltaX;
            e.preventDefault();
        }, { passive: false });
    };

    // ========== 分隔線拖曳 ==========

    BeakTrellis.prototype._setupSplitterDrag = function(splitter, leftPane) {
        var self = this;

        splitter.addEventListener('mousedown', function(e) {
            if (e.button !== 0) return;
            e.preventDefault();

            var startX = e.clientX;
            var startWidth = leftPane.offsetWidth;

            var onMove = function(me) {
                var diff = me.clientX - startX;
                var newWidth = Math.max(120, Math.min(startWidth + diff,
                    self.container.offsetWidth * 0.7));
                leftPane.style.width = newWidth + 'px';
                self._leftPaneWidth = newWidth;
            };

            var onUp = function() {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                document.body.style.cursor = '';
                document.body.style.userSelect = '';

                // 重新同步列高（寬度變化可能影響換行）
                requestAnimationFrame(function() {
                    self._syncRowHeights();
                    if (self._renderer && self._renderer.afterRender) {
                        self._renderer.afterRender(self);
                    }
                });
            };

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
        });
    };

    // ========== 左右面板 Hover/Click 同步 ==========

    BeakTrellis.prototype._setupRowSync = function() {
        var self = this;
        var leftPane = this._leftPane;
        var rightPane = this._rightPane;
        if (!leftPane || !rightPane) return;

        var currentHoverId = null;

        function findRowInTbody(tbody, id) {
            return tbody ? tbody.querySelector('tr[data-id="' + id + '"]') : null;
        }

        function setRowClass(id, cls, add) {
            var lt = self._leftTbodyEl || self._tbodyEl;
            var tr = findRowInTbody(lt, id);
            if (tr) tr.classList.toggle(cls, add);
            var rtr = findRowInTbody(self._rightTbodyEl, id);
            if (rtr) rtr.classList.toggle(cls, add);
        }

        // --- Hover 同步 ---
        function onHover(e, isLeft) {
            var tr = e.target.closest('tr.bt-row');
            var newId = tr ? tr.dataset.id : null;

            if (newId === currentHoverId) return;

            // 清除前一列
            if (currentHoverId) {
                setRowClass(currentHoverId, 'bt-row-hover', false);
            }

            currentHoverId = newId;
            if (!newId) return;

            // 對面加 hover（本側由瀏覽器 :hover 處理）
            var targetTbody = isLeft ? self._rightTbodyEl : (self._leftTbodyEl || self._tbodyEl);
            var targetTr = findRowInTbody(targetTbody, newId);
            if (targetTr) targetTr.classList.add('bt-row-hover');
        }

        function clearHover() {
            if (currentHoverId) {
                setRowClass(currentHoverId, 'bt-row-hover', false);
                currentHoverId = null;
            }
        }

        leftPane.addEventListener('mouseover', function(e) { onHover(e, true); });
        leftPane.addEventListener('mouseleave', clearHover);
        rightPane.addEventListener('mouseover', function(e) { onHover(e, false); });
        rightPane.addEventListener('mouseleave', clearHover);

        // --- Click 同步 ---
        function onRowClick(e) {
            if (e.target.tagName === 'INPUT') return;
            var tr = e.target.closest('tr.bt-row');
            if (!tr) return;
            var id = tr.dataset.id;

            var prev = self.container.querySelectorAll('.bt-row-active');
            for (var i = 0; i < prev.length; i++) {
                prev[i].classList.remove('bt-row-active');
            }

            setRowClass(id, 'bt-row-active', true);
        }

        leftPane.addEventListener('click', onRowClick);
        rightPane.addEventListener('click', onRowClick);
    };

    // ========== 欄位拖曳換位 ==========

    BeakTrellis.prototype._initColumnDrag = function(th, col, colIdx) {
        // 建立 ghost
        var rect = th.getBoundingClientRect();
        var ghost = _el('div', 'bt-col-drag-ghost');
        ghost.textContent = col.label || col.id;
        ghost.style.width = rect.width + 'px';
        document.body.appendChild(ghost);

        // 建立 drop 指示線
        var indicator = _el('div', 'bt-col-drop-indicator');
        document.body.appendChild(indicator);

        // 標記來源
        th.classList.add('bt-th-dragging');
        document.body.style.cursor = 'grabbing';
        document.body.style.userSelect = 'none';

        this._dragState = {
            th: th,
            col: col,
            fromIdx: colIdx,
            toIdx: colIdx,
            ghost: ghost,
            indicator: indicator
        };
    };

    BeakTrellis.prototype._updateColumnDrag = function(e) {
        var state = this._dragState;
        if (!state) return;

        // 移動 ghost
        state.ghost.style.left = (e.clientX + 12) + 'px';
        state.ghost.style.top = (e.clientY - 12) + 'px';

        // 計算放置位置
        var headerRow = this._rightTableEl.querySelector('thead tr');
        var ths = headerRow.querySelectorAll('th');
        var targetIdx = ths.length;
        var indicatorX = -1;

        for (var i = 0; i < ths.length; i++) {
            var rect = ths[i].getBoundingClientRect();
            if (e.clientX < rect.left + rect.width / 2) {
                targetIdx = i;
                indicatorX = rect.left;
                break;
            }
        }

        // 放在最後
        if (targetIdx === ths.length && ths.length > 0) {
            var lastRect = ths[ths.length - 1].getBoundingClientRect();
            indicatorX = lastRect.right;
        }

        state.toIdx = targetIdx;

        // 顯示指示線
        if (indicatorX >= 0) {
            var paneRect = this._rightPane.getBoundingClientRect();
            state.indicator.style.left = indicatorX + 'px';
            state.indicator.style.top = paneRect.top + 'px';
            state.indicator.style.height = paneRect.height + 'px';
            state.indicator.style.display = 'block';
        }
    };

    BeakTrellis.prototype._endColumnDrag = function() {
        var state = this._dragState;
        if (!state) return;

        // 清理
        if (state.ghost) state.ghost.remove();
        if (state.indicator) state.indicator.remove();
        if (state.th) state.th.classList.remove('bt-th-dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';

        var from = state.fromIdx;
        var to = state.toIdx;
        this._dragState = null;

        // 相同位置或緊鄰 → 不動作
        if (to === from || to === from + 1) return;

        this._reorderColumn(from, to);
    };

    BeakTrellis.prototype._reorderColumn = function(fromIdx, toIdx) {
        var dataCols = this._getDataColumns();
        var moved = dataCols.splice(fromIdx, 1)[0];
        if (toIdx > fromIdx) toIdx--;
        dataCols.splice(toIdx, 0, moved);

        // 重建 columns 陣列（保留 checkbox 位置）
        var newCols = [];
        var j = 0;
        for (var i = 0; i < this.options.columns.length; i++) {
            if (this.options.columns[i].type === 'checkbox') {
                newCols.push(this.options.columns[i]);
            } else {
                newCols.push(dataCols[j++]);
            }
        }
        this.options.columns = newCols;

        // 保存捲動狀態後重新渲染
        var scrollTop = this._rightPane ? this._rightPane.scrollTop : 0;
        var scrollLeft = this._rightPane ? this._rightPane.scrollLeft : 0;

        this._renderSplitPane();

        // 恢復捲動位置
        if (this._rightPane) {
            this._rightPane.scrollTop = scrollTop;
            this._rightPane.scrollLeft = scrollLeft;
            this._leftPane.scrollTop = scrollTop;
        }
    };

    // ========== 工具方法 ==========

    BeakTrellis.prototype._getDataColumns = function() {
        var result = [];
        for (var i = 0; i < this.options.columns.length; i++) {
            if (this.options.columns[i].type !== 'checkbox') {
                result.push(this.options.columns[i]);
            }
        }
        return result;
    };

    // ========== Virtual Scroll ==========

    /**
     * 建立 flatNodes 索引表 (id -> flatNodes index)
     */
    /**
     * 建立 flatNodes 索引表 + 累計 Y 偏移陣列
     * root 列 (level 0) 使用量測估計高度，其他列使用 rowHeight
     */
    BeakTrellis.prototype._vsBuildFlatIndex = function() {
        this._flatIndexMap = new Map();
        var rowH = this.options.rowHeight || 26;
        var rootH = this._vsRootRowHeight || rowH;
        var len = this._flatNodes.length;
        var offsets = new Array(len + 1);
        var y = 0;
        for (var i = 0; i < len; i++) {
            this._flatIndexMap.set(this._flatNodes[i].id, i);
            offsets[i] = y;
            y += (this._flatNodes[i].level === 0) ? rootH : rowH;
        }
        offsets[len] = y;
        this._vsYOffsets = offsets;
        this._vsTotalHeight = y;
    };

    /**
     * VS 模式完整渲染：建立左右面板結構，tbody 只放 spacer + 可見列
     */
    BeakTrellis.prototype._renderSplitPaneVS = function() {
        var self = this;
        var rowHeight = this.options.rowHeight || 26;
        this.options.rowHeight = rowHeight;
        var hasCheckbox = this.options.columns.some(function(c) { return c.type === 'checkbox'; });

        this._vsBuildFlatIndex();

        // === 左面板 ===
        var leftPane = _el('div', 'bt-pane-left');
        if (this._leftPaneWidth) leftPane.style.width = this._leftPaneWidth + 'px';

        var leftTable = _el('table', 'bt-table bt-table-left');
        var leftThead = document.createElement('thead');
        var leftHR = document.createElement('tr');

        if (hasCheckbox) {
            var thCb = _el('th', 'bt-th bt-th-checkbox');
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.className = 'bt-checkbox-all';
            cb.addEventListener('change', function() {
                cb.checked ? self.checkAll() : self.uncheckAll();
            });
            thCb.appendChild(cb);
            leftHR.appendChild(thCb);
        }

        var thTree = _el('th', 'bt-th bt-th-tree');
        var thTreeContent = _el('span', 'bt-th-content');
        thTreeContent.textContent = 'Tree';
        thTree.appendChild(thTreeContent);
        if (this.options.showExpandCollapseButtons) {
            this._appendExpandCollapseButtons(thTree);
        }
        leftHR.appendChild(thTree);
        leftThead.appendChild(leftHR);
        leftTable.appendChild(leftThead);

        var leftTbody = document.createElement('tbody');

        // 預填 spacer 撐高容器，確保首次 rAF 中 clientHeight 為正確值
        // （空 tbody 會導致 flex 容器高度僅等於表頭，viewportH 計算過小）
        var initSpacerH = this._vsTotalHeight;
        var lInitSpacer = document.createElement('tr');
        lInitSpacer.style.height = initSpacerH + 'px';
        lInitSpacer.appendChild(document.createElement('td'));
        leftTbody.appendChild(lInitSpacer);

        leftTable.appendChild(leftTbody);
        leftPane.appendChild(leftTable);

        // === 分隔線 ===
        var splitter = _el('div', 'bt-splitter');

        // === 右面板 ===
        var rightPane = _el('div', 'bt-pane-right');
        var rightTable = _el('table', 'bt-table bt-table-right');
        var rightThead = document.createElement('thead');
        var rightHR = document.createElement('tr');
        this._buildRightHeaders(rightHR);
        rightThead.appendChild(rightHR);
        rightTable.appendChild(rightThead);

        var rightTbody = document.createElement('tbody');
        var rInitSpacer = document.createElement('tr');
        rInitSpacer.style.height = initSpacerH + 'px';
        var rInitTd = document.createElement('td');
        rInitTd.colSpan = this._getDataColumns().length;
        rInitSpacer.appendChild(rInitTd);
        rightTbody.appendChild(rInitSpacer);

        rightTable.appendChild(rightTbody);

        // === 表尾（聚合，VS 模式也支援） ===
        if (Object.keys(this.options.aggregates).length > 0) {
            var leftTfoot = document.createElement('tfoot');
            var leftFR = _el('tr', 'bt-footer-row');
            if (hasCheckbox) leftFR.appendChild(_el('td', 'bt-td bt-td-footer'));
            leftFR.appendChild(_el('td', 'bt-td bt-td-footer'));
            leftTfoot.appendChild(leftFR);
            leftTable.appendChild(leftTfoot);
            rightTable.appendChild(this._createRightFooter());
        }

        rightPane.appendChild(rightTable);

        // === 組裝 ===
        this.container.appendChild(leftPane);
        this.container.appendChild(splitter);
        this.container.appendChild(rightPane);

        // === 儲存參照 ===
        this._leftPane = leftPane;
        this._rightPane = rightPane;
        this._splitter = splitter;
        this._leftTableEl = leftTable;
        this._rightTableEl = rightTable;
        this._leftTbodyEl = leftTbody;
        this._rightTbodyEl = rightTbody;
        this._tableEl = leftTable;
        this._tbodyEl = leftTbody;

        // === VS 狀態初始化 ===
        this._vsState = { startIdx: -1, endIdx: -1, totalRows: 0 };
        this._vsScrollRAF = null;

        // === 互動設定 ===
        this._setupScrollSync();
        this._setupSplitterDrag(splitter, leftPane);
        this._setupRowSync();

        // === 首次渲染可見列 ===
        requestAnimationFrame(function() {
            self._vsUpdateDOM();
        });
    };

    /**
     * VS 模式局部刷新（expand/collapse/setData 後觸發）
     */
    BeakTrellis.prototype._refreshSplitPaneVS = function() {
        // _computeFlatNodes() 已在 _refreshSplitPane 中呼叫
        this._vsBuildFlatIndex();
        // 強制重算：重設範圍
        this._vsState.startIdx = -1;
        this._vsState.endIdx = -1;
        this._vsUpdateDOM();
        this._refreshHeaderCheckbox();
        // 更新聚合表尾
        var hasCheckbox = this.options.columns.some(function(c) { return c.type === 'checkbox'; });
        this._refreshSplitFooter(hasCheckbox);
        // tfoot 更新後重新同步面板高度
        this._vsSyncPanelHeight();
    };

    /**
     * 捲動事件處理：用 rAF 節流 + 防重入鎖
     */
    BeakTrellis.prototype._vsOnScroll = function() {
        if (this._vsScrollRAF || this._vsRebuilding) return;
        var self = this;
        this._vsScrollRAF = requestAnimationFrame(function() {
            self._vsScrollRAF = null;
            self._vsUpdateDOM();
        });
    };

    /**
     * 計算可見範圍，如果範圍改變則重建 DOM
     */
    BeakTrellis.prototype._vsUpdateDOM = function() {
        if (!this._rightPane || this._vsRebuilding) return;

        var scrollTop = this._rightPane.scrollTop;
        var totalRows = this._flatNodes.length;
        var viewportH = this._rightPane.clientHeight;
        var buffer = 10;

        // 限制 scrollTop 不超過理論最大值（使用累計高度），防止底部震盪
        var maxScrollTop = Math.max(0, this._vsTotalHeight - viewportH);
        if (scrollTop > maxScrollTop) {
            scrollTop = maxScrollTop;
        }

        // 用累計 Y 偏移做 binary search，支援 root 列與非 root 列不同高度
        var rawStart = _vsFindRowAtY(this._vsYOffsets, scrollTop, totalRows);
        var rawEnd = _vsFindRowAtY(this._vsYOffsets, scrollTop + viewportH, totalRows) + 1;
        var startIdx = Math.max(0, rawStart - buffer);
        var endIdx = Math.min(totalRows, rawEnd + buffer);

        // 範圍未變化則跳過
        if (startIdx === this._vsState.startIdx && endIdx === this._vsState.endIdx
            && totalRows === this._vsState.totalRows) {
            return;
        }

        this._vsState.startIdx = startIdx;
        this._vsState.endIdx = endIdx;
        this._vsState.totalRows = totalRows;

        // 重建期間鎖定，防止 DOM 替換觸發的 scroll 事件造成遞迴
        this._vsRebuilding = true;
        var savedScrollTop = this._rightPane.scrollTop;
        this._vsRebuildTbodies(startIdx, endIdx);
        // 恢復 scrollTop（DOM 替換可能導致瀏覽器微調）
        this._rightPane.scrollTop = savedScrollTop;
        // 使用 rightPane 的 clamp 後實際值，避免左右 maxScrollTop 不同造成震盪
        this._leftPane.scrollTop = this._rightPane.scrollTop;
        var self = this;
        requestAnimationFrame(function() {
            self._vsRebuilding = false;
        });
    };

    /**
     * 重建左右 tbody：spacer-top + 可見列 + spacer-bottom
     */
    BeakTrellis.prototype._vsRebuildTbodies = function(startIdx, endIdx) {
        var rowHeight = this.options.rowHeight || 26;
        var totalRows = this._flatNodes.length;
        var hasCheckbox = this.options.columns.some(function(c) { return c.type === 'checkbox'; });
        var leftColSpan = hasCheckbox ? 2 : 1;
        var rightColSpan = this._getDataColumns().length;
        var self = this;

        var topH = this._vsYOffsets[startIdx];
        var bottomH = Math.max(0, this._vsTotalHeight - this._vsYOffsets[Math.min(endIdx, totalRows)]);

        // 左 tbody
        var newLeftTbody = document.createElement('tbody');
        newLeftTbody.appendChild(_vsSpacerRow(topH, leftColSpan));
        for (var i = startIdx; i < endIdx && i < totalRows; i++) {
            var node = this._flatNodes[i];
            var tr = this._createLeftRow(node, hasCheckbox);
            // root 列（level 0）不限制高度，允許配合右側 sources 等欄位自然展開
            if (node.level > 0) {
                tr.style.height = rowHeight + 'px';
                tr.style.maxHeight = rowHeight + 'px';
                tr.classList.add('bt-vs-row');
                _vsEnforceTdHeight(tr, rowHeight);
            }
            newLeftTbody.appendChild(tr);
        }
        newLeftTbody.appendChild(_vsSpacerRow(bottomH, leftColSpan));
        this._leftTableEl.replaceChild(newLeftTbody, this._leftTbodyEl);
        this._leftTbodyEl = newLeftTbody;
        this._tbodyEl = newLeftTbody;

        // 右 tbody
        var newRightTbody = document.createElement('tbody');
        newRightTbody.appendChild(_vsSpacerRow(topH, rightColSpan));
        for (var i = startIdx; i < endIdx && i < totalRows; i++) {
            var node = this._flatNodes[i];
            var tr = this._createRightRow(node);
            if (node.level > 0) {
                tr.style.height = rowHeight + 'px';
                tr.style.maxHeight = rowHeight + 'px';
                tr.classList.add('bt-vs-row');
                _vsEnforceTdHeight(tr, rowHeight);
            }
            newRightTbody.appendChild(tr);
        }
        newRightTbody.appendChild(_vsSpacerRow(bottomH, rightColSpan));
        this._rightTableEl.replaceChild(newRightTbody, this._rightTbodyEl);
        this._rightTbodyEl = newRightTbody;

        // === 高度對齊 ===
        // Step 1: 可見列左右高度同步（root 列可能因 sources 等欄位較高）
        _vsSyncVisibleRowHeights(newLeftTbody, newRightTbody);
        // Step 2: 左右 tbody 總高度同步（調整較矮側的底部 spacer）
        _vsSyncTbodyHeights(newLeftTbody, newRightTbody);
        // Step 3: 面板底部對齊（補償 tfoot 高度差異）
        self._vsSyncPanelHeight();

        // Step 4: 量測 root 列實際高度，更新累計偏移（修正 spacer 漂移）
        self._vsMeasureAndAdjustRootHeight(newLeftTbody, newRightTbody, startIdx, endIdx, totalRows);

        // 觸發渲染器後處理（tree-lines-dom overlay）
        requestAnimationFrame(function() {
            if (self._renderer && self._renderer.afterRender) {
                self._renderer.afterRender(self);
            }
        });
    };

    /**
     * 量測可見 root 列的實際高度，更新估計值。
     * 若估計值改變，重建 Y 偏移表並原地調整 spacer 高度，
     * 避免累計偏移導致深度捲動時畫面空白。
     */
    BeakTrellis.prototype._vsMeasureAndAdjustRootHeight = function(leftTbody, rightTbody, startIdx, endIdx, totalRows) {
        var rowH = this.options.rowHeight || 26;
        var rootRows = rightTbody.querySelectorAll('tr.bt-level-0.bt-row');
        if (rootRows.length === 0) return;

        var sum = 0;
        for (var i = 0; i < rootRows.length; i++) {
            sum += rootRows[i].getBoundingClientRect().height;
        }
        var avg = Math.round(sum / rootRows.length);
        var newEstimate = Math.max(rowH, avg);

        var oldEstimate = this._vsRootRowHeight || rowH;
        if (Math.abs(newEstimate - oldEstimate) <= 2) return;

        this._vsRootRowHeight = newEstimate;
        this._vsBuildFlatIndex();

        // 原地調整 spacer 高度
        var newTopH = this._vsYOffsets[startIdx];
        var newBottomH = Math.max(0, this._vsTotalHeight - this._vsYOffsets[Math.min(endIdx, totalRows)]);

        _vsSetSpacerHeight(leftTbody.firstChild, newTopH);
        _vsSetSpacerHeight(leftTbody.lastChild, newBottomH);
        _vsSetSpacerHeight(rightTbody.firstChild, newTopH);
        _vsSetSpacerHeight(rightTbody.lastChild, newBottomH);

        // 重新同步 tbody 高度（spacer 改變後左右可能不一致）
        _vsSyncTbodyHeights(leftTbody, rightTbody);
    };

    function _vsSetSpacerHeight(spacer, height) {
        if (height <= 0) {
            spacer.style.height = '';
            spacer.style.display = 'none';
        } else {
            spacer.style.height = height + 'px';
            spacer.style.display = '';
        }
    }

    /**
     * 將 tr 內每個 td 設定固定高度（overflow: hidden 在 td 層級才有效）
     */
    function _vsEnforceTdHeight(tr, rowHeight) {
        var tds = tr.getElementsByTagName('td');
        for (var t = 0; t < tds.length; t++) {
            tds[t].style.height = rowHeight + 'px';
            tds[t].style.maxHeight = rowHeight + 'px';
        }
    }

    /**
     * 同步左右 tbody 中可見列的高度。
     * root 列（level 0）可能因 sources/miniTree 等內容較高，
     * 取兩側最大值讓左右一致。
     */
    function _vsSyncVisibleRowHeights(leftTbody, rightTbody) {
        var leftRows = leftTbody.querySelectorAll('tr.bt-row');
        var rightRows = rightTbody.querySelectorAll('tr.bt-row');
        var count = Math.min(leftRows.length, rightRows.length);
        for (var i = 0; i < count; i++) {
            var lh = leftRows[i].getBoundingClientRect().height;
            var rh = rightRows[i].getBoundingClientRect().height;
            if (Math.abs(lh - rh) > 0.5) {
                var maxH = Math.ceil(Math.max(lh, rh));
                leftRows[i].style.height = maxH + 'px';
                leftRows[i].style.maxHeight = maxH + 'px';
                rightRows[i].style.height = maxH + 'px';
                rightRows[i].style.maxHeight = maxH + 'px';
            }
        }
    }

    /**
     * 同步左右 tbody 總高度，調整較矮側的底部 spacer。
     * 確保兩側可捲動範圍一致。
     */
    function _vsSyncTbodyHeights(leftTbody, rightTbody) {
        var leftH = Math.round(leftTbody.getBoundingClientRect().height);
        var rightH = Math.round(rightTbody.getBoundingClientRect().height);
        if (leftH === rightH) return;
        var targetH = Math.max(leftH, rightH);
        if (leftH < targetH) _adjustBottomSpacer(leftTbody, targetH - leftH);
        if (rightH < targetH) _adjustBottomSpacer(rightTbody, targetH - rightH);
    }

    function _adjustBottomSpacer(tbody, addPx) {
        var spacer = tbody.lastChild;
        if (!spacer) return;
        var current = parseFloat(spacer.style.height) || 0;
        spacer.style.height = (current + addPx) + 'px';
        spacer.style.display = '';
    }

    /**
     * 同步左右 tfoot 高度。
     * 右 tfoot 有聚合數值（可能多行），左 tfoot 只有空白佔位。
     * 直接讓左 tfoot tr 高度等於右 tfoot tr 高度，
     * 使粗線（border-top）位置一致，空白撐在粗線下方。
     */
    BeakTrellis.prototype._vsSyncPanelHeight = function() {
        var leftTfoot = this._leftTableEl ? this._leftTableEl.querySelector('tfoot') : null;
        var rightTfoot = this._rightTableEl ? this._rightTableEl.querySelector('tfoot') : null;
        if (!leftTfoot || !rightTfoot) return;
        var leftTR = leftTfoot.querySelector('tr');
        var rightTR = rightTfoot.querySelector('tr');
        if (!leftTR || !rightTR) return;
        leftTR.style.height = '';
        var rh = rightTR.getBoundingClientRect().height;
        leftTR.style.height = rh + 'px';
    };

    /**
     * 建立 spacer row（撐開虛擬高度）
     */
    function _vsSpacerRow(height, colSpan) {
        var tr = _el('tr', 'bt-vs-spacer');
        if (height <= 0) {
            tr.style.display = 'none';
        } else {
            tr.style.height = height + 'px';
        }
        var td = document.createElement('td');
        td.colSpan = colSpan;
        td.style.cssText = 'padding:0;border:0;line-height:0;font-size:0;';
        tr.appendChild(td);
        return tr;
    }

})();
