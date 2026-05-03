/**
 * BeakBroodNest Slash Command -- Tiptap Extension
 *
 * 在行首輸入 ;; 時觸發下拉選單，列出所有 entry schemas。
 * 選擇後將當前行（paragraph）轉為 structuredEntry node。
 *
 * 依賴 window._entrySchemas（由 whiteboard-card-editor.js 設定）。
 */
import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { openEntryModal } from './entry-modal.js'

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

        // file 必須由工具列上傳建立，這條 ;; 路徑無法產生有效的 file entry
        const schemas = (window._entrySchemas || []).filter(s => s.code !== 'freetext' && s.code !== 'file')

        // 虛擬別名：;;cal 建立 task entry（calendar 已合併入 task）
        const taskSchema = schemas.find(s => s.code === 'task')
        if (taskSchema && !schemas.find(s => s._virtualAlias === 'cal')) {
            schemas.push({
                ...taskSchema,
                name: '行事曆',
                icon: 'bi-calendar-event',
                color: '#f97316',
                slash_alias: 'cal',
                _virtualAlias: 'cal',
            })
        }

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
        // Position near the cursor; 如下方空間不夠則翻到游標上方
        const coords = view.coordsAtPos(from + 1)
        this.popup.style.display = 'block'
        this.popup.style.left = coords.left + 'px'
        // 先暫時放下方以量測高度
        this.popup.style.top = (coords.bottom + 4) + 'px'
        const popupH = this.popup.offsetHeight
        const viewportH = window.innerHeight
        if (coords.bottom + 4 + popupH > viewportH) {
            // 翻到上方
            this.popup.style.top = Math.max(4, coords.top - popupH - 4) + 'px'
        }

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

        const { from } = state
        const view = this.editorView
        const paragraph = view.state.doc.nodeAt(from)
        if (!paragraph) { this._hide(); return }
        const end = from + paragraph.nodeSize

        this._hide()

        // Z 階段:選 schema 後不立刻插 entry,先開 modal,confirm 才寫進文件;cancel 清掉 ;;XXX。
        openEntryModal({
            schema,
            schemaCode: schema.code,
            rawText: '',
            fieldValues: {},
            mode: 'create',
            focusField: 'subject',
            onSave: ({ rawText, fieldValues }) => {
                this._commitNew(schema, from, end, rawText, fieldValues)
            },
            onCancel: () => {
                this._discardSlashText(from, end)
            },
        })
    }

    // 把當前 ;;XXX 所在 paragraph 替換成填好內容的 structuredEntry。
    // 若 replaceWith 被 schema 拒絕(table cell 等容器型態),fallback 走 deleteRange + insertContentAt。
    _commitNew(schema, from, end, rawText, fieldValues) {
        const view = this.editorView
        const code = schema.code
        const fv = { ...(fieldValues || {}) }
        // idcard 主旨從 modal 的 rawText 進 fieldValues.line1
        if (code === 'idcard') {
            fv.line1 = rawText || fv.line1 || ''
        }
        // idcard 設為 primary 時,清除其他 idcard 的 primary
        let primaryNeedsClear = false
        if (code === 'idcard' && (fv.is_primary === 'true' || fv.is_primary === true)) {
            primaryNeedsClear = true
        }
        const inlineText = code === 'idcard' ? '' : (rawText || '')
        const entryAttrs = {
            schemaCode: code,
            schemaId: schema.id,
            fieldValues: fv,
            collapsed: true,
        }
        // 重新檢查 from/end 仍合法(modal 期間 doc 未變;如果變了走 fallback)
        let curEnd = end
        try {
            const para = view.state.doc.nodeAt(from)
            if (para && para.type.name === 'paragraph') {
                curEnd = from + para.nodeSize
            }
        } catch (_) { /* ignore */ }

        const entryNode = view.state.schema.nodes.structuredEntry.create(
            entryAttrs,
            inlineText ? [view.state.schema.text(inlineText)] : []
        )

        let dispatched = false
        try {
            const tr = view.state.tr
            if (primaryNeedsClear) {
                view.state.doc.descendants((n, p) => {
                    if (n.type.name !== 'structuredEntry') return
                    if ((n.attrs.schemaCode || '') !== 'idcard') return
                    const ofv = n.attrs.fieldValues || {}
                    if (ofv.is_primary === 'true' || ofv.is_primary === true) {
                        tr.setNodeMarkup(p, undefined, {
                            ...n.attrs,
                            fieldValues: { ...ofv, is_primary: 'false' },
                        })
                    }
                })
            }
            const mappedFrom = tr.mapping.map(from)
            const mappedEnd = tr.mapping.map(curEnd)
            tr.replaceWith(mappedFrom, mappedEnd, entryNode)
            if (tr.docChanged) {
                view.dispatch(tr)
                dispatched = true
            }
        } catch (e) {
            console.warn('[slashCommand] replaceWith failed, fallback', e)
        }

        if (!dispatched) {
            this.editor.chain()
                .focus()
                .deleteRange({ from, to: curEnd })
                .insertContentAt(from, {
                    type: 'structuredEntry',
                    attrs: entryAttrs,
                    content: inlineText ? [{ type: 'text', text: inlineText }] : [],
                })
                .run()
        }

        setTimeout(() => this.editor.commands.focus(), 30)
    }

    // 取消:清掉 ;;XXX 文字,留下空 paragraph;caret 留在原位,可繼續打字。
    _discardSlashText(from, end) {
        const view = this.editorView
        try {
            const para = view.state.doc.nodeAt(from)
            if (para && para.type.name === 'paragraph' && para.textContent.startsWith(';;')) {
                const tr = view.state.tr
                tr.delete(from + 1, from + 1 + para.content.size)
                view.dispatch(tr)
            }
            this.editor.commands.focus()
        } catch (_) { /* ignore */ }
    }

    destroy() {
        this.editorView.dom.removeEventListener('keydown', this._keyHandler, true)
        if (this.popup.parentNode) {
            this.popup.parentNode.removeChild(this.popup)
        }
    }
}


export default SlashCommand
