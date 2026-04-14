/**
 * 白板 Mixin: 小地圖
 */
function whiteboardMinimapMixin() {
    return {
        _minimapVisible: true,
        _minimapMapping: null,
        _minimapDragging: false,

        toggleMinimap() {
            this._minimapVisible = !this._minimapVisible;
            if (this._minimapVisible) this.$nextTick(() => this.renderMinimap());
        },

        renderMinimap() {
            if (!this._minimapVisible) return;
            var mc = this.$refs.minimapCanvas;
            if (!mc) return;
            var ctx = mc.getContext('2d');
            var mw = mc.width, mh = mc.height;
            ctx.clearRect(0, 0, mw, mh);
            ctx.fillStyle = 'rgba(30, 30, 30, 0.85)';
            ctx.fillRect(0, 0, mw, mh);
            if (this.atoms.length === 0) return;

            var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            var self = this;
            this.atoms.forEach(function(ca) {
                var w = ca.width || 260, h = ca.height || 120;
                minX = Math.min(minX, ca.pos_x); minY = Math.min(minY, ca.pos_y);
                maxX = Math.max(maxX, ca.pos_x + w); maxY = Math.max(maxY, ca.pos_y + h);
            });
            this.groups.forEach(function(g) {
                minX = Math.min(minX, g.pos_x); minY = Math.min(minY, g.pos_y);
                maxX = Math.max(maxX, g.pos_x + g.width); maxY = Math.max(maxY, g.pos_y + g.height);
            });
            var pad = 100;
            minX -= pad; minY -= pad; maxX += pad; maxY += pad;
            var cw = maxX - minX, ch = maxY - minY;
            var scale = Math.min((mw - 8) / cw, (mh - 8) / ch);
            var offX = (mw - cw * scale) / 2, offY = (mh - ch * scale) / 2;

            function toMini(x, y) {
                return { x: (x - minX) * scale + offX, y: (y - minY) * scale + offY };
            }

            // Groups
            this.groups.forEach(function(g) {
                var p = toMini(g.pos_x, g.pos_y);
                ctx.strokeStyle = g.color + '80'; ctx.lineWidth = 1;
                ctx.setLineDash([2, 2]); ctx.strokeRect(p.x, p.y, g.width * scale, g.height * scale);
                ctx.setLineDash([]);
            });

            // Connections
            ctx.lineWidth = 0.5;
            this.connections.forEach(function(conn) {
                var srcCa = self.atoms.find(function(a) { return a.atom_id === conn.source_atom_id; });
                var tgtCa = self.atoms.find(function(a) { return a.atom_id === conn.target_atom_id; });
                if (!srcCa || !tgtCa) return;
                var s = toMini(srcCa.pos_x + (srcCa.width || 260) / 2, srcCa.pos_y + (srcCa.height || 120) / 2);
                var t = toMini(tgtCa.pos_x + (tgtCa.width || 260) / 2, tgtCa.pos_y + (tgtCa.height || 120) / 2);
                ctx.strokeStyle = (conn.color || '#94a3b8') + '60';
                ctx.beginPath(); ctx.moveTo(s.x, s.y); ctx.lineTo(t.x, t.y); ctx.stroke();
            });

            // Atoms
            this.atoms.forEach(function(ca) {
                var type = ca.atom ? ca.atom.atom_type : 'F';
                var cfg = self.atomTypeConfig[type] || self.atomTypeConfig.F;
                var lifecycle = ca.atom ? ca.atom.lifecycle : 'active';
                var alpha = { active: 'cc', aging: 'aa', archived: '66', terminal: '33' }[lifecycle] || 'cc';
                var w = ca.width || 260, h = ca.height || 120;
                var p = toMini(ca.pos_x, ca.pos_y);
                ctx.fillStyle = cfg.border + alpha;
                ctx.fillRect(p.x, p.y, Math.max(3, w * scale), Math.max(2, h * scale));
                if (ca.atom_id === self.selectedAtomId) {
                    ctx.strokeStyle = '#3b82f6'; ctx.lineWidth = 1.5;
                    ctx.strokeRect(p.x - 1, p.y - 1, Math.max(3, w * scale) + 2, Math.max(2, h * scale) + 2);
                }
            });

            // Viewport rectangle
            var vp = this.$refs.viewport;
            if (!vp) return;
            var rect = vp.getBoundingClientRect();
            var vp1 = toMini((-this.panX) / this.zoom, (-this.panY) / this.zoom);
            var vpMW = rect.width / this.zoom * scale, vpMH = rect.height / this.zoom * scale;
            ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 1.5;
            ctx.strokeRect(vp1.x, vp1.y, vpMW, vpMH);
            ctx.fillStyle = 'rgba(255, 255, 255, 0.05)';
            ctx.fillRect(vp1.x, vp1.y, vpMW, vpMH);

            this._minimapMapping = { minX: minX, minY: minY, scale: scale, offX: offX, offY: offY };
        },

        onMinimapClick(e) {
            if (!this._minimapMapping) return;
            var mc = this.$refs.minimapCanvas;
            if (!mc) return;
            var cr = mc.getBoundingClientRect();
            var mx = e.clientX - cr.left, my = e.clientY - cr.top;
            var m = this._minimapMapping;
            var cx = (mx - m.offX) / m.scale + m.minX;
            var cy = (my - m.offY) / m.scale + m.minY;
            var vp = this.$refs.viewport;
            if (!vp) return;
            var rect = vp.getBoundingClientRect();
            this.panX = rect.width / 2 - cx * this.zoom;
            this.panY = rect.height / 2 - cy * this.zoom;
            this.updateTransform(); this.renderConnections(); this.renderMinimap(); this.saveViewport();
        },

        onMinimapMouseDown(e) {
            e.preventDefault(); e.stopPropagation();
            this._minimapDragging = true; this.onMinimapClick(e);
        },

        onMinimapMouseMove(e) {
            if (!this._minimapDragging) return;
            this.onMinimapClick(e);
        },

        onMinimapMouseUp(e) { this._minimapDragging = false; },
    };
}
