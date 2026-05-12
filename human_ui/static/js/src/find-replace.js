/**
 * FindReplace -- 卡片內字串搜尋／取代
 *
 * 範圍：當前卡片內的 PM 原生文字（段落 / heading / list / table cell / blockquote
 *       / code mark 之 text 等）。NodeView 內字串（structuredEntry fieldValues、
 *       Mermaid source、htmlBlock source）不在搜尋範圍。
 * 大小寫：一律不分（toLowerCase 比對）。
 * 熱鍵：Mod-Shift-f 開搜尋、Mod-Shift-h 開取代；交由 Alpine UI 接住 CustomEvent
 *       'ce:open-find' / 'ce:open-replace' 顯示控制條。
 *
 * 對外 API（從 plugin meta 觸發）：
 *   editor.commands.findReplaceSet({ query })
 *   editor.commands.findReplaceNext()
 *   editor.commands.findReplacePrev()
 *   editor.commands.findReplaceClose()
 *   editor.commands.findReplaceReplaceCurrent(replacement)
 *   editor.commands.findReplaceReplaceAll(replacement)
 *   editor.commands.findReplaceGetState()  // 回傳 plain object（不走 dispatch）
 */
import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

const findKey = new PluginKey('findReplace')

function buildMatches(doc, query) {
    if (!query) return []
    const needle = query.toLowerCase()
    const matches = []
    doc.descendants((node, pos) => {
        if (!node.isText) return
        const txt = (node.text || '').toLowerCase()
        if (!txt) return
        let i = 0
        while (true) {
            const idx = txt.indexOf(needle, i)
            if (idx < 0) break
            matches.push({ from: pos + idx, to: pos + idx + needle.length })
            i = idx + Math.max(1, needle.length)
        }
    })
    return matches
}

function buildDecorations(doc, matches, currentIdx) {
    if (!matches.length) return DecorationSet.empty
    const decos = matches.map((m, i) =>
        Decoration.inline(m.from, m.to, {
            class: i === currentIdx ? 'ce-find-hit ce-find-current' : 'ce-find-hit',
        })
    )
    return DecorationSet.create(doc, decos)
}

export const FindReplace = Extension.create({
    name: 'findReplace',

    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: findKey,
                state: {
                    init() {
                        return {
                            query: '',
                            matches: [],
                            currentIdx: -1,
                            decorations: DecorationSet.empty,
                        }
                    },
                    apply(tr, prev, oldState, newState) {
                        const meta = tr.getMeta(findKey)
                        let next = prev

                        // 文件有變動且沒有 meta：以舊 query 重新比對
                        if (!meta && tr.docChanged && prev.query) {
                            const matches = buildMatches(newState.doc, prev.query)
                            const currentIdx = matches.length
                                ? Math.min(Math.max(prev.currentIdx, 0), matches.length - 1)
                                : -1
                            next = {
                                query: prev.query,
                                matches,
                                currentIdx,
                                decorations: buildDecorations(newState.doc, matches, currentIdx),
                            }
                            return next
                        }

                        if (!meta) {
                            // 文件沒變 + 沒 meta：decoration positions 不需 map（PM 不變動），保留
                            return prev
                        }

                        if (meta.action === 'close') {
                            return {
                                query: '',
                                matches: [],
                                currentIdx: -1,
                                decorations: DecorationSet.empty,
                            }
                        }

                        if (meta.action === 'set') {
                            const q = meta.query || ''
                            const matches = buildMatches(newState.doc, q)
                            const currentIdx = matches.length ? 0 : -1
                            return {
                                query: q,
                                matches,
                                currentIdx,
                                decorations: buildDecorations(newState.doc, matches, currentIdx),
                            }
                        }

                        if (meta.action === 'move') {
                            if (!prev.matches.length) return prev
                            const dir = meta.dir
                            const n = prev.matches.length
                            const nextIdx = dir > 0
                                ? (prev.currentIdx + 1) % n
                                : (prev.currentIdx - 1 + n) % n
                            return {
                                ...prev,
                                currentIdx: nextIdx,
                                decorations: buildDecorations(newState.doc, prev.matches, nextIdx),
                            }
                        }

                        if (meta.action === 'recompute') {
                            // 取代後文件已變、需要外部呼叫 recompute 重抓最新 matches
                            const matches = buildMatches(newState.doc, prev.query)
                            const currentIdx = matches.length
                                ? Math.min(meta.preferIdx ?? 0, matches.length - 1)
                                : -1
                            return {
                                query: prev.query,
                                matches,
                                currentIdx,
                                decorations: buildDecorations(newState.doc, matches, currentIdx),
                            }
                        }

                        return prev
                    },
                },
                props: {
                    decorations(state) {
                        const s = findKey.getState(state)
                        return s ? s.decorations : DecorationSet.empty
                    },
                },
            }),
        ]
    },

    addCommands() {
        return {
            findReplaceSet: (query) => ({ tr, dispatch, state }) => {
                if (dispatch) {
                    tr.setMeta(findKey, { action: 'set', query: query || '' })
                    dispatch(tr)
                }
                return true
            },
            findReplaceClose: () => ({ tr, dispatch }) => {
                if (dispatch) {
                    tr.setMeta(findKey, { action: 'close' })
                    dispatch(tr)
                }
                return true
            },
            findReplaceNext: () => ({ tr, dispatch, state }) => {
                const s = findKey.getState(state)
                if (!s || !s.matches.length) return false
                if (dispatch) {
                    tr.setMeta(findKey, { action: 'move', dir: 1 })
                    dispatch(tr)
                }
                return true
            },
            findReplacePrev: () => ({ tr, dispatch, state }) => {
                const s = findKey.getState(state)
                if (!s || !s.matches.length) return false
                if (dispatch) {
                    tr.setMeta(findKey, { action: 'move', dir: -1 })
                    dispatch(tr)
                }
                return true
            },
            findReplaceReplaceCurrent: (replacement) => ({ state, dispatch, tr }) => {
                const s = findKey.getState(state)
                if (!s || !s.matches.length || s.currentIdx < 0) return false
                const m = s.matches[s.currentIdx]
                if (!dispatch) return true
                const repl = String(replacement ?? '')
                tr.insertText(repl, m.from, m.to)
                // 取代後讓 plugin 用同 query 重抓 matches，保留下一個 index
                tr.setMeta(findKey, { action: 'recompute', preferIdx: s.currentIdx })
                dispatch(tr)
                return true
            },
            findReplaceReplaceAll: (replacement) => ({ state, dispatch, tr }) => {
                const s = findKey.getState(state)
                if (!s || !s.matches.length) return false
                if (!dispatch) return true
                const repl = String(replacement ?? '')
                // 由後往前避免位移失準
                for (let i = s.matches.length - 1; i >= 0; i--) {
                    const m = s.matches[i]
                    tr.insertText(repl, m.from, m.to)
                }
                tr.setMeta(findKey, { action: 'recompute', preferIdx: -1 })
                dispatch(tr)
                return true
            },
        }
    },

    addKeyboardShortcuts() {
        return {
            'Mod-Shift-f': ({ editor }) => {
                const el = editor.options.element
                if (el) el.dispatchEvent(new CustomEvent('ce:open-find', { bubbles: true }))
                return true
            },
            'Mod-Shift-h': ({ editor }) => {
                if (!editor.options.editable) return false
                const el = editor.options.element
                if (el) el.dispatchEvent(new CustomEvent('ce:open-replace', { bubbles: true }))
                return true
            },
        }
    },
})

export { findKey }
export default FindReplace
