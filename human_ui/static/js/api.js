/**
 * BeakCortex API 封裝
 */
const API = {
    async _fetch(url, options = {}) {
        const defaults = { headers: { 'Content-Type': 'application/json' } };
        const resp = await fetch(url, { ...defaults, ...options });
        if (resp.status === 401) {
            window.location.href = '/bc/login';
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
        return this.get('/bc/api/atoms' + (q ? '?' + q : ''));
    },
    getAtom(id)             { return this.get('/bc/api/atoms/' + id); },
    getBlockChain(id)       { return this.get('/bc/api/atoms/' + id + '/block-chain'); },
    createAtom(data)        { return this.post('/bc/api/atoms', data); },
    updateAtom(id, data)    { return this.put('/bc/api/atoms/' + id, data); },
    deleteAtom(id)          { return this.del('/bc/api/atoms/' + id); },

    // Canvases
    getCanvases(includeArchived) { return this.get('/bc/api/canvases' + (includeArchived ? '?include_archived=1' : '')); },
    getCanvas(id)           { return this.get('/bc/api/canvases/' + id); },
    createCanvas(data)      { return this.post('/bc/api/canvases', data); },
    updateCanvas(id, data)  { return this.put('/bc/api/canvases/' + id, data); },
    deleteCanvas(id)        { return this.del('/bc/api/canvases/' + id); },

    // Canvas Atoms
    addAtomToCanvas(canvasId, data) { return this.post('/bc/api/canvases/' + canvasId + '/atoms', data); },
    updateCanvasAtom(caId, data)    { return this.put('/bc/api/canvas-atoms/' + caId, data); },
    removeCanvasAtom(caId)          { return this.del('/bc/api/canvas-atoms/' + caId); },

    // Canvas Groups
    createGroup(canvasId, data) { return this.post('/bc/api/canvases/' + canvasId + '/groups', data); },
    updateGroup(id, data)      { return this.put('/bc/api/canvas-groups/' + id, data); },
    deleteGroup(id)            { return this.del('/bc/api/canvas-groups/' + id); },

    // Canvas Connections
    createConnection(data)  { return this.post('/bc/api/canvas-connections', data); },
    updateConnection(id, data) { return this.put('/bc/api/canvas-connections/' + id, data); },
    deleteConnection(id)    { return this.del('/bc/api/canvas-connections/' + id); },

    // Search
    searchSemantic(q, limit) {
        var params = new URLSearchParams({ q: q, limit: limit || 10 });
        return this.get('/bc/api/search/hybrid?' + params.toString());
    },

    // Tags
    getTags()               { return this.get('/bc/api/tags'); },
    createTag(data)         { return this.post('/bc/api/tags', data); },
    updateTag(id, data)     { return this.put('/bc/api/tags/' + id, data); },
    deleteTag(id)           { return this.del('/bc/api/tags/' + id); },

    // Tag Categories
    getTagCategories()              { return this.get('/bc/api/tag-categories'); },
    createTagCategory(data)         { return this.post('/bc/api/tag-categories', data); },
    updateTagCategory(id, data)     { return this.put('/bc/api/tag-categories/' + id, data); },
    deleteTagCategory(id)           { return this.del('/bc/api/tag-categories/' + id); },
};
