/**
 * 白板 Mixin: Multi-Card Editor (Tiptap WYSIWYG)
 * 支援同時開啟 1~N 張卡片，自動排版
 *
 * _ceStore: Tiptap CardEditor 實例存放在閉包變數，
 * 避免 Alpine Proxy 包裹導致 ProseMirror transaction identity 檢查失敗。
 */
var _ceStore = {};  // { atomId: CardEditor instance } -- 不進入 Alpine reactive

function whiteboardCardEditorMixin() {
    return {

        // 多卡片編輯器狀態
        openEditors: [],       // [{ id, atomId, title, atomType, dirty, readonly }]
        _ceSeq: 0,
        cardEditorOpen: false, // 是否有任何卡片編輯器開啟
        ceSidebarOpen: false,  // 左側卡片選擇面板

        // 右側抓重點
        ceStagingOpen: false,
        stagingMode: 'copy',     // 'copy' or 'move'
        stagingItems: [],        // [{ id, text, sourceAtomId, sourceTitle }]
        stagingTitle: '',        // 自訂新卡片標題（空白時用預設）
        _stagingSeq: 0,

        // 最大化
        maximizedEditorId: null,  // 目前最大化的 editorId，null = 無

        // 排版模式
        editorLayout: 'auto',  // auto, horizontal, vertical, grid, list

        get editorLayoutClass() {
            var count = this.openEditors.length;
            if (this.editorLayout !== 'auto') return 'ce-layout-' + this.editorLayout;
            if (count <= 1) return 'ce-layout-single';
            if (count === 2) return 'ce-layout-horizontal';
            if (count <= 4) return 'ce-layout-grid';
            return 'ce-layout-list';
        },

        async openCardEditor(atomId) {
            // 如果已開啟同一張，聚焦
            var existing = this.openEditors.find(e => e.atomId === atomId);
            if (existing) {
                this._focusEditor(existing.id);
                return;
            }

            var resp = await API.getAtom(atomId);
            if (!resp || resp.error) { this.showToast('無法載入原子', 'error'); return; }
            var atom = resp;
            var typeCfg = this.atomTypeConfig[atom.atom_type] || {};
            var editorId = ++this._ceSeq;

            this.openEditors.push({
                id: editorId,
                atomId: atom.id,
                title: atom.title || '',
                atomType: typeCfg.label || atom.atom_type,
                dirty: false,
                readonly: this.isSnapshot || (atom.owner || 'ethan') !== 'ethan',
                _contentJson: atom.content_json || null,
                _content: atom.content || '',
            });
            if (!this.cardEditorOpen) {
                this.ceSidebarOpen = true;
                this.ceStagingOpen = true;
            }
            this.cardEditorOpen = true;

            var self = this;
            this.$nextTick(async () => {
                var host = document.querySelector('[data-ce-id="' + editorId + '"] .ce-pane-body');
                if (!host) return;

                // Make entry schemas available to NodeView
                window._entrySchemas = self.entrySchemas || [];

                var ce = new window.CardEditor();
                ce.create(host, {
                    contentJson: atom.content_json || null,
                    content: atom.content || '',
                    onChange: function() { self._markEditorDirty(editorId); },
                    editable: (atom.owner || 'ethan') === 'ethan',
                });

                // Load existing entries from DB if any
                try {
                    var entries = await API.getEntries(atomId);
                    if (entries && entries.length > 0) {
                        ce.loadEntries(entries);
                    }
                } catch (e) { /* no entries yet, use content as-is */ }

                _ceStore[atomId] = ce;
                self._focusEditor(editorId);
            });
        },

        _markEditorDirty(editorId) {
            var ed = this.openEditors.find(e => e.id === editorId);
            if (ed) ed.dirty = true;
        },

        _focusEditor(editorId) {
            var el = document.querySelector('[data-ce-id="' + editorId + '"]');
            if (!el) return;
            el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            el.classList.remove('ce-pane-flash');
            void el.offsetWidth;
            el.classList.add('ce-pane-flash');
            setTimeout(function() { el.classList.remove('ce-pane-flash'); }, 2000);
        },

        async saveEditor(editorId) {
            var ed = this.openEditors.find(e => e.id === editorId);
            if (!ed) return;
            var ce = _ceStore[ed.atomId];
            if (!ce) return;

            var md = ce.getMarkdown();
            var json = ce.getJSON();
            var title = ed.title;

            // Sync structured entries to DB
            var entries = ce.extractEntries();
            var hasStructuredEntries = entries.some(e => e.schema_code !== 'freetext');

            if (hasStructuredEntries || entries.length > 0) {
                try {
                    var syncResult = await API.syncEntries(ed.atomId, entries);
                    // Use the content snapshot from sync as the canonical content
                    md = syncResult.content_snapshot || md;

                    // Update entryId attributes in the editor from sync result
                    if (syncResult.entries) {
                        var syncEntries = syncResult.entries;
                        // Reload entries to get IDs assigned by DB
                        ce.loadEntries(syncEntries);
                    }
                } catch (e) {
                    console.warn('Entry sync failed, falling back to content save:', e);
                }
            }

            await API.updateAtom(ed.atomId, { title: title, content: md, content_json: json });

            var ca = this.atoms.find(a => a.atom_id === ed.atomId);
            if (ca && ca.atom) {
                ca.atom.title = title; ca.atom.content = md; ca.atom.content_json = json;
                var now = new Date();
                ca.atom.updated_at = now.toISOString();
            }
            if (this.selectedAtomDetails && this.selectedAtomDetails.id === ed.atomId) {
                this.selectedAtomDetails.title = title; this.selectedAtomDetails.content = md;
            }
            ed.dirty = false;
            this.refreshSidebarAtoms();
            this.showToast('已儲存', 'success');
        },

        toggleMaximize(editorId) {
            if (this.maximizedEditorId === editorId) {
                // 還原：清除 inline style
                this.maximizedEditorId = null;
                var pane = document.querySelector('[data-ce-id="' + editorId + '"]');
                if (pane) {
                    pane.style.top = '';
                    pane.style.left = '';
                    pane.style.width = '';
                    pane.style.height = '';
                }
                return;
            }
            this.maximizedEditorId = editorId;
            this.$nextTick(function() {
                var pane = document.querySelector('[data-ce-id="' + editorId + '"]');
                var container = pane && pane.parentElement;
                if (!pane || !container) return;
                pane.style.top = container.scrollTop + 'px';
                pane.style.left = '0';
                pane.style.width = container.clientWidth + 'px';
                pane.style.height = container.clientHeight + 'px';
            });
        },

        closeEditor(editorId) {
            var idx = this.openEditors.findIndex(e => e.id === editorId);
            if (idx < 0) return;
            var ed = this.openEditors[idx];
            if (ed.dirty) { if (!confirm('「' + ed.title + '」尚未儲存，確定關閉？')) return; }

            if (this.maximizedEditorId === editorId) {
                this.maximizedEditorId = null;
                var pane = document.querySelector('[data-ce-id="' + editorId + '"]');
                if (pane) { pane.style.top = ''; pane.style.left = ''; pane.style.width = ''; pane.style.height = ''; }
            }
            var ce = _ceStore[ed.atomId];
            if (ce) { ce.destroy(); delete _ceStore[ed.atomId]; }

            this.openEditors.splice(idx, 1);
            if (this.openEditors.length === 0) {
                this.cardEditorOpen = false;
                this.dragCard = null; this.bodyDragPending = false; this.bodyDragCa = null;
            }
            this.$nextTick(() => { this.renderConnections(); });
        },

        _closeAllEditors() {
            for (var i = this.openEditors.length - 1; i >= 0; i--) {
                var ed = this.openEditors[i];
                var ce = _ceStore[ed.atomId];
                if (ce) { ce.destroy(); delete _ceStore[ed.atomId]; }
            }
            this.openEditors = [];
            this.maximizedEditorId = null;
            this.cardEditorOpen = false;
            this.dragCard = null; this.bodyDragPending = false; this.bodyDragCa = null;
            this.$nextTick(() => { this.renderConnections(); });
        },

        async saveAllAndClose() {
            for (var i = 0; i < this.openEditors.length; i++) {
                var ed = this.openEditors[i];
                if (ed.dirty && !ed.readonly) await this.saveEditor(ed.id);
            }
            this._closeAllEditors();
        },

        discardAllAndClose() {
            this._closeAllEditors();
        },

        // 兼容舊呼叫（ESC 鍵等）
        closeCardEditor() {
            var hasDirty = this.openEditors.some(function(e) { return e.dirty; });
            if (hasDirty) {
                if (!confirm('有未儲存的卡片，確定不儲存並關閉？')) return;
            }
            this._closeAllEditors();
        },

        ceInsertLink(editorId) {
            var ed = this.openEditors.find(e => e.id === editorId);
            if (!ed) return;
            var url = prompt('輸入連結 URL:');
            if (url) {
                var ce = _ceStore[ed.atomId];
                if (ce) ce.cmd('link', url);
            }
        },

        ceCmd(command, editorId) {
            var ed = this.openEditors.find(e => e.id === editorId);
            if (!ed) return;
            var ce = _ceStore[ed.atomId];
            if (ce) ce.cmd(command);
        },

        ceIsActive(name, attrs, editorId) {
            var ed = this.openEditors.find(e => e.id === editorId);
            if (!ed) return false;
            var ce = _ceStore[ed.atomId];
            if (!ce) return false;
            return ce.isActive(name, attrs);
        },

        saveCardEditor() {
            // 儲存所有 dirty 的（兼容舊呼叫）
            this.openEditors.forEach(ed => { if (ed.dirty) this.saveEditor(ed.id); });
        },

        async openSelectedInEditor() {
            if (!this.selectedAtomIds || this.selectedAtomIds.length === 0) return;
            var ids = this.selectedAtomIds.slice();
            for (var i = 0; i < ids.length; i++) {
                await this.openCardEditor(ids[i]);
            }
        },

        // ============================================
        // 暫存區 Staging
        // ============================================

        toggleStaging() {
            this.ceStagingOpen = !this.ceStagingOpen;
        },

        ceHandleSelection(editorId) {
            if (!this.ceStagingOpen) return;
            var ed = this.openEditors.find(function(e) { return e.id === editorId; });
            if (!ed || ed.readonly) return;
            var ce = _ceStore[ed.atomId];
            if (!ce) return;

            // 單一原子操作：讀取 + 刪除（若為移動模式）在同一 state 上完成
            var shouldDelete = this.stagingMode === 'move';
            var info = ce.captureSelection(shouldDelete);
            if (!info) return;

            if (shouldDelete) this._markEditorDirty(editorId);
            this.addToStaging(info.markdown, ed.atomId, ed.title);
        },

        addToStaging(text, atomId, title) {
            this.stagingItems.push({
                id: ++this._stagingSeq,
                text: text,
                sourceAtomId: atomId,
                sourceTitle: title || '#' + atomId,
            });
            this.$nextTick(function() {
                var list = document.querySelector('.ce-staging-list');
                if (list) list.scrollTop = list.scrollHeight;
            });
        },

        removeStagingItem(itemId) {
            var idx = this.stagingItems.findIndex(function(s) { return s.id === itemId; });
            if (idx >= 0) this.stagingItems.splice(idx, 1);
        },

        moveStagingItem(idx, direction) {
            var target = idx + direction;
            if (target < 0 || target >= this.stagingItems.length) return;
            var items = this.stagingItems;
            var tmp = items[idx];
            items.splice(idx, 1);
            items.splice(target, 0, tmp);
        },

        clearStaging() {
            if (this.stagingItems.length === 0) return;
            if (!confirm('清空暫存區所有片段？')) return;
            this.stagingItems = [];
        },

        async saveStagingAsAtom() {
            if (this.stagingItems.length === 0) { this.showToast('暫存區無內容', 'error'); return; }

            var combined = this.stagingItems.map(function(s) { return s.text; }).join('\n\n');
            var title = this.stagingTitle.trim() || ('重組筆記 (' + this.stagingItems.length + ' 片段)');
            try {
                var atom = await API.createAtom({
                    title: title,
                    content: combined,
                    atom_type: 'F',
                    source: 'human',
                });
                var vpX = (-this.panX / this.zoom) + 300 + Math.random() * 100;
                var vpY = (-this.panY / this.zoom) + 200 + Math.random() * 100;
                await API.addAtomToCanvas(this.canvasId, { atom_id: atom.id, pos_x: vpX, pos_y: vpY });

                this.stagingItems = [];
                this.stagingTitle = '';
                await this.loadData();
                this.$nextTick(function() { this.renderConnections(); }.bind(this));
                this.showToast('已建立新卡片 #' + atom.id, 'success');
            } catch (e) {
                this.showToast('建立失敗: ' + e.message, 'error');
            }
        },
    };
}
