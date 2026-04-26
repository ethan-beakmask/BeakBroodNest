/**
 * BeakCortex ResizableImage -- Tiptap Image 擴充
 *
 * 在 @tiptap/extension-image 之上加入：
 *   - width attr（CSS 字串如 "320px"），存入 content_json
 *   - thumbnail attr（boolean），標記此圖為卡片在白板上的縮圖
 *   - NodeView：右下角拖拉把手 + 右上角「★/☆」切換縮圖按鈕（hover 才顯示）
 *
 * Markdown 序列化會丟失 width/thumbnail（標準語法不支援），但 content_json 仍為真實來源。
 * thumbnail 切換為單選：點擊後其他 image 的 thumbnail attr 會自動清掉。
 */
import { Image } from '@tiptap/extension-image'

const MIN_WIDTH = 40   // 像素，避免拖到不見

export const ResizableImage = Image.extend({
    name: 'image',

    addAttributes() {
        const parent = this.parent ? this.parent() : {}
        return {
            ...parent,
            width: {
                default: null,
                parseHTML: el => {
                    const w = el.getAttribute('width')
                    if (w) return /^\d+$/.test(w) ? w + 'px' : w
                    const sw = el.style && el.style.width
                    return sw || null
                },
                renderHTML: attrs => {
                    if (!attrs.width) return {}
                    return { style: 'width:' + attrs.width }
                },
            },
            thumbnail: {
                default: false,
                parseHTML: el => el.getAttribute('data-thumbnail') === '1',
                renderHTML: attrs => attrs.thumbnail ? { 'data-thumbnail': '1' } : {},
            },
        }
    },

    addNodeView() {
        return ({ node, getPos, editor }) => new ResizableImageView(node, getPos, editor)
    },
})


class ResizableImageView {
    constructor(node, getPos, editor) {
        this.node = node
        this.getPos = getPos
        this.editor = editor

        // 包裝層：使用 inline-block 維持 inline 圖片排版
        this.dom = document.createElement('span')
        this.dom.className = 'tt-img-wrap'
        this.dom.style.display = 'inline-block'
        this.dom.style.position = 'relative'
        this.dom.style.lineHeight = '0'  // 避免下方文字基線造成空白

        this.img = document.createElement('img')
        this.img.draggable = false
        this._applyAttrs(node)
        this.dom.appendChild(this.img)

        this.handle = document.createElement('span')
        this.handle.className = 'tt-img-handle'
        this.handle.contentEditable = 'false'
        this.handle.title = '拖拉縮放（等比例）'
        this.handle.addEventListener('mousedown', this._onHandleDown.bind(this))
        this.dom.appendChild(this.handle)

        // 右上角「★/☆」切換縮圖按鈕（hover 顯示）
        this.thumbBtn = document.createElement('span')
        this.thumbBtn.className = 'tt-img-thumb-btn'
        this.thumbBtn.contentEditable = 'false'
        this._updateThumbBtn(node)
        this.thumbBtn.addEventListener('mousedown', e => {
            e.preventDefault()
            e.stopPropagation()
        })
        this.thumbBtn.addEventListener('click', e => {
            e.preventDefault()
            e.stopPropagation()
            this._toggleThumbnail()
        })
        this.dom.appendChild(this.thumbBtn)
    }

    _applyAttrs(node) {
        if (node.attrs.src && this.img.getAttribute('src') !== node.attrs.src) {
            this.img.src = node.attrs.src
        }
        if (node.attrs.alt) this.img.alt = node.attrs.alt
        else this.img.removeAttribute('alt')
        if (node.attrs.title) this.img.title = node.attrs.title
        else this.img.removeAttribute('title')
        if (node.attrs.width) {
            this.img.style.width = node.attrs.width
        } else {
            this.img.style.removeProperty('width')
        }
        if (node.attrs.thumbnail) this.dom.classList.add('tt-img-is-thumbnail')
        else this.dom.classList.remove('tt-img-is-thumbnail')
    }

    _updateThumbBtn(node) {
        if (!this.thumbBtn) return
        if (node.attrs.thumbnail) {
            this.thumbBtn.textContent = '\u2605'
            this.thumbBtn.title = '取消設為卡片縮圖'
            this.thumbBtn.classList.add('on')
        } else {
            this.thumbBtn.textContent = '\u2606'
            this.thumbBtn.title = '設為卡片縮圖'
            this.thumbBtn.classList.remove('on')
        }
    }

    // 點擊「★」：toggle 此圖 thumbnail。為了維持單選，先把全 doc 其他 image
    // 的 thumbnail attr 都清掉，再切換目前這張。
    _toggleThumbnail() {
        if (this.editor && !this.editor.isEditable) return
        const view = this.editor.view
        const state = view.state
        const tr = state.tr
        const myPos = typeof this.getPos === 'function' ? this.getPos() : null
        if (myPos == null) return
        const willTurnOn = !this.node.attrs.thumbnail
        // 掃 doc 把其他 image 的 thumbnail 清掉
        state.doc.descendants((node, pos) => {
            if (node.type.name !== 'image') return
            if (pos === myPos) return
            if (node.attrs.thumbnail) {
                tr.setNodeMarkup(pos, undefined, { ...node.attrs, thumbnail: false })
            }
        })
        // 切換自己
        tr.setNodeMarkup(myPos, undefined, { ...this.node.attrs, thumbnail: willTurnOn })
        view.dispatch(tr)
    }

    _onHandleDown(e) {
        if (this.editor && !this.editor.isEditable) return
        e.preventDefault()
        e.stopPropagation()
        const startX = e.clientX
        const rect = this.img.getBoundingClientRect()
        const startWidth = rect.width
        const ratio = (this.img.naturalWidth && this.img.naturalHeight)
            ? this.img.naturalHeight / this.img.naturalWidth
            : (rect.height / rect.width || 1)

        document.body.style.cursor = 'nwse-resize'
        document.body.style.userSelect = 'none'

        const onMove = (ev) => {
            const dx = ev.clientX - startX
            const newWidth = Math.max(MIN_WIDTH, Math.round(startWidth + dx))
            this.img.style.width = newWidth + 'px'
            // 標記預估高度，僅供視覺，不影響 attr
            this.img.style.height = Math.round(newWidth * ratio) + 'px'
        }
        const onUp = () => {
            document.removeEventListener('mousemove', onMove)
            document.removeEventListener('mouseup', onUp)
            document.body.style.cursor = ''
            document.body.style.userSelect = ''
            // 清除暫時的 inline height（保留 auto，靠瀏覽器算）
            this.img.style.removeProperty('height')
            const finalWidth = this.img.style.width
            const pos = typeof this.getPos === 'function' ? this.getPos() : null
            if (pos == null || !finalWidth) return
            this.editor.view.dispatch(
                this.editor.view.state.tr.setNodeMarkup(pos, undefined, {
                    ...this.node.attrs,
                    width: finalWidth,
                })
            )
        }
        document.addEventListener('mousemove', onMove)
        document.addEventListener('mouseup', onUp)
    }

    update(node) {
        if (node.type.name !== this.node.type.name) return false
        this.node = node
        this._applyAttrs(node)
        this._updateThumbBtn(node)
        return true
    }

    selectNode() { this.dom.classList.add('tt-img-selected') }
    deselectNode() { this.dom.classList.remove('tt-img-selected') }

    ignoreMutation() {
        // 自行管理 DOM，避免 ProseMirror 把樣式變更當成內容變動
        return true
    }

    destroy() { /* listeners 都掛 document，會在 onUp 時清掉 */ }
}


export default ResizableImage
