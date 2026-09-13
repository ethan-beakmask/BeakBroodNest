/**
 * PasteImage -- 支援從剪貼簿直接貼上圖片，以及拖放圖片到編輯器。
 *
 * 規則：剪貼簿同時帶有文字時，放行給表格/文字貼上處理；
 * 只有純圖片剪貼簿才攔截、上傳並插入 image node。
 */
import { Extension } from '@tiptap/core'
import { Plugin, PluginKey, TextSelection } from '@tiptap/pm/state'
import { _entryDepth } from './structured-entry.js'

const IMAGE_MIME_EXT = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/webp': 'webp',
    'image/gif': 'gif',
    'image/svg+xml': 'svg',
    'image/bmp': 'bmp',
    'image/x-icon': 'ico',
}

export function collectImageFiles(dataTransfer) {
    if (!dataTransfer) return []

    const files = Array.from(dataTransfer.files || [])
        .filter(file => file.type && file.type.startsWith('image/'))
    if (files.length) return files

    return Array.from(dataTransfer.items || [])
        .filter(item => item.kind === 'file' && item.type && item.type.startsWith('image/'))
        .map(item => item.getAsFile())
        .filter(Boolean)
}

function fallbackNotify(msg, level) {
    if (typeof window !== 'undefined' && typeof window.showToast === 'function') {
        window.showToast(msg, level)
        return
    }
    if (level === 'error') console.error(msg)
    else console.info(msg)
}

function fallbackUpload(file) {
    if (typeof window !== 'undefined' && window.API && typeof window.API.uploadFile === 'function') {
        return window.API.uploadFile(file, 'image')
    }
    return null
}

function hasFallbackUpload() {
    return typeof window !== 'undefined'
        && window.API
        && typeof window.API.uploadFile === 'function'
}

function timestampForName(date = new Date()) {
    const pad = value => String(value).padStart(2, '0')
    return [
        date.getFullYear(),
        pad(date.getMonth() + 1),
        pad(date.getDate()),
        '-',
        pad(date.getHours()),
        pad(date.getMinutes()),
        pad(date.getSeconds()),
    ].join('')
}

function renamedImageFile(file, index) {
    const ext = IMAGE_MIME_EXT[file.type] || 'png'
    const name = `paste-${timestampForName()}-${index}.${ext}`
    return new File([file], name, { type: file.type })
}

function entryDepthAtPos(doc, pos) {
    const $pos = doc.resolve(pos)
    for (let d = $pos.depth; d > 0; d--) {
        if ($pos.node(d).type.name === 'structuredEntry') return d
    }
    return -1
}

function resolveInsertPos(view, dropPos, isFirstFile) {
    const state = view.state
    if (dropPos !== null && isFirstFile) {
        const pos = Math.max(0, Math.min(dropPos, state.doc.content.size))
        const depth = entryDepthAtPos(state.doc, pos)
        if (depth >= 0) return { pos: state.doc.resolve(pos).after(depth), insideEntry: true }
        return { pos, insideEntry: false }
    }

    const depth = _entryDepth(state)
    if (depth >= 0) {
        return { pos: state.selection.$from.after(depth), insideEntry: true }
    }
    return { pos: state.selection.from, insideEntry: false }
}

function setSelectionAfter(tr, pos, node) {
    const after = Math.min(pos + node.nodeSize, tr.doc.content.size)
    return tr.setSelection(TextSelection.near(tr.doc.resolve(after)))
}

async function uploadAndInsert(view, files, dropPos, upload, notify) {
    notify('上傳圖片中...', 'info')
    let inserted = 0

    for (let i = 0; i < files.length; i++) {
        if (view.destroyed || !view.dom.isConnected) return

        const file = renamedImageFile(files[i], i + 1)
        try {
            const rec = await upload(file)
            if (!rec || !rec.url) throw new Error('missing url')
            if (view.destroyed || !view.dom.isConnected) return

            const node = view.state.schema.nodes.image.create({ src: rec.url, alt: file.name })
            const target = resolveInsertPos(view, dropPos, i === 0)
            let tr
            if (!target.insideEntry && dropPos === null) {
                const pos = view.state.selection.from
                tr = view.state.tr.replaceSelectionWith(node)
                tr = setSelectionAfter(tr, pos, node)
            } else {
                tr = view.state.tr.insert(target.pos, node)
                tr = setSelectionAfter(tr, target.pos, node)
            }
            view.dispatch(tr.scrollIntoView())
            inserted++
        } catch (err) {
            notify(`圖片上傳失敗: ${err.message}`, 'error')
        }
    }

    if (inserted > 0) notify(`已插入 ${inserted} 張圖片`, 'success')
}

export const PasteImage = Extension.create({
    name: 'pasteImage',

    addOptions() {
        return {
            upload: null,
            notify: null,
        }
    },

    addProseMirrorPlugins() {
        const upload = this.options.upload || fallbackUpload
        const notify = this.options.notify || fallbackNotify
        const hasUpload = () => Boolean(this.options.upload) || hasFallbackUpload()

        return [
            new Plugin({
                key: new PluginKey('pasteImage'),
                props: {
                    handlePaste: (view, event) => {
                        const dt = event.clipboardData
                        if (!dt) return false

                        const files = collectImageFiles(dt)
                        if (!files.length) return false
                        if ((dt.getData('text/plain') || '').trim()) return false
                        if (!hasUpload()) return false

                        event.preventDefault()
                        uploadAndInsert(view, files, null, upload, notify)
                        return true
                    },

                    handleDrop: (view, event, slice, moved) => {
                        if (moved) return false

                        const files = collectImageFiles(event.dataTransfer)
                        if (!files.length) return false
                        if (!hasUpload()) return false

                        event.preventDefault()
                        event.stopPropagation()
                        const coords = view.posAtCoords({ left: event.clientX, top: event.clientY })
                        const dropPos = coords ? coords.pos : null
                        uploadAndInsert(view, files, dropPos, upload, notify)
                        return true
                    },
                },
            }),
        ]
    },
})
