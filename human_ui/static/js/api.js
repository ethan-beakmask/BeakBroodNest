/**
 * BeakCortex API 封裝
 */
const API = {
    async _fetch(url, options = {}) {
        const defaults = { headers: { 'Content-Type': 'application/json' } };
        const resp = await fetch(url, { ...defaults, ...options });
        if (resp.status === 401) {
            window.location.href = '/beakcortex/login';
            throw new Error('未登入');
        }
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ error: resp.statusText }));
            throw new Error(err.error || resp.statusText);
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
        return this.get('/beakcortex/api/atoms' + (q ? '?' + q : ''));
    },
    getAtom(id)             { return this.get('/beakcortex/api/atoms/' + id); },
    getBlockChain(id)       { return this.get('/beakcortex/api/atoms/' + id + '/block-chain'); },
    createAtom(data)        { return this.post('/beakcortex/api/atoms', data); },
    updateAtom(id, data)    { return this.put('/beakcortex/api/atoms/' + id, data); },
    deleteAtom(id)          { return this.del('/beakcortex/api/atoms/' + id); },          // 軟刪除（舊全域字紙簍，仍保留作 API）
    hardDeleteAtom(id)      { return this.del('/beakcortex/api/atoms/' + id + '/hard'); },// 真徹底刪除
    getAtomUsage(id)        { return this.get('/beakcortex/api/atoms/' + id + '/usage'); },// 此 atom 在哪些白板/包/字紙簍
    listTrash()             { return this.get('/beakcortex/api/atoms/trash'); },           // 全域字紙簍（已不再被白板 UI 使用）
    restoreAtom(id, data)   { return this.post('/beakcortex/api/atoms/' + id + '/restore', data); },
    emptyTrash()            { return this.del('/beakcortex/api/atoms/trash/empty'); },

    // Canvas Trash (白板私有字紙簍)
    addToCanvasTrash(slug, atomIds) { return this.post('/beakcortex/api/canvases/' + slug + '/trash', { atom_ids: atomIds }); },
    listCanvasTrash(slug)           { return this.get('/beakcortex/api/canvases/' + slug + '/trash'); },
    restoreFromCanvasTrash(slug, atomIds) { return this.post('/beakcortex/api/canvases/' + slug + '/trash/restore', { atom_ids: atomIds }); },
    emptyCanvasTrash(slug)          { return this.del('/beakcortex/api/canvases/' + slug + '/trash'); },

    // Canvases
    getCanvases(includeArchived) { return this.get('/beakcortex/api/canvases' + (includeArchived ? '?include_archived=1' : '')); },
    getCanvas(id)           { return this.get('/beakcortex/api/canvases/' + id); },
    createCanvas(data)      { return this.post('/beakcortex/api/canvases', data); },
    updateCanvas(id, data)  { return this.put('/beakcortex/api/canvases/' + id, data); },
    deleteCanvas(id)        { return this.del('/beakcortex/api/canvases/' + id); },
    pollCanvas(slug, since)  {
        var url = '/beakcortex/api/canvases/' + slug + '/poll';
        if (since) url += '?since=' + encodeURIComponent(since);
        return this.get(url);
    },

    // Canvas Atoms
    addAtomToCanvas(canvasId, data) { return this.post('/beakcortex/api/canvases/' + canvasId + '/atoms', data); },
    updateCanvasAtom(caId, data)    { return this.put('/beakcortex/api/canvas-atoms/' + caId, data); },
    removeCanvasAtom(caId)          { return this.del('/beakcortex/api/canvas-atoms/' + caId); },

    // Canvas Groups
    createGroup(canvasId, data) { return this.post('/beakcortex/api/canvases/' + canvasId + '/groups', data); },
    updateGroup(id, data)      { return this.put('/beakcortex/api/canvas-groups/' + id, data); },
    deleteGroup(id)            { return this.del('/beakcortex/api/canvas-groups/' + id); },

    // Canvas Textboxes (獨立文字框)
    createTextbox(canvasId, data) { return this.post('/beakcortex/api/canvases/' + canvasId + '/textboxes', data); },
    updateTextbox(id, data)       { return this.put('/beakcortex/api/canvas-textboxes/' + id, data); },
    deleteTextbox(id)             { return this.del('/beakcortex/api/canvas-textboxes/' + id); },
    addTextboxesToCanvasTrash(slug, ids) {
        return this.post('/beakcortex/api/canvases/' + slug + '/trash/textboxes', { textbox_ids: ids });
    },
    restoreTextboxesFromTrash(slug, trashIds) {
        return this.post('/beakcortex/api/canvases/' + slug + '/trash/textboxes/restore', { trash_ids: trashIds });
    },

    // Canvas Connections
    createConnection(data)  { return this.post('/beakcortex/api/canvas-connections', data); },
    updateConnection(id, data) { return this.put('/beakcortex/api/canvas-connections/' + id, data); },
    deleteConnection(id)    { return this.del('/beakcortex/api/canvas-connections/' + id); },

    // Exchange Packs (交換卡片)
    getExchangePacks()                  { return this.get('/beakcortex/api/exchange-packs'); },
    createExchangePack(data)            { return this.post('/beakcortex/api/exchange-packs', data); },
    getExchangePack(packId)             { return this.get('/beakcortex/api/exchange-packs/' + packId); },
    takeFromExchangePack(packId, data)  { return this.post('/beakcortex/api/exchange-packs/' + packId + '/take', data); },
    removeAtomsFromPack(packId, atomIds) {
        return this._fetch('/beakcortex/api/exchange-packs/' + packId + '/atoms', {
            method: 'DELETE',
            body: JSON.stringify({ atom_ids: atomIds }),
        });
    },
    deleteExchangePack(packId)          { return this.del('/beakcortex/api/exchange-packs/' + packId); },

    // Search
    searchSemantic(q, limit) {
        var params = new URLSearchParams({ q: q, limit: limit || 10 });
        return this.get('/beakcortex/api/search/hybrid?' + params.toString());
    },

    // Tags
    getTags()               { return this.get('/beakcortex/api/tags'); },
    createTag(data)         { return this.post('/beakcortex/api/tags', data); },
    updateTag(id, data)     { return this.put('/beakcortex/api/tags/' + id, data); },
    deleteTag(id)           { return this.del('/beakcortex/api/tags/' + id); },

    // Tag Categories
    getTagCategories()              { return this.get('/beakcortex/api/tag-categories'); },
    createTagCategory(data)         { return this.post('/beakcortex/api/tag-categories', data); },
    updateTagCategory(id, data)     { return this.put('/beakcortex/api/tag-categories/' + id, data); },
    deleteTagCategory(id)           { return this.del('/beakcortex/api/tag-categories/' + id); },

    // Entry Schemas
    getEntrySchemas()               { return this.get('/beakcortex/api/entry-schemas'); },
    createEntrySchema(data)         { return this.post('/beakcortex/api/entry-schemas', data); },
    updateEntrySchema(id, data)     { return this.put('/beakcortex/api/entry-schemas/' + id, data); },
    deleteEntrySchema(id)           { return this.del('/beakcortex/api/entry-schemas/' + id); },

    // Atom Entries
    getEntries(atomId)              { return this.get('/beakcortex/api/atoms/' + atomId + '/entries'); },
    createEntry(atomId, data)       { return this.post('/beakcortex/api/atoms/' + atomId + '/entries', data); },
    getEntry(id)                    { return this.get('/beakcortex/api/entries/' + id); },
    updateEntry(id, data)           { return this.put('/beakcortex/api/entries/' + id, data); },
    deleteEntry(id)                 { return this.del('/beakcortex/api/entries/' + id); },
    syncEntries(atomId, entries)    { return this.post('/beakcortex/api/atoms/' + atomId + '/entries/sync', { entries: entries }); },

    // Entry Schema Fields
    getEntrySchemaFields(schemaId)  { return this.get('/beakcortex/api/entry-schemas/' + schemaId + '/fields'); },
    createEntrySchemaField(schemaId, data) { return this.post('/beakcortex/api/entry-schemas/' + schemaId + '/fields', data); },
    updateEntrySchemaField(id, data) { return this.put('/beakcortex/api/entry-schema-fields/' + id, data); },
    deleteEntrySchemaField(id)      { return this.del('/beakcortex/api/entry-schema-fields/' + id); },
    reorderEntrySchemaFields(schemaId, fieldIds) { return this.put('/beakcortex/api/entry-schemas/' + schemaId + '/fields/reorder', { field_ids: fieldIds }); },

    // Unified Relations
    getUnifiedRelations(params)     { var q = new URLSearchParams(params || {}).toString(); return this.get('/beakcortex/api/unified-relations' + (q ? '?' + q : '')); },
    createUnifiedRelation(data)     { return this.post('/beakcortex/api/unified-relations', data); },
    updateUnifiedRelation(id, data) { return this.put('/beakcortex/api/unified-relations/' + id, data); },
    deleteUnifiedRelation(id)       { return this.del('/beakcortex/api/unified-relations/' + id); },

    // Canvas Mindmap Shells (心智圖殼 + 樹結構)
    createMindmapShell(slug, data)         { return this.post('/beakcortex/api/canvases/' + slug + '/mindmap-shells', data); },
    updateMindmapShell(shellId, data)      { return this.put('/beakcortex/api/canvas-mindmap-shells/' + shellId, data); },
    deleteMindmapShell(shellId, mode)      {
        var url = '/beakcortex/api/canvas-mindmap-shells/' + shellId;
        if (mode) url += '?mode=' + encodeURIComponent(mode);
        return this.del(url);
    },
    addMindmapNode(shellId, data)          { return this.post('/beakcortex/api/canvas-mindmap-shells/' + shellId + '/nodes', data); },
    moveMindmapNode(shellId, atomId, data) { return this.put('/beakcortex/api/canvas-mindmap-shells/' + shellId + '/nodes/' + atomId + '/move', data); },
    deleteMindmapNode(shellId, atomId)     { return this.del('/beakcortex/api/canvas-mindmap-shells/' + shellId + '/nodes/' + atomId); },
    extractMindmapSubtree(shellId, atomId) { return this.post('/beakcortex/api/canvas-mindmap-shells/' + shellId + '/extract', { atom_id: atomId }); },

    // Promote entry to atom
    promoteEntry(entryId)           { return this.post('/beakcortex/api/entries/' + entryId + '/promote', {}); },

    // File upload (multipart/form-data, 不能用 _fetch)
    async uploadFile(file, kind) {
        var fd = new FormData();
        fd.append('file', file);
        if (kind) fd.append('kind', kind);
        var resp = await fetch('/beakcortex/api/files/upload', {
            method: 'POST',
            body: fd,
        });
        if (resp.status === 401) {
            window.location.href = '/beakcortex/login';
            throw new Error('未登入');
        }
        if (!resp.ok) {
            var err = await resp.json().catch(function() { return { error: resp.statusText }; });
            throw new Error(err.error || resp.statusText);
        }
        return resp.json();
    },
};
