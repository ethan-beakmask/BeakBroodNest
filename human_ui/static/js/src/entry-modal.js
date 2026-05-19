/**
 * BeakBroodNest Entry Modal -- Schema-driven 編輯對話框
 *
 * 取代「在 PM 文件流內 inline 編輯 entry」的混血架構。
 * 文件流內的 structuredEntry NodeView 只負責顯示;編輯一律走本 modal。
 *
 * API:
 *   openEntryModal({
 *     schema,                  // schema object (含 fields)
 *     schemaCode,              // 'task' | 'idcard' | ...
 *     rawText,                 // 主旨字串(idcard 用 line1)
 *     fieldValues,             // {fieldName: value}
 *     mode,                    // 'create' | 'edit'
 *     focusField,              // 'subject' | <fieldName>,預設 'subject'
 *     onSave({rawText, fieldValues}),
 *     onCancel(),
 *   })
 *
 * 鍵盤:
 *   Esc          -> cancel
 *   Mod-Enter    -> save
 *   Enter (input)-> focus next field;末欄 -> save
 *   Tab/ShiftTab -> 自然 focus 順序(含環繞 trap)
 */

import { openImageAlbumPicker } from './image-album.js'

let _activeModal = null

export function openEntryModal(opts) {
    if (_activeModal) {
        _activeModal._cancel()
    }
    _activeModal = new EntryModal(opts || {})
    _activeModal.show()
    return _activeModal
}

class EntryModal {
    constructor(opts) {
        this.opts = opts
        this.schema = opts.schema || null
        this.schemaCode = opts.schemaCode || (opts.schema && opts.schema.code) || 'freetext'
        this.rawText = opts.rawText || ''
        this.fieldValues = { ...(opts.fieldValues || {}) }
        this.mode = opts.mode || 'edit'
        this.onSave = opts.onSave || (() => {})
        this.onCancel = opts.onCancel || (() => {})
        this.focusField = opts.focusField || 'subject'
        this._closed = false
        this._fieldInputs = []        // ordered focusable list (for Enter→next)
    }

    show() {
        this.backdrop = document.createElement('div')
        this.backdrop.className = 'beak-entry-modal-backdrop'
        document.body.appendChild(this.backdrop)

        this.dialog = document.createElement('div')
        this.dialog.className = 'beak-entry-modal'
        this.dialog.classList.add('beak-entry-modal--' + this.schemaCode)
        this.dialog.setAttribute('role', 'dialog')
        this.dialog.setAttribute('aria-modal', 'true')
        this.backdrop.appendChild(this.dialog)

        // header
        const header = document.createElement('div')
        header.className = 'beak-entry-modal__header'
        const title = document.createElement('span')
        title.className = 'beak-entry-modal__title'
        title.textContent = this._titleText()
        const closeBtn = document.createElement('button')
        closeBtn.type = 'button'
        closeBtn.className = 'beak-entry-modal__close'
        closeBtn.textContent = '×'  // ×
        closeBtn.title = '取消 (Esc)'
        closeBtn.addEventListener('click', () => this._cancel())
        header.appendChild(title)
        header.appendChild(closeBtn)
        this.dialog.appendChild(header)

        // body
        this.body = document.createElement('div')
        this.body.className = 'beak-entry-modal__body'
        this.dialog.appendChild(this.body)

        this._renderForm()

        // footer
        const footer = document.createElement('div')
        footer.className = 'beak-entry-modal__footer'
        const hint = document.createElement('span')
        hint.className = 'beak-entry-modal__hint'
        hint.textContent = 'Esc 取消 / Ctrl+Enter 儲存'
        footer.appendChild(hint)
        const cancelBtn = document.createElement('button')
        cancelBtn.type = 'button'
        cancelBtn.className = 'btn btn-sm btn-outline-secondary'
        cancelBtn.textContent = '取消'
        cancelBtn.addEventListener('click', () => this._cancel())
        const saveBtn = document.createElement('button')
        saveBtn.type = 'button'
        saveBtn.className = 'btn btn-sm btn-primary'
        saveBtn.textContent = '儲存'
        saveBtn.addEventListener('click', () => this._save())
        footer.appendChild(cancelBtn)
        footer.appendChild(saveBtn)
        this.dialog.appendChild(footer)

        // 鍵盤總攔: Esc / Mod-Enter / Tab trap
        this._keyHandler = (e) => this._onKey(e)
        this.dialog.addEventListener('keydown', this._keyHandler)

        // 阻止 keydown 冒泡到 PM(若 modal 在 PM 容器附近時)
        const STOP = ['keydown', 'keyup', 'keypress', 'beforeinput', 'input', 'paste', 'cut', 'copy']
        for (const ev of STOP) {
            this.dialog.addEventListener(ev, (e) => e.stopPropagation())
        }

        queueMicrotask(() => this._focusInitial())
    }

