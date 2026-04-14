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
            await this.loadData(); this.$nextTick(function() { self.renderConnections(); });
        },

        getGroupStyle(g) {
            return 'left:' + g.pos_x + 'px; top:' + g.pos_y + 'px; width:' + g.width + 'px; height:' + g.height + 'px; z-index:' + (g.z_index || 1) + '; border-color:' + g.color + '; background:' + g.color + '08;';
        },

        getGroupLabelStyle(g) { return 'color:' + g.color + ';'; },

        onGroupMouseDown(e, g) {
            if (e.button !== 0) return;
            e.stopPropagation();
            this.dragGroup = g;
            this.groupDragStartX = e.clientX; this.groupDragStartY = e.clientY;
            this.groupDragStartPos = { x: g.pos_x, y: g.pos_y };
            var self = this; this.groupDragMemberStarts = {};
            this.atoms.forEach(function(ca) { if (ca.group_id === g.id) self.groupDragMemberStarts[ca.atom_id] = { x: ca.pos_x, y: ca.pos_y }; });
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
            this.groupForm = { name: g.name, color: g.color };
            this.showGroupModal = true;
        },

        async saveGroupEdit() {
            if (!this.editingGroup) return;
            await API.updateGroup(this.editingGroup.id, { name: this.groupForm.name, color: this.groupForm.color });
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

        recalcGroupBounds(groupId) {
            var group = this.groups.find(function(g) { return g.id === groupId; });
            if (!group) return;
            var members = this.atoms.filter(function(ca) { return ca.group_id === groupId; });
            if (members.length === 0) return;
            var pad = 20, labelH = 24;
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
