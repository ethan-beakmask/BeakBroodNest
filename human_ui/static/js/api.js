/**
 * BeakBroodNest API 封裝
 */

// AES-256-GCM session key — 透明加密所有 POST/PUT/PATCH/DELETE body
const _bbnCrypto = (() => {
    let _keyPromise = null;

    async function _importKey(b64) {
        const keyBytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
        return crypto.subtle.importKey('raw', keyBytes, 'AES-GCM', false, ['encrypt']);
    }

    async function _fetchKey() {
        // 優先讀 server 在 HTML 模板中嵌入的 key — 沒有 fetch 就沒有 cookie race
        if (typeof window !== 'undefined' && window.__BBN_AES_KEY) {
            return _importKey(window.__BBN_AES_KEY);
        }
        // Fallback: 模板未注入時走 endpoint(self-heal 後 retry 也走這條)
        const resp = await fetch('/beakbroodnest/api/session-key', {
            cache: 'no-store',
            credentials: 'same-origin',
            headers: { 'Cache-Control': 'no-cache' },
        });
        if (!resp.ok) throw new Error('session-key fetch failed: ' + resp.status);
        const { key } = await resp.json();
        return _importKey(key);
    }

    function _getKey() {
        if (!_keyPromise) _keyPromise = _fetchKey().catch(e => { _keyPromise = null; throw e; });
        return _keyPromise;
    }

    function invalidateKey() {
        _keyPromise = null;
        // 同步清掉 HTML 嵌入的 key — 否則 self-heal 重抓會再拿到同一把過期的 key
        if (typeof window !== 'undefined') window.__BBN_AES_KEY = '';
    }

    async function encrypt(plainObj) {
        const cryptoKey = await _getKey();
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const plain = new TextEncoder().encode(JSON.stringify(plainObj));
        const cipher = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, cryptoKey, plain);
        const combined = new Uint8Array(12 + cipher.byteLength);
        combined.set(iv);
        combined.set(new Uint8Array(cipher), 12);
        // btoa via charCode is safe for arbitrary binary
        return btoa(Array.from(combined, b => String.fromCharCode(b)).join(''));
    }

    // 預先取得 key，頁面載入後立即暖機
    function warmup() { _getKey().catch(() => {}); }

    return { encrypt, warmup, invalidateKey };
})();

