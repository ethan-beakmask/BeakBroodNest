/**
 * BeakTreeModel - 純資料層
 * 樹狀結構的資料模型，零 DOM 依賴
 *
 * 功能：節點索引、展開/收合、checkbox 多選、扁平化計算、動態資料操作
 * 共用於 Tree（獨立元件）與 BeakTrellis（組合元件）
 *
 * 授權：MIT
 */
'use strict';

class BeakTreeModel {
    /**
     * @param {Array} data - 樹狀資料陣列
     * @param {Object} [options]
     * @param {number} [options.maxExpanded=500] - 最大展開節點數
     * @param {Function} [options.onExpand] - 展開回呼 (id, node)
     * @param {Function} [options.onCollapse] - 收合回呼 (id, node)
     * @param {Function} [options.onExpandLimited] - 展開超限回呼 (requested, max)
     * @param {Function} [options.onChecked] - 勾選回呼 (checkedIds, triggerId)
     */
    constructor(data, options) {
        if (!Array.isArray(data)) {
            throw new Error('BeakTreeModel: data 必須是陣列');
        }

        this.options = Object.assign({
            maxExpanded: 500,
            hideRoot: false,
            onExpand: null,
            onCollapse: null,
            onExpandLimited: null,
            onChecked: null
        }, options || {});

        // 內部狀態
        this._nodeMap = new Map();       // id -> node
        this._expandedSet = new Set();   // 已展開的節點 ID
        this._checkedSet = new Set();    // 已勾選的節點 ID
        this._flatNodes = [];            // 扁平化的可見節點列表
        this._expandedCount = 0;         // 當前展開節點總數

        // 建立索引
        this._buildNodeMap(data, null, 0);
    }

    // ========== 資料模型 ==========

    /**
     * 遞迴建立節點索引，標準化資料結構
     */
    _buildNodeMap(nodes, parentId, level) {
        if (!Array.isArray(nodes)) return;
        for (var i = 0; i < nodes.length; i++) {
            var raw = nodes[i];
            if (!raw.id) {
                raw.id = this._generateId();
            }
            var node = {
                id: raw.id,
                label: raw.label || '',
                level: level,
                parentId: parentId,
                children: [],
                childIds: [],
                data: raw.data || {},
                _raw: raw,
                _index: i,
                _isLast: (i === nodes.length - 1)
            };
            this._nodeMap.set(node.id, node);

            if (parentId) {
                var parent = this._nodeMap.get(parentId);
                if (parent) {
                    parent.children.push(node);
                    parent.childIds.push(node.id);
                }
            }

            // 預設展開狀態
            if (raw.expanded === true) {
                this._expandedSet.add(node.id);
                this._expandedCount++;
            }

            // 預設勾選狀態
            if (raw.checked === true) {
                this._checkedSet.add(node.id);
            }

            // 遞迴子節點
            if (raw.children && raw.children.length > 0) {
                this._buildNodeMap(raw.children, node.id, level + 1);
            }
        }
    }

    _generateId() {
        return 'tg_' + Date.now().toString(36) + '_' + Math.random().toString(36).substr(2, 6);
    }

    // ========== 查詢 ==========

    getNode(id) {
        return this._nodeMap.get(id) || null;
    }

    getRootNodes() {
        var roots = [];
        this._nodeMap.forEach(function(node) {
            if (node.parentId === null) {
                roots.push(node);
            }
        });
        roots.sort(function(a, b) { return a._index - b._index; });
        return roots;
    }

    getAncestors(id) {
        var ancestors = [];
        var node = this._nodeMap.get(id);
        while (node && node.parentId) {
            var parent = this._nodeMap.get(node.parentId);
            if (parent) {
                ancestors.unshift(parent);
            }
            node = parent;
        }
        return ancestors;
    }

    getDescendants(id) {
        var result = [];
        var node = this._nodeMap.get(id);
        if (!node) return result;

        var walk = function(n) {
            for (var i = 0; i < n.children.length; i++) {
                result.push(n.children[i]);
                walk(n.children[i]);
            }
        };
        walk(node);
        return result;
    }

    // ========== 扁平化 ==========

    computeFlatNodes() {
        var result = [];
        var roots = this.getRootNodes();
        var expandedSet = this._expandedSet;
        var hideRoot = this.options.hideRoot;

        var walk = function(nodes) {
            for (var i = 0; i < nodes.length; i++) {
                var node = nodes[i];
                node._isLast = (i === nodes.length - 1);
                result.push(node);
                if (expandedSet.has(node.id) && node.children.length > 0) {
                    walk(node.children);
                }
            }
        };

        if (hideRoot && roots.length === 1 && roots[0].children.length > 0) {
            // 隱藏唯一的 root，從其子節點開始
            // 確保 root 是展開的
            expandedSet.add(roots[0].id);
            // 子節點降一級顯示（視覺上作為 root）
            walk(roots[0].children);
        } else {
            walk(roots);
        }
        this._flatNodes = result;
        return result;
    }

