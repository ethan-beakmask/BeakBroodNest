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
const MAX_CONVERT_LEN = 200

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
        this._delayTimer = null
        this._showDelayMs = 500

        // Toolbar container
        this.toolbar = document.createElement('div')
        this.toolbar.className = 'sel-toolbar'
        this.toolbar.style.display = 'none'
        // 阻止 mousedown 把編輯器 blur 掉 -- 否則 selection 被清，click 處理時 from/to 已失效
        this.toolbar.addEventListener('mousedown', (e) => { e.preventDefault() })

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

        // 連續色筆/螢光啟用時：完全不顯示（由 ce-pane 的 data-continuous 標記判斷）
        const paneEl = view.dom.closest('.ce-pane')
        if (paneEl && paneEl.dataset.continuous === '1') {
            this._hideAndCancel()
            return
        }

        if (empty || to - from < 2) {
            this._hideAndCancel()
            return
        }

        // Check if selection spans at least one full block
        const $from = state.doc.resolve(from)

        // Only show if we have block-level selection or multi-line
        const text = state.doc.textBetween(from, to, '\n')
        if (!text.includes('\n') && $from.parent.type.name === 'structuredEntry') {
            this._hideAndCancel()
            return
        }

        // 延後顯示：拖選 / selection 變動期間反覆 reset timer，
        // selection 穩定 500ms 後才實際顯示，避免拖選過程閃爍
        this._scheduleShow(view, from)
    }

    _hideAndCancel() {
        if (this._delayTimer) { clearTimeout(this._delayTimer); this._delayTimer = null }
        this.toolbar.style.display = 'none'
        this.dropdown.style.display = 'none'
    }

    _scheduleShow(view, from) {
        // 已顯示中 + selection 仍非空 → 只更新位置，不重啟 timer 也不暫時 hide
        // 這樣 toolbar 顯示後拖選微調或點 dropdown 觸發的 selection 變動不會把它打掉
        if (this.toolbar.style.display === 'flex') {
            const coords = view.coordsAtPos(from)
            this.toolbar.style.left = coords.left + 'px'
            this.toolbar.style.top = (coords.top - 36) + 'px'
            return
        }
        if (this._delayTimer) clearTimeout(this._delayTimer)
        this.toolbar.style.display = 'none'
        this.dropdown.style.display = 'none'
        this._delayTimer = setTimeout(() => {
            this._delayTimer = null
            const sel = view.state.selection
            if (sel.empty) return
            const coords = view.coordsAtPos(from)
            this.toolbar.style.display = 'flex'
            this.toolbar.style.left = coords.left + 'px'
            this.toolbar.style.top = (coords.top - 36) + 'px'
        }, this._showDelayMs)
    }

    _showSchemaMenu() {
        this.dropdown.innerHTML = ''

        // 長度上限：選取超過 MAX_CONVERT_LEN 字時拒絕轉換
        const { state } = this.editorView
        const { from, to } = state.selection
        const selText = state.doc.textBetween(from, to, '\n')
        if (selText.length > MAX_CONVERT_LEN) {
            const warn = document.createElement('div')
            warn.className = 'sel-toolbar-dropdown-item sel-toolbar-warn'
            warn.textContent = '選取過長（' + selText.length + ' 字），請精簡至 '
                + MAX_CONVERT_LEN + ' 字內再轉換'
            this.dropdown.appendChild(warn)
            this.dropdown.style.display = 'block'
            return
        }

        // file 必須由工具列上傳建立（依賴 file_token / mime / size），這條 Convert 路徑無法產生
        const schemas = (window._entrySchemas || []).filter(s => s.code !== 'freetext' && s.code !== 'file')

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
        // 不再加 pos >= from - 1 限制，否則「未從第一個字選起」的單行會被排除
        const blocks = []
        state.doc.nodesBetween(from, to, (node, pos) => {
            if (node.isBlock && node.isTextblock) {
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
        if (this._delayTimer) { clearTimeout(this._delayTimer); this._delayTimer = null }
        document.removeEventListener('mousedown', this._outsideHandler)
        if (this.toolbar.parentNode) {
            this.toolbar.parentNode.removeChild(this.toolbar)
        }
    }
}


export default SelectionToolbar
