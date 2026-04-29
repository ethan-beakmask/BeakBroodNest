/**
 * BeakCortex Card Editor -- Tiptap WYSIWYG Markdown 編輯器
 * 打包後掛載為 window.CardEditor 供 Alpine.js 呼叫
 */
import { Editor, Extension } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'

// 額外 list 熱鍵 (與文字框對齊) + Tab 守門 + Enter 守門
//   Ctrl+Shift+6 = 清單 (BulletList)
//   Ctrl+Shift+7 = 編號 (OrderedList) -- Tiptap StarterKit 已內建
//   Ctrl+Shift+8 = 清單 (BulletList) -- Tiptap StarterKit 已內建
// Tab / Shift+Tab: 同 key 在多個 extension 註冊時 Tiptap 會以後註冊者覆寫,
//   所以這裡完整接管,內部呼叫 sinkListItem/liftListItem 處理 list 巢狀,
//   不論成不成功一律 return true 吃掉,防 focus 跳出編輯器。
// Enter: ListItem 預設只跑 splitListItem,空項時 splitListItem return false 不會
//   自動 lift,使空 li 連續累積。這裡接管後改成 split 失敗→lift,空項按 Enter 即退出清單。
const ListHotkeys = Extension.create({
    name: 'listHotkeys',
    addKeyboardShortcuts() {
        return {
            'Mod-Shift-6': () => this.editor.commands.toggleBulletList(),
            Tab: ({ editor }) => {
                editor.commands.sinkListItem('listItem')
                    || editor.commands.sinkListItem('taskItem');
                return true;
            },
            'Shift-Tab': ({ editor }) => {
                editor.commands.liftListItem('listItem')
                    || editor.commands.liftListItem('taskItem');
                return true;
            },
            Enter: ({ editor }) => {
                if (editor.isActive('listItem')) {
                    return editor.commands.splitListItem('listItem')
                        || editor.commands.liftListItem('listItem');
                }
                if (editor.isActive('taskItem')) {
                    return editor.commands.splitListItem('taskItem')
                        || editor.commands.liftListItem('taskItem');
                }
                return false;
            },
        }
    },
})
import { Table, TableRow, TableHeader, TableCell } from '@tiptap/extension-table'
import { TaskList } from '@tiptap/extension-task-list'
import { TaskItem } from '@tiptap/extension-task-item'
import { ResizableImage } from './resizable-image.js'
import { PdfThumbnail } from './pdf-thumbnail.js'
import { PdfReader } from './pdf-reader.js'
import { Placeholder } from '@tiptap/extension-placeholder'
import { Typography } from '@tiptap/extension-typography'
import { Highlight } from '@tiptap/extension-highlight'
import { TextStyle } from '@tiptap/extension-text-style'
import { Color } from '@tiptap/extension-color'
import { Markdown } from 'tiptap-markdown'
import { StructuredEntry } from './structured-entry.js'
import { SlashCommand } from './slash-command.js'
import { SelectionToolbar } from './selection-toolbar.js'

class CardEditor {
    constructor() {
        this.editor = null
        this.onChangeCallback = null
    }