    // ========== 展開/收合 ==========

    isExpanded(id) {
        return this._expandedSet.has(id);
    }

    hasChildren(id) {
        var node = this._nodeMap.get(id);
        return node ? node.children.length > 0 : false;
    }

    /**
     * 展開節點
     * @returns {boolean} 是否成功（資料已變更，呼叫端需自行刷新 UI）
     */
    expand(id, recursive) {
        var node = this._nodeMap.get(id);
        if (!node || node.children.length === 0) return false;

        if (recursive) {
            return this._expandRecursive(node);
        }

        if (this._expandedSet.has(id)) return true;

        var descendantCount = this._countVisibleDescendants(node);
        if (this._expandedCount + descendantCount > this.options.maxExpanded) {
            var requested = this._expandedCount + descendantCount;
            console.warn('BeakTreeModel: 展開上限 ' + this.options.maxExpanded + '，需要 ' + requested + '，無法展開');
            if (this.options.onExpandLimited) {
                this.options.onExpandLimited(requested, this.options.maxExpanded);
            }
            return false;
        }

        this._expandedSet.add(id);
        this._expandedCount += descendantCount;

        if (this.options.onExpand) {
            this.options.onExpand(id, node);
        }

        return true;
    }

    _expandRecursive(node) {
        var toExpand = [];
        var expandedSet = this._expandedSet;
        var walk = function(n) {
            if (n.children.length > 0 && !expandedSet.has(n.id)) {
                toExpand.push(n);
            }
            for (var i = 0; i < n.children.length; i++) {
                walk(n.children[i]);
            }
        };
        walk(node);

        var totalNew = 0;
        for (var i = 0; i < toExpand.length; i++) {
            totalNew += toExpand[i].children.length;
        }
        if (this._expandedCount + totalNew > this.options.maxExpanded) {
            var requested = this._expandedCount + totalNew;
            console.warn('BeakTreeModel: 遞迴展開需要 ' + requested + '，超過上限 ' + this.options.maxExpanded + '，已取消');
            if (this.options.onExpandLimited) {
                this.options.onExpandLimited(requested, this.options.maxExpanded);
            }
            return false;
        }

        for (var i = 0; i < toExpand.length; i++) {
            this._expandedSet.add(toExpand[i].id);
        }
        this._expandedCount += totalNew;

        if (this.options.onExpand) {
            this.options.onExpand(node.id, node);
        }

        return true;
    }

    /**
     * 收合節點
     * @returns {boolean} 資料已變更
     */
    collapse(id, recursive) {
        var node = this._nodeMap.get(id);
        if (!node) return false;

        if (recursive) {
            var self = this;
            var walk = function(n) {
                self._expandedSet.delete(n.id);
                for (var i = 0; i < n.children.length; i++) {
                    walk(n.children[i]);
                }
            };
            walk(node);
        } else {
            this._expandedSet.delete(id);
        }

        this._recountExpanded();

        if (this.options.onCollapse) {
            this.options.onCollapse(id, node);
        }

        return true;
    }

    toggle(id) {
        if (this._expandedSet.has(id)) {
            return this.collapse(id);
        } else {
            return this.expand(id);
        }
    }

    expandAll() {
        var count = 0;
        this._nodeMap.forEach(function(node) {
            if (node.children.length > 0) {
                count += node.children.length;
            }
        });
        if (count > this.options.maxExpanded) {
            console.warn('BeakTreeModel: 全部展開需要 ' + count + '，超過上限 ' + this.options.maxExpanded);
            if (this.options.onExpandLimited) {
                this.options.onExpandLimited(count, this.options.maxExpanded);
            }
            return false;
        }
        var expandedSet = this._expandedSet;
        this._nodeMap.forEach(function(node) {
            if (node.children.length > 0) {
                expandedSet.add(node.id);
            }
        });
        this._expandedCount = count;
        return true;
    }

    collapseAll() {
        this._expandedSet.clear();
        this._expandedCount = 0;
        return true;
    }

    _countVisibleDescendants(node) {
        var count = node.children.length;
        var expandedSet = this._expandedSet;
        for (var i = 0; i < node.children.length; i++) {
            if (expandedSet.has(node.children[i].id)) {
                count += this._countVisibleDescendants(node.children[i]);
            }
        }
        return count;
    }

