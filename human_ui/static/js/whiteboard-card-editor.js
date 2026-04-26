/**
 * 白板 Mixin: Multi-Card Editor (Tiptap WYSIWYG)
 * 支援同時開啟 1~N 張卡片，自動排版
 *
 * _ceStore: Tiptap CardEditor 實例存放在閉包變數，
 * 避免 Alpine Proxy 包裹導致 ProseMirror transaction identity 檢查失敗。
 */
var _ceStore = {};  // { atomId: CardEditor instance } -- 不進入 Alpine reactive

function whiteboardCardEditorMixin() {
    return {

        // 多卡片編輯器狀態
        openEditors: [],       // [{ id, atomId, title, atomType, dirty, readonly }]
        _ceSeq: 0,
        cardEditorOpen: false, // 是否有任何卡片編輯器開啟
        ceSidebarOpen: false,  // 左側卡片選擇面板

        // Toolbar reactive 狀態 (per editorId)
        ceTableActive: {},     // { editorId: 游標是否在表格內 }
        ceHasCollapsed: {},    // { editorId: 是否仍有收合中的 ;; 物件 }

        // 右側抓重點
        ceStagingOpen: false,
        stagingMode: 'copy',     // 'copy' or 'move'
        transcribeMode: false,   // 謄寫模式：直接在兩文件間複製/移動
        stagingItems: [],        // [{ id, text, sourceAtomId, sourceTitle }]
        stagingTitle: '',        // 自訂新卡片標題（空白時用預設）
        _stagingSeq: 0,

        // 最大化
        maximizedEditorId: null,  // 目前最大化的 editorId，null = 無

        // 排版模式
        editorLayout: 'auto',
        customLayoutCols: 3,
        customLayoutRows: 2,

        get editorLayoutClass() {
            var count = this.openEditors.length;
            var m = this.editorLayout;
            // 卡片數少時，無論選什麼模式都用最合理的排版
            if (count <= 1) return 'ce-layout-single';
            if (count === 2 && (m === 'auto' || m === 'grid2' || m === 'grid3' || m === 'custom')) return 'ce-layout-row';
            if (count <= 4 && (m === 'auto' || m === 'grid3' || m === 'custom')) return 'ce-layout-grid2';
            // 卡片數夠多時才套用指定模式
            if (m === 'auto') return 'ce-layout-col';
            if (m === 'custom') return 'ce-layout-custom';
            return 'ce-layout-' + m;
        },

        get customGridStyle() {
            if (this.editorLayoutClass !== 'ce-layout-custom') return '';
            return 'display:grid; grid-template-columns:repeat(' + this.customLayoutCols + ',1fr); grid-template-rows:repeat(' + this.customLayoutRows + ',1fr);';
        },

        async openCardEditor(atomId) {
            // 如果已開啟同一張，聚焦
            var existing = this.openEditors.find(e => e.atomId === atomId);
            if (existing) {
                this._focusEditor(existing.id);
                return;
            }

            var resp = await API.getAtom(atomId);
            if (!resp || resp.error) { this.showToast('無法載入卡片', 'error'); return; }
            var atom = resp;
            var typeCfg = this.atomTypeConfig[atom.atom_type] || {};
            var editorId = ++this._ceSeq;

            // 從白板卡片資料取得阻塞狀態
            var ca = (this.canvasAtoms || []).find(function(c) { return c.atom_id === atomId; });
            var isBlocked = ca ? !!ca.is_blocked : false;

            // 同步白板本地快取的 updated_at（避免 polling 誤判）
            var ca2 = this.atoms.find(function(a) { return a.atom_id === atomId; });
            if (ca2 && ca2.atom && atom.updated_at) {
                ca2.atom.updated_at = atom.updated_at;
            }

            this.openEditors.push({
                id: editorId,
                atomId: atom.id,
                title: atom.title || '',
                atomType: typeCfg.label || atom.atom_type,
                isBlocked: isBlocked,
                dirty: false,
                readonly: this.isSnapshot || (atom.owner || 'ethan') !== 'ethan',
                _contentJson: atom.content_json || null,
                _content: atom.content || '',
                _knownServerTs: atom.updated_at || '',
            });
            if (!this.cardEditorOpen) {
                this.ceSidebarOpen = true;
                this.ceStagingOpen = true;
            }
            this.cardEditorOpen = true;

            var self = this;
            this.$nextTick(async () => {
                var host = document.querySelector('[data-ce-id="' + editorId + '"] .ce-pane-body');
                if (!host) return;

                // Make entry schemas available to NodeView
                window._entrySchemas = self.entrySchemas || [];

                var initializing = true;
                var ce = new window.CardEditor();
                ce.create(host, {
                    contentJson: atom.content_json || null,
                    content: atom.content || '',
                    onChange: function() { if (!initializing) self._markEditorDirty(editorId); },
                    onStateChange: function() { self._refreshToolbarState(editorId); },
                    editable: (atom.owner || 'ethan') === 'ethan',
                });

                // content_json 是文件結構唯一真實來源（保留表格/清單等結構）；
                // 但 entry_field_values 可能因 Gantt 拖拉等外部變動而比 content_json 內的 fieldValues 新，
                // 需用 entries 同步最新 fieldValues 進對應 structuredEntry node（不重建文件）。
                try {
                    var entries = await API.getEntries(atomId);
                    if (entries && entries.length > 0) {
                        if (atom.content_json) {
                            ce.syncFieldValuesFromEntries(entries);
                        } else {
                            // 舊資料無 content_json，退回原有重建路徑
                            ce.loadEntries(entries);
                        }
                    }
                } catch (e) { /* no entries yet, use content as-is */ }

                _ceStore[atomId] = ce;
                self.$nextTick(function() {
                    initializing = false;
                    self._refreshToolbarState(editorId);
                });
                self._focusEditor(editorId);
            });
        },

        _refreshToolbarState(editorId) {
            var ed = this.openEditors.find(function(e) { return e.id === editorId; });
            if (!ed) return;
            var ce = _ceStore[ed.atomId];
            if (!ce || !ce.editor) return;
            this.ceTableActive[editorId] = ce.isActive('table');
            this.ceHasCollapsed[editorId] = ce.hasCollapsedEntry();
        },

        ceInsertImage(editorId) {
            var ed = this.openEditors.find(function(e) { return e.id === editorId; });
            if (!ed) return;
            var url = prompt('輸入圖片 URL:');
            if (!url) return;
            var ce = _ceStore[ed.atomId];
            if (ce) ce.cmd('image', url);
        },

        ceUploadImage(editorId) {
            var ed = this.openEditors.find(function(e) { return e.id === editorId; });
            if (!ed) return;
            var self = this;
            var input = document.createElement('input');
            input.type = 'file';
            input.accept = 'image/png,image/jpeg,image/webp,image/gif';
            input.style.display = 'none';
            input.addEventListener('change', async function() {
                var file = input.files && input.files[0];
                if (!file) return;
                self.showToast('上傳圖片中...', 'info');
                try {
                    var rec = await API.uploadFile(file, 'image');
                    var ce = _ceStore[ed.atomId];
                    if (ce && rec && rec.url) {
                        ce.cmd('image', rec.url);
                        self._markEditorDirty(editorId);
                        self.showToast('圖片已上傳', 'success');
                    }
                } catch (err) {
                    self.showToast('上傳失敗: ' + err.message, 'error');
                }
                document.body.removeChild(input);
            }, { once: true });
            document.body.appendChild(input);
            input.click();
        },

        ceUploadFile(editorId) {
            var ed = this.openEditors.find(function(e) { return e.id === editorId; });
            if (!ed) return;
            var self = this;
            var input = document.createElement('input');
            input.type = 'file';
            input.style.display = 'none';
            input.addEventListener('change', async function() {
                var file = input.files && input.files[0];
                if (!file) return;
                self.showToast('上傳檔案中...', 'info');
                try {
                    var rec = await API.uploadFile(file, 'file');
                    var ce = _ceStore[ed.atomId];
                    if (!ce || !ce.editor || !rec) return;
                    var fileSchema = (self.entrySchemas || []).find(function(s) { return s.code === 'file'; });
                    if (!fileSchema) {
                        self.showToast('找不到 file schema，請重新整理頁面', 'error');
                        return;
                    }
                    ce.editor.chain().focus().insertContent({
                        type: 'structuredEntry',
                        attrs: {
                            schemaCode: 'file',
                            schemaId: fileSchema.id,
                            collapsed: true,
                            fieldValues: {
                                filename: rec.original_filename,
                                file_token: rec.token,
                                mime_type: rec.mime_type,
                                size_bytes: String(rec.size_bytes),
                            },
                        },
                        content: [],
                    }).run();
                    self._markEditorDirty(editorId);
                    self.showToast('檔案已上傳', 'success');
                } catch (err) {
                    self.showToast('上傳失敗: ' + err.message, 'error');
                }
                document.body.removeChild(input);
            }, { once: true });
            document.body.appendChild(input);
            input.click();
        },

        ceToggleAllEntries(editorId) {
            var ed = this.openEditors.find(function(e) { return e.id === editorId; });
            if (!ed) return;
            var ce = _ceStore[ed.atomId];
            if (!ce) return;
            // 有任一收合 -> 全展開；否則 -> 全收合
            var collapse = !ce.hasCollapsedEntry();
            var n = ce.setAllEntriesCollapsed(collapse);
            this._refreshToolbarState(editorId);
            if (n === 0) {
                this.showToast('沒有 ;; 物件可切換', 'warning');
            } else {
                this.showToast((collapse ? '已全部收合 ' : '已全部展開 ') + n + ' 個 ;; 物件', 'success');
            }
        },

        _markEditorDirty(editorId) {
            var ed = this.openEditors.find(e => e.id === editorId);
            if (ed) ed.dirty = true;
        },

        _focusEditor(editorId) {
            var el = document.querySelector('[data-ce-id="' + editorId + '"]');
            if (!el) return;
            el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            el.classList.remove('ce-pane-flash');
            void el.offsetWidth;
            el.classList.add('ce-pane-flash');
            setTimeout(function() { el.classList.remove('ce-pane-flash'); }, 2000);
        },

        async saveEditor(editorId) {
            var ed = this.openEditors.find(e => e.id === editorId);
            if (!ed) return;
            var ce = _ceStore[ed.atomId];
            if (!ce) return;

            var md = ce.getMarkdown();
            var json = ce.getJSON();
            var title = ed.title;

            // Sync structured entries to DB
            var entries = ce.extractEntries();
            var hasStructuredEntries = entries.some(e => e.schema_code !== 'freetext');

            if (hasStructuredEntries || entries.length > 0) {
                try {
                    var syncResult = await API.syncEntries(ed.atomId, entries);
                    // 用後端回傳的 raw_text 串接作為搜尋用 content（atom.content 只供關鍵字檢索）
                    md = syncResult.content_snapshot || md;

                    // 只把 DB 新賦予的 entryId 寫回對應節點，不重建文件 -- 避免遺失表格/清單/標題結構
                    if (syncResult.entries) {
                        ce.writeBackEntryIds(syncResult.entries);
                        // entryId 寫回後 doc 變動，重新取一次 JSON 才能存到 atom.content_json
                        json = ce.getJSON();
                    }
                } catch (e) {
                    console.warn('Entry sync failed, falling back to content save:', e);
                }
            }

            var saveResp = await API.updateAtom(ed.atomId, { title: title, content: md, content_json: json });

            // 用伺服器回傳的 updated_at，避免 polling 誤判
            var serverTs = (saveResp && saveResp.updated_at) || new Date().toISOString();
            // thumbnail_url 由後端從 content_json 萃取後回傳，前端直接同步給白板對應卡片
            var serverThumb = saveResp ? saveResp.thumbnail_url : undefined;
            var ca = this.atoms.find(a => a.atom_id === ed.atomId);
            if (ca && ca.atom) {
                ca.atom.title = title; ca.atom.content = md; ca.atom.content_json = json;
                ca.atom.updated_at = serverTs;
                if (serverThumb !== undefined) ca.atom.thumbnail_url = serverThumb;
            }
            ed._knownServerTs = serverTs;
            if (this.selectedAtomDetails && this.selectedAtomDetails.id === ed.atomId) {
                this.selectedAtomDetails.title = title; this.selectedAtomDetails.content = md;
                if (serverThumb !== undefined) this.selectedAtomDetails.thumbnail_url = serverThumb;
            }
            ed.dirty = false;
            this.refreshSidebarAtoms();
            this.showToast('已儲存', 'success');
        },

        toggleMaximize(editorId) {
            if (this.maximizedEditorId === editorId) {
                // 還原：清除 inline style
                this.maximizedEditorId = null;
                var pane = document.querySelector('[data-ce-id="' + editorId + '"]');
                if (pane) {
                    pane.style.top = '';
                    pane.style.left = '';
                    pane.style.width = '';
                    pane.style.height = '';
                }
                return;
            }
            this.maximizedEditorId = editorId;
            this.$nextTick(function() {
                var pane = document.querySelector('[data-ce-id="' + editorId + '"]');
                var container = pane && pane.parentElement;
                if (!pane || !container) return;
                pane.style.top = container.scrollTop + 'px';
                pane.style.left = '0';
                pane.style.width = container.clientWidth + 'px';
                pane.style.height = container.clientHeight + 'px';
            });
        },

        closeEditor(editorId) {
            var idx = this.openEditors.findIndex(e => e.id === editorId);
            if (idx < 0) return;
            var ed = this.openEditors[idx];
            if (ed.dirty) { if (!confirm('「' + ed.title + '」尚未儲存，確定關閉？')) return; }

            if (this.maximizedEditorId === editorId) {
                this.maximizedEditorId = null;
                var pane = document.querySelector('[data-ce-id="' + editorId + '"]');
                if (pane) { pane.style.top = ''; pane.style.left = ''; pane.style.width = ''; pane.style.height = ''; }
            }
            var ce = _ceStore[ed.atomId];
            if (ce) { ce.destroy(); delete _ceStore[ed.atomId]; }

            this.openEditors.splice(idx, 1);
            if (this.openEditors.length === 0) {
                this.cardEditorOpen = false;
                this.dragCard = null; this.bodyDragPending = false; this.bodyDragCa = null;
            }
            this.$nextTick(() => { this.renderConnections(); });
        },

        _closeAllEditors() {
            for (var i = this.openEditors.length - 1; i >= 0; i--) {
                var ed = this.openEditors[i];
                var ce = _ceStore[ed.atomId];
                if (ce) { ce.destroy(); delete _ceStore[ed.atomId]; }
            }
            this.openEditors = [];
            this.maximizedEditorId = null;
            this.cardEditorOpen = false;
            this.dragCard = null; this.bodyDragPending = false; this.bodyDragCa = null;
            this.$nextTick(() => { this.renderConnections(); });
        },

        async saveAllAndClose() {
            for (var i = 0; i < this.openEditors.length; i++) {
                var ed = this.openEditors[i];
                if (ed.dirty && !ed.readonly) await this.saveEditor(ed.id);
            }
            this._closeAllEditors();
        },

        discardAllAndClose() {
            this._closeAllEditors();
        },

        // 兼容舊呼叫（ESC 鍵等）
        closeCardEditor() {
            var hasDirty = this.openEditors.some(function(e) { return e.dirty; });
            if (hasDirty) {
                if (!confirm('有未儲存的卡片，確定不儲存並關閉？')) return;
            }
            this._closeAllEditors();
        },

        ceInsertLink(editorId) {
            var ed = this.openEditors.find(e => e.id === editorId);
            if (!ed) return;
            var url = prompt('輸入連結 URL:');
            if (url) {
                var ce = _ceStore[ed.atomId];
                if (ce) ce.cmd('link', url);
            }
        },

        ceCmd(command, editorId) {
            var ed = this.openEditors.find(e => e.id === editorId);
            if (!ed) return;
            var ce = _ceStore[ed.atomId];
            if (ce) ce.cmd(command);
        },

        ceIsActive(name, attrs, editorId) {
            var ed = this.openEditors.find(e => e.id === editorId);
            if (!ed) return false;
            var ce = _ceStore[ed.atomId];
            if (!ce) return false;
            return ce.isActive(name, attrs);
        },

        saveCardEditor() {
            // 儲存所有 dirty 的（兼容舊呼叫）
            this.openEditors.forEach(ed => { if (ed.dirty) this.saveEditor(ed.id); });
        },

        undoDeletedEntry(editorId) {
            if (!window._deletedEntries || window._deletedEntries.length === 0) {
                this.showToast('沒有可復原的 Item', 'warning');
                return;
            }
            var ed = this.openEditors.find(function(e) { return e.id === editorId; });
            if (!ed) return;
            var ce = _ceStore[ed.atomId];
            if (!ce || !ce.editor) return;
            var last = window._deletedEntries.pop();
            // 插入到文件末尾，避免覆蓋游標所在的 node
            var endPos = ce.editor.state.doc.content.size;
            ce.editor.chain().focus().insertContentAt(endPos, last.node).run();
            this.showToast('已復原: ' + (last.text || '(空白 Item)').substring(0, 30), 'success');
        },

        async openSelectedInEditor() {
            if (!this.selectedAtomIds || this.selectedAtomIds.length === 0) return;
            var ids = this.selectedAtomIds.slice();
            for (var i = 0; i < ids.length; i++) {
                await this.openCardEditor(ids[i]);
            }
        },

        // ============================================
        // 暫存區 Staging
        // ============================================

        toggleStaging() {
            this.ceStagingOpen = !this.ceStagingOpen;
        },

        ceHandleSelection(editorId) {
            if (!this.ceStagingOpen) return;
            var ed = this.openEditors.find(function(e) { return e.id === editorId; });
            if (!ed || ed.readonly) return;
            var ce = _ceStore[ed.atomId];
            if (!ce) return;

            // 單一原子操作：讀取 + 刪除（若為移動模式）在同一 state 上完成
            var shouldDelete = this.stagingMode === 'move';

            // 謄寫模式：直接在兩文件間複製/移動
            if (this.transcribeMode && this.openEditors.length === 2) {
                var info = ce.captureSelection(shouldDelete);
                if (!info) return;
                var other = this.openEditors.find(function(e) { return e.id !== editorId; });
                if (!other) return;
                var otherCe = _ceStore[other.atomId];
                if (!otherCe || !otherCe.editor) return;
                // 用 contentJson 插入，保留 structuredEntry node 結構
                otherCe.editor.commands.insertContent(info.contentJson);
                this._markEditorDirty(other.id);
                if (shouldDelete) this._markEditorDirty(editorId);
                return;
            }

            var info = ce.captureSelection(shouldDelete);
            if (!info) return;

            if (shouldDelete) this._markEditorDirty(editorId);
            this.addToStaging(info.markdown, ed.atomId, ed.title, info.contentJson);
        },

        addToStaging(text, atomId, title, contentJson) {
            this.stagingItems.push({
                id: ++this._stagingSeq,
                text: text,
                contentJson: contentJson || null,
                sourceAtomId: atomId,
                sourceTitle: title || '#' + atomId,
            });
            this.$nextTick(function() {
                var list = document.querySelector('.ce-staging-list');
                if (list) list.scrollTop = list.scrollHeight;
            });
        },

        removeStagingItem(itemId) {
            var idx = this.stagingItems.findIndex(function(s) { return s.id === itemId; });
            if (idx >= 0) this.stagingItems.splice(idx, 1);
        },

        moveStagingItem(idx, direction) {
            var target = idx + direction;
            if (target < 0 || target >= this.stagingItems.length) return;
            var items = this.stagingItems;
            var tmp = items[idx];
            items.splice(idx, 1);
            items.splice(target, 0, tmp);
        },

        clearStaging() {
            if (this.stagingItems.length === 0) return;
            if (!confirm('清空暫存區所有片段？')) return;
            this.stagingItems = [];
        },

        async saveStagingAsAtom() {
            if (this.stagingItems.length === 0) { this.showToast('暫存區無內容', 'error'); return; }

            // 組合純文字（fallback）
            var combined = this.stagingItems.map(function(s) { return s.text; }).join('\n\n');
            // 組合 JSON 內容（保留 structuredEntry 等 node）
            var allContent = [];
            this.stagingItems.forEach(function(s) {
                if (s.contentJson && Array.isArray(s.contentJson)) {
                    s.contentJson.forEach(function(n) { allContent.push(n); });
                }
            });
            var contentJson = allContent.length > 0 ? { type: 'doc', content: allContent } : null;

            var title = this.stagingTitle.trim() || ('重組筆記 (' + this.stagingItems.length + ' 片段)');
            try {
                var atom = await API.createAtom({
                    title: title,
                    content: combined,
                    content_json: contentJson,
                    atom_type: 'A',
                    source: 'human',
                });
                var vpX = (-this.panX / this.zoom) + 300 + Math.random() * 100;
                var vpY = (-this.panY / this.zoom) + 200 + Math.random() * 100;
                await API.addAtomToCanvas(this.canvasId, { atom_id: atom.id, pos_x: vpX, pos_y: vpY });

                this.stagingItems = [];
                this.stagingTitle = '';
                await this.loadData();
                this.$nextTick(function() { this.renderConnections(); }.bind(this));
                this.showToast('已建立新卡片 #' + atom.id, 'success');
            } catch (e) {
                this.showToast('建立失敗: ' + e.message, 'error');
            }
        },

        // ============================================================
        //  Polling: 偵測遠端變更 + 衝突提示
        // ============================================================

        _pollTimer: null,
        _lastPollAt: null,

        startPolling() {
            if (this._pollTimer) return;
            this._lastPollAt = new Date().toISOString();
            var self = this;
            this._pollTimer = setInterval(function() { self._pollOnce(); }, 5000);
        },

        stopPolling() {
            if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = null; }
        },

        async _pollOnce() {
            if (!this.canvasId) return;
            try {
                var resp = await API.pollCanvas(this.canvasId, this._lastPollAt);
                if (!resp || !resp.atoms) return;
                this._lastPollAt = new Date().toISOString();
                this._handlePollResult(resp.atoms, resp.changes || []);
            } catch (e) { /* polling 失敗不打擾用戶 */ }
        },

        _handlePollResult(remoteAtoms, changes) {
            var remoteMap = {};
            for (var i = 0; i < remoteAtoms.length; i++) {
                remoteMap[remoteAtoms[i].atom_id] = remoteAtoms[i].updated_at;
            }

            // 按 atom_id 分組變更明細
            var changesByAtom = {};
            for (var ci = 0; ci < changes.length; ci++) {
                var c = changes[ci];
                if (!changesByAtom[c.atom_id]) changesByAtom[c.atom_id] = [];
                changesByAtom[c.atom_id].push(c);
            }

            var self = this;
            var updatedIds = [];

            for (var j = 0; j < this.atoms.length; j++) {
                var ca = this.atoms[j];
                if (!ca.atom) continue;
                var remoteTs = remoteMap[ca.atom_id];
                if (!remoteTs) continue;

                var localTs = ca.atom.updated_at || '';
                if (remoteTs <= localTs) continue;

                // 遠端有更新 -- 檢查是否正在編輯
                var ed = self.openEditors.find(function(e) { return e.atomId === ca.atom_id; });
                if (ed) {
                    // 用 _knownServerTs 比對，避免開啟時 getAtom 造成的時間差誤判
                    var knownTs = ed._knownServerTs || '';
                    if (remoteTs <= knownTs) continue;
                    // 已在衝突中 -> 跳過
                    if (ed._conflict) continue;
                    ed._conflict = true;
                    ed._conflictTs = remoteTs;
                    ed._conflictChanges = changesByAtom[ca.atom_id] || [];
                    self._showConflictUI(ed);
                } else {
                    // 未編輯 -> 靜默更新
                    updatedIds.push(ca.atom_id);
                }
            }

            if (updatedIds.length > 0) {
                this._silentUpdateAtoms(updatedIds);
            }
        },

        async _silentUpdateAtoms(atomIds) {
            for (var i = 0; i < atomIds.length; i++) {
                try {
                    var atom = await API.getAtom(atomIds[i]);
                    if (!atom || atom.error) continue;
                    var ca = this.atoms.find(function(a) { return a.atom_id === atomIds[i]; });
                    if (ca && ca.atom) {
                        ca.atom.title = atom.title;
                        ca.atom.content = atom.content;
                        ca.atom.content_json = atom.content_json;
                        ca.atom.updated_at = atom.updated_at;
                        ca.atom.tags = atom.tags || ca.atom.tags;
                    }
                } catch (e) { /* 個別失敗不影響其他 */ }
            }
            this.refreshSidebarAtoms();
        },

        _showConflictUI(ed) {
            var el = document.querySelector('[data-ce-id="' + ed.id + '"]');
            if (!el) return;
            el.classList.add('ce-pane-conflict');

            // 插入衝突提示 banner（如果尚未存在）
            if (el.querySelector('.ce-conflict-banner')) return;
            var header = el.querySelector('.ce-pane-header');
            if (!header) return;

            // 組裝變更明細文字
            var detailHtml = '';
            var changes = ed._conflictChanges || [];
            if (changes.length > 0) {
                var parts = [];
                for (var i = 0; i < Math.min(changes.length, 5); i++) {
                    var c = changes[i];
                    var old = c.old || '-';
                    var nv = c['new'] || '-';
                    // 截斷過長的值
                    if (old.length > 20) old = old.slice(0, 20) + '...';
                    if (nv.length > 20) nv = nv.slice(0, 20) + '...';
                    parts.push('<span style="color:#6c757d;">' + (c.label || c.field) + ':</span> ' + old + ' &rarr; ' + nv);
                }
                if (changes.length > 5) parts.push('...(+' + (changes.length - 5) + ')');
                detailHtml = '<div class="ce-conflict-detail">' + parts.join(' | ') + '</div>';
            }

            var banner = document.createElement('div');
            banner.className = 'ce-conflict-banner';
            banner.innerHTML =
                '<div>' +
                '<span class="ce-conflict-msg">遠端已更新</span>' +
                detailHtml +
                '</div>' +
                '<span style="white-space:nowrap;">' +
                '<button class="btn btn-sm btn-outline-danger ce-conflict-save">覆蓋遠端</button> ' +
                '<button class="btn btn-sm btn-outline-secondary ce-conflict-reload">載入遠端</button>' +
                '</span>';
            header.insertAdjacentElement('afterend', banner);

            var self = this;
            banner.querySelector('.ce-conflict-save').addEventListener('click', function() {
                self._resolveConflict(ed, 'save');
            });
            banner.querySelector('.ce-conflict-reload').addEventListener('click', function() {
                self._resolveConflict(ed, 'reload');
            });
        },

        async _resolveConflict(ed, action) {
            if (action === 'save') {
                await this.saveEditor(ed.id);
            } else if (action === 'reload') {
                // 從伺服器重新載入
                var atom = await API.getAtom(ed.atomId);
                if (atom && !atom.error) {
                    var ce = _ceStore[ed.atomId];
                    if (ce) {
                        // 保留 reload 前用戶展開的 entryId，reload 後若仍存在則恢復展開
                        var expandedIds = ce.getExpandedEntryIds();

                        if (atom.content_json) {
                            // content_json 已含完整結構（包含每個 entry 的 collapsed），不再呼叫 loadEntries
                            // -- loadEntries 會 hardcode collapsed=true，違反「保持原本狀態」
                            ce.setContentJSON(atom.content_json);
                            // 但 entry_field_values 可能比 content_json 內的 fieldValues 新（如 Gantt 拖拉），
                            // 需用 entries 同步最新欄位值進對應節點。
                            try {
                                var rEntries = await API.getEntries(ed.atomId);
                                if (rEntries && rEntries.length > 0) ce.syncFieldValuesFromEntries(rEntries);
                            } catch (e) { /* ignore */ }
                        } else {
                            ce.setContent(atom.content || '');
                            try {
                                var entries = await API.getEntries(ed.atomId);
                                if (entries && entries.length > 0) ce.loadEntries(entries);
                            } catch (e) { /* ignore */ }
                        }

                        if (expandedIds.length > 0) ce.expandEntriesByIds(expandedIds);
                    }
                    ed.title = atom.title;
                    ed.dirty = false;
                    ed._contentJson = atom.content_json;
                    ed._content = atom.content;
                    ed._knownServerTs = atom.updated_at || '';

                    // 更新白板上的資料
                    var ca = this.atoms.find(function(a) { return a.atom_id === ed.atomId; });
                    if (ca && ca.atom) {
                        ca.atom.title = atom.title;
                        ca.atom.content = atom.content;
                        ca.atom.content_json = atom.content_json;
                        ca.atom.updated_at = atom.updated_at;
                    }
                    this.refreshSidebarAtoms();
                }
            }
            this._clearConflictUI(ed);
        },

        _clearConflictUI(ed) {
            ed._conflict = false;
            ed._conflictTs = null;
            var el = document.querySelector('[data-ce-id="' + ed.id + '"]');
            if (!el) return;
            el.classList.remove('ce-pane-conflict');
            var banner = el.querySelector('.ce-conflict-banner');
            if (banner) banner.remove();
        },
    };
}
