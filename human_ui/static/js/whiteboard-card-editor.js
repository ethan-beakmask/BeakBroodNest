/**
 * 白板 Mixin: Card Editor (Tiptap WYSIWYG)
 */
function whiteboardCardEditorMixin() {
    return {

        _ceIgnoreChange: false,

        async openCardEditor(atomId) {
            const resp = await API.getAtom(atomId);
            if (!resp || resp.error) { this.showToast('無法載入原子', 'error'); return; }
            const atom = resp;
            const typeCfg = this.atomTypeConfig[atom.atom_type] || {};
            this.cardEditorAtomId = atom.id;
            this.cardEditorAtomType = typeCfg.label || atom.atom_type;
            this.cardEditorTitle = atom.title || '';
            this.cardEditorDirty = false;
            this.cardEditorOpen = true;

            this._ceIgnoreChange = false;
            this.$nextTick(() => {
                const host = this.$refs.tiptapHost;
                if (!host) return;
                if (window._bcCardEditor) window._bcCardEditor.destroy();
                window._bcCardEditor = new window.CardEditor();
                const self = this;
                window._bcCardEditor.create(host, {
                    contentJson: atom.content_json || null,
                    content: atom.content || '',
                    onChange: () => { if (!self._ceIgnoreChange) self.cardEditorDirty = true; },
                });
                host.addEventListener('keydown', function() { self._ceIgnoreChange = false; }, { once: false });
            });
        },

        async saveCardEditor() {
            const ce = window._bcCardEditor;
            if (!ce || !this.cardEditorAtomId) return;
            this._ceIgnoreChange = true;
            const md = ce.getMarkdown();
            const json = ce.getJSON();
            const title = this.cardEditorTitle;
            await API.updateAtom(this.cardEditorAtomId, { title: title, content: md, content_json: json });
            const ca = this.atoms.find(a => a.atom_id === this.cardEditorAtomId);
            if (ca && ca.atom) {
                ca.atom.title = title; ca.atom.content = md; ca.atom.content_json = json;
                var now = new Date();
                var local = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0') + 'T' + String(now.getHours()).padStart(2,'0') + ':' + String(now.getMinutes()).padStart(2,'0') + ':' + String(now.getSeconds()).padStart(2,'0') + '.' + String(now.getMilliseconds()).padStart(3,'0');
                ca.atom.updated_at = local;
            }
            if (this.selectedAtomDetails && this.selectedAtomDetails.id === this.cardEditorAtomId) {
                this.selectedAtomDetails.title = title; this.selectedAtomDetails.content = md;
            }
            this.cardEditorDirty = false;
            this.refreshSidebarAtoms();
            this.showToast('已儲存', 'success');
        },

        closeCardEditor() {
            if (this.cardEditorDirty) { if (!confirm('尚未儲存，確定關閉？')) return; }
            this.cardEditorDirty = false;
            if (window._bcCardEditor) { window._bcCardEditor.destroy(); window._bcCardEditor = null; }
            this.cardEditorOpen = false;
            this.cardEditorAtomId = null;
            this.dragCard = null; this.bodyDragPending = false; this.bodyDragCa = null;
            this.$nextTick(() => { this.renderConnections(); });
        },

        ceInsertLink() {
            const url = prompt('輸入連結 URL:');
            if (url && window._bcCardEditor) window._bcCardEditor.cmd('link', url);
        },

        ceCmd(command) {
            if (window._bcCardEditor) window._bcCardEditor.cmd(command);
        },

        ceIsActive(name, attrs) {
            if (!window._bcCardEditor) return false;
            return window._bcCardEditor.isActive(name, attrs);
        },
    };
}