    _recountExpanded() {
        var count = 0;
        var expandedSet = this._expandedSet;
        var roots = this.getRootNodes();
        var walk = function(nodes) {
            for (var i = 0; i < nodes.length; i++) {
                var node = nodes[i];
                if (expandedSet.has(node.id) && node.children.length > 0) {
                    count += node.children.length;
                    walk(node.children);
                }
            }
        };
        walk(roots);
        this._expandedCount = count;
    }

    // ========== Checkbox ==========

    getCheckState(id) {
        var node = this._nodeMap.get(id);
        if (!node) return 'unchecked';

        if (node.children.length === 0) {
            return this._checkedSet.has(id) ? 'checked' : 'unchecked';
        }

        var checkedCount = 0;
        var indeterminateCount = 0;
        var total = node.children.length;

        for (var i = 0; i < node.children.length; i++) {
            var state = this.getCheckState(node.children[i].id);
            if (state === 'checked') checkedCount++;
            if (state === 'indeterminate') indeterminateCount++;
        }

        if (checkedCount === total) return 'checked';
        if (checkedCount === 0 && indeterminateCount === 0) return 'unchecked';
        return 'indeterminate';
    }

    toggleCheck(id) {
        var currentState = this.getCheckState(id);
        var newChecked = (currentState !== 'checked');
        this._setCheckRecursive(id, newChecked);

        if (this.options.onChecked) {
            this.options.onChecked(this.getCheckedIds(), id);
        }
    }

    _setCheckRecursive(id, checked) {
        if (checked) {
            this._checkedSet.add(id);
        } else {
            this._checkedSet.delete(id);
        }
        var node = this._nodeMap.get(id);
        if (node) {
            for (var i = 0; i < node.children.length; i++) {
                this._setCheckRecursive(node.children[i].id, checked);
            }
        }
    }

    getCheckedIds(leafOnly) {
        var ids = [];
        var nodeMap = this._nodeMap;
        this._checkedSet.forEach(function(id) {
            if (leafOnly) {
                var node = nodeMap.get(id);
                if (node && node.children.length === 0) {
                    ids.push(id);
                }
            } else {
                ids.push(id);
            }
        });
        return ids;
    }

    checkAll() {
        var checkedSet = this._checkedSet;
        this._nodeMap.forEach(function(node, id) {
            checkedSet.add(id);
        });
        if (this.options.onChecked) {
            this.options.onChecked(this.getCheckedIds());
        }
    }

    uncheckAll() {
        this._checkedSet.clear();
        if (this.options.onChecked) {
            this.options.onChecked([]);
        }
    }

    // ========== 動態資料操作 ==========

    addChildren(parentId, childrenData) {
        var parent = this._nodeMap.get(parentId);
        if (!parent) {
            console.warn('BeakTreeModel.addChildren: 找不到父節點 ' + parentId);
            return false;
        }
        if (!Array.isArray(childrenData) || childrenData.length === 0) {
            return false;
        }

        var startIdx = parent.children.length;

        for (var i = 0; i < childrenData.length; i++) {
            if (!childrenData[i].id) {
                childrenData[i].id = this._generateId();
            }
        }

        this._buildNodeMap(childrenData, parentId, parent.level + 1);

        if (startIdx > 0) {
            parent.children[startIdx - 1]._isLast = false;
        }

        this._recountExpanded();
        return true;
    }

    removeChildren(parentId) {
        var parent = this._nodeMap.get(parentId);
        if (!parent) {
            console.warn('BeakTreeModel.removeChildren: 找不到父節點 ' + parentId);
            return false;
        }

        var nodeMap = this._nodeMap;
        var expandedSet = this._expandedSet;
        var checkedSet = this._checkedSet;
        var removeDescendants = function(node) {
            for (var i = 0; i < node.children.length; i++) {
                var child = node.children[i];
                removeDescendants(child);
                nodeMap.delete(child.id);
                expandedSet.delete(child.id);
                checkedSet.delete(child.id);
            }
        };
        removeDescendants(parent);

        parent.children = [];
        parent.childIds = [];
        this._expandedSet.delete(parentId);
        this._recountExpanded();
        return true;
    }

    updateNodeData(id, data) {
        var node = this._nodeMap.get(id);
        if (!node) {
            console.warn('BeakTreeModel.updateNodeData: 找不到節點 ' + id);
            return false;
        }
        Object.assign(node.data, data);
        if (node._raw) {
            if (!node._raw.data) node._raw.data = {};
            Object.assign(node._raw.data, data);
        }
        return true;
    }

    /**
     * 完全替換資料
     */
    setData(data) {
        this._nodeMap.clear();
        this._expandedSet.clear();
        this._checkedSet.clear();
        this._expandedCount = 0;
        this._flatNodes = [];
        this._buildNodeMap(data, null, 0);
    }

