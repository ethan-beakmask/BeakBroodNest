/**
 * BeakTrellis 核心引擎
 * 組合 BeakTreeModel（beak-tree-model.js）+ Grid 渲染
 *
 * 功能：資料模型（委託 BeakTreeModel）、Tree 走訪、展開/收合、渲染調度、
 *       checkbox 多選、欄位排序、欄寬拖曳、欄位驗證、動態資料 API、聚合運算
 * 依賴：beak-tree-model.js
 * 授權：MIT
 */
'use strict';

class BeakTrellis {
    /**
     * @param {HTMLElement} container - 容器元素
     * @param {Object} options - 設定選項
     * @param {string} options.treeMode - 樹狀渲染模式
     * @param {Array} options.columns - 欄位定義陣列
     * @param {Array} options.data - 樹狀資料陣列
     * @param {number} [options.maxExpanded=500] - 最大展開節點數
     * @param {Object} [options.aggregates] - 欄位聚合運算定義
     * @param {Function} [options.onChecked] - 勾選回呼
     * @param {Function} [options.onExpand] - 展開回呼
     * @param {Function} [options.onCollapse] - 收合回呼
     * @param {Function} [options.onRowClick] - 列點擊回呼
     * @param {Function} [options.onExpandLimited] - 展開超限回呼
     */
    constructor(container, options) {
        if (!container || !(container instanceof HTMLElement)) {
            throw new Error('BeakTrellis: container 必須是有效的 HTMLElement');
        }
        if (!options || !options.columns || !options.data) {
            throw new Error('BeakTrellis: options 必須包含 columns 和 data');
        }

        this.container = container;
        this.options = Object.assign({
            treeMode: 'lines-dom',
            maxExpanded: 500,
            aggregates: {},
            onChecked: null,
            onExpand: null,
            onCollapse: null,
            onRowClick: null,
            onExpandLimited: null,
            showExpandCollapseButtons: false
        }, options);

        // 建立 BeakTreeModel（純資料層）
        this._model = new BeakTreeModel(this.options.data, {
            maxExpanded: this.options.maxExpanded,
            onExpand: this.options.onExpand,
            onCollapse: this.options.onCollapse,
            onExpandLimited: this.options.onExpandLimited,
            onChecked: this.options.onChecked
        });

        // Grid 專屬內部狀態
        this._tableEl = null;
        this._tbodyEl = null;
        this._renderer = null;
        this._sortColumnId = null;
        this._sortAsc = true;
        this._resizing = false;

        // Split Pane 狀態（由 bt-splitpane.js 使用）
        this._leftPane = null;
        this._rightPane = null;
        this._splitter = null;
        this._leftTableEl = null;
        this._rightTableEl = null;
        this._leftTbodyEl = null;
        this._rightTbodyEl = null;
        this._leftPaneWidth = null;
        this._dragState = null;

        // 欄位定義驗證
        this._validateColumns();

        // 不相容組合警告
        if (this.options.splitPane && this.options.treeMode === 'scope-brackets') {
            console.warn('BeakTrellis: scope-brackets 模式與 splitPane 不相容，閉括號列會導致左右表格行數不同步。建議改用 lines-dom 模式。');
        }

        // 初始化
        this._initRenderer();
        this.render();
    }

    // ========== BeakTreeModel 代理屬性 ==========
    // 讓既有程式碼（渲染器、splitpane plugin）無痛存取

    get _nodeMap() { return this._model._nodeMap; }
    get _expandedSet() { return this._model._expandedSet; }
    get _checkedSet() { return this._model._checkedSet; }
    get _flatNodes() { return this._model._flatNodes; }
    set _flatNodes(v) { this._model._flatNodes = v; }
    get _expandedCount() { return this._model._expandedCount; }
    set _expandedCount(v) { this._model._expandedCount = v; }

    // ========== 驗證 ==========

