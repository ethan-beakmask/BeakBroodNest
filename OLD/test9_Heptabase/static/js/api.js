/**
 * API 呼叫封裝
 */
const API = {
    async _fetch(url, options = {}) {
        const defaults = {
            headers: { 'Content-Type': 'application/json' },
        };
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

    // Schema
    getSchemas()            { return this.get('/api/schemas'); },
    getSchema(id)           { return this.get(`/api/schemas/${id}`); },
    createSchema(data)      { return this.post('/api/schemas', data); },
    updateSchema(id, data)  { return this.put(`/api/schemas/${id}`, data); },
    deleteSchema(id)        { return this.del(`/api/schemas/${id}`); },

    // Item
    getItems(schemaId)      { return this.get(`/api/items?schema_id=${schemaId}`); },
    getItem(id)             { return this.get(`/api/items/${id}`); },
    createItem(data)        { return this.post('/api/items', data); },
    updateItem(id, data)    { return this.put(`/api/items/${id}`, data); },
    deleteItem(id)          { return this.del(`/api/items/${id}`); },
    getUnassignedItems(schemaId) {
        const q = schemaId ? `?schema_id=${schemaId}` : '';
        return this.get(`/api/items/unassigned${q}`);
    },

    // Whiteboard
    getWhiteboards()         { return this.get('/api/whiteboards'); },
    getWhiteboard(id)        { return this.get(`/api/whiteboards/${id}`); },
    createWhiteboard(data)   { return this.post('/api/whiteboards', data); },
    updateWhiteboard(id, d)  { return this.put(`/api/whiteboards/${id}`, d); },
    deleteWhiteboard(id)     { return this.del(`/api/whiteboards/${id}`); },

    // Card
    createCard(data)         { return this.post('/api/cards', data); },
    updateCard(id, data)     { return this.put(`/api/cards/${id}`, data); },
    deleteCard(id)           { return this.del(`/api/cards/${id}`); },
    addItemToCard(cardId, itemId)    { return this.post(`/api/cards/${cardId}/items`, { item_id: itemId }); },
    removeItemFromCard(cardId, itemId) { return this.del(`/api/cards/${cardId}/items/${itemId}`); },
    moveItem(data)           { return this.put('/api/card-items/move', data); },
    copyItem(data)           { return this.post('/api/card-items/copy', data); },

    // Tag
    getTags()                { return this.get('/api/tags'); },
    createTag(data)          { return this.post('/api/tags', data); },
    updateTag(id, data)      { return this.put(`/api/tags/${id}`, data); },
    deleteTag(id)            { return this.del(`/api/tags/${id}`); },
    addTagToCard(cardId, tagId)      { return this.post(`/api/cards/${cardId}/tags`, { tag_id: tagId }); },
    removeTagFromCard(cardId, tagId) { return this.del(`/api/cards/${cardId}/tags/${tagId}`); },

    // Connection
    createConnection(data)   { return this.post('/api/connections', data); },
    updateConnection(id, d)  { return this.put(`/api/connections/${id}`, d); },
    deleteConnection(id)     { return this.del(`/api/connections/${id}`); },

    // Knowledge Map
    getKnowledgeMap(wbId)    { return this.get(`/api/knowledge-map/${wbId}`); },
};
