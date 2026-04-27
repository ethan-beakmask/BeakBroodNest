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

        // ---- 常數: tree layout ----
        MM_NODE_W: 140,
        MM_NODE_H: 30,
        MM_X_GAP: 90,    // 層距：寬鬆 3 倍，避免子樹擴張時樹線重疊
        MM_Y_GAP: 6,
        MM_PAD_X: 24,
        MM_PAD_Y: 48,   // 殼上緣標題列高度
        MM_PAD_BOTTOM: 16,

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
        // 回傳子樹高度
        _measureSubtree(atomId) {
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
            var children = this._childrenByParent[atomId] || [];
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

            var rootX = shell.pos_x + this.MM_PAD_X;
            var rootY = shell.pos_y + this.MM_PAD_Y;
            var bounds = this._placeSubtree(shell.root_atom_id, rootX, rootY);
            if (!bounds) return;

            // 自動調整殼大小以包覆子樹
            var newW = Math.max(300, bounds.right - shell.pos_x + this.MM_PAD_X);
            var newH = Math.max(120, bounds.bottom - shell.pos_y + this.MM_PAD_BOTTOM);
            shell.width = newW;
            shell.height = newH;
        },

        recalcAllMindmapLayouts() {
            var self = this;
            (this.mindmapShells || []).forEach(function(s) { self.recalcMindmapLayout(s.id); });
        },

        // ---- Render: 殼樣式 + mini 卡額外類別 ----
        getMindmapShellStyle(shell) {
            return 'left:' + shell.pos_x + 'px;'
                 + 'top:' + shell.pos_y + 'px;'
                 + 'width:' + shell.width + 'px;'
                 + 'height:' + shell.height + 'px;'
                 + 'z-index:' + (shell.z_index || 1) + ';'
                 + 'border:2px solid ' + shell.color + ';'
                 + 'background:' + shell.color + '0a;';
        },
        getMindmapShellLabelStyle(shell) {
            return 'background:' + shell.color + ';color:#fff;';
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
            if (this.editingMindmapAtomId) {
                // 編輯標題中:Enter 結束編輯 + 新增同層；Tab 結束編輯 + 新增子節點；Esc 結束編輯
                if (e.key === 'Enter') {
                    e.preventDefault();
                    var aid = this.editingMindmapAtomId;
                    this.finishMindmapTitleEdit(aid);
                    var ca = this._getCanvasAtomByAtomId(aid);
                    if (!ca) return true;
                    // root 沒有同層，改建子節點
                    if (this._parentByChild[aid] === undefined) {
                        this._addMindmapNode(ca.mindmap_shell_id, aid, 'child');
                    } else {
                        this._addMindmapNode(ca.mindmap_shell_id, aid, 'sibling');
                    }
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

            // 非編輯中:有 active 節點時吃熱鍵
            if (!this.activeMindmapAtomId || !this.activeMindmapShellId) return false;

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
            var parent = this._parentByChild[atomId];
            var siblings = parent !== undefined ? (this._childrenByParent[parent] || []) : [];
            var idx = siblings.indexOf(atomId);

            if (key === 'ArrowUp') {
                if (idx > 0) return siblings[idx - 1];
                return null;
            }
            if (key === 'ArrowDown') {
                if (idx >= 0 && idx < siblings.length - 1) return siblings[idx + 1];
                return null;
            }
            if (key === 'ArrowLeft') {
                // 父節點（root 沒有則不動）
                return parent !== undefined ? parent : null;
            }
            if (key === 'ArrowRight') {
                // 第一個子節點
                var children = this._childrenByParent[atomId] || [];
                return children.length > 0 ? children[0] : null;
            }
            return null;
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

        // ---- SVG 樹線 (parent -> child)，獨立於 canvas_connections ----
        // 由 renderMindmapTreeLines() 呼叫，掛在 connSvg 上
        renderMindmapTreeLines(svg) {
            if (!svg) return;
            var self = this;
            var rels = this.treeParents || [];
            var path = '';
            rels.forEach(function(r) {
                var child = self._getCanvasAtomByAtomId(r.child_atom_id);
                var parent = self._getCanvasAtomByAtomId(r.parent_atom_id);
                if (!child || !parent) return;
                if (!child.mindmap_shell_id) return;
                var px = parent.pos_x + self.MM_NODE_W;
                var py = parent.pos_y + self.MM_NODE_H / 2;
                var cx = child.pos_x;
                var cy = child.pos_y + self.MM_NODE_H / 2;
                // 兩段折線:水平到中點，再垂直，再水平到子節點
                var midX = (px + cx) / 2;
                path += 'M ' + px + ' ' + py + ' '
                      + 'C ' + midX + ' ' + py + ', ' + midX + ' ' + cy + ', ' + cx + ' ' + cy + ' ';
            });
            // 用一條 <path> 全部畫，輕量
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
    };
}