    _validateColumns() {
        var cols = this.options.columns;
        if (!Array.isArray(cols) || cols.length === 0) {
            console.warn('BeakTrellis: columns 為空陣列，表格將無資料欄位');
            return;
        }

        var idSet = new Set();
        for (var i = 0; i < cols.length; i++) {
            var col = cols[i];
            if (col.type === 'checkbox') continue;

            if (!col.id) {
                console.warn('BeakTrellis: columns[' + i + '] 缺少 id 屬性，該欄位將無法正確渲染');
            } else if (idSet.has(col.id)) {
                console.warn('BeakTrellis: columns 中 id "' + col.id + '" 重複，可能導致資料錯亂');
            } else {
                idSet.add(col.id);
            }

            if (!col.width && col.type !== 'timeline') {
                console.warn('BeakTrellis: columns[' + i + '] (id="' + (col.id || '?') + '") 未設定 width，欄寬將由瀏覽器自動分配');
            }
        }
    }

    _appendExpandCollapseButtons(thEl) {
        var self = this;
        var wrap = document.createElement('span');
        wrap.className = 'bt-ec-buttons';
        var btnExpand = document.createElement('button');
        btnExpand.className = 'bt-ec-btn';
        btnExpand.type = 'button';
        btnExpand.textContent = '+';
        btnExpand.title = 'Expand All';
        btnExpand.addEventListener('click', function(e) {
            e.stopPropagation();
            self.expandAll();
        });
        var btnCollapse = document.createElement('button');
        btnCollapse.className = 'bt-ec-btn';
        btnCollapse.type = 'button';
        btnCollapse.textContent = '-';
        btnCollapse.title = 'Collapse All';
        btnCollapse.addEventListener('click', function(e) {
            e.stopPropagation();
            self.collapseAll();
        });
        wrap.appendChild(btnExpand);
        wrap.appendChild(btnCollapse);
        thEl.appendChild(wrap);
    }

    // ========== BeakTreeModel 代理方法 ==========

    _computeFlatNodes() {
        return this._model.computeFlatNodes();
    }

    getNode(id) {
        return this._model.getNode(id);
    }

    getRootNodes() {
        return this._model.getRootNodes();
    }

    getAncestors(id) {
        return this._model.getAncestors(id);
    }

    getDescendants(id) {
        return this._model.getDescendants(id);
    }

    isExpanded(id) {
        return this._model.isExpanded(id);
    }

    hasChildren(id) {
        return this._model.hasChildren(id);
    }

    // ========== 展開/收合（代理 + UI 刷新） ==========

    expand(id, recursive) {
        var result = this._model.expand(id, recursive);
        if (result) this._refresh();
        return result;
    }

    collapse(id, recursive) {
        var result = this._model.collapse(id, recursive);
        if (result) this._refresh();
        return result;
    }

    toggle(id) {
        if (this._model.isExpanded(id)) {
            this.collapse(id);
        } else {
            this.expand(id);
        }
    }

    expandAll() {
        var result = this._model.expandAll();
        if (result) this._refresh();
        return result;
    }

    collapseAll() {
        this._model.collapseAll();
        this._refresh();
    }

    // ========== 節點移動（代理） ==========

    isDescendantOf(targetId, ancestorId) {
        return this._model.isDescendantOf(targetId, ancestorId);
    }

    moveNode(nodeId, newParentId, newIndex) {
        var result = this._model.moveNode(nodeId, newParentId, newIndex);
        if (result) this._refresh();
        return result;
    }

    // ========== Checkbox（代理 + UI 刷新） ==========

    getCheckState(id) {
        return this._model.getCheckState(id);
    }

    toggleCheck(id) {
        this._model.toggleCheck(id);
        this._refreshCheckboxes();
    }

    getCheckedIds(leafOnly) {
        return this._model.getCheckedIds(leafOnly);
    }

    checkAll() {
        this._model.checkAll();
        this._refreshCheckboxes();
    }

    uncheckAll() {
        this._model.uncheckAll();
        this._refreshCheckboxes();
    }

    // ========== 欄位運算 ==========

    aggregate(columnId, operation, nodeIds) {
        var nodes = nodeIds
            ? nodeIds.map(function(id) { return this._model.getNode(id); }.bind(this)).filter(Boolean)
            : this._model._flatNodes;

        var values = nodes
            .map(function(n) { return n.data[columnId]; })
            .filter(function(v) { return v !== undefined && v !== null && !isNaN(Number(v)); })
            .map(Number);

        if (values.length === 0) return null;

        if (operation === 'sum') {
            return values.reduce(function(a, b) { return a + b; }, 0);
        }
        if (operation === 'avg') {
            return values.reduce(function(a, b) { return a + b; }, 0) / values.length;
        }
        if (operation === 'max') {
            return Math.max.apply(null, values);
        }
        if (operation === 'min') {
            return Math.min.apply(null, values);
        }
        if (operation === 'count') {
            return values.length;
        }
        if (operation.startsWith('topN:')) {
            var n = parseInt(operation.split(':')[1], 10) || 5;
            return values.slice().sort(function(a, b) { return b - a; }).slice(0, n);
        }
        return null;
    }

