/**
 * BeakNote 白板引擎
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
        selectedRelationType: 'supports',
        relationLabel: '',

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
            { value: 'causes',       label: '因果' },
            { value: 'supports',     label: '支持' },
            { value: 'contradicts',  label: '矛盾' },
            { value: 'derives_from', label: '衍生' },
            { value: 'follows',      label: '順序' },
            { value: 'contains',     label: '包含' },
            { value: 'refutes',      label: '否定' },
            { value: 'blocks',       label: '阻塞' },
        ],

        relationLabelMap: {
            causes: '因果', supports: '支持', contradicts: '矛盾',
            derives_from: '衍生', follows: '順序', contains: '包含',
            refutes: '否定', blocks: '阻塞',
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

                const sx = srcCa.pos_x + sw / 2;
                const sy = srcCa.pos_y + sh / 2;
                const tx = tgtCa.pos_x + tw / 2;
                const ty = tgtCa.pos_y + th / 2;

                const dx = tx - sx;
                const cx1 = sx + dx * 0.4;
                const cx2 = sx + dx * 0.6;

                const lc = conn.color || '#94a3b8';
                const mid = 'arr-' + lc.replace('#', '');

                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', 'M ' + sx + ' ' + sy + ' C ' + cx1 + ' ' + sy + ', ' + cx2 + ' ' + ty + ', ' + tx + ' ' + ty);
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
