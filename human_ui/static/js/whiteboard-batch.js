/**
 * 白板 Mixin: 篩選 + 批次操作 + 連線編輯 + 匯出匯入
 */
function whiteboardBatchMixin() {
    return {

        // Canvas Filters
        get filteredAtoms() {
            var self = this;
            return this.atoms.filter(function(ca) {
                if (!ca.atom) return true;
                if (!self.filterTypes[ca.atom.atom_type]) return false;
                if (!self.filterLifecycles[ca.atom.lifecycle]) return false;
                if (self.filterTagIds.length > 0) {
                    var atomTagIds = (ca.atom.tags || []).map(function(t) { return t.id; });
                    if (!self.filterTagIds.some(function(tid) { return atomTagIds.includes(tid); })) return false;
                }
                return true;
            });
        },

        get filteredAtomIds() { return this.filteredAtoms.map(function(ca) { return ca.atom_id; }); },
        get hiddenAtomCount() { return this.atoms.length - this.filteredAtoms.length; },

        isAtomVisible(ca) { return this.filteredAtomIds.includes(ca.atom_id); },

        toggleFilterType(type) { this.filterTypes[type] = !this.filterTypes[type]; },
        toggleFilterLifecycle(lc) { this.filterLifecycles[lc] = !this.filterLifecycles[lc]; },

        toggleFilterTag(tagId) {
            var idx = this.filterTagIds.indexOf(tagId);
            if (idx >= 0) this.filterTagIds.splice(idx, 1);
            else this.filterTagIds.push(tagId);
        },

        resetFilters() {
            this.filterTypes = { A: true, B: true, C: true, D: true, E: true, F: true };
            this.filterLifecycles = { active: true, aging: true, archived: true, terminal: true };
            this.filterTagIds = [];
        },

        get hasActiveFilters() {
            var allTypes = Object.values(this.filterTypes).every(function(v) { return v; });
            var allLc = Object.values(this.filterLifecycles).every(function(v) { return v; });
            return !allTypes || !allLc || this.filterTagIds.length > 0;
        },

        // Batch Operations
        async batchUpdateType(newType) {
            if (this.selectedAtomIds.length === 0) return;
            var self = this;
            var oldValues = {};
            this.atoms.forEach(function(ca) { if (self.selectedAtomIds.includes(ca.atom_id) && ca.atom) oldValues[ca.atom_id] = ca.atom.atom_type; });
            var ids = Object.keys(oldValues).map(Number);
            this.pushUndo({
                type: 'batch_type', desc: '批次改類型為 ' + newType,
                undo: async function() { for (var i = 0; i < ids.length; i++) { var ca = self.atoms.find(function(a) { return a.atom_id === ids[i]; }); if (ca && ca.atom) { ca.atom.atom_type = oldValues[ids[i]]; await API.updateAtom(ids[i], { atom_type: oldValues[ids[i]] }); } } self.$nextTick(function() { self.renderConnections(); }); },
                redo: async function() { for (var i = 0; i < ids.length; i++) { var ca = self.atoms.find(function(a) { return a.atom_id === ids[i]; }); if (ca && ca.atom) { ca.atom.atom_type = newType; await API.updateAtom(ids[i], { atom_type: newType }); } } self.$nextTick(function() { self.renderConnections(); }); },
            });
            for (var i = 0; i < ids.length; i++) { var ca = this.atoms.find(function(a) { return a.atom_id === ids[i]; }); if (ca && ca.atom) { ca.atom.atom_type = newType; await API.updateAtom(ids[i], { atom_type: newType }); } }
            this.$nextTick(function() { self.renderConnections(); });
            this.showToast(ids.length + ' 個原子已改為 ' + newType, 'success', 2000);
        },

        async batchUpdateLifecycle(newLc) {
            if (this.selectedAtomIds.length === 0) return;
            var self = this;
            var oldValues = {};
            this.atoms.forEach(function(ca) { if (self.selectedAtomIds.includes(ca.atom_id) && ca.atom) oldValues[ca.atom_id] = ca.atom.lifecycle; });
            var ids = Object.keys(oldValues).map(Number);
            this.pushUndo({
                type: 'batch_lifecycle', desc: '批次改生命週期為 ' + newLc,
                undo: async function() { for (var i = 0; i < ids.length; i++) { var ca = self.atoms.find(function(a) { return a.atom_id === ids[i]; }); if (ca && ca.atom) { ca.atom.lifecycle = oldValues[ids[i]]; await API.updateAtom(ids[i], { lifecycle: oldValues[ids[i]] }); } } self.$nextTick(function() { self.renderConnections(); }); },
                redo: async function() { for (var i = 0; i < ids.length; i++) { var ca = self.atoms.find(function(a) { return a.atom_id === ids[i]; }); if (ca && ca.atom) { ca.atom.lifecycle = newLc; await API.updateAtom(ids[i], { lifecycle: newLc }); } } self.$nextTick(function() { self.renderConnections(); }); },
            });
            for (var i = 0; i < ids.length; i++) { var ca = this.atoms.find(function(a) { return a.atom_id === ids[i]; }); if (ca && ca.atom) { ca.atom.lifecycle = newLc; await API.updateAtom(ids[i], { lifecycle: newLc }); } }
            this.$nextTick(function() { self.renderConnections(); });
            this.showToast(ids.length + ' 個原子已改為 ' + newLc, 'success', 2000);
        },

        async batchToggleTag(tagId) {
            if (this.selectedAtomIds.length === 0) return;
            var self = this;
            var tag = this.tags.find(function(t) { return t.id === tagId; });
            var tagName = tag ? tag.name : '#' + tagId;
            var haveCount = 0; var targets = [];
            this.atoms.forEach(function(ca) {
                if (self.selectedAtomIds.includes(ca.atom_id) && ca.atom) {
                    targets.push(ca);
                    if ((ca.atom.tags || []).some(function(t) { return t.id === tagId; })) haveCount++;
                }
            });
            var adding = haveCount < targets.length / 2;
            var oldTagStates = {};
            targets.forEach(function(ca) { oldTagStates[ca.atom_id] = (ca.atom.tags || []).map(function(t) { return t.id; }); });
            var ids = targets.map(function(ca) { return ca.atom_id; });
            this.pushUndo({
                type: 'batch_tag', desc: (adding ? '加入' : '移除') + '標籤 ' + tagName,
                undo: async function() { for (var i = 0; i < ids.length; i++) await API.updateAtom(ids[i], { tag_ids: oldTagStates[ids[i]] }); await self.loadData(); self.$nextTick(function() { self.renderConnections(); }); },
                redo: async function() { for (var i = 0; i < ids.length; i++) { var cur = oldTagStates[ids[i]].slice(); if (adding) { if (!cur.includes(tagId)) cur.push(tagId); } else { cur = cur.filter(function(id) { return id !== tagId; }); } await API.updateAtom(ids[i], { tag_ids: cur }); } await self.loadData(); self.$nextTick(function() { self.renderConnections(); }); },
            });
            for (var i = 0; i < ids.length; i++) {
                var cur = oldTagStates[ids[i]].slice();
                if (adding) { if (!cur.includes(tagId)) cur.push(tagId); } else { cur = cur.filter(function(id) { return id !== tagId; }); }
                await API.updateAtom(ids[i], { tag_ids: cur });
            }
            await this.loadData(); this.$nextTick(function() { self.renderConnections(); });
            this.showToast(ids.length + ' 個原子' + (adding ? '加入' : '移除') + '標籤 ' + tagName, 'success', 2000);
        },

        // Connection Inline Edit
        startEditConnection(connId, screenX, screenY) {
            var conn = this.connections.find(function(c) { return c.id === connId; });
            if (!conn) return;
            this.editingConnId = connId;
            this.editingConnLabel = conn.label || '';
            this.editingConnPos = { x: screenX, y: screenY };
        },

        async saveConnectionLabel() {
            if (!this.editingConnId) return;
            var connId = this.editingConnId;
            var newLabel = this.editingConnLabel;
            var conn = this.connections.find(function(c) { return c.id === connId; });
            var oldLabel = conn ? (conn.label || '') : '';
            if (conn) conn.label = newLabel;
            await API.updateConnection(connId, { label: newLabel });
            var self = this;
            this.pushUndo({
                type: 'edit_conn_label', desc: '編輯連線標籤',
                undo: async function() { var c = self.connections.find(function(c) { return c.id === connId; }); if (c) c.label = oldLabel; await API.updateConnection(connId, { label: oldLabel }); self.renderConnections(); },
                redo: async function() { var c = self.connections.find(function(c) { return c.id === connId; }); if (c) c.label = newLabel; await API.updateConnection(connId, { label: newLabel }); self.renderConnections(); },
            });
            this.editingConnId = null;
            this.renderConnections();
        },

        cancelEditConnection() { this.editingConnId = null; },

        // Export / Import
        async exportCanvas(format) {
            if (format === 'json') {
                var data = {
                    canvas: this.canvas,
                    atoms: this.atoms.map(function(ca) { return { atom_id: ca.atom_id, pos_x: ca.pos_x, pos_y: ca.pos_y, width: ca.width, height: ca.height, z_index: ca.z_index, group_id: ca.group_id, atom: ca.atom }; }),
                    connections: this.connections, groups: this.groups, exported_at: new Date().toISOString(),
                };
                this.exportContent = JSON.stringify(data, null, 2);
            } else {
                var lines = ['# ' + (this.canvas ? this.canvas.name : 'Canvas'), ''];
                lines.push('匯出時間: ' + new Date().toLocaleString('zh-TW'), '');
                lines.push('## 原子 (' + this.atoms.length + ')', '');
                var self = this;
                this.atoms.forEach(function(ca) {
                    if (!ca.atom) return;
                    var tags = (ca.atom.tags || []).map(function(t) { return t.name; }).join(', ');
                    lines.push('### [' + ca.atom.atom_type + '] ' + ca.atom.title + ' (#' + ca.atom_id + ')');
                    lines.push(''); lines.push('- 類型: ' + ca.atom.atom_type + ' | 生命週期: ' + ca.atom.lifecycle + ' | 來源: ' + ca.atom.source);
                    if (tags) lines.push('- 標籤: ' + tags);
                    lines.push(''); if (ca.atom.content) { lines.push(ca.atom.content); lines.push(''); }
                    lines.push('---'); lines.push('');
                });
                if (this.connections.length > 0) {
                    lines.push('## 連線 (' + this.connections.length + ')', '');
                    this.connections.forEach(function(conn) {
                        var src = self.getAtomTitle(conn.source_atom_id);
                        var tgt = self.getAtomTitle(conn.target_atom_id);
                        var label = conn.label || self.relationLabelMap[conn.relation_type] || conn.relation_type;
                        lines.push('- ' + src + ' --[' + label + ']--> ' + tgt);
                    });
                    lines.push('');
                }
                this.exportContent = lines.join('\n');
            }
            this.exportFormat = format; this.showExportModal = true;
        },

        downloadExport() {
            var ext = this.exportFormat === 'json' ? '.json' : '.md';
            var mime = this.exportFormat === 'json' ? 'application/json' : 'text/markdown';
            var name = (this.canvas ? this.canvas.name : 'canvas') + ext;
            var blob = new Blob([this.exportContent], { type: mime + ';charset=utf-8' });
            var url = URL.createObjectURL(blob); var a = document.createElement('a');
            a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url);
        },

        copyExport() {
            navigator.clipboard.writeText(this.exportContent).then(() => { this.showToast('已複製到剪貼簿', 'success', 2000); });
        },

        async importCanvasFromFile(e) {
            var file = e.target.files[0];
            if (!file) return;
            var text = await file.text();
            try {
                var data = JSON.parse(text);
                if (!data.atoms || !Array.isArray(data.atoms)) { this.showToast('JSON 格式不正確: 缺少 atoms 陣列', 'error'); return; }
                var imported = 0;
                for (var i = 0; i < data.atoms.length; i++) {
                    var item = data.atoms[i]; var atomId = item.atom_id;
                    try { await API.getAtom(atomId); } catch (err) { continue; }
                    if (this.atoms.some(function(ca) { return ca.atom_id === atomId; })) continue;
                    await API.addAtomToCanvas(this.canvasId, { atom_id: atomId, pos_x: item.pos_x || 100 + i * 30, pos_y: item.pos_y || 100 + i * 30, width: item.width, height: item.height });
                    imported++;
                }
                await this.loadData(); this.$nextTick(() => this.renderConnections());
                this.showToast('已匯入 ' + imported + ' 個原子', 'success');
                this.showImportModal = false;
            } catch (err) { this.showToast('匯入失敗: ' + err.message, 'error'); }
        },
    };
}