    // ========== 渲染引擎 ==========

    _initRenderer() {
        var renderers = BeakTrellis.renderers || {};
        var mode = this.options.treeMode;

        if (renderers[mode]) {
            this._renderer = renderers[mode];
        } else {
            var model = this._model;
            this._renderer = {
                renderTreeCell: function(node, ancestors) {
                    var indent = '';
                    for (var i = 0; i < node.level; i++) indent += '\u00A0\u00A0';
                    var toggle = node.children.length > 0
                        ? (model.isExpanded(node.id) ? '[-] ' : '[+] ')
                        : '    ';
                    return indent + toggle + node.label;
                }
            };
        }
    }

    render() {
        if (this.options.splitPane && typeof this._renderSplitPane === 'function') {
            this._renderSplitPane();
            return;
        }
        this._computeFlatNodes();
        this.container.innerHTML = '';
        this.container.style.display = '';
        this.container.classList.add('bt-container');

        var table = document.createElement('table');
        table.className = 'bt-table';

        // 表頭
        var thead = document.createElement('thead');
        var headerRow = document.createElement('tr');

        var hasCheckbox = this.options.columns.some(function(c) { return c.type === 'checkbox'; });
        if (hasCheckbox) {
            var thCb = document.createElement('th');
            thCb.className = 'bt-th bt-th-checkbox';
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.className = 'bt-checkbox-all';
            var self = this;
            cb.addEventListener('change', function() {
                cb.checked ? self.checkAll() : self.uncheckAll();
            });
            thCb.appendChild(cb);
            headerRow.appendChild(thCb);
        }

        var thTree = document.createElement('th');
        thTree.className = 'bt-th bt-th-tree';
        thTree.textContent = '';
        if (this.options.showExpandCollapseButtons) {
            this._appendExpandCollapseButtons(thTree);
        }
        headerRow.appendChild(thTree);

        for (var i = 0; i < this.options.columns.length; i++) {
            var col = this.options.columns[i];
            if (col.type === 'checkbox') continue;
            var th = document.createElement('th');
            th.className = 'bt-th';
            th.dataset.columnId = col.id;
            if (col.width) {
                th.style.width = col.width;
            }

            var thContent = document.createElement('span');
            thContent.className = 'bt-th-content';
            thContent.textContent = col.label || col.id;

            if (col.sortable !== false && col.type !== 'timeline') {
                thContent.classList.add('bt-sortable');
                var sortIcon = document.createElement('span');
                sortIcon.className = 'bt-sort-icon';
                if (this._sortColumnId === col.id) {
                    sortIcon.textContent = this._sortAsc ? ' [A]' : ' [D]';
                }
                thContent.appendChild(sortIcon);

                (function(colId, grid) {
                    thContent.addEventListener('click', function() {
                        grid._toggleSort(colId);
                    });
                })(col.id, this);
            }
            th.appendChild(thContent);

            if (col.resizable !== false) {
                var resizer = document.createElement('span');
                resizer.className = 'bt-resizer';
                (function(thEl, colDef, grid) {
                    resizer.addEventListener('mousedown', function(e) {
                        grid._startResize(e, thEl, colDef);
                    });
                })(th, col, this);
                th.appendChild(resizer);
            }

            headerRow.appendChild(th);
        }

        thead.appendChild(headerRow);
        table.appendChild(thead);

        // 表身
        var tbody = document.createElement('tbody');
        var flatNodes = this._model._flatNodes;
        for (var i = 0; i < flatNodes.length; i++) {
            tbody.appendChild(this._createRow(flatNodes[i], hasCheckbox));
        }
        table.appendChild(tbody);

        // 表尾
        if (Object.keys(this.options.aggregates).length > 0) {
            table.appendChild(this._createFooter(hasCheckbox));
        }

        this.container.appendChild(table);
        this._tableEl = table;
        this._tbodyEl = tbody;

        if (this._renderer && this._renderer.afterRender) {
            this._renderer.afterRender(this);
        }
    }

