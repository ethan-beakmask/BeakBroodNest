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

        // 展開/收合按鈕
        this.toggleBtn = document.createElement('span')
        this.toggleBtn.className = 'se-toggle-btn'
        this.toggleBtn.textContent = node.attrs.collapsed ? '+' : '-'
        this.toggleBtn.title = node.attrs.collapsed ? '展開欄位' : '收合欄位'
        this.toggleBtn.addEventListener('click', (e) => {
            e.stopPropagation()
            this._toggleCollapsed()
        })
        this.tagRow.appendChild(this.toggleBtn)

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

        // 內容區（ProseMirror 管理的 inline content）
        this.contentDOM = document.createElement('div')
        this.contentDOM.className = 'se-content'
        this.dom.appendChild(this.contentDOM)

        // 欄位面板
        this.fieldsPanel = document.createElement('div')
        this.fieldsPanel.className = 'se-fields'
        this.fieldsPanel.style.display = node.attrs.collapsed ? 'none' : 'block'
        this._renderFields()
        this.dom.appendChild(this.fieldsPanel)
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
        const table = document.createElement('div')
        table.className = 'se-fields-grid'

        for (const field of schema.fields.sort((a, b) => a.sort_order - b.sort_order)) {
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

            const input = this._createFieldInput(field, fv[field.name] || '')
            row.appendChild(input)

            table.appendChild(row)
        }
        this.fieldsPanel.appendChild(table)
    }

    _createFieldInput(field, currentValue) {
        let el
        if (field.field_type === 'select' || field.field_type === 'multiselect') {
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
        this.dom.className = 'se-block se-' + (node.attrs.schemaCode || 'freetext')
        this._updateVisualMode()
        this.fieldsPanel.style.display = node.attrs.collapsed ? 'none' : 'block'
        this.toggleBtn.textContent = node.attrs.collapsed ? '+' : '-'
        this.toggleBtn.title = node.attrs.collapsed ? '展開欄位' : '收合欄位'
        if (!node.attrs.collapsed) {
            this._renderFields()
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
