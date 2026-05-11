/**
 * HtmlBlock -- 原生 HTML/SVG 退路區塊。
 *
 *   - 預覽區呈現經 DOMPurify 過濾後的結果 (Mermaid 不夠用時的兜底)
 *   - source 區永遠可編輯，blur 時寫回 node attrs
 *   - 序列化成 ```html fenced block，與 .md 匯出/匯入保持一致
 *   - 同樣 atomic + isolating，只能透過 [x] 按鈕刪除
 *   - DOMPurify 用 default profile (移除 <script>、event handler 等)
 */
import { Node, mergeAttributes } from '@tiptap/core'
import { NodeSelection } from '@tiptap/pm/state'
import DOMPurify from 'dompurify'
import { HTML_BLOCK_TEMPLATE } from './mermaid-templates.js'

function escapeHtmlForPre(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
}

function purify(html) {
    return DOMPurify.sanitize(String(html || ''), {
        USE_PROFILES: { html: true, svg: true, svgFilters: true },
        ADD_ATTR: ['target'],
    })
}

export const HtmlBlock = Node.create({
    name: 'htmlBlock',
    group: 'block',
    atom: true,
    selectable: true,
    draggable: true,
    isolating: true,

    addAttributes() {
        return {
            source: { default: '' },
        }
    },

    parseHTML() {
        return [{
            tag: 'pre[data-html-block]',
            preserveWhitespace: 'full',
            getAttrs: (dom) => ({ source: dom.textContent || '' }),
        }]
    },

    renderHTML({ node, HTMLAttributes }) {
        return ['pre', mergeAttributes(HTMLAttributes, {
            'data-html-block': '',
            'class': 'html-block-raw',
        }), node.attrs.source || '']
    },

    addNodeView() {
        return ({ node, getPos, editor }) => new HtmlBlockView(node, getPos, editor)
    },

    addStorage() {
        return {
            markdown: {
                serialize(state, node) {
                    state.write('```html\n')
                    state.text(node.attrs.source || '', false)
                    state.ensureNewLine()
                    state.write('```')
                    state.closeBlock(node)
                },
                parse: {
                    setup(md) {
                        const prev = md.renderer.rules.fence
                        md.renderer.rules.fence = function (tokens, idx, opts, env, slf) {
                            const t = tokens[idx]
                            const info = (t.info || '').trim().toLowerCase()
                            if (info === 'html') {
                                return '<pre data-html-block="">' + escapeHtmlForPre(t.content) + '</pre>'
                            }
                            if (typeof prev === 'function') return prev(tokens, idx, opts, env, slf)
                            return slf.renderToken(tokens, idx, opts)
                        }
                    },
                },
            },
        }
    },

    addKeyboardShortcuts() {
        return {
            Backspace: ({ editor }) => {
                const sel = editor.state.selection
                if (sel instanceof NodeSelection && sel.node.type.name === 'htmlBlock') return true
                return false
            },
            Delete: ({ editor }) => {
                const sel = editor.state.selection
                if (sel instanceof NodeSelection && sel.node.type.name === 'htmlBlock') return true
                return false
            },
        }
    },

    addCommands() {
        return {
            insertHtmlBlock: () => ({ commands }) => {
                return commands.insertContent({
                    type: 'htmlBlock',
                    attrs: { source: HTML_BLOCK_TEMPLATE },
                })
            },
        }
    },
})


