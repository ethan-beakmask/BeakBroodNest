/**
 * BeakCortex 白板引擎
 * pan/zoom、原子卡片渲染、拖曳、SVG 連線、atom_type 視覺區分、lifecycle 透明度
 */

function whiteboardApp(canvasId) {
    return {
        canvasId,
        canvas: null,
        atoms: [],
        connections: [],
        canvases: [],
        tags: [],

        // Viewport
        panX: 0, panY: 0, zoom: 1,
        isPanning: false,
        panStartX: 0, panStartY: 0,

        // Drag
        dragCard: null,
        dragStartX: 0, dragStartY: 0,
        cardStartX: 0, cardStartY: 0,

        // Mode
        mode: 'select',
        connSourceAtomId: null,

        // Selection
        selectedAtomId: null,
        showPanel: false,

        // Context menu
        contextMenu: null,

        // Modals
        showNewAtomModal: false,
        showAddExistingModal: false,
        showNewCanvasModal: false,
        showTagModal: false,
        showRelationModal: false,

        // Forms
        newAtom: { title: '', content: '', atom_type: 'F' },
        newAtomPos: { x: 100, y: 100 },
        newCanvasName: '',
        newTagName: '',
        newTagColor: '#6b7280',
        searchQuery: '',
        searchResults: [],
        pendingConnection: null,
        selectedRelationType: 'follows',
        relationLabel: '',

        // Connection drag (from anchors)
        isConnDragging: false,
        connDragSourceAtomId: null,
        connDragSourceAnchor: null,
        connDragHoverAtomId: null,
        connDragMouseX: 0,
        connDragMouseY: 0,

        // Phase 3: Relations & Block Chain
        selectedAtomDetails: null,
        highlightedAtomIds: [],
        blockChain: null,

        // -- Config --
        atomTypeConfig: {
            A: { label: '萬用', bg: '#f3f4f6', color: '#6b7280', border: '#9ca3af' },
            B: { label: '發散', bg: '#fef3c7', color: '#d97706', border: '#f59e0b' },
            C: { label: '流程', bg: '#dbeafe', color: '#2563eb', border: '#3b82f6' },
            D: { label: '歸納', bg: '#dcfce7', color: '#059669', border: '#10b981' },
            E: { label: '套表', bg: '#ede9fe', color: '#7c3aed', border: '#8b5cf6' },
            F: { label: '碎片', bg: '#f3f4f6', color: '#6b7280', border: '#9ca3af' },
        },

        relationTypeList: [
            { value: 'follows',      label: '順序', desc: 'B 在 A 之後',  color: '#3b82f6' },
            { value: 'blocks',       label: '阻塞', desc: 'A 擋住 B',    color: '#dc2626' },
            { value: 'contains',     label: '包含', desc: 'A 包含 B',    color: '#6b7280' },
            { value: 'supports',     label: '支持', desc: 'A 支持 B',    color: '#10b981' },
            { value: 'contradicts',  label: '矛盾', desc: 'A 與 B 互斥', color: '#f59e0b' },
            { value: 'derives_from', label: '衍生', desc: 'B 衍生自 A',  color: '#8b5cf6' },
            { value: 'supersedes',   label: '取代', desc: 'A 取代 B',    color: '#a855f7' },
            { value: 'causes',       label: '因果', desc: 'A 導致 B',    color: '#ef4444' },
            { value: 'enables',      label: '啟用', desc: 'A 使 B 可能', color: '#f97316' },
            { value: 'references',   label: '參考', desc: 'A 參考 B',    color: '#64748b' },
        ],

        relationLabelMap: {
            causes: '因果', enables: '啟用', supports: '支持', contradicts: '矛盾',
            derives_from: '衍生', supersedes: '取代', follows: '順序',
            contains: '包含', references: '參考', blocks: '阻塞',
        },

        // ============================================
        // Init
        // ============================================
        async init() {
            await this.loadData();
            this.$nextTick(() => {
                this.renderConnections();
                this.setupWheelZoom();
                if (this.atoms.length > 0) this.fitView();
            });
            // Cancel connection drag if mouse released outside viewport
            document.addEventListener('mouseup', () => {
                if (this.isConnDragging) this.cancelConnDrag();
            });
        },

        async loadData() {
            const [canvas, canvases, tags] = await Promise.all([
                API.getCanvas(this.canvasId),
                API.getCanvases(),
                API.getTags(),
            ]);
            this.canvas = canvas;
            this.atoms = canvas.atoms || [];
            this.connections = canvas.connections || [];
            this.canvases = canvases;
            this.tags = tags;
            if (canvas.viewport_x || canvas.viewport_y || (canvas.viewport_zoom && canvas.viewport_zoom !== 1)) {
                this.panX = canvas.viewport_x || 0;
                this.panY = canvas.viewport_y || 0;
                this.zoom = canvas.viewport_zoom || 1;
                this.updateTransform();
            }
        },

        // ============================================
        // Pan / Zoom
        // ============================================
        setupWheelZoom() {
            const vp = this.$refs.viewport;
            if (!vp) return;
            vp.addEventListener('wheel', (e) => {
                e.preventDefault();
                const delta = e.deltaY > 0 ? 0.92 : 1.08;
                const newZoom = Math.max(0.15, Math.min(3, this.zoom * delta));
                const rect = vp.getBoundingClientRect();
                const mx = e.clientX - rect.left;
                const my = e.clientY - rect.top;
                this.panX = mx - (mx - this.panX) * (newZoom / this.zoom);
                this.panY = my - (my - this.panY) * (newZoom / this.zoom);
                this.zoom = newZoom;
                this.updateTransform();
                this.renderConnections();
            }, { passive: false });
        },

        onViewportMouseDown(e) {
            // Middle button: always pan
            if (e.button === 1) {
                this.isPanning = true;
                this.panStartX = e.clientX - this.panX;
                this.panStartY = e.clientY - this.panY;
                e.preventDefault();
                return;
            }
            // Connect mode: click on empty space cancels
            if (this.mode === 'connect' && e.button === 0 && !e.target.closest('.wb-card')) {
                this.connSourceAtomId = null;
                this.mode = 'select';
                return;
            }
            // Left button on empty area: pan
            if (e.button === 0
                && !e.target.closest('.wb-card')
                && !e.target.closest('.wb-toolbar')
                && !e.target.closest('.wb-zoom')) {
                this.isPanning = true;
                this.panStartX = e.clientX - this.panX;
                this.panStartY = e.clientY - this.panY;
                e.preventDefault();
            }
        },

        onViewportMouseMove(e) {
            if (this.isConnDragging) {
                this.connDragMouseX = e.clientX;
                this.connDragMouseY = e.clientY;
                this.updatePreviewLine();
                return;
            }
            if (this.isPanning) {
                this.panX = e.clientX - this.panStartX;
                this.panY = e.clientY - this.panStartY;
                this.updateTransform();
                this.renderConnections();
                return;
            }
            if (this.dragCard) {
                const dx = (e.clientX - this.dragStartX) / this.zoom;
                const dy = (e.clientY - this.dragStartY) / this.zoom;
                this.dragCard.pos_x = this.cardStartX + dx;
                this.dragCard.pos_y = this.cardStartY + dy;
                this.renderConnections();
            }
        },

        onViewportMouseUp(e) {
            if (this.isConnDragging) {
                this.endConnDrag();
                return;
            }
            if (this.isPanning) {
                this.isPanning = false;
                this.saveViewport();
            }
            if (this.dragCard) {
                API.updateCanvasAtom(this.dragCard.id, {
                    pos_x: this.dragCard.pos_x,
                    pos_y: this.dragCard.pos_y,
                });
                this.dragCard = null;
            }
        },

        updateTransform() {
            const c = this.$refs.canvas;
            if (c) c.style.transform = `translate(${this.panX}px, ${this.panY}px) scale(${this.zoom})`;
        },

        saveViewport() {
            API.updateCanvas(this.canvasId, {
                viewport_x: this.panX,
                viewport_y: this.panY,
                viewport_zoom: this.zoom,
            });
        },

        zoomIn() {
            this.zoom = Math.min(3, this.zoom * 1.2);
            this.updateTransform(); this.renderConnections();
        },

        zoomOut() {
            this.zoom = Math.max(0.15, this.zoom / 1.2);
            this.updateTransform(); this.renderConnections();
        },

        resetZoom() {
            this.zoom = 1; this.panX = 0; this.panY = 0;
            this.updateTransform(); this.renderConnections(); this.saveViewport();
        },

        fitView() {
            if (this.atoms.length === 0) return;
            const vp = this.$refs.viewport;
            if (!vp) return;
            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            this.atoms.forEach(ca => {
                minX = Math.min(minX, ca.pos_x);
                minY = Math.min(minY, ca.pos_y);
                maxX = Math.max(maxX, ca.pos_x + 260);
                maxY = Math.max(maxY, ca.pos_y + 160);
            });
            const pad = 80;
            const cw = maxX - minX + pad * 2;
            const ch = maxY - minY + pad * 2;
            const rect = vp.getBoundingClientRect();
            this.zoom = Math.min(rect.width / cw, rect.height / ch, 1.2);
            this.panX = (rect.width - cw * this.zoom) / 2 - (minX - pad) * this.zoom;
            this.panY = (rect.height - ch * this.zoom) / 2 - (minY - pad) * this.zoom;
            this.updateTransform(); this.renderConnections(); this.saveViewport();
        },

        get zoomPercent() { return Math.round(this.zoom * 100); },

        screenToCanvas(sx, sy) {
            const vp = this.$refs.viewport;
            const rect = vp.getBoundingClientRect();
            return {
                x: (sx - rect.left - this.panX) / this.zoom,
                y: (sy - rect.top - this.panY) / this.zoom,
            };
        },

        // ============================================
        // Card Operations
        // ============================================
        onCardMouseDown(e, ca) {
            if (e.button !== 0 || this.mode === 'connect') return;
            e.stopPropagation();
            this.selectCard(ca.atom_id);
            this.dragCard = ca;
            this.dragStartX = e.clientX;
            this.dragStartY = e.clientY;
            this.cardStartX = ca.pos_x;
            this.cardStartY = ca.pos_y;
            const maxZ = Math.max(0, ...this.atoms.map(a => a.z_index || 0));
            ca.z_index = maxZ + 1;
        },

        async selectCard(atomId) {
            this.selectedAtomId = atomId;
            this.showPanel = true;
            this.selectedAtomDetails = null;
            this.blockChain = null;
            this.highlightedAtomIds = [];
            try {
                var details = await API.getAtom(atomId);
                if (this.selectedAtomId === atomId) {
                    this.selectedAtomDetails = details;
                }
            } catch (e) {
                console.error('Failed to fetch atom details:', e);
            }
        },

        deselectCard() {
            this.selectedAtomId = null;
            this.showPanel = false;
            this.selectedAtomDetails = null;
            this.blockChain = null;
            this.highlightedAtomIds = [];
        },

        get selectedAtom() {
            return this.atoms.find(ca => ca.atom_id === this.selectedAtomId) || null;
        },

        getCardStyle(ca) {
            const type = ca.atom ? ca.atom.atom_type : 'F';
            const lifecycle = ca.atom ? ca.atom.lifecycle : 'active';
            const cfg = this.atomTypeConfig[type] || this.atomTypeConfig.F;
            const opacity = { active: 1, aging: 0.65, archived: 0.35, terminal: 0.2 }[lifecycle] || 1;
            const border = type === 'F'
                ? '2px dashed ' + cfg.border
                : '2px solid ' + cfg.border;
            return 'left:' + ca.pos_x + 'px; top:' + ca.pos_y + 'px; z-index:' + (ca.z_index || 10) + '; border:' + border + '; opacity:' + opacity + ';';
        },

        getTypeBadgeStyle(type) {
            const cfg = this.atomTypeConfig[type] || this.atomTypeConfig.F;
            return 'background:' + cfg.bg + '; color:' + cfg.color + ';';
        },

        // ============================================
        // New Atom
        // ============================================
        openNewAtomModal(e) {
            this.newAtom = { title: '', content: '', atom_type: 'F' };
            if (e && e.clientX) {
                const pos = this.screenToCanvas(e.clientX, e.clientY);
                this.newAtomPos = { x: pos.x, y: pos.y };
            } else {
                this.newAtomPos = {
                    x: (-this.panX / this.zoom) + 200,
                    y: (-this.panY / this.zoom) + 200,
                };
            }
            this.showNewAtomModal = true;
        },

        async createNewAtom() {
            const atom = await API.createAtom({
                title: this.newAtom.title || '新原子',
                content: this.newAtom.content,
                atom_type: this.newAtom.atom_type,
                source: 'human',
            });
            await API.addAtomToCanvas(this.canvasId, {
                atom_id: atom.id,
                pos_x: this.newAtomPos.x,
                pos_y: this.newAtomPos.y,
            });
            this.showNewAtomModal = false;
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        // ============================================
        // Add Existing Atom
        // ============================================
        async openAddExistingModal() {
            this.searchQuery = '';
            this.searchResults = [];
            this.showAddExistingModal = true;
            await this.doSearch();
        },

        async doSearch() {
            const existingIds = new Set(this.atoms.map(ca => ca.atom_id));
            if (this.searchQuery.trim()) {
                // 有搜尋詞：混合搜尋（語意 + 文字）
                const resp = await API.searchSemantic(this.searchQuery, 20);
                this.searchResults = (resp.items || []).filter(a => !existingIds.has(a.id));
            } else {
                // 無搜尋詞：列出最近原子
                const resp = await API.getAtoms({ per_page: 20 });
                this.searchResults = (resp.items || []).filter(a => !existingIds.has(a.id));
            }
        },

        async addExistingAtom(atomId) {
            await API.addAtomToCanvas(this.canvasId, {
                atom_id: atomId,
                pos_x: (-this.panX / this.zoom) + 200 + Math.random() * 100,
                pos_y: (-this.panY / this.zoom) + 200 + Math.random() * 100,
            });
            this.searchResults = this.searchResults.filter(a => a.id !== atomId);
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        // ============================================
        // Update Atom
        // ============================================
        async updateAtomField(ca, field, value) {
            if (!ca || !ca.atom) return;
            ca.atom[field] = value;
            await API.updateAtom(ca.atom_id, { [field]: value });
            this.$nextTick(() => this.renderConnections());
        },

        // ============================================
        // Remove / Delete
        // ============================================
        async removeFromCanvas(ca) {
            await API.removeCanvasAtom(ca.id);
            if (this.selectedAtomId === ca.atom_id) this.deselectCard();
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        async deleteAtomEntirely(ca) {
            await API.deleteAtom(ca.atom_id);
            if (this.selectedAtomId === ca.atom_id) this.deselectCard();
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        // ============================================
        // Connection Mode
        // ============================================
        toggleConnectMode() {
            this.mode = this.mode === 'connect' ? 'select' : 'connect';
            if (this.mode !== 'connect') this.connSourceAtomId = null;
        },

        onCardClickForConnect(e, ca) {
            if (this.mode !== 'connect') return;
            e.stopPropagation();
            if (!this.connSourceAtomId) {
                this.connSourceAtomId = ca.atom_id;
            } else if (this.connSourceAtomId !== ca.atom_id) {
                this.pendingConnection = {
                    sourceAtomId: this.connSourceAtomId,
                    targetAtomId: ca.atom_id,
                };
                this.selectedRelationType = 'supports';
                this.relationLabel = '';
                this.showRelationModal = true;
                this.connSourceAtomId = null;
            }
        },

        getAtomTitle(atomId) {
            const ca = this.atoms.find(a => a.atom_id === atomId);
            return ca && ca.atom ? ca.atom.title : ('#' + atomId);
        },

        async confirmConnection() {
            if (!this.pendingConnection) return;
            await API.createConnection({
                canvas_id: this.canvasId,
                source_atom_id: this.pendingConnection.sourceAtomId,
                target_atom_id: this.pendingConnection.targetAtomId,
                relation_type: this.selectedRelationType,
                label: this.relationLabel,
            });
            this.showRelationModal = false;
            this.pendingConnection = null;
            this.mode = 'select';
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        async deleteConnection(connId) {
            await API.deleteConnection(connId);
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        // ============================================
        // Connection Drag (from anchors)
        // ============================================
        startConnDrag(e, ca, anchor) {
            this.isConnDragging = true;
            this.connDragSourceAtomId = ca.atom_id;
            this.connDragSourceAnchor = anchor;
            this.connDragHoverAtomId = null;
            this.connDragMouseX = e.clientX;
            this.connDragMouseY = e.clientY;
            this.updatePreviewLine();
        },

        endConnDrag() {
            if (this.connDragHoverAtomId && this.connDragHoverAtomId !== this.connDragSourceAtomId) {
                this.pendingConnection = {
                    sourceAtomId: this.connDragSourceAtomId,
                    targetAtomId: this.connDragHoverAtomId,
                };
                this.selectedRelationType = 'follows';
                this.relationLabel = '';
                this.showRelationModal = true;
            }
            this.isConnDragging = false;
            this.connDragSourceAtomId = null;
            this.connDragSourceAnchor = null;
            this.connDragHoverAtomId = null;
            this.clearPreviewLine();
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
                tgt.x = snap.x;
                tgt.y = snap.y;
            }

            var dx = tgt.x - src.x;
            var cx1 = src.x + dx * 0.4;
            var cx2 = src.x + dx * 0.6;

            line.setAttribute('d',
                'M ' + src.x + ' ' + src.y +
                ' C ' + cx1 + ' ' + src.y +
                ', ' + cx2 + ' ' + tgt.y +
                ', ' + tgt.x + ' ' + tgt.y);
            line.style.display = '';
        },

        clearPreviewLine() {
            var line = this.$refs.previewLine;
            if (line) {
                line.setAttribute('d', '');
                line.style.display = 'none';
            }
        },

        onCardMouseEnterForConn(ca) {
            if (this.isConnDragging && ca.atom_id !== this.connDragSourceAtomId) {
                this.connDragHoverAtomId = ca.atom_id;
            }
        },

        onCardMouseLeaveForConn(ca) {
            if (this.connDragHoverAtomId === ca.atom_id) {
                this.connDragHoverAtomId = null;
            }
        },

        // ============================================
        // Render Connections (SVG)
        // ============================================
        renderConnections() {
            const svg = this.$refs.connSvg;
            if (!svg) return;
            svg.innerHTML = '';

            // Arrow markers
            const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
            const usedColors = new Set();
            this.connections.forEach(c => usedColors.add(c.color || '#94a3b8'));
            usedColors.forEach(color => {
                const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
                const mid = 'arr-' + color.replace('#', '');
                marker.setAttribute('id', mid);
                marker.setAttribute('viewBox', '0 0 10 10');
                marker.setAttribute('refX', '9');
                marker.setAttribute('refY', '5');
                marker.setAttribute('markerWidth', '6');
                marker.setAttribute('markerHeight', '6');
                marker.setAttribute('orient', 'auto-start-reverse');
                const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                p.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
                p.setAttribute('fill', color);
                marker.appendChild(p);
                defs.appendChild(marker);
            });
            svg.appendChild(defs);

            const self = this;
            this.connections.forEach(conn => {
                const srcCa = self.atoms.find(ca => ca.atom_id === conn.source_atom_id);
                const tgtCa = self.atoms.find(ca => ca.atom_id === conn.target_atom_id);
                if (!srcCa || !tgtCa) return;

                const srcEl = document.getElementById('card-' + srcCa.atom_id);
                const tgtEl = document.getElementById('card-' + tgtCa.atom_id);
                const sw = srcEl ? srcEl.offsetWidth : 260;
                const sh = srcEl ? srcEl.offsetHeight : 120;
                const tw = tgtEl ? tgtEl.offsetWidth : 260;
                const th = tgtEl ? tgtEl.offsetHeight : 120;

                // Edge-to-edge: line starts/ends at card border, not center
                var scx = srcCa.pos_x + sw / 2;
                var scy = srcCa.pos_y + sh / 2;
                var tcx = tgtCa.pos_x + tw / 2;
                var tcy = tgtCa.pos_y + th / 2;
                var ddx = tcx - scx;
                var ddy = tcy - scy;
                var sx, sy, tx, ty, cx1, cy1, cx2, cy2;

                if (Math.abs(ddx) > Math.abs(ddy)) {
                    // Horizontal arrangement
                    if (ddx > 0) {
                        sx = srcCa.pos_x + sw; sy = scy;
                        tx = tgtCa.pos_x;      ty = tcy;
                    } else {
                        sx = srcCa.pos_x;       sy = scy;
                        tx = tgtCa.pos_x + tw;  ty = tcy;
                    }
                    var gx = Math.max(Math.abs(tx - sx) * 0.4, 20);
                    cx1 = sx + (ddx > 0 ? gx : -gx); cy1 = sy;
                    cx2 = tx + (ddx > 0 ? -gx : gx); cy2 = ty;
                } else {
                    // Vertical arrangement
                    if (ddy > 0) {
                        sx = scx; sy = srcCa.pos_y + sh;
                        tx = tcx; ty = tgtCa.pos_y;
                    } else {
                        sx = scx; sy = srcCa.pos_y;
                        tx = tcx; ty = tgtCa.pos_y + th;
                    }
                    var gy = Math.max(Math.abs(ty - sy) * 0.4, 20);
                    cx1 = sx; cy1 = sy + (ddy > 0 ? gy : -gy);
                    cx2 = tx; cy2 = ty + (ddy > 0 ? -gy : gy);
                }

                const lc = conn.color || '#94a3b8';
                const mid = 'arr-' + lc.replace('#', '');

                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', 'M ' + sx + ' ' + sy + ' C ' + cx1 + ' ' + cy1 + ', ' + cx2 + ' ' + cy2 + ', ' + tx + ' ' + ty);
                path.setAttribute('fill', 'none');
                path.setAttribute('stroke', lc);
                path.setAttribute('stroke-width', '2');
                path.setAttribute('marker-end', 'url(#' + mid + ')');

                if (conn.line_style === 'dashed') path.setAttribute('stroke-dasharray', '8 4');
                else if (conn.line_style === 'dotted') path.setAttribute('stroke-dasharray', '3 3');

                path.style.pointerEvents = 'stroke';
                path.style.cursor = 'pointer';
                const connId = conn.id;
                path.addEventListener('click', function() {
                    if (confirm('刪除此連線?')) self.deleteConnection(connId);
                });
                svg.appendChild(path);

                // Label
                const labelText = conn.label || self.relationLabelMap[conn.relation_type] || '';
                if (labelText) {
                    const mx = (sx + tx) / 2;
                    const my = (sy + ty) / 2;
                    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                    text.setAttribute('x', mx);
                    text.setAttribute('y', my - 8);
                    text.setAttribute('text-anchor', 'middle');
                    text.setAttribute('class', 'conn-label');
                    text.setAttribute('fill', lc);
                    text.textContent = labelText;
                    svg.appendChild(text);
                }
            });
        },

        // ============================================
        // Tags
        // ============================================
        getTagStyle(color) {
            return 'background:' + color + '20; color:' + color + '; border:1px solid ' + color + '40;';
        },

        atomHasTag(ca, tagId) {
            return ca && ca.atom && ca.atom.tags && ca.atom.tags.some(function(t) { return t.id === tagId; });
        },

        async toggleAtomTag(ca, tagId) {
            if (!ca || !ca.atom) return;
            const cur = (ca.atom.tags || []).map(function(t) { return t.id; });
            const newIds = cur.includes(tagId)
                ? cur.filter(function(id) { return id !== tagId; })
                : cur.concat([tagId]);
            await API.updateAtom(ca.atom_id, { tag_ids: newIds });
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        async createTag() {
            if (!this.newTagName.trim()) return;
            await API.createTag({ name: this.newTagName.trim(), color: this.newTagColor });
            this.tags = await API.getTags();
            this.newTagName = '';
        },

        async deleteTag(tagId) {
            await API.deleteTag(tagId);
            this.tags = await API.getTags();
        },

        // ============================================
        // Canvas Management
        // ============================================
        async createCanvas() {
            if (!this.newCanvasName.trim()) return;
            const c = await API.createCanvas({ name: this.newCanvasName.trim() });
            window.location.href = '/canvas/' + c.id;
        },

        async deleteCanvas(id) {
            if (this.canvases.length <= 1) return;
            await API.deleteCanvas(id);
            if (id === this.canvasId) {
                window.location.href = '/';
            } else {
                this.canvases = await API.getCanvases();
            }
        },

        // ============================================
        // Context Menu
        // ============================================
        onCanvasContextMenu(e) {
            e.preventDefault();
            this.contextMenu = { x: e.clientX, y: e.clientY, type: 'canvas' };
        },

        onCardContextMenu(e, ca) {
            e.preventDefault();
            e.stopPropagation();
            this.contextMenu = { x: e.clientX, y: e.clientY, type: 'card', ca: ca };
        },

        closeContextMenu() { this.contextMenu = null; },

        contextAddAtom() {
            this.openNewAtomModal({ clientX: this.contextMenu.x, clientY: this.contextMenu.y });
            this.closeContextMenu();
        },

        // ============================================
        // Phase 3: Block Chain & Navigation
        // ============================================
        async traceBlockChain(atomId) {
            try {
                var result = await API.getBlockChain(atomId);
                this.blockChain = result;
                this.highlightedAtomIds = (result.chain || []).map(function(n) { return n.atom_id; });
            } catch (e) {
                console.error('Failed to trace block chain:', e);
            }
        },

        navigateToAtom(atomId) {
            var ca = this.atoms.find(function(a) { return a.atom_id === atomId; });
            if (!ca) return;
            this.selectCard(atomId);
            var vp = this.$refs.viewport;
            if (vp) {
                var rect = vp.getBoundingClientRect();
                this.panX = rect.width / 2 - (ca.pos_x + 130) * this.zoom;
                this.panY = rect.height / 2 - (ca.pos_y + 80) * this.zoom;
                this.updateTransform();
                this.renderConnections();
                this.saveViewport();
            }
        },

        isAtomOnCanvas(atomId) {
            return this.atoms.some(function(ca) { return ca.atom_id === atomId; });
        },

        // ============================================
        // Utilities
        // ============================================
        truncate(text, n) {
            if (!text) return '';
            return text.length > n ? text.substring(0, n) + '...' : text;
        },

        formatDate(iso) {
            if (!iso) return '';
            return new Date(iso).toLocaleString('zh-TW');
        },
    };
}
