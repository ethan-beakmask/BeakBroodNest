/**
 * BeakCortex StructuredEntry -- Tiptap Node Extension
 *
 * 在 ProseMirror 文件中表示一筆結構化記錄（entry）。
 * 視覺上：[type tag] raw_text   (展開時顯示欄位表單)
 *
 * Attributes:
 *   entryId     - DB id (nullable for unsaved)
 *   schemaCode  - entry schema code ('freetext','task','expense'...)
 *   schemaId    - entry schema id
 *   rawText     - 主要文字內容
 *   fieldValues - JSON object {field_name: value}
 *   collapsed   - 欄位面板是否收合
 */
import { Node, mergeAttributes } from '@tiptap/core'
import { NodeSelection, TextSelection } from '@tiptap/pm/state'
import { openImageAlbumPicker } from './image-album.js'

// 共用：在 selection 路徑上找 structuredEntry 的 depth (回傳 -1 表示不在 entry 內)
function _entryDepth(state) {
    const { $from } = state.selection
    for (let d = $from.depth; d > 0; d--) {
        if ($from.node(d).type.name === 'structuredEntry') return d
    }
    return -1
}

// 把 caret 移到指定 textblock。若該 textblock 是 idcard,直接 focus line1 input,
// 不 dispatch PM transaction--idcard 的 contentDOM 是 hidden,把 PM caret 放進去會
// 讓用戶後續輸入污染 inline content(產生看不見的殘留文字)。
function _moveCaretTo(editor, textblockPos, textblockNode, atEnd) {
    const isIdcard = textblockNode.type.name === 'structuredEntry'
        && (textblockNode.attrs.schemaCode || '') === 'idcard'
    if (isIdcard) {
        queueMicrotask(() => {
            try {
                const dom = editor.view.nodeDOM(textblockPos)
                const inp = dom && dom.querySelector('.se-idcard-line-1')
                if (inp) {
                    inp.focus()
                    try { inp.select() } catch (_) {}
                }
            } catch (_) { /* ignore */ }
        })
        return true
    }
    const inlinePos = atEnd
        ? textblockPos + 1 + textblockNode.content.size
        : textblockPos + 1
    editor.chain().focus().setTextSelection(inlinePos).run()
    return true
}

// 共用：跳到 entry 之後「最近的 textblock」(包含其他 entry,讓並列 entry 可以鄰接導航)
// 沒有後續 textblock 則插一個 paragraph 進入。
function _focusAfterCurrentEntry(editor) {
    const d = _entryDepth(editor.state)
    if (d < 0) return false
    const { $from } = editor.state.selection
    const entryAfter = $from.after(d)
    const doc = editor.state.doc
    let target = null
    let targetNode = null
    doc.nodesBetween(entryAfter, doc.content.size, (n, p) => {
        if (target !== null) return false
        if (n.isTextblock) {
            target = p
            targetNode = n
            return false
        }
        return true
    })
    if (target !== null) {
        return _moveCaretTo(editor, target, targetNode, false)
    }
    // 沒有後續 textblock：在 doc 末插一個 paragraph 並進入
    const tr = editor.state.tr
    const para = editor.state.schema.nodes.paragraph.create()
    tr.insert(entryAfter, para)
    tr.setSelection(TextSelection.create(tr.doc, entryAfter + 1))
    editor.view.dispatch(tr)
    editor.view.focus()
    return true
}

// 共用：跳到 entry 之前「最近的 textblock」尾端(包含其他 entry);無則在 doc 開頭插 paragraph
function _focusBeforeCurrentEntry(editor) {
    const d = _entryDepth(editor.state)
    if (d < 0) return false
    const { $from } = editor.state.selection
    const entryBefore = $from.before(d)
    const doc = editor.state.doc
    let target = null
    let targetNode = null
    doc.nodesBetween(0, entryBefore, (n, p) => {
        if (n.isTextblock) {
            target = p  // 持續覆蓋以取得「最接近 entry 的 textblock」
            targetNode = n
            return false
        }
        return true
    })
    if (target !== null) {
        return _moveCaretTo(editor, target, targetNode, true)
    }
    // 沒有前置 textblock：在 doc 開頭插 paragraph
    const tr = editor.state.tr
    const para = editor.state.schema.nodes.paragraph.create()
    tr.insert(entryBefore, para)
    tr.setSelection(TextSelection.create(tr.doc, entryBefore + 1))
    editor.view.dispatch(tr)
    editor.view.focus()
    return true
}

