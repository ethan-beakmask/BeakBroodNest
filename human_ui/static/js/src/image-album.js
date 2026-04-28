/**
 * BeakCortex Image Album Picker
 *
 * 提供「圖檔相簿」modal：
 *   - 列出已上傳 image kind 檔案（GET /api/files?kind=image）
 *   - 拖拉檔案進來批次上傳（POST /api/files/upload）
 *   - 點縮圖選定 → callback(token, url)
 *
 * 用法：
 *   import { openImageAlbumPicker } from './image-album.js'
 *   openImageAlbumPicker({ currentToken, onSelect: (token, url) => {...} })
 */

const ALLOWED_IMAGE_MIMES = new Set([
    'image/jpeg', 'image/png', 'image/webp', 'image/gif',
    'image/svg+xml', 'image/bmp', 'image/x-icon',
])

let _activePicker = null  // 同時間只允許一個 picker，避免疊加

export function openImageAlbumPicker(opts) {
    if (_activePicker) {
        _activePicker.close()
    }
    _activePicker = new ImageAlbumPicker(opts || {})
    _activePicker.open()
    return _activePicker
}

class ImageAlbumPicker {
    constructor({ currentToken = null, onSelect = null, title = '圖檔相簿' } = {}) {
        this.currentToken = currentToken
        this.onSelect = onSelect
        this.titleText = title
        this.page = 1
        this.pageSize = 60
        this.total = 0
        this.q = ''
        this.items = []
        this.uploading = 0
        this.dom = null
    }

    open() {
        this._buildDom()
        document.body.appendChild(this.dom)
        document.body.style.overflow = 'hidden'
        this._attachKey()
        this.refresh()
    }

    close() {
        if (this.dom && this.dom.parentNode) {
            this.dom.parentNode.removeChild(this.dom)
        }
        this.dom = null
        document.body.style.overflow = ''
        this._detachKey()
        if (_activePicker === this) _activePicker = null
    }

    _buildDom() {
        // 遮罩
        this.dom = document.createElement('div')
        this.dom.className = 'ial-overlay'

        // 視窗本體
        const box = document.createElement('div')
        box.className = 'ial-box'
        this.dom.appendChild(box)

        // 標頭
        const header = document.createElement('div')
        header.className = 'ial-header'
        const title = document.createElement('div')
        title.className = 'ial-title'
        title.textContent = this.titleText
        header.appendChild(title)

        const closeBtn = document.createElement('button')
        closeBtn.type = 'button'
        closeBtn.className = 'ial-close'
        closeBtn.textContent = '×'
        closeBtn.title = '關閉'
        closeBtn.addEventListener('click', () => this.close())
        header.appendChild(closeBtn)
        box.appendChild(header)

        // 工具列：搜尋 + 上傳按鈕
        const toolbar = document.createElement('div')
        toolbar.className = 'ial-toolbar'

        this.searchInput = document.createElement('input')
        this.searchInput.type = 'text'
        this.searchInput.className = 'ial-search'
        this.searchInput.placeholder = '搜尋檔名...'
        this.searchInput.addEventListener('input', () => {
            clearTimeout(this._searchTimer)
            this._searchTimer = setTimeout(() => {
                this.q = this.searchInput.value.trim()
                this.page = 1
                this.refresh()
            }, 250)
        })
        toolbar.appendChild(this.searchInput)

        this.uploadBtn = document.createElement('button')
        this.uploadBtn.type = 'button'
        this.uploadBtn.className = 'ial-btn ial-btn-primary'
        this.uploadBtn.textContent = '上傳圖檔'
        this.uploadBtn.addEventListener('click', () => this._pickFiles())
        toolbar.appendChild(this.uploadBtn)

        this.statusLabel = document.createElement('span')
        this.statusLabel.className = 'ial-status'
        toolbar.appendChild(this.statusLabel)

        box.appendChild(toolbar)

        // 拖拉接收區（覆蓋整個 grid）
        this.dropZone = document.createElement('div')
        this.dropZone.className = 'ial-dropzone'
        this.dropZone.innerHTML = '<span>拖拉圖檔到此處 / 或點擊上傳按鈕</span>'
        this.dropZone.style.display = 'none'
        box.appendChild(this.dropZone)

        // 主內容區（grid）
        this.gridWrap = document.createElement('div')
        this.gridWrap.className = 'ial-grid-wrap'
        this.grid = document.createElement('div')
        this.grid.className = 'ial-grid'
        this.gridWrap.appendChild(this.grid)
        box.appendChild(this.gridWrap)

        // 分頁列
        this.pager = document.createElement('div')
        this.pager.className = 'ial-pager'
        box.appendChild(this.pager)

        // 拖拉行為（整個 box）
        let dragCounter = 0
        const onDragEnter = (e) => {
            if (!_hasFiles(e)) return
            e.preventDefault()
            dragCounter++
            this.dropZone.style.display = 'flex'
            this.dropZone.classList.add('ial-dropzone-active')
        }
        const onDragLeave = (e) => {
            if (!_hasFiles(e)) return
            dragCounter = Math.max(0, dragCounter - 1)
            if (dragCounter === 0) {
                this.dropZone.style.display = 'none'
                this.dropZone.classList.remove('ial-dropzone-active')
            }
        }
        const onDragOver = (e) => {
            if (!_hasFiles(e)) return
            e.preventDefault()
            e.dataTransfer.dropEffect = 'copy'
        }
        const onDrop = (e) => {
            if (!_hasFiles(e)) return
            e.preventDefault()
            dragCounter = 0
            this.dropZone.style.display = 'none'
            this.dropZone.classList.remove('ial-dropzone-active')
            const files = Array.from(e.dataTransfer.files || [])
            this._uploadFiles(files)
        }
        box.addEventListener('dragenter', onDragEnter)
        box.addEventListener('dragleave', onDragLeave)
        box.addEventListener('dragover', onDragOver)
        box.addEventListener('drop', onDrop)
    }

