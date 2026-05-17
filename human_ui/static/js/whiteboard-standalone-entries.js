/**
 * 白板 Mixin: 獨立 structuredEntry (canvas_standalone_entries) -- P3a
 * 與卡片同階層的結構化條目（;;td / ;;cal / ;;idcard 等），不寄生於 atom。
 * 沿用 .se-block / .se-{schemaCode} CSS class，外觀與卡片內 entry 一致。
 *
 * State 在 whiteboard.js 主 app 宣告：standaloneEntries = []
 *   每筆形如 { id, canvas_id, standalone_entry_id, pos_x, pos_y, width, height, z_index, visual_style, entry: {...} }
 *   entry 內 { id, schema_code, raw_text, summary, field_values, node_id, ... }
 */
function whiteboardStandaloneEntriesMixin() {
    return {
        // ---- drag/edit state ----
        dragStandaloneEntry: null,
        seDragStartX: 0,
        seDragStartY: 0,
        seDragStartPos: null,
        editingStandaloneEntry: null,  // 開 entry-modal 的目標

        // ---- 新增（用戶從工具列下拉選 schema_code 後呼叫） ----
        async addStandaloneEntryAtViewportCenter(schemaCode) {
            if (this.isSnapshot) { this.showToast('歸檔白板為唯讀快照', 'warn'); return; }
            var vp = this.$refs.viewport;
            if (!vp) return;
            var rect = vp.getBoundingClientRect();
            var center = this.screenToCanvas(
                rect.left + rect.width / 2 - 140,
                rect.top + rect.height / 2 - 40
            );
            try {
                var resp = await API._fetch(
                    '/beakbroodnest/api/canvases/' + this.canvasId + '/standalone-entries',
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            schema_code: schemaCode || 'freetext',
                            raw_text: '',
                            field_values: {},
                            pos_x: center.x,
                            pos_y: center.y,
                        }),
                    }
                );
                if (resp && !resp.error) {
                    this.standaloneEntries.push(resp);
                    // 自動開 modal 編輯
                    this.editStandaloneEntry(resp);
                }
            } catch (e) {
                this.showToast('獨立 entry 建立失敗：' + (e.message || e), 'error');
            }
        },

        // ---- 視覺樣式 ----
        getStandaloneEntryStyle(cse) {
            return 'left:' + cse.pos_x + 'px;'
                 + 'top:' + cse.pos_y + 'px;'
                 + 'width:' + (cse.width || 280) + 'px;'
                 + 'z-index:' + (cse.z_index || 1) + ';';
        },

        getStandaloneEntryClass(cse) {
            var code = (cse.entry && cse.entry.schema_code) || 'freetext';
            return 'se-block se-readonly se-' + code + ' wb-standalone-entry';
        },

        getStandaloneEntryLabel(cse) {
            var e = cse.entry || {};
            // 優先 summary，其次 raw_text 截斷
            if (e.summary) return e.summary;
            var raw = (e.raw_text || '').trim();
            if (raw) return raw.length > 60 ? raw.slice(0, 60) + '…' : raw;
            return '(空白)';
        },

        // ---- 拖拉移動 ----
        onStandaloneEntryMouseDown(e, cse) {
            if (e.button !== 0) return;
            if (this.isSnapshot) return;
            if (e.target.closest('.wb-se-action')) return;
            e.stopPropagation();
            this.dragStandaloneEntry = cse;
            this.seDragStartX = e.clientX;
            this.seDragStartY = e.clientY;
            this.seDragStartPos = { x: cse.pos_x, y: cse.pos_y };
        },

        onStandaloneEntryMouseMove(e) {
            if (!this.dragStandaloneEntry) return false;
            var dx = (e.clientX - this.seDragStartX) / this.zoom;
            var dy = (e.clientY - this.seDragStartY) / this.zoom;
            this.dragStandaloneEntry.pos_x = this.seDragStartPos.x + dx;
            this.dragStandaloneEntry.pos_y = this.seDragStartPos.y + dy;
            return true;
        },

        async onStandaloneEntryMouseUp() {
            if (!this.dragStandaloneEntry) return false;
            var cse = this.dragStandaloneEntry;
            this.dragStandaloneEntry = null;
            // snap10
            if (typeof this.snap10 === 'function') {
                cse.pos_x = this.snap10(cse.pos_x);
                cse.pos_y = this.snap10(cse.pos_y);
            }
            try {
                await API._fetch(
                    '/beakbroodnest/api/canvas-standalone-entries/' + cse.id,
                    {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ pos_x: cse.pos_x, pos_y: cse.pos_y }),
                    }
                );
            } catch (e) {
                this.showToast('位置儲存失敗：' + (e.message || e), 'error');
            }
            return true;
        },

        // ---- 編輯（開 entry-modal） ----
        async editStandaloneEntry(cse) {
            if (this.isSnapshot) { this.showToast('歸檔白板為唯讀快照', 'warn'); return; }
            var e = cse.entry || {};
            // 用全域 openEntryModal（card-editor.bundle 內 export，由 window 暴露）
            if (typeof window.openEntryModal !== 'function') {
                this.showToast('entry modal 未就緒', 'error');
                return;
            }
            var schema = (this.entrySchemas || []).find(function (s) { return s.code === e.schema_code; });
            var self = this;
            window.openEntryModal({
                schemaCode: e.schema_code,
                schema: schema,
                rawText: e.raw_text || '',
                fieldValues: e.field_values || {},
                mode: 'edit',
                onSave: async function (payload) {
                    try {
                        var resp = await API._fetch(
                            '/beakbroodnest/api/standalone-entries/' + e.id,
                            {
                                method: 'PUT',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    raw_text: payload.rawText || '',
                                    field_values: payload.fieldValues || {},
                                }),
                            }
                        );
                        if (resp && !resp.error) {
                            cse.entry = resp;
                        }
                    } catch (err) {
                        self.showToast('儲存失敗：' + (err.message || err), 'error');
                    }
                },
            });
        },

        // ---- 刪除 ----
        async removeStandaloneEntryFromCanvas(cse) {
            if (this.isSnapshot) return;
            if (!confirm('從白板移除這個 entry？')) return;
            try {
                await API._fetch(
                    '/beakbroodnest/api/canvas-standalone-entries/' + cse.id,
                    { method: 'DELETE' }
                );
                this.standaloneEntries = this.standaloneEntries.filter(function (x) { return x.id !== cse.id; });
            } catch (e) {
                this.showToast('移除失敗：' + (e.message || e), 'error');
            }
        },

        async deleteStandaloneEntry(cse) {
            // 軟刪 entry 本體（同時清掉所有 placement）
            if (this.isSnapshot) return;
            if (!confirm('永久刪除這個 entry？（含所有白板上的放置）')) return;
            try {
                var eid = cse.entry && cse.entry.id;
                if (!eid) return;
                await API._fetch(
                    '/beakbroodnest/api/standalone-entries/' + eid,
                    { method: 'DELETE' }
                );
                this.standaloneEntries = this.standaloneEntries.filter(function (x) {
                    return !x.entry || x.entry.id !== eid;
                });
            } catch (e) {
                this.showToast('刪除失敗：' + (e.message || e), 'error');
            }
        },
    };
}