const API = {
    async _fetch(url, options = {}) {
        const defaults = { headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin' };
        const merged = { ...defaults, ...options };

        const method = (merged.method || 'GET').toUpperCase();
        const needsEncrypt = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) && merged.body;
        const plainBody = needsEncrypt ? merged.body : null;

        async function send() {
            const req = { ...merged };
            if (needsEncrypt) {
                const plainObj = JSON.parse(plainBody);
                const enc = await _bbnCrypto.encrypt(plainObj);
                req.body = JSON.stringify({ _enc: enc });
            }
            return fetch(url, req);
        }

        let resp = await send();

        // 422 + aes_key_missing/invalid：server session 失去 _aes_key 或 key 已輪替，
        // 清掉本地 key cache 重抓一次（self-heal）。只重試一次避免無限循環。
        if (resp.status === 422 && needsEncrypt) {
            const peek = await resp.clone().json().catch(() => null);
            if (peek && (peek.code === 'aes_key_missing' || peek.code === 'aes_key_invalid')) {
                _bbnCrypto.invalidateKey();
                resp = await send();
            }
        }

        if (resp.status === 401) {
            window.location.href = '/beakbroodnest/login';
            throw new Error('未登入');
        }
        if (!resp.ok) {
            const body = await resp.json().catch(() => ({ error: resp.statusText }));
            const err = new Error(body.error || resp.statusText);
            err.status = resp.status;
            err.body = body;
            throw err;
        }
        return resp.json();
    },

    get(url) { return this._fetch(url); },
    post(url, data) { return this._fetch(url, { method: 'POST', body: JSON.stringify(data) }); },
    put(url, data) { return this._fetch(url, { method: 'PUT', body: JSON.stringify(data) }); },
    del(url) { return this._fetch(url, { method: 'DELETE' }); },

    // Atoms
    getAtoms(params = {}) {
        const q = new URLSearchParams(params).toString();
        return this.get('/beakbroodnest/api/atoms' + (q ? '?' + q : ''));
    },
    getAtom(id)             { return this.get('/beakbroodnest/api/atoms/' + id); },
    getBlockChain(id)       { return this.get('/beakbroodnest/api/atoms/' + id + '/block-chain'); },
    createAtom(data)        { return this.post('/beakbroodnest/api/atoms', data); },
    updateAtom(id, data)    { return this.put('/beakbroodnest/api/atoms/' + id, data); },
    deleteAtom(id)          { return this.del('/beakbroodnest/api/atoms/' + id); },          // 軟刪除（舊全域字紙簍，仍保留作 API）
    hardDeleteAtom(id)      { return this.del('/beakbroodnest/api/atoms/' + id + '/hard'); },// 真徹底刪除
    getAtomUsage(id)        { return this.get('/beakbroodnest/api/atoms/' + id + '/usage'); },// 此 atom 在哪些白板/包/字紙簍
    listTrash()             { return this.get('/beakbroodnest/api/atoms/trash'); },           // 全域字紙簍（已不再被白板 UI 使用）
    restoreAtom(id, data)   { return this.post('/beakbroodnest/api/atoms/' + id + '/restore', data); },
    emptyTrash()            { return this.del('/beakbroodnest/api/atoms/trash/empty'); },

    // Canvas Trash (白板私有字紙簍)
    addToCanvasTrash(slug, atomIds) { return this.post('/beakbroodnest/api/canvases/' + slug + '/trash', { atom_ids: atomIds }); },
    listCanvasTrash(slug)           { return this.get('/beakbroodnest/api/canvases/' + slug + '/trash'); },
    restoreFromCanvasTrash(slug, atomIds) { return this.post('/beakbroodnest/api/canvases/' + slug + '/trash/restore', { atom_ids: atomIds }); },
    emptyCanvasTrash(slug)          { return this.del('/beakbroodnest/api/canvases/' + slug + '/trash'); },

    // Canvases
    getCanvases(includeArchived) { return this.get('/beakbroodnest/api/canvases' + (includeArchived ? '?include_archived=1' : '')); },
    getProjectCanvases() { return this.get('/beakbroodnest/api/canvases?only_projects=1'); },
    getPreference(key) { return this.get('/beakbroodnest/api/preferences/' + encodeURIComponent(key)); },
    setPreference(key, value) { return this.put('/beakbroodnest/api/preferences/' + encodeURIComponent(key), { value: value }); },
    getCanvas(id)           { return this.get('/beakbroodnest/api/canvases/' + id); },
    createCanvas(data)      { return this.post('/beakbroodnest/api/canvases', data); },
    updateCanvas(id, data)  { return this.put('/beakbroodnest/api/canvases/' + id, data); },
    deleteCanvas(id)        { return this.del('/beakbroodnest/api/canvases/' + id); },
    pollCanvas(slug, since)  {
        var url = '/beakbroodnest/api/canvases/' + slug + '/poll';
        if (since) url += '?since=' + encodeURIComponent(since);
        return this.get(url);
    },

    // Canvas Atoms
    addAtomToCanvas(canvasId, data) { return this.post('/beakbroodnest/api/canvases/' + canvasId + '/atoms', data); },
    updateCanvasAtom(caId, data)    { return this.put('/beakbroodnest/api/canvas-atoms/' + caId, data); },
    removeCanvasAtom(caId)          { return this.del('/beakbroodnest/api/canvas-atoms/' + caId); },

    // Canvas Groups
    createGroup(canvasId, data) { return this.post('/beakbroodnest/api/canvases/' + canvasId + '/groups', data); },
    updateGroup(id, data)      { return this.put('/beakbroodnest/api/canvas-groups/' + id, data); },
    deleteGroup(id)            { return this.del('/beakbroodnest/api/canvas-groups/' + id); },

    // Canvas Textboxes (獨立文字框)
    createTextbox(canvasId, data) { return this.post('/beakbroodnest/api/canvases/' + canvasId + '/textboxes', data); },
    updateTextbox(id, data)       { return this.put('/beakbroodnest/api/canvas-textboxes/' + id, data); },
    deleteTextbox(id)             { return this.del('/beakbroodnest/api/canvas-textboxes/' + id); },
    addTextboxesToCanvasTrash(slug, ids) {
        return this.post('/beakbroodnest/api/canvases/' + slug + '/trash/textboxes', { textbox_ids: ids });
    },
    restoreTextboxesFromTrash(slug, trashIds) {
        return this.post('/beakbroodnest/api/canvases/' + slug + '/trash/textboxes/restore', { trash_ids: trashIds });
    },

    // Canvas Connections
    createConnection(data)  { return this.post('/beakbroodnest/api/canvas-connections', data); },
    updateConnection(id, data) { return this.put('/beakbroodnest/api/canvas-connections/' + id, data); },
    deleteConnection(id)    { return this.del('/beakbroodnest/api/canvas-connections/' + id); },

    // Exchange Packs (交換卡片)
    getExchangePacks()                  { return this.get('/beakbroodnest/api/exchange-packs'); },
    createExchangePack(data)            { return this.post('/beakbroodnest/api/exchange-packs', data); },
    getExchangePack(packId)             { return this.get('/beakbroodnest/api/exchange-packs/' + packId); },
    takeFromExchangePack(packId, data)  { return this.post('/beakbroodnest/api/exchange-packs/' + packId + '/take', data); },
    removeAtomsFromPack(packId, atomIds) {
        return this._fetch('/beakbroodnest/api/exchange-packs/' + packId + '/atoms', {
            method: 'DELETE',
            body: JSON.stringify({ atom_ids: atomIds }),
        });
    },
    deleteExchangePack(packId)          { return this.del('/beakbroodnest/api/exchange-packs/' + packId); },

    // Search
    searchSemantic(q, limit) {
        var params = new URLSearchParams({ q: q, limit: limit || 10 });
        return this.get('/beakbroodnest/api/search/hybrid?' + params.toString());
    },

    // Tags
    getTags(params = {}) {
        const q = new URLSearchParams(params).toString();
        return this.get('/beakbroodnest/api/tags' + (q ? '?' + q : ''));
    },
    createTag(data)         { return this.post('/beakbroodnest/api/tags', data); },
    updateTag(id, data)     { return this.put('/beakbroodnest/api/tags/' + id, data); },
    deleteTag(id)           { return this.del('/beakbroodnest/api/tags/' + id); },

    // Tag Categories
    getTagCategories()              { return this.get('/beakbroodnest/api/tag-categories'); },
    createTagCategory(data)         { return this.post('/beakbroodnest/api/tag-categories', data); },
    updateTagCategory(id, data)     { return this.put('/beakbroodnest/api/tag-categories/' + id, data); },
    deleteTagCategory(id)           { return this.del('/beakbroodnest/api/tag-categories/' + id); },

    // Entry Schemas
    getEntrySchemas()               { return this.get('/beakbroodnest/api/entry-schemas'); },
    createEntrySchema(data)         { return this.post('/beakbroodnest/api/entry-schemas', data); },
    updateEntrySchema(id, data)     { return this.put('/beakbroodnest/api/entry-schemas/' + id, data); },
    deleteEntrySchema(id)           { return this.del('/beakbroodnest/api/entry-schemas/' + id); },

    // Atom Entries
    getEntries(atomId)              { return this.get('/beakbroodnest/api/atoms/' + atomId + '/entries'); },
    createEntry(atomId, data)       { return this.post('/beakbroodnest/api/atoms/' + atomId + '/entries', data); },
    getEntry(id)                    { return this.get('/beakbroodnest/api/entries/' + id); },
    updateEntry(id, data)           { return this.put('/beakbroodnest/api/entries/' + id, data); },
    deleteEntry(id)                 { return this.del('/beakbroodnest/api/entries/' + id); },
    syncEntries(atomId, entries)    { return this.post('/beakbroodnest/api/atoms/' + atomId + '/entries/sync', { entries: entries }); },
    taskAction(atomId, action, reason, source) {
        return this.post('/beakbroodnest/api/atoms/' + atomId + '/task/action', {
            action: action, reason: reason || '', source: source || 'card',
        });
    },

    // Entry Schema Fields
    getEntrySchemaFields(schemaId)  { return this.get('/beakbroodnest/api/entry-schemas/' + schemaId + '/fields'); },
    createEntrySchemaField(schemaId, data) { return this.post('/beakbroodnest/api/entry-schemas/' + schemaId + '/fields', data); },
    updateEntrySchemaField(id, data) { return this.put('/beakbroodnest/api/entry-schema-fields/' + id, data); },
    deleteEntrySchemaField(id)      { return this.del('/beakbroodnest/api/entry-schema-fields/' + id); },
    reorderEntrySchemaFields(schemaId, fieldIds) { return this.put('/beakbroodnest/api/entry-schemas/' + schemaId + '/fields/reorder', { field_ids: fieldIds }); },

    // Unified Relations
    getUnifiedRelations(params)     { var q = new URLSearchParams(params || {}).toString(); return this.get('/beakbroodnest/api/unified-relations' + (q ? '?' + q : '')); },
    createUnifiedRelation(data)     { return this.post('/beakbroodnest/api/unified-relations', data); },
    updateUnifiedRelation(id, data) { return this.put('/beakbroodnest/api/unified-relations/' + id, data); },
    deleteUnifiedRelation(id)       { return this.del('/beakbroodnest/api/unified-relations/' + id); },

    // Canvas Mindmap Shells (心智圖殼 + 樹結構)
    createMindmapShell(slug, data)         { return this.post('/beakbroodnest/api/canvases/' + slug + '/mindmap-shells', data); },
    updateMindmapShell(shellId, data)      { return this.put('/beakbroodnest/api/canvas-mindmap-shells/' + shellId, data); },
    deleteMindmapShell(shellId, mode)      {
        var url = '/beakbroodnest/api/canvas-mindmap-shells/' + shellId;
        if (mode) url += '?mode=' + encodeURIComponent(mode);
        return this.del(url);
    },
    addMindmapNode(shellId, data)          { return this.post('/beakbroodnest/api/canvas-mindmap-shells/' + shellId + '/nodes', data); },
    attachMindmapAtom(shellId, atomId, parentAtomId, includeSubtree) {
        return this.post('/beakbroodnest/api/canvas-mindmap-shells/' + shellId + '/attach', {
            atom_id: atomId,
            parent_atom_id: parentAtomId,
            include_subtree: !!includeSubtree,
        });
    },
    moveMindmapNode(shellId, atomId, data) { return this.put('/beakbroodnest/api/canvas-mindmap-shells/' + shellId + '/nodes/' + atomId + '/move', data); },
    deleteMindmapNode(shellId, atomId)     { return this.del('/beakbroodnest/api/canvas-mindmap-shells/' + shellId + '/nodes/' + atomId); },
    extractMindmapSubtree(shellId, atomId, opts) {
        var body = Object.assign({ atom_id: atomId }, opts || {});
        return this.post('/beakbroodnest/api/canvas-mindmap-shells/' + shellId + '/extract', body);
    },
    transferMindmapShell(shellId, targetSlug, mode) {
        return this.post('/beakbroodnest/api/canvas-mindmap-shells/' + shellId + '/transfer', {
            target_canvas_slug: targetSlug,
            mode: mode,
        });
    },
    transferTextbox(tbId, targetSlug, mode) {
        return this.post('/beakbroodnest/api/canvas-textboxes/' + tbId + '/transfer', {
            target_canvas_slug: targetSlug,
            mode: mode,
        });
    },

    // Promote entry to atom
    promoteEntry(entryId)           { return this.post('/beakbroodnest/api/entries/' + entryId + '/promote', {}); },

    // File upload (multipart/form-data, 不能用 _fetch)
    async uploadFile(file, kind) {
        var fd = new FormData();
        fd.append('file', file);
        if (kind) fd.append('kind', kind);
        var resp = await fetch('/beakbroodnest/api/files/upload', {
            method: 'POST',
            body: fd,
        });
        if (resp.status === 401) {
            window.location.href = '/beakbroodnest/login';
            throw new Error('未登入');
        }
        if (!resp.ok) {
            var err = await resp.json().catch(function() { return { error: resp.statusText }; });
            throw new Error(err.error || resp.statusText);
        }
        return resp.json();
    },
};

// 頁面載入後立即暖機 session key（減少首次 POST 延遲）
_bbnCrypto.warmup();