export const StructuredEntry = Node.create({
    name: 'structuredEntry',
    group: 'block',
    content: 'inline*',
    defining: true,
    draggable: true,

    addAttributes() {
        return {
            entryId: { default: null },
            schemaCode: { default: 'freetext' },
            schemaId: { default: null },
            fieldValues: { default: {} },
            collapsed: { default: true },
        }
    },

    parseHTML() {
        return [{
            tag: 'div[data-entry]',
            getAttrs(dom) {
                return {
                    entryId: dom.getAttribute('data-entry-id') ? parseInt(dom.getAttribute('data-entry-id')) : null,
                    schemaCode: dom.getAttribute('data-schema-code') || 'freetext',
                    schemaId: dom.getAttribute('data-schema-id') ? parseInt(dom.getAttribute('data-schema-id')) : null,
                    fieldValues: JSON.parse(dom.getAttribute('data-field-values') || '{}'),
                    collapsed: dom.getAttribute('data-collapsed') !== 'false',
                }
            },
        }]
    },

    renderHTML({ HTMLAttributes, node }) {
        const attrs = {
            'data-entry': '',
            'data-entry-id': HTMLAttributes.entryId || '',
            'data-schema-code': HTMLAttributes.schemaCode || 'freetext',
            'data-schema-id': HTMLAttributes.schemaId || '',
            'data-field-values': JSON.stringify(HTMLAttributes.fieldValues || {}),
            'data-collapsed': HTMLAttributes.collapsed ? 'true' : 'false',
            'class': 'se-block se-' + (HTMLAttributes.schemaCode || 'freetext'),
        }
        return ['div', mergeAttributes(attrs), 0]
    },

    addNodeView() {
        return ({ node, getPos, editor }) => {
            return new StructuredEntryView(node, getPos, editor)
        }
    },

    addKeyboardShortcuts() {
        // 接管「主旨欄 (contentDOM inline content)」的鍵盤行為:
        //   ArrowUp/ArrowDown -> 跳脫至 entry 前/後的非 entry textblock (主旨欄統一單行)
        //   Enter             -> 跳脫至 entry 後 textblock (不允許在 entry 內 splitBlock)
        //   Shift-Enter       -> 同 Enter (不允許主旨欄產生 hardBreak)
        // 注意:idcard / fieldsPanel 的 input 走自己的 keydown,事件已 stopPropagation,不會走到這裡。
        return {
            ArrowUp: ({ editor }) => {
                if (_entryDepth(editor.state) < 0) return false
                return _focusBeforeCurrentEntry(editor)
            },
            ArrowDown: ({ editor }) => {
                if (_entryDepth(editor.state) < 0) return false
                return _focusAfterCurrentEntry(editor)
            },
            Enter: ({ editor }) => {
                if (_entryDepth(editor.state) < 0) return false
                return _focusAfterCurrentEntry(editor)
            },
            'Shift-Enter': ({ editor }) => {
                if (_entryDepth(editor.state) < 0) return false
                return _focusAfterCurrentEntry(editor)
            },
        }
    },

    addCommands() {
        return {
            insertEntry: (attrs) => ({ commands }) => {
                return commands.insertContent({
                    type: 'structuredEntry',
                    attrs: attrs || {},
                    content: attrs.text ? [{ type: 'text', text: attrs.text }] : [],
                })
            },
            convertToEntry: (schemaCode, schemaId) => ({ state, dispatch }) => {
                // Convert current paragraph to structuredEntry
                const { from, to } = state.selection
                const node = state.doc.nodeAt(from - 1) || state.doc.nodeAt(from)
                if (!node) return false
                if (dispatch) {
                    const text = node.textContent
                    const tr = state.tr
                    const entryNode = state.schema.nodes.structuredEntry.create(
                        { schemaCode, schemaId, fieldValues: {} },
                        text ? [state.schema.text(text)] : []
                    )
                    const start = state.doc.resolve(from).before()
                    const end = state.doc.resolve(from).after()
                    tr.replaceWith(start, end, entryNode)
                    dispatch(tr)
                }
                return true
            },
        }
    },
})


/**
 * NodeView: 自訂渲染邏輯
 */
