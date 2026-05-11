/**
 * MermaidBlock -- 在卡片編輯器內以 atomic block 呈現的 Mermaid 圖形。
 *
 * 設計重點:
 *   - atom + isolating: 不可被 PM caret 進入，鍵盤刪除被吃掉，只能透過 [x] 按鈕刪除
 *   - NodeView 直接同時呈現「source textarea」與「即時預覽」(stacked)
 *   - tiptap-markdown 序列化為 ```mermaid fenced block，parse 時用 fence renderer 攔截
 *   - Mermaid securityLevel: 'strict' (防止知識庫內容注入 HTML)
 */
import { Node, mergeAttributes } from '@tiptap/core'
import { NodeSelection } from '@tiptap/pm/state'
// 必須走 esm.min 全量入口；core.mjs 內部用 await import() 動態載入各圖型，
// 在 IIFE bundle 下 dynamic import 失效，render() 會靜默失敗。
import mermaid from 'mermaid/dist/mermaid.esm.min.mjs'
import { MERMAID_TEMPLATES } from './mermaid-templates.js'

let _mermaidInitialised = false
function ensureMermaidInit() {
    if (_mermaidInitialised) return
    try {
        mermaid.initialize({
            startOnLoad: false,
            securityLevel: 'strict',
            theme: 'default',
            flowchart: { useMaxWidth: true, htmlLabels: false },
            sequence: { useMaxWidth: true },
        })
    } catch (_) { /* ignore double-init */ }
    _mermaidInitialised = true
}

function escapeHtmlForPre(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
}

export const MermaidBlock = Node.create({
    name: 'mermaidBlock',
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
            tag: 'pre[data-mermaid]',
            preserveWhitespace: 'full',
            getAttrs: (dom) => ({ source: dom.textContent || '' }),
        }]
    },

    renderHTML({ node, HTMLAttributes }) {
        return ['pre', mergeAttributes(HTMLAttributes, {
            'data-mermaid': '',
            'class': 'mermaid-block-raw',
        }), node.attrs.source || '']
    },

    addNodeView() {
        return ({ node, getPos, editor }) => new MermaidBlockView(node, getPos, editor)
    },

    addStorage() {
        return {
            markdown: {
                serialize(state, node) {
                    state.write('```mermaid\n')
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
                            if (info === 'mermaid') {
                                return '<pre data-mermaid="">' + escapeHtmlForPre(t.content) + '</pre>'
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
            // NodeSelection 對 mermaidBlock -> 吃掉 (只能由 [x] 刪除)
            Backspace: ({ editor }) => {
                const sel = editor.state.selection
                if (sel instanceof NodeSelection && sel.node.type.name === 'mermaidBlock') return true
                return false
            },
            Delete: ({ editor }) => {
                const sel = editor.state.selection
                if (sel instanceof NodeSelection && sel.node.type.name === 'mermaidBlock') return true
                return false
            },
        }
    },

    addCommands() {
        return {
            insertMermaid: (kind) => ({ commands }) => {
                const src = MERMAID_TEMPLATES[kind] || MERMAID_TEMPLATES.flowchart
                return commands.insertContent({
                    type: 'mermaidBlock',
                    attrs: { source: src },
                })
            },
        }
    },
})


class MermaidBlockView {
    constructor(node, getPos, editor) {
        this.node = node
        this.getPos = getPos
        this.editor = editor
        ensureMermaidInit()

        this.dom = document.createElement('div')
        this.dom.className = 'mermaid-block-wrap'
        this.dom.contentEditable = 'false'
        // 整塊不可拖；只在 header 的 drag handle 可拖
        this.dom.draggable = false

        // header
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

        // 鎖死非 handle 的拖曳:
        //   textarea 在「選取文字後再拖」會觸發 dragstart (文字拖放),
        //   PM 收到後沿 DOM 往上找到本 NodeView (Node spec draggable:true) 就把
        //   整個圖塊當拖曳目標。攔在 capture 階段並 preventDefault 即可斷掉。
        this.dom.addEventListener('dragstart', (e) => {
            if (!this.handle.contains(e.target)) {
                e.preventDefault()
                e.stopPropagation()
            }
        }, true)
        const tag = document.createElement('span')
        tag.className = 'mermaid-block-tag'
        tag.textContent = 'Mermaid'
        header.appendChild(tag)
        const spacer = document.createElement('span')
        spacer.style.flex = '1'
        header.appendChild(spacer)
        const del = document.createElement('button')
        del.type = 'button'
        del.className = 'mermaid-block-x'
        del.title = '刪除此圖形'
        del.tabIndex = -1
        del.textContent = '[x]'
        del.addEventListener('mousedown', (e) => e.preventDefault())
        del.addEventListener('click', (e) => { e.preventDefault(); this._deleteSelf() })
        header.appendChild(del)
        this.dom.appendChild(header)

        // preview area
        this.preview = document.createElement('div')
        this.preview.className = 'mermaid-block-preview'
        this.dom.appendChild(this.preview)

        // source textarea
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
        this._renderTimer = setTimeout(() => this._renderPreview(this.textarea.value), 400)
    }

    async _renderPreview(src) {
        const text = (src || '').trim()
        if (!text) {
            this.preview.innerHTML = ''
            const empty = document.createElement('div')
            empty.className = 'mermaid-block-empty'
            empty.textContent = '(空白圖形)'
            this.preview.appendChild(empty)
            return
        }
        const renderId = 'mermaid-' + Math.random().toString(36).slice(2, 10)
        try {
            const result = await mermaid.render(renderId, text)
            this.preview.innerHTML = result && result.svg ? result.svg : ''
        } catch (err) {
            this.preview.innerHTML = ''
            const msg = document.createElement('div')
            msg.className = 'mermaid-block-error'
            const head = document.createElement('strong')
            head.textContent = 'Mermaid 渲染失敗'
            msg.appendChild(head)
            const detail = document.createElement('pre')
            detail.textContent = (err && err.message) ? err.message : String(err)
            msg.appendChild(detail)
            this.preview.appendChild(msg)
        }
        // 注意：不要在這裡 getElementById(renderId) 然後 removeChild --
        // mermaid 產生的 SVG 本身的 id 就是 renderId，剛 innerHTML 進去的 SVG
        // 會被當成 orphan 清掉。mermaid 11 內部會自行清理 body 上的臨時容器。
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

    // 讓 textarea / 按鈕內的事件不要被 PM 視為 PM 事件
    stopEvent(event) {
        const t = event.target
        if (!t) return false
        return this.textarea.contains(t) || (t.tagName === 'BUTTON' && this.dom.contains(t))
    }

    ignoreMutation() { return true }
}

export default MermaidBlock