    _titleText() {
        const sname = (this.schema && this.schema.name) || this.schemaCode
        return (this.mode === 'create' ? '新增 ' : '編輯 ') + sname
    }

    _renderForm() {
        // 主旨欄 -- idcard / image / file 不需要(主旨來自 line1 / caption / file_header)
        if (this.schemaCode !== 'idcard' && this.schemaCode !== 'image' && this.schemaCode !== 'file') {
            this.body.appendChild(this._buildSubjectRow())
        }
        if (this.schema && this.schema.fields && this.schema.fields.length > 0) {
            if (this.schemaCode === 'task') {
                this._renderTaskFields()
            } else if (this.schemaCode === 'idcard') {
                this._renderIdCardFields()
            } else if (this.schemaCode === 'image') {
                this._renderImageFields()
            } else {
                this._renderGenericFields()
            }
        }
    }

    _buildSubjectRow() {
        const row = document.createElement('div')
        row.className = 'beak-entry-modal__field beak-entry-modal__subject'
        const label = document.createElement('label')
        label.textContent = '主旨'
        const inp = document.createElement('input')
        inp.type = 'text'
        inp.className = 'form-control'
        inp.value = this.rawText
        inp.placeholder = '一句話主旨'
        inp.dataset.fieldKey = '__subject__'
        inp.addEventListener('input', () => { this.rawText = inp.value })
        row.appendChild(label)
        row.appendChild(inp)
        this._subjectInput = inp
        this._fieldInputs.push(inp)
        return row
    }

    _renderGenericFields() {
        const grid = document.createElement('div')
        grid.className = 'beak-entry-modal__grid'
        const sorted = this.schema.fields.slice().sort((a, b) => a.sort_order - b.sort_order)
        const LONG_FIELDS = ['note', 'body']
        for (const f of sorted) {
            if (LONG_FIELDS.includes(f.name)) continue
            grid.appendChild(this._buildFieldCell(f, false))
        }
        this.body.appendChild(grid)
        for (const f of sorted) {
            if (!LONG_FIELDS.includes(f.name)) continue
            const cell = this._buildFieldCell(f, true)
            cell.classList.add('beak-entry-modal__field--full')
            this.body.appendChild(cell)
        }
    }

    _renderTaskFields() {
        const grid = document.createElement('div')
        grid.className = 'beak-entry-modal__grid beak-entry-modal__grid--task'
        const fmap = {}
        for (const f of this.schema.fields) fmap[f.name] = f
        const layout = [
            ['category', 'urgency', 'location', 'attendees'],
            ['note'],
            ['baseline_start', 'baseline_end'],
            ['planned_start', 'planned_end', 'planned_duration'],
            ['actual_start', 'actual_end', 'progress', 'status'],
        ]
        for (const row of layout) {
            for (const name of row) {
                const f = fmap[name]
                if (!f) continue
                const isNote = name === 'note'
                const cell = this._buildFieldCell(f, isNote)
                if (isNote) cell.classList.add('beak-entry-modal__field--full')
                grid.appendChild(cell)
            }
            const remain = 4 - row.length
            if (remain > 0 && row[0] !== 'note') {
                for (let i = 0; i < remain; i++) {
                    const filler = document.createElement('div')
                    filler.className = 'beak-entry-modal__field beak-entry-modal__filler'
                    grid.appendChild(filler)
                }
            }
        }
        this.body.appendChild(grid)
    }

