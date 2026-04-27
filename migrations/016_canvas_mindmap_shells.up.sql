-- 016 UP: 心智圖殼 (canvas_mindmap_shells) + tree_parent 關係類型
-- A 表（樹結構）:借用 unified_relations + relation_type='tree_parent'
--   方向: child -> parent，每個 atom 最多一個 tree_parent (partial unique index)
-- 視覺殼:
--   * canvas_mindmap_shells: 殼本體（標題/位置/大小/layout/root）
--   * canvas_atoms.mindmap_shell_id: 標記該卡屬於某殼，render 為 mini 卡

BEGIN;

-- ============================================================
-- Step A: 註冊 tree_parent 關係類型
-- ============================================================
INSERT INTO relation_type_registry
    (relation_type, graph_family, semantic_layer, affects_scheduling,
     display_name, is_directed, default_color, default_style, sort_order, description)
VALUES
    ('tree_parent', 'acyclic_tree', 'structural', FALSE,
     '從屬於', TRUE, '#94a3b8', 'solid', 11,
     '心智圖/樹狀結構:子節點從屬於父節點，每個節點最多一個父');

-- ============================================================
-- Step B: canvas_mindmap_shells 主表
-- ============================================================
CREATE TABLE IF NOT EXISTS canvas_mindmap_shells (
    id              SERIAL PRIMARY KEY,
    canvas_id       INTEGER NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
    title           VARCHAR(200) NOT NULL DEFAULT '心智圖',
    pos_x           DOUBLE PRECISION NOT NULL DEFAULT 0,
    pos_y           DOUBLE PRECISION NOT NULL DEFAULT 0,
    width           DOUBLE PRECISION NOT NULL DEFAULT 600,
    height          DOUBLE PRECISION NOT NULL DEFAULT 400,
    z_index         INTEGER NOT NULL DEFAULT 1,
    color           VARCHAR(20) NOT NULL DEFAULT '#3b82f6',
    layout          VARCHAR(20) NOT NULL DEFAULT 'tree-right',
        -- tree-right | tree-down | radial（先做 tree-right，其餘 layout 預留欄位）
    root_atom_id    INTEGER REFERENCES knowledge_atoms(id) ON DELETE SET NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    updated_at      TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mindmap_shells_canvas ON canvas_mindmap_shells(canvas_id);

-- ============================================================
-- Step C: canvas_atoms 加 mindmap_shell_id 欄位
-- ============================================================
ALTER TABLE canvas_atoms
    ADD COLUMN IF NOT EXISTS mindmap_shell_id INTEGER
        REFERENCES canvas_mindmap_shells(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_canvas_atoms_mindmap_shell
    ON canvas_atoms(mindmap_shell_id) WHERE mindmap_shell_id IS NOT NULL;

-- ============================================================
-- Step D: tree_parent 單一父約束
--   每個 from_atom 在 tree_parent 中只能指向一個 parent（軟刪除不算）
-- ============================================================
CREATE UNIQUE INDEX IF NOT EXISTS uq_unified_tree_parent_from
    ON unified_relations(from_atom_id)
    WHERE relation_type = 'tree_parent' AND is_deleted = FALSE;

COMMIT;
