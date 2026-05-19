/**
 * 白板 Mixin: 心智圖殼 (canvas_mindmap_shells) + 樹結構 (unified_relations.tree_parent)
 *
 * 殼:畫布層的視覺容器，內部節點 = canvas_atoms.mindmap_shell_id 指向此殼。
 *   render 時節點為 mini 卡（小、只標題），位置由 tree layout 自動計算。
 * 樹:由 unified_relations(relation_type='tree_parent') 表達，方向 child -> parent。
 *   sort_order 決定同層次序。
 * 熱鍵:focus 在殼內某節點時 -- Tab=新增子節點、Enter=新增同層、Del=刪除子樹、字元=改標題
 *
 * Mini 節點視覺由 CSS 類 wb-mindmap-node 控制（見 whiteboard.css）。
 */
function whiteboardMindmapMixin() {
    return {

        // ---- 狀態（與主 app 合併） ----
        // mindmapShells: [],     // 由 whiteboard.js 主 app 宣告
        // treeParents: [],       // 由主 app 宣告; [{child_atom_id, parent_atom_id, sort_order}]
        activeMindmapShellId: null,    // 當前 focused 殼（鍵盤事件路由用）
        activeMindmapAtomId: null,     // 當前 focused 節點
        editingMindmapAtomId: null,    // 標題編輯中的節點
        editingMindmapTitle: '',
        _mindmapTitleSaveTimer: null,
        dragMindmapShell: null,
        mindmapShellDragStartX: 0, mindmapShellDragStartY: 0,
        mindmapShellDragStartPos: null,
        mindmapShellDragMemberStarts: null,

        // 殼標題編輯（#1）
        editingShellId: null,
        editingShellTitle: '',
        _shellTitleSaveTimer: null,

        // 節點同層拖曳排序（#2）/ 拖出殼（B） / 跨殼搬移
        mindmapDragNode: null,         // 拖曳中的 ca
        mindmapDragStartX: 0,
        mindmapDragStartY: 0,
        mindmapDragMoved: false,
        mindmapDragDropTargetId: null, // sibling atom_id（drop indicator 顯示在它上/下）
        mindmapDragDropPosition: null, // 'above' | 'below' | 'left' | 'right'
        mindmapDragOutsideShell: false, // 拖到殼範圍外 = 準備 extract
        // 跨殼搬移
        mindmapDragCrossShellId: null,        // 目標殼 id（不是當前殼）
        mindmapDragCrossParentAtomId: null,   // 目標父節點 atom_id（null=接到目標殼 root）

        // 子樹摺疊（#3）-- per-session，不入 DB
        // 用 plain object 而非 Set，alpine reactivity 對 object key 較穩定
        collapsedMindmapAtomIds: {},

        // ---- 常數: tree layout ----
        // v1 統一節點尺寸 240×80（grid 基底 = 20，所有數值皆 20 的倍數）
        // 3 種模板（純文 / 圖+文 / 純圖）皆在 240×80 box 內排版，layout 演算法不必區分
        MM_NODE_W: 240,
        MM_NODE_H: 80,
        // tree-right: 同層垂直堆疊、不同層水平展開
        MM_X_GAP: 80,    // 層距(水平)
        MM_Y_GAP: 20,    // sibling 間距(垂直)
        MM_DIAG_X_OFFSET: 60,  // tree-right-diag: 同層 sibling 每張的 X 階梯位移(NODE_W/4)
        // tree-down: 同層水平排列、不同層垂直展開
        MM_X_GAP_DOWN: 20,  // sibling 間距(水平)
        MM_Y_GAP_DOWN: 60,  // 層距(垂直)
        MM_PAD_X: 24,
        MM_PAD_Y: 48,   // 殼上緣標題列高度
        MM_PAD_BOTTOM: 16,
        // radial: root 在中心，子節點在以 root 為圓心的同心圓上
        MM_RADIUS_STEP: 380,    // 每層半徑增量
        MM_RADIAL_PAD: 40,      // 殼邊與最外圈卡片的間距
        // tree-folder: 像 tree 指令的目錄清單,root 在左上,每個節點佔一行,子節點向右縮排
        // INDENT 與 STEM 互相獨立,但要求 STEM < INDENT(否則 rail 會跑到 parent 卡片之外左側)
        // rail X = child.pos_x - STEM = parent.pos_x + (INDENT - STEM)
        // 預設:INDENT=140, STEM=60 => rail X 距 parent 左邊緣 80px (= NODE_W/3 = 1/3 位置)
        MM_FOLDER_INDENT: 140,  // 每層往右縮排(X 軸)
        MM_FOLDER_STEM: 60,     // 直角轉向 child 的水平段長度
        MM_FOLDER_ROW_GAP: 20,  // 列距(節點底到下一節點頂)

        // ---- 樹索引（從 treeParents 建立） ----
        // 每次 loadData 後呼叫 _rebuildTreeIndex
        _childrenByParent: null,   // {parent_atom_id: [child_atom_id sorted by sort_order]}
        _parentByChild: null,      // {child_atom_id: parent_atom_id}
        _sortOrderByChild: null,   // {child_atom_id: sort_order}

        _rebuildTreeIndex() {
            this._childrenByParent = {};
            this._parentByChild = {};
            this._sortOrderByChild = {};
            var rels = this.treeParents || [];
            for (var i = 0; i < rels.length; i++) {
                var r = rels[i];
                var p = r.parent_atom_id, c = r.child_atom_id;
                this._parentByChild[c] = p;
                this._sortOrderByChild[c] = r.sort_order || 0;
                if (!this._childrenByParent[p]) this._childrenByParent[p] = [];
                this._childrenByParent[p].push(c);
            }
            // 排序每個父的子節點
            var self = this;
            Object.keys(this._childrenByParent).forEach(function(p) {
                self._childrenByParent[p].sort(function(a, b) {
                    return (self._sortOrderByChild[a] || 0) - (self._sortOrderByChild[b] || 0);
                });
            });
        },

        // ---- 判定/查詢 ----
        isMindmapNode(ca) {
            // 用 == null 同時排除 undefined / null（嚴格判斷避免 alpine reactive 對 undefined 的怪行為）
            if (!ca) return false;
            var v = ca.mindmap_shell_id;
            return v !== null && v !== undefined && v !== 0 && v !== '';
        },
        getShellById(shellId) {
            return (this.mindmapShells || []).find(function(s) { return s.id === shellId; });
        },
        _getCanvasAtomByAtomId(atomId) {
            return this.atoms.find(function(ca) { return ca.atom_id === atomId; });
        },

        // ---- Tree Layout (tree-right):root 在左、子節點往右、同層垂直堆疊 ----
        // 摺疊節點視為葉節點 -- 不展開子樹、不佔垂直空間
        _isCollapsed(atomId) {
            return !!this.collapsedMindmapAtomIds[atomId];
        },

        // 回傳子樹高度
        _measureSubtree(atomId) {
            if (this._isCollapsed(atomId)) return this.MM_NODE_H;
            var children = this._childrenByParent[atomId] || [];
            if (children.length === 0) return this.MM_NODE_H;
            var sum = 0;
            for (var i = 0; i < children.length; i++) {
                sum += this._measureSubtree(children[i]);
                if (i > 0) sum += this.MM_Y_GAP;
            }
            return Math.max(this.MM_NODE_H, sum);
        },

        _placeSubtree(atomId, x, y) {
            var ca = this._getCanvasAtomByAtomId(atomId);
            if (!ca) return { width: 0, height: this.MM_NODE_H };
            var children = this._isCollapsed(atomId) ? [] : (this._childrenByParent[atomId] || []);
            var subtreeH = this._measureSubtree(atomId);

            // 自身放在子樹垂直中線
            ca.pos_x = x;
            ca.pos_y = y + (subtreeH - this.MM_NODE_H) / 2;
            ca.width = this.MM_NODE_W;
            ca.height = this.MM_NODE_H;

            var childX = x + this.MM_NODE_W + this.MM_X_GAP;
            var childY = y;
            var maxRightX = x + this.MM_NODE_W;
            for (var i = 0; i < children.length; i++) {
                var ch = children[i];
                var childH = this._measureSubtree(ch);
                var sub = this._placeSubtree(ch, childX, childY);
                if (sub.right > maxRightX) maxRightX = sub.right;
                childY += childH + this.MM_Y_GAP;
            }
            return { right: maxRightX, bottom: y + subtreeH, height: subtreeH };
        },

        recalcMindmapLayout(shellId) {
            var shell = this.getShellById(shellId);
            if (!shell || !shell.root_atom_id) return;
            this._rebuildTreeIndex();

            if (shell.layout === 'radial' || shell.layout === 'radial-rotated') {
                this._recalcRadial(shell, shell.layout === 'radial-rotated');
                return;
            }

            var rootX = shell.pos_x + this.MM_PAD_X;
            var rootY = shell.pos_y + this.MM_PAD_Y;
            var bounds;
            if (shell.layout === 'tree-down') {
                bounds = this._placeSubtreeDown(shell.root_atom_id, rootX, rootY);
            } else if (shell.layout === 'tree-right-diag') {
                bounds = this._placeSubtreeDiag(shell.root_atom_id, rootX, rootY, 0);
            } else if (shell.layout === 'tree-folder') {
                var rowCounter = { value: 0 };
                bounds = this._placeSubtreeFolder(shell.root_atom_id, rootX, 0, rowCounter, rootY);
            } else {
                bounds = this._placeSubtree(shell.root_atom_id, rootX, rootY);
            }
            if (!bounds) return;

            // 自動調整殼大小以包覆子樹
            var newW = Math.max(300, bounds.right - shell.pos_x + this.MM_PAD_X);
            var newH = Math.max(120, bounds.bottom - shell.pos_y + this.MM_PAD_BOTTOM);
            shell.width = newW;
            shell.height = newH;
        },

        // ---- Radial layout: root 中心、子節點在同心圓 ----
        // 角度配額按 leaf-count 加權，避免分支重疊
        _countSubtreeLeaves(atomId) {
            if (this._isCollapsed(atomId)) return 1;
            var children = this._childrenByParent[atomId] || [];
            if (children.length === 0) return 1;
            var sum = 0;
            for (var i = 0; i < children.length; i++) {
                sum += this._countSubtreeLeaves(children[i]);
            }
            return sum;
        },

        _placeSubtreeRadial(atomId, cx, cy, angleStart, angleEnd, depth, bounds, applyRotation) {
            var ca = this._getCanvasAtomByAtomId(atomId);
            if (!ca) return;

            if (depth === 0) {
                ca.pos_x = cx - this.MM_NODE_W / 2;
                ca.pos_y = cy - this.MM_NODE_H / 2;
                ca._mm_rotate = 0;
            } else {
                var midAngle = (angleStart + angleEnd) / 2;
                var r = depth * this.MM_RADIUS_STEP;
                ca.pos_x = cx + r * Math.cos(midAngle) - this.MM_NODE_W / 2;
                ca.pos_y = cy + r * Math.sin(midAngle) - this.MM_NODE_H / 2;
                if (applyRotation) {
                    var rotRad = midAngle;
                    if (Math.cos(midAngle) < 0) rotRad += Math.PI;
                    ca._mm_rotate = rotRad * 180 / Math.PI;
                } else {
                    ca._mm_rotate = 0;
                }
            }
            ca.width = this.MM_NODE_W;
            ca.height = this.MM_NODE_H;

            if (bounds) {
                var x1 = ca.pos_x, x2 = ca.pos_x + this.MM_NODE_W;
                var y1 = ca.pos_y, y2 = ca.pos_y + this.MM_NODE_H;
                if (x1 < bounds.minX) bounds.minX = x1;
                if (x2 > bounds.maxX) bounds.maxX = x2;
                if (y1 < bounds.minY) bounds.minY = y1;
                if (y2 > bounds.maxY) bounds.maxY = y2;
            }

            var children = this._isCollapsed(atomId) ? [] : (this._childrenByParent[atomId] || []);
            if (children.length === 0) return;

            var totalLeaves = 0;
            var leafArr = [];
            for (var i = 0; i < children.length; i++) {
                var lc = this._countSubtreeLeaves(children[i]);
                leafArr.push(lc);
                totalLeaves += lc;
            }
            if (totalLeaves <= 0) totalLeaves = children.length;
            var totalAngle = angleEnd - angleStart;
            var cursor = angleStart;
            for (var j = 0; j < children.length; j++) {
                var portion = totalAngle * (leafArr[j] / totalLeaves);
                this._placeSubtreeRadial(children[j], cx, cy, cursor, cursor + portion, depth + 1, bounds, applyRotation);
                cursor += portion;
            }
        },

        _recalcRadial(shell, applyRotation) {
            // 圓心 = 殼當前中心；layout 完後保持中心不變、調整 width/height
            var cx = shell.pos_x + (shell.width || 400) / 2;
            var cy = shell.pos_y + (shell.height || 240) / 2;
            var bounds = { minX: cx, maxX: cx, minY: cy, maxY: cy };
            // -PI/2 起算 = 12 點鐘方向開始繞，視覺較自然
            this._placeSubtreeRadial(
                shell.root_atom_id, cx, cy,
                -Math.PI / 2, Math.PI * 3 / 2, 0, bounds, !!applyRotation
            );
            var pad = this.MM_RADIAL_PAD;
            var halfW = Math.max(
                150,
                Math.max(cx - bounds.minX, bounds.maxX - cx) + pad
            );
            var halfH = Math.max(
                80,
                Math.max(cy - bounds.minY, bounds.maxY - cy) + pad
            );
            // 殼上緣有標題列，下方多保留 PAD_Y/2 給視覺平衡
            shell.pos_x = cx - halfW;
            shell.pos_y = cy - halfH - this.MM_PAD_Y / 2;
            shell.width = halfW * 2;
            shell.height = halfH * 2 + this.MM_PAD_Y / 2;
        },

        // ---- Tree Layout (tree-right-diag): 同層 sibling 每張往右錯開 1/4 卡寬 ----
        // 子樹高度沿用 _measureSubtree(垂直),但每個 sibling 的 X 加上 sibIdx*OFFSET 階梯位移
        _placeSubtreeDiag(atomId, x, y, sibIdx) {
            var ca = this._getCanvasAtomByAtomId(atomId);
            if (!ca) return { right: x, bottom: y, height: this.MM_NODE_H };
            var children = this._isCollapsed(atomId) ? [] : (this._childrenByParent[atomId] || []);
            var subtreeH = this._measureSubtree(atomId);

            var diagX = x + sibIdx * this.MM_DIAG_X_OFFSET;
            ca.pos_x = diagX;
            ca.pos_y = y + (subtreeH - this.MM_NODE_H) / 2;
            ca.width = this.MM_NODE_W;
            ca.height = this.MM_NODE_H;

            var childX = diagX + this.MM_NODE_W + this.MM_X_GAP;
            var childY = y;
            var maxRightX = diagX + this.MM_NODE_W;
            for (var i = 0; i < children.length; i++) {
                var ch = children[i];
                var childH = this._measureSubtree(ch);
                var sub = this._placeSubtreeDiag(ch, childX, childY, i);
                if (sub.right > maxRightX) maxRightX = sub.right;
                childY += childH + this.MM_Y_GAP;
            }
            return { right: maxRightX, bottom: y + subtreeH, height: subtreeH };
        },

        // ---- Tree Layout (tree-down):root 在上、子節點往下、同層水平排列 ----
        _measureSubtreeWidth(atomId) {
            if (this._isCollapsed(atomId)) return this.MM_NODE_W;
            var children = this._childrenByParent[atomId] || [];
            if (children.length === 0) return this.MM_NODE_W;
            var sum = 0;
            for (var i = 0; i < children.length; i++) {
                sum += this._measureSubtreeWidth(children[i]);
                if (i > 0) sum += this.MM_X_GAP_DOWN;
            }
            return Math.max(this.MM_NODE_W, sum);
        },

        _placeSubtreeDown(atomId, x, y) {
            var ca = this._getCanvasAtomByAtomId(atomId);
            if (!ca) return { right: x + this.MM_NODE_W, bottom: y + this.MM_NODE_H };
            var children = this._isCollapsed(atomId) ? [] : (this._childrenByParent[atomId] || []);
            var subtreeW = this._measureSubtreeWidth(atomId);

            ca.pos_x = x + (subtreeW - this.MM_NODE_W) / 2;
            ca.pos_y = y;
            ca.width = this.MM_NODE_W;
            ca.height = this.MM_NODE_H;

            var childY = y + this.MM_NODE_H + this.MM_Y_GAP_DOWN;
            var childX = x;
            var maxBottom = y + this.MM_NODE_H;
            for (var i = 0; i < children.length; i++) {
                var ch = children[i];
                var childW = this._measureSubtreeWidth(ch);
                var sub = this._placeSubtreeDown(ch, childX, childY);
                if (sub.bottom > maxBottom) maxBottom = sub.bottom;
                childX += childW + this.MM_X_GAP_DOWN;
            }
            return { right: x + subtreeW, bottom: maxBottom };
        },

        // ---- Tree Layout (tree-folder): 像 tree 指令的目錄清單,每個節點佔一行 ----
        // root 在左上、每個子節點向右縮排 INDENT,DFS 順序依 sort_order 排列
        // rowCounter 用 object 包裝以便在遞迴間共享計數器
        _placeSubtreeFolder(atomId, rootX, depth, rowCounter, rootY) {
            var ca = this._getCanvasAtomByAtomId(atomId);
            if (!ca) return { right: rootX, bottom: rootY };
            ca.pos_x = rootX + depth * this.MM_FOLDER_INDENT;
            ca.pos_y = rootY + rowCounter.value * (this.MM_NODE_H + this.MM_FOLDER_ROW_GAP);
            ca.width = this.MM_NODE_W;
            ca.height = this.MM_NODE_H;
            var nodeRight = ca.pos_x + this.MM_NODE_W;
            var nodeBottom = ca.pos_y + this.MM_NODE_H;
            rowCounter.value += 1;
            var children = this._isCollapsed(atomId) ? [] : (this._childrenByParent[atomId] || []);
            for (var i = 0; i < children.length; i++) {
                var sub = this._placeSubtreeFolder(children[i], rootX, depth + 1, rowCounter, rootY);
                if (sub.right > nodeRight) nodeRight = sub.right;
                if (sub.bottom > nodeBottom) nodeBottom = sub.bottom;
            }
            return { right: nodeRight, bottom: nodeBottom };
        },

        async setMindmapShellBorderStyle(shellId, borderStyle) {
            if (this.isSnapshot) return;
            var shell = this.getShellById(shellId);
            if (!shell) return;
            var oldVal = shell.border_style || 'solid';
            shell.border_style = borderStyle;
            try {
                await API.updateMindmapShell(shellId, { border_style: borderStyle });
                var self = this;
                this.pushUndo({
                    type: 'mindmap_shell_border_style',
                    desc: '變更心智圖殼框線',
                    undo: async function() {
                        var sh = self.getShellById(shellId);
                        if (sh) sh.border_style = oldVal;
                        try { await API.updateMindmapShell(shellId, { border_style: oldVal }); } catch (e) {}
                    },
                    redo: async function() {
                        var sh = self.getShellById(shellId);
                        if (sh) sh.border_style = borderStyle;
                        try { await API.updateMindmapShell(shellId, { border_style: borderStyle }); } catch (e) {}
                    },
                });
            } catch (e) {
                shell.border_style = oldVal;
                this.showToast('變更框線失敗：' + (e.message || e), 'error');
            }
        },

        async setMindmapShellLineStyle(shellId, lineStyle) {
            if (this.isSnapshot) return;
            var shell = this.getShellById(shellId);
            if (!shell) return;
            var oldVal = shell.line_style || 'bezier';
            if (oldVal === lineStyle) return;
            shell.line_style = lineStyle;
            var self = this;
            this.$nextTick(function() { self.renderConnections(); });
            try {
                await API.updateMindmapShell(shellId, { line_style: lineStyle });
                this.pushUndo({
                    type: 'mindmap_shell_line_style',
                    desc: '變更心智圖線條樣式',
                    undo: async function() {
                        var sh = self.getShellById(shellId);
                        if (sh) sh.line_style = oldVal;
                        try { await API.updateMindmapShell(shellId, { line_style: oldVal }); } catch (e) {}
                        self.$nextTick(function() { self.renderConnections(); });
                    },
                    redo: async function() {
                        var sh = self.getShellById(shellId);
                        if (sh) sh.line_style = lineStyle;
                        try { await API.updateMindmapShell(shellId, { line_style: lineStyle }); } catch (e) {}
                        self.$nextTick(function() { self.renderConnections(); });
                    },
                });
            } catch (e) {
                shell.line_style = oldVal;
                this.$nextTick(function() { self.renderConnections(); });
                this.showToast('變更線條樣式失敗：' + (e.message || e), 'error');
            }
        },

        async setMindmapShellColor(shellId, color) {
            if (this.isSnapshot) return;
            var shell = this.getShellById(shellId);
            if (!shell) return;
            var oldColor = shell.color;
            shell.color = color;  // 即時 UI
            try {
                await API.updateMindmapShell(shellId, { color: color });
                var self = this;
                this.pushUndo({
                    type: 'mindmap_shell_color',
                    desc: '變更心智圖殼底色',
                    undo: async function() {
                        var sh = self.getShellById(shellId);
                        if (sh) sh.color = oldColor;
                        try { await API.updateMindmapShell(shellId, { color: oldColor }); } catch (e) {}
                    },
                    redo: async function() {
                        var sh = self.getShellById(shellId);
                        if (sh) sh.color = color;
                        try { await API.updateMindmapShell(shellId, { color: color }); } catch (e) {}
                    },
                });
            } catch (e) {
                shell.color = oldColor;  // rollback UI
                this.showToast('變更底色失敗：' + (e.message || e), 'error');
            }
        },

        async setShellLayout(shellId, layout) {
            var shell = this.getShellById(shellId);
            if (!shell) return;
            try {
                await API.updateMindmapShell(shellId, { layout: layout });
                // 重新從後端拉取，alpine 重建整套 reactive
                await this.loadData();
                var self = this;
                this.$nextTick(function() { self.renderConnections(); });
            } catch (e) {
                this.showToast('切換 layout 失敗：' + (e.message || e), 'error');
            }
        },

        recalcAllMindmapLayouts() {
            var self = this;
            (this.mindmapShells || []).forEach(function(s) { self.recalcMindmapLayout(s.id); });
        },

        // ---- Visual style helpers (節點外框/底色自訂) ----
        parseVisualStyle(ca) {
            if (!ca || !ca.visual_style) return {};
            try { return JSON.parse(ca.visual_style); } catch (e) { return {}; }
        },

        getMindmapNodeStyle(ca) {
            var s = 'left:' + ca.pos_x + 'px; top:' + ca.pos_y + 'px; z-index:' + (ca.z_index || 10) + ';';
            if (ca.width) s += ' width:' + ca.width + 'px;';
            if (ca.height) s += ' height:' + ca.height + 'px;';
            var vs = this.parseVisualStyle(ca);
            if (vs.border) s += ' border:1.5px solid ' + vs.border + ';';
            if (vs.bg) s += ' background:' + vs.bg + ';';
            // radial-rotated 模式:套用 rotation；編輯中不旋轉以方便輸入
            if (ca.mindmap_shell_id && ca._mm_rotate &&
                this.editingMindmapAtomId !== ca.atom_id) {
                var sh = this.getShellById(ca.mindmap_shell_id);
                if (sh && sh.layout === 'radial-rotated') {
                    s += ' transform: rotate(' + ca._mm_rotate + 'deg);';
                }
            }
            return s;
        },

        // 當前要套色的心智圖節點集合：若選中多張且 ca 在內,套全部選中;否則只套 ca
        _mindmapColorTargets(ca) {
            var ids = (this.selectedAtomIds || []).slice();
            if (ca && ids.indexOf(ca.atom_id) === -1) ids = [ca.atom_id];
            if (ids.length === 0 && ca) ids = [ca.atom_id];
            var self = this;
            return this.atoms.filter(function(c) {
                return c.mindmap_shell_id && ids.indexOf(c.atom_id) !== -1;
            });
        },

        // kind: 'border' | 'bg' | null(=都重置)
        async setMindmapNodeVisual(ca, color, kind) {
            if (this.isSnapshot) return;
            var targets = this._mindmapColorTargets(ca);
            if (targets.length === 0) return;
            var self = this;
            var beforeMap = {};
            targets.forEach(function(t) { beforeMap[t.id] = t.visual_style || '{}'; });

            for (var i = 0; i < targets.length; i++) {
                var t = targets[i];
                var vs = self.parseVisualStyle(t);
                if (kind === 'border') vs.border = color;
                else if (kind === 'bg') vs.bg = color;
                else { delete vs.border; delete vs.bg; }
                var newStyle = JSON.stringify(vs);
                t.visual_style = newStyle;  // 即時 UI
                try { await API.updateCanvasAtom(t.id, { visual_style: newStyle }); }
                catch (e) { /* 個別失敗繼續其他 */ }
            }

            this.pushUndo({
                type: 'mindmap_node_visual',
                desc: '節點視覺(' + targets.length + ')',
                undo: async function() {
                    for (var i = 0; i < targets.length; i++) {
                        var t = targets[i];
                        var prev = beforeMap[t.id] || '{}';
                        t.visual_style = prev;
                        try { await API.updateCanvasAtom(t.id, { visual_style: prev }); } catch (e) {}
                    }
                },
                redo: async function() {
                    for (var i = 0; i < targets.length; i++) {
                        var t = targets[i];
                        var vs2 = self.parseVisualStyle(t);
                        if (kind === 'border') vs2.border = color;
                        else if (kind === 'bg') vs2.bg = color;
                        else { delete vs2.border; delete vs2.bg; }
                        var ns = JSON.stringify(vs2);
                        t.visual_style = ns;
                        try { await API.updateCanvasAtom(t.id, { visual_style: ns }); } catch (e) {}
                    }
                },
            });
        },

        // ---- Render: 殼樣式 + mini 卡額外類別 ----
        getMindmapShellStyle(shell) {
            var bs = shell.border_style || 'solid';
            var border, bg;
            if (bs === 'none') {
                border = 'none';
                bg = shell.color + '0a';
            } else if (bs === 'transparent') {
                border = 'none';
                bg = 'transparent';
            } else if (bs === 'dashed') {
                border = '2px dashed ' + shell.color;
                bg = shell.color + '0a';
            } else {  // solid
                border = '2px solid ' + shell.color;
                bg = shell.color + '0a';
            }
            return 'left:' + shell.pos_x + 'px;'
                 + 'top:' + shell.pos_y + 'px;'
                 + 'width:' + shell.width + 'px;'
                 + 'height:' + shell.height + 'px;'
                 + 'z-index:' + (shell.z_index || 1) + ';'
                 + 'border:' + border + ';'
                 + 'background:' + bg + ';';
        },
        getMindmapShellLabelStyle(shell) {
            return 'background:' + shell.color + ';color:#fff;';
        },

        // 4a: 心智圖標題顯示在根節點上方
        // 標籤定位基於 root atom 的 pos,而非 shell 的 pos(shell 視覺已隱身)
        getMindmapRootLabelStyle(shell) {
            if (!shell || !shell.root_atom_id) return 'display:none;';
            var rootCa = this._getCanvasAtomByAtomId(shell.root_atom_id);
            if (!rootCa) return 'display:none;';
            var w = rootCa.width || this.MM_NODE_W;
            // 標籤水平置中於 root 節點上方,寬度 auto,垂直距節點 6px
            var x = (rootCa.pos_x || 0);
            var y = (rootCa.pos_y || 0) - 28;
            return 'left:' + x + 'px; top:' + y + 'px; width:' + w + 'px;'
                 + ' background:' + (shell.color || '#3b82f6') + '; color:#fff;'
                 + ' z-index:' + ((rootCa.z_index || 10) + 1) + ';';
        },

        // ---- 建立殼（從工具列） ----
        async createMindmapShellAtViewportCenter() {
            if (this.isSnapshot) { this.showToast('歸檔白板為唯讀快照', 'warn'); return; }
            var vp = this.$refs.viewport;
            if (!vp) return;
            var rect = vp.getBoundingClientRect();
            var center = this.screenToCanvas(rect.left + rect.width / 2 - 200, rect.top + rect.height / 2 - 150);
            try {
                var resp = await API.createMindmapShell(this.canvasId, {
                    title: '心智圖',
                    pos_x: center.x,
                    pos_y: center.y,
                    width: 400,
                    height: 240,
                    color: '#3b82f6',
                    layout: 'tree-right',
                    root_title: '主題',
                });
                this.mindmapShells.push(resp.shell);
                // 把 root 的 canvas_atom 注入 atoms（顯式 set mindmap_shell_id 確保 alpine 追蹤）
                var rootCa = resp.root_canvas_atom;
                rootCa.atom = resp.root_atom;
                rootCa.mindmap_shell_id = resp.shell.id;
                rootCa.group_ids = rootCa.group_ids || [];
                this.atoms.push(rootCa);
                this.recalcMindmapLayout(resp.shell.id);
                this.activeMindmapShellId = resp.shell.id;
                this.activeMindmapAtomId = resp.root_atom.id;
                this.editingMindmapAtomId = resp.root_atom.id;
                this.editingMindmapTitle = resp.root_atom.title || '';
                this.$nextTick(function() {
                    var inp = document.getElementById('mm-title-input-' + resp.root_atom.id);
                    if (inp) { inp.focus(); inp.select(); }
                });
                this.$nextTick(() => this.renderConnections());
            } catch (e) {
                this.showToast('建立心智圖失敗:' + (e.message || e), 'error');
            }
        },

        // ---- 拖殼移動（含內部節點一起搬）----
        onMindmapShellMouseDown(e, shell) {
            if (e.button !== 0) return;
            if (this.isSnapshot) return;
            if (e.target.closest('.wb-card')) return;
            if (e.target.closest('.wb-mindmap-resize')) return;
            e.stopPropagation();
            this.dragMindmapShell = shell;
            this.mindmapShellDragStartX = e.clientX;
            this.mindmapShellDragStartY = e.clientY;
            this.mindmapShellDragStartPos = { x: shell.pos_x, y: shell.pos_y };
            // 記下殼內 atom 的初始位置
            var self = this;
            this.mindmapShellDragMemberStarts = {};
            this.atoms.forEach(function(ca) {
                if (ca.mindmap_shell_id === shell.id) {
                    self.mindmapShellDragMemberStarts[ca.atom_id] = { x: ca.pos_x, y: ca.pos_y };
                }
            });
        },

        // ---- 節點點擊:設為 active，啟用熱鍵路由 ----
        onMindmapNodeClick(ca, e) {
            if (!this.isMindmapNode(ca)) return;
            this.activeMindmapShellId = ca.mindmap_shell_id;
            this.activeMindmapAtomId = ca.atom_id;
        },

        onMindmapNodeDblClick(ca, e) {
            if (!this.isMindmapNode(ca)) return;
            if (this.isSnapshot) return;
            this.activeMindmapShellId = ca.mindmap_shell_id;
            this.activeMindmapAtomId = ca.atom_id;
            this.editingMindmapAtomId = ca.atom_id;
            this.editingMindmapTitle = ca.atom ? (ca.atom.title || '') : '';
            var self = this;
            this.$nextTick(function() {
                var inp = document.getElementById('mm-title-input-' + ca.atom_id);
                if (inp) { inp.focus(); inp.select(); }
            });
        },

        // ---- 標題輸入 ----
        onMindmapTitleInput(atomId, value) {
            this.editingMindmapTitle = value;
            var ca = this._getCanvasAtomByAtomId(atomId);
            if (ca && ca.atom) ca.atom.title = value;  // 即時 UI
            var self = this;
            if (this._mindmapTitleSaveTimer) clearTimeout(this._mindmapTitleSaveTimer);
            this._mindmapTitleSaveTimer = setTimeout(function() {
                self._mindmapTitleSaveTimer = null;
                API.updateAtom(atomId, { title: value }).catch(function() {});
            }, 400);
        },

        finishMindmapTitleEdit(atomId) {
            if (this._mindmapTitleSaveTimer) {
                clearTimeout(this._mindmapTitleSaveTimer);
                this._mindmapTitleSaveTimer = null;
                var v = this.editingMindmapTitle;
                API.updateAtom(atomId, { title: v }).catch(function() {});
            }
            this.editingMindmapAtomId = null;
        },

        // ---- 熱鍵處理:由 whiteboard-undo.js 的 handleKeyDown 之前判定 mindmap 是否吃掉 ----
        // 若 active 在心智圖節點，吞掉 Tab/Enter/Delete/可印刷字元
        // 回傳 true = 已處理，外層 return；false = 由外層繼續
        handleMindmapKeyDown(e) {
            // 殼標題編輯中：不攔截任何鍵，讓 input 自然處理
            // （否則 active 節點仍存在，printable 字元會誤觸標題改寫到 active 節點）
            if (this.editingShellId !== null && this.editingShellId !== undefined) return false;

            if (this.editingMindmapAtomId) {
                // 編輯標題中:Enter 只結束編輯（避免誤觸新增同層,丟失輸入）
                //          Tab  結束編輯 + 新增子節點
                //          Esc  結束編輯
                if (e.key === 'Enter') {
                    e.preventDefault();
                    this.finishMindmapTitleEdit(this.editingMindmapAtomId);
                    return true;
                }
                if (e.key === 'Tab') {
                    e.preventDefault();
                    var aid2 = this.editingMindmapAtomId;
                    this.finishMindmapTitleEdit(aid2);
                    var ca2 = this._getCanvasAtomByAtomId(aid2);
                    if (!ca2) return true;
                    this._addMindmapNode(ca2.mindmap_shell_id, aid2, 'child');
                    return true;
                }
                if (e.key === 'Escape') {
                    e.preventDefault();
                    e.stopPropagation();      // 阻止 alpine @keydown.escape.window 後續清狀態
                    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                    this.finishMindmapTitleEdit(this.editingMindmapAtomId);
                    return true;
                }
                return false;
            }

            // 焦點在外部輸入元素（文字框 textarea / 卡片內聯編輯 textarea / 其他 input）時不吞熱鍵
            // 心智圖自身的標題輸入框由上方 editingMindmapAtomId / editingShellId 分支自治處理
            var et = e.target;
            if (et && (et.tagName === 'INPUT' || et.tagName === 'TEXTAREA' || et.isContentEditable)) {
                return false;
            }

            // 非編輯中:有 active 節點時吃熱鍵
            if (!this.activeMindmapAtomId || !this.activeMindmapShellId) return false;

            // Ctrl+E 或 F2 = 開啟詳細編輯卡片（完整 markdown / entries 編輯器）
            if ((e.ctrlKey && (e.key === 'e' || e.key === 'E')) || e.key === 'F2') {
                e.preventDefault();
                if (this.openCardEditor) this.openCardEditor(this.activeMindmapAtomId);
                return true;
            }

            if (e.key === 'Tab') {
                e.preventDefault();
                this._addMindmapNode(this.activeMindmapShellId, this.activeMindmapAtomId, 'child');
                return true;
            }
            if (e.key === 'Enter') {
                e.preventDefault();
                if (this._parentByChild[this.activeMindmapAtomId] === undefined) {
                    this._addMindmapNode(this.activeMindmapShellId, this.activeMindmapAtomId, 'child');
                } else {
                    this._addMindmapNode(this.activeMindmapShellId, this.activeMindmapAtomId, 'sibling');
                }
                return true;
            }
            if (e.key === 'Delete' || e.key === 'Backspace') {
                e.preventDefault();
                this._deleteMindmapNode(this.activeMindmapShellId, this.activeMindmapAtomId);
                return true;
            }
            // 方向鍵:在心智圖中導覽 active 節點
            //   ↑/↓ = 同層 sort_order 上/下一個
            //   ← = 父節點
            //   → = 第一個子節點
            if (e.key === 'ArrowUp' || e.key === 'ArrowDown' || e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                var next = this._navigateMindmap(this.activeMindmapAtomId, e.key);
                if (next !== null && next !== undefined) {
                    e.preventDefault();
                    this.activeMindmapAtomId = next;
                    var selfNav = this;
                    this.$nextTick(function() { selfNav.ensureAtomVisible(next); });
                    return true;
                }
                return false;
            }
            // 可印字元:進入標題編輯模式並把這個字元送入輸入框
            if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
                e.preventDefault();
                var aid3 = this.activeMindmapAtomId;
                var ca3 = this._getCanvasAtomByAtomId(aid3);
                if (!ca3) return false;
                this.editingMindmapAtomId = aid3;
                this.editingMindmapTitle = e.key;
                if (ca3.atom) ca3.atom.title = e.key;
                var self = this;
                this.$nextTick(function() {
                    var inp = document.getElementById('mm-title-input-' + aid3);
                    if (inp) {
                        inp.focus();
                        inp.setSelectionRange(inp.value.length, inp.value.length);
                    }
                });
                return true;
            }
            return false;
        },

        // ---- 新增節點 ----
        async _addMindmapNode(shellId, anchorAtomId, mode) {
            try {
                var resp = await API.addMindmapNode(shellId, {
                    mode: mode,
                    anchor_atom_id: anchorAtomId,
                    title: '',
                });
                var newCa = resp.canvas_atom;
                newCa.atom = resp.atom;
                newCa.mindmap_shell_id = shellId;  // 顯式設，確保 alpine reactivity
                newCa.group_ids = newCa.group_ids || [];
                this.atoms.push(newCa);
                // 更新樹索引
                this.treeParents.push({
                    child_atom_id: resp.atom.id,
                    parent_atom_id: resp.tree_parent_relation.to_atom_id,
                    sort_order: resp.tree_parent_relation.sort_order || 0,
                });
                this.recalcMindmapLayout(shellId);
                // focus 新節點，進入標題編輯
                this.activeMindmapAtomId = resp.atom.id;
                this.editingMindmapAtomId = resp.atom.id;
                this.editingMindmapTitle = '';
                var self = this;
                this.$nextTick(function() {
                    var inp = document.getElementById('mm-title-input-' + resp.atom.id);
                    if (inp) { inp.focus(); }
                    self.renderConnections();
                    self.ensureAtomVisible(resp.atom.id);
                });
                // undo:reverse = 刪節點
                var newAtomId = resp.atom.id;
                this.pushUndo({
                    type: 'mindmap_add_node',
                    desc: '新增心智圖節點',
                    undo: async function() {
                        try { await API.deleteMindmapNode(shellId, newAtomId); } catch (e) {}
                        await self.loadData();
                        self.$nextTick(function() { self.renderConnections(); });
                    },
                    redo: async function() {
                        try {
                            var r2 = await API.addMindmapNode(shellId, { mode: mode, anchor_atom_id: anchorAtomId, title: resp.atom.title || '' });
                            // 注意:redo 後 atom_id 會不同，因此 redo 後再 undo 必須以新 ID 為準。簡化:直接 reload
                        } catch (e) {}
                        await self.loadData();
                        self.$nextTick(function() { self.renderConnections(); });
                    },
                });
            } catch (e) {
                this.showToast('新增節點失敗:' + (e.message || e), 'error');
            }
        },

        // ---- 刪除節點（含子樹進字紙簍） ----
        async _deleteMindmapNode(shellId, atomId) {
            // 焦點目標:同層 sort_order 上一個（用戶要求）
            var nextActive = this._pickNextActiveAfterDelete(atomId);
            try {
                var resp = await API.deleteMindmapNode(shellId, atomId);
                var self = this;
                this.activeMindmapAtomId = nextActive;
                if (resp.shell_deleted) {
                    this.activeMindmapShellId = null;
                    this.activeMindmapAtomId = null;
                }
                this.pushUndo({
                    type: 'mindmap_delete_node',
                    desc: '刪除心智圖節點',
                    undo: async function() {
                        try { await API.restoreFromCanvasTrash(self.canvasId, resp.removed_atom_ids || []); } catch (e) {}
                        await self.loadData();
                        self.$nextTick(function() { self.renderConnections(); });
                    },
                    redo: async function() {
                        try { await API.deleteMindmapNode(shellId, atomId); } catch (e) {}
                        await self.loadData();
                        self.$nextTick(function() { self.renderConnections(); });
                    },
                });
                await this.loadData();
                this.$nextTick(function() { self.renderConnections(); });
            } catch (e) {
                this.showToast('刪除節點失敗:' + (e.message || e), 'error');
            }
        },

        _navigateMindmap(atomId, key) {
            this._rebuildTreeIndex();
            var ca = this._getCanvasAtomByAtomId(atomId);
            var shell = ca && this.getShellById(ca.mindmap_shell_id);
            var isDown = shell && shell.layout === 'tree-down';

            var parent = this._parentByChild[atomId];
            var children = this._childrenByParent[atomId] || [];

            // 同 depth 跨子樹: 找出當前殼內所有與 atomId 同深度且可見的節點,
            // 按視覺位置(tree-right 排 pos_y, tree-down 排 pos_x)排序,取 prev/next
            var prevSameDepth = null, nextSameDepth = null;
            if (ca) {
                var sameDepth = this._visibleSameDepthNodes(atomId, isDown ? 'tree-down' : 'tree-right');
                var sIdx = -1;
                for (var i = 0; i < sameDepth.length; i++) {
                    if (sameDepth[i].atom_id === atomId) { sIdx = i; break; }
                }
                if (sIdx > 0) prevSameDepth = sameDepth[sIdx - 1].atom_id;
                if (sIdx >= 0 && sIdx < sameDepth.length - 1) nextSameDepth = sameDepth[sIdx + 1].atom_id;
            }
            var goParent = function() { return parent !== undefined ? parent : null; };
            var goFirstChild = function() { return children.length > 0 ? children[0] : null; };

            // 對應表（對應視覺方向）
            //   tree-right / tree-right-diag: ↑↓ = 同 depth 跨子樹, ← = parent, → = first child
            //   tree-down: ←→ = 同 depth 跨子樹, ↑ = parent, ↓ = first child
            if (isDown) {
                if (key === 'ArrowLeft')  return prevSameDepth;
                if (key === 'ArrowRight') return nextSameDepth;
                if (key === 'ArrowUp')    return goParent();
                if (key === 'ArrowDown')  return goFirstChild();
            } else {
                if (key === 'ArrowUp')    return prevSameDepth;
                if (key === 'ArrowDown')  return nextSameDepth;
                if (key === 'ArrowLeft')  return goParent();
                if (key === 'ArrowRight') return goFirstChild();
            }
            return null;
        },

        _depthOfMindmapAtom(atomId) {
            var depth = 0;
            var cur = this._parentByChild[atomId];
            while (cur !== undefined) {
                depth++;
                cur = this._parentByChild[cur];
                if (depth > 100) break;  // 環狀防呆
            }
            return depth;
        },

        _visibleSameDepthNodes(atomId, layout) {
            var refCa = this._getCanvasAtomByAtomId(atomId);
            if (!refCa) return [];
            var shellId = refCa.mindmap_shell_id;
            var depth = this._depthOfMindmapAtom(atomId);
            var hidden = this._collapsedHiddenAtomIds();
            var self = this;
            var nodes = this.atoms.filter(function(c) {
                if (!c || c.mindmap_shell_id !== shellId) return false;
                if (hidden[c.atom_id]) return false;
                return self._depthOfMindmapAtom(c.atom_id) === depth;
            });
            nodes.sort(function(a, b) {
                if (layout === 'tree-down') return a.pos_x - b.pos_x;
                return a.pos_y - b.pos_y;
            });
            return nodes;
        },

        _pickNextActiveAfterDelete(atomId) {
            var parent = this._parentByChild[atomId];
            if (parent === undefined) return null;
            var siblings = (this._childrenByParent[parent] || []).slice();
            var idx = siblings.indexOf(atomId);
            if (idx > 0) return siblings[idx - 1];
            if (siblings.length > 1) return siblings[1];
            return parent;
        },

        // ---- 從矩形中心沿世界方向 (dx,dy) 到「旋轉 rotDeg 的 w×h 矩形」邊界 ----
        // 旋轉保長度，邊界點世界坐標 = (cx + dx*t, cy + dy*t)，
        // 其中 t = min(w/2/|lx|, h/2/|ly|)，(lx,ly) = (dx,dy) 反向旋轉到卡片自身坐標
        _rectEdgeAlong(cx, cy, rotDeg, w, h, dx, dy) {
            if (dx === 0 && dy === 0) return { x: cx, y: cy };
            var rad = -(rotDeg || 0) * Math.PI / 180;
            var cs = Math.cos(rad), sn = Math.sin(rad);
            var lx = dx * cs - dy * sn;
            var ly = dx * sn + dy * cs;
            var t1 = lx !== 0 ? (w / 2) / Math.abs(lx) : Infinity;
            var t2 = ly !== 0 ? (h / 2) / Math.abs(ly) : Infinity;
            var t = Math.min(t1, t2);
            return { x: cx + dx * t, y: cy + dy * t };
        },

        // ---- SVG 樹線 (parent -> child)，獨立於 canvas_connections ----
        // 固定灰色折線/貝茲,純結構視覺;relation_type connection 由 renderConnections 並存渲染
        renderMindmapTreeLines(svg) {
            if (!svg) return;
            var self = this;
            var rels = this.treeParents || [];
            var hidden = this._collapsedHiddenAtomIds();
            var path = '';
            rels.forEach(function(r) {
                var child = self._getCanvasAtomByAtomId(r.child_atom_id);
                var parent = self._getCanvasAtomByAtomId(r.parent_atom_id);
                if (!child || !parent) return;
                if (!child.mindmap_shell_id) return;
                if (hidden[r.child_atom_id]) return;

                var shell = self.getShellById(child.mindmap_shell_id);
                var layout = shell ? shell.layout : 'tree-right';
                // line_style: 'bezier'(預設) | 'elbow'(正交折線)
                // radial / radial-rotated 不受 line_style 影響(同心圓本身用直線)
                var lineStyle = shell && shell.line_style ? shell.line_style : 'bezier';

                var pW = parent.width || self.MM_NODE_W;
                var pH = parent.height || self.MM_NODE_H;
                var cW = child.width || self.MM_NODE_W;
                var cH = child.height || self.MM_NODE_H;

                if (layout === 'radial' || layout === 'radial-rotated') {
                    // 連線端點精確到「旋轉矩形邊界」，避免穿過卡片
                    var pcx = parent.pos_x + pW / 2;
                    var pcy = parent.pos_y + pH / 2;
                    var ccx = child.pos_x + cW / 2;
                    var ccy = child.pos_y + cH / 2;
                    var ddx = ccx - pcx, ddy = ccy - pcy;
                    var pRot = parent._mm_rotate || 0;
                    var cRot = child._mm_rotate || 0;
                    var pe = self._rectEdgeAlong(pcx, pcy, pRot, pW, pH, ddx, ddy);
                    var ce = self._rectEdgeAlong(ccx, ccy, cRot, cW, cH, -ddx, -ddy);
                    path += 'M ' + pe.x + ' ' + pe.y + ' L ' + ce.x + ' ' + ce.y + ' ';
                } else if (layout === 'tree-folder') {
                    // 樹狀(資料夾風格): rail 從 parent 卡片下方(明確在 parent 底邊以下)出來,
                    // 垂直延伸到 child 中線,水平 STEM 進 child 左邊
                    // rail X = child.pos_x - STEM,等於 parent 內偏左 (INDENT - STEM) 處
                    var railX = child.pos_x - self.MM_FOLDER_STEM;
                    var parentBottom = parent.pos_y + pH;
                    var childCy = child.pos_y + cH / 2;
                    var childLeft = child.pos_x;
                    path += 'M ' + railX + ' ' + parentBottom
                          + ' L ' + railX + ' ' + childCy
                          + ' L ' + childLeft + ' ' + childCy + ' ';
                } else if (layout === 'tree-down') {
                    var px = parent.pos_x + pW / 2;
                    var py = parent.pos_y + pH;
                    var cx = child.pos_x + cW / 2;
                    var cy = child.pos_y;
                    if (lineStyle === 'diagonal') {
                        // 斜線:parent 出短段 -> 斜線到 child 前 -> 短段進 child
                        var STUB_D = 40;
                        path += 'M ' + px + ' ' + py
                              + ' L ' + px + ' ' + (py + STUB_D)
                              + ' L ' + cx + ' ' + (cy - STUB_D)
                              + ' L ' + cx + ' ' + cy + ' ';
                    } else {
                        // bezier: 折點 Y 取中點(各 sibling cy 同 -> 樹幹效果)
                        // elbow:  折點 Y 緊貼 child 上方(在 sibling cx 各異的情況下,垂直段彼此分開)
                        var elbowY = lineStyle === 'elbow'
                            ? (cy - self.MM_Y_GAP_DOWN / 2)
                            : ((py + cy) / 2);
                        path += 'M ' + px + ' ' + py
                              + ' L ' + px + ' ' + elbowY
                              + ' L ' + cx + ' ' + elbowY
                              + ' L ' + cx + ' ' + cy + ' ';
                    }
                } else {
                    // tree-right / tree-right-diag
                    var px2 = parent.pos_x + pW;
                    var py2 = parent.pos_y + pH / 2;
                    var cx2 = child.pos_x;
                    var cy2 = child.pos_y + cH / 2;
                    if (lineStyle === 'elbow') {
                        // 正交折線:垂直段 X 設在 child 左側內 GAP/2 處
                        // diag layout 下每個 sibling 的 child.pos_x 已階梯式錯開,垂直段 X 也錯開,自然不交叉
                        var elbowX = cx2 - self.MM_X_GAP / 2;
                        path += 'M ' + px2 + ' ' + py2
                              + ' L ' + elbowX + ' ' + py2
                              + ' L ' + elbowX + ' ' + cy2
                              + ' L ' + cx2 + ' ' + cy2 + ' ';
                    } else if (lineStyle === 'diagonal') {
                        // 斜線:parent 出短水平段 -> 斜線直連到 child 前 -> 短水平段進 child
                        // 斜線方向與 diag layout 階梯排列相容,不會橫切過更早 sibling 的卡片內部
                        var STUB_R = 40;
                        path += 'M ' + px2 + ' ' + py2
                              + ' L ' + (px2 + STUB_R) + ' ' + py2
                              + ' L ' + (cx2 - STUB_R) + ' ' + cy2
                              + ' L ' + cx2 + ' ' + cy2 + ' ';
                    } else {
                        // bezier: 立方曲線,控制點在 parent/child 中間 X
                        var midX = (px2 + cx2) / 2;
                        path += 'M ' + px2 + ' ' + py2
                              + ' C ' + midX + ' ' + py2 + ', ' + midX + ' ' + cy2 + ', ' + cx2 + ' ' + cy2 + ' ';
                    }
                }
            });
            var existing = svg.querySelector('path.wb-mindmap-tree-lines');
            if (!existing) {
                existing = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                existing.setAttribute('class', 'wb-mindmap-tree-lines');
                existing.setAttribute('fill', 'none');
                existing.setAttribute('stroke', '#94a3b8');
                existing.setAttribute('stroke-width', '1.5');
                svg.appendChild(existing);
            }
            existing.setAttribute('d', path);
        },

        // ---- 獨立卡片 -> 升格為新心智圖 root ----
        async promoteToMindmapRoot(ca) {
            if (this.isSnapshot) { this.showToast('歸檔白板為唯讀快照', 'warn'); return; }
            if (!ca || !ca.atom_id) return;
            if (ca.mindmap_shell_id) {
                this.showToast('此卡片已是心智圖節點', 'warn', 1500);
                return;
            }
            // 殼位置反推:讓既有卡片的中心 = root 中心 = shell.pos + (PAD_X + NODE_W/2, PAD_Y + NODE_H/2)
            var caW = ca.width || 265;
            var caH = ca.height || 125;
            var caCenterX = ca.pos_x + caW / 2;
            var caCenterY = ca.pos_y + caH / 2;
            var shellPosX = caCenterX - this.MM_NODE_W / 2 - this.MM_PAD_X;
            var shellPosY = caCenterY - this.MM_NODE_H / 2 - this.MM_PAD_Y;
            var title = (ca.atom && ca.atom.title) ? ca.atom.title : '心智圖';
            var atomId = ca.atom_id;
            var shellPayload = {
                title: title,
                pos_x: shellPosX,
                pos_y: shellPosY,
                width: 400,
                height: 240,
                color: '#3b82f6',
                layout: 'tree-right',
                root_atom_id: atomId,
            };
            try {
                var resp = await API.createMindmapShell(this.canvasId, shellPayload);
                await this.loadData();
                var self = this;
                this.$nextTick(function() {
                    self.recalcMindmapLayout(resp.shell.id);
                    self.activeMindmapShellId = resp.shell.id;
                    self.activeMindmapAtomId = atomId;
                    self.renderConnections();
                });
                this.showToast('已建立心智圖', 'info', 1500);
                // undo = 解殼(shell_only),節點變回獨立卡片;redo = 重新 createMindmapShell
                var createdShellId = resp.shell.id;
                this.pushUndo({
                    type: 'mindmap_promote',
                    desc: '建立心智圖',
                    undo: async function() {
                        try { await API.deleteMindmapShell(createdShellId, 'shell_only'); } catch (e) {}
                        await self.loadData();
                        self.$nextTick(function() { self.renderConnections(); });
                    },
                    redo: async function() {
                        try { await API.createMindmapShell(self.canvasId, shellPayload); } catch (e) {}
                        await self.loadData();
                        self.$nextTick(function() { self.renderConnections(); });
                    },
                });
            } catch (e) {
                this.showToast('建立心智圖失敗：' + (e.message || e), 'error');
            }
        },

        // ---- 把節點脫離殼（拖出） ----
        async extractMindmapSubtree(shellId, atomId) {
            try {
                await API.extractMindmapSubtree(shellId, atomId);
                await this.loadData();
                var self = this;
                this.$nextTick(function() { self.renderConnections(); });
            } catch (e) {
                this.showToast('脫離心智圖失敗:' + (e.message || e), 'error');
            }
        },

        // ---- 刪除整個殼（殼內 atom 變獨立卡） ----
        async deleteMindmapShell(shellId, mode) {
            try {
                await API.deleteMindmapShell(shellId, mode || 'shell_only');
                await this.loadData();
                var self = this;
                this.$nextTick(function() { self.renderConnections(); });
            } catch (e) {
                this.showToast('刪除心智圖殼失敗:' + (e.message || e), 'error');
            }
        },

        // ============================================================
        // #1 殼標題改名
        // ============================================================
        startShellTitleEdit(shell) {
            if (this.isSnapshot) return;
            this.editingShellId = shell.id;
            this.editingShellTitle = shell.title || '';
            var self = this;
            this.$nextTick(function() {
                var inp = document.getElementById('mm-shell-title-input-' + shell.id);
                if (inp) { inp.focus(); inp.select(); }
            });
        },

        onShellTitleInput(shellId, value) {
            this.editingShellTitle = value;
            var shell = this.getShellById(shellId);
            if (shell) shell.title = value;  // 即時 UI
            var self = this;
            if (this._shellTitleSaveTimer) clearTimeout(this._shellTitleSaveTimer);
            this._shellTitleSaveTimer = setTimeout(function() {
                self._shellTitleSaveTimer = null;
                API.updateMindmapShell(shellId, { title: value }).catch(function() {});
            }, 400);
        },

        finishShellTitleEdit() {
            if (this.editingShellId === null) return;
            var shellId = this.editingShellId;
            if (this._shellTitleSaveTimer) {
                clearTimeout(this._shellTitleSaveTimer);
                this._shellTitleSaveTimer = null;
                var v = this.editingShellTitle;
                API.updateMindmapShell(shellId, { title: v }).catch(function() {});
            }
            this.editingShellId = null;
        },

        // ============================================================
        // #2 同層拖曳排序
        // ============================================================
        onMindmapNodeMouseDown(e, ca) {
            if (e.button !== 0) return;
            if (this.isSnapshot) return;
            if (!ca || !ca.mindmap_shell_id) return;
            // 編輯標題中時不啟動拖曳
            if (this.editingMindmapAtomId === ca.atom_id) return;
            // Shift+拖 -- 走 connection drag（含 root），由 endConnDrag 跳 relation modal
            if (e.shiftKey) {
                e.stopPropagation();
                e.preventDefault();
                if (this.startConnDrag) this.startConnDrag(e, ca, 'right');
                return;
            }
            this._rebuildTreeIndex();
            var isRoot = (this._parentByChild[ca.atom_id] === undefined);
            // root 節點:必須 Ctrl+拖才啟動(避免誤拖整棵樹);純點擊只 select
            // 但無論如何都要 stopPropagation,避免事件冒泡到 viewport 觸發框選
            if (isRoot && !e.ctrlKey && !e.metaKey) {
                e.stopPropagation();
                return;
            }
            e.stopPropagation();
            this.mindmapDragNode = ca;
            this.mindmapDragStartX = e.clientX;
            this.mindmapDragStartY = e.clientY;
            this.mindmapDragMoved = false;
            this.mindmapDragDropTargetId = null;
            this.mindmapDragDropPosition = null;
        },

        // 由 onViewportMouseMove 呼叫
        _handleMindmapDragMove(e) {
            if (!this.mindmapDragNode) return false;
            var dx = e.clientX - this.mindmapDragStartX;
            var dy = e.clientY - this.mindmapDragStartY;
            if (!this.mindmapDragMoved) {
                if (Math.abs(dx) < 5 && Math.abs(dy) < 5) return true;
                this.mindmapDragMoved = true;
            }
            this._updateMindmapDragDropTarget(e.clientX, e.clientY);
            return true;
        },

        _updateMindmapDragDropTarget(clientX, clientY) {
            var node = this.mindmapDragNode;
            if (!node) return;
            this._rebuildTreeIndex();
            var shell = this.getShellById(node.mindmap_shell_id);
            var pos = this.screenToCanvas(clientX, clientY);

            // 偵測是否拖出殼範圍 -- 用 16px buffer 避免邊界抖動
            if (shell) {
                var BUF = 16;
                var inShell = pos.x >= shell.pos_x - BUF
                           && pos.x <= shell.pos_x + shell.width + BUF
                           && pos.y >= shell.pos_y - BUF
                           && pos.y <= shell.pos_y + shell.height + BUF;
                if (!inShell) {
                    // 不在原殼 -- 先看是不是落在「其他殼」上,跨殼搬移優先於 extract
                    var cross = this._detectCrossShellTarget(clientX, clientY, node);
                    if (cross) {
                        this.mindmapDragCrossShellId = cross.shellId;
                        this.mindmapDragCrossParentAtomId = cross.parentAtomId;
                        this.mindmapDragOutsideShell = false;
                        this.mindmapDragDropTargetId = null;
                        return;
                    }
                    this.mindmapDragCrossShellId = null;
                    this.mindmapDragCrossParentAtomId = null;
                    this.mindmapDragOutsideShell = true;
                    this.mindmapDragDropTargetId = null;
                    return;
                }
                this.mindmapDragOutsideShell = false;
                this.mindmapDragCrossShellId = null;
                this.mindmapDragCrossParentAtomId = null;
            }

            var parentId = this._parentByChild[node.atom_id];
            if (parentId === undefined) {
                this.mindmapDragDropTargetId = null;
                return;
            }
            var draggedId = node.atom_id;
            var siblings = (this._childrenByParent[parentId] || []).filter(function(s) { return s !== draggedId; });
            if (siblings.length === 0) {
                this.mindmapDragDropTargetId = null;
                return;
            }
            var isDown = shell && shell.layout === 'tree-down';
            var self = this;
            var nearestId = null;
            var nearestDist = Infinity;
            var position = isDown ? 'left' : 'above';
            siblings.forEach(function(sid) {
                var sca = self._getCanvasAtomByAtomId(sid);
                if (!sca) return;
                var probe, mid;
                if (isDown) {
                    probe = pos.x;
                    mid = sca.pos_x + (sca.width || self.MM_NODE_W) / 2;
                } else {
                    probe = pos.y;
                    mid = sca.pos_y + (sca.height || self.MM_NODE_H) / 2;
                }
                var d = Math.abs(probe - mid);
                if (d < nearestDist) {
                    nearestDist = d;
                    nearestId = sid;
                    if (isDown) position = probe < mid ? 'left' : 'right';
                    else        position = probe < mid ? 'above' : 'below';
                }
            });
            this.mindmapDragDropTargetId = nearestId;
            this.mindmapDragDropPosition = position;
        },

        // 偵測拖曳是否落在「其他殼」上（跨殼搬移）
        // 用 elementFromPoint 精準命中,優先順序:節點 > 殼空白
        // 回傳 { shellId, parentAtomId } 或 null
        _detectCrossShellTarget(clientX, clientY, draggedCa) {
            var elem = document.elementFromPoint(clientX, clientY);
            if (!elem) return null;
            var nodeEl = elem.closest('.wb-mindmap-node');
            var shellEl = elem.closest('.wb-mindmap-shell');
            if (!nodeEl && !shellEl) return null;

            var draggedShellId = draggedCa.mindmap_shell_id;
            var draggedAtomId = draggedCa.atom_id;

            if (nodeEl) {
                var aid = parseInt(nodeEl.id.replace('card-', ''), 10);
                if (aid === draggedAtomId) return null;
                var ca = this._getCanvasAtomByAtomId(aid);
                if (!ca || !ca.mindmap_shell_id) return null;
                if (ca.mindmap_shell_id === draggedShellId) return null;  // 同殼節點不算跨殼
                // 後代偵測:不能拖到自己後代下（跨殼後代不在另一殼,但保險）
                if (this._isDescendantOf(aid, draggedAtomId)) return null;
                return { shellId: ca.mindmap_shell_id, parentAtomId: aid };
            }
            // shell 空白處 -- 接到目標殼 root
            var sid = parseInt(shellEl.id.replace('mindmap-shell-', ''), 10);
            if (!sid || sid === draggedShellId) return null;
            var targetShell = this.getShellById(sid);
            if (!targetShell) return null;
            // 接到 root（attach API parentAtomId=null 會自動接 root）
            return { shellId: sid, parentAtomId: null };
        },

        _isDescendantOf(candidateId, ancestorId) {
            // candidate 是 ancestor 的後代嗎？
            var cur = this._parentByChild[candidateId];
            while (cur !== undefined) {
                if (cur === ancestorId) return true;
                cur = this._parentByChild[cur];
            }
            return false;
        },

        // 由 onViewportMouseUp 呼叫；回傳 true 表示已處理
        _handleMindmapDragUp(e) {
            if (!this.mindmapDragNode) return false;
            var dragged = this.mindmapDragNode;
            var dropId = this.mindmapDragDropTargetId;
            var dropPos = this.mindmapDragDropPosition;
            var moved = this.mindmapDragMoved;
            var outside = this.mindmapDragOutsideShell;
            var crossShellId = this.mindmapDragCrossShellId;
            var crossParentAtomId = this.mindmapDragCrossParentAtomId;
            var dropClientX = e.clientX, dropClientY = e.clientY;
            this.mindmapDragNode = null;
            this.mindmapDragMoved = false;
            this.mindmapDragDropTargetId = null;
            this.mindmapDragDropPosition = null;
            this.mindmapDragOutsideShell = false;
            this.mindmapDragCrossShellId = null;
            this.mindmapDragCrossParentAtomId = null;
            if (moved && crossShellId) {
                // 跨殼搬移（含子樹）
                this._moveAcrossShell(dragged, crossShellId, crossParentAtomId);
            } else if (moved && outside) {
                // 拖出殼 -- extract，並把節點放到滑鼠座標
                this._extractFromDrag(dragged, dropClientX, dropClientY);
            } else if (moved && dropId !== null && dropId !== undefined) {
                this._commitMindmapReorder(dragged, dropId, dropPos);
            } else if (!moved) {
                // 未實際拖動 -- 視為 click
                this.onMindmapNodeClick(dragged, e);
            }
            return true;
        },

        async _moveAcrossShell(draggedCa, targetShellId, targetParentAtomId) {
            var atomId = draggedCa.atom_id;
            try {
                await API.attachMindmapAtom(targetShellId, atomId, targetParentAtomId, true);
                await this.loadData();
                var self = this;
                this.$nextTick(function() {
                    self.recalcMindmapLayout(targetShellId);
                    self.renderConnections();
                });
                this.showToast('已搬到目標心智圖', 'info', 1500);
            } catch (err) {
                this.showToast('跨殼搬移失敗：' + (err.message || err), 'error');
            }
        },

        async _extractFromDrag(draggedCa, clientX, clientY) {
            var shellId = draggedCa.mindmap_shell_id;
            var atomId = draggedCa.atom_id;
            var pos = this.screenToCanvas(clientX, clientY);
            this._rebuildTreeIndex();
            var hasChildren = (this._childrenByParent[atomId] || []).length > 0;
            try {
                if (hasChildren) {
                    // 有子樹 -- 變獨立新心智圖殼，殼位置讓 root 卡片中心落在滑鼠座標
                    var newShellPosX = pos.x - this.MM_NODE_W / 2 - this.MM_PAD_X;
                    var newShellPosY = pos.y - this.MM_NODE_H / 2 - this.MM_PAD_Y;
                    await API.extractMindmapSubtree(shellId, atomId, {
                        as_new_shell: true,
                        new_shell_pos_x: newShellPosX,
                        new_shell_pos_y: newShellPosY,
                    });
                    await this.loadData();
                    var self = this;
                    this.$nextTick(function() {
                        self.recalcMindmapLayout(self._findShellByRoot(atomId));
                        self.renderConnections();
                    });
                    this.showToast('已轉為新心智圖', 'info', 1500);
                } else {
                    // 葉子 -- 變獨立卡片，落在滑鼠位置
                    await API.extractMindmapSubtree(shellId, atomId);
                    await API.updateCanvasAtom(draggedCa.id, {
                        pos_x: pos.x - this.MM_NODE_W / 2,
                        pos_y: pos.y - this.MM_NODE_H / 2,
                    });
                    await this.loadData();
                    var self2 = this;
                    this.$nextTick(function() { self2.renderConnections(); });
                    this.showToast('已脫離心智圖殼', 'info', 1500);
                }
            } catch (err) {
                this.showToast('拖出殼失敗：' + (err.message || err), 'error');
            }
        },

        _findShellByRoot(rootAtomId) {
            var s = (this.mindmapShells || []).find(function(sh) { return sh.root_atom_id === rootAtomId; });
            return s ? s.id : null;
        },

        async _commitMindmapReorder(draggedCa, dropTargetAtomId, position) {
            this._rebuildTreeIndex();
            var targetSortOrder = this._sortOrderByChild[dropTargetAtomId] || 0;
            // 用 ±0.5 插入，避免整批重新編號；後端不在意小數
            // tree-right:above/below；tree-down:left/right -- 兩者語意一致(前/後)
            var isBefore = (position === 'above' || position === 'left');
            var newSortOrder = isBefore ? targetSortOrder - 0.5 : targetSortOrder + 0.5;
            var parentId = this._parentByChild[draggedCa.atom_id];
            try {
                await API.moveMindmapNode(draggedCa.mindmap_shell_id, draggedCa.atom_id, {
                    new_parent_atom_id: parentId,
                    sort_order: newSortOrder,
                });
                var rel = this.treeParents.find(function(r) { return r.child_atom_id === draggedCa.atom_id; });
                if (rel) rel.sort_order = newSortOrder;
                this.recalcMindmapLayout(draggedCa.mindmap_shell_id);
                var self = this;
                this.$nextTick(function() { self.renderConnections(); });
            } catch (e) {
                this.showToast('排序失敗：' + (e.message || e), 'error');
            }
        },

        // drop indicator 樣式（在 template 中綁 :style）
        get mindmapDropIndicatorStyle() {
            if (!this.mindmapDragDropTargetId || !this.mindmapDragMoved) return 'display:none;';
            var ca = this._getCanvasAtomByAtomId(this.mindmapDragDropTargetId);
            if (!ca) return 'display:none;';
            var w = ca.width || this.MM_NODE_W;
            var h = ca.height || this.MM_NODE_H;
            var pos = this.mindmapDragDropPosition;
            if (pos === 'left' || pos === 'right') {
                // tree-down:垂直線在左/右
                var x = pos === 'left' ? ca.pos_x - 4 : ca.pos_x + w + 1;
                return 'left:' + x + 'px; top:' + ca.pos_y + 'px; width:3px; height:' + h + 'px;';
            }
            // tree-right:水平線在上/下
            var y = pos === 'above' ? ca.pos_y - 4 : ca.pos_y + h + 1;
            return 'left:' + ca.pos_x + 'px; top:' + y + 'px; width:' + w + 'px; height:3px;';
        },

        // ============================================================
        // #4 拖入殼:外部卡片拖曳放下時偵測是否落在心智圖殼/節點
        // 由 whiteboard.js onViewportMouseUp 的 dragCard 分支呼叫；回傳 true 已處理
        // ============================================================
        _tryAttachDragToMindmap(e) {
            if (!this.dragCard) return false;
            // 已在某殼內的 mindmap 節點不重複 attach
            if (this.dragCard.mindmap_shell_id) return false;

            // 拖曳中的卡片以 z-index:100 蓋在游標下，需跳過它才能命中底下的 mindmap shell/node
            var draggedDomId = 'card-' + this.dragCard.atom_id;
            var stack = (document.elementsFromPoint ? document.elementsFromPoint(e.clientX, e.clientY) : [document.elementFromPoint(e.clientX, e.clientY)]) || [];
            var nodeEl = null, shellEl = null;
            for (var i = 0; i < stack.length; i++) {
                var el = stack[i];
                if (!el) continue;
                var draggedRoot = document.getElementById(draggedDomId);
                if (draggedRoot && (el === draggedRoot || draggedRoot.contains(el))) continue;
                if (!nodeEl) { var n = el.closest && el.closest('.wb-mindmap-node'); if (n) nodeEl = n; }
                if (!shellEl) { var s = el.closest && el.closest('.wb-mindmap-shell'); if (s) shellEl = s; }
                if (nodeEl || shellEl) break;
            }
            if (!nodeEl && !shellEl) return false;

            var shellId = null;
            var parentAtomId = null;
            if (nodeEl) {
                var aid = parseInt(nodeEl.id.replace('card-', ''), 10);
                var ca = this._getCanvasAtomByAtomId(aid);
                if (!ca || !ca.mindmap_shell_id) return false;
                shellId = ca.mindmap_shell_id;
                parentAtomId = aid;
            } else {
                var sid = parseInt(shellEl.id.replace('mindmap-shell-', ''), 10);
                var shell = this.getShellById(sid);
                if (!shell) return false;
                shellId = sid;
                parentAtomId = shell.root_atom_id;  // null 也讓後端用 root
            }

            var draggedAtomId = this.dragCard.atom_id;
            if (parentAtomId === draggedAtomId) {
                // 不可附加到自己 -- 視為一般拖曳，不攔截
                return false;
            }

            var self = this;
            API.attachMindmapAtom(shellId, draggedAtomId, parentAtomId)
                .then(function() { return self.loadData(); })
                .then(function() {
                    self.$nextTick(function() { self.renderConnections(); });
                    self.showToast('已收入心智圖', 'info', 1500);
                })
                .catch(function(err) {
                    self.showToast('收入心智圖失敗：' + (err.message || err), 'error');
                });
            return true;
        },

        // ============================================================
        // #3 摺疊/展開子樹
        // ============================================================
        hasMindmapChildren(ca) {
            if (!ca || !ca.mindmap_shell_id) return false;
            this._rebuildTreeIndex();
            var children = this._childrenByParent[ca.atom_id] || [];
            return children.length > 0;
        },

        isMindmapCollapsed(ca) {
            return !!(ca && this.collapsedMindmapAtomIds[ca.atom_id]);
        },

        toggleMindmapCollapse(ca) {
            if (!ca || !ca.mindmap_shell_id) return;
            var aid = ca.atom_id;
            var copy = Object.assign({}, this.collapsedMindmapAtomIds);
            if (copy[aid]) delete copy[aid];
            else copy[aid] = true;
            this.collapsedMindmapAtomIds = copy;  // 重新賦值以觸發 alpine 重算
            this.recalcMindmapLayout(ca.mindmap_shell_id);
            var self = this;
            this.$nextTick(function() { self.renderConnections(); });
        },

        // 計算被摺疊子樹隱藏的所有 atom_ids（後代）
        _collapsedHiddenAtomIds() {
            var hidden = {};
            var keys = Object.keys(this.collapsedMindmapAtomIds || {});
            if (keys.length === 0) return hidden;
            this._rebuildTreeIndex();
            var self = this;
            function markDescendants(parentId) {
                var children = self._childrenByParent[parentId] || [];
                children.forEach(function(c) {
                    hidden[c] = true;
                    markDescendants(c);
                });
            }
            keys.forEach(function(aid) { markDescendants(parseInt(aid, 10)); });
            return hidden;
        },

        // 過濾後可見的 mindmap atom（取代主 app 的 mindmapAtoms）
        get visibleMindmapAtoms() {
            var hidden = this._collapsedHiddenAtomIds();
            return this.atoms.filter(function(ca) {
                var v = ca && ca.mindmap_shell_id;
                if (v === null || v === undefined) return false;
                return !hidden[ca.atom_id];
            });
        },

        // ---- 通用轉移 modal（心智圖 / 文字框共用）----
        transferModal: {
            open: false,
            kind: '',     // 'mindmap' | 'textbox'
            obj: null,    // sh or tb
            label: '',    // 顯示在標題的名稱
            canvases: [],
            targetSlug: '',
            mode: 'move',
            loading: false,
            error: '',
        },

        async _openTransferModal(kind, obj, label) {
            var m = this.transferModal;
            m.kind = kind;
            m.obj = obj;
            m.label = label;
            m.targetSlug = '';
            m.mode = 'move';
            m.loading = false;
            m.error = '';
            try {
                var all = await API.getCanvases(false);
                var currentSlug = this.canvasId;
                m.canvases = (all || []).filter(function(cv) {
                    return cv.slug !== currentSlug && !cv.is_archived;
                });
            } catch (e) {
                m.canvases = [];
            }
            m.open = true;
        },

        openMindmapTransferModal(sh) {
            return this._openTransferModal('mindmap', sh, sh.title || '心智圖');
        },

        openTextboxTransferModal(tb) {
            return this._openTransferModal('textbox', tb, tb.title || '文字框');
        },

        async doTransfer() {
            var m = this.transferModal;
            if (!m.obj || !m.targetSlug) return;
            m.loading = true;
            m.error = '';
            try {
                if (m.kind === 'mindmap') {
                    await API.transferMindmapShell(m.obj.id, m.targetSlug, m.mode);
                    if (m.mode === 'move') {
                        var shellId = m.obj.id;
                        this.mindmapShells = this.mindmapShells.filter(function(s) { return s.id !== shellId; });
                        this.atoms = this.atoms.filter(function(ca) { return ca.mindmap_shell_id !== shellId; });
                        this.treeParents = [];
                        await this.loadData();
                    }
                } else if (m.kind === 'textbox') {
                    await API.transferTextbox(m.obj.id, m.targetSlug, m.mode);
                    if (m.mode === 'move') {
                        var tbId = m.obj.id;
                        this.textboxes = this.textboxes.filter(function(tb) { return tb.id !== tbId; });
                        this.connections = this.connections.filter(function(c) {
                            return c.source_textbox_id !== tbId && c.target_textbox_id !== tbId;
                        });
                    }
                }
                m.open = false;
                var verb = m.mode === 'copy' ? '已複製' : '已移動';
                this.showToast((m.kind === 'mindmap' ? '心智圖' : '文字框') + verb + '到目標白板', 'success');
            } catch (e) {
                m.error = '操作失敗：' + ((e && e.message) || String(e));
            } finally {
                m.loading = false;
            }
        },
    };
}
