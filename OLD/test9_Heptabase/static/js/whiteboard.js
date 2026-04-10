/**
 * 白板核心引擎
 * 負責：pan/zoom、卡片渲染、拖曳、連線、item drag-and-drop
 */

function whiteboardApp(wbId) {
    return {
        wbId: wbId,
        wb: null,
        cards: [],
        connections: [],
        schemas: [],
        tags: [],

        // 畫布狀態
        panX: 0,
        panY: 0,
        zoom: 1,
        isPanning: false,
        panStartX: 0,
        panStartY: 0,

        // 卡片拖曳
        dragCard: null,
        dragStartX: 0,
        dragStartY: 0,
        cardStartX: 0,
        cardStartY: 0,

        // 連線建立
        isConnecting: false,
        connSourceId: null,
        connTempLine: null,

        // UI 狀態
        selectedCardId: null,
        showPanel: false,
        showAddCardModal: false,
        showAddItemModal: false,
        showTagModal: false,
        contextMenu: null,
        mode: 'select',  // select, connect

        // 新卡片表單
        newCard: { title: '', schema_id: '', color: '#ffffff' },
        // 新 item 表單
        addItemSchemaId: null,
        addItemTargetCardId: null,
        availableItems: [],
        // Tag 表單
        newTagName: '',
        newTagColor: '#6b7280',

        async init() {
            await this.loadData();
            this.$nextTick(() => {
                this.renderConnections();
                this.setupCanvasEvents();
                // 置中視圖
                if (this.cards.length > 0) {
                    this.fitView();
                }
            });
        },

        async loadData() {
            const [wb, schemas, tags] = await Promise.all([
                API.getWhiteboard(this.wbId),
                API.getSchemas(),
                API.getTags(),
            ]);
            this.wb = wb;
            this.cards = wb.cards || [];
            this.connections = wb.connections || [];
            this.schemas = schemas;
            this.tags = tags;
            if (wb.viewport_x || wb.viewport_y) {
                this.panX = wb.viewport_x;
                this.panY = wb.viewport_y;
                this.zoom = wb.viewport_zoom || 1;
                this.updateTransform();
            }
        },

        // ============================================
        // Pan / Zoom
        // ============================================
        setupCanvasEvents() {
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
            // 中鍵或空白處左鍵開始平移
            if (e.button === 1 || (e.button === 0 && e.target === this.$refs.canvas)) {
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
                return;
            }
            if (this.isConnecting) {
                this.updateTempLine(e);
            }
        },

        onViewportMouseUp(e) {
            if (this.isPanning) {
                this.isPanning = false;
                this.saveViewport();
            }
            if (this.dragCard) {
                API.updateCard(this.dragCard.id, {
                    pos_x: this.dragCard.pos_x,
                    pos_y: this.dragCard.pos_y,
                });
                this.dragCard = null;
            }
        },

        updateTransform() {
            const canvas = this.$refs.canvas;
            if (canvas) {
                canvas.style.transform = `translate(${this.panX}px, ${this.panY}px) scale(${this.zoom})`;
            }
        },

        saveViewport() {
            API.updateWhiteboard(this.wbId, {
                viewport_x: this.panX,
                viewport_y: this.panY,
                viewport_zoom: this.zoom,
            });
        },

        zoomIn() {
            this.zoom = Math.min(3, this.zoom * 1.2);
            this.updateTransform();
            this.renderConnections();
        },

        zoomOut() {
            this.zoom = Math.max(0.15, this.zoom / 1.2);
            this.updateTransform();
            this.renderConnections();
        },

        resetZoom() {
            this.zoom = 1;
            this.panX = 0;
            this.panY = 0;
            this.updateTransform();
            this.renderConnections();
            this.saveViewport();
        },

        fitView() {
            if (this.cards.length === 0) return;
            const vp = this.$refs.viewport;
            if (!vp) return;
            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            this.cards.forEach(c => {
                minX = Math.min(minX, c.pos_x);
                minY = Math.min(minY, c.pos_y);
                maxX = Math.max(maxX, c.pos_x + (c.width || 280));
                maxY = Math.max(maxY, c.pos_y + 200);
            });
            const cw = maxX - minX + 100;
            const ch = maxY - minY + 100;
            const rect = vp.getBoundingClientRect();
            this.zoom = Math.min(rect.width / cw, rect.height / ch, 1.2);
            this.panX = (rect.width - cw * this.zoom) / 2 - minX * this.zoom + 50;
            this.panY = (rect.height - ch * this.zoom) / 2 - minY * this.zoom + 50;
            this.updateTransform();
            this.renderConnections();
            this.saveViewport();
        },

        get zoomPercent() {
            return Math.round(this.zoom * 100);
        },

        // ============================================
        // 座標轉換
        // ============================================
        screenToCanvas(sx, sy) {
            const vp = this.$refs.viewport;
            const rect = vp.getBoundingClientRect();
            return {
                x: (sx - rect.left - this.panX) / this.zoom,
                y: (sy - rect.top - this.panY) / this.zoom,
            };
        },

        // ============================================
        // 卡片操作
        // ============================================
        onCardMouseDown(e, card) {
            if (e.button !== 0) return;
            if (this.mode === 'connect') return;
            e.stopPropagation();
            this.selectCard(card.id);
            this.dragCard = card;
            this.dragStartX = e.clientX;
            this.dragStartY = e.clientY;
            this.cardStartX = card.pos_x;
            this.cardStartY = card.pos_y;
            // 提升 z-index
            const maxZ = Math.max(0, ...this.cards.map(c => c.z_index || 0));
            card.z_index = maxZ + 1;
        },

        selectCard(cardId) {
            this.selectedCardId = cardId;
            this.showPanel = true;
        },

        deselectCard() {
            this.selectedCardId = null;
            this.showPanel = false;
        },

        get selectedCard() {
            return this.cards.find(c => c.id === this.selectedCardId) || null;
        },

        async openAddCardModal(e) {
            this.newCard = { title: '', schema_id: '', color: '#ffffff' };
            if (e) {
                const pos = this.screenToCanvas(e.clientX || 400, e.clientY || 300);
                this.newCard._x = pos.x;
                this.newCard._y = pos.y;
            } else {
                this.newCard._x = (-this.panX / this.zoom) + 200;
                this.newCard._y = (-this.panY / this.zoom) + 200;
            }
            this.showAddCardModal = true;
        },

        async createCard() {
            const schemaId = this.newCard.schema_id ? parseInt(this.newCard.schema_id) : null;
            let title = this.newCard.title;
            if (!title && schemaId) {
                const s = this.schemas.find(s => s.id === schemaId);
                if (s) title = s.name;
            }
            if (!title) title = '新卡片';

            const resp = await API.createCard({
                whiteboard_id: this.wbId,
                title: title,
                schema_id: schemaId,
                pos_x: this.newCard._x || 100,
                pos_y: this.newCard._y || 100,
                color: this.newCard.color,
            });
            this.showAddCardModal = false;
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        async deleteCard(cardId) {
            await API.deleteCard(cardId);
            if (this.selectedCardId === cardId) this.deselectCard();
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        async updateCardTitle(card) {
            await API.updateCard(card.id, { title: card.title });
        },

        async updateCardColor(card, color) {
            card.color = color;
            await API.updateCard(card.id, { color });
        },

        getSchemaName(schemaId) {
            if (!schemaId) return '';
            const s = this.schemas.find(s => s.id === schemaId);
            return s ? s.name : '';
        },

        // ============================================
        // Item 拖曳 (在卡片之間)
        // ============================================
        onItemDragStart(e, item, card) {
            e.dataTransfer.setData('application/json', JSON.stringify({
                type: 'card-item',
                itemId: item.item_id,
                sourceCardId: card.id,
            }));
            e.dataTransfer.effectAllowed = 'move';
            e.target.classList.add('dragging');
        },

        onItemDragEnd(e) {
            e.target.classList.remove('dragging');
        },

        onCardDragOver(e, card) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
        },

        onCardDragEnter(e, card) {
            e.preventDefault();
            const el = e.currentTarget;
            if (el) el.classList.add('drag-over');
        },

        onCardDragLeave(e, card) {
            const el = e.currentTarget;
            if (el && !el.contains(e.relatedTarget)) {
                el.classList.remove('drag-over');
            }
        },

        async onCardDrop(e, targetCard) {
            e.preventDefault();
            e.currentTarget.classList.remove('drag-over');

            let data;
            try {
                data = JSON.parse(e.dataTransfer.getData('application/json'));
            } catch { return; }

            if (data.type === 'card-item' && data.sourceCardId !== targetCard.id) {
                await API.moveItem({
                    item_id: data.itemId,
                    source_card_id: data.sourceCardId,
                    target_card_id: targetCard.id,
                });
                await this.loadData();
                this.$nextTick(() => this.renderConnections());
            } else if (data.type === 'unassigned-item') {
                await API.addItemToCard(targetCard.id, data.itemId);
                await this.loadData();
                this.$nextTick(() => this.renderConnections());
            }
        },

        async removeItemFromCard(cardId, itemId) {
            await API.removeItemFromCard(cardId, itemId);
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        // 從側邊欄加入 item
        async openAddItemModal(cardId) {
            this.addItemTargetCardId = cardId;
            const card = this.cards.find(c => c.id === cardId);
            this.addItemSchemaId = card?.schema_id || null;
            await this.loadAvailableItems();
            this.showAddItemModal = true;
        },

        async loadAvailableItems() {
            this.availableItems = await API.getUnassignedItems(this.addItemSchemaId);
        },

        async addItemToCard(itemId) {
            await API.addItemToCard(this.addItemTargetCardId, itemId);
            this.showAddItemModal = false;
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        // ============================================
        // 連線操作
        // ============================================
        toggleConnectMode() {
            this.mode = this.mode === 'connect' ? 'select' : 'connect';
            if (this.mode !== 'connect') {
                this.isConnecting = false;
                this.connSourceId = null;
                this.removeTempLine();
            }
        },

        onAnchorMouseDown(e, card, side) {
            if (this.mode !== 'connect') return;
            e.stopPropagation();
            this.isConnecting = true;
            this.connSourceId = card.id;
        },

        onCardClickForConnect(e, card) {
            if (this.mode !== 'connect') return;
            e.stopPropagation();
            if (!this.isConnecting) {
                // 開始連線
                this.isConnecting = true;
                this.connSourceId = card.id;
            } else if (this.connSourceId && this.connSourceId !== card.id) {
                // 完成連線
                this.createConnection(this.connSourceId, card.id);
                this.isConnecting = false;
                this.connSourceId = null;
                this.removeTempLine();
            }
        },

        async createConnection(sourceId, targetId) {
            await API.createConnection({
                whiteboard_id: this.wbId,
                source_card_id: sourceId,
                target_card_id: targetId,
            });
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        async deleteConnection(connId) {
            await API.deleteConnection(connId);
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        updateTempLine(e) {
            // 畫臨時連線跟隨滑鼠
            const svg = this.$refs.connSvg;
            if (!svg) return;
            let line = svg.querySelector('.wb-temp-line');
            if (!line) {
                line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                line.classList.add('wb-temp-line');
                svg.appendChild(line);
            }
            const sourceCard = this.cards.find(c => c.id === this.connSourceId);
            if (!sourceCard) return;
            const sx = sourceCard.pos_x + (sourceCard.width || 280) / 2;
            const sy = sourceCard.pos_y + 80;
            const canvasPos = this.screenToCanvas(e.clientX, e.clientY);
            line.setAttribute('x1', sx);
            line.setAttribute('y1', sy);
            line.setAttribute('x2', canvasPos.x);
            line.setAttribute('y2', canvasPos.y);
        },

        removeTempLine() {
            const svg = this.$refs.connSvg;
            if (!svg) return;
            const line = svg.querySelector('.wb-temp-line');
            if (line) line.remove();
        },

        renderConnections() {
            const svg = this.$refs.connSvg;
            if (!svg) return;
            // 保留 temp line，清其他
            const tempLine = svg.querySelector('.wb-temp-line');
            svg.innerHTML = '';
            if (tempLine) svg.appendChild(tempLine);

            // Arrow marker
            const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
            const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
            marker.setAttribute('id', 'arrow');
            marker.setAttribute('viewBox', '0 0 10 10');
            marker.setAttribute('refX', '9');
            marker.setAttribute('refY', '5');
            marker.setAttribute('markerWidth', '6');
            marker.setAttribute('markerHeight', '6');
            marker.setAttribute('orient', 'auto-start-reverse');
            const arrowPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            arrowPath.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
            arrowPath.setAttribute('fill', '#94a3b8');
            marker.appendChild(arrowPath);
            defs.appendChild(marker);
            svg.appendChild(defs);

            this.connections.forEach(conn => {
                const src = this.cards.find(c => c.id === conn.source_card_id);
                const tgt = this.cards.find(c => c.id === conn.target_card_id);
                if (!src || !tgt) return;

                const srcEl = document.getElementById(`card-${src.id}`);
                const tgtEl = document.getElementById(`card-${tgt.id}`);
                const sw = srcEl ? srcEl.offsetWidth : (src.width || 280);
                const sh = srcEl ? srcEl.offsetHeight : 150;
                const tw = tgtEl ? tgtEl.offsetWidth : (tgt.width || 280);
                const th = tgtEl ? tgtEl.offsetHeight : 150;

                const sx = src.pos_x + sw / 2;
                const sy = src.pos_y + sh / 2;
                const tx = tgt.pos_x + tw / 2;
                const ty = tgt.pos_y + th / 2;

                const dx = tx - sx;
                const cx1 = sx + dx * 0.4;
                const cx2 = sx + dx * 0.6;

                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', `M ${sx} ${sy} C ${cx1} ${sy}, ${cx2} ${ty}, ${tx} ${ty}`);
                path.setAttribute('fill', 'none');
                path.setAttribute('stroke', '#94a3b8');
                path.setAttribute('stroke-width', '1.5');
                path.setAttribute('marker-end', 'url(#arrow)');

                if (conn.line_style === 'dashed') {
                    path.setAttribute('stroke-dasharray', '6 4');
                } else if (conn.line_style === 'dotted') {
                    path.setAttribute('stroke-dasharray', '2 3');
                }

                path.addEventListener('click', () => {
                    if (confirm('刪除此連線？')) {
                        this.deleteConnection(conn.id);
                    }
                });
                path.style.pointerEvents = 'stroke';
                path.style.cursor = 'pointer';

                svg.appendChild(path);

                // 連線標籤
                if (conn.label) {
                    const mx = (sx + tx) / 2;
                    const my = (sy + ty) / 2;
                    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                    text.setAttribute('x', mx);
                    text.setAttribute('y', my - 6);
                    text.setAttribute('text-anchor', 'middle');
                    text.setAttribute('class', 'conn-label');
                    text.textContent = conn.label;
                    svg.appendChild(text);
                }
            });
        },

        // ============================================
        // Tag 操作
        // ============================================
        async openTagModal() {
            this.showTagModal = true;
            this.newTagName = '';
            this.newTagColor = '#6b7280';
        },

        async createTag() {
            if (!this.newTagName.trim()) return;
            await API.createTag({ name: this.newTagName.trim(), color: this.newTagColor });
            this.tags = await API.getTags();
            this.newTagName = '';
        },

        async toggleCardTag(cardId, tagId) {
            const card = this.cards.find(c => c.id === cardId);
            if (!card) return;
            const hasTag = card.tags && card.tags.some(t => t.tag_id === tagId);
            if (hasTag) {
                await API.removeTagFromCard(cardId, tagId);
            } else {
                await API.addTagToCard(cardId, tagId);
            }
            await this.loadData();
            this.$nextTick(() => this.renderConnections());
        },

        cardHasTag(cardId, tagId) {
            const card = this.cards.find(c => c.id === cardId);
            return card && card.tags && card.tags.some(t => t.tag_id === tagId);
        },

        getTagStyle(color) {
            return `background: ${color}20; color: ${color}; border: 1px solid ${color}40;`;
        },

        // ============================================
        // 右鍵選單
        // ============================================
        onCanvasContextMenu(e) {
            e.preventDefault();
            this.contextMenu = {
                x: e.clientX,
                y: e.clientY,
                type: 'canvas',
            };
        },

        onCardContextMenu(e, card) {
            e.preventDefault();
            e.stopPropagation();
            this.contextMenu = {
                x: e.clientX,
                y: e.clientY,
                type: 'card',
                cardId: card.id,
            };
        },

        closeContextMenu() {
            this.contextMenu = null;
        },

        async contextAddCard() {
            await this.openAddCardModal({ clientX: this.contextMenu.x, clientY: this.contextMenu.y });
            this.closeContextMenu();
        },

        // ============================================
        // Item 詳情格式化
        // ============================================
        formatItemDetails(item) {
            if (!item.values) return '';
            const parts = [];
            for (const [key, val] of Object.entries(item.values)) {
                if (val && val.length < 40) {
                    parts.push(val);
                }
            }
            return parts.slice(0, 3).join(' / ');
        },

        // ============================================
        // 白板管理
        // ============================================
        whiteboards: [],
        showWbModal: false,
        newWbName: '',

        async loadWhiteboards() {
            this.whiteboards = await API.getWhiteboards();
        },

        async createWhiteboard() {
            if (!this.newWbName.trim()) return;
            const resp = await API.createWhiteboard({ name: this.newWbName.trim() });
            window.location.href = `/whiteboard/${resp.id}`;
        },

        async deleteWhiteboard(id) {
            if (this.whiteboards.length <= 1) return;
            await API.deleteWhiteboard(id);
            if (id === this.wbId) {
                window.location.href = '/';
            } else {
                await this.loadWhiteboards();
            }
        },

        // 卡片顏色選項
        cardColors: [
            '#ffffff', '#fef3c7', '#dcfce7', '#dbeafe',
            '#f3e8ff', '#fce7f3', '#ffedd5', '#f1f5f9',
        ],
    };
}
