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
                desc: '移動 ' + atomIds.length + ' 張卡片',
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
            // Event-level dedupe：同一 event 被 handler 處理過就不再處理
            // （防 init/listener 多重註冊或 alpine 對某些事件的雙派發）
            if (e.__bcHandled) return;
            e.__bcHandled = true;
            if (this.cardEditorOpen) {
                // 卡片編輯器熱鍵: Ctrl+S 儲存當前 / Ctrl+K,S 全部儲存並關 / Ctrl+K,Q 全部捨棄並關
                if (this._handleCardEditorKeydown && this._handleCardEditorKeydown(e)) return;
                return;
            }

            // Ctrl/Cmd 組合鍵優先處理（undo/redo/select-all）
            if ((e.ctrlKey || e.metaKey) && !e.altKey) {
                if (e.key === 'z' && !e.shiftKey) { e.preventDefault(); this.doUndo(); return; }
                if ((e.key === 'z' && e.shiftKey) || e.key === 'y') { e.preventDefault(); this.doRedo(); return; }
                if (e.key === 'a') {
                    var tag0 = e.target.tagName;
                    if (tag0 === 'INPUT' || tag0 === 'TEXTAREA' || tag0 === 'SELECT') return;
                    e.preventDefault();
                    this.selectedAtomIds = this.filteredAtoms.map(function(ca) { return ca.atom_id; });
                    return;
                }
            }

            // 心智圖節點熱鍵優先（active/editing 在心智圖時吃掉 Tab/Enter/Del/printable）
            if (this.handleMindmapKeyDown && this.handleMindmapKeyDown(e)) return;

            var tag = e.target.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            if (e.target.isContentEditable) return;

            if (e.key === 'Escape' && this.pickSizeTargetMode) { e.preventDefault(); this.cancelPickSizeTarget(); return; }
            if (e.key === 'Escape' && this.pickAlignTargetMode) { e.preventDefault(); this.cancelPickAlign(); return; }
            if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); this.deleteSelected(); return; }
        },

        // Delete 鍵 / 工具列「刪除」/ Backspace：送入此白板的字紙簍
        // 三個破壞層級的中間層：
        //   - 解除連結 (右鍵)         : 只刪 canvas_atoms，不可救回
        //   - 白板字紙簍 (本動作)     : 從當前白板移除，可從字紙簍救回，atom 本體與其他白板不受影響
        //   - 徹底刪除 (右鍵)         : hard delete atom 本體，所有白板連帶清除，不可逆
        async deleteSelected() {
            var self = this;
            var ids = [];
            if (this.selectedAtomIds.length > 0) {
                ids = this.selectedAtomIds.slice();
            } else if (this.selectedAtomId) {
                ids = [this.selectedAtomId];
            }
            if (ids.length === 0) return;

            var toDelete = this.atoms.filter(function(ca) { return ids.includes(ca.atom_id); });
            if (toDelete.length === 0) return;
            var atomIds = toDelete.map(function(ca) { return ca.atom_id; });

            this.pushUndo({
                type: 'canvas_trash_multi',
                desc: '送入字紙簍 ' + toDelete.length + ' 張卡片',
                undo: async function() {
                    try { await API.restoreFromCanvasTrash(self.canvasId, atomIds); }
                    catch (e) { console.warn('canvas trash restore failed', e); }
                    await self.loadData(); self.$nextTick(function() { self.renderConnections(); });
                },
                redo: async function() {
                    try { await API.addToCanvasTrash(self.canvasId, atomIds); }
                    catch (e) { console.warn('canvas trash add failed', e); }
                    await self.loadData(); self.$nextTick(function() { self.renderConnections(); });
                },
            });

            try { await API.addToCanvasTrash(this.canvasId, atomIds); }
            catch (e) { this.showToast(e.message || '送入字紙簍失敗', 'error'); return; }

            this.selectedAtomIds = []; this.deselectCard();
            await this.loadData(); this.$nextTick(function() { self.renderConnections(); });
        },
    };
}
