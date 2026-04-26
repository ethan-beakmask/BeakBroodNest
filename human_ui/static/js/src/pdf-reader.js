/**
 * BeakCortex PdfReader -- Tiptap node
 *
 * 兩種 viewMode：
 *   reader    -- 完整 PDF.js 多頁 viewer，支援文字選取與矩形截圖
 *   thumbnail -- 等同 pdfThumbnail（向下相容/手動切換）
 *
 * Attributes:
 *   token, filename, pages, thumbnailToken, viewMode
 *
 * NodeView 實例會掛在 root DOM (`element._pdfReaderView`)，外層 mixin
 * 透過此參考觸發截圖模式或讀取選取資訊。
 */
import { Node, mergeAttributes } from '@tiptap/core'

const PDFJS_BASE = '/beakcortex/static/vendor/pdfjs/'
let _pdfjsPromise = null
async function _loadPdfjs() {
    if (_pdfjsPromise) return _pdfjsPromise
    _pdfjsPromise = (async () => {
        const mod = await import(PDFJS_BASE + 'pdf.min.mjs')
        mod.GlobalWorkerOptions.workerSrc = PDFJS_BASE + 'pdf.worker.min.mjs'
        return mod
    })()
    return _pdfjsPromise
}

export const PdfReader = Node.create({
    name: 'pdfReader',
    group: 'block',
    atom: true,
    selectable: true,
    draggable: false,

    addAttributes() {
        return {
            token: { default: '' },
            filename: { default: '' },
            pages: { default: null },
            thumbnailToken: { default: null },
            viewMode: { default: 'reader' },
        }
    },

    parseHTML() {
        return [{
            tag: 'div[data-pdf-reader]',
            getAttrs(dom) {
                return {
                    token: dom.getAttribute('data-token') || '',
                    filename: dom.getAttribute('data-filename') || '',
                    pages: dom.getAttribute('data-pages') ? parseInt(dom.getAttribute('data-pages')) : null,
                    thumbnailToken: dom.getAttribute('data-thumb') || null,
                    viewMode: dom.getAttribute('data-view-mode') || 'reader',
                }
            },
        }]
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, {
            'data-pdf-reader': '',
            'data-token': HTMLAttributes.token || '',
            'data-filename': HTMLAttributes.filename || '',
            'data-pages': HTMLAttributes.pages != null ? String(HTMLAttributes.pages) : '',
            'data-thumb': HTMLAttributes.thumbnailToken || '',
            'data-view-mode': HTMLAttributes.viewMode || 'reader',
            'class': 'pdf-reader-block',
        })]
    },

    addCommands() {
        return {
            setPdfReaderViewMode: (mode) => ({ tr, state, dispatch }) => {
                let touched = false
                state.doc.descendants((node, pos) => {
                    if (node.type.name !== 'pdfReader') return
                    if (node.attrs.viewMode === mode) return
                    tr.setNodeMarkup(pos, undefined, { ...node.attrs, viewMode: mode })
                    touched = true
                })
                if (touched && dispatch) dispatch(tr)
                return touched
            },
        }
    },

    addNodeView() {
        return ({ node, editor, getPos }) => new PdfReaderView(node, editor, getPos)
    },
})


class PdfReaderView {
    constructor(node, editor, getPos) {
        this.node = node
        this.editor = editor
        this.getPos = getPos
        this._doc = null
        this._pageRenderPromises = {}
        this._observer = null
        this._cropMode = false
        this._cropCallback = null

        this.dom = document.createElement('div')
        this.dom.className = 'pdf-reader-block'
        this.dom.contentEditable = 'false'
        this.dom.draggable = false
        this.dom._pdfReaderView = this
        // 攔截 native HTML5 drag：避免 user 在 canvas/text layer 上 mousedown 把整個 atom 拖走
        this.dom.addEventListener('dragstart', function(e) {
            e.preventDefault()
            e.stopPropagation()
        })

        this._render()
    }