class StructuredEntryView {
    constructor(node, getPos, editor) {
        this.node = node
        this.getPos = getPos
        this.editor = editor
        this._schemas = window._entrySchemas || []

        // 外層容器
        this.dom = document.createElement('div')
        this.dom.className = 'se-block se-' + (node.attrs.schemaCode || 'freetext')
        this.dom.setAttribute('data-entry', '')

        // 上方 tag 列 -- 全部 contentEditable=false,避免瀏覽器 caret 跑進 deleteBtn(x) / badge / toggleBtn 等 span
        // 這些 span 視覺上看似獨立 UI 控件,實際是 contenteditable region 內的子節點;若不顯式擋住,
        // 瀏覽器在 NodeView contentDOM hidden 時會把 caret fallback 到這些 span,用戶的鍵入會污染 inline content。
        this.tagRow = document.createElement('div')
        this.tagRow.className = 'se-tag-row'
        this.tagRow.contentEditable = 'false'

        // 拖拉把手
        this.dragHandle = document.createElement('span')
        this.dragHandle.className = 'se-drag-handle'
        this.dragHandle.setAttribute('data-drag-handle', '')
        this.dragHandle.textContent = '\u2261'  // ≡
        this.dragHandle.title = '拖拉排序'
        this.dragHandle.contentEditable = 'false'
        this.tagRow.appendChild(this.dragHandle)

        // Type tag badge -- 點擊選取整個 node（供擷取/謄寫）
        this.badge = document.createElement('span')
        this.badge.className = 'se-badge'
        this._updateVisualMode()
        this.badge.addEventListener('click', (e) => {
            e.stopPropagation()
            e.preventDefault()
            this._selectNode()
        })
        this.tagRow.appendChild(this.badge)

        // 展開/收合按鈕（file / idcard 類型沒有額外欄位面板，省略此鈕）
        const isFile = (node.attrs.schemaCode || '') === 'file'
        const isIdCard = (node.attrs.schemaCode || '') === 'idcard'
        if (!isFile && !isIdCard) {
            this.toggleBtn = document.createElement('span')
            this.toggleBtn.className = 'se-toggle-btn'
            this.toggleBtn.textContent = node.attrs.collapsed ? '+' : '-'
            this.toggleBtn.title = node.attrs.collapsed ? '展開欄位' : '收合欄位'
            this.toggleBtn.addEventListener('click', (e) => {
                e.stopPropagation()
                this._toggleCollapsed()
            })
            this.tagRow.appendChild(this.toggleBtn)
        }

        // 刪除 Item 按鈕（freetext 不顯示）
        if ((node.attrs.schemaCode || 'freetext') !== 'freetext') {
            this.deleteBtn = document.createElement('span')
            this.deleteBtn.className = 'se-delete-btn'
            this.deleteBtn.textContent = 'x'
            this.deleteBtn.title = '刪除此 Item'
            this.deleteBtn.addEventListener('click', (e) => {
                e.stopPropagation()
                e.preventDefault()
                this._deleteEntry()
            })
            this.tagRow.appendChild(this.deleteBtn)
        }

        this.dom.appendChild(this.tagRow)

        // file 類型：先加上「檔案連結列」，再放可編輯說明（contentDOM）
        if (isFile) {
            this.fileHeader = document.createElement('div')
            this.fileHeader.className = 'se-file-header'
            this.fileHeader.contentEditable = 'false'
            this._renderFileHeader()
            this.dom.appendChild(this.fileHeader)
        }

        // 內容區（ProseMirror 管理的 inline content）
        this.contentDOM = document.createElement('div')
        this.contentDOM.className = 'se-content'
        if (isFile) {
            this.contentDOM.classList.add('se-file-desc')
            this.contentDOM.setAttribute('data-placeholder', '輸入檔案說明...')
        }
        if (isIdCard) {
            // idcard 不需要可編輯的 inline 內容區，但 ProseMirror 仍要求 contentDOM 存在
            this.contentDOM.style.display = 'none'
        }
        this.dom.appendChild(this.contentDOM)

        // 欄位面板（file 類型不顯示；idcard 走自己的識別證版型）
        // contentEditable=false 同樣避免瀏覽器 caret fallback 進 fieldsPanel 容器(input 自身仍可編輯)
        this.fieldsPanel = document.createElement('div')
        this.fieldsPanel.className = 'se-fields'
        this.fieldsPanel.contentEditable = 'false'
        if (isFile) {
            this.fieldsPanel.style.display = 'none'
        } else if (isIdCard) {
            this.dom.classList.add('se-idcard')
            this.fieldsPanel.style.display = 'block'
            this._renderIdCard()
            this._idcardRenderedOnce = true
            // ;;idcard 剛建立 → 自動 focus line1
            if (window._pendingIdCardFocusEntry) {
                window._pendingIdCardFocusEntry = false
                queueMicrotask(() => {
                    if (this._idcardInputs && this._idcardInputs[0]) {
                        this._idcardInputs[0].focus()
                        try { this._idcardInputs[0].select() } catch (_) {}
                    }
                })
            }
        } else {
            this.fieldsPanel.style.display = node.attrs.collapsed ? 'none' : 'block'
            this._renderFields()
        }
        this.dom.appendChild(this.fieldsPanel)

        // 只允許從漢堡把手拖拉：
        // mousedown 記錄按下位置是否在 handle 內（不改 dom.draggable，避免影響其他功能）；
        // dragstart 時若不是從 handle 起源，preventDefault 取消拖拉。
        this.dom.addEventListener('mousedown', (e) => {
            this._mousedownInHandle = this.dragHandle.contains(e.target)
        }, true)
        this.dom.addEventListener('dragstart', (e) => {
            if (!this._mousedownInHandle) e.preventDefault()
        })

        // idcard contentDOM 是 hidden,當 PM 從外部把 caret 設到此 entry 內(ArrowDown 跨 entry
        // 時的常見路徑),DOM 上看不見 caret。監聽 selectionUpdate,把 focus redirect 到 line1,
        // 並清除可能產生的 inline content 殘留(若 PM 已把字符寫進 hidden contentDOM)。
        if (isIdCard) {
            this._onSelUpdate = () => {
                const pos = this.getPos()
                if (pos === undefined) return
                const sel = editor.state.selection
                const entryEnd = pos + this.node.nodeSize
                if (sel.from < pos || sel.to > entryEnd) return
                if (!this._idcardInputs || this._idcardInputs.length === 0) return
                // 已 focus 在 line1~4 任一就不動;否則 redirect 到 line1
                if (this._idcardInputs.includes(document.activeElement)) return
                queueMicrotask(() => {
                    try { this._idcardInputs[0].focus() } catch (_) {}
                })
            }
            try { editor.on('selectionUpdate', this._onSelUpdate) } catch (_) {}

            // mount 時清除 idcard 殘留的 inline content (主旨欄是 line1 input,不該有 inline)
            this._scheduleIdcardInlineCleanup()
        }
    }

    // idcard 不該有 inline content,若殘留就清掉(可能來自舊版本 PM caret 跑進 contentDOM 時的污染)
    _scheduleIdcardInlineCleanup() {
        if ((this.node.attrs.schemaCode || '') !== 'idcard') return
        if (!this.node.content || this.node.content.size === 0) return
        queueMicrotask(() => {
            try {
                const pos = this.getPos()
                if (pos === undefined) return
                const view = this.editor.view
                const cur = view.state.doc.nodeAt(pos)
                if (!cur || (cur.attrs.schemaCode || '') !== 'idcard') return
                if (cur.content.size === 0) return
                const tr = view.state.tr
                tr.delete(pos + 1, pos + 1 + cur.content.size)
                view.dispatch(tr)
            } catch (_) { /* ignore */ }
        })
    }

    // 收集 entry 內所有可 focus 的 form element + 顯式 tabindex 元素(如 idcard 圖框),
    // 供 Tab 順序導航使用。tabindex="-1" 排除。
    _collectFocusables() {
        const sel = 'input, textarea, select, [tabindex]:not([tabindex="-1"])'
        const list = Array.from(this.dom.querySelectorAll(sel))
        // 過濾不可見/disabled 的元素
        return list.filter(el => {
            if (el.disabled) return false
            // 簡易可見性檢查:offsetParent 為 null 表 hidden(display:none)
            if (el.offsetParent === null && el.tagName !== 'BODY') return false
            return true
        })
    }

