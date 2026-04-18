/**
 * 白板 Mixin: Multi-Card Editor (Tiptap WYSIWYG)
 * 支援同時開啟 1~N 張卡片，自動排版
 */
function whiteboardCardEditorMixin() {
    return {

        // 多卡片編輯器狀態
        openEditors: [],       // [{ id, atomId, title, atomType, dirty, readonly }]
        _editorInstances: {},  // { atomId: CardEditor instance }
        _ceSeq: 0,
        cardEditorOpen: false, // 是否有任何卡片編輯器開啟
        ceSidebarOpen: false,  // 左側卡片選擇面板

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
                readonly: (atom.owner || 'ethan') !== 'ethan',
                _contentJson: atom.content_json || null,
                _content: atom.content || '',
            });
            this.cardEditorOpen = true;

            var self = this;
            this.$nextTick(() => {
                var host = document.querySelector('[data-ce-id="' + editorId + '"] .ce-pane-body');
                if (!host) return;
                var ce = new window.CardEditor();
                ce.create(host, {
                    contentJson: atom.content_json || null,
                    content: atom.content || '',
                    onChange: function() { self._markEditorDirty(editorId); },
                    editable: (atom.owner || 'ethan') === 'ethan',
                });
                self._editorInstances[atomId] = ce;
            });
        },

        _markEditorDirty(editorId) {
            var ed = this.openEditors.find(e => e.id === editorId);
            if (ed) ed.dirty = true;
        },

        _focusEditor(editorId) {
            var el = document.querySelector('[data-ce-id="' + editorId + '"]');
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        },

        async saveEditor(editorId) {
            var ed = this.openEditors.find(e => e.id === editorId);
            if (!ed) return;
            var ce = this._editorInstances[ed.atomId];
            if (!ce) return;

            var md = ce.getMarkdown();
            var json = ce.getJSON();
            var title = ed.title;
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

        closeEditor(editorId) {
            var idx = this.openEditors.findIndex(e => e.id === editorId);
            if (idx < 0) return;
            var ed = this.openEditors[idx];
            if (ed.dirty) { if (!confirm('「' + ed.title + '」尚未儲存，確定關閉？')) return; }

            // 清理 Tiptap
            var ce = this._editorInstances[ed.atomId];
            if (ce) { ce.destroy(); delete this._editorInstances[ed.atomId]; }

            this.openEditors.splice(idx, 1);
            if (this.openEditors.length === 0) {
                this.cardEditorOpen = false;
                this.dragCard = null; this.bodyDragPending = false; this.bodyDragCa = null;
            }
            this.$nextTick(() => { this.renderConnections(); });
        },

        closeCardEditor() {
            // 關閉所有（兼容舊呼叫）
            var ids = this.openEditors.map(e => e.id).slice();
            for (var i = ids.length - 1; i >= 0; i--) {
                var ed = this.openEditors.find(e => e.id === ids[i]);
                if (ed && ed.dirty) {
                    if (!confirm('「' + ed.title + '」尚未儲存，確定關閉？')) return;
                }
                var ce = this._editorInstances[ed.atomId];
                if (ce) { ce.destroy(); delete this._editorInstances[ed.atomId]; }
                var idx = this.openEditors.findIndex(e => e.id === ids[i]);
                if (idx >= 0) this.openEditors.splice(idx, 1);
            }
            this.cardEditorOpen = false;
            this.dragCard = null; this.bodyDragPending = false; this.bodyDragCa = null;
            this.$nextTick(() => { this.renderConnections(); });
        },

        ceInsertLink(editorId) {
            var ed = this.openEditors.find(e => e.id === editorId);
            if (!ed) return;
            var url = prompt('輸入連結 URL:');
            if (url) {
                var ce = this._editorInstances[ed.atomId];
                if (ce) ce.cmd('link', url);
            }
        },

        ceCmd(command, editorId) {
            var ed = this.openEditors.find(e => e.id === editorId);
            if (!ed) return;
            var ce = this._editorInstances[ed.atomId];
            if (ce) ce.cmd(command);
        },

        ceIsActive(name, attrs, editorId) {
            var ed = this.openEditors.find(e => e.id === editorId);
            if (!ed) return false;
            var ce = this._editorInstances[ed.atomId];
            if (!ce) return false;
            return ce.isActive(name, attrs);
        },

        saveCardEditor() {
            // 儲存所有 dirty 的（兼容舊呼叫）
            this.openEditors.forEach(ed => { if (ed.dirty) this.saveEditor(ed.id); });
        },
    };
}
