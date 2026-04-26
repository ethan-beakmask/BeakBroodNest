/**
 * BeakCortex PDF utilities
 *
 * 用 pdfjs-dist 在 client side 提供：
 *   - renderFirstPageThumbnail(source, maxWidth) -> Promise<dataURL>
 *   - extractAllText(source) -> Promise<string>
 *   - getPageCount(source) -> Promise<number>
 *
 * source 接受 File / Blob / URL 字串。
 *
 * 載入採 lazy import：第一次呼叫時才動態載入 pdfjs ESM module，
 * 避免白板首次載入時就吃 1.6MB worker。
 */

const PDFJS_BASE = '/beakcortex/static/vendor/pdfjs/';
let _pdfjsPromise = null;

async function _loadPdfjs() {
    if (_pdfjsPromise) return _pdfjsPromise;
    _pdfjsPromise = (async () => {
        const mod = await import(PDFJS_BASE + 'pdf.min.mjs');
        mod.GlobalWorkerOptions.workerSrc = PDFJS_BASE + 'pdf.worker.min.mjs';
        return mod;
    })();
    return _pdfjsPromise;
}

async function _loadDocument(source) {
    const pdfjs = await _loadPdfjs();
    let task;
    if (source instanceof Blob) {
        const buf = await source.arrayBuffer();
        task = pdfjs.getDocument({ data: buf });
    } else {
        task = pdfjs.getDocument({ url: source });
    }
    return task.promise;
}

window.PdfUtils = {
    async getPageCount(source) {
        const doc = await _loadDocument(source);
        const n = doc.numPages;
        try { await doc.destroy(); } catch (e) {}
        return n;
    },

    /** 渲染第一頁為 PNG dataURL，maxWidth 控制縮圖寬度 */
    async renderFirstPageThumbnail(source, maxWidth) {
        maxWidth = maxWidth || 320;
        const doc = await _loadDocument(source);
        try {
            const page = await doc.getPage(1);
            const viewport0 = page.getViewport({ scale: 1.0 });
            const scale = maxWidth / viewport0.width;
            const viewport = page.getViewport({ scale });
            const canvas = document.createElement('canvas');
            canvas.width = Math.ceil(viewport.width);
            canvas.height = Math.ceil(viewport.height);
            const ctx = canvas.getContext('2d');
            await page.render({ canvasContext: ctx, viewport, canvas }).promise;
            return canvas.toDataURL('image/png');
        } finally {
            try { await doc.destroy(); } catch (e) {}
        }
    },

    /** 抽取整份 PDF 的純文字（按頁分隔） */
    async extractAllText(source) {
        const doc = await _loadDocument(source);
        try {
            const out = [];
            for (let i = 1; i <= doc.numPages; i++) {
                const page = await doc.getPage(i);
                const tc = await page.getTextContent();
                const txt = tc.items.map(it => it.str).join(' ');
                out.push(txt.trim());
            }
            return out.join('\n\n');
        } finally {
            try { await doc.destroy(); } catch (e) {}
        }
    },
};