    /**
     * 初始化編輯器實例
     * @param {HTMLElement} element - 掛載的 DOM 元素
     * @param {object} options - { content, contentJson, onChange }
     */
    create(element, options = {}) {
        if (this.editor) {
            this.editor.destroy()
        }

        const editorConfig = {
            element,
            extensions: [
                StarterKit.configure({
                    heading: { levels: [1, 2, 3, 4] },
                    codeBlock: {
                        HTMLAttributes: { class: 'code-block' },
                    },
                    link: { openOnClick: false },
                }),
                Table.configure({ resizable: true }),
                TableRow,
                TableHeader,
                TableCell,
                TaskList,
                TaskItem.configure({ nested: true }),
                ResizableImage.configure({
                    inline: true,
                }),
                Placeholder.configure({
                    placeholder: '開始撰寫...',
                }),
                Highlight.configure({ multicolor: true }),
                TextStyle,
                Color,
                Typography,
                Markdown.configure({
                    html: true,
                    transformPastedText: true,
                    transformCopiedText: true,
                }),
                StructuredEntry,
                PdfThumbnail,
                PdfReader,
                SlashCommand,
                SelectionToolbar,
                ListHotkeys,
            ],
            editorProps: {
                attributes: {
                    class: 'card-editor-content',
                },
            },
            onUpdate: ({ editor }) => {
                if (this.onChangeCallback) {
                    this.onChangeCallback({
                        markdown: editor.storage.markdown.getMarkdown(),
                        json: editor.getJSON(),
                    })
                }
                if (this.onStateChangeCallback) this.onStateChangeCallback()
            },
            onSelectionUpdate: () => {
                if (this.onStateChangeCallback) this.onStateChangeCallback()
            },
        }

        // 優先用 JSON，其次 markdown
        if (options.contentJson) {
            editorConfig.content = options.contentJson
        } else if (options.content) {
            editorConfig.content = options.content
        } else {
            editorConfig.content = ''
        }

        if (options.editable === false) {
            editorConfig.editable = false
        }

        this.editor = new Editor(editorConfig)
        this.onChangeCallback = options.onChange || null
        this.onStateChangeCallback = options.onStateChange || null

        return this
    }

    /** 取得 Markdown 字串 */
    getMarkdown() {
        if (!this.editor) return ''
        return this.editor.storage.markdown.getMarkdown()
    }

    /** 取得 Tiptap JSON (ProseMirror doc tree) */
    getJSON() {
        if (!this.editor) return null
        return this.editor.getJSON()
    }

    /** 設定內容 (markdown 字串) */
    setContent(markdown) {
        if (!this.editor) return
        this.editor.commands.setContent(markdown)
    }

    /** 設定內容 (JSON) */
    setContentJSON(json) {
        if (!this.editor) return
        this.editor.commands.setContent(json)
    }

    /** 工具列指令 */
    cmd(command, ...args) {
        if (!this.editor) return
        const chain = this.editor.chain().focus()
        switch (command) {
            case 'bold': chain.toggleBold().run(); break
            case 'italic': chain.toggleItalic().run(); break
            case 'underline': chain.toggleMark('underline').run(); break
            case 'strike': chain.toggleStrike().run(); break
            case 'code': chain.toggleCode().run(); break
            case 'highlight': chain.toggleHighlight().run(); break
            case 'h1': chain.toggleHeading({ level: 1 }).run(); break
            case 'h2': chain.toggleHeading({ level: 2 }).run(); break
            case 'h3': chain.toggleHeading({ level: 3 }).run(); break
            case 'h4': chain.toggleHeading({ level: 4 }).run(); break
            case 'bulletList': chain.toggleBulletList().run(); break
            case 'orderedList': chain.toggleOrderedList().run(); break
            case 'taskList': chain.toggleTaskList().run(); break
            case 'blockquote': chain.toggleBlockquote().run(); break
            case 'codeBlock': chain.toggleCodeBlock().run(); break
            case 'hr': chain.setHorizontalRule().run(); break
            case 'undo': chain.undo().run(); break
            case 'redo': chain.redo().run(); break
            case 'link':
                if (args[0]) {
                    chain.setLink({ href: args[0] }).run()
                } else {
                    chain.unsetLink().run()
                }
                break
            case 'image':
                if (args[0]) {
                    chain.setImage({ src: args[0] }).run()
                }
                break
            case 'table':
                chain.insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
                break
            case 'insertEntry':
                this.editor.commands.insertEntry({
                    schemaCode: args[0] || 'freetext',
                    schemaId: args[1] || null,
                    text: args[2] || '',
                })
                return
            case 'convertToEntry':
                this.editor.commands.convertToEntry(args[0] || 'freetext', args[1] || null)
                return
            case 'deleteTable': chain.deleteTable().run(); break
            case 'addRowAfter': chain.addRowAfter().run(); break
            case 'addRowBefore': chain.addRowBefore().run(); break
            case 'deleteRow': chain.deleteRow().run(); break
            case 'addColAfter': chain.addColumnAfter().run(); break
            case 'addColBefore': chain.addColumnBefore().run(); break
            case 'deleteCol': chain.deleteColumn().run(); break
        }
    }