    update(node) {
        if (node.type.name !== 'pdfReader') return false
        const prevMode = this.node.attrs.viewMode
        const prevToken = this.node.attrs.token
        this.node = node
        // Token 變化 (placeholder → 真正 token) 或 viewMode 切換 → 重畫
        if (prevToken !== node.attrs.token || prevMode !== node.attrs.viewMode) {
            this._teardown()
            this._render()
        }
        return true
    }

    /**
     * 告訴 ProseMirror 不要處理 NodeView 內部的 mouse / pointer / drag 事件，
     * 讓 native window.getSelection() 能在 text layer 上正常拖選文字。
     * mouseup 仍會冒泡到 ce-pane 的 listener，觸發擷取/謄寫流程。
     */
    stopEvent(event) {
        const t = event.type
        if (t.startsWith('mouse') || t.startsWith('pointer') ||
            t.startsWith('drag') || t === 'wheel' || t === 'click' ||
            t === 'dblclick' || t === 'contextmenu') {
            return true
        }
        return false
    }

    /** 不讓 PM 把 NodeView 子節點當 ProseMirror 子文件來監聽變更 */
    ignoreMutation() {
        return true
    }

    destroy() {
        this._teardown()
        this.dom._pdfReaderView = null
    }

    _teardown() {
        if (this._observer) { try { this._observer.disconnect() } catch (e) {} this._observer = null }
        if (this._doc) { try { this._doc.destroy() } catch (e) {} this._doc = null }
        this._pageRenderPromises = {}
        this.dom.innerHTML = ''
    }

    _render() {
        const mode = this.node.attrs.viewMode || 'reader'
        if (mode === 'thumbnail') this._renderThumbnail()
        else this._renderReader()
    }

    // ---------- thumbnail 模式 ----------
    _renderThumbnail() {
        this.dom.classList.add('pdf-reader-thumb-mode')
        this.dom.classList.remove('pdf-reader-reader-mode')

        const wrap = document.createElement('div')
        wrap.className = 'pdf-thumb-block'

        const imgWrap = document.createElement('div')
        imgWrap.className = 'pdf-thumb-img'
        const placeholder = document.createElement('div')
        placeholder.className = 'pdf-thumb-loading'
        placeholder.textContent = '載入 PDF 縮圖中...'
        imgWrap.appendChild(placeholder)
        wrap.appendChild(imgWrap)

        const meta = document.createElement('div')
        meta.className = 'pdf-thumb-meta'
        const icon = document.createElement('span')
        icon.className = 'pdf-thumb-icon'
        icon.textContent = 'PDF'
        meta.appendChild(icon)
        const name = document.createElement('span')
        name.className = 'pdf-thumb-name'
        name.textContent = this.node.attrs.filename || '(未命名)'
        meta.appendChild(name)
        if (this.node.attrs.pages != null) {
            const pages = document.createElement('span')
            pages.className = 'pdf-thumb-pages'
            pages.textContent = this.node.attrs.pages + ' 頁'
            meta.appendChild(pages)
        }
        if (this.node.attrs.token) {
            const link = document.createElement('a')
            link.className = 'pdf-thumb-link'
            link.href = '/beakcortex/files/' + encodeURIComponent(this.node.attrs.token)
            link.target = '_blank'
            link.rel = 'noopener'
            link.textContent = '開啟'
            meta.appendChild(link)
        }
        wrap.appendChild(meta)
        this.dom.appendChild(wrap)

        this._loadThumbImage(imgWrap)
    }

    async _loadThumbImage(imgWrap) {
        if (this.node.attrs.thumbnailToken) {
            imgWrap.innerHTML = ''
            const img = document.createElement('img')
            img.src = '/beakcortex/files/' + encodeURIComponent(this.node.attrs.thumbnailToken)
            img.alt = this.node.attrs.filename || ''
            img.draggable = false
            imgWrap.appendChild(img)
            return
        }
        if (!this.node.attrs.token || !window.PdfUtils) return
        try {
            const url = '/beakcortex/files/' + encodeURIComponent(this.node.attrs.token)
            const dataUrl = await window.PdfUtils.renderFirstPageThumbnail(url, 360)
            imgWrap.innerHTML = ''
            const img = document.createElement('img')
            img.src = dataUrl
            img.alt = this.node.attrs.filename || ''
            img.draggable = false
            imgWrap.appendChild(img)
        } catch (e) {
            imgWrap.innerHTML = ''
            const err = document.createElement('div')
            err.className = 'pdf-thumb-error'
            err.textContent = 'PDF 縮圖載入失敗'
            imgWrap.appendChild(err)
        }
    }