class HtmlBlockView {
    constructor(node, getPos, editor) {
        this.node = node
        this.getPos = getPos
        this.editor = editor

        this.dom = document.createElement('div')
        this.dom.className = 'mermaid-block-wrap html-block-wrap'
        this.dom.contentEditable = 'false'
        this.dom.draggable = false

        const header = document.createElement('div')
        header.className = 'mermaid-block-header'
        const handle = document.createElement('span')
        handle.className = 'mermaid-block-drag-handle'
        handle.setAttribute('draggable', 'true')
        handle.setAttribute('data-drag-handle', '')
        handle.title = '拖曳搬移此區塊'
        handle.textContent = '☰'
        header.appendChild(handle)
        this.handle = handle

        this.dom.addEventListener('dragstart', (e) => {
            if (!this.handle.contains(e.target)) {
                e.preventDefault()
                e.stopPropagation()
            }
        }, true)
        const tag = document.createElement('span')
        tag.className = 'mermaid-block-tag'
        tag.textContent = 'HTML / SVG'
        header.appendChild(tag)
        const note = document.createElement('span')
        note.className = 'mermaid-block-note'
        note.textContent = '預覽經 DOMPurify 過濾'
        header.appendChild(note)
        const spacer = document.createElement('span')
        spacer.style.flex = '1'
        header.appendChild(spacer)
        const del = document.createElement('button')
        del.type = 'button'
        del.className = 'mermaid-block-x'
        del.title = '刪除此區塊'
        del.tabIndex = -1
        del.textContent = '[x]'
        del.addEventListener('mousedown', (e) => e.preventDefault())
        del.addEventListener('click', (e) => { e.preventDefault(); this._deleteSelf() })
        header.appendChild(del)
        this.dom.appendChild(header)

        this.preview = document.createElement('div')
        this.preview.className = 'mermaid-block-preview html-block-preview'
        this.dom.appendChild(this.preview)

        this.textarea = document.createElement('textarea')
        this.textarea.className = 'mermaid-block-source'
        this.textarea.spellcheck = false
        this.textarea.value = node.attrs.source || ''
        this._autosizeTextarea()
        ;['keydown', 'keyup', 'keypress', 'beforeinput', 'paste', 'copy', 'cut'].forEach(ev => {
            this.textarea.addEventListener(ev, (e) => e.stopPropagation())
        })
        this.textarea.addEventListener('input', () => {
            this._autosizeTextarea()
            this._scheduleRender()
        })
        this.textarea.addEventListener('blur', () => this._commitSource())
        this.dom.appendChild(this.textarea)

        this._renderPreview(this.textarea.value)
    }

    _autosizeTextarea() {
        const lines = (this.textarea.value || '').split('\n').length
        this.textarea.rows = Math.min(24, Math.max(4, lines + 1))
    }

    _scheduleRender() {
        if (this._renderTimer) clearTimeout(this._renderTimer)
        this._renderTimer = setTimeout(() => this._renderPreview(this.textarea.value), 350)
    }

    _renderPreview(src) {
        const text = (src || '').trim()
        if (!text) {
            this.preview.innerHTML = '<div class="mermaid-block-empty">(空白)</div>'
            return
        }
        try {
            this.preview.innerHTML = purify(text)
        } catch (err) {
            this.preview.innerHTML = ''
            const msg = document.createElement('div')
            msg.className = 'mermaid-block-error'
            msg.textContent = 'HTML 過濾失敗: ' + ((err && err.message) || String(err))
            this.preview.appendChild(msg)
        }
    }

    _commitSource() {
        if (typeof this.getPos !== 'function') return
        const pos = this.getPos()
        if (pos == null) return
        const val = this.textarea.value
        if (val === this.node.attrs.source) return
        const tr = this.editor.view.state.tr.setNodeMarkup(pos, undefined, {
            ...this.node.attrs,
            source: val,
        })
        this.editor.view.dispatch(tr)
    }

    _deleteSelf() {
        if (typeof this.getPos !== 'function') return
        const pos = this.getPos()
        if (pos == null) return
        const tr = this.editor.view.state.tr.delete(pos, pos + this.node.nodeSize)
        this.editor.view.dispatch(tr)
        this.editor.view.focus()
    }

    update(node) {
        if (node.type.name !== this.node.type.name) return false
        this.node = node
        const fresh = node.attrs.source || ''
        if (this.textarea.value !== fresh) {
            this.textarea.value = fresh
            this._autosizeTextarea()
            this._renderPreview(fresh)
        }
        return true
    }

    destroy() {
        if (this._renderTimer) clearTimeout(this._renderTimer)
    }

    stopEvent(event) {
        const t = event.target
        if (!t) return false
        return this.textarea.contains(t) || (t.tagName === 'BUTTON' && this.dom.contains(t))
    }

    ignoreMutation() { return true }
}

export default HtmlBlock