    // Tab 導航:在 entry 內 input 順序移動;邊界跳脫到 entry 前/後 textblock。
    _focusNextField(currentEl, reverse) {
        const all = this._collectFocusables()
        const idx = all.indexOf(currentEl)
        if (idx < 0) {
            // 找不到當前元素,fallback 跳脫
            if (reverse) this._focusBeforeEntry()
            else this._focusAfterEntry()
            return
        }
        if (reverse) {
            if (idx === 0) {
                this._focusBeforeEntry()
                return
            }
            const prev = all[idx - 1]
            try { prev.focus(); if (prev.select) prev.select() } catch (_) {}
        } else {
            if (idx === all.length - 1) {
                this._focusAfterEntry()
                return
            }
            const next = all[idx + 1]
            try { next.focus(); if (next.select) next.select() } catch (_) {}
        }
    }

    _renderFileHeader() {
        if (!this.fileHeader) return
        this.fileHeader.innerHTML = ''
        const fv = this.node.attrs.fieldValues || {}
        const token = fv.file_token || ''
        const filename = fv.filename || '(未命名)'
        const sizeBytes = parseInt(fv.size_bytes || '0', 10) || 0
        const mime = fv.mime_type || ''

        const icon = document.createElement('span')
        icon.className = 'se-file-icon'
        icon.textContent = '\u{1F4CE}'  // 📎
        this.fileHeader.appendChild(icon)

        const link = document.createElement('a')
        link.className = 'se-file-link'
        if (token) {
            link.href = '/beakcortex/files/' + encodeURIComponent(token)
            link.target = '_blank'
            link.rel = 'noopener'
            link.title = '點擊下載 ' + filename
        }
        link.textContent = filename
        this.fileHeader.appendChild(link)

        const meta = document.createElement('span')
        meta.className = 'se-file-meta'
        meta.textContent = ' (' + this._humanSize(sizeBytes) + (mime ? ' · ' + mime : '') + ')'
        this.fileHeader.appendChild(meta)
    }

    _humanSize(bytes) {
        if (!bytes) return '0 B'
        const units = ['B', 'KB', 'MB', 'GB']
        let i = 0
        let n = bytes
        while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
        return (i === 0 ? n : n.toFixed(1)) + ' ' + units[i]
    }

    _getSchema() {
        const code = this.node.attrs.schemaCode || 'freetext'
        return this._schemas.find(s => s.code === code)
    }

    _isCalendarMode() {
        if ((this.node.attrs.schemaCode || 'freetext') !== 'task') return false
        const fv = this.node.attrs.fieldValues || {}
        return !!(fv.planned_start && fv.planned_start.trim())
    }

    _updateBadge() {
        const schema = this._getSchema()
        const code = this.node.attrs.schemaCode || 'freetext'
        const isCal = this._isCalendarMode()
        if (schema) {
            this.badge.textContent = isCal ? '行事曆' : schema.name
            this.badge.style.backgroundColor = isCal ? '#f97316' : (schema.color || '#6b7280')
        } else {
            this.badge.textContent = code
            this.badge.style.backgroundColor = '#6b7280'
        }
        this.badge.title = '點擊選取此物件（供擷取/謄寫）'
    }

    _updateVisualMode() {
        const isCal = this._isCalendarMode()
        const code = this.node.attrs.schemaCode || 'freetext'
        if (code === 'task') {
            this.dom.classList.toggle('se-task--calendar', isCal)
        }
        this._updateBadge()
    }

    _selectNode() {
        const pos = this.getPos()
        if (pos === undefined) return
        const tr = this.editor.view.state.tr
        const sel = NodeSelection.create(this.editor.view.state.doc, pos)
        this.editor.view.dispatch(tr.setSelection(sel))
        this.editor.view.focus()
    }

    _toggleCollapsed() {
        const pos = this.getPos()
        if (pos === undefined) return
        const collapsed = !this.node.attrs.collapsed
        this.editor.view.dispatch(
            this.editor.view.state.tr.setNodeMarkup(pos, undefined, {
                ...this.node.attrs,
                collapsed,
            })
        )
    }

    _deleteEntry() {
        const pos = this.getPos()
        if (pos === undefined) return
        // 存入全域回收站供復原
        if (!window._deletedEntries) window._deletedEntries = []
        window._deletedEntries.push({
            node: this.node.toJSON(),
            text: this.node.textContent,
            time: Date.now(),
        })
        // 軟刪除：直接從文件移除此 node
        const tr = this.editor.view.state.tr
        tr.delete(pos, pos + this.node.nodeSize)
        this.editor.view.dispatch(tr)
    }

    _renderFields() {
        this.fieldsPanel.innerHTML = ''
        const schema = this._getSchema()
        if (!schema || !schema.fields || schema.fields.length === 0) return

        const fv = this.node.attrs.fieldValues || {}
        const code = this.node.attrs.schemaCode || 'freetext'

        // task / 行事曆使用固定排版（4 欄 grid + 備註佔整列且 textarea）
        if (code === 'task') {
            this._renderTaskGrid(schema, fv)
            return
        }

        const table = document.createElement('div')
        table.className = 'se-fields-grid'

        // 長文字欄位（備註 / 內容）自成整列 + textarea 三列高
        const LONG_FIELDS = ['note', 'body']
        const sorted = schema.fields.slice().sort((a, b) => a.sort_order - b.sort_order)

        for (const field of sorted) {
            if (LONG_FIELDS.includes(field.name)) continue
            table.appendChild(this._buildFieldCell(field, fv[field.name] || ''))
        }
        for (const field of sorted) {
            if (!LONG_FIELDS.includes(field.name)) continue
            const cell = this._buildFieldCell(field, fv[field.name] || '', { multiline: true })
            cell.classList.add('se-multiline-row')
            table.appendChild(cell)
        }
        this.fieldsPanel.appendChild(table)
    }

