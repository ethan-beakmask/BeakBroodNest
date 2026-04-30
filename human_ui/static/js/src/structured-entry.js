/**
 * BeakCortex StructuredEntry -- Tiptap Node Extension
 *
 * Z 階段架構:
 *   - 文件流內 entry NodeView 是「純展示」(整個 contentEditable=false)
 *   - 編輯一律走 entry-modal.js 的 modal 對話框
 *   - 收合 -> 顯示主旨;全展 -> 顯示主旨 + 唯讀欄位
 *   - 唯一刪除入口是 [x] 按鈕(或 NodeSelection + Backspace 業界慣例)
 *
 * Attributes:
 *   entryId     - DB id (nullable for unsaved)
 *   schemaCode  - entry schema code ('task','idcard','expense'...)
 *   schemaId    - entry schema id
 *   fieldValues - JSON object {field_name: value}
 *   collapsed   - 是否收合(true=只顯示主旨,false=展示完整唯讀欄位)
 *
 * 主旨儲存:仍走 inline content (PM contentDOM,但 hidden 不可編輯)。
 * idcard 例外:主旨來自 fieldValues.line1,inline 文字保持空。
 */
import { Node, mergeAttributes } from '@tiptap/core'
import { NodeSelection, TextSelection, Plugin } from '@tiptap/pm/state'
import { openEntryModal } from './entry-modal.js'

// 共用：在 selection 路徑上找 structuredEntry 的 depth (回傳 -1 表示不在 entry 內)
function _entryDepth(state) {
    const { $from } = state.selection
    for (let d = $from.depth; d > 0; d--) {
        if ($from.node(d).type.name === 'structuredEntry') return d
    }
    return -1
}

// 共用:判斷 selection 是否為 NodeSelection 且選中 structuredEntry。
function _isEntryNodeSelection(sel) {
    return sel instanceof NodeSelection
        && sel.node
        && sel.node.type.name === 'structuredEntry'
}

// 共用:在 caret 位於 textblock 末尾且下一個 sibling 是 entry 時,把 selection 設為 NodeSelection。
function _enterEntryAfterIfAdjacent(editor) {
    const state = editor.state
    const { $from, empty } = state.selection
    if (!empty) return false
    const parent = $from.parent
    if ($from.parentOffset !== parent.content.size) return false
    try {
        const after = $from.after($from.depth)
        const next = state.doc.nodeAt(after)
        if (next && next.type.name === 'structuredEntry') {
            const tr = state.tr.setSelection(NodeSelection.create(state.doc, after))
            editor.view.dispatch(tr)
            editor.view.focus()
            return true
        }
    } catch (_) { /* ignore */ }
    return false
}

// 共用:在 caret 位於 textblock 開頭且前一個 sibling 是 entry 時,把 selection 設為 NodeSelection。
function _enterEntryBeforeIfAdjacent(editor) {
    const state = editor.state
    const { $from, empty } = state.selection
    if (!empty) return false
    if ($from.parentOffset !== 0) return false
    try {
        const before = $from.before($from.depth)
        if (before <= 0) return false
        const $before = state.doc.resolve(before)
        const prev = $before.nodeBefore
        if (prev && prev.type.name === 'structuredEntry') {
            const prevPos = before - prev.nodeSize
            const tr = state.tr.setSelection(NodeSelection.create(state.doc, prevPos))
            editor.view.dispatch(tr)
            editor.view.focus()
            return true
        }
    } catch (_) { /* ignore */ }
    return false
}

