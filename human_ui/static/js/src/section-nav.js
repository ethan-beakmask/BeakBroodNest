/**
 * Section Navigator -- 列出 H1~H4 章節，點擊跳到對應位置。
 * 純 UI 不改變內容；用 vanilla DOM 建 modal，鍵盤可操作。
 */

function collectHeadings(editor) {
    const out = []
    editor.state.doc.descendants((node, pos) => {
        if (node.type.name === 'heading') {
            const level = node.attrs.level || 1
            if (level >= 1 && level <= 4) {
                out.push({ level, text: node.textContent || '(無標題)', pos })
            }
        }
    })
    return out
}

function jumpTo(editor, pos) {
    const tr = editor.state.tr
    const resolved = tr.doc.resolve(pos + 1)
    editor.chain()
        .focus()
        .setTextSelection(resolved.pos)
        .run()
    // 把該 heading 的 DOM node 對齊到可捲動容器頂端
    requestAnimationFrame(() => {
        let dom = null
        try { dom = editor.view.nodeDOM(pos) } catch (e) { dom = null }
        if (!dom || dom.nodeType !== 1) {
            try {
                const at = editor.view.domAtPos(pos + 1)
                dom = at && at.node
                while (dom && dom.nodeType !== 1) dom = dom.parentNode
            } catch (e) { /* ignore */ }
        }
        if (dom && typeof dom.scrollIntoView === 'function') {
            dom.scrollIntoView({ block: 'start', inline: 'nearest' })
        }
    })
}

let _activeModal = null

export function openSectionNav(editor) {
    if (!editor) return
    if (_activeModal) closeModal()

    const headings = collectHeadings(editor)

    const overlay = document.createElement('div')
    overlay.className = 'sn-overlay'
    overlay.style.cssText = `
        position: fixed; inset: 0; background: rgba(0,0,0,0.5);
        z-index: 10000; display: flex; align-items: center; justify-content: center;
    `

    const panel = document.createElement('div')
    panel.className = 'sn-panel'
    panel.style.cssText = `
        background: #1e293b; color: #e2e8f0;
        border: 1px solid rgba(255,255,255,0.15); border-radius: 6px;
        width: 520px; max-width: 90vw; max-height: 70vh;
        display: flex; flex-direction: column; box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    `

    const header = document.createElement('div')
    header.style.cssText = `
        padding: 10px 14px; border-bottom: 1px solid rgba(255,255,255,0.1);
        display: flex; align-items: center; justify-content: space-between;
        font-size: 13px; font-weight: 600;
    `
    header.innerHTML = `
        <span>章節導覽</span>
        <span style="font-size:11px;color:#94a3b8;font-weight:400;">↑↓ 選擇 · Enter 跳轉 · Esc 關閉</span>
    `

    const list = document.createElement('div')
    list.style.cssText = `
        flex: 1; overflow-y: auto; padding: 6px 0;
    `

    if (headings.length === 0) {
        const empty = document.createElement('div')
        empty.style.cssText = 'padding: 20px; text-align: center; color: #94a3b8; font-size: 13px;'
        empty.textContent = '此卡片無章節標題（H1~H4）'
        list.appendChild(empty)
    } else {
        headings.forEach((h, idx) => {
            const item = document.createElement('div')
            item.className = 'sn-item'
            item.dataset.idx = idx
            item.style.cssText = `
                padding: 6px 14px 6px ${14 + (h.level - 1) * 18}px;
                cursor: pointer; font-size: 13px;
                display: flex; align-items: center; gap: 8px;
                border-left: 3px solid transparent;
            `
            const tag = document.createElement('span')
            tag.textContent = `H${h.level}`
            tag.style.cssText = `
                color: #64748b; font-size: 10px; font-weight: 700;
                background: rgba(255,255,255,0.05); padding: 1px 5px; border-radius: 2px;
                min-width: 22px; text-align: center;
            `
            const txt = document.createElement('span')
            txt.textContent = h.text
            txt.style.cssText = 'flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;'
            item.appendChild(tag)
            item.appendChild(txt)
            item.addEventListener('mouseenter', () => setActive(idx))
            item.addEventListener('click', () => {
                jumpTo(editor, h.pos)
                closeModal()
            })
            list.appendChild(item)
        })
    }

    panel.appendChild(header)
    panel.appendChild(list)
    overlay.appendChild(panel)
    document.body.appendChild(overlay)

    let activeIdx = headings.length > 0 ? 0 : -1

    function setActive(idx) {
        if (idx < 0 || idx >= headings.length) return
        activeIdx = idx
        list.querySelectorAll('.sn-item').forEach((el, i) => {
            if (i === idx) {
                el.style.background = 'rgba(59,130,246,0.2)'
                el.style.borderLeftColor = '#3b82f6'
                el.scrollIntoView({ block: 'nearest' })
            } else {
                el.style.background = ''
                el.style.borderLeftColor = 'transparent'
            }
        })
    }

    setActive(activeIdx)

    function onKey(e) {
        if (e.key === 'Escape') {
            e.preventDefault()
            closeModal()
        } else if (e.key === 'ArrowDown') {
            e.preventDefault()
            if (headings.length) setActive((activeIdx + 1) % headings.length)
        } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            if (headings.length) setActive((activeIdx - 1 + headings.length) % headings.length)
        } else if (e.key === 'Enter') {
            e.preventDefault()
            if (activeIdx >= 0) {
                jumpTo(editor, headings[activeIdx].pos)
                closeModal()
            }
        }
    }

    function onOverlayClick(e) {
        if (e.target === overlay) closeModal()
    }

    function closeModal() {
        document.removeEventListener('keydown', onKey, true)
        overlay.removeEventListener('click', onOverlayClick)
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay)
        _activeModal = null
    }

    document.addEventListener('keydown', onKey, true)
    overlay.addEventListener('click', onOverlayClick)

    _activeModal = { close: closeModal }
}
