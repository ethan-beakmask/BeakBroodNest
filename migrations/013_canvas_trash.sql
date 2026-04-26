-- 013: 白板私有字紙簍 (canvas_trash)
-- 取代既有「全域 atom 軟刪除」進字紙簍的設計
-- 新流程：在白板 A 按 Delete -> 從 canvas_atoms 移除 + 寫入 canvas_trash
--         救回 = 從 canvas_trash 讀回，重建 canvas_atoms
--         atom 本體完全不動（不軟刪、不影響其他白板）
-- 「徹底刪除卡片」改走 hard delete（DELETE knowledge_atoms）

BEGIN;

CREATE TABLE IF NOT EXISTS canvas_trash (
    id              SERIAL PRIMARY KEY,
    canvas_id       INTEGER NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
    atom_id         INTEGER NOT NULL REFERENCES knowledge_atoms(id) ON DELETE CASCADE,
    deleted_at      TIMESTAMP NOT NULL DEFAULT now(),
    original_pos_x  DOUBLE PRECISION NOT NULL DEFAULT 0,
    original_pos_y  DOUBLE PRECISION NOT NULL DEFAULT 0,
    original_width  DOUBLE PRECISION,
    original_height DOUBLE PRECISION,
    z_index         INTEGER NOT NULL DEFAULT 0,
    visual_style    TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT uq_canvas_trash UNIQUE(canvas_id, atom_id)
);
CREATE INDEX IF NOT EXISTS idx_canvas_trash_canvas ON canvas_trash(canvas_id, deleted_at DESC);
CREATE INDEX IF NOT EXISTS idx_canvas_trash_atom ON canvas_trash(atom_id);

COMMIT;