    // ========== 節點移動 ==========

    /**
     * 判斷 targetId 是否為 ancestorId 的後代（防止循環參照）
     */
    isDescendantOf(targetId, ancestorId) {
        if (targetId === ancestorId) return true;
        var node = this._nodeMap.get(targetId);
        while (node && node.parentId) {
            if (node.parentId === ancestorId) return true;
            node = this._nodeMap.get(node.parentId);
        }
        return false;
    }

    /**
     * 移動節點到新位置
     * @param {string} nodeId - 要移動的節點 ID
     * @param {string|null} newParentId - 新父節點 ID（null 表示移到根層）
     * @param {number} newIndex - 在新父節點 children 中的位置索引
     * @returns {boolean} 是否成功
     */
    moveNode(nodeId, newParentId, newIndex) {
        var node = this._nodeMap.get(nodeId);
        if (!node) {
            console.warn('BeakTreeModel.moveNode: 找不到節點 ' + nodeId);
            return false;
        }

        // 不能移動到自己的後代下（循環檢測）
        if (newParentId && this.isDescendantOf(newParentId, nodeId)) {
            console.warn('BeakTreeModel.moveNode: 不能將節點移到自己的後代中');
            return false;
        }

        // 隱藏 root 模式下，不能移到真正的 root 層（只能在隱藏 root 的子節點之間移動）
        if (this.options.hideRoot && newParentId === null) {
            var roots = this.getRootNodes();
            if (roots.length === 1) {
                // 把 newParentId 改成隱藏的 root
                newParentId = roots[0].id;
            }
        }

        var oldParentId = node.parentId;

        // === 從舊位置移除 ===
        if (oldParentId) {
            var oldParent = this._nodeMap.get(oldParentId);
            if (oldParent) {
                var oldIdx = oldParent.children.indexOf(node);
                if (oldIdx >= 0) {
                    oldParent.children.splice(oldIdx, 1);
                    oldParent.childIds.splice(oldIdx, 1);
                }
                // 更新舊兄弟的 _isLast
                if (oldParent.children.length > 0) {
                    for (var i = 0; i < oldParent.children.length; i++) {
                        oldParent.children[i]._isLast = (i === oldParent.children.length - 1);
                        oldParent.children[i]._index = i;
                    }
                }
            }
        } else {
            // 節點原本在根層，需要從根層移除
            // 根層節點沒有顯式的 children 陣列，靠 parentId === null 識別
            // 不需要特別處理，只需更新 parentId
        }

        // === 插入新位置 ===
        node.parentId = newParentId;

        if (newParentId) {
            var newParent = this._nodeMap.get(newParentId);
            if (!newParent) {
                console.warn('BeakTreeModel.moveNode: 找不到新父節點 ' + newParentId);
                return false;
            }
            // clamp index
            var insertIdx = Math.max(0, Math.min(newIndex, newParent.children.length));
            newParent.children.splice(insertIdx, 0, node);
            newParent.childIds.splice(insertIdx, 0, node.id);

            // 更新 level（遞迴）
            this._updateLevel(node, newParent.level + 1);

            // 更新新兄弟的 _isLast 和 _index
            for (var i = 0; i < newParent.children.length; i++) {
                newParent.children[i]._isLast = (i === newParent.children.length - 1);
                newParent.children[i]._index = i;
            }

            // 確保新父節點已展開（否則看不到移入的節點）
            if (!this._expandedSet.has(newParentId)) {
                this._expandedSet.add(newParentId);
            }
        } else {
            // 移到根層
            node.level = 0;
            this._updateLevel(node, 0);
        }

        this._recountExpanded();
        return true;
    }

    /**
     * 遞迴更新節點及其後代的 level
     */
    _updateLevel(node, newLevel) {
        node.level = newLevel;
        for (var i = 0; i < node.children.length; i++) {
            this._updateLevel(node.children[i], newLevel + 1);
        }
    }

    // ========== 統計 ==========

    getVisibleCount() {
        return this._flatNodes.length;
    }

    countLeaves() {
        var count = 0;
        this._nodeMap.forEach(function(node) {
            if (node.children.length === 0) count++;
        });
        return count;
    }

    countCheckedLeaves() {
        var count = 0;
        var nodeMap = this._nodeMap;
        this._checkedSet.forEach(function(id) {
            var node = nodeMap.get(id);
            if (node && node.children.length === 0) count++;
        });
        return count;
    }

    destroy() {
        this._nodeMap.clear();
        this._expandedSet.clear();
        this._checkedSet.clear();
        this._flatNodes = [];
    }
}