    _buildFieldCell(field, currentValue, opts = {}) {
        const row = document.createElement('div')
        row.className = 'se-field-row'

        const label = document.createElement('span')
        label.className = 'se-field-label'
        label.textContent = field.label
        if (field.dimension) {
            const dim = document.createElement('span')
            dim.className = 'se-field-dim'
            dim.textContent = field.dimension
            label.appendChild(dim)
        }
        row.appendChild(label)

        const input = this._createFieldInput(field, currentValue, opts)
        row.appendChild(input)
        return row
    }

    _renderTaskGrid(schema, fv) {
        const table = document.createElement('div')
        table.className = 'se-fields-grid se-task-grid'

        const fmap = {}
        for (const f of schema.fields) fmap[f.name] = f

        // 用戶指定的 5 列佈局（每列 4 欄；缺項留空格）
        const layout = [
            ['category', 'urgency', 'location', 'attendees'],
            ['note'],
            ['baseline_start', 'baseline_end'],
            ['planned_start', 'planned_end', 'planned_duration'],
            ['actual_start', 'actual_end', 'progress', 'status'],
        ]

        for (const row of layout) {
            for (const name of row) {
                const field = fmap[name]
                if (!field) continue
                const isNote = name === 'note'
                const cell = this._buildFieldCell(
                    field,
                    fv[field.name] || '',
                    { multiline: isNote }
                )
                if (isNote) cell.classList.add('se-task-note')
                table.appendChild(cell)
            }
            // 補空格 cell 對齊 grid 欄數（避免下一列從上一列留下的空隙開始）
            const remain = 4 - row.length
            if (remain > 0 && row[0] !== 'note') {
                for (let i = 0; i < remain; i++) {
                    const filler = document.createElement('div')
                    filler.className = 'se-field-row se-task-filler'
                    table.appendChild(filler)
                }
            }
        }
        this.fieldsPanel.appendChild(table)
    }

