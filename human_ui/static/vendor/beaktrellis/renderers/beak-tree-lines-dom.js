/**
 * Tree Lines DOM 渲染器
 * 用 DOM overlay 繪製連續不斷裂的 OS tree 風格線條
 *
 * 原理：
 *   CSS pseudo-element 方案的線條受限於單一 cell 高度（22px），
 *   當 table row 因 padding/border/其他欄位內容而實際更高時，
 *   相鄰列之間的垂直線會出現斷裂。
 *
 *   DOM overlay 方案在 table 上方疊加一層 position:absolute 的 div，
 *   根據每一列的實際 DOM 位置計算線條座標，
 *   繪製跨越多列的連續線段，徹底消除斷裂。
 *
 * 提供：
 *   - 'lines-dom' 渲染器：主 Tree 連續線條
 *   - DomMiniTree.create()：Cell 內嵌迷你樹（也用 overlay 連續線條）
 */
'use strict';

(function() {

    var INDENT_W = 20;   // 每層縮排寬度 px
    var LINE_X = 9;      // 線條在 indent 區塊中的 x 偏移（中心）
    var LINE_COLOR = '#999';

    // ========== 主 Tree: lines-dom 渲染器 ==========

    /**
     * 渲染 tree cell 內容（僅佔位空間 + toggle + label，不畫線）
     */
    function renderTreeCell(node, ancestors, grid) {
        var cell = document.createElement('div');
        cell.className = 'bt-tree-cell bt-dom-cell';

        // 祖先層佔位（空白 span，線條由 overlay 繪製）
        for (var i = 0; i < ancestors.length; i++) {
            var sp = document.createElement('span');
            sp.className = 'bt-indent bt-indent-blank';
            cell.appendChild(sp);
        }

        // 分支佔位（非根節點需要）
        if (node.level > 0) {
            var br = document.createElement('span');
            br.className = 'bt-branch';
            cell.appendChild(br);
        }

        // 展開/收合按鈕
        if (node.children.length > 0) {
            var tog = document.createElement('span');
            tog.className = 'bt-toggle bt-toggle';
            tog.classList.add(grid.isExpanded(node.id) ? 'bt-toggle-expanded' : 'bt-toggle-collapsed');
            tog.textContent = grid.isExpanded(node.id) ? '[-]' : '[+]';
            cell.appendChild(tog);
        } else {
            var leaf = document.createElement('span');
            leaf.className = 'bt-leaf-spacer';
            cell.appendChild(leaf);
        }

        // 標籤
        var lbl = document.createElement('span');
        lbl.className = 'bt-label';
        lbl.textContent = node.label;
        cell.appendChild(lbl);

        return cell;
    }

    /**
     * 渲染完成後：建立 overlay 並繪製連續線條
     */
    function afterRender(grid) {
        // 使用 rAF 確保 DOM layout 已完成
        requestAnimationFrame(function() {
            if (grid.options.virtualScroll && grid._vsState) {
                _drawMainTreeLinesVS(grid);
            } else {
                _drawMainTreeLines(grid);
            }
            _drawAllMiniTreeLines(grid);
        });
    }

    // ---------- 主 Tree overlay ----------

    function _drawMainTreeLines(grid) {
        var container = grid.container;
        var table = grid._tableEl;
        var tbody = grid._tbodyEl;
        if (!tbody || !table) return;

        // 確保 table 包在 position:relative wrapper 內
        var wrapper = table.parentElement;
        if (!wrapper || !wrapper.classList.contains('bt-dom-wrapper')) {
            wrapper = document.createElement('div');
            wrapper.className = 'bt-dom-wrapper';
            wrapper.style.position = 'relative';
            table.parentNode.insertBefore(wrapper, table);
            wrapper.appendChild(table);
        }

        // 移除舊 overlay
        var old = wrapper.querySelector('.bt-line-overlay');
        if (old) old.remove();

        // 建立新 overlay
        var overlay = document.createElement('div');
        overlay.className = 'bt-line-overlay';
        overlay.style.cssText =
            'position:absolute;top:0;left:0;' +
            'width:' + table.offsetWidth + 'px;' +
            'height:' + table.offsetHeight + 'px;' +
            'pointer-events:none;z-index:5;';
        wrapper.appendChild(overlay);

        // 收集列位置資料
        var flatNodes = grid._flatNodes;
        var rows = tbody.querySelectorAll('tr.bt-row:not(.bt-row-closing)');
        if (rows.length === 0 || flatNodes.length === 0) return;

        var rowData = [];
        for (var i = 0; i < flatNodes.length && i < rows.length; i++) {
            var row = rows[i];
            rowData.push({
                node: flatNodes[i],
                top: row.offsetTop,
                h: row.offsetHeight,
                midY: row.offsetTop + row.offsetHeight / 2
            });
        }

        // tree 欄的 left offset
        var treeTd = rows[0].querySelector('.bt-td-tree');
        if (!treeTd) return;
        var treeLeft = treeTd.offsetLeft;

        // === 繪製線條 ===
        for (var i = 0; i < rowData.length; i++) {
            var rd = rowData[i];
            var nd = rd.node;

            // (A) 已展開父節點 → 垂直線從自己到最後一個可見直接子節點
            if (grid.isExpanded(nd.id) && nd.children.length > 0) {
                var lastChildIdx = _findLastDirectChild(flatNodes, rowData, i, nd.id, nd.level);
                if (lastChildIdx >= 0) {
                    var x = treeLeft + nd.level * INDENT_W + LINE_X;
                    _addVLine(overlay, x, rd.midY, rowData[lastChildIdx].midY);
                }
            }

            // (B) 非根節點 → 水平分支線從父層垂直線到本節點
            if (nd.level > 0 && nd.parentId) {
                var x1 = treeLeft + (nd.level - 1) * INDENT_W + LINE_X;
                var x2 = treeLeft + nd.level * INDENT_W + LINE_X;
                _addHLine(overlay, x1, x2, rd.midY);
            }
        }
    }

    /**
     * 在 rowData 中找到指定父節點的最後一個直接子節點的索引
     */
    function _findLastDirectChild(flatNodes, rowData, parentIdx, parentId, parentLevel) {
        var last = -1;
        for (var j = parentIdx + 1; j < rowData.length; j++) {
            if (rowData[j].node.level <= parentLevel) break;
            if (rowData[j].node.parentId === parentId) {
                last = j;
            }
        }
        return last;
    }

    // ---------- 線條繪製工具 ----------

    function _addVLine(parent, x, y1, y2) {
        var el = document.createElement('div');
        el.className = 'bt-ol-vline';
        el.style.cssText =
            'position:absolute;' +
            'left:' + x + 'px;' +
            'top:' + y1 + 'px;' +
            'height:' + (y2 - y1) + 'px;' +
            'border-left:1px solid ' + LINE_COLOR + ';';
        parent.appendChild(el);
    }

    function _addHLine(parent, x1, x2, y) {
        var el = document.createElement('div');
        el.className = 'bt-ol-hline';
        el.style.cssText =
            'position:absolute;' +
            'left:' + x1 + 'px;' +
            'top:' + y + 'px;' +
            'width:' + (x2 - x1) + 'px;' +
            'border-top:1px solid ' + LINE_COLOR + ';';
        parent.appendChild(el);
    }

    // ========== miniTree DOM overlay ==========

    var MINI_INDENT = 14;
    var MINI_LINE_X = 5;
    var MINI_LINE_COLOR = '#aaa';

    /**
     * 掃描頁面上所有 .bt-minitree-dom 容器，繪製 overlay 線條
     */
    function _drawAllMiniTreeLines(grid) {
        var containers = grid.container.querySelectorAll('.bt-minitree-dom');
        for (var i = 0; i < containers.length; i++) {
            _drawMiniLines(containers[i]);
        }
    }

    function _drawMiniLines(container) {
        // 移除舊 overlay
        var old = container.querySelector('.bt-mini-overlay');
        if (old) old.remove();

        var rows = container.querySelectorAll('.bt-mini-dom-row');
        if (rows.length === 0) return;

        var overlay = document.createElement('div');
        overlay.className = 'bt-mini-overlay';
        overlay.style.cssText =
            'position:absolute;top:0;left:0;' +
            'width:100%;height:100%;pointer-events:none;';

        // 收集列位置
        var rowData = [];
        for (var i = 0; i < rows.length; i++) {
            var r = rows[i];
            rowData.push({
                top: r.offsetTop,
                h: r.offsetHeight,
                midY: r.offsetTop + r.offsetHeight / 2,
                level: parseInt(r.dataset.level, 10) || 0,
                hasChildren: r.dataset.hasChildren === '1',
                parentIdx: parseInt(r.dataset.parentIdx, 10)
            });
        }

        // 繪製
        for (var i = 0; i < rowData.length; i++) {
            var rd = rowData[i];

            // 垂直線：有子節點的列 → 最後一個直接子節點
            if (rd.hasChildren) {
                var lastChild = -1;
                for (var j = i + 1; j < rowData.length; j++) {
                    if (rowData[j].level <= rd.level) break;
                    if (rowData[j].level === rd.level + 1) {
                        lastChild = j;
                    }
                }
                if (lastChild >= 0) {
                    _addMiniVLine(overlay, rd.level * MINI_INDENT + MINI_LINE_X,
                        rd.midY, rowData[lastChild].midY);
                }
            }

            // 水平分支
            if (rd.level > 0) {
                var x1 = (rd.level - 1) * MINI_INDENT + MINI_LINE_X;
                var x2 = rd.level * MINI_INDENT;
                _addMiniHLine(overlay, x1, x2, rd.midY);
            }
        }

        container.appendChild(overlay);
    }

    function _addMiniVLine(parent, x, y1, y2) {
        var el = document.createElement('div');
        el.style.cssText =
            'position:absolute;' +
            'left:' + x + 'px;' +
            'top:' + y1 + 'px;' +
            'height:' + (y2 - y1) + 'px;' +
            'border-left:1px solid ' + MINI_LINE_COLOR + ';';
        parent.appendChild(el);
    }

    function _addMiniHLine(parent, x1, x2, y) {
        var el = document.createElement('div');
        el.style.cssText =
            'position:absolute;' +
            'left:' + x1 + 'px;' +
            'top:' + y + 'px;' +
            'width:' + (x2 - x1) + 'px;' +
            'border-top:1px solid ' + MINI_LINE_COLOR + ';';
        parent.appendChild(el);
    }

    // ========== DomMiniTree 元件工廠 ==========

    /**
     * 建立 DOM 版 miniTree 渲染器
     * @param {Object} opts
     * @param {number} [opts.indentPx=14]
     * @returns {Function} column renderer
     */
    function createDomMiniTree(opts) {
        opts = Object.assign({ indentPx: 14 }, opts || {});

        return function(value, node, col) {
            var data = Array.isArray(value) ? value : [];
            if (data.length === 0) {
                return '<span style="color:#bbb;font-size:11px;">--</span>';
            }

            var container = document.createElement('div');
            container.className = 'bt-minitree bt-minitree-dom';
            container.style.position = 'relative';

            // 扁平化樹結構
            var flatRows = [];
            function flatten(nodes, level, parentFlatIdx) {
                for (var i = 0; i < nodes.length; i++) {
                    var n = nodes[i];
                    var hasChildren = !!(n.children && n.children.length > 0);
                    var myIdx = flatRows.length;
                    flatRows.push({
                        label: n.label || '',
                        level: level,
                        hasChildren: hasChildren,
                        parentFlatIdx: parentFlatIdx
                    });
                    if (hasChildren) {
                        flatten(n.children, level + 1, myIdx);
                    }
                }
            }
            flatten(data, 0, -1);

            // 建立 row div
            for (var i = 0; i < flatRows.length; i++) {
                var fr = flatRows[i];
                var rowDiv = document.createElement('div');
                rowDiv.className = 'bt-mini-dom-row';
                rowDiv.dataset.level = fr.level;
                rowDiv.dataset.hasChildren = fr.hasChildren ? '1' : '0';
                rowDiv.dataset.parentIdx = fr.parentFlatIdx;

                // 縮排佔位（空白，線由 overlay 繪製）
                for (var j = 0; j < fr.level; j++) {
                    var sp = document.createElement('span');
                    sp.className = 'bt-mini-spacer';
                    sp.style.cssText = 'display:inline-block;width:' + opts.indentPx + 'px;';
                    rowDiv.appendChild(sp);
                }

                // 分支佔位
                if (fr.level > 0) {
                    var brSp = document.createElement('span');
                    brSp.className = 'bt-mini-branch-spacer';
                    brSp.style.cssText = 'display:inline-block;width:' + opts.indentPx + 'px;';
                    rowDiv.appendChild(brSp);
                }

                // 標籤
                var lbl = document.createElement('span');
                lbl.className = 'bt-mini-label';
                lbl.textContent = fr.label;
                rowDiv.appendChild(lbl);

                container.appendChild(rowDiv);
            }

            return container;
        };
    }

    // ========== Virtual Scroll 線條繪製 ==========

    /**
     * VS 模式：用數學座標繪製樹線，不依賴 DOM 量測
     * 可見列有 DOM，離屏父節點用 flatIndexMap 計算位置
     */
    function _drawMainTreeLinesVS(grid) {
        var table = grid._tableEl;
        var tbody = grid._tbodyEl;
        if (!tbody || !table) return;

        var state = grid._vsState;
        if (!state) return;

        var rowHeight = grid.options.rowHeight || 26;
        var startIdx = state.startIdx;
        var endIdx = Math.min(state.endIdx, grid._flatNodes.length);
        var flatNodes = grid._flatNodes;

        // 確保 wrapper
        var wrapper = table.parentElement;
        if (!wrapper || !wrapper.classList.contains('bt-dom-wrapper')) {
            wrapper = document.createElement('div');
            wrapper.className = 'bt-dom-wrapper';
            wrapper.style.position = 'relative';
            table.parentNode.insertBefore(wrapper, table);
            wrapper.appendChild(table);
        }

        // 移除舊 overlay
        var old = wrapper.querySelector('.bt-line-overlay');
        if (old) old.remove();

        // 建立新 overlay
        var overlay = document.createElement('div');
        overlay.className = 'bt-line-overlay';
        overlay.style.cssText =
            'position:absolute;top:0;left:0;' +
            'width:' + table.offsetWidth + 'px;' +
            'height:' + table.offsetHeight + 'px;' +
            'pointer-events:none;z-index:5;';
        wrapper.appendChild(overlay);

        // 從 DOM 取得 treeLeft（只需第一個可見列的偏移）
        var dataRows = tbody.querySelectorAll('tr.bt-row');
        if (dataRows.length === 0) return;
        var treeTd = dataRows[0].querySelector('.bt-td-tree');
        if (!treeTd) return;
        var treeLeft = treeTd.offsetLeft;

        // 第一個可見列的 DOM offsetTop（spacer 之後）
        var firstRowTop = dataRows[0].offsetTop;

        // 使用累計 Y 偏移計算 midY，支援 root 列不同高度
        var yOffsets = grid._vsYOffsets;
        var rootRowH = grid._vsRootRowHeight || rowHeight;
        function getRowH(idx) {
            return (grid._flatNodes[idx].level === 0) ? rootRowH : rowHeight;
        }
        function midY(idx) {
            if (yOffsets) {
                return firstRowTop + (yOffsets[idx] - yOffsets[startIdx]) + getRowH(idx) / 2;
            }
            return firstRowTop + (idx - startIdx) * rowHeight + rowHeight / 2;
        }

        // 可見繪製區域（clipping）
        var clipTop = firstRowTop;
        var clipBottom = yOffsets
            ? firstRowTop + (yOffsets[endIdx] - yOffsets[startIdx])
            : firstRowTop + (endIdx - startIdx) * rowHeight;

        // 取得父節點最後直接子節點的 flatIndex（O(1) 查找）
        function lastDirectChildFlatIdx(parentId) {
            var parent = grid._nodeMap.get(parentId);
            if (!parent || parent.children.length === 0) return -1;
            var lastChild = parent.children[parent.children.length - 1];
            var idx = grid._flatIndexMap ? grid._flatIndexMap.get(lastChild.id) : undefined;
            return (idx !== undefined) ? idx : -1;
        }

        var drawnVLines = new Set();

        for (var i = startIdx; i < endIdx; i++) {
            var nd = flatNodes[i];
            var my = midY(i);

            // (A) 已展開父節點 → 垂直線到最後直接子節點
            if (grid.isExpanded(nd.id) && nd.children.length > 0) {
                var lcIdx = lastDirectChildFlatIdx(nd.id);
                if (lcIdx >= 0) {
                    var x = treeLeft + nd.level * INDENT_W + LINE_X;
                    var y1 = Math.max(clipTop, my);
                    var y2 = Math.min(clipBottom, midY(lcIdx));
                    if (y2 > y1) _addVLine(overlay, x, y1, y2);
                    drawnVLines.add(nd.id);
                }
            }

            // (B) 非根節點 → 水平分支線
            if (nd.level > 0 && nd.parentId) {
                var x1 = treeLeft + (nd.level - 1) * INDENT_W + LINE_X;
                var x2 = treeLeft + nd.level * INDENT_W + LINE_X;
                _addHLine(overlay, x1, x2, my);
            }

            // (C) 離屏祖先的續線（父節點在 startIdx 之上）
            var current = nd;
            while (current.parentId) {
                var parentNode = grid._nodeMap.get(current.parentId);
                if (!parentNode) break;
                if (drawnVLines.has(parentNode.id)) break;
                if (!grid.isExpanded(parentNode.id)) break;

                var parentFlatIdx = grid._flatIndexMap
                    ? grid._flatIndexMap.get(parentNode.id) : undefined;
                if (parentFlatIdx === undefined) break;
                // 父節點在可見範圍內，由 (A) 處理
                if (parentFlatIdx >= startIdx && parentFlatIdx < endIdx) break;

                var lcIdx2 = lastDirectChildFlatIdx(parentNode.id);
                if (lcIdx2 >= 0) {
                    var x = treeLeft + parentNode.level * INDENT_W + LINE_X;
                    var y1 = Math.max(clipTop, midY(parentFlatIdx));
                    var y2 = Math.min(clipBottom, midY(lcIdx2));
                    if (y2 > y1) _addVLine(overlay, x, y1, y2);
                }
                drawnVLines.add(parentNode.id);

                current = parentNode;
            }
        }
    }

    // ========== 註冊 ==========

    var rendererDef = {
        renderTreeCell: renderTreeCell,
        afterRender: afterRender
    };

    // 同時註冊到 BeakTrellis 和 Tree（獨立元件）
    if (typeof BeakTrellis !== 'undefined' && BeakTrellis.registerRenderer) {
        BeakTrellis.registerRenderer('lines-dom', rendererDef);
    }
    if (typeof BeakTree !== 'undefined' && BeakTree.registerRenderer) {
        BeakTree.registerRenderer('lines-dom', rendererDef);
    }

    // 公開 miniTree 工廠到全域
    window.DomMiniTree = {
        create: createDomMiniTree
    };

})();
