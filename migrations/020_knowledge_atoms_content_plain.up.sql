-- 020: knowledge_atoms 加 content_plain 欄位
-- 目的：搜尋（ILIKE / pg_trgm / embedding）改抓純文字版本，
-- 避免 Tiptap 編輯器寫入的 <font color>、<span style>、<table> 等 HTML 標籤
-- 把關鍵字切斷，導致搜尋找不到。
--
-- content      → 完整 HTML/Markdown，給編輯器與顯示用
-- content_plain → strip 過的純文字，給搜尋與 embedding 用
--
-- 寫入鉤在 routes/atoms.py 維護同步。

BEGIN;

-- 加欄位（NULL 允許，回填腳本之後再 NOT NULL）
ALTER TABLE knowledge_atoms ADD COLUMN IF NOT EXISTS content_plain TEXT;

-- GIN trigram index 加速 ILIKE '%xxx%'
CREATE INDEX IF NOT EXISTS idx_atoms_content_plain_trgm
    ON knowledge_atoms USING gin (content_plain gin_trgm_ops);

-- title 也補一個 trgm index（既有搜尋也走 ILIKE，順便加速）
CREATE INDEX IF NOT EXISTS idx_atoms_title_trgm
    ON knowledge_atoms USING gin (title gin_trgm_ops);

COMMENT ON COLUMN knowledge_atoms.content      IS '原始內容（含 HTML / Markdown），編輯器與顯示用';
COMMENT ON COLUMN knowledge_atoms.content_plain IS 'HTML strip 後的純文字，搜尋與 embedding 用，由寫入鉤自動維護';

COMMIT;
