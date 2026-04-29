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
            if (this.editingTextboxId === tb.id) return;
            this.editingTextboxId = tb.id;
            // textarea 由 <template x-if> 動態產生, x-init 內已自動 focus + 將 caret 置於文末
        },

        finishTextboxEdit(tb) {
            this.editingTextboxId = null;
            this.flushTextboxContentSave(tb);
        },

        // ---- 渲染（檢視模式）：把純文字依縮排與 marker 解析為巢狀 list ----
        // marker:
        //   '\d+\.' / '[a-z]+\.'   → 編號 (ol, CSS 自動 1./a./i.)
        //   '*' / '•' / '◦' / '▪'  → 清單 (ul, CSS 自動 disc/circle/square)
        // 縮排: 每 2 spaces = 1 層, 不限層數
        renderTextboxContent(text) {
            if (text === null || text === undefined || text === '') return '';
            var lines = String(text).split('\n');
            var out = [];
            var stack = []; // [{ tag: 'ol'|'ul', liOpen }]
            function escHtml(s) {
                return s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
            }
            function closeTopLi() {
                if (stack.length && stack[stack.length - 1].liOpen) {
                    out.push('</li>');
                    stack[stack.length - 1].liOpen = false;
                }
            }
            function popList() {
                closeTopLi();
                if (stack.length) {
                    var top = stack.pop();
                    out.push('</' + top.tag + '>');
                }
            }
            function openList(tag) {
                out.push('<' + tag + '>');
                stack.push({ tag: tag, liOpen: false });
            }
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i];
                var im = /^( *)(.*)$/.exec(line);
                var indent = Math.floor(im[1].length / 2);
                var rest = im[2];
                var content = null, tag = null, mm;
                if ((mm = /^(?:\d+\.|[a-z]+\.) +(.*)$/i.exec(rest)))    { tag = 'ol'; content = mm[1]; }
                else if ((mm = /^[*•◦▪] +(.*)$/.exec(rest))) { tag = 'ul'; content = mm[1]; }
                if (tag) {
                    while (stack.length > indent + 1) popList();
                    if (stack.length === indent + 1 && stack[stack.length - 1].tag !== tag) popList();
                    while (stack.length < indent + 1) openList(tag);
                    closeTopLi();
                    out.push('<li>' + escHtml(content));
                    stack[stack.length - 1].liOpen = true;
                } else {
                    while (stack.length) popList();
                    if (rest.trim() === '') out.push('<br>');
                    else out.push('<p>' + escHtml(rest) + '</p>');
                }
            }
            while (stack.length) popList();
            return out.join('');
        },

        // ---- marker 工具 ----
        // 編號 (ol):  level 0 = 1./2./3., level 1 = a./b./c., level 2+ = i./ii./iii.
        // 清單 (ul):  level 0 = '• ', level 1 = '◦ ', level 2+ = '▪ '
        _wbMarkerForLevel(level, n) {
            if (level <= 0) return String(n) + '. ';
            if (level === 1) return this._wbToAlpha(n) + '. ';
            return this._wbToRoman(n) + '. ';
        },
        _wbBulletForLevel(level) {
            if (level <= 0) return '• ';
            if (level === 1) return '◦ ';
            return '▪ ';
        },
        _wbToAlpha(num) {
            if (num <= 0) return 'a';
            var s = '';
            while (num > 0) {
                var rem = (num - 1) % 26;
                s = String.fromCharCode(97 + rem) + s;
                num = Math.floor((num - 1) / 26);
            }
            return s;
        },
        _wbFromAlpha(str) {
            if (!str) return 0;
            var n = 0; var s = str.toLowerCase();
            for (var i = 0; i < s.length; i++) n = n * 26 + (s.charCodeAt(i) - 96);
            return n;
        },
        _wbToRoman(num) {
            if (num <= 0) return 'i';
            var v = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1];
            var s = ['m', 'cm', 'd', 'cd', 'c', 'xc', 'l', 'xl', 'x', 'ix', 'v', 'iv', 'i'];
            var r = '';
            for (var i = 0; i < v.length; i++) {
                while (num >= v[i]) { r += s[i]; num -= v[i]; }
            }
            return r;
        },
        _wbFromRoman(str) {
            if (!str) return 0;
            var map = { i: 1, v: 5, x: 10, l: 50, c: 100, d: 500, m: 1000 };
            var s = str.toLowerCase(); var n = 0;
            for (var i = 0; i < s.length; i++) {
                var v = map[s[i]]; if (!v) return 0;
                var nx = i + 1 < s.length ? map[s[i + 1]] : 0;
                if (nx > v) n -= v; else n += v;
            }
            return n;
        },
        _wbParseMarker(markerWithDot) {
            // 'i' / 'ii' / 'a' / '12' (不含尾巴的 '. ')
            var t = markerWithDot.trim().replace(/\.$/, '');
            if (/^\d+$/.test(t)) return { type: 'dec', n: parseInt(t, 10) };
            // roman 字母純字（i,v,x,l,c,d,m）→ 視作 roman, 但單一 'i'/'v'/'x' 也可能是 alpha
            // 區分靠 level 判斷, 這裡只回傳 alpha + roman 兩種解
            return {
                type: 'alpha-or-roman',
                alpha: this._wbFromAlpha(t),
                roman: this._wbFromRoman(t),
                raw: t,
            };
        },
        _wbIncrementMarker(level, current) {
            // current 為含尾巴 '. ' 的 marker (例如 '1. ' 'a. ' 'ii. ')
            var p = this._wbParseMarker(current);
            var n;
            if (level <= 0) n = (p.type === 'dec' ? p.n : 1);
            else if (level === 1) n = (p.type === 'alpha-or-roman' ? p.alpha : 1);
            else n = (p.type === 'alpha-or-roman' ? p.roman : 1);
            if (!n || n <= 0) n = 1;
            return this._wbMarkerForLevel(level, n + 1);
        },
        // 從 lineStart 往前找「同 level」的最近先行 sibling 的 marker
        // 跳過更深 (子節點) 的行；遇到更淺 (上層) 或非 list 普通行時停止
        _wbFindSiblingMarker(value, lineStart, level) {
            var pos = lineStart - 1;
            while (pos >= 0) {
                var ls = value.lastIndexOf('\n', pos - 1) + 1;
                var line = value.slice(ls, pos + 1).replace(/\n$/, '');
                var im = /^( *)/.exec(line);
                var lvl = Math.floor(im[1].length / 2);
                if (lvl < level) return null;
                if (lvl === level) {
                    var mm = /^ *((?:\d+\.|[a-z]+\.) )/i.exec(line);
                    if (mm) return mm[1];
                    return null;
                }
                pos = ls - 1;
            }
            return null;
        },

        // ---- textarea 熱鍵 ----
        // Tab / Shift+Tab : 縮排 +/- 2 spaces (不限層數)
        // Ctrl+Shift+7    : 切換 編號 (1./a./i.)
        // Ctrl+Shift+6    : 切換 清單 (* )
        // Enter           : 在 list 行延續 marker；空 list 行則脫離 list
        onTextboxKeydown(e, tb) {
            var ta = e.target;
            if ((e.ctrlKey || e.metaKey) && e.shiftKey && !e.altKey) {
                if (e.code === 'Digit7') { e.preventDefault(); this._textboxToggleList(ta, tb, 'ol'); return; }
                if (e.code === 'Digit6') { e.preventDefault(); this._textboxToggleList(ta, tb, 'ul'); return; }
            }
            if (e.key === 'Tab' && !e.ctrlKey && !e.altKey && !e.metaKey) {
                e.preventDefault();
                e.stopPropagation();
                if (e.shiftKey) this._textboxOutdent(ta, tb);
                else this._textboxIndent(ta, tb);
                return;
            }
            if (e.key === 'Enter' && !e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey) {
                if (this._textboxOnEnter(ta, tb)) e.preventDefault();
                return;
            }
            // Page Up/Down: 自己處理避免 browser native scrollIntoView 把整個白板捲走
            if ((e.key === 'PageUp' || e.key === 'PageDown') && !e.ctrlKey && !e.altKey && !e.metaKey) {
                e.preventDefault();
                e.stopPropagation();
                this._textboxPageMove(ta, e.key === 'PageDown');
                return;
            }
        },

        _textboxPageMove(ta, down) {
            var lh = parseFloat(window.getComputedStyle(ta).lineHeight);
            if (!lh || isNaN(lh)) lh = 19;
            var linesPerPage = Math.max(1, Math.floor(ta.clientHeight / lh) - 1);
            var v = ta.value;
            var caret = ta.selectionStart;
            var before = v.substring(0, caret).split('\n');
            var curLineIdx = before.length - 1;
            var curCol = before[curLineIdx].length;
            var allLines = v.split('\n');
            var newLineIdx = down
                ? Math.min(allLines.length - 1, curLineIdx + linesPerPage)
                : Math.max(0, curLineIdx - linesPerPage);
            var newCaret = 0;
            for (var i = 0; i < newLineIdx; i++) newCaret += allLines[i].length + 1;
            newCaret += Math.min(curCol, allLines[newLineIdx].length);
            ta.selectionStart = ta.selectionEnd = newCaret;
            ta.scrollTop += (newLineIdx - curLineIdx) * lh;
            this._scrollTextareaCaretIntoView(ta);
        },

        _textboxLineBounds(v, pos) {
            var ls = v.lastIndexOf('\n', pos - 1) + 1;
            var le = v.indexOf('\n', pos);
            if (le < 0) le = v.length;
            return { start: ls, end: le };
        },

        _textboxSelectionBounds(ta) {
            var v = ta.value;
            var s = ta.selectionStart, e = ta.selectionEnd;
            var ls = v.lastIndexOf('\n', s - 1) + 1;
            var le = v.indexOf('\n', e);
            if (le < 0) le = v.length;
            return { value: v, s: s, e: e, lineStart: ls, lineEnd: le };
        },

        _textboxApply(ta, tb, newValue, newSelStart, newSelEnd) {
            ta.value = newValue;
            ta.selectionStart = newSelStart;
            ta.selectionEnd = newSelEnd;
            tb.content = newValue;
            this.onTextboxContentInput(tb, newValue);
            this._scrollTextareaCaretIntoView(ta);
        },

        // textarea programmatic 改值不觸發 native auto-scroll, 手動把 caret 卷到可見區
        _scrollTextareaCaretIntoView(ta) {
            try {
                var v = ta.value;
                var lineCount = v.substring(0, ta.selectionStart).split('\n').length;
                var lh = parseFloat(window.getComputedStyle(ta).lineHeight);
                if (!lh || isNaN(lh)) lh = 19;
                var caretY = lineCount * lh;
                var visibleBottom = ta.scrollTop + ta.clientHeight;
                var pad = lh * 0.5;
                if (caretY > visibleBottom - pad) {
                    ta.scrollTop = caretY - ta.clientHeight + lh + pad;
                } else if (caretY < ta.scrollTop + lh) {
                    ta.scrollTop = Math.max(0, caretY - lh - pad);
                }
            } catch (_) { /* ignore */ }
        },

        // 計算「目標 level 的編號 marker」(處理 multi-line 連續編號 + 段外先行 sibling 銜接)
        _textboxNextOlMarker(value, sectionStart, level, counterMap) {
            if (counterMap[level]) {
                counterMap[level] += 1;
                return this._wbMarkerForLevel(level, counterMap[level]);
            }
            var sib = this._wbFindSiblingMarker(value, sectionStart, level);
            var n0;
            if (sib) {
                var marker = this._wbIncrementMarker(level, sib);
                var p = this._wbParseMarker(marker);
                if (level <= 0) n0 = (p.type === 'dec' ? p.n : 1);
                else if (level === 1) n0 = (p.alpha || 1);
                else n0 = (p.roman || 1);
                counterMap[level] = n0;
                return marker;
            }
            counterMap[level] = 1;
            return this._wbMarkerForLevel(level, 1);
        },

        // 對 list 行做 indent: 多 2 spaces + 換 marker 為新層級對應符號
        // 對非 list 行做 indent: 只多 2 spaces
        _textboxIndent(ta, tb) {
            var self = this;
            var b = this._textboxSelectionBounds(ta);
            var section = b.value.slice(b.lineStart, b.lineEnd);
            var lines = section.split('\n');
            var levelCounter = {};
            var newLines = lines.map(function(l) {
                var lead = /^( *)/.exec(l)[1];
                var newLevel = Math.floor(lead.length / 2) + 1;
                var newLead = '  ' + lead;
                var rest = l.slice(lead.length);
                var mmOl = /^((?:\d+\.|[a-z]+\.) )(.*)$/i.exec(rest);
                var mmUl = /^([*•◦▪] )(.*)$/.exec(rest);
                if (mmOl) {
                    var marker = self._textboxNextOlMarker(b.value, b.lineStart, newLevel, levelCounter);
                    return newLead + marker + mmOl[2];
                }
                if (mmUl) {
                    return newLead + self._wbBulletForLevel(newLevel) + mmUl[2];
                }
                return '  ' + l;
            });
            var newSection = newLines.join('\n');
            var firstDiff = newLines[0].length - lines[0].length;
            var totalDiff = newSection.length - section.length;
            var newValue = b.value.slice(0, b.lineStart) + newSection + b.value.slice(b.lineEnd);
            this._textboxApply(ta, tb,
                newValue,
                Math.max(b.lineStart, b.s + firstDiff),
                b.e + totalDiff);
        },

        // outdent: 移除 2 spaces + 若是 list 行則換為新層級對應 marker
        _textboxOutdent(ta, tb) {
            var self = this;
            var b = this._textboxSelectionBounds(ta);
            var section = b.value.slice(b.lineStart, b.lineEnd);
            var lines = section.split('\n');
            var levelCounter = {};
            var newLines = lines.map(function(l) {
                var lead = /^( *)/.exec(l)[1];
                if (lead.length === 0) return l;
                var newLevel = Math.max(0, Math.floor(lead.length / 2) - 1);
                var rmCount = Math.min(2, lead.length);
                var newLead = lead.slice(rmCount);
                var rest = l.slice(lead.length);
                var mmOl = /^((?:\d+\.|[a-z]+\.) )(.*)$/i.exec(rest);
                var mmUl = /^([*•◦▪] )(.*)$/.exec(rest);
                if (mmOl) {
                    var marker = self._textboxNextOlMarker(b.value, b.lineStart, newLevel, levelCounter);
                    return newLead + marker + mmOl[2];
                }
                if (mmUl) {
                    return newLead + self._wbBulletForLevel(newLevel) + mmUl[2];
                }
                return newLead + rest;
            });
            var newSection = newLines.join('\n');
            var firstDiff = newLines[0].length - lines[0].length;
            var totalDiff = newSection.length - section.length;
            var newValue = b.value.slice(0, b.lineStart) + newSection + b.value.slice(b.lineEnd);
            this._textboxApply(ta, tb,
                newValue,
                Math.max(b.lineStart, b.s + firstDiff),
                Math.max(b.lineStart, b.e + totalDiff));
        },

        _textboxOnEnter(ta, tb) {
            var v = ta.value;
            var s = ta.selectionStart, e = ta.selectionEnd;
            if (s !== e) return false; // 有選取時讓預設行為處理
            var lb = this._textboxLineBounds(v, s);
            var line = v.slice(lb.start, lb.end);
            var m = /^( *)((?:\d+\.|[a-z]+\.) |[*•◦▪] )(.*)$/i.exec(line);
            if (!m) return false;
            var indent = m[1], marker = m[2], content = m[3];
            var level = Math.floor(indent.length / 2);
            if (content.trim() === '') {
                // 空 list 行: 移除 marker 與 indent (脫離 list)
                var newValue = v.slice(0, lb.start) + v.slice(lb.end);
                this._textboxApply(ta, tb, newValue, lb.start, lb.start);
                return true;
            }
            // 延續 list
            var nextMarker;
            if (/^[*•◦▪] $/.test(marker)) nextMarker = this._wbBulletForLevel(level);
            else nextMarker = this._wbIncrementMarker(level, marker);
            var insert = '\n' + indent + nextMarker;
            var newValue = v.slice(0, s) + insert + v.slice(e);
            this._textboxApply(ta, tb, newValue, s + insert.length, s + insert.length);
            return true;
        },

        // type: 'ol' (Ctrl+Shift+7 編號) 或 'ul' (Ctrl+Shift+6 清單)
        // 切換: 套上對應 marker; 若全行已是同類則取消
        _textboxToggleList(ta, tb, type) {
            var self = this;
            var b = this._textboxSelectionBounds(ta);
            var section = b.value.slice(b.lineStart, b.lineEnd);
            var lines = section.split('\n');
            var allHave = lines.length > 0 && lines.every(function(l) {
                if (type === 'ol') return /^( *)(\d+\.|[a-z]+\.) /i.test(l);
                return /^( *)[*•◦▪] /.test(l);
            });
            var levelCounter = {};
            var newLines = lines.map(function(l) {
                var lead = /^( *)/.exec(l)[1];
                var level = Math.floor(lead.length / 2);
                var rest = l.slice(lead.length);
                // 移除任何既有 list marker
                var mm = /^((?:\d+\.|[a-z]+\.) |[*•◦▪] )(.*)$/i.exec(rest);
                var body = mm ? mm[2] : rest;
                if (allHave) return lead + body;
                if (type === 'ul') return lead + self._wbBulletForLevel(level) + body;
                // ol: 依 level 給 1./a./i.
                var marker = self._textboxNextOlMarker(b.value, b.lineStart, level, levelCounter);
                return lead + marker + body;
            });
            var newSection = newLines.join('\n');
            var firstDiff = newLines[0].length - lines[0].length;
            var totalDiff = newSection.length - section.length;
            var newValue = b.value.slice(0, b.lineStart) + newSection + b.value.slice(b.lineEnd);
            this._textboxApply(ta, tb,
                newValue,
                Math.max(b.lineStart, b.s + firstDiff),
                Math.max(b.lineStart, b.e + totalDiff));
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
