/**
 * 白板 Mixin: Undo/Redo + Keyboard Shortcuts
 */
function whiteboardUndoMixin() {
    return {

        pushUndo(action) {
            this.undoStack.push(action);
            if (this.undoStack.length > this._maxUndoDepth) this.undoStack.shift();
            this.redoStack = [];
        },

        async doUndo() {
            if (this.undoStack.length === 0) return;
            var action = this.undoStack.pop();
            try {
                await action.undo();
                this.redoStack.push(action);
                this.showToast('復原: ' + action.desc, 'info', 2000);
            } catch (e) { console.error('Undo failed:', e); this.showToast('復原失敗', 'error'); }
        },

        async doRedo() {
            if (this.redoStack.length === 0) return;
            var action = this.redoStack.pop();
            try {
                await action.redo();
                this.undoStack.push(action);
                this.showToast('重做: ' + action.desc, 'info', 2000);
            } catch (e) { console.error('Redo failed:', e); this.showToast('重做失敗', 'error'); }
        },

        pushMoveUndo(atomIds, beforePositions, afterPositions) {
            var self = this;
            this.pushUndo({
                type: 'move',
                desc: '移動 ' + atomIds.length + ' 個原子',
                undo: async function() {
                    for (var i = 0; i < atomIds.length; i++) {
                        var ca = self.atoms.find(function(a) { return a.atom_id === atomIds[i]; });
                        if (ca) { ca.pos_x = beforePositions[i].x; ca.pos_y = beforePositions[i].y; await API.updateCanvasAtom(ca.id, { pos_x: ca.pos_x, pos_y: ca.pos_y }); }
                    }
                    self.renderConnections(); self.renderMinimap();
                },
                redo: async function() {
                    for (var i = 0; i < atomIds.length; i++) {
                        var ca = self.atoms.find(function(a) { return a.atom_id === atomIds[i]; });
                        if (ca) { ca.pos_x = afterPositions[i].x; ca.pos_y = afterPositions[i].y; await API.updateCanvasAtom(ca.id, { pos_x: ca.pos_x, pos_y: ca.pos_y }); }
                    }
                    self.renderConnections(); self.renderMinimap();
                },
            });
        },

        handleKeyDown(e) {
            if (this.cardEditorOpen) return;
            var tag = e.target.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            if (e.target.isContentEditable) return;

            if ((e.ctrlKey || e.metaKey) && !e.altKey) {
                if (e.key === 'z' && !e.shiftKey) { e.preventDefault(); this.doUndo(); return; }
                if ((e.key === 'z' && e.shiftKey) || e.key === 'y') { e.preventDefault(); this.doRedo(); return; }
                if (e.key === 'a') { e.preventDefault(); this.selectedAtomIds = this.filteredAtoms.map(function(ca) { return ca.atom_id; }); return; }
            }

            if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); this.deleteSelected(); return; }
        },

        async deleteSelected() {
            if (this.selectedAtomIds.length > 0) {
                var self = this;
                var toDelete = this.atoms.filter(function(ca) { return self.selectedAtomIds.includes(ca.atom_id); });
                if (toDelete.length === 0) return;
                var removedData = toDelete.map(function(ca) {
                    return { id: ca.id, atom_id: ca.atom_id, pos_x: ca.pos_x, pos_y: ca.pos_y,
                             width: ca.width, height: ca.height, z_index: ca.z_index, group_id: ca.group_id };
                });
                this.pushUndo({
                    type: 'remove_multi',
                    desc: '移除 ' + toDelete.length + ' 個原子',
                    undo: async function() {
                        for (var i = 0; i < removedData.length; i++) {
                            var rd = removedData[i];
                            await API.addAtomToCanvas(self.canvasId, { atom_id: rd.atom_id, pos_x: rd.pos_x, pos_y: rd.pos_y, width: rd.width, height: rd.height });
                        }
                        await self.loadData(); self.$nextTick(function() { self.renderConnections(); });
                    },
                    redo: async function() {
                        for (var i = 0; i < removedData.length; i++) {
                            var ca = self.atoms.find(function(a) { return a.atom_id === removedData[i].atom_id; });
                            if (ca) await API.removeCanvasAtom(ca.id);
                        }
                        await self.loadData(); self.$nextTick(function() { self.renderConnections(); });
                    },
                });
                for (var i = 0; i < toDelete.length; i++) await API.removeCanvasAtom(toDelete[i].id);
                this.selectedAtomIds = []; this.deselectCard();
                await this.loadData(); this.$nextTick(function() { self.renderConnections(); });
                return;
            }
            if (this.selectedAtomId) {
                var ca = this.atoms.find(function(a) { return a.atom_id === self.selectedAtomId; });
                if (ca) this.removeFromCanvas(ca);
            }
        },
    };
}
