/**
 * 白板 Mixin: 獨立文字框 (canvas_textboxes)
 * 標題在框左上外緣（頁籤式），框內 textarea 直接編輯純文字。
 * 不依附任何 atom，可拉連線。
 */
function whiteboardTextboxesMixin() {
    return {

        // ---- state ----
        // textboxes: [],  // 由 whiteboard.js 主 app 宣告，避免 mixin 覆寫
        dragTextbox: null,
        textboxDragStartX: 0, textboxDragStartY: 0,
        textboxDragStartPos: null,
        resizeTextbox: null,
        resizeTextboxStartX: 0, resizeTextboxStartY: 0,
        resizeTextboxStartW: 0, resizeTextboxStartH: 0,
        editingTextboxId: null,           // 內文 textarea 編輯中
        showTextboxModal: false,
        editingTextbox: null,             // 設定 modal 編輯目標
        textboxForm: { title: '', bg_color: '#fffbe6', bg_transparent: true, border_color: '#f59e0b', border_style: 'solid', text_color: '#1f2937' },
        _textboxContentSaveTimer: null,
        _textboxTitleSaveTimer: null,

        // ---- 建立 ----
        async createTextboxAtPos(canvasX, canvasY) {
            if (this.isSnapshot) { this.showToast('歸檔白板為唯讀快照', 'warn'); return; }
            try {
                var resp = await API.createTextbox(this.canvasId, {
                    title: '新標題',
                    content: '',
                    pos_x: canvasX,
                    pos_y: canvasY + 24,  // 預留標題在框外的空間
                    width: 320,
                    height: 180,
                    bg_color: 'transparent',
                });
                if (resp && !resp.error) {
                    this.textboxes.push(resp);
                }
            } catch (e) {
                this.showToast('文字框建立失敗：' + (e.message || e), 'error');
            }
        },

        // 從工具列按鈕觸發：放在當前視窗中央
        async createTextboxAtViewportCenter() {
            var vp = this.$refs.viewport;
            if (!vp) return;
            var rect = vp.getBoundingClientRect();
            var center = this.screenToCanvas(rect.left + rect.width / 2 - 160, rect.top + rect.height / 2 - 90);
            await this.createTextboxAtPos(center.x, center.y);
        },

        // ---- 樣式 ----
        getTextboxStyle(tb) {
            var bs = tb.border_style || 'solid';
            var border = bs === 'none' ? 'border:none;' : 'border:1.5px ' + bs + ' ' + tb.border_color + ';';
            return 'left:' + tb.pos_x + 'px;'
                 + 'top:' + tb.pos_y + 'px;'
                 + 'width:' + tb.width + 'px;'
                 + 'height:' + tb.height + 'px;'
                 + 'z-index:' + (tb.z_index || 1) + ';'
                 + 'background:' + tb.bg_color + ';'
                 + 'color:' + tb.text_color + ';'
                 + border;
        },

        getTextboxLabelStyle(tb) {
            // 頁籤緊貼框線左上外緣
            return 'background:' + tb.border_color + ';color:#fff;';
        },

        // ---- 拖拉移動（內文 textarea / resize / anchor 之外的區域均可拖拉，標題也可） ----
        onTextboxMouseDown(e, tb) {
            if (e.button !== 0) return;
            if (this.isSnapshot) return;
            if (e.target.closest('.wb-textbox-content')) return;
            if (e.target.closest('.wb-textbox-resize') || e.target.closest('.wb-textbox-anchor')) return;
            e.stopPropagation();
            this.dragTextbox = tb;
            this.textboxDragStartX = e.clientX;
            this.textboxDragStartY = e.clientY;
            this.textboxDragStartPos = { x: tb.pos_x, y: tb.pos_y };
        },

        onTextboxResizeMouseDown(e, tb) {
            if (e.button !== 0) return;
            if (this.isSnapshot) return;
            e.stopPropagation(); e.preventDefault();
            this.resizeTextbox = tb;
            this.resizeTextboxStartX = e.clientX;
            this.resizeTextboxStartY = e.clientY;
            this.resizeTextboxStartW = tb.width;
            this.resizeTextboxStartH = tb.height;
        },

        // ---- 內文編輯（textarea，直接 input 事件 debounce 寫回） ----
        startTextboxEdit(tb) {
            if (this.isSnapshot) return;
            this.editingTextboxId = tb.id;
        },

        finishTextboxEdit(tb) {
            this.editingTextboxId = null;
            this.flushTextboxContentSave(tb);
        },

        onTextboxContentInput(tb, value) {
            tb.content = value;
            var self = this;
            if (this._textboxContentSaveTimer) clearTimeout(this._textboxContentSaveTimer);
            this._textboxContentSaveTimer = setTimeout(function() {
                self._textboxContentSaveTimer = null;
                API.updateTextbox(tb.id, { content: tb.content })
                    .catch(function(e) { self.showToast('文字框儲存失敗：' + (e.message || e), 'error'); });
            }, 600);
        },

        flushTextboxContentSave(tb) {
            if (this._textboxContentSaveTimer) {
                clearTimeout(this._textboxContentSaveTimer);
                this._textboxContentSaveTimer = null;
            }
            API.updateTextbox(tb.id, { content: tb.content }).catch(function() {});
        },

        // ---- 設定 modal（雙擊標題） ----
        openTextboxEditModal(tb) {
            if (this.isSnapshot) return;
            this.editingTextbox = tb;
            var isTransparent = (tb.bg_color === 'transparent' || tb.bg_color === '');
            this.textboxForm = {
                title: tb.title,
                // 透明時 color picker 顯示一個 fallback（不會回寫），用來等用戶取消透明後可以馬上選色
                bg_color: isTransparent ? '#fffbe6' : tb.bg_color,
                bg_transparent: isTransparent,
                border_color: tb.border_color,
                border_style: tb.border_style || 'solid',
                text_color: tb.text_color,
            };
            this.showTextboxModal = true;
        },

        async saveTextboxEdit() {
            if (!this.editingTextbox) return;
            var tb = this.editingTextbox;
            var payload = {
                title: this.textboxForm.title,
                bg_color: this.textboxForm.bg_transparent ? 'transparent' : this.textboxForm.bg_color,
                border_color: this.textboxForm.border_color,
                border_style: this.textboxForm.border_style,
                text_color: this.textboxForm.text_color,
            };
            try {
                var resp = await API.updateTextbox(tb.id, payload);
                Object.assign(tb, resp);
                this.showTextboxModal = false;
                this.editingTextbox = null;
                this.$nextTick(() => this.renderConnections());
            } catch (e) {
                this.showToast('文字框儲存失敗：' + (e.message || e), 'error');
            }
        },

        closeTextboxModal() {
            this.showTextboxModal = false;
            this.editingTextbox = null;
        },

        // ---- 字紙簍 ----
        async sendTextboxToTrash(tb) {
            if (this.isSnapshot) return;
            try {
                await API.addTextboxesToCanvasTrash(this.canvasId, [tb.id]);
                this.textboxes = this.textboxes.filter(function(x) { return x.id !== tb.id; });
                this.connections = this.connections.filter(function(c) {
                    return !((c.from_kind === 'textbox' && c.source_textbox_id === tb.id)
                          || (c.to_kind === 'textbox' && c.target_textbox_id === tb.id));
                });
                this.$nextTick(() => this.renderConnections());
            } catch (e) {
                this.showToast('文字框刪除失敗：' + (e.message || e), 'error');
            }
        },

        // ---- 連線：textbox 端點查詢 ----
        getTextboxAnchorPos(tbId, anchor) {
            var tb = this.textboxes.find(function(x) { return x.id === tbId; });
            if (!tb) return { x: 0, y: 0 };
            var w = tb.width, h = tb.height;
            switch (anchor) {
                case 'top':    return { x: tb.pos_x + w / 2, y: tb.pos_y };
                case 'bottom': return { x: tb.pos_x + w / 2, y: tb.pos_y + h };
                case 'left':   return { x: tb.pos_x,         y: tb.pos_y + h / 2 };
                case 'right':  return { x: tb.pos_x + w,     y: tb.pos_y + h / 2 };
                default:       return { x: tb.pos_x + w / 2, y: tb.pos_y + h / 2 };
            }
        },

        findNearestTextboxAnchor(tbId, canvasX, canvasY) {
            var tb = this.textboxes.find(function(x) { return x.id === tbId; });
            if (!tb) return { x: canvasX, y: canvasY };
            var w = tb.width, h = tb.height;
            var anchors = [
                { x: tb.pos_x + w / 2, y: tb.pos_y },
                { x: tb.pos_x + w / 2, y: tb.pos_y + h },
                { x: tb.pos_x,         y: tb.pos_y + h / 2 },
                { x: tb.pos_x + w,     y: tb.pos_y + h / 2 },
            ];
            var nearest = anchors[0]; var minDist = Infinity;
            for (var i = 0; i < anchors.length; i++) {
                var d = Math.hypot(anchors[i].x - canvasX, anchors[i].y - canvasY);
                if (d < minDist) { minDist = d; nearest = anchors[i]; }
            }
            return nearest;
        },

        // textbox 連線拖拉：從錨點出發
        startTextboxConnDrag(e, tb, anchor) {
            if (this.isSnapshot) return;
            e.stopPropagation(); e.preventDefault();
            this.isConnDragging = true;
            this.connDragSourceKind = 'textbox';
            this.connDragSourceTextboxId = tb.id;
            this.connDragSourceAtomId = null;
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

        onTextboxMouseEnterForConn(tb) {
            if (!this.isConnDragging) return;
            // 不允許自己連自己
            var sameSource = (this.connDragSourceKind === 'textbox' && this.connDragSourceTextboxId === tb.id);
            if (!sameSource) {
                this.connDragHoverTextboxId = tb.id;
                this.connDragHoverAtomId = null;
            }
        },

        onTextboxMouseLeaveForConn(tb) {
            if (this.connDragHoverTextboxId === tb.id) {
                this.connDragHoverTextboxId = null;
            }
        },
    };
}