    _renderIdCardFields() {
        const wrap = document.createElement('div')
        wrap.className = 'beak-entry-modal__idcard'

        // 左:圖框
        const imgBox = document.createElement('div')
        imgBox.className = 'beak-entry-modal__idcard-image'
        imgBox.tabIndex = 0
        const renderImage = () => {
            imgBox.innerHTML = ''
            const token = (this.fieldValues.image_token || '').trim()
            if (token) {
                const img = document.createElement('img')
                img.src = '/beakbroodnest/files/' + encodeURIComponent(token)
                img.alt = ''
                img.draggable = false
                imgBox.appendChild(img)
            } else {
                const empty = document.createElement('div')
                empty.className = 'beak-entry-modal__idcard-empty'
                empty.textContent = '點擊選圖'
                imgBox.appendChild(empty)
            }
            const actions = document.createElement('div')
            actions.className = 'beak-entry-modal__idcard-actions'
            const replaceBtn = document.createElement('button')
            replaceBtn.type = 'button'
            replaceBtn.className = 'btn btn-sm btn-outline-secondary'
            replaceBtn.textContent = token ? '換圖' : '選圖'
            replaceBtn.addEventListener('click', (e) => {
                e.stopPropagation()
                this._pickImage(renderImage)
            })
            actions.appendChild(replaceBtn)
            if (token) {
                const clearBtn = document.createElement('button')
                clearBtn.type = 'button'
                clearBtn.className = 'btn btn-sm btn-outline-danger'
                clearBtn.textContent = '清除'
                clearBtn.addEventListener('click', (e) => {
                    e.stopPropagation()
                    this.fieldValues.image_token = ''
                    renderImage()
                })
                actions.appendChild(clearBtn)
            }
            imgBox.appendChild(actions)
        }
        imgBox.addEventListener('click', (e) => {
            if (e.target.tagName === 'BUTTON') return
            this._pickImage(renderImage)
        })
        imgBox.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                this._pickImage(renderImage)
            }
        })
        renderImage()
        wrap.appendChild(imgBox)
        this._fieldInputs.push(imgBox)

        // 右:四列 + is_primary toggle
        const lines = document.createElement('div')
        lines.className = 'beak-entry-modal__idcard-lines'
        const placeholders = ['主標(姓名/設備名)', '副標(職稱/型號)', '第三列', '第四列']
        const labels = ['主標', '副標', '第三列', '第四列']
        for (let i = 1; i <= 4; i++) {
            const key = 'line' + i
            const row = document.createElement('div')
            row.className = 'beak-entry-modal__field'
            const label = document.createElement('label')
            label.textContent = labels[i - 1]
            const inp = document.createElement('input')
            inp.type = 'text'
            inp.className = 'form-control'
            inp.value = this.fieldValues[key] || ''
            inp.placeholder = placeholders[i - 1]
            inp.dataset.fieldKey = key
            inp.addEventListener('input', () => { this.fieldValues[key] = inp.value })
            row.appendChild(label)
            row.appendChild(inp)
            lines.appendChild(row)
            this._fieldInputs.push(inp)
        }
        // is_primary checkbox
        const togRow = document.createElement('div')
        togRow.className = 'beak-entry-modal__field beak-entry-modal__idcard-toggle'
        const togLbl = document.createElement('label')
        togLbl.className = 'form-check-label'
        const cb = document.createElement('input')
        cb.type = 'checkbox'
        cb.className = 'form-check-input'
        const isPrim = this.fieldValues.is_primary === 'true' || this.fieldValues.is_primary === true
        cb.checked = isPrim
        cb.dataset.fieldKey = 'is_primary'
        cb.addEventListener('change', () => {
            this.fieldValues.is_primary = cb.checked ? 'true' : 'false'
        })
        togLbl.appendChild(cb)
        const span = document.createElement('span')
        span.textContent = ' 設為白板主帳卡'
        togLbl.appendChild(span)
        togRow.appendChild(togLbl)
        lines.appendChild(togRow)
        this._fieldInputs.push(cb)

        wrap.appendChild(lines)
        this.body.appendChild(wrap)
    }

    _renderImageFields() {
        const wrap = document.createElement('div')
        wrap.className = 'beak-entry-modal__image'

        // 左：圖框
        const imgBox = document.createElement('div')
        imgBox.className = 'beak-entry-modal__image-frame'
        imgBox.tabIndex = 0
        const renderImage = () => {
            imgBox.innerHTML = ''
            const token = (this.fieldValues.image_token || '').trim()
            if (token) {
                const img = document.createElement('img')
                img.src = '/beakbroodnest/files/' + encodeURIComponent(token)
                img.alt = ''
                img.draggable = false
                imgBox.appendChild(img)
            } else {
                const empty = document.createElement('div')
                empty.className = 'beak-entry-modal__image-empty'
                empty.textContent = '點擊選圖'
                imgBox.appendChild(empty)
            }
            const actions = document.createElement('div')
            actions.className = 'beak-entry-modal__image-actions'
            const replaceBtn = document.createElement('button')
            replaceBtn.type = 'button'
            replaceBtn.className = 'btn btn-sm btn-outline-secondary'
            replaceBtn.textContent = token ? '換圖' : '選圖'
            replaceBtn.addEventListener('click', (e) => {
                e.stopPropagation()
                this._pickImage(renderImage)
            })
            actions.appendChild(replaceBtn)
            if (token) {
                const clearBtn = document.createElement('button')
                clearBtn.type = 'button'
                clearBtn.className = 'btn btn-sm btn-outline-danger'
                clearBtn.textContent = '清除'
                clearBtn.addEventListener('click', (e) => {
                    e.stopPropagation()
                    this.fieldValues.image_token = ''
                    renderImage()
                })
                actions.appendChild(clearBtn)
            }
            imgBox.appendChild(actions)
        }
        imgBox.addEventListener('click', (e) => {
            if (e.target.tagName === 'BUTTON') return
            this._pickImage(renderImage)
        })
        imgBox.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                this._pickImage(renderImage)
            }
        })
        renderImage()
        wrap.appendChild(imgBox)
        this._fieldInputs.push(imgBox)

        // 右：caption 單行說明
        const right = document.createElement('div')
        right.className = 'beak-entry-modal__image-fields'
        const row = document.createElement('div')
        row.className = 'beak-entry-modal__field'
        const label = document.createElement('label')
        label.textContent = '說明'
        const inp = document.createElement('input')
        inp.type = 'text'
        inp.className = 'form-control'
        inp.value = this.fieldValues.caption || ''
        inp.placeholder = '一句話說明此圖'
        inp.dataset.fieldKey = 'caption'
        inp.addEventListener('input', () => { this.fieldValues.caption = inp.value })
        row.appendChild(label)
        row.appendChild(inp)
        right.appendChild(row)
        this._fieldInputs.push(inp)

        wrap.appendChild(right)
        this.body.appendChild(wrap)
    }

    _pickImage(renderImage) {
        openImageAlbumPicker({
            currentToken: this.fieldValues.image_token || null,
            onSelect: (token) => {
                this.fieldValues.image_token = token
                renderImage()
            },
        })
    }

    _buildFieldCell(field, multiline) {
        const row = document.createElement('div')
        row.className = 'beak-entry-modal__field'
        const label = document.createElement('label')
        label.textContent = field.label
        if (field.dimension) {
            const dim = document.createElement('span')
            dim.className = 'beak-entry-modal__field-dim'
            dim.textContent = field.dimension
            label.appendChild(dim)
        }
        row.appendChild(label)
        const el = this._createInput(field, multiline)
        row.appendChild(el)
        this._fieldInputs.push(el)
        return row
    }

    _createInput(field, multiline) {
        const cur = this.fieldValues[field.name] != null ? this.fieldValues[field.name] : ''
        let el
        if (multiline) {
            el = document.createElement('textarea')
            el.className = 'form-control'
            el.rows = 3
            el.value = cur
        } else if (field.field_type === 'select' || field.field_type === 'multiselect') {
            el = document.createElement('select')
            el.className = 'form-select'
            const empty = document.createElement('option')
            empty.value = ''
            empty.textContent = '-'
            el.appendChild(empty)
            try {
                const opts = JSON.parse(field.options || '[]')
                for (const o of opts) {
                    const op = document.createElement('option')
                    op.value = o
                    op.textContent = o
                    if (o === cur) op.selected = true
                    el.appendChild(op)
                }
            } catch (_) { /* invalid options JSON */ }
        } else if (field.field_type === 'checkbox') {
            el = document.createElement('input')
            el.type = 'checkbox'
            el.className = 'form-check-input'
            el.checked = cur === 'true' || cur === true
        } else if (field.field_type === 'date') {
            el = document.createElement('input')
            el.type = 'date'
            el.className = 'form-control'
            el.value = cur
        } else if (field.field_type === 'datetime') {
            el = document.createElement('input')
            el.type = 'datetime-local'
            el.className = 'form-control'
            el.value = cur
        } else if (field.field_type === 'number' || field.field_type === 'decimal') {
            el = document.createElement('input')
            el.type = 'number'
            el.className = 'form-control'
            el.value = cur
            if (field.field_type === 'decimal') el.step = '0.01'
        } else {
            el = document.createElement('input')
            el.type = 'text'
            el.className = 'form-control'
            el.value = cur
        }
        el.dataset.fieldKey = field.name
        const sync = () => {
            if (el.type === 'checkbox') {
                this.fieldValues[field.name] = String(el.checked)
            } else {
                this.fieldValues[field.name] = el.value
            }
        }
        el.addEventListener('input', sync)
        el.addEventListener('change', sync)
        return el
    }

    _onKey(e) {
        if (this._closed) return
        if (e.key === 'Escape') {
            e.preventDefault()
            this._cancel()
            return
        }
        if (e.key === 'Enter') {
            // Mod-Enter -> save
            if (e.ctrlKey || e.metaKey) {
                e.preventDefault()
                this._save()
                return
            }
            const t = e.target
            // textarea: 自然換行,不攔
            if (t && t.tagName === 'TEXTAREA') return
            // select / checkbox 自然行為
            if (t && (t.tagName === 'SELECT' || (t.tagName === 'INPUT' && t.type === 'checkbox'))) return
            // 一般 input -> 跳下一個;末欄 -> save
            if (t && t.tagName === 'INPUT') {
                e.preventDefault()
                const idx = this._fieldInputs.indexOf(t)
                if (idx < 0 || idx === this._fieldInputs.length - 1) {
                    this._save()
                } else {
                    const next = this._fieldInputs[idx + 1]
                    try { next.focus(); if (next.select) next.select() } catch (_) {}
                }
                return
            }
            return
        }
        if (e.key === 'Tab') {
            // Focus trap: 在 modal 內環繞
            const all = this._collectTabbables()
            if (all.length === 0) return
            const cur = document.activeElement
            const idx = all.indexOf(cur)
            if (idx < 0) return
            if (e.shiftKey) {
                if (idx === 0) {
                    e.preventDefault()
                    all[all.length - 1].focus()
                }
            } else {
                if (idx === all.length - 1) {
                    e.preventDefault()
                    all[0].focus()
                }
            }
        }
    }

    _collectTabbables() {
        const sel = 'input:not([disabled]), textarea:not([disabled]), select:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])'
        return Array.from(this.dialog.querySelectorAll(sel)).filter(el => {
            if (el.offsetParent === null && el.tagName !== 'BODY') return false
            return true
        })
    }

    _focusInitial() {
        const targetKey = this.focusField === 'subject' ? '__subject__' : this.focusField
        let target = this.dialog.querySelector('[data-field-key="' + targetKey + '"]')
        if (!target) target = this.dialog.querySelector('input, textarea, select')
        if (target) {
            try { target.focus(); if (target.select) target.select() } catch (_) {}
        }
    }

    _save() {
        if (this._closed) return
        if (this._subjectInput) {
            this.rawText = this._subjectInput.value
        } else if (this.schemaCode === 'idcard') {
            // idcard 的主旨用 line1 當代理(供 raw_text 顯示)
            this.rawText = (this.fieldValues.line1 || '').trim()
        } else if (this.schemaCode === 'image') {
            // image 的主旨用 caption 當代理(供 raw_text 顯示)
            this.rawText = (this.fieldValues.caption || '').trim()
        }
        const result = { rawText: this.rawText, fieldValues: { ...this.fieldValues } }
        this._teardown()
        try { this.onSave(result) } catch (err) { console.error(err) }
    }

    _cancel() {
        if (this._closed) return
        this._teardown()
        try { this.onCancel() } catch (err) { console.error(err) }
    }

    _teardown() {
        this._closed = true
        if (this.backdrop && this.backdrop.parentNode) {
            this.backdrop.parentNode.removeChild(this.backdrop)
        }
        if (_activeModal === this) _activeModal = null
    }
}

export default openEntryModal
