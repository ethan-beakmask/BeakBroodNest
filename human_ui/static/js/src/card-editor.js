/**
 * BeakCortex Card Editor -- Tiptap WYSIWYG Markdown 編輯器
 * 打包後掛載為 window.CardEditor 供 Alpine.js 呼叫
 */
import { Editor } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import { Table, TableRow, TableHeader, TableCell } from '@tiptap/extension-table'
import { TaskList } from '@tiptap/extension-task-list'
import { TaskItem } from '@tiptap/extension-task-item'
import { Image } from '@tiptap/extension-image'
import { Placeholder } from '@tiptap/extension-placeholder'
import { Typography } from '@tiptap/extension-typography'
import { Highlight } from '@tiptap/extension-highlight'
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
                Image.configure({
                    inline: true,
                }),
                Placeholder.configure({
                    placeholder: '開始撰寫...',
                }),
                Highlight.configure({ multicolor: false }),
                Typography,
                Markdown.configure({
                    html: true,
                    transformPastedText: true,
                    transformCopiedText: true,
                }),
                StructuredEntry,
                SlashCommand,
                SelectionToolbar,
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
     * 擷取選取文字並可選地刪除（單一原子操作）
     * @param {boolean} shouldDelete - true 時刪除選取範圍（移動模式）
     * @returns {{ from, to, markdown }} | null
     */
    captureSelection(shouldDelete) {
        if (!this.editor) return null
        const view = this.editor.view
        const state = view.state
        const { from, to, empty } = state.selection
        if (empty) return null

        // 先取文字（純文字，避免序列化產生副作用）
        const text = state.doc.textBetween(from, to, '\n\n', '\n')
        if (!text.trim()) return null

        // 刪除必須在同一個 state 上操作
        if (shouldDelete) {
            view.dispatch(state.tr.delete(from, to))
        }

        return { from, to, markdown: text }
    }

    /**
     * 從 ProseMirror 文件中提取所有 structuredEntry nodes。
     * 回傳陣列供 sync API 使用。
     */
    extractEntries() {
        if (!this.editor) return []
        const entries = []
        const doc = this.editor.state.doc
        doc.forEach((node, offset, index) => {
            if (node.type.name === 'structuredEntry') {
                entries.push({
                    id: node.attrs.entryId || null,
                    schema_code: node.attrs.schemaCode || 'freetext',
                    schema_id: node.attrs.schemaId || null,
                    raw_text: node.textContent,
                    field_values: node.attrs.fieldValues || {},
                    sort_order: index,
                })
            } else {
                // Non-entry blocks (paragraph, heading, etc.) -> freetext entry
                const text = node.textContent
                if (text.trim() || node.type.name !== 'paragraph') {
                    entries.push({
                        schema_code: 'freetext',
                        raw_text: text,
                        field_values: {},
                        sort_order: index,
                    })
                }
            }
        })
        return entries
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