// 跳到指定 pos 後/前的下一個 textblock 或 entry。
// - 命中 entry -> 設 NodeSelection (用戶要求 entry 也是「目標」之一)
// - 命中一般 textblock -> setTextSelection 進去 (forward=開頭, backward=末尾)
// - 都沒命中 -> 在 fromPos 插一個 paragraph
// 用於「從 table cell 邊界 ArrowDown/ArrowUp 脫出表格」等場景。
export function jumpOutOfBlock(editor, fromPos, forward) {
    const state = editor.state
    const doc = state.doc
    let target = null
    let targetIsEntry = false
    let targetNode = null
    if (forward) {
        doc.nodesBetween(fromPos, doc.content.size, (n, p) => {
            if (target !== null) return false
            if (n.type.name === 'structuredEntry') {
                target = p; targetIsEntry = true; targetNode = n
                return false
            }
            if (n.isTextblock) {
                target = p; targetNode = n
                return false
            }
            return true
        })
    } else {
        doc.nodesBetween(0, fromPos, (n, p) => {
            if (n.type.name === 'structuredEntry') {
                target = p; targetIsEntry = true; targetNode = n
                return false
            }
            if (n.isTextblock) {
                target = p; targetNode = n
                return false
            }
            return true
        })
    }
    if (target !== null) {
        if (targetIsEntry) {
            const tr = state.tr.setSelection(NodeSelection.create(state.doc, target))
            editor.view.dispatch(tr)
            editor.view.focus()
        } else {
            const pos = forward ? target + 1 : target + 1 + targetNode.content.size
            editor.chain().focus().setTextSelection(pos).run()
        }
        return true
    }
    // 邊界沒目標 -> 插 paragraph
    const insertPos = forward ? Math.min(fromPos, doc.content.size) : 0
    const tr = state.tr
    const para = state.schema.nodes.paragraph.create()
    tr.insert(insertPos, para)
    tr.setSelection(TextSelection.create(tr.doc, insertPos + 1))
    editor.view.dispatch(tr)
    editor.view.focus()
    return true
}

// 共用:當前 NodeSelection 對 entry 時開 modal 編輯。
function _openEditOnSelectedEntry(editor) {
    const sel = editor.state.selection
    if (!_isEntryNodeSelection(sel)) return false
    const dom = editor.view.nodeDOM(sel.from)
    if (dom && typeof dom._beakOpenEdit === 'function') {
        dom._beakOpenEdit()
        return true
    }
    return false
}

// 共用:判斷 selection 是否在 structuredEntry 內(供 paste 攔截使用)。
function _isSelectionInEntry(state) {
    const { $from } = state.selection
    for (let d = $from.depth; d > 0; d--) {
        if ($from.node(d).type.name === 'structuredEntry') return true
    }
    return false
}

// 共用:把 caret 移到指定 textblock 的開頭/末尾。
// 若該 textblock 是 structuredEntry(其 contentDOM 永遠 hidden),跳過,讓 caller 繼續找下一個。
function _moveCaretTo(editor, textblockPos, textblockNode, atEnd) {
    if (textblockNode.type.name === 'structuredEntry') {
        // entry 不可放 caret -- 由 caller 跳過繼續找
        return false
    }
    const inlinePos = atEnd
        ? textblockPos + 1 + textblockNode.content.size
        : textblockPos + 1
    editor.chain().focus().setTextSelection(inlinePos).run()
    return true
}

// 共用:從給定的 entry pos 往後找「非 entry」的 textblock,跳到開頭。
// 找不到則在 doc 末插一個 paragraph 並進入。
function _focusAfterCurrentEntry(editor) {
    const d = _entryDepth(editor.state)
    if (d < 0) return false
    const { $from } = editor.state.selection
    const entryAfter = $from.after(d)
    return _focusForwardFromPos(editor, entryAfter)
}

function _focusForwardFromPos(editor, fromPos) {
    const doc = editor.state.doc
    let target = null
    let targetNode = null
    doc.nodesBetween(fromPos, doc.content.size, (n, p) => {
        if (target !== null) return false
        if (n.isTextblock && n.type.name !== 'structuredEntry') {
            target = p
            targetNode = n
            return false
        }
        return true
    })
    if (target !== null) {
        return _moveCaretTo(editor, target, targetNode, false)
    }
    // 沒有後續可用 textblock -- 在 doc 末插一個 paragraph
    const tr = editor.state.tr
    const insertPos = Math.min(fromPos, editor.state.doc.content.size)
    const para = editor.state.schema.nodes.paragraph.create()
    tr.insert(insertPos, para)
    tr.setSelection(TextSelection.create(tr.doc, insertPos + 1))
    editor.view.dispatch(tr)
    editor.view.focus()
    return true
}

// 共用:跳到 entry 之前「最近的非 entry textblock」尾端;無則在 doc 開頭插 paragraph。
function _focusBeforeCurrentEntry(editor) {
    const d = _entryDepth(editor.state)
    if (d < 0) return false
    const { $from } = editor.state.selection
    const entryBefore = $from.before(d)
    return _focusBackwardFromPos(editor, entryBefore)
}

