/**
 * 白板 Mixin: 連線拖拉 + SVG 渲染 + hit test
 */
function whiteboardConnectionsMixin() {
    return {

        // Connection Drag (from anchors)
        startConnDrag(e, ca, anchor) {
            this.isConnDragging = true;
            this.connDragSourceAtomId = ca.atom_id;
            this.connDragSourceAnchor = anchor;
            this.connDragHoverAtomId = null;
            this.connDragShiftKey = e.shiftKey;
            this.connDragMouseX = e.clientX;
            this.connDragMouseY = e.clientY;
            this.updatePreviewLine();
        },

        endConnDrag() {
            if (this.connDragHoverAtomId && this.connDragHoverAtomId !== this.connDragSourceAtomId) {
                if (this.connDragShiftKey) {
                    // Shift+拖拉：跳 modal 選擇型別
                    this.pendingConnection = {
                        sourceAtomId: this.connDragSourceAtomId,
                        targetAtomId: this.connDragHoverAtomId,
                    };
                    this.selectedRelationType = 'references';
                    this.relationLabel = '';
                    this.showRelationModal = true;
                } else {
                    // 普通拖拉：直接建立 references 線
                    this.createConnectionDirect(
                        this.connDragSourceAtomId,
                        this.connDragHoverAtomId,
                        'references'
                    );
                }
            }
            this.isConnDragging = false;
            this.connDragSourceAtomId = null;
            this.connDragSourceAnchor = null;
            this.connDragHoverAtomId = null;
            this.connDragShiftKey = false;
            this.clearPreviewLine();
        },

        async createConnectionDirect(sourceAtomId, targetAtomId, relationType) {
            try {
                var resp = await API.post('/beakcortex/api/canvas-connections', {
                    canvas_id: this.canvasId,
                    source_atom_id: sourceAtomId,
                    target_atom_id: targetAtomId,
                    relation_type: relationType,
                });
                if (resp && !resp.error) {
                    this.connections.push(resp);
                    this.renderConnections();
                    this.showToast(this.relationLabelMap[relationType] || relationType, 'success', 1500);
                }
            } catch (e) {
                this.showToast('連線建立失敗', 'error');
            }
            this.mode = 'select';
        },

        cancelConnDrag() {
            this.isConnDragging = false;
            this.connDragSourceAtomId = null;
            this.connDragSourceAnchor = null;
            this.connDragHoverAtomId = null;
            this.clearPreviewLine();
        },

        getAnchorPos(atomId, anchor) {
            var ca = this.atoms.find(function(a) { return a.atom_id === atomId; });
            if (!ca) return { x: 0, y: 0 };
            var el = document.getElementById('card-' + atomId);
            var w = el ? el.offsetWidth : 260;
            var h = el ? el.offsetHeight : 120;
            switch (anchor) {
                case 'top':    return { x: ca.pos_x + w / 2, y: ca.pos_y };
                case 'bottom': return { x: ca.pos_x + w / 2, y: ca.pos_y + h };
                case 'left':   return { x: ca.pos_x, y: ca.pos_y + h / 2 };
                case 'right':  return { x: ca.pos_x + w, y: ca.pos_y + h / 2 };
                default:       return { x: ca.pos_x + w / 2, y: ca.pos_y + h / 2 };
            }
        },

        findNearestAnchor(atomId, canvasX, canvasY) {
            var ca = this.atoms.find(function(a) { return a.atom_id === atomId; });
            if (!ca) return { x: canvasX, y: canvasY };
            var el = document.getElementById('card-' + atomId);
            var w = el ? el.offsetWidth : 260;
            var h = el ? el.offsetHeight : 120;
            var anchors = [
                { x: ca.pos_x + w / 2, y: ca.pos_y },
                { x: ca.pos_x + w / 2, y: ca.pos_y + h },
                { x: ca.pos_x, y: ca.pos_y + h / 2 },
                { x: ca.pos_x + w, y: ca.pos_y + h / 2 },
            ];
            var nearest = anchors[0];
            var minDist = Infinity;
            for (var i = 0; i < anchors.length; i++) {
                var d = Math.hypot(anchors[i].x - canvasX, anchors[i].y - canvasY);
                if (d < minDist) { minDist = d; nearest = anchors[i]; }
            }
            return nearest;
        },

        updatePreviewLine() {
            var line = this.$refs.previewLine;
            if (!line || !this.isConnDragging) return;
            var src = this.getAnchorPos(this.connDragSourceAtomId, this.connDragSourceAnchor);
            var tgt = this.screenToCanvas(this.connDragMouseX, this.connDragMouseY);
            if (this.connDragHoverAtomId) {
                var snap = this.findNearestAnchor(this.connDragHoverAtomId, tgt.x, tgt.y);
                tgt.x = snap.x; tgt.y = snap.y;
            }
            var dx = tgt.x - src.x;
            var cx1 = src.x + dx * 0.4;
            var cx2 = src.x + dx * 0.6;
            line.setAttribute('d', 'M ' + src.x + ' ' + src.y + ' C ' + cx1 + ' ' + src.y + ', ' + cx2 + ' ' + tgt.y + ', ' + tgt.x + ' ' + tgt.y);
            line.style.display = '';
        },

        clearPreviewLine() {
            var line = this.$refs.previewLine;
            if (line) { line.setAttribute('d', ''); line.style.display = 'none'; }
        },

        onCardMouseEnterForConn(ca) {
            if (this.isConnDragging && ca.atom_id !== this.connDragSourceAtomId) {
                this.connDragHoverAtomId = ca.atom_id;
            }
        },

        onCardMouseLeaveForConn(ca) {
            if (this.connDragHoverAtomId === ca.atom_id) this.connDragHoverAtomId = null;
        },

        // SVG Render helpers
        _calcEdgeEndpoints(srcCa, tgtCa) {
            var sw = srcCa.width || 260, sh = srcCa.height || 120;
            var tw = tgtCa.width || 260, th = tgtCa.height || 120;
            var scx = srcCa.pos_x + sw / 2, scy = srcCa.pos_y + sh / 2;
            var tcx = tgtCa.pos_x + tw / 2, tcy = tgtCa.pos_y + th / 2;
            var ddx = tcx - scx, ddy = tcy - scy;
            var sx, sy, tx, ty;
            if (Math.abs(ddx) > Math.abs(ddy)) {
                if (ddx > 0) { sx = srcCa.pos_x + sw; sy = scy; tx = tgtCa.pos_x; ty = tcy; }
                else         { sx = srcCa.pos_x;       sy = scy; tx = tgtCa.pos_x + tw; ty = tcy; }
            } else {
                if (ddy > 0) { sx = scx; sy = srcCa.pos_y + sh; tx = tcx; ty = tgtCa.pos_y; }
                else         { sx = scx; sy = srcCa.pos_y;       tx = tcx; ty = tgtCa.pos_y + th; }
            }
            return { sx: sx, sy: sy, tx: tx, ty: ty, ddx: ddx, ddy: ddy };
        },

        _buildPathD(ep, straight) {
            if (straight) return 'M ' + ep.sx + ' ' + ep.sy + ' L ' + ep.tx + ' ' + ep.ty;
            var cx1, cy1, cx2, cy2;
            if (Math.abs(ep.ddx) > Math.abs(ep.ddy)) {
                var gx = Math.max(Math.abs(ep.tx - ep.sx) * 0.4, 20);
                cx1 = ep.sx + (ep.ddx > 0 ? gx : -gx); cy1 = ep.sy;
                cx2 = ep.tx + (ep.ddx > 0 ? -gx : gx); cy2 = ep.ty;
            } else {
                var gy = Math.max(Math.abs(ep.ty - ep.sy) * 0.4, 20);
                cx1 = ep.sx; cy1 = ep.sy + (ep.ddy > 0 ? gy : -gy);
                cx2 = ep.tx; cy2 = ep.ty + (ep.ddy > 0 ? -gy : gy);
            }
            return 'M ' + ep.sx + ' ' + ep.sy + ' C ' + cx1 + ' ' + cy1 + ', ' + cx2 + ' ' + cy2 + ', ' + ep.tx + ' ' + ep.ty;
        },

        _getViewportBounds() {
            var vp = this.$refs.viewport;
            if (!vp) return null;
            var rect = vp.getBoundingClientRect();
            var left = -this.panX / this.zoom;
            var top = -this.panY / this.zoom;
            var right = left + rect.width / this.zoom;
            var bottom = top + rect.height / this.zoom;
            return { left: left, top: top, right: right, bottom: bottom, cx: (left + right) / 2, cy: (top + bottom) / 2 };
        },

        _isInViewport(ca, vb) {
            var w = ca.width || 260, h = ca.height || 120;
            return ca.pos_x + w > vb.left && ca.pos_x < vb.right && ca.pos_y + h > vb.top && ca.pos_y < vb.bottom;
        },

        _filterOptimizedConnections(connList) {
            var vb = this._getViewportBounds();
            if (!vb) return connList || this.connections;
            var sourceConns = connList || this.connections;
            var self = this;
            var atomMap = {};
            this.atoms.forEach(function(ca) { atomMap[ca.atom_id] = ca; });
            var outsideCount = 0;
            this.atoms.forEach(function(ca) { if (!self._isInViewport(ca, vb)) outsideCount++; });
            if (outsideCount <= 100) return sourceConns;
            var insideConns = [];
            var outsideConns = [];
            sourceConns.forEach(function(conn) {
                var src = atomMap[conn.source_atom_id];
                var tgt = atomMap[conn.target_atom_id];
                if (!src || !tgt) return;
                if (self._isInViewport(src, vb) && self._isInViewport(tgt, vb)) {
                    insideConns.push(conn);
                } else {
                    var sw = src.width || 260, sh = src.height || 120;
                    var tw = tgt.width || 260, th = tgt.height || 120;
                    var mx = ((src.pos_x + sw / 2) + (tgt.pos_x + tw / 2)) / 2;
                    var my = ((src.pos_y + sh / 2) + (tgt.pos_y + th / 2)) / 2;
                    var dx = mx - vb.cx, dy = my - vb.cy;
                    var dist = Math.sqrt(dx * dx + dy * dy);
                    var angle = Math.atan2(dy, dx);
                    var a = angle + Math.PI / 2;
                    if (a < 0) a += 2 * Math.PI;
                    var sector = Math.floor(a / (Math.PI / 4)) % 8;
                    outsideConns.push({ conn: conn, sector: sector, dist: dist });
                }
            });
            var perSector = this.rtOptPerSector || 10;
            var sectors = [[], [], [], [], [], [], [], []];
            outsideConns.forEach(function(item) { sectors[item.sector].push(item); });
            var kept = [];
            for (var s = 0; s < 8; s++) {
                sectors[s].sort(function(a, b) { return a.dist - b.dist; });
                for (var i = 0; i < Math.min(perSector, sectors[s].length); i++) kept.push(sectors[s][i].conn);
            }
            return insideConns.concat(kept);
        },

        applyRenderSettings() {
            this.renderConnections();
            this.saveRenderSettings();
        },

        saveRenderSettings() {
            if (this.isSnapshot) return;
            var rt = {
                rtEngine: this.rtEngine,
                rtLineStyle: this.rtLineStyle,
                rtOptEnabled: this.rtOptEnabled,
                rtOptPerSector: this.rtOptPerSector,
            };
            var settings;
            try { settings = JSON.parse((this.canvas && this.canvas.settings) || '{}'); } catch (e) { settings = {}; }
            settings.renderTest = rt;
            API.updateCanvas(this.canvasId, { settings: JSON.stringify(settings) });
        },

        _connGeometry: [],

        renderConnections() {
            var svg = this.$refs.connSvg;
            if (!svg) return;
            svg.innerHTML = '';
            this._connGeometry = [];
            if (this.rtLineStyle === 'none') {
                this.renderStats = { total: this.connections.length, rendered: 0 };
                return;
            }
            var visibleIds = this.filteredAtomIds;
            var baseConns = this.connections.filter(function(c) {
                return visibleIds.includes(c.source_atom_id) && visibleIds.includes(c.target_atom_id);
            });
            var renderList = this.rtOptEnabled ? this._filterOptimizedConnections(baseConns) : baseConns;
            this.renderStats = { total: this.connections.length, rendered: renderList.length };
            if (this.rtEngine === 'grouped') this._renderGrouped(svg, renderList);
            else this._renderIndividual(svg, renderList);
        },

        // 計算同對端點的偏移量（多條線避重疊）
        _calcPairOffset(conn, renderList) {
            var a = Math.min(conn.source_atom_id, conn.target_atom_id);
            var b = Math.max(conn.source_atom_id, conn.target_atom_id);
            var sameCount = 0, myIndex = 0;
            for (var i = 0; i < renderList.length; i++) {
                var c = renderList[i];
                var ca = Math.min(c.source_atom_id, c.target_atom_id);
                var cb = Math.max(c.source_atom_id, c.target_atom_id);
                if (ca === a && cb === b) {
                    if (c.id === conn.id) myIndex = sameCount;
                    sameCount++;
                }
            }
            if (sameCount <= 1) return 0;
            var spread = 18;
            return (myIndex - (sameCount - 1) / 2) * spread;
        },

        _buildPathDWithOffset(ep, isStraight, offset) {
            if (offset === 0) return this._buildPathD(ep, isStraight);
            // 計算法向量偏移
            var dx = ep.tx - ep.sx, dy = ep.ty - ep.sy;
            var len = Math.sqrt(dx * dx + dy * dy) || 1;
            var nx = -dy / len * offset, ny = dx / len * offset;
            var mx = (ep.sx + ep.tx) / 2 + nx;
            var my = (ep.sy + ep.ty) / 2 + ny;
            return 'M ' + ep.sx + ' ' + ep.sy + ' Q ' + mx + ' ' + my + ', ' + ep.tx + ' ' + ep.ty;
        },

        _renderIndividual(svg, renderList) {
            var isStraight = (this.rtLineStyle === 'straight');
            var defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
            var usedColors = new Set();
            this.connections.forEach(function(c) { usedColors.add(c.color || '#94a3b8'); });
            usedColors.forEach(function(color) {
                var marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
                var mid = 'arr-' + color.replace('#', '');
                marker.setAttribute('id', mid);
                marker.setAttribute('viewBox', '0 0 10 10');
                marker.setAttribute('refX', '9'); marker.setAttribute('refY', '5');
                marker.setAttribute('markerWidth', '6'); marker.setAttribute('markerHeight', '6');
                marker.setAttribute('orient', 'auto-start-reverse');
                var p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                p.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z'); p.setAttribute('fill', color);
                marker.appendChild(p); defs.appendChild(marker);
            });
            svg.appendChild(defs);
            var self = this;
            var atomMap = {};
            this.atoms.forEach(function(ca) { atomMap[ca.atom_id] = ca; });
            renderList.forEach(function(conn) {
                var srcCa = atomMap[conn.source_atom_id];
                var tgtCa = atomMap[conn.target_atom_id];
                if (!srcCa || !tgtCa) return;
                var ep = self._calcEdgeEndpoints(srcCa, tgtCa);
                var offset = self._calcPairOffset(conn, renderList);
                var lc = conn.color || '#94a3b8';
                var mid = 'arr-' + lc.replace('#', '');
                var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', self._buildPathDWithOffset(ep, isStraight, offset));
                path.setAttribute('fill', 'none'); path.setAttribute('stroke', lc);
                path.setAttribute('stroke-width', '2'); path.setAttribute('marker-end', 'url(#' + mid + ')');
                if (conn.line_style === 'dashed') path.setAttribute('stroke-dasharray', '8 4');
                else if (conn.line_style === 'dotted') path.setAttribute('stroke-dasharray', '3 3');
                path.style.pointerEvents = 'stroke'; path.style.cursor = 'pointer';
                var connId = conn.id;
                var connRelType = conn.relation_type || '';
                // 右鍵：開啟連線選單（改型別 / 刪除）
                path.addEventListener('contextmenu', function(e) {
                    e.preventDefault(); e.stopPropagation();
                    self.showConnContextMenu(connId, connRelType, e.clientX, e.clientY);
                });
                // 雙擊：開啟型別修改
                path.addEventListener('dblclick', function(e) {
                    e.stopPropagation();
                    self.showConnTypeChangeModal(connId, connRelType);
                });
                svg.appendChild(path);
                var labelText = conn.label || self.relationLabelMap[conn.relation_type] || '';
                if (labelText) {
                    var mx = (ep.sx + ep.tx) / 2, my = (ep.sy + ep.ty) / 2;
                    if (offset !== 0) { var ndx = ep.tx - ep.sx, ndy = ep.ty - ep.sy; var nl = Math.sqrt(ndx*ndx+ndy*ndy)||1; mx += (-ndy/nl*offset)/2; my += (ndx/nl*offset)/2; }
                    var text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                    text.setAttribute('x', mx); text.setAttribute('y', my - 8);
                    text.setAttribute('text-anchor', 'middle');
                    text.setAttribute('class', 'conn-label conn-label-editable');
                    text.setAttribute('fill', lc); text.style.cursor = 'text';
                    text.textContent = labelText;
                    var cid = conn.id;
                    text.addEventListener('dblclick', function(e) { e.stopPropagation(); self.startEditConnection(cid, e.clientX, e.clientY); });
                    svg.appendChild(text);
                }
            });
        },

        showConnContextMenu(connId, relType, x, y) {
            this.connContextMenu = { connId: connId, relType: relType, x: x, y: y };
        },

        closeConnContextMenu() {
            this.connContextMenu = null;
        },

        async connContextAction(action) {
            var menu = this.connContextMenu;
            if (!menu) return;
            this.connContextMenu = null;
            if (action === 'delete') {
                this.deleteConnection(menu.connId);
            } else if (action === 'change-type') {
                this.showConnTypeChangeModal(menu.connId, menu.relType);
            }
        },

        showConnTypeChangeModal(connId, currentType) {
            this.connTypeChangeTarget = connId;
            this.selectedRelationType = currentType || 'references';
            this.showConnTypeModal = true;
        },

        async confirmConnTypeChange() {
            if (!this.connTypeChangeTarget) return;
            try {
                await API.put('/beakcortex/api/canvas-connections/' + this.connTypeChangeTarget, {
                    relation_type: this.selectedRelationType,
                });
                this.showConnTypeModal = false;
                this.connTypeChangeTarget = null;
                await this.loadData();
                this.renderConnections();
                this.showToast('已變更為 ' + (this.relationLabelMap[this.selectedRelationType] || this.selectedRelationType), 'success', 1500);
            } catch (e) {
                this.showToast('變更失敗', 'error');
            }
        },

        _renderGrouped(svg, renderList) {
            var isStraight = (this.rtLineStyle === 'straight');
            var self = this;
            var atomMap = {};
            this.atoms.forEach(function(ca) { atomMap[ca.atom_id] = ca; });
            var groups = {};
            var geom = [];
            renderList.forEach(function(conn) {
                var srcCa = atomMap[conn.source_atom_id];
                var tgtCa = atomMap[conn.target_atom_id];
                if (!srcCa || !tgtCa) return;
                var ep = self._calcEdgeEndpoints(srcCa, tgtCa);
                var lc = conn.color || '#94a3b8';
                var ls = conn.line_style || 'solid';
                var key = lc + '|' + ls;
                if (!groups[key]) {
                    var da = '';
                    if (ls === 'dashed') da = '8 4'; else if (ls === 'dotted') da = '3 3';
                    groups[key] = { d: '', arrowD: '', color: lc, dasharray: da };
                }
                groups[key].d += self._buildPathD(ep, isStraight) + ' ';
                var adx = ep.tx - ep.sx, ady = ep.ty - ep.sy;
                var len = Math.sqrt(adx * adx + ady * ady);
                if (len > 0) {
                    var ux = adx / len, uy = ady / len;
                    var px = -uy, py = ux;
                    var as = 7;
                    groups[key].arrowD += 'M ' + ep.tx + ' ' + ep.ty +
                        ' L ' + (ep.tx - ux * as * 1.5 + px * as) + ' ' + (ep.ty - uy * as * 1.5 + py * as) +
                        ' L ' + (ep.tx - ux * as * 1.5 - px * as) + ' ' + (ep.ty - uy * as * 1.5 - py * as) + ' Z ';
                }
                var lt = conn.label || self.relationLabelMap[conn.relation_type] || '';
                geom.push({ connId: conn.id, sx: ep.sx, sy: ep.sy, tx: ep.tx, ty: ep.ty, label: lt, color: lc });
            });
            this._connGeometry = geom;
            geom.forEach(function(g) {
                if (!g.label) return;
                var mx = (g.sx + g.tx) / 2, my = (g.sy + g.ty) / 2;
                var text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                text.setAttribute('x', mx); text.setAttribute('y', my - 8);
                text.setAttribute('text-anchor', 'middle');
                text.setAttribute('class', 'conn-label conn-label-editable');
                text.setAttribute('fill', g.color); text.style.cursor = 'text';
                text.textContent = g.label;
                var cid = g.connId;
                text.addEventListener('dblclick', function(e) { e.stopPropagation(); self.startEditConnection(cid, e.clientX, e.clientY); });
                svg.appendChild(text);
            });
            var keys = Object.keys(groups);
            for (var i = 0; i < keys.length; i++) {
                var g = groups[keys[i]];
                var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', g.d); path.setAttribute('fill', 'none');
                path.setAttribute('stroke', g.color); path.setAttribute('stroke-width', '2');
                if (g.dasharray) path.setAttribute('stroke-dasharray', g.dasharray);
                path.style.pointerEvents = 'stroke'; path.style.cursor = 'pointer';
                path.addEventListener('click', function(e) { self._onGroupedLineClick(e); });
                svg.appendChild(path);
                if (g.arrowD) {
                    var arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                    arrow.setAttribute('d', g.arrowD); arrow.setAttribute('fill', g.color);
                    arrow.setAttribute('stroke', 'none'); arrow.style.pointerEvents = 'none';
                    svg.appendChild(arrow);
                }
            }
        },

        _onGroupedLineClick(e) {
            var vp = this.$refs.viewport;
            if (!vp) return;
            var rect = vp.getBoundingClientRect();
            var cx = (e.clientX - rect.left - this.panX) / this.zoom;
            var cy = (e.clientY - rect.top - this.panY) / this.zoom;
            var best = null, bestDist = Infinity;
            for (var i = 0; i < this._connGeometry.length; i++) {
                var g = this._connGeometry[i];
                var d = this._pointToSegmentDist(cx, cy, g.sx, g.sy, g.tx, g.ty);
                if (d < bestDist) { bestDist = d; best = g; }
            }
            if (best && bestDist < 20 / this.zoom) {
                if (confirm('刪除此連線?')) this.deleteConnection(best.connId);
            }
        },

        _pointToSegmentDist(px, py, x1, y1, x2, y2) {
            var dx = x2 - x1, dy = y2 - y1;
            var lenSq = dx * dx + dy * dy;
            if (lenSq === 0) return Math.sqrt((px - x1) * (px - x1) + (py - y1) * (py - y1));
            var t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / lenSq));
            var nx = x1 + t * dx, ny = y1 + t * dy;
            return Math.sqrt((px - nx) * (px - nx) + (py - ny) * (py - ny));
        },
    };
}
