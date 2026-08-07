/**
 * BeakBroodNest 白板引擎
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
        textboxes: [],
        standaloneEntries: [],
        seMenuOpen: false,
        mindmapShells: [],
        treeParents: [],
        canvases: [],
        tags: [],
        tagCategories: [],
        entrySchemas: [],

        // Viewport
        panX: 0, panY: 0, zoom: 1,
        isPanning: false,
        panStartX: 0, panStartY: 0,
        hasStoredViewport: false,

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

        // 圈選統一尺寸：等待用戶點選基準卡片
        pickSizeTargetMode: false,

        // 圈選對齊：等待用戶點選基準卡片，pendingAlignType ∈ left/center/right/top/middle/bottom
        pickAlignTargetMode: false,
        pendingAlignType: null,

        // Selection
        selectedAtomId: null,
        showPanel: false,

        // Context menu
        contextMenu: null,

        // Modals
        showNewAtomModal: false,
        showTrashModal: false,
        trashItems: [],

        // 徹底刪除防呆 modal
        showHardDeleteModal: false,
        hardDeleteAtomId: null,
        hardDeleteAtomTitle: '',
        hardDeleteUsage: null,
        hardDeleteSelectedCanvasIds: [],

        // 交換卡片
        showExchangeModal: false,
        exchangeTab: 'take',          // 'stash' | 'take'
        exchangeView: 'list',         // 'list' | 'detail'（取出 tab 用）
        exchangePacks: [],
        exchangePackDetail: null,
        exchangeSelectedAtomIds: [],
        exchangeStashName: '',
        exchangeStashMode: 'copy',    // 'copy' | 'move'
        exchangeFollowItem: null,     // 單張取用滑鼠跟隨的卡片資料
        exchangeFollowPackId: null,
        exchangeFollowMouseX: 0,
        exchangeFollowMouseY: 0,
        showNewCanvasModal: false,
        showRelationModal: false,
        showConnTypeModal: false,
        connTypeChangeTarget: null,
        connTypeChangeLabel: '',
        connTypeChangeColor: '',  // 空字串=用 relation_type 預設色

        // 共用視覺色板（連線、殼底色、節點視覺）
        bcColorPalette: [
            '#94a3b8', '#3b82f6', '#ef4444', '#f59e0b',
            '#10b981', '#8b5cf6', '#ec4899', '#0891b2', '#64748b',
        ],
        get connColorPalette() { return this.bcColorPalette; },
        get shellColorPalette() { return this.bcColorPalette; },
        get nodeColorPalette() { return this.bcColorPalette; },
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
        newAtom: { title: '', content: '', atom_type: 'A' },
        newAtomPos: { x: 100, y: 100 },
        newCanvasName: '',
        newTagName: '',
        newTagColor: '#6b7280',
        tagSourceFilter: 'human',  // 'human' | 'ai' | 'all'，預設只看自己建立的
        tagIncludeHidden: false,
        tagManageMode: false,
        tagEditingId: null,
        tagEditingName: '',
        // Canvas sidebar：最近開啟（localStorage）與下拉清單 + 標籤多選過濾
        recentCanvasSlugs: [],
        canvasDropdownOpen: false,
        canvasTagFilter: [],       // 選中的人類標籤 id 陣列；空=不過濾
        RECENT_CANVAS_MAX: 7,
        pendingConnection: null,
        selectedRelationType: 'follows',
        relationLabel: '',

        // Connection drag (from anchors)
        isConnDragging: false,
        connDragSourceKind: null,         // 'atom' | 'textbox'
        connDragSourceAtomId: null,
        connDragSourceTextboxId: null,
        connDragSourceAnchor: null,
        connDragHoverAtomId: null,
        connDragHoverTextboxId: null,
        connDragMouseX: 0,
        connDragMouseY: 0,

        // Entry-level connection drag
        connDragSourceEntryId: null,
        connDragHoverEntryId: null,

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
        groupForm: { name: '', color: '#3b82f6', border_style: 'none' },

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
        rtEngine: 'individual',
        rtOptEnabled: false,
        rtOptPerSector: 10,
        rtPanelOpen: false,

        // -- Card Size Mode --
        cardSizeMode: 'default',  // 'min' | 'default' | 'full'
        cardSizeModeLabels: { min: '精簡', 'default': '標準', full: '展開' },

        // -- 縮圖卡標題顯示模式 --
        // false (預設) = hover 0.5s 後浮現；true = 一律顯示
        showThumbnailTitle: false,

        // 拖曳物件時是否顯示格線底（吸附功能不受此開關影響）
        showDragGrid: true,

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
            { value: 'freeform',     label: '自由',   desc: 'A -> B',         color: '#000000', sched: false, strength: '無約束' },
            { value: 'contains',     label: '包含',   desc: 'A 包含 B',       color: '#6b7280', sched: false, strength: 'WBS 結構' },
            { value: 'blocks',       label: '阻塞',   desc: 'A 擋住 B',       color: '#dc2626', sched: true,  strength: '硬約束' },
            { value: 'follows',      label: '順序',   desc: 'B 在 A 之後',     color: '#f59e0b', sched: true,  strength: '軟約束' },
            { value: 'enables',      label: '啟用',   desc: 'A 使 B 可能',     color: '#10b981', sched: false, strength: '前提條件' },
            { value: 'causes',       label: '因果',   desc: 'A 導致 B',       color: '#8b5cf6', sched: false, strength: '事實描述' },
            { value: 'supports',     label: '支持',   desc: 'A 支持 B',       color: '#3b82f6', sched: false, strength: '論證' },
            { value: 'contradicts',  label: '矛盾',   desc: 'A 與 B 互斥',     color: '#ef4444', sched: false, strength: '論證' },
            { value: 'derives_from', label: '衍生',   desc: 'B 衍生自 A',      color: '#6366f1', sched: false, strength: '知識演化' },
            { value: 'supersedes',   label: '取代',   desc: 'A 取代 B',       color: '#64748b', sched: false, strength: '版本替換' },
            { value: 'references',   label: '參考',   desc: 'A 參考 B',       color: '#94a3b8', sched: false, strength: '無約束' },
        ],

        relationLabelMap: {
            freeform: '自由', causes: '因果', enables: '啟用', supports: '支持',
            contradicts: '矛盾', derives_from: '衍生', supersedes: '取代',
            follows: '順序', contains: '包含', references: '參考', blocks: '阻塞',
        },

        // ============================================
        // Init
        // ============================================
        // 雙陣列分流：心智圖節點與一般卡片各自獨立 iterate，避免兩個 template 重複 render
        // 用 getter 而非預先計算欄位，alpine reactivity 會自動 track this.atoms 變更
        // ============================================
        get cardAtoms() {
            return this.atoms.filter(function(ca) {
                var v = ca && ca.mindmap_shell_id;
                return v === null || v === undefined;
            });
        },
        get mindmapAtoms() {
            return this.atoms.filter(function(ca) {
                var v = ca && ca.mindmap_shell_id;
                return v !== null && v !== undefined;
            });
        },

        // ============================================
        async init() {
            var urlParams = new URLSearchParams(window.location.search);
            var rm = urlParams.get('render');
            if (rm === 'straight' || rm === 'optimized' || rm === 'opt-straight') this.renderMode = rm;
            if (rm === 'straight')      { this.rtLineStyle = 'straight'; }
            if (rm === 'optimized')     { this.rtOptEnabled = true; }
            if (rm === 'opt-straight')  { this.rtLineStyle = 'straight'; this.rtOptEnabled = true; }

            this.initMarked();
            this.loadRecentCanvases();
            this.loadCanvasTagFilter();
            await this.loadData();
            // 記錄最後活躍的白板 slug,讓其他頁面(如 Backlog)能預設聚焦此專案
            try {
                if (this.canvasId) {
                    API.setPreference('last_active_canvas_slug', this.canvasId).catch(function() {});
                    this.pushRecentCanvas(this.canvasId);
                }
            } catch (e) {}
            this.$nextTick(() => {
                // 重算所有群組邊框（含巢狀偏移）
                var self0 = this;
                this.groups.forEach(function(g) { self0.recalcGroupBounds(g.id); });
                this.renderConnections();
                this.setupWheelZoom();
                if (this.atoms.length > 0 && !this.hasStoredViewport) this.fitView();
                this.renderMinimap();
                // 啟動遠端變更偵測
                this.startPolling();
                // ?open=<atom_id> 自動開啟卡片編輯器（行事曆等外部頁面跳轉用）
                try {
                    var openId = parseInt(urlParams.get('open'), 10);
                    var openFrom = urlParams.get('from') === 'todos' ? 'todos' : null;
                    if (!isNaN(openId) && typeof self0.openCardEditor === 'function') {
                        self0.openCardEditor(openId, openFrom);
                    }
                } catch (e) { console.warn('open param failed', e); }
            });
            const self = this;
            // 用穩定的 bound handler 註冊，addEventListener 以 (event, handler, capture) 三元組去重，
            // 即使 init() 被呼叫多次（如 alpine 重建 scope），同一 handler 只註冊一次
            if (!this._kbdHandler) {
                this._kbdHandler = function(e) { self.handleKeyDown(e); };
                document.addEventListener('keydown', this._kbdHandler);
                if (this._ceInstallBeforeUnload) this._ceInstallBeforeUnload();
            }
            if (!this._mupHandler) {
                this._mupHandler = function() {
                    if (self.isConnDragging) self.cancelConnDrag();
                    // 防卡:document 層級兜底,若 viewport mouseup 沒收到事件
                    // (滑鼠在白板外放開),強制清掉 panning / rightDragPending 狀態
                    if (self.isPanning) { self.isPanning = false; self.saveViewport(); }
                    if (self.rightDragPending) { self.rightDragPending = false; self.rightDragTarget = null; }
                };
                document.addEventListener('mouseup', this._mupHandler);
            }
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
            // 點到非心智圖元素 -> 自動離開心智圖模式
            // 否則 active 節點殘留,白板 Tab/Enter/Del 會被 handleMindmapKeyDown 攔去操作心智圖
            this.$refs.viewport.addEventListener('mousedown', function(e) {
                if (!self.activeMindmapAtomId && !self.activeMindmapShellId) return;
                var t = e.target;
                if (t && t.closest && t.closest('.wb-mindmap-shell, .wb-mindmap-node')) return;
                self.leaveMindmapMode();
            }, true);
            window.addEventListener('pagehide', function() {
                if (self.isSnapshot || !self.canvasId) return;
                try {
                    fetch('/beakbroodnest/api/canvases/' + self.canvasId, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            viewport_x: self.panX,
                            viewport_y: self.panY,
                            viewport_zoom: self.zoom,
                        }),
                        keepalive: true,
                    });
                } catch (e) { /* best-effort, ignore */ }
            });
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
            this.textboxes = canvas.textboxes || [];
            this.standaloneEntries = canvas.standalone_entries || [];
            this.mindmapShells = canvas.mindmap_shells || [];
            this.treeParents = canvas.tree_parents || [];
            // 載入後重算心智圖樹的 layout（位置即時從關係樹推導）
            if (this._rebuildTreeIndex) {
                this._rebuildTreeIndex();
                this.recalcAllMindmapLayouts();
            }
            this.archivedCanvasCount = allCanvases.filter(c => c.is_archived).length;
            this.canvases = this.showArchivedCanvases ? allCanvases : allCanvases.filter(c => !c.is_archived);
            this.tags = tags;
            this.tagCategories = tagCategories;
            this.entrySchemas = entrySchemas;
            this.refreshSidebarAtoms();
            if (canvas.viewport_x || canvas.viewport_y || (canvas.viewport_zoom && canvas.viewport_zoom !== 1)) {
                this.panX = canvas.viewport_x || 0; this.panY = canvas.viewport_y || 0;
                this.zoom = canvas.viewport_zoom || 1; this.updateTransform();
                this.hasStoredViewport = true;
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
                    if (settings.showThumbnailTitle !== undefined) {
                        this.showThumbnailTitle = !!settings.showThumbnailTitle;
                    }
                    if (settings.showDragGrid !== undefined) {
                        this.showDragGrid = !!settings.showDragGrid;
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
                // Shift+wheel 或滑鼠在卡片 body 上：捲動卡片內容，不縮放
                var scrollTarget = e.target.closest('.wb-card-body');
                if (scrollTarget && (e.shiftKey || scrollTarget.scrollHeight > scrollTarget.clientHeight)) {
                    scrollTarget.scrollTop += e.deltaY;
                    e.preventDefault(); e.stopPropagation(); return;
                }
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
            // 交換卡片單張取用：滑鼠跟隨中，點空白處放下
            if (this.exchangeFollowItem && this._tryHandleExchangeFollowDrop && this._tryHandleExchangeFollowDrop(e)) return;
            if (this.editingAtomId && document.activeElement) document.activeElement.blur();
            if (e.button === 1) { this.isPanning = true; this.panStartX = e.clientX - this.panX; this.panStartY = e.clientY - this.panY; e.preventDefault(); return; }
            if (e.button === 2) return;
            if (e.button === 0) {
                if (this.mode === 'connect' && !e.target.closest('.wb-card')) { this.connSourceAtomId = null; this.mode = 'select'; return; }
                if (!e.target.closest('.wb-card') && !e.target.closest('.wb-group') && !e.target.closest('.wb-textbox') && !e.target.closest('.wb-toolbar') && !e.target.closest('.wb-zoom')) {
                    this.boxSelectPending = true;
                    this.boxSelectStartX = e.clientX; this.boxSelectStartY = e.clientY;
                    this.boxSelectCurrentX = e.clientX; this.boxSelectCurrentY = e.clientY;
                    e.preventDefault();
                }
            }
        },

        onViewportMouseMove(e) {
            // 防卡:若 isPanning 或 rightDragPending 仍在,但鼠標已無按鍵按住,
            // 代表 mouseup 在視窗外丟失了。立即重置避免游標卡在 grabbing 狀態。
            if (e.buttons === 0) {
                if (this.isPanning) { this.isPanning = false; this.saveViewport(); }
                if (this.rightDragPending) { this.rightDragPending = false; this.rightDragTarget = null; }
            }
            if (this.exchangeFollowItem && this._updateExchangeFollowPos) { this._updateExchangeFollowPos(e); return; }
            // 心智圖節點同層拖曳排序（優先）
            if (this._handleMindmapDragMove && this._handleMindmapDragMove(e)) return;
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
                var otherGroups = new Set();
                this.atoms.forEach(function(a) {
                    if (self.groupDragMemberStarts[a.atom_id]) {
                        a.pos_x = self.groupDragMemberStarts[a.atom_id].x + gdx;
                        a.pos_y = self.groupDragMemberStarts[a.atom_id].y + gdy;
                        // 成員所屬的其他群組也需要重繪
                        if (a.group_ids) a.group_ids.forEach(function(gid) {
                            if (gid !== self.dragGroup.id) otherGroups.add(gid);
                        });
                    }
                });
                otherGroups.forEach(function(gid) { self.recalcGroupBounds(gid); });
                this.renderConnections(); return;
            }
            if (this.resizeGroup) { this.resizeGroup.width = Math.max(160, this.resizeGroupStartW + (e.clientX - this.resizeGroupStartX) / this.zoom); this.resizeGroup.height = Math.max(80, this.resizeGroupStartH + (e.clientY - this.resizeGroupStartY) / this.zoom); return; }
            if (this.dragTextbox) {
                var tdx = (e.clientX - this.textboxDragStartX) / this.zoom;
                var tdy = (e.clientY - this.textboxDragStartY) / this.zoom;
                this.dragTextbox.pos_x = this.textboxDragStartPos.x + tdx;
                this.dragTextbox.pos_y = this.textboxDragStartPos.y + tdy;
                this.renderConnections();
                return;
            }
            if (this.dragStandaloneEntry) {
                this.onStandaloneEntryMouseMove(e);
                this.renderConnections();
                return;
            }
            if (this.dragMindmapShell) {
                var mdx = (e.clientX - this.mindmapShellDragStartX) / this.zoom;
                var mdy = (e.clientY - this.mindmapShellDragStartY) / this.zoom;
                this.dragMindmapShell.pos_x = this.mindmapShellDragStartPos.x + mdx;
                this.dragMindmapShell.pos_y = this.mindmapShellDragStartPos.y + mdy;
                var selfM = this;
                this.atoms.forEach(function(ca) {
                    var s = selfM.mindmapShellDragMemberStarts && selfM.mindmapShellDragMemberStarts[ca.atom_id];
                    if (s) { ca.pos_x = s.x + mdx; ca.pos_y = s.y + mdy; }
                });
                this.renderConnections();
                return;
            }
            if (this.resizeTextbox) {
                this.resizeTextbox.width = Math.max(160, this.resizeTextboxStartW + (e.clientX - this.resizeTextboxStartX) / this.zoom);
                this.resizeTextbox.height = Math.max(80, this.resizeTextboxStartH + (e.clientY - this.resizeTextboxStartY) / this.zoom);
                this.renderConnections();
                return;
            }
            if (this.resizeCard) {
                this.resizeCard.width = Math.max(160, this.resizeStartW + (e.clientX - this.resizeStartX) / this.zoom);
                this.resizeCard.height = Math.max(80, this.resizeStartH + (e.clientY - this.resizeStartY) / this.zoom);
                if (this.resizeCard.group_ids) this.resizeCard.group_ids.forEach(gid => this.recalcGroupBounds(gid));
                this.renderConnections(); return;
            }
            if (this.dragCard) {
                var dx = (e.clientX - this.dragStartX) / this.zoom, dy = (e.clientY - this.dragStartY) / this.zoom;
                var affectedGroups = new Set();
                if (this.multiDragStarts) {
                    var self = this;
                    this.atoms.forEach(function(a) { if (self.multiDragStarts[a.atom_id]) { a.pos_x = self.multiDragStarts[a.atom_id].x + dx; a.pos_y = self.multiDragStarts[a.atom_id].y + dy; if (a.group_ids) a.group_ids.forEach(function(gid) { affectedGroups.add(gid); }); } });
                } else {
                    this.dragCard.pos_x = this.cardStartX + dx; this.dragCard.pos_y = this.cardStartY + dy;
                    if (this.dragCard.group_ids) this.dragCard.group_ids.forEach(function(gid) { affectedGroups.add(gid); });
                }
                var self2 = this; affectedGroups.forEach(function(gid) { self2.recalcGroupBounds(gid); });
                this.renderConnections();
            }
        },

        onViewportMouseUp(e) {
            // 心智圖節點拖曳結算（優先）
            if (this._handleMindmapDragUp && this._handleMindmapDragUp(e)) return;
            if (this.rightDragPending) {
                this.rightDragPending = false; var tgt = this.rightDragTarget; this.rightDragTarget = null;
                if (tgt && !tgt._isGroup) {
                    this.contextMenu = { x: e.clientX, y: e.clientY, type: 'card', ca: tgt };
                } else {
                    // 找出座標下所有群組
                    var cp = this.screenToCanvas(e.clientX, e.clientY);
                    var hitGroups = this.groups.filter(function(g) {
                        return cp.x >= g.pos_x && cp.x <= g.pos_x + g.width &&
                               cp.y >= g.pos_y && cp.y <= g.pos_y + g.height;
                    });
                    if (hitGroups.length > 0) {
                        this.contextMenu = { x: e.clientX, y: e.clientY, type: 'groups', groups: hitGroups };
                    } else {
                        this.contextMenu = { x: e.clientX, y: e.clientY, type: 'canvas' };
                    }
                }
                return;
            }
            if (this.isBoxSelecting) { this.isBoxSelecting = false; this.boxSelectPending = false; if (this.selectedAtomIds.length >= 2) { this.batchBarX = e.clientX; this.batchBarY = e.clientY - 10; } return; }
            if (this.boxSelectPending) { this.boxSelectPending = false; this.selectedAtomIds = []; this.deselectCard(); return; }
            if (this.bodyDragPending) { this.bodyDragPending = false; var ca = this.bodyDragCa; this.bodyDragCa = null; if (ca) { this.selectCard(ca.atom_id); this.startInlineEdit(ca); } return; }
            if (this.isConnDragging) { this.endConnDrag(); return; }
            if (this.isPanning) { this.isPanning = false; this.saveViewport(); }
            if (this.dragGroup) {
                this.dragGroup.pos_x = this.snap10(this.dragGroup.pos_x);
                this.dragGroup.pos_y = this.snap10(this.dragGroup.pos_y);
                API.updateGroup(this.dragGroup.id, { pos_x: this.dragGroup.pos_x, pos_y: this.dragGroup.pos_y });
                var self = this;
                this.atoms.forEach(function(a) {
                    if (self.groupDragMemberStarts && self.groupDragMemberStarts[a.atom_id]) {
                        a.pos_x = self.snap10(a.pos_x); a.pos_y = self.snap10(a.pos_y);
                        API.updateCanvasAtom(a.id, { pos_x: a.pos_x, pos_y: a.pos_y });
                    }
                });
                this.dragGroup = null; this.groupDragMemberStarts = null;
                this.renderConnections();
            }
            if (this.resizeGroup) { API.updateGroup(this.resizeGroup.id, { width: this.resizeGroup.width, height: this.resizeGroup.height }); this.resizeGroup = null; }
            if (this.dragTextbox) {
                this.dragTextbox.pos_x = this.snap10(this.dragTextbox.pos_x);
                this.dragTextbox.pos_y = this.snap10(this.dragTextbox.pos_y);
                API.updateTextbox(this.dragTextbox.id, { pos_x: this.dragTextbox.pos_x, pos_y: this.dragTextbox.pos_y });
                this.dragTextbox = null;
            }
            if (this.dragStandaloneEntry) {
                this.onStandaloneEntryMouseUp();
                this.renderConnections();
            }
            if (this.dragMindmapShell) {
                var sh = this.dragMindmapShell;
                sh.pos_x = this.snap10(sh.pos_x); sh.pos_y = this.snap10(sh.pos_y);
                API.updateMindmapShell(sh.id, { pos_x: sh.pos_x, pos_y: sh.pos_y });
                var selfMM = this;
                this.atoms.forEach(function(ca) {
                    if (selfMM.mindmapShellDragMemberStarts && selfMM.mindmapShellDragMemberStarts[ca.atom_id]) {
                        ca.pos_x = selfMM.snap10(ca.pos_x); ca.pos_y = selfMM.snap10(ca.pos_y);
                        API.updateCanvasAtom(ca.id, { pos_x: ca.pos_x, pos_y: ca.pos_y });
                    }
                });
                this.dragMindmapShell = null;
                this.mindmapShellDragMemberStarts = null;
                this.renderConnections();
            }
            if (this.resizeTextbox) {
                API.updateTextbox(this.resizeTextbox.id, { width: this.resizeTextbox.width, height: this.resizeTextbox.height });
                this.resizeTextbox = null;
            }
            if (this.resizeCard) { if (this.resizeCard.id > 0) { API.updateCanvasAtom(this.resizeCard.id, { width: this.resizeCard.width, height: this.resizeCard.height }); } if (this.resizeCard.group_ids) this.resizeCard.group_ids.forEach(gid => this.autoResizeGroup(gid)); this.resizeCard = null; }
            if (this.dragCard) {
                this._justDragged = true;
                // 拖到心智圖殼/節點上 → 收入心智圖（不再走位置儲存）
                if (this._tryAttachDragToMindmap && this._tryAttachDragToMindmap(e)) {
                    if (this.multiDragStarts) this.multiDragStarts = null;
                    this.dragCard = null;
                    return;
                }
                var groupsToResize = new Set(); var movedIds = []; var beforePos = []; var afterPos = [];
                if (this.multiDragStarts) {
                    var self = this;
                    this.atoms.forEach(function(a) { if (self.multiDragStarts[a.atom_id]) { a.pos_x = self.snap10(a.pos_x); a.pos_y = self.snap10(a.pos_y); movedIds.push(a.atom_id); beforePos.push({ x: self.multiDragStarts[a.atom_id].x, y: self.multiDragStarts[a.atom_id].y }); afterPos.push({ x: a.pos_x, y: a.pos_y }); if (a.id > 0) { API.updateCanvasAtom(a.id, { pos_x: a.pos_x, pos_y: a.pos_y }); } if (a.group_ids) a.group_ids.forEach(function(gid) { groupsToResize.add(gid); }); } });
                    this.multiDragStarts = null;
                } else {
                    this.dragCard.pos_x = this.snap10(this.dragCard.pos_x); this.dragCard.pos_y = this.snap10(this.dragCard.pos_y);
                    movedIds.push(this.dragCard.atom_id); beforePos.push({ x: this.cardStartX, y: this.cardStartY }); afterPos.push({ x: this.dragCard.pos_x, y: this.dragCard.pos_y });
                    if (this.dragCard.id > 0) { API.updateCanvasAtom(this.dragCard.id, { pos_x: this.dragCard.pos_x, pos_y: this.dragCard.pos_y }); }
                    if (this.dragCard.group_ids) this.dragCard.group_ids.forEach(function(gid) { groupsToResize.add(gid); });
                }
                if (movedIds.length > 0 && (beforePos[0].x !== afterPos[0].x || beforePos[0].y !== afterPos[0].y)) this.pushMoveUndo(movedIds, beforePos, afterPos);
                var self2 = this; groupsToResize.forEach(function(gid) { self2.autoResizeGroup(gid); });
                this.dragCard = null;
                this.renderConnections();
            }
        },

        updateTransform() {
            const c = this.$refs.canvas;
            if (c) c.style.transform = `translate(${this.panX}px, ${this.panY}px) scale(${this.zoom})`;
            const v = this.$refs.viewport;
            if (v) {
                const s = 10 * this.zoom;
                v.style.backgroundSize = `${s}px ${s}px`;
                v.style.backgroundPosition = `${this.panX}px ${this.panY}px`;
            }
            this.renderMinimap();
        },

        saveViewport() { if (this.isSnapshot) return; API.updateCanvas(this.canvasId, { viewport_x: this.panX, viewport_y: this.panY, viewport_zoom: this.zoom }); },
        _zoomAround(newZoom) {
            const vp = this.$refs.viewport;
            const rect = vp ? vp.getBoundingClientRect() : { width: 0, height: 0 };
            const cx = rect.width / 2, cy = rect.height / 2;
            const wx = (cx - this.panX) / this.zoom;
            const wy = (cy - this.panY) / this.zoom;
            this.zoom = newZoom;
            this.panX = cx - wx * newZoom;
            this.panY = cy - wy * newZoom;
            this.updateTransform(); this.renderConnections(); this.saveViewport();
        },
        zoomIn() { this._zoomAround(Math.min(3, this.zoom * 1.2)); },
        zoomOut() { this._zoomAround(Math.max(0.15, this.zoom / 1.2)); },
        resetZoom() { this.fitView(); },

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

        snap10(v) { return Math.round(v / 10) * 10; },
        get isObjectDragging() {
            return !!(this.dragCard || this.dragTextbox || this.dragMindmapShell || this.dragGroup || this.dragStandaloneEntry);
        },

        // ============================================
        // Card Operations
        // ============================================
        onCardMouseDown(e, ca) {
            if (e.button !== 0 || this.mode === 'connect') return;
            if (this.pickSizeTargetMode) {
                e.stopPropagation(); e.preventDefault();
                this.applyUniformSize(ca);
                return;
            }
            if (this.pickAlignTargetMode) {
                e.stopPropagation(); e.preventDefault();
                this.applyAlign(ca);
                return;
            }
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
            if (this.pickSizeTargetMode) {
                e.stopPropagation(); e.preventDefault();
                this.applyUniformSize(ca);
                return;
            }
            if (this.pickAlignTargetMode) {
                e.stopPropagation(); e.preventDefault();
                this.applyAlign(ca);
                return;
            }
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
        // 完全離開心智圖模式（含清空方向鍵停留位置）。僅在用戶明確點到非心智圖元素時呼叫。
        leaveMindmapMode() { this.activeMindmapAtomId = null; this.activeMindmapShellId = null; this.editingMindmapAtomId = null; },

        onCardClick(ca) {
            if (this._justDragged) { this._justDragged = false; return; }
            if (this.pickSizeTargetMode || this.pickAlignTargetMode) return;
            this.selectedAtomIds = []; this.selectCard(ca.atom_id);
        },

        async onCardDblClick(ca) {
            if (this.pickSizeTargetMode || this.pickAlignTargetMode) return;
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
            const border = type === 'F' ? '1px dashed ' + cfg.border : '1px solid ' + cfg.border;
            var s = 'left:' + ca.pos_x + 'px; top:' + ca.pos_y + 'px; z-index:' + (ca.z_index || 10) + '; border:' + border + '; opacity:' + opacity + ';';
            if (ca.width) s += ' width:' + ca.width + 'px;'; if (ca.height) s += ' height:' + ca.height + 'px;';
            return s;
        },

        getTypeBadgeStyle(type) { const cfg = this.atomTypeConfig[type] || this.atomTypeConfig.F; return 'background:' + cfg.bg + '; color:' + cfg.color + ';'; },

        cycleCardSizeMode() {
            const order = ['min', 'default', 'full'];
            const idx = order.indexOf(this.cardSizeMode);
            this.cardSizeMode = order[(idx + 1) % order.length];
            this.applyCardSizeMode();
        },

        toggleShowThumbnailTitle() {
            this.showThumbnailTitle = !this.showThumbnailTitle;
            this._saveShowThumbnailTitle();
        },

        // 清空當前白板字紙簍（不影響 atom 本體；其他白板的引用也不受影響）
        async emptyTrash() {
            if (!confirm('清空此白板的字紙簍？\n卡片本體與其他白板的引用不受影響，但本白板將無法救回這些卡片。')) return;
            try {
                var resp = await API.emptyCanvasTrash(this.canvasId);
                this.showToast(resp.message || ('已清空 ' + (resp.deleted || 0) + ' 筆'), 'success');
                this.trashItems = [];
                this.showTrashModal = false;
            } catch (e) {
                this.showToast('清空失敗：' + (e.message || e), 'error');
            }
        },

        // 列出當前白板字紙簍（含 atom 與 textbox 兩種 kind）
        async openTrashModal() {
            this.showTrashModal = true;
            try {
                var resp = await API.listCanvasTrash(this.canvasId);
                this.trashItems = (resp.items || []).map(function(t) {
                    if (t.kind === 'textbox') {
                        var p = t.textbox_preview || {};
                        return {
                            kind: 'textbox',
                            _trash_id: t.id,
                            id: 'tb-' + t.id,  // x-for :key 用
                            title: p.title || '(無標題)',
                            thumbnail_url: null,
                            content_preview: p.content_preview || '',
                            atom_type: 'TXT',
                            updated_at: t.deleted_at,
                        };
                    }
                    return {
                        kind: 'atom',
                        id: t.atom_id,
                        title: t.atom ? t.atom.title : '(無標題)',
                        thumbnail_url: t.atom ? t.atom.thumbnail_url : null,
                        atom_type: t.atom ? t.atom.atom_type : 'F',
                        updated_at: t.deleted_at,
                    };
                });
            } catch (e) {
                this.showToast('讀取字紙簍失敗：' + (e.message || e), 'error');
                this.trashItems = [];
            }
        },

        // 救回此白板字紙簍中的項目（atom 或 textbox 統一入口）
        async restoreFromTrash(itemId) {
            // 找到項目區分 kind
            var item = this.trashItems.find(function(x) { return x.id === itemId; });
            if (!item) return;
            try {
                if (item.kind === 'textbox') {
                    await API.restoreTextboxesFromTrash(this.canvasId, [item._trash_id]);
                } else {
                    await API.restoreFromCanvasTrash(this.canvasId, [item.id]);
                }
                this.trashItems = this.trashItems.filter(function(t) { return t.id !== itemId; });
                await this.loadData();
                var self = this;
                this.$nextTick(function() { self.renderConnections(); });
                this.showToast('已救回到原位置', 'success');
            } catch (e) {
                this.showToast('救回失敗：' + (e.message || e), 'error');
            }
        },

        _saveShowThumbnailTitle() {
            if (this.isSnapshot) return;
            var settings;
            try { settings = JSON.parse((this.canvas && this.canvas.settings) || '{}'); } catch (e) { settings = {}; }
            settings.showThumbnailTitle = this.showThumbnailTitle;
            API.updateCanvas(this.canvasId, { settings: JSON.stringify(settings) });
        },

        toggleShowDragGrid() {
            this.showDragGrid = !this.showDragGrid;
            if (this.isSnapshot) return;
            var settings;
            try { settings = JSON.parse((this.canvas && this.canvas.settings) || '{}'); } catch (e) { settings = {}; }
            settings.showDragGrid = this.showDragGrid;
            API.updateCanvas(this.canvasId, { settings: JSON.stringify(settings) });
        },

        // 縮圖卡判定：atom 顯式設定了 thumbnail_url
        hasThumbnail(ca) {
            return !!(ca && ca.atom && ca.atom.thumbnail_url);
        },

        // 主帳卡縮圖判定：卡片內含 idcard entry 且 is_primary=true
        primaryIdCardEntry(ca) {
            if (!ca || !ca.atom || !ca.atom.entries) return null;
            for (var i = 0; i < ca.atom.entries.length; i++) {
                var e = ca.atom.entries[i];
                if (e.schema_code !== 'idcard') continue;
                var fv = e.field_values || {};
                if (fv.is_primary === 'true' || fv.is_primary === true) {
                    return e;
                }
            }
            return null;
        },
        hasPrimaryIdCard(ca) {
            return this.primaryIdCardEntry(ca) !== null;
        },
        primaryIdCardImageUrl(ca) {
            var e = this.primaryIdCardEntry(ca);
            if (!e) return '';
            var token = ((e.field_values || {}).image_token || '').trim();
            return token ? '/beakbroodnest/files/' + encodeURIComponent(token) : '';
        },
        primaryIdCardLine(ca, n) {
            var e = this.primaryIdCardEntry(ca);
            if (!e) return '';
            return ((e.field_values || {})['line' + n] || '').trim();
        },

        // 心智圖節點代表圖：取 Card 內第一個有 image_token 的 ;;image 或 ;;idcard entry
        // idcard 也納入是因為它本來就是「左圖右文」結構，圖檔資料同欄位
        mindmapNodeImageEntry(ca) {
            if (!ca || !ca.atom || !ca.atom.entries) return null;
            for (var i = 0; i < ca.atom.entries.length; i++) {
                var e = ca.atom.entries[i];
                if (e.schema_code !== 'image' && e.schema_code !== 'idcard') continue;
                var tok = ((e.field_values || {}).image_token || '').trim();
                if (tok) return e;
            }
            return null;
        },
        mindmapNodeImageUrl(ca) {
            var e = this.mindmapNodeImageEntry(ca);
            if (!e) return '';
            var token = ((e.field_values || {}).image_token || '').trim();
            return token ? '/beakbroodnest/files/' + encodeURIComponent(token) : '';
        },
        mindmapNodeHasImage(ca) {
            return !!this.mindmapNodeImageUrl(ca);
        },
        mindmapNodeHasTitle(ca) {
            return !!(ca && ca.atom && ca.atom.title && ca.atom.title.trim());
        },
        // 'text' | 'image' | 'image_text' -- v1 三模板自動判定
        mindmapNodeTemplate(ca) {
            var hasImg = this.mindmapNodeHasImage(ca);
            var hasTxt = this.mindmapNodeHasTitle(ca);
            if (hasImg && hasTxt) return 'image_text';
            if (hasImg) return 'image';
            return 'text';
        },

        _firstRowIsImage(ca) {
            if (!ca || !ca.atom) return false;
            // 優先看 content_json：第一個 block 是 image，或第一個 paragraph 的第一個 inline 是 image
            var cj = ca.atom.content_json;
            if (cj && cj.content && cj.content.length > 0) {
                var first = cj.content[0];
                if (!first) return false;
                if (first.type === 'image') return true;
                if (first.type === 'paragraph' && first.content && first.content.length > 0) {
                    for (var i = 0; i < first.content.length; i++) {
                        var n = first.content[i];
                        if (n.type === 'image') return true;
                        // 遇到非空白文字代表第一列以文字起頭
                        if (n.type === 'text' && n.text && n.text.trim()) return false;
                    }
                }
                return false;
            }
            // 退路：純 markdown content 以圖片開頭
            var content = ca.atom.content || '';
            return /^\s*!\[[^\]]*\]\([^)]+\)/.test(content);
        },

        applyCardSizeMode() {
            const HEADER_H = 34;
            const ENTRY_H = 23;
            const FOOTER_H = 28;
            const CONTENT_LINE_H = 20;
            const PADDING = 12;
            const MIN_H = 80;
            var self = this;
            this.atoms.forEach(function(ca) {
                var entries = (ca.atom && ca.atom.entries) ? ca.atom.entries.length : 0;
                var hasContent = ca.atom && ca.atom.content && ca.atom.content.trim().length > 0;
                var hasTags = ca.atom && ca.atom.tags && ca.atom.tags.length > 0;
                var footerH = hasTags ? FOOTER_H : 0;
                // 媒體卡片（PDF）或顯式縮圖卡：三種模式皆跳過，維持卡片原始尺寸
                if (ca.atom && ca.atom.content_type === 'media') return;
                if (self.hasThumbnail(ca)) return;
                if (self.hasPrimaryIdCard(ca)) return;
                var h;
                if (entries > 0) {
                    if (self.cardSizeMode === 'min') {
                        h = HEADER_H + ENTRY_H + footerH + PADDING;
                    } else if (self.cardSizeMode === 'default') {
                        h = HEADER_H + Math.min(entries, 6) * ENTRY_H + footerH + PADDING;
                    } else {
                        h = HEADER_H + entries * ENTRY_H + footerH + PADDING;
                    }
                } else if (hasContent) {
                    var lines = ca.atom.content.split('\n').length;
                    if (self.cardSizeMode === 'min') {
                        h = HEADER_H + CONTENT_LINE_H + footerH + PADDING;
                    } else if (self.cardSizeMode === 'default') {
                        h = HEADER_H + Math.min(lines, 6) * CONTENT_LINE_H + footerH + PADDING;
                    } else {
                        h = HEADER_H + lines * CONTENT_LINE_H + footerH + PADDING;
                    }
                } else {
                    h = MIN_H;
                }
                h = Math.max(MIN_H, h);
                ca.height = h;
                API.updateCanvasAtom(ca.id, { height: h });
            });
            this.$nextTick(function() { self.renderConnections(); });
        },

        // ============================================
        // New Atom
        // ============================================
        openNewAtomModal(e) {
            if (this.isSnapshot) { this.showToast('歸檔白板為唯讀快照', 'warn'); return; }
            this.newAtom = { title: '', content: '', atom_type: 'A' };
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

        async sendToCanvasTrash(ca) {
            if (this.isSnapshot) return;
            await API.addToCanvasTrash(this.canvasId, [ca.atom_id]);
            if (this.selectedAtomId === ca.atom_id) this.deselectCard();
            await this.loadData(); this.$nextTick(() => this.renderConnections());
        },

        // 開啟「徹底刪除」防呆 modal：列出此卡片在哪些白板/包/字紙簍
        // 用戶可選擇要刪哪些白板的引用，全選 = 真徹底刪除（hard delete atom 本體）
        async deleteAtomEntirely(ca) {
            if (this.isSnapshot) return;
            this.hardDeleteAtomId = ca.atom_id;
            this.hardDeleteAtomTitle = (ca.atom && ca.atom.title) ? ca.atom.title : '';
            this.hardDeleteUsage = null;
            this.hardDeleteSelectedCanvasIds = [];
            this.showHardDeleteModal = true;
            try {
                var usage = await API.getAtomUsage(ca.atom_id);
                this.hardDeleteUsage = usage;
                // 預設只勾選當前白板
                var cur = this.canvas ? this.canvas.id : null;
                if (cur && usage.canvases.some(function(c) { return c.canvas_id === cur; })) {
                    this.hardDeleteSelectedCanvasIds = [cur];
                }
            } catch (e) {
                this.showToast('載入引用清單失敗：' + (e.message || e), 'error');
                this.closeHardDeleteModal();
            }
        },

        closeHardDeleteModal() {
            this.showHardDeleteModal = false;
            this.hardDeleteAtomId = null;
            this.hardDeleteAtomTitle = '';
            this.hardDeleteUsage = null;
            this.hardDeleteSelectedCanvasIds = [];
        },

        toggleHardDeleteCanvas(canvasId) {
            var i = this.hardDeleteSelectedCanvasIds.indexOf(canvasId);
            if (i >= 0) this.hardDeleteSelectedCanvasIds.splice(i, 1);
            else this.hardDeleteSelectedCanvasIds.push(canvasId);
        },

        toggleSelectAllHardDeleteCanvases() {
            if (!this.hardDeleteUsage) return;
            var all = this.hardDeleteUsage.canvases.map(function(c) { return c.canvas_id; });
            if (this.hardDeleteSelectedCanvasIds.length === all.length) {
                this.hardDeleteSelectedCanvasIds = [];
            } else {
                this.hardDeleteSelectedCanvasIds = all.slice();
            }
        },

        get hardDeleteIsAllSelected() {
            if (!this.hardDeleteUsage) return false;
            return this.hardDeleteUsage.canvases.length > 0
                && this.hardDeleteSelectedCanvasIds.length === this.hardDeleteUsage.canvases.length;
        },

        async confirmHardDelete() {
            if (!this.hardDeleteUsage || this.hardDeleteSelectedCanvasIds.length === 0) return;
            var atomId = this.hardDeleteAtomId;
            var allSelected = this.hardDeleteIsAllSelected;
            var selectedIds = this.hardDeleteSelectedCanvasIds.slice();

            if (allSelected) {
                var msg = '最後確認：將從 DB 徹底刪除這張卡片，以及全部白板、'
                    + this.hardDeleteUsage.exchange_packs.length + ' 個交換包、'
                    + this.hardDeleteUsage.canvas_trashes.length + ' 個白板字紙簍的引用。\n\n不可逆，繼續？';
                if (!confirm(msg)) return;
                try {
                    await API.hardDeleteAtom(atomId);
                    if (this.selectedAtomId === atomId) this.deselectCard();
                    this.showToast('已從 DB 徹底刪除', 'success');
                } catch (e) {
                    this.showToast('刪除失敗：' + (e.message || e), 'error');
                    return;
                }
            } else {
                // 對選中的白板逐一解除連結
                var usage = this.hardDeleteUsage;
                var canvasMap = {};
                usage.canvases.forEach(function(c) { canvasMap[c.canvas_id] = c; });
                var failed = 0;
                for (var i = 0; i < selectedIds.length; i++) {
                    var c = canvasMap[selectedIds[i]];
                    if (!c) continue;
                    try { await API.removeCanvasAtom(c.canvas_atom_id); }
                    catch (e) { failed++; console.warn('removeCanvasAtom failed', e); }
                }
                if (failed > 0) {
                    this.showToast('完成，' + failed + ' 個白板解除失敗', 'warn');
                } else {
                    this.showToast('已從 ' + selectedIds.length + ' 個白板解除連結', 'success');
                }
                if (this.selectedAtomId === atomId
                    && selectedIds.indexOf(this.canvas ? this.canvas.id : -1) >= 0) {
                    this.deselectCard();
                }
            }

            this.closeHardDeleteModal();
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
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
            var payload = { canvas_id: this.canvasId, source_atom_id: this.pendingConnection.sourceAtomId, target_atom_id: this.pendingConnection.targetAtomId, relation_type: this.selectedRelationType, label: this.relationLabel };
            if (this.pendingConnection.sourceEntryId) payload.source_entry_id = this.pendingConnection.sourceEntryId;
            if (this.pendingConnection.targetEntryId) payload.target_entry_id = this.pendingConnection.targetEntryId;
            var resp = await API.createConnection(payload);
            this.showRelationModal = false; this.pendingConnection = null; this.mode = 'select';
            if (resp && !resp.error) {
                this.connections.push(resp);
                this.renderConnections();
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
                        try { await API.createConnection(payload); } catch (e) {}
                        await self.loadData();
                        self.$nextTick(function() { self.renderConnections(); });
                    },
                });
            }
        },

        async deleteConnection(connId) {
            // 先取現有 connection 內容,作為 undo 用 payload
            var conn = this.connections.find(function(c) { return c.id === connId; });
            var payload = null;
            if (conn) {
                payload = {
                    canvas_id: this.canvasId,
                    source_atom_id: conn.source_atom_id,
                    target_atom_id: conn.target_atom_id,
                    relation_type: conn.relation_type,
                    label: conn.label || '',
                };
                if (conn.from_kind) payload.from_kind = conn.from_kind;
                if (conn.to_kind) payload.to_kind = conn.to_kind;
                if (conn.source_textbox_id) payload.source_textbox_id = conn.source_textbox_id;
                if (conn.target_textbox_id) payload.target_textbox_id = conn.target_textbox_id;
                if (conn.source_entry_id) payload.source_entry_id = conn.source_entry_id;
                if (conn.target_entry_id) payload.target_entry_id = conn.target_entry_id;
            }
            await API.deleteConnection(connId);
            await this.loadData();
            this.renderConnections();
            if (payload) {
                var self = this;
                this.pushUndo({
                    type: 'delete_connection',
                    desc: '刪除連線',
                    undo: async function() {
                        try { await API.createConnection(payload); } catch (e) {}
                        await self.loadData();
                        self.$nextTick(function() { self.renderConnections(); });
                    },
                    redo: async function() {
                        // redo 後 conn id 變了,用 payload 找最近一條同源同目同類連線刪除
                        await self.loadData();
                        var match = self.connections.find(function(c) {
                            return c.source_atom_id === payload.source_atom_id
                                && c.target_atom_id === payload.target_atom_id
                                && c.relation_type === payload.relation_type;
                        });
                        if (match) { try { await API.deleteConnection(match.id); } catch (e) {} }
                        await self.loadData();
                        self.$nextTick(function() { self.renderConnections(); });
                    },
                });
            }
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
            let created;
            try {
                created = await API.createTag({ name: this.newTagName.trim(), color: this.newTagColor, source: 'human' });
            } catch (e) {
                // 409 = 撞名，後端會回既有 tag。若該 tag 已被隱藏，提示是否重新啟用；否則沿用既有。
                const status = e && (e.status || (e.response && e.response.status));
                const body = e && (e.body || e.data || (e.response && e.response.data));
                if (status === 409 && body && body.existing) {
                    const ex = body.existing;
                    if (ex.hidden) {
                        if (confirm('已存在同名的隱藏標籤（id=' + ex.id + '）。\n按「確定」恢復舊標籤（連同所有舊關聯）；按「取消」請改用其他名稱。')) {
                            await API.updateTag(ex.id, { hidden: false, color: this.newTagColor });
                            await this.reloadTags();
                            this.newTagName = '';
                            return;
                        }
                        // 用戶選取消：不沿用，保留輸入讓用戶改名
                        return;
                    }
                    if (ex.color !== this.newTagColor && confirm('同名標籤已存在（id=' + ex.id + '），要把顏色改為新選的色嗎？')) {
                        await API.updateTag(ex.id, { color: this.newTagColor });
                    } else {
                        alert('同名標籤已存在，沿用既有的（id=' + ex.id + '）。');
                    }
                    await this.reloadTags();
                    this.newTagName = '';
                    return;
                }
                throw e;
            }
            // 若使用者目前已勾選分類，新標籤自動歸入所選分類
            if (created && created.id && Array.isArray(this.selectedCategoryIds) && this.selectedCategoryIds.length > 0) {
                const catIds = this.selectedCategoryIds.filter(function(id) { return id !== 0; });
                if (catIds.length > 0) {
                    await API.updateTag(created.id, { category_ids: catIds });
                }
            }
            this.tags = await API.getTags();
            this.newTagName = '';
        },

        async updateTagColor(tagId, color) {
            await API.updateTag(tagId, { color: color });
            this.tags = await API.getTags();
        },

        filterTagsBySource(arr) {
            const f = this.tagSourceFilter;
            if (f === 'all') return arr;
            return arr.filter(function(t) { return (t.source || 'ai') === f; });
        },

        async reloadTags() {
            this.tags = await API.getTags({ include_hidden: this.tagIncludeHidden ? 1 : 0 });
        },

        async setTagHidden(tagId, hidden) {
            await API.updateTag(tagId, { hidden: !!hidden });
            await this.reloadTags();
        },

        startEditTag(t) {
            this.tagEditingId = t.id;
            this.tagEditingName = t.name;
        },

        cancelEditTag() {
            this.tagEditingId = null;
            this.tagEditingName = '';
        },

        async commitEditTag(t) {
            const newName = (this.tagEditingName || '').trim();
            if (!newName || newName === t.name) {
                this.cancelEditTag();
                return;
            }
            try {
                await API.updateTag(t.id, { name: newName });
            } catch (e) {
                const status = e && (e.status || (e.response && e.response.status));
                const body = e && (e.body || e.data || (e.response && e.response.data));
                if (status === 409 && body && body.existing) {
                    const ex = body.existing;
                    const flags = [];
                    if (ex.hidden) flags.push('已隱藏');
                    if (ex.source && ex.source !== 'human') flags.push('來源=' + ex.source);
                    const suffix = flags.length ? '（' + flags.join('、') + '）' : '';
                    let msg = '已存在同名標籤「' + ex.name + '」' + suffix + '，id=' + ex.id + '。';
                    if (ex.hidden) msg += '\n（提示：勾選「顯示已隱藏」可看見並恢復它，或改用其他名稱）';
                    else if (ex.source !== 'human') msg += '\n（提示：把「來源」切到「全部」可看見該標籤）';
                    else msg += '\n請改用其他名稱。';
                    alert(msg);
                    return;
                }
                throw e;
            }
            this.cancelEditTag();
            await this.reloadTags();
            // 改名後既有關聯仍指向同一 id，重新載入卡片資料讓 UI 反映新名稱
            await this.loadData();
        },

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

        async setCanvasIsProject(flag) {
            if (!this.canvas) return;
            await API.updateCanvas(this.canvasId, { is_project: !!flag });
            this.canvas.is_project = !!flag;
            this.showToast(flag ? '已設為專案白板' : '已設為自由白板', 'success');
        },

        canvasAudienceOptions: [
            { value: 'human', label: '自用', hint: '（AI 不讀，草稿與想法）' },
            { value: 'shared', label: '共用', hint: '（AI 會讀）' },
            { value: 'ai', label: 'AI 工作區', hint: '（AI 的待辦與專案卡）' },
        ],

        async setCanvasAudience(value) {
            if (!this.canvas) return;
            await API.updateCanvas(this.canvasId, { audience: value });
            this.canvas.audience = value;
            const label = (this.canvasAudienceOptions.find(o => o.value === value) || {}).label || value;
            this.showToast('AI 可見性已設為「' + label + '」', 'success');
        },

        async createCanvas() { if (!this.newCanvasName.trim()) return; const c = await API.createCanvas({ name: this.newCanvasName.trim() }); window.location.href = '/beakbroodnest/canvas/' + c.slug; },

        async deleteCanvas(slug) {
            if (this.canvases.length <= 1) return;
            await API.deleteCanvas(slug);
            if (slug === this.canvasId) window.location.href = '/beakbroodnest/'; else await this.loadCanvases();
        },

        async archiveCurrentCanvas() {
            if (!confirm('歸檔此白板？白板會隱藏但保留。')) return;
            await API.updateCanvas(this.canvasId, { is_archived: true });
            this.showUISettingsModal = false;
            window.location.href = '/beakbroodnest/';
        },

        async deleteCurrentCanvas() {
            if (!confirm('永久刪除此白板？卡片不受影響，但白板上的佈局將無法復原。')) return;
            await API.deleteCanvas(this.canvasId);
            this.showUISettingsModal = false;
            window.location.href = '/beakbroodnest/';
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

        // ============================================
        // Canvas sidebar：最近 / 下拉 / 標籤過濾
        // ============================================
        loadRecentCanvases() {
            try {
                var raw = localStorage.getItem('bb_recent_canvas_slugs');
                this.recentCanvasSlugs = raw ? JSON.parse(raw) : [];
                if (!Array.isArray(this.recentCanvasSlugs)) this.recentCanvasSlugs = [];
            } catch (e) { this.recentCanvasSlugs = []; }
        },
        pushRecentCanvas(slug) {
            if (!slug) return;
            var arr = (this.recentCanvasSlugs || []).filter(function(s) { return s !== slug; });
            arr.unshift(slug);
            if (arr.length > this.RECENT_CANVAS_MAX) arr = arr.slice(0, this.RECENT_CANVAS_MAX);
            this.recentCanvasSlugs = arr;
            try { localStorage.setItem('bb_recent_canvas_slugs', JSON.stringify(arr)); } catch (e) {}
        },
        loadCanvasTagFilter() {
            try {
                var raw = localStorage.getItem('bb_canvas_tag_filter');
                this.canvasTagFilter = raw ? JSON.parse(raw) : [];
                if (!Array.isArray(this.canvasTagFilter)) this.canvasTagFilter = [];
            } catch (e) { this.canvasTagFilter = []; }
        },
        saveCanvasTagFilter() {
            try { localStorage.setItem('bb_canvas_tag_filter', JSON.stringify(this.canvasTagFilter || [])); } catch (e) {}
        },
        toggleCanvasTagFilter(tagId) {
            var arr = this.canvasTagFilter || [];
            if (arr.includes(tagId)) {
                this.canvasTagFilter = arr.filter(function(id) { return id !== tagId; });
            } else {
                this.canvasTagFilter = arr.concat([tagId]);
            }
            this.saveCanvasTagFilter();
        },
        clearCanvasTagFilter() {
            this.canvasTagFilter = [];
            this.saveCanvasTagFilter();
        },
        get humanTags() {
            return (this.tags || []).filter(function(t) { return (t.source || 'ai') === 'human'; });
        },
        get recentCanvases() {
            var slugs = this.recentCanvasSlugs || [];
            var byslug = {};
            (this.canvases || []).forEach(function(c) { byslug[c.slug] = c; });
            var out = [];
            slugs.forEach(function(s) { if (byslug[s]) out.push(byslug[s]); });
            // 若目前白板不在 recent（剛從 URL 進來尚未 push 完），補一筆
            if (this.canvasId && !slugs.includes(this.canvasId) && byslug[this.canvasId]) {
                out.unshift(byslug[this.canvasId]);
            }
            return out.slice(0, this.RECENT_CANVAS_MAX);
        },
        get filteredOtherCanvases() {
            var recent = new Set((this.recentCanvases || []).map(function(c) { return c.slug; }));
            var tagFilter = this.canvasTagFilter || [];
            return (this.canvases || []).filter(function(c) {
                if (recent.has(c.slug)) return false;
                if (tagFilter.length === 0) return true;
                var ids = c.tag_ids || [];
                return tagFilter.some(function(id) { return ids.includes(id); });
            });
        },
        async toggleCanvasTag(tagId) {
            // 在「設定 → 白板」頁切換目前白板的標籤歸屬
            if (!this.canvas) return;
            var cur = (this.canvas.tag_ids || []).slice();
            var idx = cur.indexOf(tagId);
            if (idx >= 0) cur.splice(idx, 1); else cur.push(tagId);
            var updated = await API.updateCanvas(this.canvasId, { tag_ids: cur });
            this.canvas.tag_ids = updated.tag_ids || cur;
            // 同步 canvases 清單中的對應項
            var idx2 = (this.canvases || []).findIndex(c => c.slug === this.canvasId);
            if (idx2 >= 0) this.canvases[idx2].tag_ids = this.canvas.tag_ids;
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
        contextAddAtom() {
            var cx = this.contextMenu.x, cy = this.contextMenu.y;
            this.closeContextMenu();
            this.addCardInline(cx, cy);
        },

        async addCardInline(clientX, clientY) {
            if (this.isSnapshot) { this.showToast('歸檔白板為唯讀快照', 'warn'); return; }
            var pos = this.screenToCanvas(clientX, clientY);
            try {
                var atom = await API.createAtom({ title: '', content: '', atom_type: 'A', source: 'human' });
                await this.openCardEditor(atom.id);
                var ed = this.openEditors.find(function(e) { return e.atomId === atom.id; });
                if (ed) ed._pendingCanvasPos = { x: pos.x, y: pos.y };
            } catch (e) {
                this.showToast('新增卡片失敗：' + (e.message || e), 'error');
            }
        },

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

        // 確保卡片在 viewport 內可見;超出邊界時最小幅度 pan 回視野(留 60px margin)
        ensureAtomVisible(atomId) {
            var ca = this.atoms.find(function(a) { return a.atom_id === atomId; });
            if (!ca) return;
            var vp = this.$refs.viewport;
            if (!vp) return;
            var rect = vp.getBoundingClientRect();
            var w = (ca.width || 140) * this.zoom;
            var h = (ca.height || 30) * this.zoom;
            var screenX = ca.pos_x * this.zoom + this.panX;
            var screenY = ca.pos_y * this.zoom + this.panY;
            var margin = 60;
            var dx = 0, dy = 0;
            if (screenX < margin) dx = margin - screenX;
            else if (screenX + w > rect.width - margin) dx = rect.width - margin - (screenX + w);
            if (screenY < margin) dy = margin - screenY;
            else if (screenY + h > rect.height - margin) dy = rect.height - margin - (screenY + h);
            if (dx === 0 && dy === 0) return;
            this.panX += dx;
            this.panY += dy;
            this.updateTransform();
            this.renderConnections();
            if (this.saveViewport) this.saveViewport();
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
                var resp = await API.put('/beakbroodnest/api/auth/change-password', { old_password: this.pwOld, new_password: this.pwNew });
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
    if (typeof whiteboardTextboxesMixin === 'function') {
        _mergeInto(app, whiteboardTextboxesMixin());
    }
    if (typeof whiteboardMediaMixin === 'function') {
        _mergeInto(app, whiteboardMediaMixin());
    }
    if (typeof whiteboardExportMdMixin === 'function') {
        _mergeInto(app, whiteboardExportMdMixin());
    }
    if (typeof whiteboardExchangeMixin === 'function') {
        _mergeInto(app, whiteboardExchangeMixin());
    }
    if (typeof whiteboardMindmapMixin === 'function') {
        _mergeInto(app, whiteboardMindmapMixin());
    }
    if (typeof whiteboardStandaloneEntriesMixin === 'function') {
        _mergeInto(app, whiteboardStandaloneEntriesMixin());
    }

    return app;
}
