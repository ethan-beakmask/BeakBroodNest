/**
 * 白板 Mixin: Drop-to-upload (圖片 + PDF)
 *
 * 拖拉檔案到白板：
 *   - image/* -> 上傳 -> 建 media 原子（content_json 含 image node）
 *   - application/pdf -> 上傳 + 抽文字 -> 建 media 原子（pdfThumbnail node + 內文 paragraphs）
 *   - 其他 -> 友善錯誤訊息
 *
 * 媒體原子的識別：atom.content_type === 'media'，atom_type='F'。
 */
function _dataUrlToBlob(dataUrl) {
    if (!dataUrl) return null;
    var m = /^data:([^;]+);base64,(.+)$/.exec(dataUrl);
    if (!m) return null;
    var mime = m[1];
    var bin = atob(m[2]);
    var len = bin.length;
    var buf = new Uint8Array(len);
    for (var i = 0; i < len; i++) buf[i] = bin.charCodeAt(i);
    return new Blob([buf], { type: mime });
}

function whiteboardMediaMixin() {
    return {

        onCanvasDrop(e) {
            // 過濾：必須是真正的檔案 drop（不是內部卡片拖拉）
            if (!e.dataTransfer || !e.dataTransfer.files || e.dataTransfer.files.length === 0) return;
            e.preventDefault();
            e.stopPropagation();
            if (this.isSnapshot) {
                this.showToast('歸檔白板為唯讀快照', 'warn');
                return;
            }
            var files = Array.from(e.dataTransfer.files);
            var pos = this.screenToCanvas(e.clientX, e.clientY);
            // 樂觀 UI：立刻在 drop 位置放卡片，上傳在背景非同步進行
            for (var i = 0; i < files.length; i++) {
                var f = files[i];
                var dropPos = { x: pos.x + i * 24, y: pos.y + i * 24 };
                if (f.type && f.type.indexOf('image/') === 0) {
                    this._dropImage(f, dropPos);
                } else if (f.type === 'application/pdf' || /\.pdf$/i.test(f.name)) {
                    this._dropPdf(f, dropPos);
                } else if (f.type === 'text/markdown' || /\.md$/i.test(f.name) || /\.markdown$/i.test(f.name)) {
                    this._dropMarkdown(f, dropPos);
                } else {
                    this.showToast('不支援的檔案類型: ' + (f.type || '未知'), 'error');
                }
            }
        },

        // 把新建的 canvas_atom + atom 補成白板期待的形狀並 append 到 atoms
        _appendCanvasAtomLocal(ca, fullAtom) {
            if (!ca) return;
            if (!ca.atom) ca.atom = fullAtom || null;
            if (ca.atom) {
                if (!ca.atom.tags) ca.atom.tags = [];
                if (!ca.atom.entries) ca.atom.entries = [];
            }
            this.atoms.push(ca);
            this.refreshSidebarAtoms();
            var self = this;
            this.$nextTick(function() { self.renderConnections(); });
        },

        _tempLocalAtomId() {
            // 負數本地 id 不會與 DB 序列衝突
            this._localAtomSeq = (this._localAtomSeq || 0) - 1;
            return this._localAtomSeq;
        },

        _replacePlaceholder(localId, ca, fullAtom) {
            var idx = this.atoms.findIndex(function(a) { return a.id === localId; });
            if (idx < 0) return;
            if (!ca.atom) ca.atom = fullAtom || null;
            if (ca.atom) {
                if (!ca.atom.tags) ca.atom.tags = [];
                if (!ca.atom.entries) ca.atom.entries = [];
            }
            this.atoms.splice(idx, 1, ca);
            this.refreshSidebarAtoms();
            var self = this;
            this.$nextTick(function() { self.renderConnections(); });
        },

        _removePlaceholder(localId) {
            var idx = this.atoms.findIndex(function(a) { return a.id === localId; });
            if (idx >= 0) this.atoms.splice(idx, 1);
            var self = this;
            this.$nextTick(function() { self.renderConnections(); });
        },

        onCanvasDragOver(e) {
            if (e.dataTransfer && e.dataTransfer.types && Array.from(e.dataTransfer.types).indexOf('Files') >= 0) {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'copy';
            }
        },

        _dropImage(file, pos) {
            // 建普通卡片 + 顯式 thumbnail_url，走縮圖卡渲染路徑
            // content_json 的 image node 同時標記 attrs.thumbnail=true，編輯時可看到「★」狀態
            var localId = this._tempLocalAtomId();
            var blobUrl = URL.createObjectURL(file);
            var width = 320, height = 240;
            var contentJson = function(src) {
                return {
                    type: 'doc',
                    content: [{
                        type: 'paragraph',
                        content: [{
                            type: 'image',
                            attrs: { src: src, alt: 'image', title: null, width: null, thumbnail: true },
                        }],
                    }],
                };
            };
            var mdContent = function(src, name) {
                return '![' + (name || '') + '](' + src + ')';
            };
            var placeholder = {
                id: localId,
                atom_id: localId,
                canvas_id: this.canvasId,
                pos_x: pos.x, pos_y: pos.y,
                width: width, height: height,
                z_index: 0,
                visual_style: '{}',
                atom: {
                    id: localId,
                    title: file.name,
                    content: mdContent(blobUrl, file.name),
                    content_json: contentJson(blobUrl),
                    content_type: null,
                    thumbnail_url: blobUrl,
                    atom_type: 'F',
                    lifecycle: 'active',
                    owner: 'ethan',
                    source: 'human',
                    tags: [],
                    entries: [],
                    _pending: true,
                },
            };
            this.atoms.push(placeholder);
            var self = this;
            this.$nextTick(function() { self.renderConnections(); });

            // 背景：讀圖片實際比例，更新 placeholder 尺寸（也作為上 canvas 的最終尺寸）
            var dimsReady = new Promise(function(resolve) {
                var probe = new Image();
                probe.onload = function() {
                    var w = probe.naturalWidth, h = probe.naturalHeight;
                    if (!w || !h) { resolve({ w: width, h: height }); return; }
                    var MAX_W = 480, MAX_H = 360, MIN_W = 160;
                    var ratio = Math.min(MAX_W / w, MAX_H / h, 1);
                    if (ratio < 1) { w = Math.round(w * ratio); h = Math.round(h * ratio); }
                    if (w < MIN_W) { var s = MIN_W / w; w = MIN_W; h = Math.round(h * s); }
                    placeholder.width = w; placeholder.height = h;
                    resolve({ w: w, h: h });
                };
                probe.onerror = function() { resolve({ w: width, h: height }); };
                probe.src = blobUrl;
            });

            (async function() {
                try {
                    var dims = await dimsReady;
                    var rec = await API.uploadFile(file, 'image');
                    var atom = await API.createAtom({
                        title: rec.original_filename,
                        content: '',
                        content_json: contentJson(rec.url),
                        atom_type: 'F',
                        source: 'human',
                    });
                    var ca = await API.addAtomToCanvas(self.canvasId, {
                        atom_id: atom.id,
                        pos_x: placeholder.pos_x, pos_y: placeholder.pos_y,
                        width: dims.w, height: dims.h,
                    });
                    self._replacePlaceholder(localId, ca, atom);
                    URL.revokeObjectURL(blobUrl);
                } catch (err) {
                    console.error('drop image upload failed:', err);
                    self.showToast('圖片上傳失敗: ' + (err.message || err), 'error');
                    self._removePlaceholder(localId);
                    URL.revokeObjectURL(blobUrl);
                }
            })();
        },

        _dropPdf(file, pos) {
            // 預先檢查頁數（>50 直接拒絕，不放 placeholder）
            var self = this;
            (async function() {
                var pageCount = null;
                if (window.PdfUtils) {
                    try { pageCount = await window.PdfUtils.getPageCount(file); } catch (e) {}
                }
                if (pageCount != null && pageCount > 500) {
                    self.showToast('PDF 超過 500 頁（' + pageCount + ' 頁），請拆分後再上傳', 'error');
                    return;
                }
                self._dropPdfAfterCheck(file, pos, pageCount);
            })();
        },

        _dropPdfAfterCheck(file, pos, pageCount) {
            // 樂觀 UI：先放 placeholder 卡片，背景上傳 + 渲首頁縮圖完成才替換
            var localId = this._tempLocalAtomId();
            var width = 320, height = 280;
            var placeholder = {
                id: localId,
                atom_id: localId,
                canvas_id: this.canvasId,
                pos_x: pos.x, pos_y: pos.y,
                width: width, height: height,
                z_index: 0,
                visual_style: '{}',
                atom: {
                    id: localId,
                    title: file.name,
                    content: '',
                    content_json: {
                        type: 'doc',
                        content: [{
                            type: 'pdfReader',
                            attrs: {
                                token: '',
                                filename: file.name,
                                pages: pageCount,
                                thumbnailToken: null,
                                viewMode: 'reader',
                            },
                        }],
                    },
                    content_type: 'media',
                    atom_type: 'F',
                    lifecycle: 'active',
                    owner: 'ethan',
                    source: 'human',
                    tags: [],
                    entries: [],
                    _pending: true,
                },
            };
            this.atoms.push(placeholder);
            var self = this;
            this.$nextTick(function() { self.renderConnections(); });

            (async function() {
                try {
                    var rec = await API.uploadFile(file, 'file');

                    // 背景：渲染首頁縮圖（給白板顯示用，不抽 OCR 文字）
                    var thumbnailToken = null;
                    if (window.PdfUtils) {
                        try {
                            var dataUrl = await window.PdfUtils.renderFirstPageThumbnail(file, 480);
                            var blob = _dataUrlToBlob(dataUrl);
                            if (blob) {
                                var thumbName = file.name.replace(/\.pdf$/i, '') + '.thumb.png';
                                var thumbFile = new File([blob], thumbName, { type: 'image/png' });
                                var thumbRec = await API.uploadFile(thumbFile, 'image');
                                thumbnailToken = thumbRec && thumbRec.token;
                            }
                        } catch (e) {}
                    }

                    var content_json = {
                        type: 'doc',
                        content: [{
                            type: 'pdfReader',
                            attrs: {
                                token: rec.token,
                                filename: rec.original_filename,
                                pages: pageCount,
                                thumbnailToken: thumbnailToken,
                                viewMode: 'reader',
                            },
                        }],
                    };

                    var atom = await API.createAtom({
                        title: rec.original_filename,
                        content: '',
                        content_json: content_json,
                        content_type: 'media',
                        atom_type: 'F',
                        source: 'human',
                    });
                    var ca = await API.addAtomToCanvas(self.canvasId, {
                        atom_id: atom.id,
                        pos_x: placeholder.pos_x, pos_y: placeholder.pos_y,
                        width: placeholder.width, height: placeholder.height,
                    });
                    self._replacePlaceholder(localId, ca, atom);
                    // 背景索引：不阻塞 UI，純圖檔抽不到字也安靜吞掉
                    self._backgroundIndexPdf(atom.id, file).catch(function(e) {
                        console.warn('background pdf index failed:', e);
                    });
                } catch (err) {
                    console.error('drop pdf upload failed:', err);
                    self.showToast('PDF 上傳失敗: ' + (err.message || err), 'error');
                    self._removePlaceholder(localId);
                }
            })();
        },

        // 拖拉 PDF 後在背景抽文字寫入 atom.content，讓 note_search 找得到
        // 並讓白板卡片底下的內文摘要區即時顯示
        async _backgroundIndexPdf(atomId, file) {
            if (!window.PdfUtils) return;
            var text;
            try {
                text = await window.PdfUtils.extractAllText(file);
            } catch (e) { return; }
            if (!text || !text.trim()) return;
            var resp = await API.updateAtom(atomId, { content: text });
            // 觸發 reactive：用 splice 重建 ca 物件
            var idx = this.atoms.findIndex(function(a) { return a.atom_id === atomId; });
            if (idx >= 0) {
                var newAtom = Object.assign({}, this.atoms[idx].atom, {
                    content: text,
                    updated_at: (resp && resp.updated_at) || this.atoms[idx].atom.updated_at,
                });
                var newCa = Object.assign({}, this.atoms[idx], { atom: newAtom });
                this.atoms.splice(idx, 1, newCa);
            }
            // 若該卡片正開在編輯器中，同步更新讓 PDF 內文 panel 立即出現
            var ed = (this.openEditors || []).find(function(e) { return e.atomId === atomId; });
            if (ed) {
                ed._content = text;
                if (resp && resp.updated_at) ed._knownServerTs = resp.updated_at;
            }
        },

        // ============================================
        // 媒體卡片偵測（給白板渲染用）
        // ============================================

        isMediaCard(ca) {
            return !!(ca && ca.atom && ca.atom.content_type === 'media');
        },

        // 在 content_json 內找第一個 pdfReader/pdfThumbnail node（不假設是 first child）
        _findPdfNodeInCa(ca) {
            if (!this.isMediaCard(ca)) return null;
            var cj = ca.atom.content_json;
            if (!cj || !cj.content) return null;
            for (var i = 0; i < cj.content.length; i++) {
                var n = cj.content[i];
                if (n && (n.type === 'pdfReader' || n.type === 'pdfThumbnail')) return { node: n, index: i };
            }
            return null;
        },

        // 只剩 PDF 用；圖片改走普通卡片快路徑（_firstRowIsImage + isImageOnlyCard）
        mediaCardKind(ca) {
            return this._findPdfNodeInCa(ca) ? 'pdf' : null;
        },

        mediaCardPdfToken(ca) {
            var hit = this._findPdfNodeInCa(ca);
            return (hit && hit.node.attrs && hit.node.attrs.token) || '';
        },

        // 公開方法：給模板用，回傳該媒體卡的 PDF 縮圖 token（無則 null）
        mediaCardPdfThumbnailToken(ca) {
            var hit = this._findPdfNodeInCa(ca);
            return (hit && hit.node.attrs && hit.node.attrs.thumbnailToken) || null;
        },

        // 是否為 pdfReader 類型（新版本，編輯器內顯閱讀器）
        isPdfReaderCard(ca) {
            var hit = this._findPdfNodeInCa(ca);
            return !!(hit && hit.node.type === 'pdfReader');
        },

        // 取得 viewMode（pdfReader 用：reader / thumbnail）
        pdfReaderViewMode(ca) {
            var hit = this._findPdfNodeInCa(ca);
            if (!hit || hit.node.type !== 'pdfReader') return null;
            return (hit.node.attrs && hit.node.attrs.viewMode) || 'reader';
        },

        // 白板右鍵切換 PDF reader viewMode（reader ↔ thumbnail）
        async togglePdfViewModeOnCanvas(ca) {
            if (!this.isPdfReaderCard(ca)) {
                this.showToast('此卡片無法切換顯示模式', 'warning');
                return;
            }
            // 若該卡片正在編輯器中開啟，提示先關閉避免雙寫衝突
            var openEd = (this.openEditors || []).find(function(e) { return e.atomId === ca.atom_id; });
            if (openEd) {
                this.showToast('請先關閉編輯器再切換顯示模式', 'warning');
                return;
            }
            var hit = this._findPdfNodeInCa(ca);
            if (!hit) return;
            var cj = ca.atom.content_json;
            var current = (hit.node.attrs && hit.node.attrs.viewMode) || 'reader';
            var next = current === 'reader' ? 'thumbnail' : 'reader';
            var newNode = Object.assign({}, hit.node, {
                attrs: Object.assign({}, hit.node.attrs || {}, { viewMode: next }),
            });
            var newContent = cj.content.slice();
            newContent[hit.index] = newNode;
            var newJson = Object.assign({}, cj, { content: newContent });
            try {
                var resp = await API.updateAtom(ca.atom_id, { content_json: newJson });
                ca.atom.content_json = newJson;
                if (resp && resp.updated_at) ca.atom.updated_at = resp.updated_at;
                this.showToast('已切換為「' + (next === 'reader' ? '閱讀器' : '縮圖') + '」', 'success');
            } catch (e) {
                this.showToast('切換失敗：' + (e.message || e), 'error');
            }
        },

        // Fallback：舊 PDF 卡片沒 thumbnailToken 時，client side 即時渲染並背景快取
        async renderPdfThumbFallback(ca, host) {
            if (!host || !window.PdfUtils) return;
            if (host.dataset.rendered === '1') return;
            host.dataset.rendered = '1';
            var token = this.mediaCardPdfToken(ca);
            if (!token) return;
            try {
                var url = '/beakbroodnest/files/' + encodeURIComponent(token);
                var dataUrl = await window.PdfUtils.renderFirstPageThumbnail(url, 480);
                var img = document.createElement('img');
                img.src = dataUrl;
                img.draggable = false;
                host.innerHTML = '';
                host.appendChild(img);
                // 背景上傳並寫回 atom，下次直接走 <img> 路徑
                this._cachePdfThumbnailForCard(ca, dataUrl);
            } catch (e) {
                host.dataset.rendered = '0';
                host.innerHTML = '<div class="wb-media-pdf-error">PDF 縮圖載入失敗</div>';
            }
        },

        // Lazy 快取：舊 PDF 卡片（沒 thumbnailToken）首次客戶端渲染後，
        // 上傳縮圖檔並把 token 寫回 atom.content_json，下次就不必重算
        async _cachePdfThumbnailForCard(ca, dataUrl) {
            if (!ca || !ca.atom || !ca.atom.content_json) return;
            var cj = ca.atom.content_json;
            if (!cj.content || cj.content.length === 0) return;
            var first = cj.content[0];
            if (!first || (first.type !== 'pdfThumbnail' && first.type !== 'pdfReader')) return;
            if (first.attrs && first.attrs.thumbnailToken) return;
            try {
                var blob = _dataUrlToBlob(dataUrl);
                if (!blob) return;
                var fname = (first.attrs && first.attrs.filename) || 'pdf';
                fname = fname.replace(/\.pdf$/i, '') + '.thumb.png';
                var f = new File([blob], fname, { type: 'image/png' });
                var rec = await API.uploadFile(f, 'image');
                if (!rec || !rec.token) return;
                // 改 atom.content_json 寫回 DB
                first.attrs = Object.assign({}, first.attrs, { thumbnailToken: rec.token });
                ca.atom.content_json = cj;
                await API.updateAtom(ca.atom_id, { content_json: cj });
            } catch (e) {
                console.warn('_cachePdfThumbnailForCard failed', e);
            }
        },

        // 拖拉 .md 檔案到白板：檔名（去 .md）成標題、內文 = content
        // content_json 保留 null，由卡片編輯器首次開啟時依 content 重建
        // 上限 256KB（系統安全紅線；商業 md 通常遠小於此）
        _dropMarkdown(file, pos) {
            var MAX_BYTES = 256 * 1024;
            if (file.size > MAX_BYTES) {
                this.showToast('Markdown 檔過大（' + Math.round(file.size / 1024) + 'KB > 256KB 上限）：' + file.name, 'error');
                return;
            }
            var self = this;
            var localId = this._tempLocalAtomId();
            var rawTitle = file.name.replace(/\.(md|markdown)$/i, '').trim() || 'untitled';
            var width = 280, height = 180;
            var placeholder = {
                id: localId,
                atom_id: localId,
                canvas_id: this.canvasId,
                pos_x: pos.x, pos_y: pos.y,
                width: width, height: height,
                z_index: 0,
                visual_style: '{}',
                atom: {
                    id: localId,
                    title: rawTitle,
                    content: '（讀取中...）',
                    content_json: null,
                    content_type: 'markdown',
                    atom_type: 'F',
                    lifecycle: 'active',
                    owner: 'ethan',
                    source: 'human',
                    tags: [],
                    entries: [],
                    _pending: true,
                },
            };
            this.atoms.push(placeholder);
            this.$nextTick(function() { self.renderConnections(); });

            (async function() {
                try {
                    var text = await file.text();
                    if (text.length > MAX_BYTES) {
                        // text.length 是字元數，再保險一次（UTF-8 後可能更大已被前面擋下）
                        self.showToast('Markdown 內容過大：' + file.name, 'error');
                        self._removePlaceholder(localId);
                        return;
                    }
                    var atom = await API.createAtom({
                        title: rawTitle,
                        content: text,
                        content_json: null,
                        content_type: 'markdown',
                        atom_type: 'F',
                        source: 'human',
                    });
                    var ca = await API.addAtomToCanvas(self.canvasId, {
                        atom_id: atom.id,
                        pos_x: placeholder.pos_x, pos_y: placeholder.pos_y,
                        width: width, height: height,
                    });
                    self._replacePlaceholder(localId, ca, atom);
                    self.showToast('已建立卡片：' + rawTitle, 'success', 1500);
                } catch (err) {
                    console.error('drop markdown failed:', err);
                    self.showToast('Markdown 匯入失敗: ' + (err.message || err), 'error');
                    self._removePlaceholder(localId);
                }
            })();
        },
    };
}
