/**
 * PasteTextTable -- 偵測貼上的 Unicode/ASCII box-drawing 表格並轉成 Tiptap 表格。
 *
 * 觸發條件：整段貼上的文字（trim 後）由「邊框列」與「內容列」組成。
 *   - 邊框列：僅由邊框字元 (─ │ ┌ ┐ └ ┘ ├ ┤ ┬ ┴ ┼ ═ + -) 與空白構成
 *   - 內容列：以 │ 或 | 開頭，至少含兩個 │/| 分隔
 * 命中：建立 PM table node，第一列為 tableHeader。
 * 不命中（混入其它文字、欄數不一致、僅一欄）：return false 走正常 paste 流程。
 */
import { Extension } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'

const BORDER_ONLY = /^[\s│|+\-─═├┤┼┬┴┌┐└┘╔╗╚╝╠╣╦╩╬]+$/

function isBorderOnly(line) {
    return BORDER_ONLY.test(line) && /[─\-═]/.test(line)
}

function isContentRow(line) {
    const t = line.trimStart()
    if (!/^[│|]/.test(t)) return false
    return (t.match(/[│|]/g) || []).length >= 2
}

function splitCells(line) {
    let s = line.trim()
    s = s.replace(/^[│|]/, '').replace(/[│|]$/, '')
    return s.split(/[│|]/).map(c => c.trim())
}

/**
 * 嘗試把整段文字解析成 rows（陣列的陣列）。
 * 失敗回傳 null。
 */
function parseTextTable(text) {
    const lines = text.split(/\r?\n/)
    let started = false
    let ended = false
    const rows = []
    for (const raw of lines) {
        const line = raw
        const trimmed = line.trim()
        if (!trimmed) {
            if (started) { ended = true; continue }
            continue
        }
        if (ended) return null  // 表格結束後又出現內容 = 混合內容，放棄
        if (isContentRow(line)) {
            rows.push(splitCells(line))
            started = true
        } else if (isBorderOnly(line)) {
            started = true
        } else {
            return null  // 非表格列 = 放棄
        }
    }
    if (rows.length < 1) return null
    const cols = rows[0].length
    if (cols < 2) return null
    if (!rows.every(r => r.length === cols)) return null
    return rows
}

function buildTableNode(schema, rows) {
    const { table, tableRow, tableHeader, tableCell, paragraph, text: textType } = schema.nodes
    if (!table || !tableRow || !tableHeader || !tableCell || !paragraph) return null

    const makeCell = (cellText, isHeader) => {
        const cellType = isHeader ? tableHeader : tableCell
        const paraContent = cellText ? schema.text(cellText) : null
        const para = paragraph.create(null, paraContent)
        return cellType.create(null, para)
    }

    const trs = rows.map((row, idx) =>
        tableRow.create(null, row.map(c => makeCell(c, idx === 0)))
    )
    return table.create(null, trs)
}

export const PasteTextTable = Extension.create({
    name: 'pasteTextTable',
    addProseMirrorPlugins() {
        return [
            new Plugin({
                props: {
                    handlePaste: (view, event) => {
                        const text = event.clipboardData?.getData('text/plain')
                        if (!text || !text.trim()) return false
                        // 快速門檻：必須含至少一個邊框字元或多個 |
                        if (!/[─│┌┐└┘├┤┬┴┼═]/.test(text) &&
                            !((text.match(/\|/g) || []).length >= 4 && /[+\-]/.test(text))) {
                            return false
                        }
                        const rows = parseTextTable(text)
                        if (!rows) return false
                        const node = buildTableNode(view.state.schema, rows)
                        if (!node) return false
                        const tr = view.state.tr.replaceSelectionWith(node)
                        view.dispatch(tr.scrollIntoView())
                        return true
                    },
                },
            }),
        ]
    },
})
