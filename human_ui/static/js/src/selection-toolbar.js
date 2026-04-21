/**
 * BeakCortex Selection Toolbar -- Tiptap Extension
 *
 * 圈選多行文字後出現浮動工具列：
 *   [轉換為...v]  [合併]  [提升為原子]
 *
 * 「轉換為...」展開 entry schemas 選單，每行轉為獨立 structuredEntry。
 * 依賴 window._entrySchemas。
 */
import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'

const selToolbarKey = new PluginKey('selectionToolbar')

export const SelectionToolbar = Extension.create({
    name: 'selectionToolbar',

    addProseMirrorPlugins() {
        const editor = this.editor
        return [
            new Plugin({
                key: selToolbarKey,
                view(editorView) {
                    return new SelectionToolbarView(editorView, editor)
                },
            }),
        ]
    },
})


class SelectionToolbarView {
    constructor(editorView, editor) {
        this.editorView = editorView
        this.editor = editor

        // Toolbar container
        this.toolbar = document.createElement('div')
        this.toolbar.className = 'sel-toolbar'
        this.toolbar.style.display = 'none'

        // "Convert to..." button
        this.convertBtn = document.createElement('button')
        this.convertBtn.className = 'sel-toolbar-btn'
        this.convertBtn.textContent = 'Convert...'
        this.convertBtn.addEventListener('click', (e) => {
            e.preventDefault()
            e.stopPropagation()
            this._showSchemaMenu()
        })
        this.toolbar.appendChild(this.convertBtn)

        // Schema dropdown
        this.dropdown = document.createElement('div')
        this.dropdown.className = 'sel-toolbar-dropdown'
        this.dropdown.style.display = 'none'
        this.toolbar.appendChild(this.dropdown)

        document.body.appendChild(this.toolbar)

        // Click outside to close dropdown
        this._outsideHandler = (e) => {
            if (!this.toolbar.contains(e.target)) {
                this.dropdown.style.display = 'none'
            }
        }
        document.addEventListener('mousedown', this._outsideHandler)
    }

    update(view) {
        const { state } = view
        const { selection } = state
        const { from, to, empty } = selection

        if (empty || to - from < 2) {
            this.toolbar.style.display = 'none'
            this.dropdown.style.display = 'none'
            return
        }

        // Check if selection spans at least one full block
        const $from = state.doc.resolve(from)
        const $to = state.doc.resolve(to)

        // Only show if we have block-level selection or multi-line
        const text = state.doc.textBetween(from, to, '\n')
        if (!text.includes('\n') && $from.parent.type.name === 'structuredEntry') {
            this.toolbar.style.display = 'none'
            return
        }

        // Position above selection
        const coords = view.coordsAtPos(from)
        this.toolbar.style.display = 'flex'
        this.toolbar.style.left = coords.left + 'px'
        this.toolbar.style.top = (coords.top - 36) + 'px'
    }

    _showSchemaMenu() {
        const schemas = (window._entrySchemas || []).filter(s => s.code !== 'freetext')
        this.dropdown.innerHTML = ''

        for (const schema of schemas) {
            const item = document.createElement('div')
            item.className = 'sel-toolbar-dropdown-item'

            const icon = document.createElement('span')
            icon.className = schema.icon || 'bi-file-text'
            icon.style.color = schema.color || '#6b7280'
            icon.style.width = '16px'
            icon.style.textAlign = 'center'
            item.appendChild(icon)

            const label = document.createElement('span')
            label.textContent = schema.name
            item.appendChild(label)

            item.addEventListener('mousedown', (e) => {
                e.preventDefault()
                this._convertSelection(schema)
            })
            this.dropdown.appendChild(item)
        }

        this.dropdown.style.display = 'block'
    }

    _convertSelection(schema) {
        const { state } = this.editorView
        const { from, to } = state.selection

        // Collect all block nodes in selection
        const blocks = []
        state.doc.nodesBetween(from, to, (node, pos) => {
            if (node.isBlock && node.isTextblock && pos >= from - 1) {
                blocks.push({ node, pos })
            }
        })

        if (blocks.length === 0) return

        // Replace each block with a structuredEntry, from end to start to keep positions valid
        let tr = state.tr
        for (let i = blocks.length - 1; i >= 0; i--) {
            const { node, pos } = blocks[i]
            const text = node.textContent
            if (!text.trim() && node.type.name === 'paragraph') continue

            const entryNode = state.schema.nodes.structuredEntry.create(
                {
                    schemaCode: schema.code,
                    schemaId: schema.id,
                    fieldValues: {},
                    collapsed: false,
                },
                text ? [state.schema.text(text)] : []
            )
            tr = tr.replaceWith(pos, pos + node.nodeSize, entryNode)
        }

        this.editorView.dispatch(tr)
        this.dropdown.style.display = 'none'
        this.toolbar.style.display = 'none'
    }

    destroy() {
        document.removeEventListener('mousedown', this._outsideHandler)
        if (this.toolbar.parentNode) {
            this.toolbar.parentNode.removeChild(this.toolbar)
        }
    }
}


export default SelectionToolbar
