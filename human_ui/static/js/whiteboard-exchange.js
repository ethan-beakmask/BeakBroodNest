/**
 * 白板 Mixin: 交換卡片（寄存 / 取出）
 *
 * 用語對齊：
 *   - 寄存 = 從白板放入交換包；mode='copy' 不動白板，'move' 解除 canvas_atoms 連結
 *   - 取出 = 從交換包取到當前白板；單張滑鼠跟隨，多張陣列排列 + 自動建紅色群組
 *   - 永久寄存：取出後包仍存在，不會自動清空
 */
function whiteboardExchangeMixin() {
    return {

        // ============================================
        // 狀態 reset
        // ============================================
        _resetExchangeState() {
            this.showExchangeModal = false;
            this.exchangeTab = 'take';
            this.exchangeView = 'list';
            this.exchangePacks = [];
            this.exchangePackDetail = null;
            this.exchangeSelectedAtomIds = [];
            this.exchangeStashName = '';
            this.exchangeStashMode = 'copy';
        },

        // 是否能寄存（有選卡片）
        get exchangeStashAvailable() {
            var multi = (this.selectedAtomIds || []).length;
            var single = this.selectedAtomId ? 1 : 0;
            return (multi + single) > 0;
        },

        // 取出時要寄存的卡片 atom_id 陣列
        _getStashAtomIds() {
            if (this.selectedAtomIds && this.selectedAtomIds.length > 0) {
                return this.selectedAtomIds.slice();
            }
            if (this.selectedAtomId) {
                return [this.selectedAtomId];
            }
            return [];
        },

        // ============================================
        // 開關 modal
        // ============================================
        async openExchangeModal() {
            if (this.isSnapshot) { this.showToast('歸檔白板為唯讀快照', 'warn'); return; }
            this.cancelExchangeFollow();
            this.exchangeView = 'list';
            this.exchangePackDetail = null;
            this.exchangeSelectedAtomIds = [];

            // 預設 tab：有選卡片開「寄存」，否則「取出」
            if (this.exchangeStashAvailable) {
                this.exchangeTab = 'stash';
                this._fillDefaultStashName();
            } else {
                this.exchangeTab = 'take';
            }

            // 先開 modal 再非同步載入清單，避免畫面卡頓
            this.showExchangeModal = true;
            try {
                var resp = await API.getExchangePacks();
                this.exchangePacks = resp.items || [];
            } catch (e) {
                this.showToast(e.message || '載入交換包失敗', 'error');
            }
        },

        closeExchangeModal() {
            this._resetExchangeState();
        },

        _fillDefaultStashName() {
            var ids = this._getStashAtomIds();
            if (ids.length === 1) {
                var ca = this.atoms.find(function(a) { return a.atom_id === ids[0]; });
                this.exchangeStashName = (ca && ca.atom && ca.atom.title) ? ca.atom.title : '單卡';
            } else {
                var canvasName = (this.canvas && this.canvas.name) ? this.canvas.name : '白板';
                var d = new Date();
                var pad = function(n) { return n < 10 ? '0' + n : '' + n; };
                var stamp = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
                          + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
                this.exchangeStashName = canvasName + ' ' + stamp;
            }
        },

        // ============================================
        // 寄存
        // ============================================
        async confirmExchangeStash() {
            var atomIds = this._getStashAtomIds();
            if (atomIds.length === 0) { this.showToast('沒有選擇卡片', 'warn'); return; }
            var name = (this.exchangeStashName || '').trim();
            if (!name) { this.showToast('請輸入名稱', 'warn'); return; }

            try {
                await API.createExchangePack({
                    name: name,
                    source_canvas_id: this.canvas ? this.canvas.id : null,
                    mode: this.exchangeStashMode,
                    atom_ids: atomIds,
                });
                var n = atomIds.length;
                var modeLabel = this.exchangeStashMode === 'move' ? '移動' : '複製';
                this.showToast('已' + modeLabel + ' ' + n + ' 張卡片到「' + name + '」', 'success');
                this.closeExchangeModal();
                // 移動模式 -- 重載資料以反映白板變化
                if (this.exchangeStashMode === 'move') {
                    this.selectedAtomIds = [];
                    this.deselectCard();
                    await this.loadData();
                    this.$nextTick(() => this.renderConnections());
                }
            } catch (e) {
                this.showToast(e.message || '寄存失敗', 'error');
            }
        },

        // ============================================
        // 取出 -- 包列表 / 詳情
        // ============================================
        async openExchangePackDetail(packId) {
            try {
                var detail = await API.getExchangePack(packId);
                this.exchangePackDetail = detail;
                // 預設全選：用戶通常想取出全部，再視情況取消勾選
                this.exchangeSelectedAtomIds = (detail.items || []).map(function(it) { return it.id; });
                this.exchangeView = 'detail';
            } catch (e) {
                this.showToast(e.message || '載入失敗', 'error');
            }
        },

        toggleExchangeAtomSelect(atomId) {
            var i = this.exchangeSelectedAtomIds.indexOf(atomId);
            if (i >= 0) this.exchangeSelectedAtomIds.splice(i, 1);
            else this.exchangeSelectedAtomIds.push(atomId);
        },

        toggleSelectAllExchangeAtoms() {
            if (!this.exchangePackDetail) return;
            var items = this.exchangePackDetail.items || [];
            if (this.exchangeSelectedAtomIds.length === items.length) {
                this.exchangeSelectedAtomIds = [];
            } else {
                this.exchangeSelectedAtomIds = items.map(function(it) { return it.id; });
            }
        },

        // ============================================
        // 取用：依選擇張數 -- 1 -> 滑鼠跟隨；>=2 -> 陣列排列
        // ============================================
        async confirmTakeFromExchange() {
            if (!this.exchangePackDetail) return;
            var n = this.exchangeSelectedAtomIds.length;
            if (n === 0) { this.showToast('請選擇要取用的卡片', 'warn'); return; }

            if (n === 1) {
                // 單張 -- 進入滑鼠跟隨模式
                var atomId = this.exchangeSelectedAtomIds[0];
                var item = (this.exchangePackDetail.items || []).find(function(it) { return it.id === atomId; });
                if (!item) return;
                this._enterExchangeFollow(this.exchangePackDetail.id, item);
                this.showExchangeModal = false; // 暫時隱藏 modal，落下後完全關閉
                return;
            }

            // 多張 -- 陣列放置 + 自動建群組
            await this._placeMultiTakeArray();
        },

        async _placeMultiTakeArray() {
            if (!this.exchangePackDetail) return;
            var pack = this.exchangePackDetail;
            var atomIds = this.exchangeSelectedAtomIds.slice();
            var items = (pack.items || []).filter(function(it) { return atomIds.indexOf(it.id) >= 0; });
            if (items.length === 0) return;

            var positions = this._computeArrayPlacement(items.length);
            var payloadItems = items.map(function(it, idx) {
                return {
                    atom_id: it.id,
                    pos_x: positions[idx].x,
                    pos_y: positions[idx].y,
                    width: it.original_width || null,
                    height: it.original_height || null,
                };
            });

            try {
                await API.takeFromExchangePack(pack.id, {
                    canvas_id: this.canvas.id,
                    items: payloadItems,
                    group_name: pack.name,
                    group_color: '#dc2626',
                });
                this.showToast('已取用 ' + items.length + ' 張卡片並建立群組', 'success');
                this.closeExchangeModal();
                await this.loadData();
                this.$nextTick(() => this.renderConnections());
            } catch (e) {
                this.showToast(e.message || '取用失敗', 'error');
            }
        },

        // 陣列放置演算法：grid + 整體推擠避撞
        // 從 viewport 左上 (offset 24, 80) 開始，sqrt(n) 列；若與既有卡片重疊則整塊下移
        _computeArrayPlacement(n) {
            var cols = Math.ceil(Math.sqrt(n));
            var rows = Math.ceil(n / cols);
            var defaultW = 260, defaultH = 120, gap = 24;
            var totalW = cols * defaultW + (cols - 1) * gap;
            var totalH = rows * defaultH + (rows - 1) * gap;

            var startX = (-this.panX / this.zoom) + 24;
            var startY = (-this.panY / this.zoom) + 80;

            var existingBoxes = (this.atoms || []).map(function(ca) {
                return {
                    x: ca.pos_x,
                    y: ca.pos_y,
                    w: ca.width || defaultW,
                    h: ca.height || defaultH,
                };
            });

            function blockOverlaps(x, y) {
                return existingBoxes.some(function(b) {
                    return !(x + totalW + gap <= b.x ||
                             x >= b.x + b.w + gap ||
                             y + totalH + gap <= b.y ||
                             y >= b.y + b.h + gap);
                });
            }

            var tryY = startY;
            var safety = 200;
            while (blockOverlaps(startX, tryY) && safety-- > 0) {
                tryY += defaultH + gap * 2;
            }

            var positions = [];
            for (var i = 0; i < n; i++) {
                var col = i % cols;
                var row = Math.floor(i / cols);
                positions.push({
                    x: startX + col * (defaultW + gap),
                    y: tryY + row * (defaultH + gap),
                });
            }
            return positions;
        },

        // ============================================
        // 單張取用 -- 滑鼠跟隨
        // ============================================
        _enterExchangeFollow(packId, item) {
            this.exchangeFollowItem = item;
            this.exchangeFollowPackId = packId;
            this.exchangeFollowMouseX = 0;
            this.exchangeFollowMouseY = 0;
        },

        cancelExchangeFollow() {
            if (!this.exchangeFollowItem) return;
            this.exchangeFollowItem = null;
            this.exchangeFollowPackId = null;
        },

        // 由 onViewportMouseMove 呼叫
        _updateExchangeFollowPos(e) {
            if (!this.exchangeFollowItem) return;
            this.exchangeFollowMouseX = e.clientX;
            this.exchangeFollowMouseY = e.clientY;
        },

        // 由 onViewportMouseDown 呼叫；回傳 true 表示已處理
        _tryHandleExchangeFollowDrop(e) {
            if (!this.exchangeFollowItem) return false;
            if (e.button !== 0) {
                // 右鍵或中鍵 -- 取消
                this.cancelExchangeFollow();
                return true;
            }
            // 必須是 viewport 空白（不在卡片/群組/工具列上）
            if (e.target.closest('.wb-card') || e.target.closest('.wb-group')
                || e.target.closest('.wb-toolbar') || e.target.closest('.wb-zoom')
                || e.target.closest('.wb-batch-bar') || e.target.closest('.modal-overlay')
                || e.target.closest('.context-menu')) {
                return false;  // 落到非空白區，忽略本次點擊
            }

            var pos = this.screenToCanvas(e.clientX, e.clientY);
            var item = this.exchangeFollowItem;
            var packId = this.exchangeFollowPackId;
            var self = this;

            // 落下後立即清狀態，避免重入
            this.cancelExchangeFollow();
            e.preventDefault();
            e.stopPropagation();

            (async function() {
                try {
                    await API.takeFromExchangePack(packId, {
                        canvas_id: self.canvas.id,
                        items: [{
                            atom_id: item.id,
                            pos_x: pos.x - 130,  // 卡片寬度一半
                            pos_y: pos.y - 60,
                            width: item.original_width || null,
                            height: item.original_height || null,
                        }],
                    });
                    self.showToast('已取用「' + (item.title || '卡片') + '」', 'success');
                    await self.loadData();
                    self.$nextTick(function() { self.renderConnections(); });
                } catch (err) {
                    self.showToast(err.message || '取用失敗', 'error');
                }
            })();
            return true;
        },

        // ============================================
        // 從包刪除選中卡片
        // ============================================
        async confirmRemoveAtomsFromPack() {
            if (!this.exchangePackDetail) return;
            var atomIds = this.exchangeSelectedAtomIds.slice();
            if (atomIds.length === 0) return;
            var ok = confirm('從交換包刪除 ' + atomIds.length + ' 張卡片？\n（卡片本體與其他白板的引用不受影響）');
            if (!ok) return;
            try {
                await API.removeAtomsFromPack(this.exchangePackDetail.id, atomIds);
                this.showToast('已從包移除 ' + atomIds.length + ' 張', 'success');
                // 重載 detail + list
                await this.openExchangePackDetail(this.exchangePackDetail.id);
                var resp = await API.getExchangePacks();
                this.exchangePacks = resp.items || [];
            } catch (e) {
                this.showToast(e.message || '刪除失敗', 'error');
            }
        },

        async confirmDeleteExchangePack() {
            if (!this.exchangePackDetail) return;
            var pack = this.exchangePackDetail;
            var ok = confirm('刪除整個交換包「' + pack.name + '」？\n包內 ' + ((pack.items || []).length) + ' 張卡片的引用會解除（卡片本體不受影響）');
            if (!ok) return;
            try {
                await API.deleteExchangePack(pack.id);
                this.showToast('交換包已刪除', 'success');
                this.exchangePackDetail = null;
                this.exchangeSelectedAtomIds = [];
                this.exchangeView = 'list';
                var resp = await API.getExchangePacks();
                this.exchangePacks = resp.items || [];
            } catch (e) {
                this.showToast(e.message || '刪除失敗', 'error');
            }
        },
    };
}
