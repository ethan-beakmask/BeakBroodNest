-- 026_canvas_tags.up.sql
-- 白板與標籤多對多關聯，用於 sidebar 篩選白板
-- 採用人類標籤做分類（AI 不需要白板分類）

CREATE TABLE IF NOT EXISTS canvas_tags (
    canvas_id INTEGER NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
    tag_id    INTEGER NOT NULL REFERENCES tags(id)     ON DELETE CASCADE,
    PRIMARY KEY (canvas_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_canvas_tags_tag ON canvas_tags(tag_id);