    // ---------- reader 模式 ----------
    _renderReader() {
        this.dom.classList.add('pdf-reader-reader-mode')
        this.dom.classList.remove('pdf-reader-thumb-mode')

        // header（檔名 + 頁數 + 開啟連結）
        const header = document.createElement('div')
        header.className = 'pdf-reader-header'
        const icon = document.createElement('span')
        icon.className = 'pdf-thumb-icon'
        icon.textContent = 'PDF'
        header.appendChild(icon)
        const name = document.createElement('span')
        name.className = 'pdf-reader-name'
        name.textContent = this.node.attrs.filename || '(未命名)'
        header.appendChild(name)
        if (this.node.attrs.pages != null) {
            const pages = document.createElement('span')
            pages.className = 'pdf-reader-pages-count'
            pages.textContent = this.node.attrs.pages + ' 頁'
            header.appendChild(pages)
        }
        if (this.node.attrs.token) {
            const link = document.createElement('a')
            link.className = 'pdf-thumb-link'
            link.href = '/beakcortex/files/' + encodeURIComponent(this.node.attrs.token)
            link.target = '_blank'
            link.rel = 'noopener'
            link.textContent = '開啟'
            header.appendChild(link)
        }
        this.dom.appendChild(header)

        // pages 滾動容器 + crop overlay
        const pagesWrap = document.createElement('div')
        pagesWrap.className = 'pdf-reader-pages-wrap'
        const pagesContainer = document.createElement('div')
        pagesContainer.className = 'pdf-reader-pages'
        pagesWrap.appendChild(pagesContainer)
        const overlay = document.createElement('div')
        overlay.className = 'pdf-reader-crop-overlay'
        pagesWrap.appendChild(overlay)
        this.dom.appendChild(pagesWrap)

        if (!this.node.attrs.token) {
            const note = document.createElement('div')
            note.className = 'pdf-reader-note'
            note.textContent = '上傳中...'
            pagesContainer.appendChild(note)
            return
        }

        this._loadDocument(pagesContainer)
    }

    async _loadDocument(pagesContainer) {
        try {
            const pdfjs = await _loadPdfjs()
            const url = '/beakcortex/files/' + encodeURIComponent(this.node.attrs.token)
            const task = pdfjs.getDocument({ url })
            this._doc = await task.promise
            const pageCount = Math.min(this._doc.numPages, 500)
            for (let i = 1; i <= pageCount; i++) {
                const pageEl = document.createElement('div')
                pageEl.className = 'pdf-reader-page'
                pageEl.dataset.pageNum = String(i)
                pageEl.dataset.rendered = '0'
                const placeholder = document.createElement('div')
                placeholder.className = 'pdf-reader-page-placeholder'
                placeholder.textContent = '第 ' + i + ' 頁'
                pageEl.appendChild(placeholder)
                pagesContainer.appendChild(pageEl)
            }
            this._observer = new IntersectionObserver((entries) => {
                for (const ent of entries) {
                    const el = ent.target
                    if (ent.isIntersecting && el.dataset.rendered === '0') {
                        const num = parseInt(el.dataset.pageNum)
                        this._renderPage(num, el)
                    }
                }
            }, { root: pagesContainer, rootMargin: '300px 0px' })
            pagesContainer.querySelectorAll('.pdf-reader-page').forEach(el => this._observer.observe(el))
        } catch (e) {
            console.error('PDF reader load failed:', e)
            const err = document.createElement('div')
            err.className = 'pdf-thumb-error'
            err.textContent = 'PDF 載入失敗：' + (e.message || e)
            pagesContainer.appendChild(err)
        }
    }

