/**
 * BeakCortex 白板引擎
 * pan/zoom、原子卡片渲染、拖曳、SVG 連線、atom_type 視覺區分、lifecycle 透明度
 *
 * Mixin 載入順序（whiteboard.html 中 script 標籤）：
 *   whiteboard-connections.js, whiteboard-minimap.js, whiteboard-card-editor.js,
 *   whiteboard-undo.js, whiteboard-batch.js, whiteboard-groups.js
 *   -> whiteboard.js (本檔)
 */

/** 合併 mixin：保留 getter/setter */
function _mergeInto(target, source) {
    Object.defineProperties(target, Object.getOwnPropertyDescriptors(source));
}

function whiteboardApp(canvasId) {
    var app = {
        canvasId,
        canvas: null,
        isSnapshot: false,
        atoms: [],
        connections: [],
        groups: [],
        canvases: [],
        tags: [],
        tagCategories: [],
        entrySchemas: [],

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
        showConnTypeModal: false,
        connTypeChangeTarget: null,
        connTypeChangeLabel: '',
        connDragShiftKey: false,
        showUISettingsModal: false,
        showBatchTagModal: false,
        batchTagActiveTab: 0,
        uiSettingsTab: 'canvas',
        newCategoryName: '',
        settingsCanvasName: '',
        selectedCategoryIds: [],

        // Entry Schema settings
        esSelectedId: null,
        esEditSchema: null,
        esNewCode: '',
        esNewName: '',
        esNewField: { name: '', label: '', field_type: 'text', options: '', required: false, dimension: '' },
        esFieldTypes: [
            { value: 'text', label: '文字' },
            { value: 'number', label: '整數' },
            { value: 'decimal', label: '小數' },
            { value: 'date', label: '日期' },
            { value: 'datetime', label: '日期時間' },
            { value: 'duration', label: '時長' },
            { value: 'select', label: '單選' },
            { value: 'multiselect', label: '多選' },
            { value: 'checkbox', label: '核取' },
            { value: 'relation', label: '關聯' },
            { value: 'attachment', label: '附件' },
        ],
        esDimensions: [
            { value: '', label: '-' },
            { value: 'W', label: 'W (who)' },
            { value: 'H', label: 'H (what)' },
            { value: 'T', label: 'T (when)' },
            { value: 'P', label: 'P (where)' },
            { value: 'Y', label: 'Y (why)' },
        ],

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
        batchBarX: 0, batchBarY: 0,

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

        // Card Editor (state managed by whiteboard-card-editor.js mixin)

        // Toast
        toasts: [],
        _toastSeq: 0,

        // Undo/Redo
        undoStack: [],
        redoStack: [],
        _maxUndoDepth: 50,

        // Filters
        filterTypes: { A: true, B: true, C: true, D: true, E: true, F: true },
        filterLifecycles: { active: true, aging: true, archived: true, terminal: true },
        filterTagIds: [],
        filterPanelOpen: false,

        // Batch operations
        showBatchPanel: false,
        batchAtomType: '',
        batchLifecycle: '',

        // Connection inline edit
        editingConnId: null,
        editingConnLabel: '',
        editingConnPos: { x: 0, y: 0 },

        // Export/Import
        showExportModal: false,
        showImportModal: false,
        exportFormat: 'json',
        exportContent: '',
        importFile: null,

        // Canvas sidebar
        showArchivedCanvases: false,
        archivedCanvasCount: 0,

        // Account
        pwOld: '', pwNew: '', pwConfirm: '',
        pwMsg: '', pwMsgOk: false,

        // Render test panel
        renderMode: 'normal',
        renderStats: { total: 0, rendered: 0 },
        rtLineStyle: 'curve',
        rtEngine: 'grouped',
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
            var urlParams = new URLSearchParams(window.location.search);
            var rm = urlParams.get('render');
            if (rm === 'straight' || rm === 'optimized' || rm === 'opt-straight') this.renderMode = rm;
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
            const self = this;
            document.addEventListener('keydown', function(e) { self.handleKeyDown(e); });
            document.addEventListener('mouseup', () => { if (this.isConnDragging) this.cancelConnDrag(); });
            this.$refs.viewport.addEventListener('mousedown', function(e) {
                if (e.button === 2) {
                    self.rightDragPending = true;
                    self.rightDragStartX = e.clientX; self.rightDragStartY = e.clientY;
                    var cardEl = e.target.closest('.wb-card');
                    var groupEl = e.target.closest('.wb-group');
                    if (cardEl) {
                        var atomId = parseInt(cardEl.id.replace('card-', ''), 10);
                        self.rightDragTarget = self.atoms.find(function(a) { return a.atom_id === atomId; }) || null;
                    } else if (groupEl) {
                        var gid = parseInt(groupEl.id.replace('group-', ''), 10);
                        var grp = self.groups.find(function(g) { return g.id === gid; });
                        self.rightDragTarget = grp ? { _isGroup: true, group: grp } : null;
                    } else { self.rightDragTarget = null; }
                    e.preventDefault();
                }
            }, true);
        },

        async loadData() {
            const [canvas, allCanvases, tags, tagCategories, entrySchemas] = await Promise.all([
                API.getCanvas(this.canvasId), API.getCanvases(true), API.getTags(), API.getTagCategories(),
                API.getEntrySchemas(),
            ]);
            this.canvas = canvas;
            this.isSnapshot = !!canvas.is_snapshot;
            this.atoms = canvas.atoms || [];
            this.connections = canvas.connections || [];
            this.groups = canvas.groups || [];
            this.archivedCanvasCount = allCanvases.filter(c => c.is_archived).length;
            this.canvases = this.showArchivedCanvases ? allCanvases : allCanvases.filter(c => !c.is_archived);
            this.tags = tags;
            this.tagCategories = tagCategories;
            this.entrySchemas = entrySchemas;
            this.refreshSidebarAtoms();
            if (canvas.viewport_x || canvas.viewport_y || (canvas.viewport_zoom && canvas.viewport_zoom !== 1)) {
                this.panX = canvas.viewport_x || 0; this.panY = canvas.viewport_y || 0;
                this.zoom = canvas.viewport_zoom || 1; this.updateTransform();
            }
            // 還原 RT 設定（URL 參數優先於 DB）
            var urlOverride = new URLSearchParams(window.location.search).get('render');
            if (!urlOverride) {
                try {
                    var settings = JSON.parse(canvas.settings || '{}');
                    if (settings.renderTest) {
                        var rt = settings.renderTest;
                        if (rt.rtEngine) this.rtEngine = rt.rtEngine;
                        if (rt.rtLineStyle) this.rtLineStyle = rt.rtLineStyle;
                        if (rt.rtOptEnabled !== undefined) this.rtOptEnabled = rt.rtOptEnabled;
                        if (rt.rtOptPerSector !== undefined) this.rtOptPerSector = rt.rtOptPerSector;
                    }
                } catch (e) { /* ignore parse errors */ }
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
                const mx = e.clientX - rect.left, my = e.clientY - rect.top;
                this.panX = mx - (mx - this.panX) * (newZoom / this.zoom);
                this.panY = my - (my - this.panY) * (newZoom / this.zoom);
                this.zoom = newZoom;
                this.updateTransform(); this.renderConnections();
            }, { passive: false });
        },

        onViewportMouseDown(e) {
            if (this.editingAtomId && document.activeElement) document.activeElement.blur();
            if (e.button === 1) { this.isPanning = true; this.panStartX = e.clientX - this.panX; this.panStartY = e.clientY - this.panY; e.preventDefault(); return; }
            if (e.button === 2) return;
            if (e.button === 0) {
                if (this.mode === 'connect' && !e.target.closest('.wb-card')) { this.connSourceAtomId = null; this.mode = 'select'; return; }
                if (!e.target.closest('.wb-card') && !e.target.closest('.wb-group') && !e.target.closest('.wb-toolbar') && !e.target.closest('.wb-zoom')) {
                    this.boxSelectPending = true;
                    this.boxSelectStartX = e.clientX; this.boxSelectStartY = e.clientY;
                    this.boxSelectCurrentX = e.clientX; this.boxSelectCurrentY = e.clientY;
                    e.preventDefault();
                }
            }
        },

        onViewportMouseMove(e) {
            if (this.isConnDragging) { this.connDragMouseX = e.clientX; this.connDragMouseY = e.clientY; this.updatePreviewLine(); return; }
            if (this.rightDragPending) {
                if (Math.abs(e.clientX - this.rightDragStartX) > 5 || Math.abs(e.clientY - this.rightDragStartY) > 5) {
                    this.rightDragPending = false; this.isPanning = true;
                    this.panStartX = this.rightDragStartX - this.panX; this.panStartY = this.rightDragStartY - this.panY;
                }
            }
            if (this.isPanning) { this.panX = e.clientX - this.panStartX; this.panY = e.clientY - this.panStartY; this.updateTransform(); this.renderConnections(); return; }
            if (this.boxSelectPending) {
                if (Math.abs(e.clientX - this.boxSelectStartX) > 5 || Math.abs(e.clientY - this.boxSelectStartY) > 5) { this.boxSelectPending = false; this.isBoxSelecting = true; }
            }
            if (this.isBoxSelecting) { this.boxSelectCurrentX = e.clientX; this.boxSelectCurrentY = e.clientY; this.updateBoxSelection(); return; }
            if (this.bodyDragPending) {
                if (Math.abs(e.clientX - this.bodyDragStartX) > 5 || Math.abs(e.clientY - this.bodyDragStartY) > 5) {
                    this.bodyDragPending = false; var ca = this.bodyDragCa; this.bodyDragCa = null;
                    this.startCardDrag(e, ca, this.bodyDragStartX, this.bodyDragStartY);
                }
            }
            if (this.dragGroup) {
                var gdx = (e.clientX - this.groupDragStartX) / this.zoom, gdy = (e.clientY - this.groupDragStartY) / this.zoom;
                this.dragGroup.pos_x = this.groupDragStartPos.x + gdx; this.dragGroup.pos_y = this.groupDragStartPos.y + gdy;
                var self = this;
                this.atoms.forEach(function(a) { if (self.groupDragMemberStarts[a.atom_id]) { a.pos_x = self.groupDragMemberStarts[a.atom_id].x + gdx; a.pos_y = self.groupDragMemberStarts[a.atom_id].y + gdy; } });
                this.renderConnections(); return;
            }
            if (this.resizeGroup) { this.resizeGroup.width = Math.max(160, this.resizeGroupStartW + (e.clientX - this.resizeGroupStartX) / this.zoom); this.resizeGroup.height = Math.max(80, this.resizeGroupStartH + (e.clientY - this.resizeGroupStartY) / this.zoom); return; }
            if (this.resizeCard) {
                this.resizeCard.width = Math.max(160, this.resizeStartW + (e.clientX - this.resizeStartX) / this.zoom);
                this.resizeCard.height = Math.max(80, this.resizeStartH + (e.clientY - this.resizeStartY) / this.zoom);
                if (this.resizeCard.group_id) this.recalcGroupBounds(this.resizeCard.group_id);
                this.renderConnections(); return;
            }
            if (this.dragCard) {
                var dx = (e.clientX - this.dragStartX) / this.zoom, dy = (e.clientY - this.dragStartY) / this.zoom;
                var affectedGroups = new Set();
                if (this.multiDragStarts) {
                    var self = this;
                    this.atoms.forEach(function(a) { if (self.multiDragStarts[a.atom_id]) { a.pos_x = self.multiDragStarts[a.atom_id].x + dx; a.pos_y = self.multiDragStarts[a.atom_id].y + dy; if (a.group_id) affectedGroups.add(a.group_id); } });
                } else {
                    this.dragCard.pos_x = this.cardStartX + dx; this.dragCard.pos_y = this.cardStartY + dy;
                    if (this.dragCard.group_id) affectedGroups.add(this.dragCard.group_id);
                }
                var self2 = this; affectedGroups.forEach(function(gid) { self2.recalcGroupBounds(gid); });
                this.renderConnections();
            }
        },

        onViewportMouseUp(e) {
            if (this.rightDragPending) {
                this.rightDragPending = false; var tgt = this.rightDragTarget; this.rightDragTarget = null;
                if (tgt && tgt._isGroup) this.contextMenu = { x: e.clientX, y: e.clientY, type: 'group', group: tgt.group };
                else if (tgt) this.contextMenu = { x: e.clientX, y: e.clientY, type: 'card', ca: tgt };
                else this.contextMenu = { x: e.clientX, y: e.clientY, type: 'canvas' };
                return;
            }
            if (this.isBoxSelecting) { this.isBoxSelecting = false; this.boxSelectPending = false; if (this.selectedAtomIds.length >= 2) { this.batchBarX = e.clientX; this.batchBarY = e.clientY - 10; } return; }
            if (this.boxSelectPending) { this.boxSelectPending = false; this.selectedAtomIds = []; this.deselectCard(); return; }
            if (this.bodyDragPending) { this.bodyDragPending = false; var ca = this.bodyDragCa; this.bodyDragCa = null; if (ca) { this.selectCard(ca.atom_id); this.startInlineEdit(ca); } return; }
            if (this.isConnDragging) { this.endConnDrag(); return; }
            if (this.isPanning) { this.isPanning = false; this.saveViewport(); }
            if (this.dragGroup) {
                API.updateGroup(this.dragGroup.id, { pos_x: this.dragGroup.pos_x, pos_y: this.dragGroup.pos_y });
                var self = this;
                this.atoms.forEach(function(a) { if (self.groupDragMemberStarts && self.groupDragMemberStarts[a.atom_id]) API.updateCanvasAtom(a.id, { pos_x: a.pos_x, pos_y: a.pos_y }); });
                this.dragGroup = null; this.groupDragMemberStarts = null;
            }
            if (this.resizeGroup) { API.updateGroup(this.resizeGroup.id, { width: this.resizeGroup.width, height: this.resizeGroup.height }); this.resizeGroup = null; }
            if (this.resizeCard) { API.updateCanvasAtom(this.resizeCard.id, { width: this.resizeCard.width, height: this.resizeCard.height }); if (this.resizeCard.group_id) this.autoResizeGroup(this.resizeCard.group_id); this.resizeCard = null; }
            if (this.dragCard) {
                this._justDragged = true;
                var groupsToResize = new Set(); var movedIds = []; var beforePos = []; var afterPos = [];
                if (this.multiDragStarts) {
                    var self = this;
                    this.atoms.forEach(function(a) { if (self.multiDragStarts[a.atom_id]) { movedIds.push(a.atom_id); beforePos.push({ x: self.multiDragStarts[a.atom_id].x, y: self.multiDragStarts[a.atom_id].y }); afterPos.push({ x: a.pos_x, y: a.pos_y }); API.updateCanvasAtom(a.id, { pos_x: a.pos_x, pos_y: a.pos_y }); if (a.group_id) groupsToResize.add(a.group_id); } });
                    this.multiDragStarts = null;
                } else {
                    movedIds.push(this.dragCard.atom_id); beforePos.push({ x: this.cardStartX, y: this.cardStartY }); afterPos.push({ x: this.dragCard.pos_x, y: this.dragCard.pos_y });
                    API.updateCanvasAtom(this.dragCard.id, { pos_x: this.dragCard.pos_x, pos_y: this.dragCard.pos_y });
                    if (this.dragCard.group_id) groupsToResize.add(this.dragCard.group_id);
                }
                if (movedIds.length > 0 && (beforePos[0].x !== afterPos[0].x || beforePos[0].y !== afterPos[0].y)) this.pushMoveUndo(movedIds, beforePos, afterPos);
                var self2 = this; groupsToResize.forEach(function(gid) { self2.autoResizeGroup(gid); });
                this.dragCard = null;
            }
        },

        updateTransform() {
            const c = this.$refs.canvas;
            if (c) c.style.transform = `translate(${this.panX}px, ${this.panY}px) scale(${this.zoom})`;
            this.renderMinimap();
        },

        saveViewport() { if (this.isSnapshot) return; API.updateCanvas(this.canvasId, { viewport_x: this.panX, viewport_y: this.panY, viewport_zoom: this.zoom }); },
        zoomIn() { this.zoom = Math.min(3, this.zoom * 1.2); this.updateTransform(); this.renderConnections(); },
        zoomOut() { this.zoom = Math.max(0.15, this.zoom / 1.2); this.updateTransform(); this.renderConnections(); },
        resetZoom() { this.zoom = 1; this.panX = 0; this.panY = 0; this.updateTransform(); this.renderConnections(); this.saveViewport(); },

        fitView() {
            if (this.atoms.length === 0) return;
            const vp = this.$refs.viewport; if (!vp) return;
            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            this.atoms.forEach(ca => { minX = Math.min(minX, ca.pos_x); minY = Math.min(minY, ca.pos_y); maxX = Math.max(maxX, ca.pos_x + (ca.width || 265)); maxY = Math.max(maxY, ca.pos_y + (ca.height || 160)); });
            const pad = 80, cw = maxX - minX + pad * 2, ch = maxY - minY + pad * 2;
            const rect = vp.getBoundingClientRect();
            this.zoom = Math.min(rect.width / cw, rect.height / ch, 1.2);
            this.panX = (rect.width - cw * this.zoom) / 2 - (minX - pad) * this.zoom;
            this.panY = (rect.height - ch * this.zoom) / 2 - (minY - pad) * this.zoom;
            this.updateTransform(); this.renderConnections(); this.saveViewport();
        },

        get zoomPercent() { return Math.round(this.zoom * 100); },

        sidebarAtoms: [],

        refreshSidebarAtoms() {
            this.sidebarAtoms = this.atoms.slice().sort(function(a, b) {
                var ta = (a.atom && a.atom.updated_at) || '';
                var tb = (b.atom && b.atom.updated_at) || '';
                return tb.localeCompare(ta);
            });
        },

        screenToCanvas(sx, sy) {
            const vp = this.$refs.viewport; const rect = vp.getBoundingClientRect();
            return { x: (sx - rect.left - this.panX) / this.zoom, y: (sy - rect.top - this.panY) / this.zoom };
        },

        // ============================================
        // Card Operations
        // ============================================
        onCardMouseDown(e, ca) {
            if (e.button !== 0 || this.mode === 'connect') return;
            e.stopPropagation(); this.startCardDrag(e, ca, e.clientX, e.clientY);
        },

        startCardDrag(e, ca, startX, startY) {
            if (this.selectedAtomIds.includes(ca.atom_id) && this.selectedAtomIds.length > 1) {
                this.dragCard = ca; this.dragStartX = startX; this.dragStartY = startY;
                this.multiDragStarts = {}; var self = this;
                this.atoms.forEach(function(a) { if (self.selectedAtomIds.includes(a.atom_id)) self.multiDragStarts[a.atom_id] = { x: a.pos_x, y: a.pos_y }; });
            } else {
                this.selectedAtomIds = []; this.selectCard(ca.atom_id);
                this.dragCard = ca; this.dragStartX = startX; this.dragStartY = startY;
                this.cardStartX = ca.pos_x; this.cardStartY = ca.pos_y;
            }
            ca.z_index = Math.max(0, ...this.atoms.map(function(a) { return a.z_index || 0; })) + 1;
        },

        onCardBodyMouseDown(e, ca) {
            if (e.button !== 0 || this.mode === 'connect') return;
            if (this.editingAtomId === ca.atom_id) return;
            e.stopPropagation();
            this.bodyDragPending = true; this.bodyDragStartX = e.clientX; this.bodyDragStartY = e.clientY; this.bodyDragCa = ca;
        },

        startInlineEdit(ca) { if (!ca || !ca.atom) return; this.openCardEditor(ca.atom_id); },
        async finishInlineEdit(ca) {},
        cancelInlineEdit() {},

        // Resize
        onResizeMouseDown(e, ca) {
            if (e.button !== 0) return;
            e.stopPropagation(); e.preventDefault();
            this.resizeCard = ca; this.resizeStartX = e.clientX; this.resizeStartY = e.clientY;
            const el = document.getElementById('card-' + ca.atom_id);
            this.resizeStartW = el ? el.offsetWidth : (ca.width || 265);
            this.resizeStartH = el ? el.offsetHeight : (ca.height || 125);
        },

        // Atom info dialog
        showAtomInfoModal: false,

        async selectCard(atomId) {
            this.selectedAtomId = atomId;
            this.selectedAtomDetails = null; this.blockChain = null; this.highlightedAtomIds = [];
        },

        async loadAtomDetails(atomId) {
            this.selectedAtomDetails = null; this.blockChain = null; this.highlightedAtomIds = [];
            try { var details = await API.getAtom(atomId); this.selectedAtomDetails = details; }
            catch (e) { console.error('Failed to fetch atom details:', e); }
        },

        deselectCard() { this.selectedAtomId = null; this.selectedAtomDetails = null; this.blockChain = null; this.highlightedAtomIds = []; },

        onCardClick(ca) {
            if (this._justDragged) { this._justDragged = false; return; }
            this.selectedAtomIds = []; this.selectCard(ca.atom_id);
        },

        async onCardDblClick(ca) {
            this.selectedAtomIds = [];
            this.selectedAtomId = ca.atom_id;
            await this.loadAtomDetails(ca.atom_id);
            this.showAtomInfoModal = true;
        },

        // Box selection
        get boxSelectStyle() {
            if (!this.isBoxSelecting) return 'display:none;';
            var vp = this.$refs.viewport; if (!vp) return 'display:none;';
            var rect = vp.getBoundingClientRect();
            var x1 = this.boxSelectStartX - rect.left, y1 = this.boxSelectStartY - rect.top;
            var x2 = this.boxSelectCurrentX - rect.left, y2 = this.boxSelectCurrentY - rect.top;
            return 'left:' + Math.min(x1, x2) + 'px; top:' + Math.min(y1, y2) + 'px; width:' + Math.abs(x2 - x1) + 'px; height:' + Math.abs(y2 - y1) + 'px;';
        },

        updateBoxSelection() {
            var start = this.screenToCanvas(this.boxSelectStartX, this.boxSelectStartY);
            var end = this.screenToCanvas(this.boxSelectCurrentX, this.boxSelectCurrentY);
            var left = Math.min(start.x, end.x), top = Math.min(start.y, end.y);
            var right = Math.max(start.x, end.x), bottom = Math.max(start.y, end.y);
            this.selectedAtomIds = this.atoms.filter(function(ca) {
                var w = ca.width || 265, h = ca.height || 125;
                return ca.pos_x + w > left && ca.pos_x < right && ca.pos_y + h > top && ca.pos_y < bottom;
            }).map(function(ca) { return ca.atom_id; });
        },

        get selectedAtom() { return this.atoms.find(ca => ca.atom_id === this.selectedAtomId) || null; },

        getCardStyle(ca) {
            const type = ca.atom ? ca.atom.atom_type : 'F';
            const lifecycle = ca.atom ? ca.atom.lifecycle : 'active';
            const cfg = this.atomTypeConfig[type] || this.atomTypeConfig.F;
            const opacity = { active: 1, aging: 0.65, archived: 0.35, terminal: 0.2 }[lifecycle] || 1;
            const border = type === 'F' ? '2px dashed ' + cfg.border : '2px solid ' + cfg.border;
            var s = 'left:' + ca.pos_x + 'px; top:' + ca.pos_y + 'px; z-index:' + (ca.z_index || 10) + '; border:' + border + '; opacity:' + opacity + ';';
            if (ca.width) s += ' width:' + ca.width + 'px;'; if (ca.height) s += ' height:' + ca.height + 'px;';
            return s;
        },

        getTypeBadgeStyle(type) { const cfg = this.atomTypeConfig[type] || this.atomTypeConfig.F; return 'background:' + cfg.bg + '; color:' + cfg.color + ';'; },

        // ============================================
        // New Atom
        // ============================================
        openNewAtomModal(e) {
            if (this.isSnapshot) { this.showToast('歸檔白板為唯讀快照', 'warn'); return; }
            this.newAtom = { title: '', content: '', atom_type: 'F' };
            if (e && e.clientX) { const pos = this.screenToCanvas(e.clientX, e.clientY); this.newAtomPos = { x: pos.x, y: pos.y }; }
            else { this.newAtomPos = { x: (-this.panX / this.zoom) + 200, y: (-this.panY / this.zoom) + 200 }; }
            this.showNewAtomModal = true;
        },

        async createNewAtom() {
            if (this.isSnapshot) return;
            const atom = await API.createAtom({ title: this.newAtom.title || '新卡片', content: this.newAtom.content, atom_type: this.newAtom.atom_type, source: 'human' });
            await API.addAtomToCanvas(this.canvasId, { atom_id: atom.id, pos_x: this.newAtomPos.x, pos_y: this.newAtomPos.y });
            this.showNewAtomModal = false; await this.loadData(); this.$nextTick(() => this.renderConnections());
        },

        // ============================================
        // Add Existing Atom
        // ============================================
        async openAddExistingModal() {
            this.searchQuery = ''; this.searchResults = []; this.showAddExistingModal = true; await this.doSearch();
        },

        async doSearch() {
            const existingIds = new Set(this.atoms.map(ca => ca.atom_id));
            if (this.searchQuery.trim()) { const resp = await API.searchSemantic(this.searchQuery, 20); this.searchResults = (resp.items || []).filter(a => !existingIds.has(a.id)); }
            else { const resp = await API.getAtoms({ per_page: 20 }); this.searchResults = (resp.items || []).filter(a => !existingIds.has(a.id)); }
        },

        async addExistingAtom(atomId) {
            await API.addAtomToCanvas(this.canvasId, { atom_id: atomId, pos_x: (-this.panX / this.zoom) + 200 + Math.random() * 100, pos_y: (-this.panY / this.zoom) + 200 + Math.random() * 100 });
            this.searchResults = this.searchResults.filter(a => a.id !== atomId);
            await this.loadData(); this.$nextTick(() => this.renderConnections());
        },

        // ============================================
        // Update / Remove / Delete
        // ============================================
        async updateAtomField(ca, field, value) {
            if (!ca || !ca.atom) return; ca.atom[field] = value;
            await API.updateAtom(ca.atom_id, { [field]: value }); this.$nextTick(() => this.renderConnections());
        },

        async updateAtomFieldById(atomId, field, value) {
            try {
                await API.updateAtom(atomId, { [field]: value });
                if (this.selectedAtomDetails && this.selectedAtomDetails.id === atomId) {
                    this.selectedAtomDetails[field] = value;
                }
                var ca = this.atoms.find(a => a.atom_id === atomId);
                if (ca && ca.atom) { ca.atom[field] = value; }
                this.$nextTick(() => this.renderConnections());
            } catch (e) { this.showToast(e.message || '更新失敗', 'error'); }
        },

        async toggleAtomTagById(atomId, tagId) {
            if (!this.selectedAtomDetails) return;
            var cur = (this.selectedAtomDetails.tags || []).map(t => t.id);
            var newIds = cur.includes(tagId) ? cur.filter(id => id !== tagId) : cur.concat([tagId]);
            await API.updateAtom(atomId, { tag_ids: newIds });
            await this.loadAtomDetails(atomId);
            await this.loadData(); this.$nextTick(() => this.renderConnections());
        },

        async removeFromCanvas(ca) {
            if (this.isSnapshot) return;
            await API.removeCanvasAtom(ca.id); if (this.selectedAtomId === ca.atom_id) this.deselectCard();
            await this.loadData(); this.$nextTick(() => this.renderConnections());
        },

        async deleteAtomEntirely(ca) {
            if (this.isSnapshot) return;
            await API.deleteAtom(ca.atom_id); if (this.selectedAtomId === ca.atom_id) this.deselectCard();
            await this.loadData(); this.$nextTick(() => this.renderConnections());
        },

        // ============================================
        // Connection Mode
        // ============================================
        toggleConnectMode() { this.mode = this.mode === 'connect' ? 'select' : 'connect'; if (this.mode !== 'connect') this.connSourceAtomId = null; },

        onCardClickForConnect(e, ca) {
            if (this.mode !== 'connect') return; e.stopPropagation();
            if (!this.connSourceAtomId) { this.connSourceAtomId = ca.atom_id; }
            else if (this.connSourceAtomId !== ca.atom_id) {
                this.pendingConnection = { sourceAtomId: this.connSourceAtomId, targetAtomId: ca.atom_id };
                this.selectedRelationType = 'references'; this.relationLabel = ''; this.showRelationModal = true;
                this.connSourceAtomId = null;
            }
        },

        getAtomTitle(atomId) { const ca = this.atoms.find(a => a.atom_id === atomId); return ca && ca.atom ? ca.atom.title : ('#' + atomId); },

        async confirmConnection() {
            if (!this.pendingConnection) return;
            var resp = await API.createConnection({ canvas_id: this.canvasId, source_atom_id: this.pendingConnection.sourceAtomId, target_atom_id: this.pendingConnection.targetAtomId, relation_type: this.selectedRelationType, label: this.relationLabel });
            this.showRelationModal = false; this.pendingConnection = null; this.mode = 'select';
            if (resp && !resp.error) { this.connections.push(resp); this.renderConnections(); }
        },

        async deleteConnection(connId) {
            await API.deleteConnection(connId);
            await this.loadData();
            this.renderConnections();
        },

        // ============================================
        // Tags
        // ============================================
        getTagStyle(color) { return 'background:' + color + '20; color:' + color + '; border:1px solid ' + color + '40;'; },
        atomHasTag(ca, tagId) { return ca && ca.atom && ca.atom.tags && ca.atom.tags.some(function(t) { return t.id === tagId; }); },

        async toggleAtomTag(ca, tagId) {
            if (!ca || !ca.atom) return;
            const cur = (ca.atom.tags || []).map(function(t) { return t.id; });
            const newIds = cur.includes(tagId) ? cur.filter(function(id) { return id !== tagId; }) : cur.concat([tagId]);
            await API.updateAtom(ca.atom_id, { tag_ids: newIds }); await this.loadData(); this.$nextTick(() => this.renderConnections());
        },

        async createTag() {
            if (!this.newTagName.trim()) return;
            await API.createTag({ name: this.newTagName.trim(), color: this.newTagColor }); this.tags = await API.getTags(); this.newTagName = '';
        },

        async deleteTag(tagId) { await API.deleteTag(tagId); this.tags = await API.getTags(); },

        // ============================================
        // Tag Categories
        // ============================================
        async createCategory() {
            if (!this.newCategoryName.trim()) return;
            await API.createTagCategory({ name: this.newCategoryName.trim() });
            this.tagCategories = await API.getTagCategories();
            this.newCategoryName = '';
        },

        async deleteCategory(catId) {
            await API.deleteTagCategory(catId);
            this.tagCategories = await API.getTagCategories();
            this.tags = await API.getTags();
        },

        async setTagCategories(tagId, categoryIds) {
            await API.updateTag(tagId, { category_ids: categoryIds });
            this.tags = await API.getTags();
        },

        toggleCategorySelection(catId) {
            var idx = this.selectedCategoryIds.indexOf(catId);
            if (idx >= 0) { this.selectedCategoryIds.splice(idx, 1); }
            else { this.selectedCategoryIds.push(catId); }
        },

        isTagInSelectedCats(tag) {
            var catIds = tag.category_ids || [];
            for (var i = 0; i < this.selectedCategoryIds.length; i++) {
                var selId = this.selectedCategoryIds[i];
                if (selId === 0 && catIds.length === 0) return true;
                if (catIds.includes(selId)) return true;
            }
            return false;
        },

        async toggleTagInCategory(tag) {
            if (this.selectedCategoryIds.length === 0) return;
            var realCatIds = this.selectedCategoryIds.filter(id => id !== 0);
            var curCatIds = tag.category_ids || [];

            if (realCatIds.length === 0) {
                // 只選了「未分類」：將標籤從所有分類移出
                if (curCatIds.length > 0) {
                    await this.setTagCategories(tag.id, []);
                }
                return;
            }

            // 判斷標籤是否已在所有被勾選的分類中
            var allIn = realCatIds.every(function(id) { return curCatIds.includes(id); });
            var newCatIds;
            if (allIn) {
                // 全在 -> 從被勾選的分類移出（保留其他分類）
                newCatIds = curCatIds.filter(function(id) { return !realCatIds.includes(id); });
            } else {
                // 有缺 -> 加入所有被勾選的分類（保留現有）
                var merged = curCatIds.slice();
                realCatIds.forEach(function(id) { if (merged.indexOf(id) < 0) merged.push(id); });
                newCatIds = merged;
            }
            await this.setTagCategories(tag.id, newCatIds);
        },

        get tagsByCategory() {
            var self = this;
            var result = [];
            var cats = this.tagCategories.slice().sort(function(a, b) { return a.sort_order - b.sort_order; });
            cats.forEach(function(cat) {
                result.push({
                    id: cat.id,
                    name: cat.name,
                    tags: self.tags.filter(function(t) { return (t.category_ids || []).includes(cat.id); }),
                });
            });
            var uncategorized = this.tags.filter(function(t) { return !t.category_ids || t.category_ids.length === 0; });
            if (uncategorized.length > 0) {
                result.push({ id: 0, name: '未分類', tags: uncategorized });
            }
            return result;
        },

        // ============================================
        // Entry Schemas
        // ============================================
        esGetSelected() {
            if (!this.esSelectedId) return null;
            return this.entrySchemas.find(s => s.id === this.esSelectedId) || null;
        },

        esSelectSchema(id) {
            this.esSelectedId = id;
            var schema = this.esGetSelected();
            if (schema) {
                this.esEditSchema = {
                    name: schema.name, icon: schema.icon, color: schema.color,
                    slash_alias: schema.slash_alias || '', code: schema.code,
                };
            }
            this.esNewField = { name: '', label: '', field_type: 'text', options: '', required: false, dimension: '' };
        },

        async esCreateSchema() {
            var code = this.esNewCode.trim();
            var name = this.esNewName.trim();
            if (!code || !name) return;
            try {
                await API.createEntrySchema({ code: code, name: name });
                this.entrySchemas = await API.getEntrySchemas();
                this.esNewCode = '';
                this.esNewName = '';
                this.showToast('記錄類型已建立', 'success');
            } catch (e) { this.showToast(e.message, 'error'); }
        },

        async esUpdateSchema() {
            if (!this.esSelectedId || !this.esEditSchema) return;
            try {
                await API.updateEntrySchema(this.esSelectedId, this.esEditSchema);
                this.entrySchemas = await API.getEntrySchemas();
                this.showToast('已更新', 'success');
            } catch (e) { this.showToast(e.message, 'error'); }
        },

        async esDeleteSchema() {
            var schema = this.esGetSelected();
            if (!schema) return;
            if (schema.is_system) { this.showToast('系統內建類型不可刪除', 'error'); return; }
            if (!confirm('刪除記錄類型: ' + schema.name + '?')) return;
            try {
                await API.deleteEntrySchema(this.esSelectedId);
                this.entrySchemas = await API.getEntrySchemas();
                this.esSelectedId = null;
                this.esEditSchema = null;
                this.showToast('已刪除', 'success');
            } catch (e) { this.showToast(e.message, 'error'); }
        },

        async esAddField() {
            if (!this.esSelectedId) return;
            var f = this.esNewField;
            if (!f.name.trim() || !f.label.trim()) return;
            try {
                await API.createEntrySchemaField(this.esSelectedId, {
                    name: f.name.trim(), label: f.label.trim(),
                    field_type: f.field_type, options: f.options,
                    required: f.required, dimension: f.dimension || null,
                });
                this.entrySchemas = await API.getEntrySchemas();
                this.esNewField = { name: '', label: '', field_type: 'text', options: '', required: false, dimension: '' };
                this.showToast('欄位已新增', 'success');
            } catch (e) { this.showToast(e.message, 'error'); }
        },

        async esUpdateField(fieldId, updates) {
            try {
                await API.updateEntrySchemaField(fieldId, updates);
                this.entrySchemas = await API.getEntrySchemas();
            } catch (e) { this.showToast(e.message, 'error'); }
        },

        async esDeleteField(fieldId) {
            if (!confirm('刪除此欄位?')) return;
            try {
                await API.deleteEntrySchemaField(fieldId);
                this.entrySchemas = await API.getEntrySchemas();
                this.showToast('欄位已刪除', 'success');
            } catch (e) { this.showToast(e.message, 'error'); }
        },

        async esMoveField(fieldId, direction) {
            var schema = this.esGetSelected();
            if (!schema || !schema.fields) return;
            var fields = schema.fields.slice().sort((a, b) => a.sort_order - b.sort_order);
            var idx = fields.findIndex(f => f.id === fieldId);
            if (idx < 0) return;
            var swapIdx = direction === 'up' ? idx - 1 : idx + 1;
            if (swapIdx < 0 || swapIdx >= fields.length) return;
            var ids = fields.map(f => f.id);
            var tmp = ids[idx]; ids[idx] = ids[swapIdx]; ids[swapIdx] = tmp;
            try {
                await API.reorderEntrySchemaFields(this.esSelectedId, ids);
                this.entrySchemas = await API.getEntrySchemas();
            } catch (e) { this.showToast(e.message, 'error'); }
        },

        // ============================================
        // Canvas Management
        // ============================================
        async saveCanvasName() {
            var name = this.settingsCanvasName.trim();
            if (!name) return;
            await API.updateCanvas(this.canvasId, { name: name });
            this.canvas.name = name;
            await this.loadCanvases();
            this.showToast('白板名稱已更新', 'success');
        },

        async createCanvas() { if (!this.newCanvasName.trim()) return; const c = await API.createCanvas({ name: this.newCanvasName.trim() }); window.location.href = '/beakcortex/canvas/' + c.slug; },

        async deleteCanvas(slug) {
            if (this.canvases.length <= 1) return;
            await API.deleteCanvas(slug);
            if (slug === this.canvasId) window.location.href = '/beakcortex/'; else await this.loadCanvases();
        },

        async archiveCurrentCanvas() {
            if (!confirm('歸檔此白板？白板會隱藏但保留。')) return;
            await API.updateCanvas(this.canvasId, { is_archived: true });
            this.showUISettingsModal = false;
            window.location.href = '/beakcortex/';
        },

        async deleteCurrentCanvas() {
            if (!confirm('永久刪除此白板？卡片不受影響，但白板上的佈局將無法復原。')) return;
            await API.deleteCanvas(this.canvasId);
            this.showUISettingsModal = false;
            window.location.href = '/beakcortex/';
        },

        async loadCanvases() {
            var all = await API.getCanvases(true);
            this.archivedCanvasCount = all.filter(c => c.is_archived).length;
            this.canvases = this.showArchivedCanvases ? all : all.filter(c => !c.is_archived);
        },

        get canvasGroups() {
            var map = {};
            var order = ['ethan', 'claude'];
            (this.canvases || []).forEach(c => {
                var o = c.owner || 'ethan';
                if (!map[o]) map[o] = [];
                map[o].push(c);
            });
            var result = [];
            order.forEach(o => { if (map[o]) { result.push({ owner: o, items: map[o] }); delete map[o]; } });
            Object.keys(map).sort().forEach(o => { result.push({ owner: o, items: map[o] }); });
            return result;
        },

        ownerDisplayName(owner) {
            if (owner === 'ethan') return 'Ethan';
            if (owner === 'claude') return 'Claude';
            if (owner && owner.startsWith('agent:')) return 'Agent';
            if (owner && owner.startsWith('claude@')) return 'Claude (' + owner.split('@')[1] + ')';
            if (owner && owner.startsWith('tool:')) return 'Tool';
            return owner || 'Unknown';
        },

        // ============================================
        // Context Menu
        // ============================================
        onCanvasContextMenu(e) { e.preventDefault(); this.contextMenu = { x: e.clientX, y: e.clientY, type: 'canvas' }; },
        onCardContextMenu(e, ca) { e.preventDefault(); e.stopPropagation(); this.contextMenu = { x: e.clientX, y: e.clientY, type: 'card', ca: ca }; },
        closeContextMenu() { this.contextMenu = null; },
        contextAddAtom() { this.openNewAtomModal({ clientX: this.contextMenu.x, clientY: this.contextMenu.y }); this.closeContextMenu(); },

        // ============================================
        // Block Chain & Navigation
        // ============================================
        async traceBlockChain(atomId) {
            try { var result = await API.getBlockChain(atomId); this.blockChain = result; this.highlightedAtomIds = (result.chain || []).map(function(n) { return n.atom_id; }); }
            catch (e) { console.error('Failed to trace block chain:', e); }
        },

        navigateToAtom(atomId) {
            var ca = this.atoms.find(function(a) { return a.atom_id === atomId; }); if (!ca) return;
            this.selectCard(atomId); var vp = this.$refs.viewport;
            if (vp) { var rect = vp.getBoundingClientRect(); this.panX = rect.width / 2 - (ca.pos_x + 130) * this.zoom; this.panY = rect.height / 2 - (ca.pos_y + 80) * this.zoom; this.updateTransform(); this.renderConnections(); this.saveViewport(); }
        },

        isAtomOnCanvas(atomId) { return this.atoms.some(function(ca) { return ca.atom_id === atomId; }); },

        // ============================================
        // Markdown Rendering
        // ============================================
        _markedInited: false,

        initMarked() {
            if (this._markedInited || typeof marked === 'undefined') return;
            marked.use({ breaks: true, gfm: true }); this._markedInited = true;
        },

        renderMarkdown(text, maxLen) {
            if (!text) return ''; this.initMarked();
            var src = maxLen && text.length > maxLen ? text.substring(0, maxLen) + '...' : text;
            try { return marked.parse(src); }
            catch (e) { return src.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>'); }
        },

        // ============================================
        // Toast
        // ============================================
        showToast(msg, type, duration) {
            var id = ++this._toastSeq; this.toasts.push({ id: id, msg: msg, type: type || 'info', duration: duration || 4000 });
        },

        removeToast(id) { this.toasts = this.toasts.filter(function(t) { return t.id !== id; }); },

        // ============================================
        // Utilities
        // ============================================
        async changePassword() {
            this.pwMsg = '';
            if (!this.pwOld) { this.pwMsg = '請輸入舊密碼'; this.pwMsgOk = false; return; }
            if (!this.pwNew || this.pwNew.length < 8) { this.pwMsg = '新密碼至少 8 字元'; this.pwMsgOk = false; return; }
            if (this.pwNew !== this.pwConfirm) { this.pwMsg = '新密碼不一致'; this.pwMsgOk = false; return; }
            try {
                var resp = await API.put('/beakcortex/api/auth/change-password', { old_password: this.pwOld, new_password: this.pwNew });
                this.pwMsg = resp.message || '密碼已變更'; this.pwMsgOk = true;
                this.pwOld = ''; this.pwNew = ''; this.pwConfirm = '';
            } catch (e) {
                this.pwMsg = e.message || '變更失敗'; this.pwMsgOk = false;
            }
        },

        truncate(text, n) { if (!text) return ''; return text.length > n ? text.substring(0, n) + '...' : text; },
        formatDate(iso) { if (!iso) return ''; return new Date(iso).toLocaleString('zh-TW'); },
    };

    // 合併所有 mixin
    _mergeInto(app, whiteboardConnectionsMixin());
    _mergeInto(app, whiteboardMinimapMixin());
    _mergeInto(app, whiteboardCardEditorMixin());
    _mergeInto(app, whiteboardUndoMixin());
    _mergeInto(app, whiteboardBatchMixin());
    _mergeInto(app, whiteboardGroupsMixin());

    return app;
}