    /** 檢查目前游標所在的格式狀態 */
    isActive(name, attrs) {
        if (!this.editor) return false
        return this.editor.isActive(name, attrs)
    }

    /**
     * 將文件中所有 structuredEntry 統一設為展開或收合。
     * @param {boolean} collapsed - true=全收合, false=全展開
     */
    setAllEntriesCollapsed(collapsed) {
        if (!this.editor) return 0
        const view = this.editor.view
        const state = view.state
        const tr = state.tr
        let touched = 0
        state.doc.descendants((node, pos) => {
            if (node.type.name !== 'structuredEntry') return
            if (!!node.attrs.collapsed === !!collapsed) return
            tr.setNodeMarkup(pos, undefined, { ...node.attrs, collapsed: !!collapsed })
            touched += 1
        })
        if (touched > 0) view.dispatch(tr)
        return touched
    }

    /** 回傳目前展開（collapsed=false）且有 entryId 的所有 entryId，供 reload 後恢復 */
    getExpandedEntryIds() {
        if (!this.editor) return []
        const ids = []
        this.editor.state.doc.descendants(node => {
            if (node.type.name !== 'structuredEntry') return
            if (!node.attrs.collapsed && node.attrs.entryId) {
                ids.push(node.attrs.entryId)
            }
        })
        return ids
    }

    /**
     * 從 DB entries 同步最新 fieldValues 到對應的 structuredEntry node。
     * 不重建文件、不動結構、不動其他 attrs（entryId/collapsed/schemaCode 全保留）。
     *
     * 用途：Gantt 拖拉時間或外部修改 entry_field_values 後，卡片重新開啟時
     * 把 DB 最新欄位值補進 content_json 重建出的編輯器 -- 而 content_json 本身
     * 只在 saveEditor 時才會更新，無法反映後續的外部變動。
     */
    syncFieldValuesFromEntries(entries) {
        if (!this.editor || !entries || entries.length === 0) return 0
        const fvByEntryId = {}
        for (const e of entries) {
            if (e.id) fvByEntryId[e.id] = e.field_values || {}
        }
        if (Object.keys(fvByEntryId).length === 0) return 0

        const view = this.editor.view
        const state = view.state
        const tr = state.tr
        let mutated = 0
        state.doc.descendants((node, pos) => {
            if (node.type.name !== 'structuredEntry') return
            const eid = node.attrs.entryId
            if (!eid || !(eid in fvByEntryId)) return
            const fresh = fvByEntryId[eid]
            const current = node.attrs.fieldValues || {}
            // 鍵集合或值任一不同就更新
            const keys = new Set([...Object.keys(current), ...Object.keys(fresh)])
            let changed = false
            for (const k of keys) {
                if ((current[k] || '') !== (fresh[k] || '')) { changed = true; break }
            }
            if (!changed) return
            tr.setNodeMarkup(pos, undefined, { ...node.attrs, fieldValues: fresh })
            mutated += 1
        })
        if (mutated > 0) view.dispatch(tr)
        return mutated
    }

    /** 將指定 entryId 集合對應的 structuredEntry 設為展開 */
    expandEntriesByIds(entryIds) {
        if (!this.editor || !entryIds || entryIds.length === 0) return
        const set = new Set(entryIds)
        const view = this.editor.view
        const state = view.state
        const tr = state.tr
        let mutated = false
        state.doc.descendants((node, pos) => {
            if (node.type.name !== 'structuredEntry') return
            if (!set.has(node.attrs.entryId)) return
            if (!node.attrs.collapsed) return
            tr.setNodeMarkup(pos, undefined, { ...node.attrs, collapsed: false })
            mutated = true
        })
        if (mutated) view.dispatch(tr)
    }

