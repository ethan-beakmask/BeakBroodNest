/**
 * BeakCortex Slash Command -- Tiptap Extension
 *
 * 在行首輸入 ;; 時觸發下拉選單，列出所有 entry schemas。
 * 選擇後將當前行（paragraph）轉為 structuredEntry node。
 *
 * 依賴 window._entrySchemas（由 whiteboard-card-editor.js 設定）。
 */
import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

const slashKey = new PluginKey('slashCommand')

export const SlashCommand = Extension.create({
    name: 'slashCommand',

    addProseMirrorPlugins() {
        const editor = this.editor
        return [
            new Plugin({
                key: slashKey,
                state: {
                    init() {
                        return { active: false, query: '', from: 0 }
                    },
                    apply(tr, prev, oldState, newState) {
                        const { selection } = newState
                        const { $from } = selection
                        // Only trigger in empty paragraphs or at start of text
                        if (!$from.parent || $from.parent.type.name !== 'paragraph') {
                            return { active: false, query: '', from: 0 }
                        }
                        const text = $from.parent.textContent
                        if (text.startsWith(';;')) {
                            const query = text.slice(2).toLowerCase()
                            return { active: true, query, from: $from.before() }
                        }
                        return { active: false, query: '', from: 0 }
                    },
                },
                view(editorView) {
                    return new SlashMenuView(editorView, editor)
                },
            }),
        ]
    },
})


class SlashMenuView {
    constructor(editorView, editor) {
        this.editorView = editorView
        this.editor = editor
        this.selectedIndex = 0

        // Build popup DOM
        this.popup = document.createElement('div')
        this.popup.className = 'slash-menu'
        this.popup.style.display = 'none'
        document.body.appendChild(this.popup)

        // Key handler
        this._keyHandler = (e) => this._handleKey(e)
    }

    update(view, prevState) {
        const state = slashKey.getState(view.state)
        if (!state || !state.active) {
            this._hide()
            return
        }

        const schemas = (window._entrySchemas || []).filter(s => s.code !== 'freetext')
        const query = state.query
        const filtered = query
            ? schemas.filter(s =>
                s.name.toLowerCase().includes(query) ||
                s.code.toLowerCase().includes(query) ||
                (s.slash_alias && s.slash_alias.toLowerCase().includes(query))
            )
            : schemas

        if (filtered.length === 0) {
            this._hide()
            return
        }

        this.items = filtered
        this.selectedIndex = Math.min(this.selectedIndex, filtered.length - 1)
        this._renderItems()
        this._show(view, state.from)
    }

    _renderItems() {
        this.popup.innerHTML = ''
        this.items.forEach((schema, i) => {
            const item = document.createElement('div')
            item.className = 'slash-menu-item' + (i === this.selectedIndex ? ' active' : '')
            const icon = document.createElement('span')
            icon.className = schema.icon || 'bi-file-text'
            icon.style.color = schema.color || '#6b7280'
            icon.style.width = '18px'
            icon.style.textAlign = 'center'
            item.appendChild(icon)

            const label = document.createElement('span')
            label.textContent = schema.name
            label.style.flex = '1'
            item.appendChild(label)

            if (schema.slash_alias) {
                const alias = document.createElement('span')
                alias.textContent = ';;' + schema.slash_alias
                alias.style.fontSize = '11px'
                alias.style.color = '#94a3b8'
                item.appendChild(alias)
            }

            item.addEventListener('mousedown', (e) => {
                e.preventDefault()
                this._select(schema)
            })
            this.popup.appendChild(item)
        })
    }

    _show(view, from) {
        // Position near the cursor
        const coords = view.coordsAtPos(from + 1)
        this.popup.style.display = 'block'
        this.popup.style.left = coords.left + 'px'
        this.popup.style.top = (coords.bottom + 4) + 'px'

        // Attach key listener
        this.editorView.dom.addEventListener('keydown', this._keyHandler, true)
    }

    _hide() {
        this.popup.style.display = 'none'
        this.selectedIndex = 0
        this.editorView.dom.removeEventListener('keydown', this._keyHandler, true)
    }

    _handleKey(e) {
        if (!this.items || this.items.length === 0) return

        if (e.key === 'ArrowDown') {
            e.preventDefault()
            this.selectedIndex = (this.selectedIndex + 1) % this.items.length
            this._renderItems()
        } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            this.selectedIndex = (this.selectedIndex - 1 + this.items.length) % this.items.length
            this._renderItems()
        } else if (e.key === 'Enter') {
            e.preventDefault()
            this._select(this.items[this.selectedIndex])
        } else if (e.key === 'Escape') {
            e.preventDefault()
            this._hide()
        }
    }

    _select(schema) {
        const state = slashKey.getState(this.editorView.state)
        if (!state) return

        // Replace the current paragraph with a structuredEntry
        const { from } = state
        const tr = this.editorView.state.tr
        const end = from + this.editorView.state.doc.nodeAt(from).nodeSize

        const entryNode = this.editorView.state.schema.nodes.structuredEntry.create({
            schemaCode: schema.code,
            schemaId: schema.id,
            fieldValues: {},
            collapsed: false,
        })

        tr.replaceWith(from, end, entryNode)
        this.editorView.dispatch(tr)
        this._hide()

        // Focus the new entry's content
        setTimeout(() => {
            this.editor.commands.focus()
        }, 50)
    }

    destroy() {
        this.editorView.dom.removeEventListener('keydown', this._keyHandler, true)
        if (this.popup.parentNode) {
            this.popup.parentNode.removeChild(this.popup)
        }
    }
}


export default SlashCommand