    _attachKey() {
        this._keyHandler = (e) => {
            if (e.key === 'Escape') {
                e.preventDefault()
                this.close()
            }
        }
        document.addEventListener('keydown', this._keyHandler, true)
    }

    _detachKey() {
        if (this._keyHandler) {
            document.removeEventListener('keydown', this._keyHandler, true)
            this._keyHandler = null
        }
    }

    async refresh() {
        this._setStatus('載入中...')
        try {
            const params = new URLSearchParams({
                kind: 'image',
                page: String(this.page),
                page_size: String(this.pageSize),
            })
            if (this.q) params.set('q', this.q)
            const resp = await fetch('/beakcortex/api/files?' + params.toString(), {
                credentials: 'same-origin',
            })
            if (!resp.ok) throw new Error('HTTP ' + resp.status)
            const data = await resp.json()
            this.total = data.total || 0
            this.items = data.items || []
            this._renderGrid()
            this._renderPager()
            this._setStatus(`共 ${this.total} 張`)
        } catch (e) {
            this._setStatus('載入失敗：' + (e.message || e))
        }
    }

    _renderGrid() {
        this.grid.innerHTML = ''
        if (this.items.length === 0) {
            const empty = document.createElement('div')
            empty.className = 'ial-empty'
            empty.textContent = this.q ? '沒有符合的圖檔' : '尚無上傳的圖檔。拖拉或點上傳開始。'
            this.grid.appendChild(empty)
            return
        }
        for (const item of this.items) {
            const cell = document.createElement('div')
            cell.className = 'ial-cell'
            if (this.currentToken && this.currentToken === item.token) {
                cell.classList.add('ial-cell-current')
            }
            const img = document.createElement('img')
            img.src = item.url
            img.alt = item.original_filename
            img.loading = 'lazy'
            img.draggable = false
            cell.appendChild(img)

            const meta = document.createElement('div')
            meta.className = 'ial-cell-meta'
            meta.textContent = item.original_filename
            meta.title = item.original_filename
            cell.appendChild(meta)

            cell.addEventListener('click', () => {
                if (this.onSelect) this.onSelect(item.token, item.url, item)
                this.close()
            })
            this.grid.appendChild(cell)
        }
    }

    _renderPager() {
        this.pager.innerHTML = ''
        const totalPages = Math.max(1, Math.ceil(this.total / this.pageSize))
        if (totalPages <= 1) return

        const prev = document.createElement('button')
        prev.type = 'button'
        prev.className = 'ial-btn'
        prev.textContent = '上一頁'
        prev.disabled = this.page <= 1
        prev.addEventListener('click', () => {
            if (this.page > 1) { this.page--; this.refresh() }
        })
        this.pager.appendChild(prev)

        const info = document.createElement('span')
        info.className = 'ial-pager-info'
        info.textContent = `第 ${this.page} / ${totalPages} 頁`
        this.pager.appendChild(info)

        const next = document.createElement('button')
        next.type = 'button'
        next.className = 'ial-btn'
        next.textContent = '下一頁'
        next.disabled = this.page >= totalPages
        next.addEventListener('click', () => {
            if (this.page < totalPages) { this.page++; this.refresh() }
        })
        this.pager.appendChild(next)
    }

    _setStatus(text) {
        if (this.statusLabel) this.statusLabel.textContent = text || ''
    }

    _pickFiles() {
        const input = document.createElement('input')
        input.type = 'file'
        input.accept = 'image/*'
        input.multiple = true
        input.style.display = 'none'
        input.addEventListener('change', () => {
            const files = Array.from(input.files || [])
            this._uploadFiles(files)
        })
        document.body.appendChild(input)
        input.click()
        setTimeout(() => { if (input.parentNode) input.parentNode.removeChild(input) }, 1000)
    }

    async _uploadFiles(files) {
        const valid = files.filter(f => {
            const mime = (f.type || '').toLowerCase()
            return mime.startsWith('image/') && (!mime || ALLOWED_IMAGE_MIMES.has(mime))
        })
        if (valid.length === 0) {
            this._setStatus('沒有可上傳的圖檔（請確認類型）')
            return
        }
        this.uploading = valid.length
        this._setStatus(`上傳中... 0/${valid.length}`)
        let done = 0
        let failed = 0
        for (const file of valid) {
            try {
                const fd = new FormData()
                fd.append('file', file)
                fd.append('kind', 'image')
                const resp = await fetch('/beakcortex/api/files/upload', {
                    method: 'POST',
                    body: fd,
                    credentials: 'same-origin',
                })
                if (!resp.ok) {
                    failed++
                    continue
                }
                done++
                this._setStatus(`上傳中... ${done}/${valid.length}`)
            } catch (e) {
                failed++
            }
        }
        if (failed > 0) {
            this._setStatus(`完成：成功 ${done}，失敗 ${failed}`)
        } else {
            this._setStatus(`已上傳 ${done} 張`)
        }
        this.uploading = 0
        this.page = 1
        this.refresh()
    }
}


function _hasFiles(e) {
    if (!e.dataTransfer) return false
    const types = e.dataTransfer.types
    if (!types) return false
    for (let i = 0; i < types.length; i++) {
        if (types[i] === 'Files') return true
    }
    return false
}


export default openImageAlbumPicker