    /** 回傳「是否仍有任一 structuredEntry 處於收合」-- 供 toolbar 判斷下次動作 */
    hasCollapsedEntry() {
        if (!this.editor) return false
        let found = false
        this.editor.state.doc.descendants(node => {
            if (found) return false
            if (node.type.name === 'structuredEntry' && node.attrs.collapsed) {
                found = true
                return false
            }
        })
        return found
    }

    /**
     * 擷取選取文字並可選地刪除（單一原子操作）
     * @param {boolean} shouldDelete - true 時刪除選取範圍（移動模式）
     * @returns {{ from, to, markdown, contentJson }} | null
     */
    captureSelection(shouldDelete) {
        if (!this.editor) return null
        const view = this.editor.view
        const state = view.state
        const { from, to, empty } = state.selection
        if (empty) return null

        // JSON 內容（保留 structuredEntry 等 node 結構）
        const slice = state.doc.slice(from, to)
        const contentJson = slice.content.toJSON()

        // 顯示用純文字
        let text = state.doc.textBetween(from, to, '\n\n', '\n')
        // NodeSelection 選取 structuredEntry 時，加上 schema 標記方便辨識
        if (state.selection.node && state.selection.node.type.name === 'structuredEntry') {
            const code = state.selection.node.attrs.schemaCode || 'freetext'
            text = '[' + code + '] ' + text
        }
        // 純文字為空但 selection 含非文字 node（例如圖片）時，產出顯示用 placeholder
        if (!text.trim()) {
            const tags = []
            slice.content.descendants(n => {
                if (n.type.name === 'image') {
                    const src = (n.attrs && n.attrs.src) ? String(n.attrs.src) : ''
                    const tail = src ? src.split('/').pop() : ''
                    tags.push('[圖片' + (tail ? ' ' + tail : '') + ']')
                    return false
                }
                return true
            })
            if (tags.length === 0) return null
            text = tags.join(' ')
        }

        // 刪除必須在同一個 state 上操作
        if (shouldDelete) {
            view.dispatch(state.tr.delete(from, to))
        }

        return { from, to, markdown: text, contentJson: contentJson }
    }

    /**
     * 收集 doc 內所有要進 entries 表的節點，並回傳 {node, pos, isFreetext} 陣列。
     * 規則：
     *   - 頂層非空 paragraph / heading 等 → freetext entry（保持索引穩定）
     *   - 頂層 structuredEntry → entry
     *   - 巢狀 structuredEntry（table cell / blockquote / list 內）→ entry
     *     （巢狀 freetext 不轉 entry，避免 entries 爆量）
     * extractEntries 與 writeBackEntryIds 共用此走訪以保證索引對齊。
     */
    _collectStructuredItems() {
        if (!this.editor) return []
        const doc = this.editor.state.doc
        const items = []
        const seenPos = new Set()

        // 階段 1：頂層 blocks
        doc.forEach((node, offset) => {
            if (node.type.name === 'pdfReader' || node.type.name === 'pdfThumbnail') return
            if (node.type.name === 'structuredEntry') {
                items.push({ node, pos: offset, isFreetext: false })
                seenPos.add(offset)
                return
            }
            const text = node.textContent
            if (text.trim() || node.type.name !== 'paragraph') {
                items.push({ node, pos: offset, isFreetext: true })
            }
        })

        // 階段 2：補抓巢狀 structuredEntry（table cell / blockquote / list / etc.）
        doc.descendants((sub, pos) => {
            if (sub.type.name === 'structuredEntry') {
                if (!seenPos.has(pos)) {
                    items.push({ node: sub, pos, isFreetext: false })
                }
                return false  // entry 內部不再 descend
            }
            return true
        })

        items.sort((a, b) => a.pos - b.pos)
        return items
    }

    /**
     * 從 ProseMirror 文件中提取所有 structuredEntry nodes。
     * 回傳陣列供 sync API 使用。
     */
    extractEntries() {
        const items = this._collectStructuredItems()
        return items.map((it, sortOrder) => {
            if (it.isFreetext) {
                return {
                    schema_code: 'freetext',
                    raw_text: it.node.textContent,
                    field_values: {},
                    sort_order: sortOrder,
                }
            }
            return {
                id: it.node.attrs.entryId || null,
                schema_code: it.node.attrs.schemaCode || 'freetext',
                schema_id: it.node.attrs.schemaId || null,
                raw_text: it.node.textContent,
                field_values: it.node.attrs.fieldValues || {},
                sort_order: sortOrder,
            }
        })
    }