    _renderIdCard() {
        this.fieldsPanel.innerHTML = ''
        this._idcardInputs = []
        this._idcardImgBox = null
        this._idcardRenderImage = null
        this._idcardToggle = null
        const fv = this.node.attrs.fieldValues || {}

        const body = document.createElement('div')
        body.className = 'se-idcard-body'

        // 左：圖框（contentEditable=false 讓 ProseMirror 不接管 caret，可正常觸發 click）
        const imgBox = document.createElement('div')
        imgBox.className = 'se-idcard-image'
        imgBox.title = '點擊選圖 (Tab 訪問,Enter 開啟)'
        imgBox.contentEditable = 'false'
        imgBox.tabIndex = 0
        // 阻擋 keydown 冒泡到 PM,並提供 Tab/Enter/Arrow 處理
        imgBox.addEventListener('keydown', (e) => {
            e.stopPropagation()
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                imgBox.click()
            } else if (e.key === 'Tab') {
                e.preventDefault()
                this._focusNextField(imgBox, e.shiftKey)
            } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                this._focusBeforeEntry()
            } else if (e.key === 'ArrowDown') {
                e.preventDefault()
                this._focusAfterEntry()
            } else if (e.key === 'Escape') {
                e.preventDefault()
                imgBox.blur()
            }
        })

        const renderImage = () => {
            imgBox.innerHTML = ''
            const currentFv = this.node.attrs.fieldValues || {}
            const token = (currentFv.image_token || '').trim()
            if (token) {
                const img = document.createElement('img')
                img.src = '/beakcortex/files/' + encodeURIComponent(token)
                img.alt = ''
                img.draggable = false
                imgBox.appendChild(img)
            } else {
                const empty = document.createElement('div')
                empty.className = 'se-idcard-image-empty'
                empty.textContent = '點擊選圖'
                imgBox.appendChild(empty)
            }

            const actions = document.createElement('div')
            actions.className = 'se-idcard-image-actions'
            const replaceBtn = document.createElement('button')
            replaceBtn.type = 'button'
            replaceBtn.className = 'se-idcard-image-action'
            replaceBtn.textContent = token ? '換圖' : '選圖'
            replaceBtn.addEventListener('click', (e) => {
                e.stopPropagation()
                pickImage()
            })
            actions.appendChild(replaceBtn)
            if (token) {
                const clearBtn = document.createElement('button')
                clearBtn.type = 'button'
                clearBtn.className = 'se-idcard-image-action'
                clearBtn.textContent = '清除'
                clearBtn.addEventListener('click', (e) => {
                    e.stopPropagation()
                    this._setIdCardField('image_token', '')
                    renderImage()
                })
                actions.appendChild(clearBtn)
            }
            imgBox.appendChild(actions)
        }

        const pickImage = () => {
            const currentFv = this.node.attrs.fieldValues || {}
            openImageAlbumPicker({
                currentToken: currentFv.image_token || null,
                onSelect: (token) => {
                    this._setIdCardField('image_token', token)
                    renderImage()
                },
            })
        }
        imgBox.addEventListener('click', pickImage)
        renderImage()
        this._idcardImgBox = imgBox
        this._idcardRenderImage = renderImage
        body.appendChild(imgBox)

        // 右：四列文字
        const fields = document.createElement('div')
        fields.className = 'se-idcard-fields'
        const placeholders = ['主標（如姓名/設備名）', '副標（職稱/型號）', '第三列', '第四列']
        // 阻擋鍵盤/輸入/貼上事件冒泡到 ProseMirror，否則：
        //   - IME 中文 composition 會被 PM 攔截（無法輸入中文）
        //   - paste / Ctrl+V 會被 PM 接管
        //   - Backspace 會觸發 PM 對整個 NodeSelection 的刪除
        const STOP_EVENTS = [
            'keydown', 'keyup', 'keypress',
            'beforeinput', 'input',
            'paste', 'cut', 'copy',
            'compositionstart', 'compositionupdate', 'compositionend',
            'mousedown', 'mouseup', 'click', 'dblclick',
            'drop', 'dragstart',
        ]
        for (let i = 1; i <= 4; i++) {
            const key = 'line' + i
            const inp = document.createElement('input')
            inp.type = 'text'
            inp.className = 'se-idcard-line se-idcard-line-' + i
            inp.placeholder = placeholders[i - 1]
            inp.value = fv[key] || ''
            // 先註冊 stopPropagation -- 必須在自訂 keydown handler 之前
            for (const evName of STOP_EVENTS) {
                inp.addEventListener(evName, (e) => e.stopPropagation())
            }
            inp.addEventListener('blur', () => {
                this._setIdCardField(key, inp.value)
            })
            const lineIdx = i  // 1..4 closure 鎖定
            inp.addEventListener('keydown', (e) => {
                // ArrowUp/Down: 跳脫 entry 至前/後 textblock（不在 line 之間移動）
                if (e.key === 'ArrowUp') {
                    e.preventDefault()
                    this._setIdCardField(key, inp.value)
                    this._focusBeforeEntry()
                } else if (e.key === 'ArrowDown') {
                    e.preventDefault()
                    this._setIdCardField(key, inp.value)
                    this._focusAfterEntry()
                } else if (e.key === 'Enter') {
                    // Enter 跳脫 entry 到後方 textblock（line1~4 短文不需換行）
                    e.preventDefault()
                    this._setIdCardField(key, inp.value)
                    this._focusAfterEntry()
                } else if (e.key === 'Tab') {
                    // 主動接管 Tab:在 entry 內所有 focusable input 間順序移動;邊界跳脫 entry。
                    e.preventDefault()
                    this._setIdCardField(key, inp.value)
                    this._focusNextField(inp, e.shiftKey)
                } else if (e.key === 'Escape') {
                    e.preventDefault()
                    inp.value = (this.node.attrs.fieldValues || {})[key] || ''
                    inp.blur()
                }
            })
            this._idcardInputs.push(inp)
            fields.appendChild(inp)
        }
        body.appendChild(fields)
        this.fieldsPanel.appendChild(body)

        // 工具列：主帳卡 toggle
        const toolbar = document.createElement('div')
        toolbar.className = 'se-idcard-toolbar'
        toolbar.contentEditable = 'false'
        toolbar.addEventListener('mousedown', (e) => e.stopPropagation())

        const isPrimary = this._idCardIsPrimary()
        const toggle = document.createElement('span')
        toggle.className = 'se-idcard-primary-toggle' + (isPrimary ? ' is-active' : '')
        toggle.textContent = (isPrimary ? '★' : '☆') + ' 設為白板主帳卡'
        toggle.title = '勾選後，此帳卡將取代卡片在白板上的縮圖預覽'
        toggle.addEventListener('click', () => this._toggleIdCardPrimary())
        this._idcardToggle = toggle
        toolbar.appendChild(toggle)
        this.fieldsPanel.appendChild(toolbar)
    }

    _refreshIdCard() {
        // 增量更新：不替換 input 元素，避免 ProseMirror dispatch 觸發的 NodeView.update 把焦點打掉
        const fv = this.node.attrs.fieldValues || {}
        if (this._idcardRenderImage) {
            try { this._idcardRenderImage() } catch (_) {}
        }
        if (this._idcardInputs) {
            for (let i = 0; i < this._idcardInputs.length; i++) {
                const inp = this._idcardInputs[i]
                if (!inp) continue
                const newVal = fv['line' + (i + 1)] || ''
                // 不覆蓋正在被使用者編輯的 input（避免 IME composition 中被中斷）
                if (document.activeElement !== inp && inp.value !== newVal) {
                    inp.value = newVal
                }
            }
        }
        if (this._idcardToggle) {
            const isPrimary = this._idCardIsPrimary()
            this._idcardToggle.classList.toggle('is-active', isPrimary)
            this._idcardToggle.textContent = (isPrimary ? '★' : '☆') + ' 設為白板主帳卡'
        }
    }

    _focusAfterEntry() {
        // 從此 entry 的下一個位置找最近的 textblock(包括其他 entry,讓並列 entry 可以鄰接導航)。
        // 對 idcard 等 hidden contentDOM 的 entry,_moveCaretTo 會 redirect 到 line1 input。
        if (!this.editor || !this.editor.state) return
        const pos = this.getPos()
        if (pos === undefined) {
            this.editor.commands.focus()
            return
        }
        const after = pos + this.node.nodeSize
        const doc = this.editor.state.doc
        let target = null
        let targetNode = null
        try {
            doc.nodesBetween(after, doc.content.size, (n, p) => {
                if (target !== null) return false
                if (n.isTextblock) {
                    target = p
                    targetNode = n
                    return false
                }
                return true
            })
        } catch (_) { /* ignore */ }
        if (target !== null) {
            _moveCaretTo(this.editor, target, targetNode, false)
            return
        }
        // 沒有後續 textblock:在 doc 末插一個 paragraph 並進入
        try {
            const tr = this.editor.state.tr
            const para = this.editor.state.schema.nodes.paragraph.create()
            tr.insert(after, para)
            tr.setSelection(TextSelection.create(tr.doc, after + 1))
            this.editor.view.dispatch(tr)
            this.editor.view.focus()
        } catch (_) {
            this.editor.commands.focus()
        }
    }

    _focusBeforeEntry() {
        // 從 entry 之前的位置往前找最後一個 textblock,進入其尾端(包括其他 entry)。
        if (!this.editor || !this.editor.state) return
        const pos = this.getPos()
        if (pos === undefined || pos <= 0) {
            this.editor.commands.focus()
            return
        }
        const doc = this.editor.state.doc
        let target = null
        let targetNode = null
        try {
            doc.nodesBetween(0, pos, (n, p) => {
                if (n.isTextblock) {
                    target = p
                    targetNode = n
                    return false
                }
                return true
            })
        } catch (_) { /* ignore */ }
        if (target !== null) {
            _moveCaretTo(this.editor, target, targetNode, true)
            return
        }
        // 沒有前置 textblock:在 doc 開頭插 paragraph
        try {
            const tr = this.editor.state.tr
            const para = this.editor.state.schema.nodes.paragraph.create()
            tr.insert(0, para)
            tr.setSelection(TextSelection.create(tr.doc, 1))
            this.editor.view.dispatch(tr)
            this.editor.view.focus()
        } catch (_) {
            this.editor.commands.focus()
        }
    }

    _idCardIsPrimary() {
        const v = (this.node.attrs.fieldValues || {}).is_primary
        return v === 'true' || v === true
    }

    _setIdCardField(key, value) {
        const pos = this.getPos()
        if (pos === undefined) return
        const fv = { ...(this.node.attrs.fieldValues || {}) }
        fv[key] = value
        this.editor.view.dispatch(
            this.editor.view.state.tr.setNodeMarkup(pos, undefined, {
                ...this.node.attrs,
                fieldValues: fv,
            })
        )
    }

    _toggleIdCardPrimary() {
        const pos = this.getPos()
        if (pos === undefined) return
        const next = !this._idCardIsPrimary()
        const tr = this.editor.view.state.tr

        if (next) {
            // 單選邏輯：把同 doc 內所有其他 idcard 的 is_primary 設為 false
            this.editor.view.state.doc.descendants((node, p) => {
                if (node.type.name !== 'structuredEntry') return
                if ((node.attrs.schemaCode || '') !== 'idcard') return
                if (p === pos) return
                const ofv = node.attrs.fieldValues || {}
                if (ofv.is_primary === 'true' || ofv.is_primary === true) {
                    tr.setNodeMarkup(p, undefined, {
                        ...node.attrs,
                        fieldValues: { ...ofv, is_primary: 'false' },
                    })
                }
            })
        }

        const fv = { ...(this.node.attrs.fieldValues || {}) }
        fv.is_primary = next ? 'true' : 'false'
        tr.setNodeMarkup(pos, undefined, { ...this.node.attrs, fieldValues: fv })
        this.editor.view.dispatch(tr)
    }

    _createFieldInput(field, currentValue, opts = {}) {
        let el
        if (opts.multiline) {
            el = document.createElement('textarea')
            el.className = 'se-field-input se-field-textarea'
            el.rows = 3
            el.value = currentValue
            el.placeholder = 'Enter 跳脫物件 / Shift+Enter 換行'
        } else if (field.field_type === 'select' || field.field_type === 'multiselect') {
            el = document.createElement('select')
            el.className = 'se-field-input'
            // Add empty option
            const emptyOpt = document.createElement('option')
            emptyOpt.value = ''
            emptyOpt.textContent = '-'
            el.appendChild(emptyOpt)
            try {
                const options = JSON.parse(field.options || '[]')
                for (const opt of options) {
                    const o = document.createElement('option')
                    o.value = opt
                    o.textContent = opt
                    if (opt === currentValue) o.selected = true
                    el.appendChild(o)
                }
            } catch (e) { /* invalid options JSON */ }
        } else if (field.field_type === 'checkbox') {
            el = document.createElement('input')
            el.type = 'checkbox'
            el.className = 'se-field-input'
            el.checked = currentValue === 'true' || currentValue === true
        } else if (field.field_type === 'date') {
            el = document.createElement('input')
            el.type = 'date'
            el.className = 'se-field-input'
            el.value = currentValue
        } else if (field.field_type === 'datetime') {
            el = document.createElement('input')
            el.type = 'datetime-local'
            el.className = 'se-field-input'
            el.value = currentValue
        } else if (field.field_type === 'number' || field.field_type === 'decimal') {
            el = document.createElement('input')
            el.type = 'number'
            el.className = 'se-field-input'
            el.value = currentValue
            if (field.field_type === 'decimal') el.step = '0.01'
        } else {
            el = document.createElement('input')
            el.type = 'text'
            el.className = 'se-field-input'
            el.value = currentValue
        }

        // On change, update the node attribute
        const handler = () => {
            const pos = this.getPos()
            if (pos === undefined) return
            const newValue = el.type === 'checkbox' ? String(el.checked) : el.value
            const fv = { ...(this.node.attrs.fieldValues || {}) }
            fv[field.name] = newValue
            this.editor.view.dispatch(
                this.editor.view.state.tr.setNodeMarkup(pos, undefined, {
                    ...this.node.attrs,
                    fieldValues: fv,
                })
            )
        }
        el.addEventListener('change', handler)
        if (el.tagName === 'INPUT' && el.type !== 'checkbox') {
            el.addEventListener('blur', handler)
        }

        // 阻擋所有鍵盤/輸入相關事件冒到 ProseMirror,避免 PM 攔截 Tab/Enter/Shift-Enter
        // (PM 的 ListHotkeys.Tab 會 preventDefault 吃掉 Tab、Shift-Enter 會在主旨欄插 hardBreak)
        const STOP_FIELD_EVENTS = [
            'keyup', 'keypress',
            'beforeinput', 'input',
            'paste', 'cut', 'copy',
            'compositionstart', 'compositionupdate', 'compositionend',
        ]
        for (const evName of STOP_FIELD_EVENTS) {
            el.addEventListener(evName, (e) => e.stopPropagation())
        }

        // 鍵盤導航:Enter 跳脫 entry、Shift+Enter 在 textarea 自然換行、ArrowUp/Down 跳脫
        // 不攔 Tab(讓瀏覽器自然在 fieldsPanel 內 input 之間移動,但要 stopPropagation 阻擋 PM)
        // checkbox/select 預設行為較特殊,避開 ArrowUp/Down 攔截
        const isCheckbox = el.tagName === 'INPUT' && el.type === 'checkbox'
        const isSelect = el.tagName === 'SELECT'
        const isTextarea = el.tagName === 'TEXTAREA'
        el.addEventListener('keydown', (e) => {
            // 一律 stopPropagation,確保 PM 收不到任何 input 內的 keydown
            e.stopPropagation()

            if (e.key === 'Enter' && !e.shiftKey) {
                // Enter 跳脫 entry (textarea 也適用,換行請用 Shift+Enter)
                e.preventDefault()
                handler()
                this._focusAfterEntry()
            } else if (e.key === 'Enter' && e.shiftKey) {
                // textarea: 不 preventDefault,瀏覽器自然在 textarea 內換行
                // 非 textarea 的 input: Shift+Enter 也跳脫,行為等同 Enter
                if (!isTextarea) {
                    e.preventDefault()
                    handler()
                    this._focusAfterEntry()
                }
            } else if (e.key === 'Escape') {
                e.preventDefault()
                el.blur()
            } else if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && !isSelect && !isCheckbox) {
                if (isTextarea) {
                    // textarea 內若是多行,讓 Arrow 在文字內正常移動;只在邊界行跳脫
                    const isAtTopLine = el.selectionStart === 0 || el.value.lastIndexOf('\n', el.selectionStart - 1) === -1
                    const isAtBottomLine = el.value.indexOf('\n', el.selectionStart) === -1
                    if (e.key === 'ArrowUp' && isAtTopLine) {
                        e.preventDefault()
                        handler()
                        this._focusBeforeEntry()
                    } else if (e.key === 'ArrowDown' && isAtBottomLine) {
                        e.preventDefault()
                        handler()
                        this._focusAfterEntry()
                    }
                } else {
                    e.preventDefault()
                    handler()
                    if (e.key === 'ArrowUp') this._focusBeforeEntry()
                    else this._focusAfterEntry()
                }
            } else if (e.key === 'Tab') {
                // 主動接管 Tab:在 entry 內所有 focusable input 間順序移動;邊界跳脫 entry。
                // 瀏覽器預設 Tab 在 contenteditable nodeView 內表現不一致,改全部主動處理。
                e.preventDefault()
                handler()
                this._focusNextField(el, e.shiftKey)
            }
        })

        return el
    }

    update(node) {
        if (node.type.name !== 'structuredEntry') return false
        this.node = node
        const code = node.attrs.schemaCode || 'freetext'
        const isFile = code === 'file'
        const isIdCard = code === 'idcard'
        this.dom.className = 'se-block se-' + code
        if (isIdCard) this.dom.classList.add('se-idcard')
        this._updateVisualMode()
        if (isFile) {
            this._renderFileHeader()
            this.fieldsPanel.style.display = 'none'
        } else if (isIdCard) {
            this.contentDOM.style.display = 'none'
            this.fieldsPanel.style.display = 'block'
            // 用增量更新而非整個 re-render，避免 input 元素被 detach 導致焦點丟失
            if (this._idcardRenderedOnce) {
                this._refreshIdCard()
            } else {
                this._renderIdCard()
                this._idcardRenderedOnce = true
            }
            // 清除 idcard 殘留的 inline content (主旨欄是 line1 input,不該有 inline 文字)
            this._scheduleIdcardInlineCleanup()
        } else {
            this.fieldsPanel.style.display = node.attrs.collapsed ? 'none' : 'block'
            if (this.toggleBtn) {
                this.toggleBtn.textContent = node.attrs.collapsed ? '+' : '-'
                this.toggleBtn.title = node.attrs.collapsed ? '展開欄位' : '收合欄位'
            }
            if (!node.attrs.collapsed) {
                this._renderFields()
            }
        }
        return true
    }

    selectNode() {
        this.dom.classList.add('se-selected')
        // idcard 被 PM NodeSelection 時(從上下方 caret 進入 hidden contentDOM 的常見路徑),
        // 重定向 caret 到 line1(主旨欄),避免 caret 卡在隱形 contentDOM 內視覺上消失
        if ((this.node.attrs.schemaCode || '') === 'idcard' && this._idcardInputs && this._idcardInputs[0]) {
            queueMicrotask(() => {
                try { this._idcardInputs[0].focus() } catch (_) {}
            })
        }
    }

    deselectNode() {
        this.dom.classList.remove('se-selected')
    }

    destroy() {
        if (this._onSelUpdate && this.editor) {
            try { this.editor.off('selectionUpdate', this._onSelUpdate) } catch (_) {}
            this._onSelUpdate = null
        }
    }
}


export default StructuredEntry
