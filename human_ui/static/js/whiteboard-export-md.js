/**
 * 白板 Mixin: 卡片匯出為 Markdown (.md)
 *
 * 從 atom.content_json (Tiptap ProseMirror doc) 重新序列化成 GFM Markdown，
 * 不直接吐 atom.content (Tiptap 內建 md 序列化器會丟失 table/structuredEntry/pdfReader)。
 *
 * 對應規格：
 *   - heading/paragraph/list/codeBlock/blockquote/hr/hardBreak: 標準 md
 *   - table*: GFM pipe 表格，cell 內 hardBreak 轉 <br>
 *   - image: ![alt](filename)，server 路徑(/beakbroodnest/files/<token>) 改成檔名，token 寫入 frontmatter assets
 *   - pdfReader/pdfThumbnail: 文字 fallback「[PDF: filename (N頁)](filename)」+ assets
 *   - structuredEntry: 「[entry:{schemaCode}#{entryId}] {field=val ...} content」+ frontmatter entries
 *   - 未知節點: <!-- unsupported: {type} --> 並把節點 JSON 收進 frontmatter unsupported_nodes
 *
 * Marks: bold/italic/code/strike/underline(HTML)/link/highlight(==)/textStyle(忽略)
 */
function whiteboardExportMdMixin() {
    return {
        async exportCardMarkdown(ca) {
            try {
                if (!ca || !ca.atom) {
                    this.showToast('卡片資料不完整', 'error');
                    return;
                }
                // 白板載入時為效能只回傳 content_preview，content_json 沒帶；
                // 匯出前先拉完整原子（含 content_json + tags）。
                var atomId = ca.atom_id || ca.atom.id;
                var fullAtom = await API.getAtom(atomId);
                if (!fullAtom) {
                    this.showToast('讀取卡片失敗', 'error');
                    return;
                }
                var built = this._buildAtomMarkdown(fullAtom);
                var safeTitle = (fullAtom.title || 'untitled').replace(/[\\/:*?"<>|]+/g, '_').trim() || 'untitled';
                var filename = safeTitle + '.md';
                var blob = new Blob([built], { type: 'text/markdown;charset=utf-8' });
                var url = URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.href = url; a.download = filename; a.click();
                setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
                this.showToast('已匯出 ' + filename, 'success', 2000);
            } catch (err) {
                console.error('exportCardMarkdown failed:', err);
                this.showToast('匯出失敗: ' + (err.message || err), 'error');
            }
        },

        _buildAtomMarkdown(atom) {
            var ctx = { lossyEntry: 0, lossyUnsupported: 0, lossyMark: 0 };
            var body;
            if (atom.content_json && typeof atom.content_json === 'object') {
                body = this._pmDocToMd(atom.content_json, ctx).trimEnd();
            } else {
                // 沒有 content_json，退回 atom.content（可能仍是不完整的 md）
                body = (atom.content || '').trimEnd();
            }
            // 跨系統交換用途，不寫 frontmatter。
            // 只有當實際發生資料流失（entry 元資料 / 未知節點 / highlight 等視覺 mark），才在開頭加一行提示。
            var notice = '';
            if (ctx.lossyEntry || ctx.lossyUnsupported || ctx.lossyMark) {
                notice = '> [!] 因 BeakBroodNest 格式比 Markdown 更豐富，部份資料於匯出時遺失\n\n';
            }
            return notice + body + '\n';
        },

        _pmDocToMd(doc, ctx) {
            if (!doc || !doc.content) return '';
            var out = [];
            for (var i = 0; i < doc.content.length; i++) {
                out.push(this._pmBlockToMd(doc.content[i], ctx, ''));
            }
            return out.join('').replace(/\n{3,}/g, '\n\n');
        },

        _pmBlockToMd(node, ctx, indent) {
            if (!node) return '';
            var t = node.type;
            switch (t) {
                case 'paragraph': {
                    var inline = this._pmInlineToMd(node.content || [], ctx);
                    return (indent ? this._indentLines(inline, indent) : inline) + '\n\n';
                }
                case 'heading': {
                    var lv = (node.attrs && node.attrs.level) || 1;
                    var s = '';
                    for (var k = 0; k < lv; k++) s += '#';
                    return s + ' ' + this._pmInlineToMd(node.content || [], ctx) + '\n\n';
                }
                case 'bulletList':
                    return this._pmListToMd(node, ctx, indent, false);
                case 'orderedList':
                    return this._pmListToMd(node, ctx, indent, true);
                case 'taskList':
                    return this._pmTaskListToMd(node, ctx, indent);
                case 'codeBlock': {
                    var lang = (node.attrs && node.attrs.language) || '';
                    var code = (node.content || []).map(function(n) { return n.text || ''; }).join('');
                    return '```' + lang + '\n' + code + '\n```\n\n';
                }
                case 'blockquote': {
                    var inner = '';
                    (node.content || []).forEach(function(c) { inner += this._pmBlockToMd(c, ctx, ''); }, this);
                    var quoted = inner.trimEnd().split('\n').map(function(l) { return l.length ? '> ' + l : '>'; }).join('\n');
                    return quoted + '\n\n';
                }
                case 'horizontalRule':
                    return '---\n\n';
                case 'table':
                    return this._pmTableToMd(node, ctx) + '\n\n';
                case 'structuredEntry':
                    return this._pmEntryBlockToMd(node, ctx) + '\n\n';
                case 'pdfReader':
                case 'pdfThumbnail':
                    return this._pmPdfToMd(node, ctx) + '\n\n';
                default:
                    ctx.lossyUnsupported++;
                    return '<!-- unsupported: ' + t + ' -->\n\n';
            }
        },

        _pmListToMd(node, ctx, indent, ordered) {
            var items = node.content || [];
            var out = [];
            for (var i = 0; i < items.length; i++) {
                var marker = ordered ? (i + 1) + '. ' : '- ';
                var item = items[i];
                var first = '';
                var rest = [];
                (item.content || []).forEach(function(c, idx) {
                    var rendered = this._pmBlockToMd(c, ctx, '');
                    if (idx === 0) first = rendered.trimEnd();
                    else rest.push(rendered.trimEnd());
                }, this);
                var firstLines = first.split('\n');
                var head = indent + marker + (firstLines[0] || '');
                var subIndent = indent + '  ';
                var tail = firstLines.slice(1).map(function(l) { return subIndent + l; });
                out.push(head);
                if (tail.length) out.push(tail.join('\n'));
                if (rest.length) {
                    out.push('');
                    out.push(rest.map(function(b) {
                        return b.split('\n').map(function(l) { return l.length ? subIndent + l : ''; }).join('\n');
                    }).join('\n\n'));
                }
            }
            return out.join('\n') + '\n\n';
        },

        _pmTaskListToMd(node, ctx, indent) {
            var items = node.content || [];
            var out = [];
            for (var i = 0; i < items.length; i++) {
                var item = items[i];
                var checked = !!(item.attrs && item.attrs.checked);
                var marker = '- [' + (checked ? 'x' : ' ') + '] ';
                var bodyParts = [];
                (item.content || []).forEach(function(c) {
                    bodyParts.push(this._pmBlockToMd(c, ctx, '').trimEnd());
                }, this);
                var firstLines = (bodyParts[0] || '').split('\n');
                out.push(indent + marker + (firstLines[0] || ''));
                var subIndent = indent + '  ';
                if (firstLines.length > 1) {
                    out.push(firstLines.slice(1).map(function(l) { return subIndent + l; }).join('\n'));
                }
                for (var j = 1; j < bodyParts.length; j++) {
                    out.push(bodyParts[j].split('\n').map(function(l) { return l.length ? subIndent + l : ''; }).join('\n'));
                }
            }
            return out.join('\n') + '\n\n';
        },

        _pmTableToMd(node, ctx) {
            var rows = (node.content || []).filter(function(r) { return r && r.type === 'tableRow'; });
            if (!rows.length) return '';
            var grid = [];
            var hasHeaderRow = false;
            for (var i = 0; i < rows.length; i++) {
                var cells = (rows[i].content || []).filter(function(c) { return c && (c.type === 'tableCell' || c.type === 'tableHeader'); });
                if (i === 0 && cells.length && cells.every(function(c) { return c.type === 'tableHeader'; })) hasHeaderRow = true;
                var line = [];
                for (var j = 0; j < cells.length; j++) {
                    var cellMd = this._pmCellToMd(cells[j], ctx);
                    line.push(cellMd);
                }
                grid.push(line);
            }
            var colCount = 0;
            grid.forEach(function(r) { if (r.length > colCount) colCount = r.length; });
            grid.forEach(function(r) { while (r.length < colCount) r.push(''); });
            var out = [];
            if (hasHeaderRow) {
                out.push('| ' + grid[0].join(' | ') + ' |');
                out.push('|' + new Array(colCount).fill(' --- ').join('|') + '|');
                for (var k = 1; k < grid.length; k++) out.push('| ' + grid[k].join(' | ') + ' |');
            } else {
                // 沒明確 header，造一個空 header 維持 GFM 合法
                out.push('| ' + new Array(colCount).fill(' ').join(' | ') + ' |');
                out.push('|' + new Array(colCount).fill(' --- ').join('|') + '|');
                for (var m = 0; m < grid.length; m++) out.push('| ' + grid[m].join(' | ') + ' |');
            }
            return out.join('\n');
        },

        _pmCellToMd(cell, ctx) {
            var pieces = [];
            (cell.content || []).forEach(function(c) {
                if (c.type === 'paragraph') {
                    pieces.push(this._pmInlineToMd(c.content || [], ctx));
                } else {
                    // 表格 cell 內若有 list/codeBlock 等，降級為純文字並用 <br> 分隔
                    var rendered = this._pmBlockToMd(c, ctx, '').trimEnd();
                    pieces.push(rendered);
                }
            }, this);
            return pieces.join('<br>').replace(/\n+/g, '<br>').replace(/\|/g, '\\|');
        },

        _pmEntryBlockToMd(node, ctx) {
            var attrs = node.attrs || {};
            var fv = attrs.fieldValues || {};
            var schemaCode = attrs.schemaCode || '';
            ctx.lossyEntry++; // entryId/schemaId 等結構元資料不入 md
            var inline = this._pmInlineToMd(node.content || [], ctx).trim();
            // 取 schema 顯示名稱（如「待辦事項」/「行事曆」）放在標題前綴
            var schema = (this.entrySchemas || []).find(function(s) { return s.code === schemaCode; });
            var schemaName = schema ? schema.name : schemaCode;
            var titlePrefix = schemaName ? '[' + schemaName + '] ' : '';
            var lines = [];
            if (inline) lines.push('## ' + titlePrefix + inline);
            else if (schemaName) lines.push('## ' + titlePrefix.trim());

            // 欄位順序：以 schema fields 的 sort_order 為主；schema 找不到則退回插入序
            var fvKeys = Object.keys(fv);
            var keyOrder;
            if (schema && Array.isArray(schema.fields)) {
                var rank = {};
                schema.fields.forEach(function(f, idx) { rank[f.name] = (typeof f.sort_order === 'number') ? f.sort_order : idx; });
                keyOrder = fvKeys.slice().sort(function(a, b) {
                    var ra = (a in rank) ? rank[a] : 9999;
                    var rb = (b in rank) ? rank[b] : 9999;
                    return ra - rb;
                });
            } else {
                keyOrder = fvKeys;
            }

            // 長值（>80 字 或 含換行）沉到清單末端
            var shortKeys = [], longKeys = [];
            keyOrder.forEach(function(k) {
                var v = fv[k];
                var s = (v === null || v === undefined) ? '' : (typeof v === 'string' ? v : JSON.stringify(v));
                if (s.length > 80 || /\n/.test(s)) longKeys.push(k);
                else shortKeys.push(k);
            });
            var ordered = shortKeys.concat(longKeys);

            ordered.forEach(function(k) {
                var v = fv[k];
                var s = (v === null || v === undefined) ? '' : (typeof v === 'string' ? v : JSON.stringify(v));
                lines.push('- ' + k + '=' + JSON.stringify(s));
            });
            return lines.join('\n');
        },

        _pmPdfToMd(node, ctx) {
            var attrs = node.attrs || {};
            var name = attrs.filename || 'document.pdf';
            var pages = attrs.pages || '?';
            var token = attrs.token || attrs.thumbnailToken || null;
            // 用實際可用的檔案路徑（不含 FQDN），保留再拖回白板的相容性
            var path = token ? ('/beakbroodnest/files/' + token) : name;
            return '[PDF: ' + name + ' (' + pages + '頁)](' + path + ')';
        },

        _pmInlineToMd(content, ctx) {
            if (!content || !content.length) return '';
            var self = this;
            var out = '';
            for (var i = 0; i < content.length; i++) {
                var n = content[i];
                if (n.type === 'text') {
                    out += self._applyMarks(n.text || '', n.marks || [], ctx);
                } else if (n.type === 'hardBreak') {
                    out += '  \n';
                } else if (n.type === 'image') {
                    out += self._pmImageToMd(n, ctx);
                } else if (n.type === 'structuredEntry') {
                    // 行內 entry：扁平化成純文字描述（少見情境）
                    ctx.lossyEntry++;
                    out += self._pmInlineToMd(n.content || [], ctx);
                } else {
                    ctx.lossyUnsupported++;
                    out += '<!-- unsupported-inline: ' + n.type + ' -->';
                }
            }
            return out;
        },

        _pmImageToMd(node, ctx) {
            var attrs = node.attrs || {};
            var src = attrs.src || '';
            var alt = attrs.alt || '';
            // 完整路徑保留（不含 FQDN），讓用戶把 .md 拉回白板時仍能解析回相同檔案
            return '![' + alt + '](' + src + ')';
        },

        _applyMarks(text, marks, ctx) {
            if (!text) return '';
            var s = text;
            // 順序：先 inline-code（內部不再轉義），再粗體斜體刪除，再 link
            var hasCode = false, hasBold = false, hasItalic = false, hasStrike = false;
            var linkHref = null;
            for (var i = 0; i < marks.length; i++) {
                var m = marks[i];
                if (m.type === 'code') hasCode = true;
                else if (m.type === 'bold') hasBold = true;
                else if (m.type === 'italic') hasItalic = true;
                else if (m.type === 'strike') hasStrike = true;
                else if (m.type === 'link') linkHref = (m.attrs && m.attrs.href) || null;
                else if (m.type === 'highlight' || m.type === 'underline') {
                    if (ctx) ctx.lossyMark++;
                }
                // textStyle 等其他 mark 忽略（純色不視為資料流失）
            }
            if (hasCode) {
                s = '`' + s.replace(/`/g, '​`​') + '`';
            } else {
                // escape md 特殊字元（最小集合，避免破壞中文）
                s = s.replace(/([\\`*_{}\[\]])/g, '\\$1');
            }
            if (hasBold) s = '**' + s + '**';
            if (hasItalic) s = '*' + s + '*';
            if (hasStrike) s = '~~' + s + '~~';
            if (linkHref) s = '[' + s + '](' + linkHref + ')';
            return s;
        },

        _indentLines(text, indent) {
            return text.split('\n').map(function(l) { return l.length ? indent + l : l; }).join('\n');
        },
    };
}
