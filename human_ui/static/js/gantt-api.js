/**
 * BeakGantt.Api -- Gantt API 封裝
 *
 * 負責與後端 gantt API 溝通，隔離 fetch 細節。
 */
window.BeakGantt = window.BeakGantt || {};

(function(BG) {
'use strict';

var BASE = '/beakbroodnest/gantt-mvp/api/gantt';

BG.Api = {

    /**
     * 讀取甘特圖資料
     * @param {string} slug - 白板 slug
     * @returns {Promise<Object>} { tasks, warnings, errors, canvas_name }
     */
    fetchGantt: function(slug) {
        return fetch(BASE + '/' + slug)
            .then(function(r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            });
    },

    /**
     * 更新單一任務欄位
     * @param {string} slug
     * @param {number} entryId
     * @param {Object} fields - { field_name: value }
     * @param {boolean} [resetBaseline=false]
     * @returns {Promise<Object>}
     */
    patchTask: function(slug, entryId, fields, resetBaseline) {
        var url = BASE + '/' + slug + '/' + entryId;
        if (resetBaseline) url += '?reset_baseline=true';

        return fetch(url, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(fields),
        })
        .then(function(r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
    }
};

})(window.BeakGantt);
