/**
 * BeakCortex PdfThumbnail -- Tiptap node
 *
 * 表示 PDF 在 Tiptap 編輯器內的縮圖區塊：
 *   - block-level，atomic（contentEditable=false）
 *   - 顯示第一頁縮圖 + 檔名 + 開啟連結
 *   - 縮圖透過 window.PdfUtils.renderFirstPageThumbnail 動態產生
 *
 * Attributes:
 *   token       - uploaded_files.token，用來組 /beakcortex/files/<token>
 *   filename    - 顯示用檔名
 *   pages       - 頁數（已知時填入，純資訊用）
 */
import { Node, mergeAttributes } from '@tiptap/core'

export const PdfThumbnail = Node.create({
    name: 'pdfThumbnail',
    group: 'block',
    atom: true,
    selectable: true,
    draggable: true,

    addAttributes() {
        return {
            token: { default: '' },
            filename: { default: '' },
            pages: { default: null },
            thumbnailToken: { default: null },
        }
    },

    parseHTML() {
        return [{
            tag: 'div[data-pdf-thumbnail]',
            getAttrs(dom) {
                return {
                    token: dom.getAttribute('data-token') || '',
                    filename: dom.getAttribute('data-filename') || '',
                    pages: dom.getAttribute('data-pages') ? parseInt(dom.getAttribute('data-pages')) : null,
                    thumbnailToken: dom.getAttribute('data-thumb') || null,
                }
            },
        }]
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, {
            'data-pdf-thumbnail': '',
            'data-token': HTMLAttributes.token || '',
            'data-filename': HTMLAttributes.filename || '',
            'data-pages': HTMLAttributes.pages != null ? String(HTMLAttributes.pages) : '',
            'data-thumb': HTMLAttributes.thumbnailToken || '',
            'class': 'pdf-thumb-block',
        })]
    },

    addNodeView() {
        return ({ node }) => new PdfThumbnailView(node)
    },
})


class PdfThumbnailView {
    constructor(node) {
        this.node = node
        this.dom = document.createElement('div')
        this.dom.className = 'pdf-thumb-block'
        this.dom.contentEditable = 'false'

        this.imgWrap = document.createElement('div')
        this.imgWrap.className = 'pdf-thumb-img'

        const placeholder = document.createElement('div')
        placeholder.className = 'pdf-thumb-loading'
        placeholder.textContent = '載入 PDF 縮圖中...'
        this.imgWrap.appendChild(placeholder)

        this.dom.appendChild(this.imgWrap)

        const meta = document.createElement('div')
        meta.className = 'pdf-thumb-meta'
        const icon = document.createElement('span')
        icon.className = 'pdf-thumb-icon'
        icon.textContent = 'PDF'
        meta.appendChild(icon)

        const name = document.createElement('span')
        name.className = 'pdf-thumb-name'
        name.textContent = node.attrs.filename || '(未命名)'
        meta.appendChild(name)

        if (node.attrs.pages != null) {
            const pages = document.createElement('span')
            pages.className = 'pdf-thumb-pages'
            pages.textContent = node.attrs.pages + ' 頁'
            meta.appendChild(pages)
        }

        if (node.attrs.token) {
            const link = document.createElement('a')
            link.className = 'pdf-thumb-link'
            link.href = '/beakcortex/files/' + encodeURIComponent(node.attrs.token)
            link.target = '_blank'
            link.rel = 'noopener'
            link.textContent = '開啟'
            meta.appendChild(link)
        }

        this.dom.appendChild(meta)

        this._renderThumb()
    }

    async _renderThumb() {
        // 優先：已快取的縮圖（uploaded_files 內存的圖片 token）
        if (this.node.attrs.thumbnailToken) {
            this.imgWrap.innerHTML = ''
            const img = document.createElement('img')
            img.src = '/beakcortex/files/' + encodeURIComponent(this.node.attrs.thumbnailToken)
            img.alt = this.node.attrs.filename || ''
            img.draggable = false
            this.imgWrap.appendChild(img)
            return
        }
        // 退路：用 PDF.js 即時渲染（舊 PDF 沒上傳縮圖時）
        if (!this.node.attrs.token || !window.PdfUtils) return
        const url = '/beakcortex/files/' + encodeURIComponent(this.node.attrs.token)
        try {
            const dataUrl = await window.PdfUtils.renderFirstPageThumbnail(url, 360)
            this.imgWrap.innerHTML = ''
            const img = document.createElement('img')
            img.src = dataUrl
            img.alt = this.node.attrs.filename || ''
            img.draggable = false
            this.imgWrap.appendChild(img)
        } catch (e) {
            this.imgWrap.innerHTML = ''
            const err = document.createElement('div')
            err.className = 'pdf-thumb-error'
            err.textContent = 'PDF 縮圖載入失敗'
            this.imgWrap.appendChild(err)
        }
    }
}


export default PdfThumbnail
