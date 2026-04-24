/**
 * 白板 Mixin: 群組操作
 */
function whiteboardGroupsMixin() {
    return {

        async createGroupFromSelection() {
            if (this.selectedAtomIds.length === 0) return;
            var pad = 20; var self = this;
            var selected = this.atoms.filter(function(ca) { return self.selectedAtomIds.includes(ca.atom_id); });
            if (selected.length === 0) return;
            var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            selected.forEach(function(ca) {
                minX = Math.min(minX, ca.pos_x); minY = Math.min(minY, ca.pos_y);
                maxX = Math.max(maxX, ca.pos_x + (ca.width || 260)); maxY = Math.max(maxY, ca.pos_y + (ca.height || 120));
            });
            await API.createGroup(this.canvasId, {
                name: 'Group', color: '#3b82f6',
                pos_x: minX - pad, pos_y: minY - pad - 24,
                width: maxX - minX + pad * 2, height: maxY - minY + pad * 2 + 24,
                atom_ids: this.selectedAtomIds,
            });
            this.selectedAtomIds = [];
            await this.loadData();
            this.$nextTick(function() {
                // 重繪所有群組邊框（含巢狀偏移）
                self.groups.forEach(function(g) { self.recalcGroupBounds(g.id); });
                self.groups.forEach(function(g) {
                    API.updateGroup(g.id, { pos_x: g.pos_x, pos_y: g.pos_y, width: g.width, height: g.height });
                });
                self.renderConnections();
            });
        },

        getGroupStyle(g) {
            var bs = g.border_style || 'none';
            var border = bs === 'none' ? 'border:none;' : 'border:1px ' + bs + ' ' + g.color + ';';
            return 'left:' + g.pos_x + 'px; top:' + g.pos_y + 'px; width:' + g.width + 'px; height:' + g.height + 'px; z-index:' + (g.z_index || 1) + '; ' + border + ' background:' + g.color + '08;';
        },

        getGroupLabelStyle(g) { return 'color:' + g.color + ';'; },

        onGroupMouseDown(e, g) {
            if (e.button !== 0) return;
            e.stopPropagation();
            this.dragGroup = g;
            this.groupDragStartX = e.clientX; this.groupDragStartY = e.clientY;
            this.groupDragStartPos = { x: g.pos_x, y: g.pos_y };
            var self = this; this.groupDragMemberStarts = {};
            this.atoms.forEach(function(ca) { if (ca.group_ids && ca.group_ids.includes(g.id)) self.groupDragMemberStarts[ca.atom_id] = { x: ca.pos_x, y: ca.pos_y }; });
        },

        onGroupResizeMouseDown(e, g) {
            if (e.button !== 0) return;
            e.stopPropagation(); e.preventDefault();
            this.resizeGroup = g;
            this.resizeGroupStartX = e.clientX; this.resizeGroupStartY = e.clientY;
            this.resizeGroupStartW = g.width; this.resizeGroupStartH = g.height;
        },

        openGroupEditModal(g) {
            this.editingGroup = g;
            this.groupForm = { name: g.name, color: g.color, border_style: g.border_style || 'none' };
            this.showGroupModal = true;
        },

        async saveGroupEdit() {
            if (!this.editingGroup) return;
            await API.updateGroup(this.editingGroup.id, { name: this.groupForm.name, color: this.groupForm.color, border_style: this.groupForm.border_style });
            this.showGroupModal = false; this.editingGroup = null;
            await this.loadData(); this.$nextTick(() => this.renderConnections());
        },

        async deleteGroup(groupId) {
            await API.deleteGroup(groupId);
            await this.loadData(); this.$nextTick(() => this.renderConnections());
        },

        async ungroupAtoms(groupId) {
            await API.deleteGroup(groupId);
            await this.loadData(); this.$nextTick(() => this.renderConnections());
        },

        // 計算群組的巢狀層級（用於邊框向外遞增）
        // 成員越多 = 框越大 = padding 越大 = level 越高
        _getGroupNestLevel(groupId) {
            var group = this.groups.find(function(g) { return g.id === groupId; });
            if (!group) return 0;
            var myCount = group.atom_ids ? group.atom_ids.length : 0;
            var level = 0;
            this.groups.forEach(function(other) {
                if (other.id === groupId) return;
                var otherCount = other.atom_ids ? other.atom_ids.length : 0;
                var hasOverlap = (group.atom_ids || []).some(function(aid) {
                    return (other.atom_ids || []).includes(aid);
                });
                if (hasOverlap) {
                    // 比我小的重疊群組越多，我的 level 越高
                    if (otherCount < myCount || (otherCount === myCount && other.id > groupId)) {
                        level++;
                    }
                }
            });
            return level;
        },

        recalcGroupBounds(groupId) {
            var group = this.groups.find(function(g) { return g.id === groupId; });
            if (!group) return;
            var members = this.atoms.filter(function(ca) { return ca.group_ids && ca.group_ids.includes(groupId); });
            if (members.length === 0) return;
            var nestLevel = this._getGroupNestLevel(groupId);
            var pad = 20 + nestLevel * 10;
            var labelH = 24 + nestLevel * 10;  // 外層群組名稱區域加大，避免被內層框線遮住
            var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            members.forEach(function(ca) {
                var el = document.getElementById('card-' + ca.atom_id);
                var w = el ? el.offsetWidth : (ca.width || 260);
                var h = el ? el.offsetHeight : (ca.height || 120);
                minX = Math.min(minX, ca.pos_x); minY = Math.min(minY, ca.pos_y);
                maxX = Math.max(maxX, ca.pos_x + w); maxY = Math.max(maxY, ca.pos_y + h);
            });
            group.pos_x = minX - pad; group.pos_y = minY - pad - labelH;
            group.width = maxX - minX + pad * 2; group.height = maxY - minY + pad * 2 + labelH;
        },

        autoResizeGroup(groupId) {
            this.recalcGroupBounds(groupId);
            var group = this.groups.find(function(g) { return g.id === groupId; });
            if (group) API.updateGroup(group.id, { pos_x: group.pos_x, pos_y: group.pos_y, width: group.width, height: group.height });
        },
    };
}