    /**
     * 將 sync 回傳的 entries 中新賦予的 id 寫回對應的 structuredEntry node，
     * 而不重建整份文件（避免 reload 時遺失表格/清單/標題等非 entry 結構）。
     *
     * 對應規則：syncEntries 的順序與 extractEntries() 產生的順序一致，
     * 後者用 doc.forEach 過濾「空 paragraph」後依序輸出。
     */
    writeBackEntryIds(syncEntries) {
        if (!this.editor || !syncEntries || syncEntries.length === 0) return
        const items = this._collectStructuredItems()
        const view = this.editor.view
        const tr = view.state.tr
        let mutated = false
        // setNodeMarkup 是同 size 操作，後續 pos 仍有效
        items.forEach((it, idx) => {
            const sched = syncEntries[idx]
            if (!sched) return
            if (it.isFreetext) return
            if (!sched.id || sched.schema_code === 'freetext') return
            if (it.node.attrs.entryId === sched.id) return
            tr.setNodeMarkup(it.pos, undefined, { ...it.node.attrs, entryId: sched.id })
            mutated = true
        })
        if (mutated) view.dispatch(tr)
    }

    /**
     * 從 DB entries 載入：將 entries 陣列轉為 ProseMirror 文件。
     * @param {Array} entries - API 回傳的 entries
     */
    loadEntries(entries) {
        if (!this.editor || !entries || entries.length === 0) return
        const content = entries.map(e => {
            if (e.schema_code === 'freetext') {
                return {
                    type: 'paragraph',
                    content: e.raw_text ? [{ type: 'text', text: e.raw_text }] : [],
                }
            }
            return {
                type: 'structuredEntry',
                attrs: {
                    entryId: e.id,
                    schemaCode: e.schema_code,
                    schemaId: e.schema_id,
                    fieldValues: e.field_values || {},
                    collapsed: true,
                },
                content: e.raw_text ? [{ type: 'text', text: e.raw_text }] : [],
            }
        })
        this.editor.commands.setContent({ type: 'doc', content })
    }

    /**
     * 偵測整份文件是否為 PDF 媒體卡片：第一塊 node 是 pdfReader 或 pdfThumbnail。
     * @returns {{ kind: 'pdfReader' | 'pdfThumbnail', viewMode: string, attrs: object } | null}
     */
    detectPdfMediaNode() {
        if (!this.editor) return null
        const doc = this.editor.state.doc
        let found = null
        doc.forEach((node) => {
            if (found) return
            const t = node.type.name
            if (t === 'pdfReader' || t === 'pdfThumbnail') found = node
        })
        if (!found) return null
        const t = found.type.name
        return {
            kind: t,
            viewMode: t === 'pdfReader' ? (found.attrs.viewMode || 'reader') : 'thumbnail',
            attrs: { ...found.attrs },
        }
    }

    /**
     * 取得文件中第一個 pdfReader NodeView 實例（若有）。
     * @returns {PdfReaderView | null}
     */
    getFirstPdfReaderView() {
        if (!this.editor || !this.editor.view) return null
        const root = this.editor.view.dom
        const el = root.querySelector('.pdf-reader-block')
        return el && el._pdfReaderView ? el._pdfReaderView : null
    }

    /** 切換 pdfReader node 的 viewMode（reader / thumbnail） */
    setPdfReaderViewMode(mode) {
        if (!this.editor) return false
        return this.editor.commands.setPdfReaderViewMode(mode)
    }

    /** 銷毀編輯器 */
    destroy() {
        if (this.editor) {
            this.editor.destroy()
            this.editor = null
        }
    }
}

// 掛載到 window 供 Alpine.js 使用
window.CardEditor = CardEditor
