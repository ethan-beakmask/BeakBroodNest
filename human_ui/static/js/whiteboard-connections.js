/**
 * 白板 Mixin: 連線拖拉 + SVG 渲染 + hit test
 */
function whiteboardConnectionsMixin() {
    return {

        // Connection Drag (from card anchors)
        startConnDrag(e, ca, anchor) {
            this.isConnDragging = true;
            this.connDragSourceKind = 'atom';
            this.connDragSourceAtomId = ca.atom_id;
            this.connDragSourceTextboxId = null;
            this.connDragSourceAnchor = anchor;
            this.connDragSourceEntryId = null;
            this.connDragHoverAtomId = null;
            this.connDragHoverTextboxId = null;
            this.connDragHoverEntryId = null;
            this.connDragShiftKey = e.shiftKey;
            this.connDragMouseX = e.clientX;
            this.connDragMouseY = e.clientY;
            this.updatePreviewLine();
        },

        // Entry-level connection drag
        startEntryConnDrag(e, ca, entry) {
            this.isConnDragging = true;
            this.connDragSourceAtomId = ca.atom_id;
            this.connDragSourceEntryId = entry.id;
            this.connDragSourceAnchor = 'right';
            this.connDragHoverAtomId = null;
            this.connDragHoverEntryId = null;
            this.connDragShiftKey = e.shiftKey;
            this.connDragMouseX = e.clientX;
            this.connDragMouseY = e.clientY;
            this.updatePreviewLine();
        },

        onEntryMouseEnter(ca, entry) {
            if (this.isConnDragging && (ca.atom_id !== this.connDragSourceAtomId || entry.id !== this.connDragSourceEntryId)) {
                this.connDragHoverAtomId = ca.atom_id;
                this.connDragHoverEntryId = entry.id;
                var el = document.getElementById('entry-' + ca.atom_id + '-' + entry.id);
                if (el) el.classList.add('conn-entry-hover');
            }
        },

        onEntryMouseLeave(ca, entry) {
            if (this.connDragHoverEntryId === entry.id) {
                this.connDragHoverEntryId = null;
                if (this.connDragHoverAtomId === ca.atom_id) this.connDragHoverAtomId = null;
            }
            var el = document.getElementById('entry-' + ca.atom_id + '-' + entry.id);
            if (el) el.classList.remove('conn-entry-hover');
        },

        endConnDrag() {
            // 清除 hover 樣式
            if (this.connDragHoverEntryId && this.connDragHoverAtomId) {
                var hel = document.getElementById('entry-' + this.connDragHoverAtomId + '-' + this.connDragHoverEntryId);
                if (hel) hel.classList.remove('conn-entry-hover');
            }

            var srcKind = this.connDragSourceKind || 'atom';
            var tgtKind = this.connDragHoverTextboxId ? 'textbox'
                        : (this.connDragHoverAtomId ? 'atom' : null);
            var sameNode = (srcKind === tgtKind) && (
                (srcKind === 'atom'    && this.connDragHoverAtomId    === this.connDragSourceAtomId) ||
                (srcKind === 'textbox' && this.connDragHoverTextboxId === this.connDragSourceTextboxId)
            );
            var hasTarget = tgtKind && !sameNode;
            var isEntryLevel = (srcKind === 'atom' && tgtKind === 'atom') &&
                               (this.connDragSourceEntryId || this.connDragHoverEntryId);
            var isPureAtom = (srcKind === 'atom' && tgtKind === 'atom');

            if (hasTarget || (isPureAtom && this.connDragHoverAtomId && isEntryLevel)) {
                if (isPureAtom && this.connDragShiftKey) {
                    // Shift+拖拉：跳 modal 選擇型別（僅 atom-atom）
                    this.pendingConnection = {
                        sourceAtomId: this.connDragSourceAtomId,
                        targetAtomId: this.connDragHoverAtomId,
                        sourceEntryId: this.connDragSourceEntryId || null,
                        targetEntryId: this.connDragHoverEntryId || null,
                    };
                    this.selectedRelationType = isEntryLevel ? 'freeform' : 'references';
                    this.relationLabel = '';
                    this.showRelationModal = true;
                } else if (isPureAtom) {
                    this.createConnectionDirect(
                        this.connDragSourceAtomId,
                        this.connDragHoverAtomId,
                        isEntryLevel ? 'freeform' : 'references',
                        this.connDragSourceEntryId || null,
                        this.connDragHoverEntryId || null
                    );
                } else {
                    // textbox 端點：純視覺連線，不掛 unified_relation
                    this.createTextboxConnectionDirect(
                        srcKind, this.connDragSourceAtomId, this.connDragSourceTextboxId,
                        tgtKind, this.connDragHoverAtomId, this.connDragHoverTextboxId
                    );
                }
            }
            this.isConnDragging = false;
            this.connDragSourceKind = null;
            this.connDragSourceAtomId = null;
            this.connDragSourceTextboxId = null;
            this.connDragSourceAnchor = null;
            this.connDragSourceEntryId = null;
            this.connDragHoverAtomId = null;
            this.connDragHoverTextboxId = null;
            this.connDragHoverEntryId = null;
            this.connDragShiftKey = false;
            this.clearPreviewLine();
        },

        async createTextboxConnectionDirect(srcKind, srcAtomId, srcTbId, tgtKind, tgtAtomId, tgtTbId) {
            try {
                var payload = {
                    canvas_id: this.canvasId,
                    from_kind: srcKind, to_kind: tgtKind,
                };
                if (srcKind === 'atom')    payload.source_atom_id = srcAtomId;
                if (srcKind === 'textbox') payload.source_textbox_id = srcTbId;
                if (tgtKind === 'atom')    payload.target_atom_id = tgtAtomId;
                if (tgtKind === 'textbox') payload.target_textbox_id = tgtTbId;
                var resp = await API.post('/beakbroodnest/api/canvas-connections', payload);
                if (resp && !resp.error) {
                    var newConnId = resp.id;
                    var self = this;
                    this.pushUndo({
                        type: 'create_connection',
                        desc: '建立連線',
                        undo: async function() {
                            try { await API.deleteConnection(newConnId); } catch (e) {}
                            await self.loadData();
                            self.$nextTick(function() { self.renderConnections(); });
                        },
                        redo: async function() {
                            try { await API.post('/beakbroodnest/api/canvas-connections', payload); } catch (e) {}
                            await self.loadData();
                            self.$nextTick(function() { self.renderConnections(); });
                        },
                    });
                    await this.loadData();
                    this.renderConnections();
                }
            } catch (e) {
                this.showToast('連線建立失敗', 'error');
            }
            this.mode = 'select';
        },

        async createConnectionDirect(sourceAtomId, targetAtomId, relationType, sourceEntryId, targetEntryId) {
            try {
                var payload = {
                    canvas_id: this.canvasId,
                    source_atom_id: sourceAtomId,
                    target_atom_id: targetAtomId,
                    relation_type: relationType,
                };
                if (sourceEntryId) payload.source_entry_id = sourceEntryId;
                if (targetEntryId) payload.target_entry_id = targetEntryId;

                var resp = await API.post('/beakbroodnest/api/canvas-connections', payload);
                if (resp && !resp.error) {
                    var newConnId = resp.id;
                    var self = this;
                    this.pushUndo({
                        type: 'create_connection',
                        desc: '建立連線',
                        undo: async function() {
                            try { await API.deleteConnection(newConnId); } catch (e) {}
                            await self.loadData();
                            self.$nextTick(function() { self.renderConnections(); });
                        },
                        redo: async function() {
                            try { await API.post('/beakbroodnest/api/canvas-connections', payload); } catch (e) {}
                            await self.loadData();
                            self.$nextTick(function() { self.renderConnections(); });
                        },
                    });
                    await this.loadData();
                    this.renderConnections();
                    this.showToast(this.relationLabelMap[relationType] || relationType, 'success', 1500);
                }
            } catch (e) {
                this.showToast('連線建立失敗', 'error');
            }
            this.mode = 'select';
        },

        cancelConnDrag() {
            // 清除 hover 樣式
            if (this.connDragHoverEntryId && this.connDragHoverAtomId) {
                var hel = document.getElementById('entry-' + this.connDragHoverAtomId + '-' + this.connDragHoverEntryId);
                if (hel) hel.classList.remove('conn-entry-hover');
            }
            this.isConnDragging = false;
            this.connDragSourceKind = null;
            this.connDragSourceAtomId = null;
            this.connDragSourceTextboxId = null;
            this.connDragSourceAnchor = null;
            this.connDragSourceEntryId = null;
            this.connDragHoverAtomId = null;
            this.connDragHoverTextboxId = null;
            this.connDragHoverEntryId = null;
            this.clearPreviewLine();
        },

        getAnchorPos(atomId, anchor) {
            var ca = this.atoms.find(function(a) { return a.atom_id === atomId; });
            if (!ca) return { x: 0, y: 0 };
            var el = document.getElementById('card-' + atomId);
            var w = el ? el.offsetWidth : 265;
            var h = el ? el.offsetHeight : 125;
            switch (anchor) {
                case 'top':    return { x: ca.pos_x + w / 2, y: ca.pos_y };
                case 'bottom': return { x: ca.pos_x + w / 2, y: ca.pos_y + h };
                case 'left':   return { x: ca.pos_x, y: ca.pos_y + h / 2 };
                case 'right':  return { x: ca.pos_x + w, y: ca.pos_y + h / 2 };
                default:       return { x: ca.pos_x + w / 2, y: ca.pos_y + h / 2 };
            }
        },

        // 取得 entry 錨點在 canvas 座標系中的位置
        // 純計算，不依賴 DOM（拖曳時 DOM 座標不穩定）
        getEntryEdgePos(atomId, entryId, side) {
            var ca = this.atoms.find(function(a) { return a.atom_id === atomId; });
            if (!ca) return { x: 0, y: 0 };
            var sz = this._getCardSize(ca);
            // 錨點內縮距離（從 card 邊緣到錨點中心）
            var ANCHOR_INSET_R = 10;  // 右側: padding-right(6) + anchor半徑(3.5)
            var ANCHOR_INSET_L = 11;  // 左側: padding-left(4) + icon中心(7)
            // 佈局常數
            var HEADER_H = 37;  // card header (min-height 36 + 1px border)
            var BODY_PAD = 6;   // card-body padding-top
            var ROW_H = 22;     // entry row min-height

            var entries = (ca.atom && ca.atom.entries) || [];
            var idx = 0;
            for (var i = 0; i < entries.length; i++) {
                if (entries[i].id === entryId) { idx = i; break; }
            }
            var entryMidY = ca.pos_y + HEADER_H + BODY_PAD + idx * ROW_H + ROW_H / 2;
            if (side === 'left') return { x: ca.pos_x + ANCHOR_INSET_L, y: entryMidY };
            return { x: ca.pos_x + sz.w - ANCHOR_INSET_R, y: entryMidY };
        },

        findNearestAnchor(atomId, canvasX, canvasY) {
            var ca = this.atoms.find(function(a) { return a.atom_id === atomId; });
            if (!ca) return { x: canvasX, y: canvasY };
            var el = document.getElementById('card-' + atomId);
            var w = el ? el.offsetWidth : 265;
            var h = el ? el.offsetHeight : 125;
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
            // 起點：entry 級 -> entry 邊緣；card/textbox 級 -> 對應 anchor
            var src;
            if (this.connDragSourceKind === 'textbox') {
                src = this.getTextboxAnchorPos(this.connDragSourceTextboxId, this.connDragSourceAnchor);
            } else if (this.connDragSourceEntryId) {
                src = this.getEntryEdgePos(this.connDragSourceAtomId, this.connDragSourceEntryId, 'right');
            } else {
                src = this.getAnchorPos(this.connDragSourceAtomId, this.connDragSourceAnchor);
            }
            var tgt = this.screenToCanvas(this.connDragMouseX, this.connDragMouseY);
            // 終點 snap
            if (this.connDragHoverEntryId && this.connDragHoverAtomId) {
                var eSide = (tgt.x < src.x) ? 'right' : 'left';
                var ep = this.getEntryEdgePos(this.connDragHoverAtomId, this.connDragHoverEntryId, eSide);
                tgt.x = ep.x; tgt.y = ep.y;
            } else if (this.connDragHoverTextboxId) {
                var snap = this.findNearestTextboxAnchor(this.connDragHoverTextboxId, tgt.x, tgt.y);
                tgt.x = snap.x; tgt.y = snap.y;
            } else if (this.connDragHoverAtomId) {
                var snap2 = this.findNearestAnchor(this.connDragHoverAtomId, tgt.x, tgt.y);
                tgt.x = snap2.x; tgt.y = snap2.y;
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
            if (!this.isConnDragging) return;
            // entry 級拖拉允許同卡片（不同 entry），card 級拖拉禁止同卡片
            // textbox->atom 連線無同卡片限制
            var sameAtomSource = (this.connDragSourceKind === 'atom' && ca.atom_id === this.connDragSourceAtomId);
            if (this.connDragSourceEntryId || !sameAtomSource) {
                this.connDragHoverAtomId = ca.atom_id;
                this.connDragHoverTextboxId = null;
            }
        },

        onCardMouseLeaveForConn(ca) {
            if (this.connDragHoverAtomId === ca.atom_id && !this.connDragHoverEntryId) {
                this.connDragHoverAtomId = null;
            }
        },

        // SVG Render helpers
        _getCardSize(ca) {
            var el = document.getElementById('card-' + ca.atom_id);
            var w = el ? el.offsetWidth : 0;
            var h = el ? el.offsetHeight : 0;
            return {
                w: w || ca.width || 265,
                h: h || ca.height || 125,
            };
        },

        // 取得連線端點的「物件」(atom 卡片或文字框)
        // 回傳統一形狀: { kind, id, pos_x, pos_y, w, h }
        _getConnEndpointObj(conn, side) {
            if (side === 'source') {
                if (conn.from_kind === 'textbox') {
                    var tb = (this.textboxes || []).find(function(x) { return x.id === conn.source_textbox_id; });
                    if (!tb) return null;
                    return { kind: 'textbox', id: tb.id, pos_x: tb.pos_x, pos_y: tb.pos_y, w: tb.width, h: tb.height };
                }
                var srcCa = this.atoms.find(function(a) { return a.atom_id === conn.source_atom_id; });
                if (!srcCa) return null;
                var sz = this._getCardSize(srcCa);
                return { kind: 'atom', id: srcCa.atom_id, pos_x: srcCa.pos_x, pos_y: srcCa.pos_y, w: sz.w, h: sz.h };
            } else {
                if (conn.to_kind === 'textbox') {
                    var tb2 = (this.textboxes || []).find(function(x) { return x.id === conn.target_textbox_id; });
                    if (!tb2) return null;
                    return { kind: 'textbox', id: tb2.id, pos_x: tb2.pos_x, pos_y: tb2.pos_y, w: tb2.width, h: tb2.height };
                }
                var tgtCa = this.atoms.find(function(a) { return a.atom_id === conn.target_atom_id; });
                if (!tgtCa) return null;
                var sz2 = this._getCardSize(tgtCa);
                return { kind: 'atom', id: tgtCa.atom_id, pos_x: tgtCa.pos_x, pos_y: tgtCa.pos_y, w: sz2.w, h: sz2.h };
            }
        },

        // 通用：接受 endpoint 物件 ({ pos_x, pos_y, w, h })
        _calcEdgeEndpoints(srcEp, tgtEp) {
            var sw = srcEp.w, sh = srcEp.h;
            var tw = tgtEp.w, th = tgtEp.h;
            var scx = srcEp.pos_x + sw / 2, scy = srcEp.pos_y + sh / 2;
            var tcx = tgtEp.pos_x + tw / 2, tcy = tgtEp.pos_y + th / 2;
            var ddx = tcx - scx, ddy = tcy - scy;
            var sx, sy, tx, ty;
            if (Math.abs(ddx) > Math.abs(ddy)) {
                if (ddx > 0) { sx = srcEp.pos_x + sw; sy = scy; tx = tgtEp.pos_x; ty = tcy; }
                else         { sx = srcEp.pos_x;       sy = scy; tx = tgtEp.pos_x + tw; ty = tcy; }
            } else {
                if (ddy > 0) { sx = scx; sy = srcEp.pos_y + sh; tx = tcx; ty = tgtEp.pos_y; }
                else         { sx = scx; sy = srcEp.pos_y;       tx = tcx; ty = tgtEp.pos_y + th; }
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
            var csz = this._getCardSize(ca); var w = csz.w, h = csz.h;
            return ca.pos_x + w > vb.left && ca.pos_x < vb.right && ca.pos_y + h > vb.top && ca.pos_y < vb.bottom;
        },

        _isEpInViewport(ep, vb) {
            return ep.pos_x + ep.w > vb.left && ep.pos_x < vb.right && ep.pos_y + ep.h > vb.top && ep.pos_y < vb.bottom;
        },

        _filterOptimizedConnections(connList) {
            var vb = this._getViewportBounds();
            if (!vb) return connList || this.connections;
            var sourceConns = connList || this.connections;
            var self = this;
            var outsideCount = 0;
            this.atoms.forEach(function(ca) { if (!self._isInViewport(ca, vb)) outsideCount++; });
            if (outsideCount <= 100) return sourceConns;
            var insideConns = [];
            var outsideConns = [];
            sourceConns.forEach(function(conn) {
                var src = self._getConnEndpointObj(conn, 'source');
                var tgt = self._getConnEndpointObj(conn, 'target');
                if (!src || !tgt) return;
                if (self._isEpInViewport(src, vb) && self._isEpInViewport(tgt, vb)) {
                    insideConns.push(conn);
                } else {
                    var mx = ((src.pos_x + src.w / 2) + (tgt.pos_x + tgt.w / 2)) / 2;
                    var my = ((src.pos_y + src.h / 2) + (tgt.pos_y + tgt.h / 2)) / 2;
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
            // $refs.connSvg 在某些 reactive 重建後會暫時失效（如 setShellLayout 後 alpine 對
            // atoms/mindmapShells/treeParents 連續重新賦值的 nextTick 內），用 querySelector
            // 作 fallback 確保 SVG 取得到
            var svg = this.$refs.connSvg || document.querySelector('.wb-connections:not(.wb-preview-layer)');
            if (!svg) {
                if (this.renderMinimap) this.renderMinimap();
                return;
            }
            svg.innerHTML = '';
            this._connGeometry = [];
            // 心智圖樹線優先繪製（在連線下層）
            if (this.renderMindmapTreeLines) this.renderMindmapTreeLines(svg);
            if (this.rtLineStyle === 'none') {
                this.renderStats = { total: this.connections.length, rendered: 0 };
                if (this.renderMinimap) this.renderMinimap();
                return;
            }
            var visibleIds = this.filteredAtomIds;
            // 心智圖摺疊隱藏的後代 atom，連線需一併隱藏（展開時 renderConnections 會重繪恢復）
            var hiddenByCollapse = (this._collapsedHiddenAtomIds ? this._collapsedHiddenAtomIds() : {}) || {};
            // 連線可見性：atom 端點受 filter 控制；textbox 端點一律可見
            // 樹線(灰色)與 connection(彩色)並存,不去重
            var baseConns = this.connections.filter(function(c) {
                var srcOk = (c.from_kind === 'textbox') || (visibleIds.includes(c.source_atom_id) && !hiddenByCollapse[c.source_atom_id]);
                var tgtOk = (c.to_kind   === 'textbox') || (visibleIds.includes(c.target_atom_id) && !hiddenByCollapse[c.target_atom_id]);
                return srcOk && tgtOk;
            });
            var renderList = this.rtOptEnabled ? this._filterOptimizedConnections(baseConns) : baseConns;
            this.renderStats = { total: this.connections.length, rendered: renderList.length };
            if (this.rtEngine === 'grouped') this._renderGrouped(svg, renderList);
            else this._renderIndividual(svg, renderList);
            // 心智圖節點移動/排序/層級切換等只重繪連線,minimap 也跟著更新
            if (this.renderMinimap) this.renderMinimap();
        },

        // 計算同對端點的偏移量（多條線避重疊）
        // 端點 key 用 kind 與 id 組合，避免不同類型 ID 撞號
        _connEndpointKey(conn, side) {
            if (side === 'source') {
                return (conn.from_kind || 'atom') + ':' + (conn.from_kind === 'textbox' ? conn.source_textbox_id : conn.source_atom_id);
            }
            return (conn.to_kind || 'atom') + ':' + (conn.to_kind === 'textbox' ? conn.target_textbox_id : conn.target_atom_id);
        },

        _calcPairOffset(conn, renderList) {
            var sk = this._connEndpointKey(conn, 'source');
            var tk = this._connEndpointKey(conn, 'target');
            var a = sk < tk ? sk : tk;
            var b = sk < tk ? tk : sk;
            var sameCount = 0, myIndex = 0;
            for (var i = 0; i < renderList.length; i++) {
                var c = renderList[i];
                var csk = this._connEndpointKey(c, 'source');
                var ctk = this._connEndpointKey(c, 'target');
                var ca = csk < ctk ? csk : ctk;
                var cb = csk < ctk ? ctk : csk;
                if (ca === a && cb === b) {
                    if (c.id === conn.id) myIndex = sameCount;
                    sameCount++;
                }
            }
            if (sameCount <= 1) return { offset: 0, index: 0, total: 1 };
            var spread = 27;
            return { offset: (myIndex - (sameCount - 1) / 2) * spread, index: myIndex, total: sameCount };
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

        // entry-level 端點：ER-model 風格，永遠左右出線
        _calcEntryEndpoints(srcCa, tgtCa, conn) {
            var srcEntryId = conn.source_entry_id;
            var tgtEntryId = conn.target_entry_id;
            var srcSize = this._getCardSize(srcCa);
            var tgtSize = this._getCardSize(tgtCa);
            // 用 card 中心 X 判斷相對位置
            var srcCx = srcCa.pos_x + srcSize.w / 2;
            var tgtCx = tgtCa.pos_x + tgtSize.w / 2;
            // target 在 source 右邊（或重疊）-> source 從右出，target 從左入
            // target 在 source 左邊 -> source 從左出，target 從右入
            var srcSide, tgtSide;
            if (tgtCx >= srcCx) {
                srcSide = 'right'; tgtSide = 'left';
            } else {
                srcSide = 'left'; tgtSide = 'right';
            }
            var sx, sy, tx, ty;
            if (srcEntryId) {
                var sp = this.getEntryEdgePos(srcCa.atom_id, srcEntryId, srcSide);
                sx = sp.x; sy = sp.y;
            } else {
                sx = srcSide === 'right' ? srcCa.pos_x + srcSize.w : srcCa.pos_x;
                sy = srcCa.pos_y + srcSize.h / 2;
            }
            if (tgtEntryId) {
                var tp = this.getEntryEdgePos(tgtCa.atom_id, tgtEntryId, tgtSide);
                tx = tp.x; ty = tp.y;
            } else {
                tx = tgtSide === 'left' ? tgtCa.pos_x : tgtCa.pos_x + tgtSize.w;
                ty = tgtCa.pos_y + tgtSize.h / 2;
            }
            return { sx: sx, sy: sy, tx: tx, ty: ty, ddx: tx - sx, ddy: ty - sy };
        },

        _renderIndividual(svg, renderList) {
            var isStraight = (this.rtLineStyle === 'straight');
            var defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
            var usedColors = new Set();
            this.connections.forEach(function(c) { usedColors.add(c.color || '#94a3b8'); });
            usedColors.forEach(function(color) {
                // card 級箭頭（大）
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
                // entry 級箭頭（小）
                var markerSm = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
                var midSm = 'arr-sm-' + color.replace('#', '');
                markerSm.setAttribute('id', midSm);
                markerSm.setAttribute('viewBox', '0 0 10 10');
                markerSm.setAttribute('refX', '9'); markerSm.setAttribute('refY', '5');
                markerSm.setAttribute('markerWidth', '4'); markerSm.setAttribute('markerHeight', '4');
                markerSm.setAttribute('orient', 'auto-start-reverse');
                var pSm = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                pSm.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z'); pSm.setAttribute('fill', color);
                markerSm.appendChild(pSm); defs.appendChild(markerSm);
            });
            svg.appendChild(defs);
            var self = this;
            renderList.forEach(function(conn) {
                var srcEp = self._getConnEndpointObj(conn, 'source');
                var tgtEp = self._getConnEndpointObj(conn, 'target');
                if (!srcEp || !tgtEp) return;
                var isAtomToAtom = (srcEp.kind === 'atom' && tgtEp.kind === 'atom');
                var isEntryConn = isAtomToAtom && !!(conn.source_entry_id || conn.target_entry_id);
                var ep;
                if (isEntryConn) {
                    var srcCa = self.atoms.find(function(a) { return a.atom_id === conn.source_atom_id; });
                    var tgtCa = self.atoms.find(function(a) { return a.atom_id === conn.target_atom_id; });
                    ep = self._calcEntryEndpoints(srcCa, tgtCa, conn);
                } else {
                    ep = self._calcEdgeEndpoints(srcEp, tgtEp);
                }
                var pairInfo = self._calcPairOffset(conn, renderList);
                var offset = isEntryConn ? 0 : pairInfo.offset;
                // 心智圖節點之間 connection: 強制繞行,避免在小卡密集排列時退化為直線/重疊
                if (!isEntryConn && isAtomToAtom) {
                    var srcCa2 = self.atoms.find(function(a) { return a.atom_id === conn.source_atom_id; });
                    var tgtCa2 = self.atoms.find(function(a) { return a.atom_id === conn.target_atom_id; });
                    if (srcCa2 && tgtCa2 && srcCa2.mindmap_shell_id && tgtCa2.mindmap_shell_id) {
                        var MM_BASE = 32;
                        if (pairInfo.total === 1) {
                            offset = MM_BASE;
                        } else {
                            // 多條時 spread 拉大,保留奇偶分散方向
                            var idx = pairInfo.index, total = pairInfo.total;
                            offset = (idx - (total - 1) / 2) * (MM_BASE * 1.6);
                        }
                    }
                }
                var lc = conn.color || '#94a3b8';
                var mid = isEntryConn
                    ? 'arr-sm-' + lc.replace('#', '')
                    : 'arr-' + lc.replace('#', '');
                var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', self._buildPathDWithOffset(ep, isStraight, offset));
                path.setAttribute('fill', 'none'); path.setAttribute('stroke', lc);
                if (isEntryConn) {
                    // entry 級：1px 虛線
                    path.setAttribute('stroke-width', '1');
                    path.setAttribute('stroke-dasharray', '4 3');
                } else {
                    // card 級：2px + registry style
                    path.setAttribute('stroke-width', '2');
                    if (conn.line_style === 'dashed') path.setAttribute('stroke-dasharray', '8 4');
                    else if (conn.line_style === 'dotted') path.setAttribute('stroke-dasharray', '3 3');
                }
                path.setAttribute('marker-end', 'url(#' + mid + ')');
                path.style.pointerEvents = 'stroke'; path.style.cursor = 'pointer';
                var connId = conn.id;
                var connRelType = conn.relation_type || '';
                path.addEventListener('dblclick', function(e) {
                    e.stopPropagation();
                    self.showConnTypeChangeModal(connId, connRelType);
                });
                svg.appendChild(path);
                var labelText = conn.label || (isEntryConn ? '' : (self.relationLabelMap[conn.relation_type] || ''));
                if (labelText) {
                    var tRatio = pairInfo.total > 1 ? (pairInfo.index + 1) / (pairInfo.total + 1) : 0.5;
                    var lx = ep.sx + (ep.tx - ep.sx) * tRatio;
                    var ly = ep.sy + (ep.ty - ep.sy) * tRatio;
                    if (offset !== 0) {
                        var ndx = ep.tx - ep.sx, ndy = ep.ty - ep.sy;
                        var nl = Math.sqrt(ndx * ndx + ndy * ndy) || 1;
                        var curveT = 2 * Math.abs(tRatio - 0.5);
                        var textOffset = offset * (1 - curveT * curveT);
                        lx += (-ndy / nl) * textOffset;
                        ly += (ndx / nl) * textOffset;
                    }
                    var text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                    text.setAttribute('x', lx); text.setAttribute('y', ly - 8);
                    text.setAttribute('text-anchor', 'middle');
                    text.setAttribute('class', 'conn-label conn-label-editable');
                    text.setAttribute('fill', lc); text.style.cursor = 'text';
                    if (isEntryConn) text.setAttribute('font-size', '10');
                    text.textContent = labelText;
                    var cid = conn.id;
                    text.addEventListener('dblclick', function(e) { e.stopPropagation(); self.startEditConnection(cid, e.clientX, e.clientY); });
                    svg.appendChild(text);
                }
            });
        },

        showConnTypeChangeModal(connId, currentType) {
            this.connTypeChangeTarget = connId;
            this.selectedRelationType = currentType || 'references';
            var conn = this.connections.find(function(c) { return c.id === connId; });
            this.connTypeChangeLabel = conn ? (conn.label || '') : '';
            // 若用戶已自訂色（與 registry 預設不同），就把該色帶入色板選中態;否則空(=預設)
            this.connTypeChangeColor = '';
            if (conn && conn.color) {
                var rt = (this.relationTypeList || []).find(function(x) { return x.value === conn.relation_type; });
                if (!rt || rt.color !== conn.color) {
                    this.connTypeChangeColor = conn.color;
                }
            }
            this.showConnTypeModal = true;
        },

        async deleteConnFromModal() {
            if (!this.connTypeChangeTarget) return;
            var connId = this.connTypeChangeTarget;
            // 走 deleteConnection 才會 push undo,然後關 modal
            await this.deleteConnection(connId);
            this.showConnTypeModal = false;
            this.connTypeChangeTarget = null;
            this.connTypeChangeLabel = '';
        },

        async confirmConnTypeChange() {
            if (!this.connTypeChangeTarget) return;
            try {
                var payload = { relation_type: this.selectedRelationType };
                if (this.connTypeChangeLabel !== undefined) payload.label = this.connTypeChangeLabel;
                // color 空字串 = 用 relation_type 預設色（後端會由 registry 帶入）
                if (this.connTypeChangeColor) payload.color = this.connTypeChangeColor;
                var resp = await API.put('/beakbroodnest/api/canvas-connections/' + this.connTypeChangeTarget, payload);
                // 本地更新 connection 屬性 + 同步重繪
                var connId = this.connTypeChangeTarget;
                var newType = this.selectedRelationType;
                var newLabel = this.connTypeChangeLabel;
                for (var i = 0; i < this.connections.length; i++) {
                    if (this.connections[i].id === connId) {
                        this.connections[i].relation_type = newType;
                        this.connections[i].label = newLabel;
                        if (resp && resp.color) this.connections[i].color = resp.color;
                        if (resp && resp.line_style) this.connections[i].line_style = resp.line_style;
                        if (resp && resp.graph_family) this.connections[i].graph_family = resp.graph_family;
                        if (resp && resp.semantic_layer) this.connections[i].semantic_layer = resp.semantic_layer;
                        break;
                    }
                }
                this.showConnTypeModal = false;
                this.connTypeChangeTarget = null;
                this.connTypeChangeLabel = '';
                this.renderConnections();
                this.showToast('已變更為 ' + (this.relationLabelMap[newType] || newType), 'success', 1500);
            } catch (e) {
                this.showToast('變更失敗', 'error');
            }
        },

        _renderGrouped(svg, renderList) {
            var isStraight = (this.rtLineStyle === 'straight');
            var self = this;
            var groups = {};
            var geom = [];
            renderList.forEach(function(conn) {
                var srcEp = self._getConnEndpointObj(conn, 'source');
                var tgtEp = self._getConnEndpointObj(conn, 'target');
                if (!srcEp || !tgtEp) return;
                var ep = self._calcEdgeEndpoints(srcEp, tgtEp);
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
                geom.push({ connId: conn.id, sx: ep.sx, sy: ep.sy, tx: ep.tx, ty: ep.ty, label: lt, color: lc, relType: conn.relation_type || '' });
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
                path.addEventListener('dblclick', function(e) { self._onGroupedLineDblClick(e); });
                svg.appendChild(path);
                if (g.arrowD) {
                    var arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                    arrow.setAttribute('d', g.arrowD); arrow.setAttribute('fill', g.color);
                    arrow.setAttribute('stroke', 'none'); arrow.style.pointerEvents = 'none';
                    svg.appendChild(arrow);
                }
            }
        },

        _findNearestConn(e) {
            var vp = this.$refs.viewport;
            if (!vp) return null;
            var rect = vp.getBoundingClientRect();
            var cx = (e.clientX - rect.left - this.panX) / this.zoom;
            var cy = (e.clientY - rect.top - this.panY) / this.zoom;
            var best = null, bestDist = Infinity;
            for (var i = 0; i < this._connGeometry.length; i++) {
                var g = this._connGeometry[i];
                var d = this._pointToSegmentDist(cx, cy, g.sx, g.sy, g.tx, g.ty);
                if (d < bestDist) { bestDist = d; best = g; }
            }
            if (best && bestDist < 20 / this.zoom) return best;
            return null;
        },

        _onGroupedLineDblClick(e) {
            e.stopPropagation();
            var best = this._findNearestConn(e);
            if (best) {
                this.showConnTypeChangeModal(best.connId, best.relType);
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