    _createRow(node, hasCheckbox) {
        var self = this;
        var tr = document.createElement('tr');
        tr.className = 'bt-row bt-level-' + node.level;
        tr.dataset.id = node.id;

        if (this.options.rowClassFn) {
            var extraClass = this.options.rowClassFn(node);
            if (extraClass) tr.className += ' ' + extraClass;
        }

        if (this._model._checkedSet.has(node.id)) {
            tr.classList.add('bt-row-checked');
        }

        if (hasCheckbox) {
            var tdCb = document.createElement('td');
            tdCb.className = 'bt-td bt-td-checkbox';
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.className = 'bt-checkbox';
            cb.dataset.id = node.id;

            var state = this._model.getCheckState(node.id);
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
        var tdTree = document.createElement('td');
        tdTree.className = 'bt-td bt-td-tree';

        var ancestors = this._model.getAncestors(node.id);
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

        // 資料欄位
        for (var i = 0; i < this.options.columns.length; i++) {
            var col = this.options.columns[i];
            if (col.type === 'checkbox') continue;

            var td = document.createElement('td');
            td.className = 'bt-td bt-td-data';
            td.dataset.columnId = col.id;

            var cellValue = node.data[col.id];

            if (col.renderer && typeof col.renderer === 'function') {
                var cellContent = col.renderer(cellValue, node, col, this);
                if (typeof cellContent === 'string') {
                    td.innerHTML = cellContent;
                } else if (cellContent instanceof HTMLElement) {
                    td.appendChild(cellContent);
                }
            } else {
                td.textContent = (cellValue !== undefined && cellValue !== null)
                    ? String(cellValue) : '';
            }

            tr.appendChild(td);
        }

        tr.addEventListener('click', function(e) {
            if (e.target.tagName === 'INPUT') return;
            // 清除 focusNode 高亮
            var focused = self.container.querySelectorAll('.bt-row-focused');
            for (var f = 0; f < focused.length; f++) focused[f].classList.remove('bt-row-focused');
            if (self.options.onRowClick) {
                self.options.onRowClick(node.id, node, e);
            }
        });

        return tr;
    }

    _createFooter(hasCheckbox) {
        var tfoot = document.createElement('tfoot');
        var tr = document.createElement('tr');
        tr.className = 'bt-footer-row';

        if (hasCheckbox) {
            var td = document.createElement('td');
            td.className = 'bt-td bt-td-footer';
            tr.appendChild(td);
        }

        var tdTree = document.createElement('td');
        tdTree.className = 'bt-td bt-td-footer';
        tdTree.textContent = '';
        tr.appendChild(tdTree);

        for (var i = 0; i < this.options.columns.length; i++) {
            var col = this.options.columns[i];
            if (col.type === 'checkbox') continue;

            var td = document.createElement('td');
            td.className = 'bt-td bt-td-footer';
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
    }

    _refresh() {
        if (this.options.splitPane && typeof this._refreshSplitPane === 'function'
            && this._leftTbodyEl && this._rightTbodyEl) {
            this._refreshSplitPane();
            return;
        }
        this._computeFlatNodes();
        if (!this._tbodyEl || !this._tableEl) {
            this.render();
            return;
        }

        var hasCheckbox = this.options.columns.some(function(c) { return c.type === 'checkbox'; });

        var newTbody = document.createElement('tbody');
        var flatNodes = this._model._flatNodes;
        for (var i = 0; i < flatNodes.length; i++) {
            newTbody.appendChild(this._createRow(flatNodes[i], hasCheckbox));
        }
        this._tableEl.replaceChild(newTbody, this._tbodyEl);
        this._tbodyEl = newTbody;

        if (this._renderer && this._renderer.afterRender) {
            this._renderer.afterRender(this);
        }

        this._refreshFooter(hasCheckbox);
        this._refreshHeaderCheckbox();
    }

    _refreshCheckboxes() {
        if (!this._tbodyEl) return;

        var checkboxes = this._tbodyEl.querySelectorAll('.bt-checkbox');
        for (var i = 0; i < checkboxes.length; i++) {
            var cb = checkboxes[i];
            var id = cb.dataset.id;
            var state = this._model.getCheckState(id);
            cb.checked = (state === 'checked');
            cb.indeterminate = (state === 'indeterminate');

            var tr = cb.closest('tr');
            if (tr) {
                tr.classList.toggle('bt-row-checked', state === 'checked');
            }

            // Split Pane: 同步右面板
            if (this._rightTbodyEl) {
                var rightTr = this._rightTbodyEl.querySelector('tr[data-id="' + id + '"]');
                if (rightTr) {
                    rightTr.classList.toggle('bt-row-checked', state === 'checked');
                }
            }
        }

        this._refreshHeaderCheckbox();
    }

    _refreshHeaderCheckbox() {
        var headerCb = this.container.querySelector('.bt-checkbox-all');
        if (!headerCb) return;

        var totalLeaves = this._model.countLeaves();
        var checkedLeaves = this._model.countCheckedLeaves();

        headerCb.checked = (totalLeaves > 0 && checkedLeaves === totalLeaves);
        headerCb.indeterminate = (checkedLeaves > 0 && checkedLeaves < totalLeaves);
    }

    _refreshFooter(hasCheckbox) {
        if (!this._tableEl || Object.keys(this.options.aggregates).length === 0) return;

        var oldFoot = this._tableEl.querySelector('tfoot');
        if (oldFoot) {
            this._tableEl.replaceChild(this._createFooter(hasCheckbox), oldFoot);
        }
    }

    // ========== 排序 ==========

    _toggleSort(columnId) {
        if (this._sortColumnId === columnId) {
            if (this._sortAsc) {
                this._sortAsc = false;
            } else {
                this._sortColumnId = null;
                this._sortAsc = true;
            }
        } else {
            this._sortColumnId = columnId;
            this._sortAsc = true;
        }
        this._applySortToTree();
        this.render();
    }

    _applySortToTree() {
        var colId = this._sortColumnId;
        var asc = this._sortAsc;

        if (!colId) {
            this._model._nodeMap.forEach(function(node) {
                node.children.sort(function(a, b) { return a._index - b._index; });
            });
            return;
        }

        var sortChildren = function(children) {
            children.sort(function(a, b) {
                var va = a.data[colId];
                var vb = b.data[colId];
                if (va !== undefined && vb !== undefined && !isNaN(Number(va)) && !isNaN(Number(vb))) {
                    return asc ? Number(va) - Number(vb) : Number(vb) - Number(va);
                }
                va = va !== undefined && va !== null ? String(va) : '';
                vb = vb !== undefined && vb !== null ? String(vb) : '';
                return asc ? va.localeCompare(vb) : vb.localeCompare(va);
            });
            for (var i = 0; i < children.length; i++) {
                if (children[i].children.length > 0) {
                    sortChildren(children[i].children);
                }
            }
        };

        var roots = this._model.getRootNodes();
        roots.sort(function(a, b) {
            var va = a.data[colId];
            var vb = b.data[colId];
            if (va !== undefined && vb !== undefined && !isNaN(Number(va)) && !isNaN(Number(vb))) {
                return asc ? Number(va) - Number(vb) : Number(vb) - Number(va);
            }
            va = va !== undefined && va !== null ? String(va) : '';
            vb = vb !== undefined && vb !== null ? String(vb) : '';
            return asc ? va.localeCompare(vb) : vb.localeCompare(va);
        });

        for (var i = 0; i < roots.length; i++) {
            roots[i]._index = i;
        }

        this._model._nodeMap.forEach(function(node) {
            if (node.children.length > 0) {
                sortChildren(node.children);
                for (var i = 0; i < node.children.length; i++) {
                    node.children[i]._index = i;
                }
            }
        });
    }

    // ========== 欄寬拖曳 ==========

    _startResize(e, th, col) {
        e.preventDefault();
        e.stopPropagation();
        this._resizing = true;

        var startX = e.clientX;
        var startWidth = th.offsetWidth;

        var dataThs = th.parentElement.querySelectorAll('th[data-column-id]');
        var dataCols = this.options.columns.filter(function(c) { return c.type !== 'checkbox'; });
        for (var i = 0; i < dataThs.length && i < dataCols.length; i++) {
            var w = dataThs[i].offsetWidth;
            dataThs[i].style.width = w + 'px';
            dataCols[i].width = w + 'px';
        }

        var nextTh = th.nextElementSibling;
        var nextStartWidth = nextTh ? nextTh.offsetWidth : 0;
        var nextCol = null;
        if (nextTh) {
            var idx = dataCols.indexOf(col);
            if (idx >= 0 && idx + 1 < dataCols.length) {
                nextCol = dataCols[idx + 1];
            }
        }

        var onMove = function(moveE) {
            var diff = moveE.clientX - startX;
            var newWidth = Math.max(40, startWidth + diff);
            th.style.width = newWidth + 'px';
            col.width = newWidth + 'px';

            if (nextTh) {
                var nextNewWidth = Math.max(40, nextStartWidth - diff);
                nextTh.style.width = nextNewWidth + 'px';
                if (nextCol) nextCol.width = nextNewWidth + 'px';
            }
        };

        var self = this;
        var onUp = function() {
            self._resizing = false;
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            document.body.style.cursor = '';
            document.body.style.userSelect = '';

            if (self.options.splitPane && typeof self._syncRowHeights === 'function') {
                requestAnimationFrame(function() { self._syncRowHeights(); });
            }
        };

        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    }

    // ========== 公開 API ==========

    setTreeMode(mode) {
        this.options.treeMode = mode;
        this._initRenderer();
        this.render();
    }

    setColumns(columns) {
        this.options.columns = columns;
        this.render();
    }

    setData(data) {
        this._model.setData(data);
        this.render();
    }

    getVisibleCount() {
        return this._model.getVisibleCount();
    }

    // ========== 節點導航 ==========

    focusNode(id, opts) {
        var node = this._model.getNode(id);
        if (!node) return false;

        opts = Object.assign({ expanded: false, highlight: true }, opts || {});

        // 展開所有祖先
        var ancestors = this._model.getAncestors(id);
        var needRefresh = false;
        for (var i = 0; i < ancestors.length; i++) {
            if (!this._model.isExpanded(ancestors[i].id)) {
                this._model.expand(ancestors[i].id);
                needRefresh = true;
            }
        }

        // 展開節點本身
        if (opts.expanded && node.children.length > 0 && !this._model.isExpanded(id)) {
            this._model.expand(id);
            needRefresh = true;
        }

        if (needRefresh) this._refresh();

        // 找到 DOM row（splitPane 下在左表格）
        var tbody = this._tbodyEl || this._leftTbodyEl;
        var row = tbody ? tbody.querySelector('tr[data-id="' + id + '"]') : null;
        if (!row) return false;

        // 捲動（splitPane 下需要操作右面板）
        if (this.options.splitPane && this._rightPane) {
            var rowTop = row.offsetTop;
            var paneHeight = this._rightPane.clientHeight;
            this._rightPane.scrollTop = rowTop - paneHeight / 2 + row.offsetHeight / 2;
        } else {
            row.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }

        // 高亮
        if (opts.highlight) {
            var oldFocus = this.container.querySelector('.bt-row-focused');
            if (oldFocus) oldFocus.classList.remove('bt-row-focused');

            row.classList.add('bt-row-focused');

            // splitPane 下同步右側 row 高亮
            if (this._rightTbodyEl) {
                var rightRow = this._rightTbodyEl.querySelector('tr[data-id="' + id + '"]');
                if (rightRow) rightRow.classList.add('bt-row-focused');
            }
        }

        return true;
    }

    // ========== 動態資料操作 ==========

    addChildren(parentId, childrenData) {
        var result = this._model.addChildren(parentId, childrenData);
        if (result) this._refresh();
        return result;
    }

    removeChildren(parentId) {
        var result = this._model.removeChildren(parentId);
        if (result) this._refresh();
        return result;
    }

    updateNodeData(id, data) {
        var result = this._model.updateNodeData(id, data);
        if (result) this._refresh();
        return result;
    }

    destroy() {
        this.container.innerHTML = '';
        this._model.destroy();
        this._tableEl = null;
        this._tbodyEl = null;
    }
}

// 靜態屬性：渲染器註冊表
BeakTrellis.renderers = {};

BeakTrellis.registerRenderer = function(name, renderer) {
    BeakTrellis.renderers[name] = renderer;
};
