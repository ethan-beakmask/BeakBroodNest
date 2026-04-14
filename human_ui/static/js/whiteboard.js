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
        groups: [],
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

        // Resize
        resizeCard: null,
        resizeStartX: 0, resizeStartY: 0,
        resizeStartW: 0, resizeStartH: 0,

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

        // Inline edit
        editingAtomId: null,
        editContent: '',
        bodyDragPending: false,
        bodyDragStartX: 0,
        bodyDragStartY: 0,
        bodyDragCa: null,

        // Right-click pan
        rightDragPending: false,
        rightDragStartX: 0, rightDragStartY: 0,
        rightDragTarget: null,

        // Box selection
        isBoxSelecting: false,
        boxSelectPending: false,
        boxSelectStartX: 0, boxSelectStartY: 0,
        boxSelectCurrentX: 0, boxSelectCurrentY: 0,
        selectedAtomIds: [],

        // Multi-drag
        multiDragStarts: null,
        _justDragged: false,

        // Groups
        dragGroup: null,
        groupDragStartX: 0, groupDragStartY: 0,
        groupDragStartPos: null,
        groupDragMemberStarts: null,
        resizeGroup: null,
        resizeGroupStartX: 0, resizeGroupStartY: 0,
        resizeGroupStartW: 0, resizeGroupStartH: 0,
        showGroupModal: false,
        editingGroup: null,
        groupForm: { name: '', color: '#3b82f6' },

        // Toast
        toasts: [],
        _toastSeq: 0,

        // Render test panel
        renderMode: 'normal',   // kept for URL default
        renderStats: { total: 0, rendered: 0 },
        rtLineStyle: 'curve',   // 'curve' | 'straight' | 'none'
        rtEngine: 'grouped', // 'individual' | 'grouped'
        rtOptEnabled: false,
        rtOptPerSector: 10,
        rtPanelOpen: false,

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
            // Read render mode from URL query param
            var urlParams = new URLSearchParams(window.location.search);
            var rm = urlParams.get('render');
            if (rm === 'straight' || rm === 'optimized' || rm === 'opt-straight') this.renderMode = rm;
            // Sync panel state from URL default
            if (rm === 'straight')      { this.rtLineStyle = 'straight'; }
            if (rm === 'optimized')     { this.rtOptEnabled = true; }
            if (rm === 'opt-straight')  { this.rtLineStyle = 'straight'; this.rtOptEnabled = true; }

            this.initMarked();
            await this.loadData();
            this.$nextTick(() => {
                this.renderConnections();
                this.setupWheelZoom();
                if (this.atoms.length > 0) this.fitView();
                this.renderMinimap();
            });
            // Cancel connection drag if mouse released outside viewport
            document.addEventListener('mouseup', () => {
                if (this.isConnDragging) this.cancelConnDrag();
            });
            // Capture-phase: catch right-click before card/group handlers stop propagation
            const self = this;
            this.$refs.viewport.addEventListener('mousedown', function(e) {
                if (e.button === 2) {
                    self.rightDragPending = true;
                    self.rightDragStartX = e.clientX;
                    self.rightDragStartY = e.clientY;
                    var cardEl = e.target.closest('.wb-card');
                    var groupEl = e.target.closest('.wb-group');
                    if (cardEl) {
                        var atomId = parseInt(cardEl.id.replace('card-', ''), 10);
                        self.rightDragTarget = self.atoms.find(function(a) { return a.atom_id === atomId; }) || null;
                    } else if (groupEl) {
                        var gid = parseInt(groupEl.id.replace('group-', ''), 10);
                        var grp = self.groups.find(function(g) { return g.id === gid; });
                        self.rightDragTarget = grp ? { _isGroup: true, group: grp } : null;
                    } else {
                        self.rightDragTarget = null;
                    }
                    e.preventDefault();
                }
            }, true);
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
            this.groups = canvas.groups || [];
            this.canvases = canvases;
            this.tags = tags;
            if (canvas.viewport_x || canvas.viewport_y || (canvas.viewport_zoom && canvas.viewport_zoom !== 1)) {
                this.panX = canvas.viewport_x || 0;
                this.panY = canvas.viewport_y || 0;
                this.zoom = canvas.viewport_zoom || 1;
                this.updateTransform();
            }
            this.$nextTick(() => this.renderMinimap());
        },

        // ============================================
        // Pan / Zoom
        // ============================================
        setupWheelZoom() {
            const vp = this.$refs.viewport;
            if (!vp) return;
            vp.addEventListener('wheel', (e) => {
                if (this.editingAtomId) return;
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
            // End inline edit on any viewport click
            if (this.editingAtomId && document.activeElement) {
                document.activeElement.blur();
            }
            // Middle button: always pan
            if (e.button === 1) {
                this.isPanning = true;
                this.panStartX = e.clientX - this.panX;
                this.panStartY = e.clientY - this.panY;
                e.preventDefault();
                return;
            }
            // Right button handled by capture-phase listener
            if (e.button === 2) return;
            // Left button
            if (e.button === 0) {
                // Connect mode: click on empty space cancels
                if (this.mode === 'connect' && !e.target.closest('.wb-card')) {
                    this.connSourceAtomId = null;
                    this.mode = 'select';
                    return;
                }
                // Left button on empty area: box selection
                if (!e.target.closest('.wb-card')
                    && !e.target.closest('.wb-group')
                    && !e.target.closest('.wb-toolbar')
                    && !e.target.closest('.wb-zoom')) {
                    this.boxSelectPending = true;
                    this.boxSelectStartX = e.clientX;
                    this.boxSelectStartY = e.clientY;
                    this.boxSelectCurrentX = e.clientX;
                    this.boxSelectCurrentY = e.clientY;
                    e.preventDefault();
                }
            }
        },

        onViewportMouseMove(e) {
            if (this.isConnDragging) {
                this.connDragMouseX = e.clientX;
                this.connDragMouseY = e.clientY;
                this.updatePreviewLine();
                return;
            }
            // Right-click drag -> pan
            if (this.rightDragPending) {
                var rdx = Math.abs(e.clientX - this.rightDragStartX);
                var rdy = Math.abs(e.clientY - this.rightDragStartY);
                if (rdx > 5 || rdy > 5) {
                    this.rightDragPending = false;
                    this.isPanning = true;
                    this.panStartX = this.rightDragStartX - this.panX;
                    this.panStartY = this.rightDragStartY - this.panY;
                }
            }
            if (this.isPanning) {
                this.panX = e.clientX - this.panStartX;
                this.panY = e.clientY - this.panStartY;
                this.updateTransform();
                this.renderConnections();
                return;
            }
            // Box selection
            if (this.boxSelectPending) {
                var bsdx = Math.abs(e.clientX - this.boxSelectStartX);
                var bsdy = Math.abs(e.clientY - this.boxSelectStartY);
                if (bsdx > 5 || bsdy > 5) {
                    this.boxSelectPending = false;
                    this.isBoxSelecting = true;
                }
            }
            if (this.isBoxSelecting) {
                this.boxSelectCurrentX = e.clientX;
                this.boxSelectCurrentY = e.clientY;
                this.updateBoxSelection();
                return;
            }
            if (this.bodyDragPending) {
                var bdx = Math.abs(e.clientX - this.bodyDragStartX);
                var bdy = Math.abs(e.clientY - this.bodyDragStartY);
                if (bdx > 5 || bdy > 5) {
                    this.bodyDragPending = false;
                    var ca = this.bodyDragCa;
                    this.bodyDragCa = null;
                    this.startCardDrag(e, ca, this.bodyDragStartX, this.bodyDragStartY);
                }
            }
            if (this.dragGroup) {
                var gdx = (e.clientX - this.groupDragStartX) / this.zoom;
                var gdy = (e.clientY - this.groupDragStartY) / this.zoom;
                this.dragGroup.pos_x = this.groupDragStartPos.x + gdx;
                this.dragGroup.pos_y = this.groupDragStartPos.y + gdy;
                var self = this;
                this.atoms.forEach(function(a) {
                    if (self.groupDragMemberStarts[a.atom_id]) {
                        a.pos_x = self.groupDragMemberStarts[a.atom_id].x + gdx;
                        a.pos_y = self.groupDragMemberStarts[a.atom_id].y + gdy;
                    }
                });
                this.renderConnections();
                return;
            }
            if (this.resizeGroup) {
                var grw = (e.clientX - this.resizeGroupStartX) / this.zoom;
                var grh = (e.clientY - this.resizeGroupStartY) / this.zoom;
                this.resizeGroup.width = Math.max(160, this.resizeGroupStartW + grw);
                this.resizeGroup.height = Math.max(80, this.resizeGroupStartH + grh);
                return;
            }
            if (this.resizeCard) {
                var dw = (e.clientX - this.resizeStartX) / this.zoom;
                var dh = (e.clientY - this.resizeStartY) / this.zoom;
                this.resizeCard.width = Math.max(160, this.resizeStartW + dw);
                this.resizeCard.height = Math.max(80, this.resizeStartH + dh);
                if (this.resizeCard.group_id) this.recalcGroupBounds(this.resizeCard.group_id);
                this.renderConnections();
                return;
            }
            if (this.dragCard) {
                var dx = (e.clientX - this.dragStartX) / this.zoom;
                var dy = (e.clientY - this.dragStartY) / this.zoom;
                var affectedGroups = new Set();
                if (this.multiDragStarts) {
                    var self = this;
                    this.atoms.forEach(function(a) {
                        if (self.multiDragStarts[a.atom_id]) {
                            a.pos_x = self.multiDragStarts[a.atom_id].x + dx;
                            a.pos_y = self.multiDragStarts[a.atom_id].y + dy;
                            if (a.group_id) affectedGroups.add(a.group_id);
                        }
                    });
                } else {
                    this.dragCard.pos_x = this.cardStartX + dx;
                    this.dragCard.pos_y = this.cardStartY + dy;
                    if (this.dragCard.group_id) affectedGroups.add(this.dragCard.group_id);
                }
                var self2 = this;
                affectedGroups.forEach(function(gid) { self2.recalcGroupBounds(gid); });
                this.renderConnections();
            }
        },

        onViewportMouseUp(e) {
            // Right-click release: context menu or end pan
            if (this.rightDragPending) {
                this.rightDragPending = false;
                // Didn't pan -> context menu
                var tgt = this.rightDragTarget;
                this.rightDragTarget = null;
                if (tgt && tgt._isGroup) {
                    this.contextMenu = { x: e.clientX, y: e.clientY, type: 'group', group: tgt.group };
                } else if (tgt) {
                    this.contextMenu = { x: e.clientX, y: e.clientY, type: 'card', ca: tgt };
                } else {
                    this.contextMenu = { x: e.clientX, y: e.clientY, type: 'canvas' };
                }
                return;
            }
            // Box selection end
            if (this.isBoxSelecting) {
                this.isBoxSelecting = false;
                this.boxSelectPending = false;
                return;
            }
            if (this.boxSelectPending) {
                // Click on empty without drag -> deselect all
                this.boxSelectPending = false;
                this.selectedAtomIds = [];
                this.deselectCard();
                return;
            }
            if (this.bodyDragPending) {
                this.bodyDragPending = false;
                var ca = this.bodyDragCa;
                this.bodyDragCa = null;
                if (ca) {
                    this.selectCard(ca.atom_id);
                    this.startInlineEdit(ca);
                }
                return;
            }
            if (this.isConnDragging) {
                this.endConnDrag();
                return;
            }
            if (this.isPanning) {
                this.isPanning = false;
                this.saveViewport();
            }
            if (this.dragGroup) {
                API.updateGroup(this.dragGroup.id, {
                    pos_x: this.dragGroup.pos_x,
                    pos_y: this.dragGroup.pos_y,
                });
                var self = this;
                this.atoms.forEach(function(a) {
                    if (self.groupDragMemberStarts && self.groupDragMemberStarts[a.atom_id]) {
                        API.updateCanvasAtom(a.id, { pos_x: a.pos_x, pos_y: a.pos_y });
                    }
                });
                this.dragGroup = null;
                this.groupDragMemberStarts = null;
            }
            if (this.resizeGroup) {
                API.updateGroup(this.resizeGroup.id, {
                    width: this.resizeGroup.width,
                    height: this.resizeGroup.height,
                });
                this.resizeGroup = null;
            }
            if (this.resizeCard) {
                API.updateCanvasAtom(this.resizeCard.id, {
                    width: this.resizeCard.width,
                    height: this.resizeCard.height,
                });
                if (this.resizeCard.group_id) this.autoResizeGroup(this.resizeCard.group_id);
                this.resizeCard = null;
            }
            if (this.dragCard) {
                this._justDragged = true;
                var groupsToResize = new Set();
                if (this.multiDragStarts) {
                    var self = this;
                    this.atoms.forEach(function(a) {
                        if (self.multiDragStarts[a.atom_id]) {
                            API.updateCanvasAtom(a.id, { pos_x: a.pos_x, pos_y: a.pos_y });
                            if (a.group_id) groupsToResize.add(a.group_id);
                        }
                    });
                    this.multiDragStarts = null;
                } else {
                    API.updateCanvasAtom(this.dragCard.id, {
                        pos_x: this.dragCard.pos_x,
                        pos_y: this.dragCard.pos_y,
                    });
                    if (this.dragCard.group_id) groupsToResize.add(this.dragCard.group_id);
                }
                var self2 = this;
                groupsToResize.forEach(function(gid) { self2.autoResizeGroup(gid); });
                this.dragCard = null;
            }
        },

        updateTransform() {
            const c = this.$refs.canvas;
            if (c) c.style.transform = `translate(${this.panX}px, ${this.panY}px) scale(${this.zoom})`;
            this.renderMinimap();
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
                maxX = Math.max(maxX, ca.pos_x + (ca.width || 260));
                maxY = Math.max(maxY, ca.pos_y + (ca.height || 160));
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
            this.startCardDrag(e, ca, e.clientX, e.clientY);
        },

        startCardDrag(e, ca, startX, startY) {
            if (this.selectedAtomIds.includes(ca.atom_id) && this.selectedAtomIds.length > 1) {
                // Multi-drag
                this.dragCard = ca;
                this.dragStartX = startX;
                this.dragStartY = startY;
                this.multiDragStarts = {};
                var self = this;
                this.atoms.forEach(function(a) {
                    if (self.selectedAtomIds.includes(a.atom_id)) {
                        self.multiDragStarts[a.atom_id] = { x: a.pos_x, y: a.pos_y };
                    }
                });
            } else {
                // Single drag
                this.selectedAtomIds = [];
                this.selectCard(ca.atom_id);
                this.dragCard = ca;
                this.dragStartX = startX;
                this.dragStartY = startY;
                this.cardStartX = ca.pos_x;
                this.cardStartY = ca.pos_y;
            }
            var maxZ = Math.max(0, ...this.atoms.map(function(a) { return a.z_index || 0; }));
            ca.z_index = maxZ + 1;
        },

        // Body: click-to-edit, drag-to-move
        onCardBodyMouseDown(e, ca) {
            if (e.button !== 0 || this.mode === 'connect') return;
            if (this.editingAtomId === ca.atom_id) return;
            e.stopPropagation();
            this.bodyDragPending = true;
            this.bodyDragStartX = e.clientX;
            this.bodyDragStartY = e.clientY;
            this.bodyDragCa = ca;
        },

        startInlineEdit(ca) {
            if (!ca || !ca.atom) return;
            this.editingAtomId = ca.atom_id;
            this.editContent = ca.atom.content || '';
            this.$nextTick(() => {
                const el = document.getElementById('edit-' + ca.atom_id);
                if (el) el.focus();
            });
        },

        async finishInlineEdit(ca) {
            if (!ca || !ca.atom || this.editingAtomId !== ca.atom_id) return;
            const newContent = this.editContent;
            this.editingAtomId = null;
            if (newContent !== (ca.atom.content || '')) {
                ca.atom.content = newContent;
                await API.updateAtom(ca.atom_id, { content: newContent });
            }
        },

        cancelInlineEdit() {
            this.editingAtomId = null;
            this.editContent = '';
        },

        // Resize
        onResizeMouseDown(e, ca) {
            if (e.button !== 0) return;
            e.stopPropagation();
            e.preventDefault();
            this.resizeCard = ca;
            this.resizeStartX = e.clientX;
            this.resizeStartY = e.clientY;
            const el = document.getElementById('card-' + ca.atom_id);
            this.resizeStartW = el ? el.offsetWidth : (ca.width || 260);
            this.resizeStartH = el ? el.offsetHeight : (ca.height || 120);
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

        onCardClick(ca) {
            if (this._justDragged) {
                this._justDragged = false;
                return;
            }
            this.selectedAtomIds = [];
            this.selectCard(ca.atom_id);
        },

        // Box selection
        get boxSelectStyle() {
            if (!this.isBoxSelecting) return 'display:none;';
            var vp = this.$refs.viewport;
            if (!vp) return 'display:none;';
            var rect = vp.getBoundingClientRect();
            var x1 = this.boxSelectStartX - rect.left;
            var y1 = this.boxSelectStartY - rect.top;
            var x2 = this.boxSelectCurrentX - rect.left;
            var y2 = this.boxSelectCurrentY - rect.top;
            return 'left:' + Math.min(x1, x2) + 'px; top:' + Math.min(y1, y2) + 'px; width:' + Math.abs(x2 - x1) + 'px; height:' + Math.abs(y2 - y1) + 'px;';
        },

        updateBoxSelection() {
            var start = this.screenToCanvas(this.boxSelectStartX, this.boxSelectStartY);
            var end = this.screenToCanvas(this.boxSelectCurrentX, this.boxSelectCurrentY);
            var left = Math.min(start.x, end.x);
            var top = Math.min(start.y, end.y);
            var right = Math.max(start.x, end.x);
            var bottom = Math.max(start.y, end.y);
            this.selectedAtomIds = this.atoms
                .filter(function(ca) {
                    var w = ca.width || 260;
                    var h = ca.height || 120;
                    return ca.pos_x + w > left && ca.pos_x < right
                        && ca.pos_y + h > top && ca.pos_y < bottom;
                })
                .map(function(ca) { return ca.atom_id; });
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
            var s = 'left:' + ca.pos_x + 'px; top:' + ca.pos_y + 'px; z-index:' + (ca.z_index || 10) + '; border:' + border + '; opacity:' + opacity + ';';
            if (ca.width) s += ' width:' + ca.width + 'px;';
            if (ca.height) s += ' height:' + ca.height + 'px;';
            return s;
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
            this.renderConnections();
        },

        async deleteConnection(connId) {
            var result = await API.deleteConnection(connId);
            await this.loadData();
            this.renderConnections();
            if (result && result.relation_kept) {
                this.showToast(result.relation_kept_reason || '底層知識關係仍被其他白板引用，BLOCKED 標章保留', 'warn', 5000);
            }
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

        // Calculate edge endpoints for a connection (edge-to-edge, not center)
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

        // Build SVG path 'd' attribute: bezier or straight
        _buildPathD(ep, straight) {
            if (straight) {
                return 'M ' + ep.sx + ' ' + ep.sy + ' L ' + ep.tx + ' ' + ep.ty;
            }
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

        // Get current viewport bounds in canvas coordinates
        _getViewportBounds() {
            var vp = this.$refs.viewport;
            if (!vp) return null;
            var rect = vp.getBoundingClientRect();
            var left = -this.panX / this.zoom;
            var top = -this.panY / this.zoom;
            var right = left + rect.width / this.zoom;
            var bottom = top + rect.height / this.zoom;
            return { left: left, top: top, right: right, bottom: bottom,
                     cx: (left + right) / 2, cy: (top + bottom) / 2 };
        },

        // Check if a card is inside viewport bounds
        _isInViewport(ca, vb) {
            var w = ca.width || 260, h = ca.height || 120;
            return ca.pos_x + w > vb.left && ca.pos_x < vb.right &&
                   ca.pos_y + h > vb.top  && ca.pos_y < vb.bottom;
        },

        // Filter connections for optimized mode (8-direction, max 10 per sector)
        _filterOptimizedConnections() {
            var vb = this._getViewportBounds();
            if (!vb) return this.connections;

            var self = this;
            var atomMap = {};
            this.atoms.forEach(function(ca) { atomMap[ca.atom_id] = ca; });

            // Count nodes outside viewport
            var outsideCount = 0;
            this.atoms.forEach(function(ca) {
                if (!self._isInViewport(ca, vb)) outsideCount++;
            });

            // Threshold not met: render all
            if (outsideCount <= 100) return this.connections;

            // Separate: both-endpoints-in-viewport vs at-least-one-outside
            var insideConns = [];
            var outsideConns = [];
            this.connections.forEach(function(conn) {
                var src = atomMap[conn.source_atom_id];
                var tgt = atomMap[conn.target_atom_id];
                if (!src || !tgt) return;
                var srcIn = self._isInViewport(src, vb);
                var tgtIn = self._isInViewport(tgt, vb);
                if (srcIn && tgtIn) {
                    insideConns.push(conn);
                } else {
                    // midpoint of the two card centers for direction calc
                    var sw = src.width || 260, sh = src.height || 120;
                    var tw = tgt.width || 260, th = tgt.height || 120;
                    var mx = ((src.pos_x + sw / 2) + (tgt.pos_x + tw / 2)) / 2;
                    var my = ((src.pos_y + sh / 2) + (tgt.pos_y + th / 2)) / 2;
                    var dx = mx - vb.cx, dy = my - vb.cy;
                    var dist = Math.sqrt(dx * dx + dy * dy);
                    // angle -> sector 0-7 (N=0, NE=1, E=2, SE=3, S=4, SW=5, W=6, NW=7)
                    var angle = Math.atan2(dy, dx); // -PI..PI, 0=right
                    // Rotate so 0=North: subtract PI/2, then normalize
                    var a = angle + Math.PI / 2;
                    if (a < 0) a += 2 * Math.PI;
                    var sector = Math.floor(a / (Math.PI / 4)) % 8;
                    outsideConns.push({ conn: conn, sector: sector, dist: dist });
                }
            });

            // Per-sector: sort by distance ascending, take top N
            var perSector = this.rtOptPerSector || 10;
            var sectors = [[], [], [], [], [], [], [], []];
            outsideConns.forEach(function(item) { sectors[item.sector].push(item); });
            var kept = [];
            for (var s = 0; s < 8; s++) {
                sectors[s].sort(function(a, b) { return a.dist - b.dist; });
                for (var i = 0; i < Math.min(perSector, sectors[s].length); i++) {
                    kept.push(sectors[s][i].conn);
                }
            }

            return insideConns.concat(kept);
        },

        // Called by panel controls
        applyRenderSettings() {
            this.renderConnections();
        },

        // Store connection geometry for hit testing (grouped mode)
        _connGeometry: [],

        renderConnections() {
            var svg = this.$refs.connSvg;
            if (!svg) return;
            svg.innerHTML = '';
            this._connGeometry = [];

            // 'none' = hide all edges
            if (this.rtLineStyle === 'none') {
                this.renderStats = { total: this.connections.length, rendered: 0 };
                return;
            }

            // Determine which connections to render
            var renderList = this.rtOptEnabled
                ? this._filterOptimizedConnections()
                : this.connections;

            this.renderStats = { total: this.connections.length, rendered: renderList.length };

            if (this.rtEngine === 'grouped') {
                this._renderGrouped(svg, renderList);
            } else {
                this._renderIndividual(svg, renderList);
            }
        },

        _renderIndividual(svg, renderList) {
            var isStraight = (this.rtLineStyle === 'straight');

            // Arrow markers
            var defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
            var usedColors = new Set();
            this.connections.forEach(function(c) { usedColors.add(c.color || '#94a3b8'); });
            usedColors.forEach(function(color) {
                var marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
                var mid = 'arr-' + color.replace('#', '');
                marker.setAttribute('id', mid);
                marker.setAttribute('viewBox', '0 0 10 10');
                marker.setAttribute('refX', '9');
                marker.setAttribute('refY', '5');
                marker.setAttribute('markerWidth', '6');
                marker.setAttribute('markerHeight', '6');
                marker.setAttribute('orient', 'auto-start-reverse');
                var p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                p.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
                p.setAttribute('fill', color);
                marker.appendChild(p);
                defs.appendChild(marker);
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
                var lc = conn.color || '#94a3b8';
                var mid = 'arr-' + lc.replace('#', '');

                var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', self._buildPathD(ep, isStraight));
                path.setAttribute('fill', 'none');
                path.setAttribute('stroke', lc);
                path.setAttribute('stroke-width', '2');
                path.setAttribute('marker-end', 'url(#' + mid + ')');

                if (conn.line_style === 'dashed') path.setAttribute('stroke-dasharray', '8 4');
                else if (conn.line_style === 'dotted') path.setAttribute('stroke-dasharray', '3 3');

                path.style.pointerEvents = 'stroke';
                path.style.cursor = 'pointer';
                var connId = conn.id;
                path.addEventListener('click', function() {
                    if (confirm('刪除此連線?')) self.deleteConnection(connId);
                });
                svg.appendChild(path);

                // Label
                var labelText = conn.label || self.relationLabelMap[conn.relation_type] || '';
                if (labelText) {
                    var mx = (ep.sx + ep.tx) / 2;
                    var my = (ep.sy + ep.ty) / 2;
                    var text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
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

        _renderGrouped(svg, renderList) {
            var isStraight = (this.rtLineStyle === 'straight');
            var self = this;
            var atomMap = {};
            this.atoms.forEach(function(ca) { atomMap[ca.atom_id] = ca; });

            // Group by (color + line_style) -> combined path 'd' + arrow triangles
            var groups = {};   // key -> { d: '', arrowD: '', color, dasharray }
            var geom = [];     // for hit testing

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
                    if (ls === 'dashed') da = '8 4';
                    else if (ls === 'dotted') da = '3 3';
                    groups[key] = { d: '', arrowD: '', color: lc, dasharray: da };
                }

                // Append line segment to combined path
                groups[key].d += self._buildPathD(ep, isStraight) + ' ';

                // Build arrowhead triangle at target end
                var adx = ep.tx - ep.sx, ady = ep.ty - ep.sy;
                var len = Math.sqrt(adx * adx + ady * ady);
                if (len > 0) {
                    var ux = adx / len, uy = ady / len;  // unit vector along line
                    var px = -uy, py = ux;                // perpendicular
                    var as = 7;  // arrow size
                    var ax1 = ep.tx - ux * as * 1.5 + px * as;
                    var ay1 = ep.ty - uy * as * 1.5 + py * as;
                    var ax2 = ep.tx - ux * as * 1.5 - px * as;
                    var ay2 = ep.ty - uy * as * 1.5 - py * as;
                    groups[key].arrowD += 'M ' + ep.tx + ' ' + ep.ty +
                        ' L ' + ax1 + ' ' + ay1 +
                        ' L ' + ax2 + ' ' + ay2 + ' Z ';
                }

                // Store geometry for hit test
                geom.push({ connId: conn.id, sx: ep.sx, sy: ep.sy, tx: ep.tx, ty: ep.ty });
            });

            this._connGeometry = geom;

            // Render each group as 2 elements: 1 combined line path + 1 combined arrow path
            var keys = Object.keys(groups);
            for (var i = 0; i < keys.length; i++) {
                var g = groups[keys[i]];

                // Lines
                var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', g.d);
                path.setAttribute('fill', 'none');
                path.setAttribute('stroke', g.color);
                path.setAttribute('stroke-width', '2');
                if (g.dasharray) path.setAttribute('stroke-dasharray', g.dasharray);
                path.style.pointerEvents = 'stroke';
                path.style.cursor = 'pointer';
                path.addEventListener('click', function(e) { self._onGroupedLineClick(e); });
                svg.appendChild(path);

                // Arrows (filled triangles, combined into one path)
                if (g.arrowD) {
                    var arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                    arrow.setAttribute('d', g.arrowD);
                    arrow.setAttribute('fill', g.color);
                    arrow.setAttribute('stroke', 'none');
                    arrow.style.pointerEvents = 'none';
                    svg.appendChild(arrow);
                }
            }
        },

        // Hit test: find which connection was clicked in grouped mode
        _onGroupedLineClick(e) {
            var vp = this.$refs.viewport;
            if (!vp) return;
            var rect = vp.getBoundingClientRect();
            // Convert screen coords to canvas coords
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

        // Point-to-line-segment distance
        _pointToSegmentDist(px, py, x1, y1, x2, y2) {
            var dx = x2 - x1, dy = y2 - y1;
            var lenSq = dx * dx + dy * dy;
            if (lenSq === 0) return Math.sqrt((px - x1) * (px - x1) + (py - y1) * (py - y1));
            var t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / lenSq));
            var nx = x1 + t * dx, ny = y1 + t * dy;
            return Math.sqrt((px - nx) * (px - nx) + (py - ny) * (py - ny));
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
        // Groups
        // ============================================
        async createGroupFromSelection() {
            if (this.selectedAtomIds.length === 0) return;
            var pad = 20;
            var self = this;
            var selected = this.atoms.filter(function(ca) { return self.selectedAtomIds.includes(ca.atom_id); });
            if (selected.length === 0) return;
            var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            selected.forEach(function(ca) {
                minX = Math.min(minX, ca.pos_x);
                minY = Math.min(minY, ca.pos_y);
                maxX = Math.max(maxX, ca.pos_x + (ca.width || 260));
                maxY = Math.max(maxY, ca.pos_y + (ca.height || 120));
            });
            await API.createGroup(this.canvasId, {
                name: 'Group',
                color: '#3b82f6',
                pos_x: minX - pad,
                pos_y: minY - pad - 24,
                width: maxX - minX + pad * 2,
                height: maxY - minY + pad * 2 + 24,
                atom_ids: this.selectedAtomIds,
            });
            this.selectedAtomIds = [];
            await this.loadData();
            this.$nextTick(function() { self.renderConnections(); });
        },

        getGroupStyle(g) {
            return 'left:' + g.pos_x + 'px; top:' + g.pos_y + 'px; width:' + g.width + 'px; height:' + g.height + 'px; z-index:' + (g.z_index || 1) + '; border-color:' + g.color + '; background:' + g.color + '08;';
        },

        getGroupLabelStyle(g) {
            return 'color:' + g.color + ';';
        },

        onGroupMouseDown(e, g) {
            if (e.button !== 0) return;
            e.stopPropagation();
            this.dragGroup = g;
            this.groupDragStartX = e.clientX;
            this.groupDragStartY = e.clientY;
            this.groupDragStartPos = { x: g.pos_x, y: g.pos_y };
            var self = this;
            this.groupDragMemberStarts = {};
            this.atoms.forEach(function(ca) {
                if (ca.group_id === g.id) {
                    self.groupDragMemberStarts[ca.atom_id] = { x: ca.pos_x, y: ca.pos_y };
                }
            });
        },

        onGroupResizeMouseDown(e, g) {
            if (e.button !== 0) return;
            e.stopPropagation();
            e.preventDefault();
            this.resizeGroup = g;
            this.resizeGroupStartX = e.clientX;
            this.resizeGroupStartY = e.clientY;
            this.resizeGroupStartW = g.width;
            this.resizeGroupStartH = g.height;
        },

        openGroupEditModal(g) {
            this.editingGroup = g;
            this.groupForm = { name: g.name, color: g.color };
            this.showGroupModal = true;
        },

        async saveGroupEdit() {
            if (!this.editingGroup) return;
            await API.updateGroup(this.editingGroup.id, {
                name: this.groupForm.name,
                color: this.groupForm.color,
            });
            this.showGroupModal = false;
            this.editingGroup = null;
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        async deleteGroup(groupId) {
            await API.deleteGroup(groupId);
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        async ungroupAtoms(groupId) {
            await API.deleteGroup(groupId);
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        recalcGroupBounds(groupId) {
            var group = this.groups.find(function(g) { return g.id === groupId; });
            if (!group) return;
            var members = this.atoms.filter(function(ca) { return ca.group_id === groupId; });
            if (members.length === 0) return;
            var pad = 20;
            var labelH = 24;
            var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            members.forEach(function(ca) {
                var el = document.getElementById('card-' + ca.atom_id);
                var w = el ? el.offsetWidth : (ca.width || 260);
                var h = el ? el.offsetHeight : (ca.height || 120);
                minX = Math.min(minX, ca.pos_x);
                minY = Math.min(minY, ca.pos_y);
                maxX = Math.max(maxX, ca.pos_x + w);
                maxY = Math.max(maxY, ca.pos_y + h);
            });
            group.pos_x = minX - pad;
            group.pos_y = minY - pad - labelH;
            group.width = maxX - minX + pad * 2;
            group.height = maxY - minY + pad * 2 + labelH;
        },

        autoResizeGroup(groupId) {
            this.recalcGroupBounds(groupId);
            var group = this.groups.find(function(g) { return g.id === groupId; });
            if (group) {
                API.updateGroup(group.id, {
                    pos_x: group.pos_x, pos_y: group.pos_y,
                    width: group.width, height: group.height,
                });
            }
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
        // Markdown Rendering
        // ============================================
        _markedInited: false,

        initMarked() {
            if (this._markedInited || typeof marked === 'undefined') return;
            marked.use({
                breaks: true,
                gfm: true,
            });
            this._markedInited = true;
        },

        renderMarkdown(text, maxLen) {
            if (!text) return '';
            this.initMarked();
            var src = maxLen && text.length > maxLen ? text.substring(0, maxLen) + '...' : text;
            try {
                return marked.parse(src);
            } catch (e) {
                // Fallback to escaped plain text
                return src.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
            }
        },

        // ============================================
        // Minimap
        // ============================================
        _minimapVisible: true,

        toggleMinimap() {
            this._minimapVisible = !this._minimapVisible;
            if (this._minimapVisible) {
                this.$nextTick(() => this.renderMinimap());
            }
        },

        renderMinimap() {
            if (!this._minimapVisible) return;
            var mc = this.$refs.minimapCanvas;
            if (!mc) return;
            var ctx = mc.getContext('2d');
            var mw = mc.width;
            var mh = mc.height;

            ctx.clearRect(0, 0, mw, mh);

            // Background
            ctx.fillStyle = 'rgba(30, 30, 30, 0.85)';
            ctx.fillRect(0, 0, mw, mh);

            if (this.atoms.length === 0) return;

            // Calculate content bounds (all atoms + groups)
            var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            var self = this;
            this.atoms.forEach(function(ca) {
                var w = ca.width || 260;
                var h = ca.height || 120;
                minX = Math.min(minX, ca.pos_x);
                minY = Math.min(minY, ca.pos_y);
                maxX = Math.max(maxX, ca.pos_x + w);
                maxY = Math.max(maxY, ca.pos_y + h);
            });
            this.groups.forEach(function(g) {
                minX = Math.min(minX, g.pos_x);
                minY = Math.min(minY, g.pos_y);
                maxX = Math.max(maxX, g.pos_x + g.width);
                maxY = Math.max(maxY, g.pos_y + g.height);
            });

            // Add padding
            var pad = 100;
            minX -= pad; minY -= pad; maxX += pad; maxY += pad;
            var cw = maxX - minX;
            var ch = maxY - minY;

            // Scale to fit minimap
            var scale = Math.min((mw - 8) / cw, (mh - 8) / ch);
            var offX = (mw - cw * scale) / 2;
            var offY = (mh - ch * scale) / 2;

            function toMini(x, y) {
                return { x: (x - minX) * scale + offX, y: (y - minY) * scale + offY };
            }

            // Draw groups
            this.groups.forEach(function(g) {
                var p = toMini(g.pos_x, g.pos_y);
                var gw = g.width * scale;
                var gh = g.height * scale;
                ctx.strokeStyle = g.color + '80';
                ctx.lineWidth = 1;
                ctx.setLineDash([2, 2]);
                ctx.strokeRect(p.x, p.y, gw, gh);
                ctx.setLineDash([]);
            });

            // Draw connections
            ctx.lineWidth = 0.5;
            this.connections.forEach(function(conn) {
                var srcCa = self.atoms.find(function(a) { return a.atom_id === conn.source_atom_id; });
                var tgtCa = self.atoms.find(function(a) { return a.atom_id === conn.target_atom_id; });
                if (!srcCa || !tgtCa) return;
                var sw = srcCa.width || 260, sh = srcCa.height || 120;
                var tw = tgtCa.width || 260, th = tgtCa.height || 120;
                var s = toMini(srcCa.pos_x + sw / 2, srcCa.pos_y + sh / 2);
                var t = toMini(tgtCa.pos_x + tw / 2, tgtCa.pos_y + th / 2);
                ctx.strokeStyle = (conn.color || '#94a3b8') + '60';
                ctx.beginPath();
                ctx.moveTo(s.x, s.y);
                ctx.lineTo(t.x, t.y);
                ctx.stroke();
            });

            // Draw atoms
            this.atoms.forEach(function(ca) {
                var type = ca.atom ? ca.atom.atom_type : 'F';
                var cfg = self.atomTypeConfig[type] || self.atomTypeConfig.F;
                var lifecycle = ca.atom ? ca.atom.lifecycle : 'active';
                var alpha = { active: 'cc', aging: 'aa', archived: '66', terminal: '33' }[lifecycle] || 'cc';
                var w = ca.width || 260;
                var h = ca.height || 120;
                var p = toMini(ca.pos_x, ca.pos_y);
                var rw = Math.max(3, w * scale);
                var rh = Math.max(2, h * scale);

                ctx.fillStyle = cfg.border + alpha;
                ctx.fillRect(p.x, p.y, rw, rh);

                // Highlight selected
                if (ca.atom_id === self.selectedAtomId) {
                    ctx.strokeStyle = '#3b82f6';
                    ctx.lineWidth = 1.5;
                    ctx.strokeRect(p.x - 1, p.y - 1, rw + 2, rh + 2);
                }
            });

            // Draw viewport rectangle
            var vp = this.$refs.viewport;
            if (!vp) return;
            var rect = vp.getBoundingClientRect();
            var vpLeft = (-this.panX) / this.zoom;
            var vpTop = (-this.panY) / this.zoom;
            var vpW = rect.width / this.zoom;
            var vpH = rect.height / this.zoom;

            var vp1 = toMini(vpLeft, vpTop);
            var vpMW = vpW * scale;
            var vpMH = vpH * scale;

            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 1.5;
            ctx.strokeRect(vp1.x, vp1.y, vpMW, vpMH);
            ctx.fillStyle = 'rgba(255, 255, 255, 0.05)';
            ctx.fillRect(vp1.x, vp1.y, vpMW, vpMH);

            // Store mapping for click-to-navigate
            this._minimapMapping = { minX: minX, minY: minY, scale: scale, offX: offX, offY: offY };
        },

        _minimapMapping: null,

        onMinimapClick(e) {
            if (!this._minimapMapping) return;
            var mc = this.$refs.minimapCanvas;
            if (!mc) return;
            var cr = mc.getBoundingClientRect();
            var mx = e.clientX - cr.left;
            var my = e.clientY - cr.top;
            var m = this._minimapMapping;

            // Convert minimap coords to canvas coords
            var cx = (mx - m.offX) / m.scale + m.minX;
            var cy = (my - m.offY) / m.scale + m.minY;

            // Center viewport on clicked point
            var vp = this.$refs.viewport;
            if (!vp) return;
            var rect = vp.getBoundingClientRect();
            this.panX = rect.width / 2 - cx * this.zoom;
            this.panY = rect.height / 2 - cy * this.zoom;
            this.updateTransform();
            this.renderConnections();
            this.renderMinimap();
            this.saveViewport();
        },

        _minimapDragging: false,

        onMinimapMouseDown(e) {
            e.preventDefault();
            e.stopPropagation();
            this._minimapDragging = true;
            this.onMinimapClick(e);
        },

        onMinimapMouseMove(e) {
            if (!this._minimapDragging) return;
            this.onMinimapClick(e);
        },

        onMinimapMouseUp(e) {
            this._minimapDragging = false;
        },

        // ============================================
        // Toast
        // ============================================
        showToast(msg, type, duration) {
            var id = ++this._toastSeq;
            this.toasts.push({ id: id, msg: msg, type: type || 'info', duration: duration || 4000 });
        },

        removeToast(id) {
            this.toasts = this.toasts.filter(function(t) { return t.id !== id; });
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
