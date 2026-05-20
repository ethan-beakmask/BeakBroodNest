/**
 * PasteTextTable -- 掃描貼上的整段文字，找出其中所有的 Unicode/ASCII/Markdown 表格
 * 並轉成 Tiptap 表格節點；表格前後或中間的純文字保留為 paragraph。
 *
 * 表格判定（嚴格）：
 *   - 一段「連續、非空」的列，由「邊框列」與「內容列」組成
 *   - 至少 2 列 contentRow、欄數 ≥ 2、所有 contentRow 欄數一致
 *
 * 非表格段：以空行為段落界，每段一個 paragraph，段內換行用 hardBreak。
 *
 * 任何位置的文字 / 符號 / 空白都不再阻擋轉換，只要文章中能掃出 ≥ 1 個表格就介入。
 */
import { Extension } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { Fragment, Slice } from '@tiptap/pm/model'

const BORDER_ONLY = /^[\s│|+\-─═├┤┼┬┴┌┐└┘╔╗╚╝╠╣╦╩╬:]+$/

function isBorderOnly(line) {
    return BORDER_ONLY.test(line) && /[─\-═]/.test(line)
}

function isContentRow(line) {
    const t = line.trimStart()
    if (!/^[│|]/.test(t)) return false
    return (t.match(/[│|]/g) || []).length >= 2
}

/**
 * 切欄。以「行首邊界字元」決定本列用哪個分隔符，避免單元格內含另一種 |/│
 * 被誤判為分隔（例如 Unicode 表格中描述 markdown 表格的 `|---|---|`）。
 */
function splitCells(line) {
    let s = line.trim()
    const head = s[0]
    const sep = (head === '│') ? '│' : '|'
    // 去頭尾邊界字元（限同一種）
    if (s.startsWith(sep)) s = s.slice(1)
    if (s.endsWith(sep)) s = s.slice(0, -1)
    return s.split(sep).map(c => c.trim())
}

/**
 * 從 candidate 區段（連續非空列）萃取表格。
 * 回傳 rows 或 null（不符合條件）。
 */
function extractTable(candidateLines) {
    const rows = []
    let cols = null
    for (const ln of candidateLines) {
        // 先判 border：markdown 的 |---|---| 同時符合 content/border 兩條，
        // 語意上是分隔列，不應被當成資料列。
        if (isBorderOnly(ln)) {
            continue
        }
        if (isContentRow(ln)) {
            const cells = splitCells(ln)
            if (cols === null) cols = cells.length
            else if (cells.length !== cols) return null
            rows.push(cells)
        } else {
            return null
        }
    }
    if (rows.length < 2) return null
    if (cols < 2) return null
    return rows
}

/**
 * 掃描整段文字，回傳 segments 陣列。
 * segment.kind = 'table' (帶 rows) 或 'text' (帶 lines)
 */
function scanSegments(text) {
    const lines = text.split(/\r?\n/)
    const segments = []
    let textBuf = []
    const flushText = () => {
        if (textBuf.length) {
            segments.push({ kind: 'text', lines: textBuf })
            textBuf = []
        }
    }
    let i = 0
    while (i < lines.length) {
        const line = lines[i]
        const trimmed = line.trim()
        // 嘗試從 i 起識別表格 candidate（連續非空、且每列都是 content/border）
        if (trimmed && (isContentRow(line) || isBorderOnly(line))) {
            const candidate = []
            let j = i
            while (j < lines.length) {
                const ln = lines[j]
                const t = ln.trim()
                if (!t) break  // 空行終止 candidate
                if (isContentRow(ln) || isBorderOnly(ln)) {
                    candidate.push(ln)
                    j++
                } else {
                    break  // 出現非表格列終止 candidate
                }
            }
            const rows = extractTable(candidate)
            if (rows) {
                flushText()
                segments.push({ kind: 'table', rows })
                i = j
                continue
            }
            // 不算表格 → 把 candidate 整段塞回 text buffer
            for (const ln of candidate) textBuf.push(ln)
            i = j
            continue
        }
        // 普通文字行（含空行）
        textBuf.push(line)
        i++
    }
    flushText()
    return segments
}

function buildTableNode(schema, rows) {
    const { table, tableRow, tableHeader, tableCell, paragraph } = schema.nodes
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

/**
 * 把文字 lines 轉成 paragraph 節點陣列。
 * 規則：以空行為段落界、段內多行用 hardBreak 串接；首尾空行修剪。
 */
function buildTextNodes(schema, lines) {
    const { paragraph, hardBreak } = schema.nodes
    if (!paragraph) return []
    // 修剪首尾空行
    let start = 0
    let end = lines.length
    while (start < end && lines[start].trim() === '') start++
    while (end > start && lines[end - 1].trim() === '') end--
    if (start >= end) return []
    const trimmed = lines.slice(start, end)
    // 依空行分段
    const blocks = []
    let cur = []
    for (const ln of trimmed) {
        if (ln.trim() === '') {
            if (cur.length) { blocks.push(cur); cur = [] }
        } else {
            cur.push(ln)
        }
    }
    if (cur.length) blocks.push(cur)
    const nodes = []
    for (const block of blocks) {
        const content = []
        block.forEach((ln, idx) => {
            if (idx > 0 && hardBreak) content.push(hardBreak.create())
            if (ln) content.push(schema.text(ln))
        })
        nodes.push(paragraph.create(null, content))
    }
    return nodes
}

function buildNodes(schema, segments) {
    const nodes = []
    for (const seg of segments) {
        if (seg.kind === 'table') {
            const t = buildTableNode(schema, seg.rows)
            if (t) nodes.push(t)
        } else {
            nodes.push(...buildTextNodes(schema, seg.lines))
        }
    }
    return nodes
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
                        // 快速門檻：必須含至少一個邊框字元，或多於 4 個 |（最少含 2 列 2 欄的痕跡）
                        if (!/[─│┌┐└┘├┤┬┴┼═]/.test(text) &&
                            (text.match(/\|/g) || []).length < 4) {
                            return false
                        }
                        const segments = scanSegments(text)
                        // 至少要掃到一個表格才介入；否則放手
                        if (!segments.some(s => s.kind === 'table')) return false
                        const nodes = buildNodes(view.state.schema, segments)
                        if (!nodes.length) return false
                        const frag = Fragment.fromArray(nodes)
                        const slice = new Slice(frag, 0, 0)
                        const tr = view.state.tr.replaceSelection(slice)
                        view.dispatch(tr.scrollIntoView())
                        return true
                    },
                },
            }),
        ]
    },
})