    async _renderPage(num, host) {
        if (host.dataset.rendered !== '0') return
        host.dataset.rendered = '1'
        if (this._pageRenderPromises[num]) return this._pageRenderPromises[num]
        this._pageRenderPromises[num] = (async () => {
            try {
                const pdfjs = await _loadPdfjs()
                const page = await this._doc.getPage(num)
                const dpr = window.devicePixelRatio || 1
                const containerWidth = (host.parentElement && host.parentElement.clientWidth) || 800
                const targetWidth = Math.max(320, containerWidth - 24)
                const viewport0 = page.getViewport({ scale: 1.0 })
                const scale = targetWidth / viewport0.width
                const viewport = page.getViewport({ scale })

                const cssW = Math.floor(viewport.width)
                const cssH = Math.floor(viewport.height)

                host.style.width = cssW + 'px'
                host.style.height = cssH + 'px'
                host.innerHTML = ''

                const canvas = document.createElement('canvas')
                canvas.className = 'pdf-reader-canvas'
                canvas.draggable = false
                canvas.width = Math.floor(cssW * dpr)
                canvas.height = Math.floor(cssH * dpr)
                canvas.style.width = cssW + 'px'
                canvas.style.height = cssH + 'px'
                host.appendChild(canvas)

                const ctx = canvas.getContext('2d')
                const renderViewport = page.getViewport({ scale: scale * dpr })
                await page.render({ canvasContext: ctx, viewport: renderViewport, canvas }).promise

                const textDiv = document.createElement('div')
                textDiv.className = 'pdf-reader-text-layer textLayer'
                textDiv.style.setProperty('--scale-factor', String(scale))
                textDiv.style.width = cssW + 'px'
                textDiv.style.height = cssH + 'px'
                host.appendChild(textDiv)

                try {
                    const textLayer = new pdfjs.TextLayer({
                        textContentSource: page.streamTextContent({ disableNormalization: true }),
                        container: textDiv,
                        viewport,
                    })
                    await textLayer.render()
                } catch (txtErr) {
                    // text layer 失敗不影響主渲染
                    console.warn('text layer render failed page=' + num, txtErr)
                }
            } catch (err) {
                console.error('render page ' + num + ' failed:', err)
                host.dataset.rendered = '0'
                host.innerHTML = ''
                const e = document.createElement('div')
                e.className = 'pdf-thumb-error'
                e.textContent = '第 ' + num + ' 頁載入失敗'
                host.appendChild(e)
            }
        })()
        return this._pageRenderPromises[num]
    }

    // ---------- 對外 API：給 mixin 用 ----------

    getSelectedText() {
        const sel = window.getSelection ? window.getSelection() : null
        if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return ''
        // 確認 selection anchor/focus 都在這個 reader 內
        const range = sel.getRangeAt(0)
        if (!this.dom.contains(range.startContainer) || !this.dom.contains(range.endContainer)) return ''
        return sel.toString()
    }

    enterCropMode(callback) {
        if (this.node.attrs.viewMode !== 'reader') return false
        this._cropMode = true
        this._cropCallback = callback || null
        const overlay = this.dom.querySelector('.pdf-reader-crop-overlay')
        if (!overlay) return false
        overlay.classList.add('active')
        this.dom.classList.add('pdf-cropping')
        this._installCropHandlers(overlay)
        return true
    }

    exitCropMode() {
        this._cropMode = false
        const overlay = this.dom.querySelector('.pdf-reader-crop-overlay')
        if (overlay) {
            overlay.classList.remove('active')
            overlay.onmousedown = null
            const rects = overlay.querySelectorAll('.pdf-crop-rect')
            rects.forEach(r => r.remove())
        }
        this.dom.classList.remove('pdf-cropping')
    }