function _focusBackwardFromPos(editor, toPos) {
    const doc = editor.state.doc
    let target = null
    let targetNode = null
    doc.nodesBetween(0, toPos, (n, p) => {
        if (n.isTextblock && n.type.name !== 'structuredEntry') {
            target = p
            targetNode = n
            return false
        }
        return true
    })
    if (target !== null) {
        return _moveCaretTo(editor, target, targetNode, true)
    }
    const tr = editor.state.tr
    const para = editor.state.schema.nodes.paragraph.create()
    tr.insert(0, para)
    tr.setSelection(TextSelection.create(tr.doc, 1))
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
            'class': 'se-block se-readonly se-' + (HTMLAttributes.schemaCode || 'freetext'),
        }
        return ['div', mergeAttributes(attrs), 0]
    },

    addNodeView() {
        return ({ node, getPos, editor }) => {
            return new StructuredEntryView(node, getPos, editor)
        }
    },

    addKeyboardShortcuts() {
        // entry NodeView 永遠 contentEditable=false。鍵盤行為:
        //   ArrowDown 從前段末尾 -> 將下一個 entry 設為 NodeSelection (停在 entry)
        //   ArrowDown 在 entry NodeSelection -> 跳到下一個非 entry textblock
        //   ArrowUp   對稱
        //   Enter on NodeSelection(entry) -> 開 modal
        //   F2 on NodeSelection(entry)    -> 開 modal
        //   Tab on NodeSelection(entry)   -> 跳到下一個位置 (同 ArrowDown)
        //   Backspace/Delete on NodeSelection(entry) -> 吃掉 (entry 只能由 [x] 刪除)
        //   Backspace 在 entry 後段首字 / Delete 在 entry 前段末字 -> 吃掉
        return {
            ArrowUp: ({ editor }) => {
                const state = editor.state
                const sel = state.selection
                // 已 NodeSelection 在 entry 上 -> 跳出到上一個位置
                if (_isEntryNodeSelection(sel)) {
                    return _focusBackwardFromPos(editor, sel.from)
                }
                // 萬一 caret 跑進 entry inline -> redirect 出去
                if (_entryDepth(state) >= 0) {
                    return _focusBeforeCurrentEntry(editor)
                }
                // 在 textblock 開頭 + 前一個 sibling 是 entry -> 設 NodeSelection
                return _enterEntryBeforeIfAdjacent(editor)
            },
            ArrowDown: ({ editor }) => {
                const state = editor.state
                const sel = state.selection
                if (_isEntryNodeSelection(sel)) {
                    const node = state.doc.nodeAt(sel.from)
                    if (!node) return false
                    return _focusForwardFromPos(editor, sel.from + node.nodeSize)
                }
                if (_entryDepth(state) >= 0) {
                    return _focusAfterCurrentEntry(editor)
                }
                return _enterEntryAfterIfAdjacent(editor)
            },
            Enter: ({ editor }) => {
                const sel = editor.state.selection
                // entry NodeSelection -> 開 modal
                if (_isEntryNodeSelection(sel)) {
                    return _openEditOnSelectedEntry(editor)
                }
                if (_entryDepth(editor.state) < 0) return false
                return _focusAfterCurrentEntry(editor)
            },
            'Shift-Enter': ({ editor }) => {
                if (_isEntryNodeSelection(editor.state.selection)) {
                    return _openEditOnSelectedEntry(editor)
                }
                if (_entryDepth(editor.state) < 0) return false
                return _focusAfterCurrentEntry(editor)
            },
            'Mod-Enter': ({ editor }) => {
                if (_isEntryNodeSelection(editor.state.selection)) {
                    return _openEditOnSelectedEntry(editor)
                }
                if (_entryDepth(editor.state) < 0) return false
                return _focusAfterCurrentEntry(editor)
            },
            Tab: ({ editor }) => {
                const state = editor.state
                const sel = state.selection
                if (_isEntryNodeSelection(sel)) {
                    const node = state.doc.nodeAt(sel.from)
                    if (!node) return false
                    return _focusForwardFromPos(editor, sel.from + node.nodeSize)
                }
                if (_entryDepth(state) < 0) return false
                return _focusAfterCurrentEntry(editor)
            },
            'Shift-Tab': ({ editor }) => {
                const sel = editor.state.selection
                if (_isEntryNodeSelection(sel)) {
                    return _focusBackwardFromPos(editor, sel.from)
                }
                if (_entryDepth(editor.state) < 0) return false
                return _focusBeforeCurrentEntry(editor)
            },
            Backspace: ({ editor }) => {
                const state = editor.state
                const sel = state.selection
                // NodeSelection 對 entry -> 吃掉(entry 只能透過 [x] 刪除)
                if (_isEntryNodeSelection(sel)) return true
                const { $from, empty } = sel
                if (!empty) return false
                if (_entryDepth(state) >= 0) {
                    return _focusBeforeCurrentEntry(editor)
                }
                if ($from.parentOffset !== 0) return false
                try {
                    const before = $from.before($from.depth)
                    if (before <= 0) return false
                    const $before = state.doc.resolve(before)
                    const prev = $before.nodeBefore
                    if (prev && prev.type.name === 'structuredEntry') return true
                } catch (_) { /* ignore */ }
                return false
            },
            Delete: ({ editor }) => {
                const state = editor.state
                const sel = state.selection
                if (_isEntryNodeSelection(sel)) return true
                const { $from, empty } = sel
                if (!empty) return false
                if (_entryDepth(state) >= 0) {
                    return _focusAfterCurrentEntry(editor)
                }
                const parent = $from.parent
                if ($from.parentOffset !== parent.content.size) return false
                try {
                    const after = $from.after($from.depth)
                    const next = state.doc.nodeAt(after)
                    if (next && next.type.name === 'structuredEntry') return true
                } catch (_) { /* ignore */ }
                return false
            },
            F2: ({ editor }) => {
                if (_isEntryNodeSelection(editor.state.selection)) {
                    return _openEditOnSelectedEntry(editor)
                }
                return false
            },
        }
    },

    addProseMirrorPlugins() {
        return [
            new Plugin({
                props: {
                    // 主旨欄是「單行」-- 貼上含換行的文字時把換行轉空格
                    transformPastedText: (text, _plain, view) => {
                        if (!_isSelectionInEntry(view.state)) return text
                        return text.replace(/\r?\n+/g, ' ')
                    },
                    transformPastedHTML: (html, view) => {
                        if (!_isSelectionInEntry(view.state)) return html
                        try {
                            const tmp = document.createElement('div')
                            tmp.innerHTML = html
                            const text = (tmp.textContent || '').replace(/\r?\n+/g, ' ').trim()
                            return text.replace(/[&<>]/g, (c) => (
                                c === '&' ? '&amp;' : c === '<' ? '&lt;' : '&gt;'
                            ))
                        } catch (_) {
                            return html
                        }
                    },
                },
            }),
        ]
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
 * NodeView: 純展示模式 (Z 階段)
 */
class StructuredEntryView {
    constructor(node, getPos, editor) {
        this.node = node
        this.getPos = getPos
        this.editor = editor
        this._schemas = window._entrySchemas || []

        this.dom = document.createElement('div')
        this.dom.className = 'se-block se-readonly se-' + (node.attrs.schemaCode || 'freetext')
        this.dom.setAttribute('data-entry', '')
        this.dom.contentEditable = 'false'
        // 暴露給 PM keymap F2 開啟編輯
        this.dom._beakOpenEdit = () => this._openEdit()

        // 上方 tag 列
        this.tagRow = document.createElement('div')
        this.tagRow.className = 'se-tag-row'
        this.dom.appendChild(this.tagRow)

        // body 區(主旨 + 全展時的唯讀欄位)
        this.body = document.createElement('div')
        this.body.className = 'se-body'
        this.dom.appendChild(this.body)

        // contentDOM 必須存在(schema content: inline*),但永遠 hidden + 不可編輯
        this.contentDOM = document.createElement('div')
        this.contentDOM.className = 'se-content-hidden'
        this.contentDOM.style.display = 'none'
        this.dom.appendChild(this.contentDOM)

        this._buildTagRow()
        this._renderBody()

        // 雙擊整個 entry -> 開 modal
        this.dom.addEventListener('dblclick', (e) => {
            // 點到 [x] / dragHandle / badge / toggle / editBtn 不要觸發雙擊編輯
            if (this._isControlEl(e.target)) return
            e.preventDefault()
            e.stopPropagation()
            this._openEdit()
        })

        // 拖拉:只允許從 dragHandle 起源
        this.dom.addEventListener('mousedown', (e) => {
            this._mousedownInHandle = !!(this.dragHandle && this.dragHandle.contains(e.target))
        }, true)
        this.dom.addEventListener('dragstart', (e) => {
            if (!this._mousedownInHandle) e.preventDefault()
        })
    }

    _isControlEl(el) {
        if (!el) return false
        return !!(el.closest && el.closest('.se-tag-row'))
    }

    _buildTagRow() {
        this.tagRow.innerHTML = ''

        // 拖把手
        this.dragHandle = document.createElement('span')
        this.dragHandle.className = 'se-drag-handle'
        this.dragHandle.setAttribute('data-drag-handle', '')
        this.dragHandle.textContent = '≡'  // ≡
        this.dragHandle.title = '拖拉排序'
        this.tagRow.appendChild(this.dragHandle)

        // schema badge -- 點擊 = NodeSelection
        this.badge = document.createElement('span')
        this.badge.className = 'se-badge'
        this._updateBadge()
        this.badge.addEventListener('click', (e) => {
            e.stopPropagation()
            e.preventDefault()
            this._selectNode()
        })
        this.tagRow.appendChild(this.badge)

        // 展開/收合(file 不顯示)
        const code = this.node.attrs.schemaCode || ''
        if (code !== 'file') {
            this.toggleBtn = document.createElement('span')
            this.toggleBtn.className = 'se-toggle-btn'
            this.toggleBtn.textContent = this.node.attrs.collapsed ? '+' : '-'
            this.toggleBtn.title = this.node.attrs.collapsed ? '展開全部欄位 (唯讀)' : '收合'
            this.toggleBtn.addEventListener('click', (e) => {
                e.stopPropagation()
                this._toggleCollapsed()
            })
            this.tagRow.appendChild(this.toggleBtn)
        }

        // 編輯按鈕 -- 開 modal (file 類型只能透過工具列重新上傳,不開 modal)
        if (code !== 'file') {
            this.editBtn = document.createElement('button')
            this.editBtn.type = 'button'
            this.editBtn.className = 'se-edit-btn'
            this.editBtn.textContent = '編輯'
            this.editBtn.title = '編輯此物件 (F2 / 雙擊)'
            this.editBtn.addEventListener('click', (e) => {
                e.stopPropagation()
                this._openEdit()
            })
            this.tagRow.appendChild(this.editBtn)
        }

        // 刪除(freetext 不顯示;但實務 freetext 走 paragraph,structuredEntry 內不會出現)
        if ((this.node.attrs.schemaCode || 'freetext') !== 'freetext') {
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
    }

    _renderBody() {
        this.body.innerHTML = ''
        this.body.appendChild(this._buildSubjectDisplay())
        if (!this.node.attrs.collapsed) {
            const fields = this._buildFieldsReadonly()
            if (fields) this.body.appendChild(fields)
        }
    }

    _subjectText() {
        const code = this.node.attrs.schemaCode || ''
        const fv = this.node.attrs.fieldValues || {}
        if (code === 'idcard') {
            return (fv.line1 || '').trim()
        }
        if (code === 'file') {
            return fv.filename || (this.node.textContent || '')
        }
        return this.node.textContent || ''
    }

    _buildSubjectDisplay() {
        const wrap = document.createElement('div')
        wrap.className = 'se-display-row'
        const subjectSpan = document.createElement('span')
        subjectSpan.className = 'se-display-subject'
        const text = this._subjectText()
        if (text) {
            subjectSpan.textContent = text
        } else {
            subjectSpan.textContent = '(空白主旨,雙擊編輯)'
            subjectSpan.classList.add('se-display-subject--empty')
        }
        wrap.appendChild(subjectSpan)
        return wrap
    }

    _buildFieldsReadonly() {
        const code = this.node.attrs.schemaCode || ''
        if (code === 'idcard') return this._buildIdCardReadonly()
        if (code === 'file') return this._buildFileReadonly()
        const schema = this._getSchema()
        if (!schema || !schema.fields || schema.fields.length === 0) return null
        const grid = document.createElement('div')
        grid.className = 'se-fields-readonly'
        const fv = this.node.attrs.fieldValues || {}
        const sorted = schema.fields.slice().sort((a, b) => a.sort_order - b.sort_order)
        for (const f of sorted) {
            const row = document.createElement('div')
            row.className = 'se-fields-readonly__row'
            const lbl = document.createElement('span')
            lbl.className = 'se-fields-readonly__label'
            lbl.textContent = f.label + ':'
            row.appendChild(lbl)
            const val = document.createElement('span')
            val.className = 'se-fields-readonly__value'
            const v = fv[f.name]
            val.textContent = (v == null || v === '') ? '—' : String(v)
            row.appendChild(val)
            grid.appendChild(row)
        }
        return grid
    }

    _buildIdCardReadonly() {
        const wrap = document.createElement('div')
        wrap.className = 'se-idcard-readonly'
        const fv = this.node.attrs.fieldValues || {}
        const token = (fv.image_token || '').trim()
        const imgBox = document.createElement('div')
        imgBox.className = 'se-idcard-image'
        if (token) {
            const img = document.createElement('img')
            img.src = '/beakcortex/files/' + encodeURIComponent(token)
            img.alt = ''
            img.draggable = false
            imgBox.appendChild(img)
        } else {
            const empty = document.createElement('div')
            empty.className = 'se-idcard-image-empty'
            empty.textContent = '(無圖)'
            imgBox.appendChild(empty)
        }
        wrap.appendChild(imgBox)
        const lines = document.createElement('div')
        lines.className = 'se-idcard-fields'
        for (let i = 1; i <= 4; i++) {
            const line = document.createElement('div')
            line.className = 'se-idcard-line se-idcard-line-' + i
            line.textContent = fv['line' + i] || ''
            lines.appendChild(line)
        }
        wrap.appendChild(lines)
        return wrap
    }

    _buildFileReadonly() {
        const wrap = document.createElement('div')
        wrap.className = 'se-file-header'
        const fv = this.node.attrs.fieldValues || {}
        const token = fv.file_token || ''
        const filename = fv.filename || '(未命名)'
        const sizeBytes = parseInt(fv.size_bytes || '0', 10) || 0
        const mime = fv.mime_type || ''
        const icon = document.createElement('span')
        icon.className = 'se-file-icon'
        icon.textContent = '\u{1F4CE}'  // 📎
        wrap.appendChild(icon)
        const link = document.createElement('a')
        link.className = 'se-file-link'
        if (token) {
            link.href = '/beakcortex/files/' + encodeURIComponent(token)
            link.target = '_blank'
            link.rel = 'noopener'
            link.title = '點擊下載 ' + filename
        }
        link.textContent = filename
        wrap.appendChild(link)
        const meta = document.createElement('span')
        meta.className = 'se-file-meta'
        meta.textContent = ' (' + this._humanSize(sizeBytes) + (mime ? ' · ' + mime : '') + ')'
        wrap.appendChild(meta)
        return wrap
    }

    _humanSize(bytes) {
        if (!bytes) return '0 B'
        const units = ['B', 'KB', 'MB', 'GB']
        let i = 0
        let n = bytes
        while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
        return (i === 0 ? n : n.toFixed(1)) + ' ' + units[i]
    }

    _openEdit() {
        const schema = this._getSchema()
        const code = this.node.attrs.schemaCode || ''
        if (code === 'file') return  // file 不走 modal 編輯
        const subject = this._subjectText()
        openEntryModal({
            schema,
            schemaCode: code,
            rawText: subject,
            fieldValues: { ...(this.node.attrs.fieldValues || {}) },
            mode: 'edit',
            focusField: 'subject',
            onSave: ({ rawText, fieldValues }) => {
                this._applyEdit(rawText, fieldValues)
            },
        })
    }

    _applyEdit(rawText, fieldValues) {
        const pos = this.getPos()
        if (pos === undefined) return
        const view = this.editor.view
        const state = view.state
        const code = this.node.attrs.schemaCode || ''
        const fv = { ...(fieldValues || {}) }
        // idcard 主旨從 line1 進來
        if (code === 'idcard') {
            fv.line1 = rawText || fv.line1 || ''
        }
        // idcard is_primary 單選邏輯:其他 idcard 全部 false
        let primaryClearTr = null
        if (code === 'idcard' && (fv.is_primary === 'true' || fv.is_primary === true)) {
            primaryClearTr = state.tr
            state.doc.descendants((n, p) => {
                if (n.type.name !== 'structuredEntry') return
                if ((n.attrs.schemaCode || '') !== 'idcard') return
                if (p === pos) return
                const ofv = n.attrs.fieldValues || {}
                if (ofv.is_primary === 'true' || ofv.is_primary === true) {
                    primaryClearTr.setNodeMarkup(p, undefined, {
                        ...n.attrs,
                        fieldValues: { ...ofv, is_primary: 'false' },
                    })
                }
            })
        }
        const tr = primaryClearTr || state.tr
        tr.setNodeMarkup(pos, undefined, {
            ...this.node.attrs,
            fieldValues: fv,
        })
        // 替換 inline content
        const mappedPos = primaryClearTr ? tr.mapping.map(pos) : pos
        const node = state.doc.nodeAt(mappedPos) || this.node
        const inlineFrom = mappedPos + 1
        const inlineTo = mappedPos + 1 + node.content.size
        const subjectForInline = code === 'idcard' ? '' : (rawText || '')
        if (subjectForInline) {
            tr.replaceWith(inlineFrom, inlineTo, state.schema.text(subjectForInline))
        } else {
            tr.delete(inlineFrom, inlineTo)
        }
        view.dispatch(tr)
    }

    _updateBadge() {
        const schema = this._getSchema()
        const code = this.node.attrs.schemaCode || ''
        const isCal = this._isCalendarMode()
        if (schema) {
            this.badge.textContent = isCal ? '行事曆' : schema.name
            this.badge.style.backgroundColor = isCal ? '#f97316' : (schema.color || '#6b7280')
        } else {
            this.badge.textContent = code
            this.badge.style.backgroundColor = '#6b7280'
        }
        this.badge.title = '點擊選取此物件 (供擷取/謄寫)'
    }

    _updateVisualMode() {
        const isCal = this._isCalendarMode()
        const code = this.node.attrs.schemaCode || ''
        if (code === 'task') {
            this.dom.classList.toggle('se-task--calendar', isCal)
        }
        this._updateBadge()
    }

    _isCalendarMode() {
        if ((this.node.attrs.schemaCode || 'freetext') !== 'task') return false
        const fv = this.node.attrs.fieldValues || {}
        return !!(fv.planned_start && fv.planned_start.trim())
    }

    _getSchema() {
        const code = this.node.attrs.schemaCode || 'freetext'
        return this._schemas.find(s => s.code === code)
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
        if (!window._deletedEntries) window._deletedEntries = []
        window._deletedEntries.push({
            node: this.node.toJSON(),
            text: this.node.textContent,
            time: Date.now(),
        })
        const tr = this.editor.view.state.tr
        tr.delete(pos, pos + this.node.nodeSize)
        this.editor.view.dispatch(tr)
    }

    update(node) {
        if (node.type.name !== 'structuredEntry') return false
        this.node = node
        const code = node.attrs.schemaCode || 'freetext'
        this.dom.className = 'se-block se-readonly se-' + code
        this._updateVisualMode()
        if (this.toggleBtn) {
            this.toggleBtn.textContent = node.attrs.collapsed ? '+' : '-'
            this.toggleBtn.title = node.attrs.collapsed ? '展開全部欄位 (唯讀)' : '收合'
        }
        this._renderBody()
        return true
    }

    selectNode() {
        this.dom.classList.add('se-selected')
    }

    deselectNode() {
        this.dom.classList.remove('se-selected')
    }

    destroy() {
        if (this.dom) this.dom._beakOpenEdit = null
    }

    // PM 對 NodeView 內 DOM 變動的判斷:hidden contentDOM 內若有外部 mutation,
    // 我們不在乎(從 attrs 顯示主旨)。允許 PM 自然處理。
    ignoreMutation(m) {
        // 標籤列 / body 內的 DOM 變動是我們自己的渲染,PM 不要當成內容變動
        if (this.tagRow && this.tagRow.contains(m.target)) return true
        if (this.body && this.body.contains(m.target)) return true
        return false
    }
}


export default StructuredEntry
