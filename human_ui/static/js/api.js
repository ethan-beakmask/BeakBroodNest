/**
 * BeakCortex API 封裝
 */
const API = {
    async _fetch(url, options = {}) {
        const defaults = { headers: { 'Content-Type': 'application/json' } };
        const resp = await fetch(url, { ...defaults, ...options });
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
        return this.get('/api/atoms' + (q ? '?' + q : ''));
    },
    getAtom(id)             { return this.get('/api/atoms/' + id); },
    getBlockChain(id)       { return this.get('/api/atoms/' + id + '/block-chain'); },
    createAtom(data)        { return this.post('/api/atoms', data); },
    updateAtom(id, data)    { return this.put('/api/atoms/' + id, data); },
    deleteAtom(id)          { return this.del('/api/atoms/' + id); },

    // Canvases
    getCanvases()           { return this.get('/api/canvases'); },
    getCanvas(id)           { return this.get('/api/canvases/' + id); },
    createCanvas(data)      { return this.post('/api/canvases', data); },
    updateCanvas(id, data)  { return this.put('/api/canvases/' + id, data); },
    deleteCanvas(id)        { return this.del('/api/canvases/' + id); },

    // Canvas Atoms
    addAtomToCanvas(canvasId, data) { return this.post('/api/canvases/' + canvasId + '/atoms', data); },
    updateCanvasAtom(caId, data)    { return this.put('/api/canvas-atoms/' + caId, data); },
    removeCanvasAtom(caId)          { return this.del('/api/canvas-atoms/' + caId); },

    // Canvas Groups
    createGroup(canvasId, data) { return this.post('/api/canvases/' + canvasId + '/groups', data); },
    updateGroup(id, data)      { return this.put('/api/canvas-groups/' + id, data); },
    deleteGroup(id)            { return this.del('/api/canvas-groups/' + id); },

    // Canvas Connections
    createConnection(data)  { return this.post('/api/canvas-connections', data); },
    updateConnection(id, data) { return this.put('/api/canvas-connections/' + id, data); },
    deleteConnection(id)    { return this.del('/api/canvas-connections/' + id); },

    // Search
    searchSemantic(q, limit) {
        var params = new URLSearchParams({ q: q, limit: limit || 10 });
        return this.get('/api/search/hybrid?' + params.toString());
    },

    // Tags
    getTags()               { return this.get('/api/tags'); },
    createTag(data)         { return this.post('/api/tags', data); },
    updateTag(id, data)     { return this.put('/api/tags/' + id, data); },
    deleteTag(id)           { return this.del('/api/tags/' + id); },

    // Tag Categories
    getTagCategories()              { return this.get('/api/tag-categories'); },
    createTagCategory(data)         { return this.post('/api/tag-categories', data); },
    updateTagCategory(id, data)     { return this.put('/api/tag-categories/' + id, data); },
    deleteTagCategory(id)           { return this.del('/api/tag-categories/' + id); },
};
