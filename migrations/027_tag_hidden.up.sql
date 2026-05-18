-- 標籤隱藏旗標：從介面隱藏，不刪除，保留所有 atom_tags / canvas_tags 關聯
ALTER TABLE tags ADD COLUMN IF NOT EXISTS hidden BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_tags_hidden ON tags(hidden) WHERE hidden = FALSE;
