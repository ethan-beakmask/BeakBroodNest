/**
 * NodeIdExtension -- 為 Tiptap 結構性節點補 stable nodeId
 *
 * 設計（見原子 #4389）：
 *   - 透過 addGlobalAttributes 給結構性節點型別注入 nodeId attribute（含 parseHTML/renderHTML）
 *   - 透過 ProseMirror Plugin 的 view.update 偵測缺 ID 的節點，async 向後端 API 取 ID 後寫回
 *   - 寫回時 setMeta('addToHistory', false)，避免污染 undo stack
 *   - 失敗 retry 一次；仍失敗則保留 null（後端 atoms PUT/POST 守門會兜底）
 *   - 為避免併發發送重複請求，inflight set 以 pos+type 為簽名
 *
 * 結構性節點清單必須與 scripts/backfill_tiptap_node_id.py / core/tiptap_node_id.py 同步。
 */
import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'

export const STRUCTURAL_NODE_TYPES = [
    'structuredEntry',
    'image',
    'imageAlbum',
    'htmlBlock',
    'pdfThumbnail',
    'pdfReader',
    'mermaidBlock',
    'heading',
    'table',
    'taskList',
    'taskItem',
    'bulletList',
    'orderedList',
    'blockquote',
    'codeBlock',
]

const STRUCTURAL_SET = new Set(STRUCTURAL_NODE_TYPES)

// 後端 API endpoint（與 routes/tiptap_node.py 對齊）
const API_NEXT_ID = '/beakbroodnest/api/tiptap/next-id'
const API_NEXT_IDS = '/beakbroodnest/api/tiptap/next-ids'

async function fetchSingleId() {
    const res = await fetch(API_NEXT_ID, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
    if (!res.ok) throw new Error('next-id HTTP ' + res.status)
    const data = await res.json()
    if (typeof data.id !== 'number') throw new Error('next-id 回傳缺 id')
    return data.id
}

async function fetchBatchIds(count) {
    const res = await fetch(API_NEXT_IDS, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ count }),
    })
    if (!res.ok) throw new Error('next-ids HTTP ' + res.status)
    const data = await res.json()
    if (!Array.isArray(data.ids) || data.ids.length !== count) throw new Error('next-ids 回傳長度錯誤')
    return data.ids
}

async function fetchIdsWithRetry(count) {
    try {
        return count === 1 ? [await fetchSingleId()] : await fetchBatchIds(count)
    } catch (e) {
        // retry 一次
        try {
            return count === 1 ? [await fetchSingleId()] : await fetchBatchIds(count)
        } catch (e2) {
            console.warn('[NodeIdExtension] 取 ID 失敗 (已重試):', e2)
            return null
        }
    }
}

export const NodeIdExtension = Extension.create({
    name: 'nodeId',

    addGlobalAttributes() {
        return [
            {
                types: STRUCTURAL_NODE_TYPES,
                attributes: {
                    nodeId: {
                        default: null,
                        parseHTML: (el) => {
                            const v = el.getAttribute('data-node-id')
                            if (v == null || v === '') return null
                            const n = parseInt(v, 10)
                            return Number.isFinite(n) ? n : null
                        },
                        renderHTML: (attrs) => {
                            if (attrs.nodeId == null) return {}
                            return { 'data-node-id': String(attrs.nodeId) }
                        },
                        keepOnSplit: false,  // split 出新節點時不繼承來源 ID（會由 plugin 後補）
                    },
                },
            },
        ]
    },

    addProseMirrorPlugins() {
        // 簽名：pos+type，避免重複 fetch；fetch 完不論成敗都 delete
        const inflight = new Set()
        // 上一次掃描結束時的 doc，避免 doc 沒變還重跑
        let lastDocRef = null

        const ensureIds = (view) => {
            if (view.isDestroyed) return
            if (view.state.doc === lastDocRef) return
            lastDocRef = view.state.doc

            const targets = []
            view.state.doc.descendants((node, pos) => {
                if (!STRUCTURAL_SET.has(node.type.name)) return
                if (node.attrs.nodeId != null) return
                const sig = pos + ':' + node.type.name
                if (inflight.has(sig)) return
                targets.push({ pos, typeName: node.type.name, sig })
                return true  // 繼續走訪子節點（巢套也可能缺）
            })
            if (targets.length === 0) return

            targets.forEach((t) => inflight.add(t.sig))

            // 取 ID（單一節點走 single API；多節點走 batch）
            fetchIdsWithRetry(targets.length).then((ids) => {
                targets.forEach((t) => inflight.delete(t.sig))
                if (!ids || view.isDestroyed) return

                const state = view.state
                let tr = state.tr
                let any = false
                targets.forEach((t, i) => {
                    const id = ids[i]
                    if (id == null) return
                    // 重新比對：doc 可能已變動，必須以當前 doc 為準
                    const cur = state.doc.nodeAt(t.pos)
                    if (!cur || cur.type.name !== t.typeName) return
                    if (cur.attrs.nodeId != null) return
                    tr = tr.setNodeAttribute(t.pos, 'nodeId', id)
                    any = true
                })
                if (any) {
                    tr = tr.setMeta('addToHistory', false)
                    view.dispatch(tr)
                }
            })
        }

        return [
            new Plugin({
                key: new PluginKey('nodeIdAutoFill'),
                view(view) {
                    // 初始掃描（載入既有 atom 時 → 大多已被後端守門補過，這邊只兜底）
                    setTimeout(() => ensureIds(view), 0)
                    return {
                        update(view, prevState) {
                            if (view.state.doc !== prevState.doc) {
                                ensureIds(view)
                            }
                        },
                        destroy() {
                            inflight.clear()
                            lastDocRef = null
                        },
                    }
                },
            }),
        ]
    },
})