    _installCropHandlers(overlay) {
        const self = this
        overlay.onmousedown = function(e) {
            if (!self._cropMode) return
            e.preventDefault()
            e.stopPropagation()
            const ovRect = overlay.getBoundingClientRect()
            // 起點以 viewport 座標計算 (clientX/Y)，避免 overlay 滾動內容時相對座標偏移
            const startCx = e.clientX
            const startCy = e.clientY
            const rectEl = document.createElement('div')
            rectEl.className = 'pdf-crop-rect'
            // 起點以 overlay client coord（不滾動的視窗內）
            rectEl.style.position = 'fixed'
            rectEl.style.left = startCx + 'px'
            rectEl.style.top = startCy + 'px'
            rectEl.style.width = '0px'
            rectEl.style.height = '0px'
            document.body.appendChild(rectEl)

            function onMove(ev) {
                const x = ev.clientX, y = ev.clientY
                const left = Math.min(x, startCx), top = Math.min(y, startCy)
                rectEl.style.left = left + 'px'
                rectEl.style.top = top + 'px'
                rectEl.style.width = Math.abs(x - startCx) + 'px'
                rectEl.style.height = Math.abs(y - startCy) + 'px'
            }
            function onUp(ev) {
                document.removeEventListener('mousemove', onMove)
                document.removeEventListener('mouseup', onUp)
                const x = ev.clientX, y = ev.clientY
                const left = Math.min(x, startCx), top = Math.min(y, startCy)
                const w = Math.abs(x - startCx), h = Math.abs(y - startCy)
                if (rectEl.parentNode) rectEl.parentNode.removeChild(rectEl)
                self.exitCropMode()
                if (w < 5 || h < 5) {
                    if (self._cropCallback) self._cropCallback(null, null, '取消')
                    return
                }
                self._performCrop(left, top, w, h)
            }
            document.addEventListener('mousemove', onMove)
            document.addEventListener('mouseup', onUp)
        }
    }

    async _performCrop(absLeft, absTop, w, h) {
        // absLeft/absTop 為視窗座標 (clientX/Y)
        const pages = Array.from(this.dom.querySelectorAll('.pdf-reader-page'))
        let bestPage = null
        let bestOverlap = 0
        for (const p of pages) {
            const r = p.getBoundingClientRect()
            const ix = Math.max(0, Math.min(absLeft + w, r.right) - Math.max(absLeft, r.left))
            const iy = Math.max(0, Math.min(absTop + h, r.bottom) - Math.max(absTop, r.top))
            const ov = ix * iy
            if (ov > bestOverlap) { bestOverlap = ov; bestPage = p }
        }
        if (!bestPage) {
            if (this._cropCallback) this._cropCallback(null, null, '無命中頁面')
            return
        }
        const canvas = bestPage.querySelector('canvas.pdf-reader-canvas')
        if (!canvas) {
            if (this._cropCallback) this._cropCallback(null, null, '頁面尚未渲染完成')
            return
        }
        const cRect = canvas.getBoundingClientRect()
        const sx = Math.max(0, absLeft - cRect.left)
        const sy = Math.max(0, absTop - cRect.top)
        const sxEnd = Math.min(cRect.width, absLeft + w - cRect.left)
        const syEnd = Math.min(cRect.height, absTop + h - cRect.top)
        const sw = sxEnd - sx
        const sh = syEnd - sy
        if (sw < 2 || sh < 2) {
            if (this._cropCallback) this._cropCallback(null, null, '裁切範圍過小')
            return
        }
        const scaleX = canvas.width / cRect.width
        const scaleY = canvas.height / cRect.height

        const out = document.createElement('canvas')
        out.width = Math.round(sw * scaleX)
        out.height = Math.round(sh * scaleY)
        const ctx = out.getContext('2d')
        ctx.drawImage(canvas, sx * scaleX, sy * scaleY, sw * scaleX, sh * scaleY,
                      0, 0, out.width, out.height)
        const dataUrl = out.toDataURL('image/png')
        const pageNum = parseInt(bestPage.dataset.pageNum)
        if (this._cropCallback) this._cropCallback(dataUrl, pageNum, null)
    }
}


export default PdfReader
