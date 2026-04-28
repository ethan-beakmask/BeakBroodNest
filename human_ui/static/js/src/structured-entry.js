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
import { NodeSelection } from '@tiptap/pm/state'
import { openImageAlbumPicker } from './image-album.js'

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

        // 上方 tag 列
        this.tagRow = document.createElement('div')
        this.tagRow.className = 'se-tag-row'

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
        this.fieldsPanel = document.createElement('div')
        this.fieldsPanel.className = 'se-fields'
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
        imgBox.title = '點擊選圖'
        imgBox.contentEditable = 'false'

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
                if (e.key === 'Enter') {
                    e.preventDefault()
                    // 寫值（_refreshIdCard 不會替換 input 元素，焦點不會丟）
                    this._setIdCardField(key, inp.value)
                    if (lineIdx < 4) {
                        const next = this._idcardInputs[lineIdx]  // lineIdx=1→inputs[1]=line2
                        if (next) {
                            next.focus()
                            try { next.select() } catch (_) {}
                        }
                    } else {
                        // line4：跳回 ProseMirror 編輯區
                        this._focusAfterEntry()
                    }
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
        // 從 idcard entry 的下一個位置找最近的 inline-content textblock
        // 在 table cell / blockquote 等容器內，entry 之後可能直接是 block 邊界（非 inline pos），
        // 直接 setTextSelection 會丟 "TextSelection endpoint not pointing into a node with inline content"
        if (!this.editor || !this.editor.state) return
        const pos = this.getPos()
        if (pos === undefined) {
            this.editor.commands.focus()
            return
        }
        const after = pos + this.node.nodeSize
        const doc = this.editor.state.doc
        let target = null
        try {
            doc.nodesBetween(after, doc.content.size, (n, p) => {
                if (target !== null) return false
                if (n.isTextblock) {
                    // 進入 textblock 開頭 (+1)
                    target = p + 1
                    return false
                }
                return true
            })
        } catch (_) { /* ignore */ }
        if (target !== null) {
            try {
                this.editor.commands.focus(target)
                return
            } catch (_) { /* fallback */ }
        }
        this.editor.commands.focus()
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
    }

    deselectNode() {
        this.dom.classList.remove('se-selected')
    }

    destroy() {
        // cleanup
    }
}


export default StructuredEntry
