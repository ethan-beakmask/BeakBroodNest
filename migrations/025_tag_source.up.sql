-- 025_tag_source.up.sql
-- tags 加 source 欄位區分人類與 AI 建立的標籤
-- 既有資料一律視為 'ai'（因為過去無區分，且 UI 將預設只顯示 human）
-- 新建：human_ui 路徑寫 'human'，ai_kb / orchestrator / worker 路徑寫 'ai'

ALTER TABLE tags
    ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'ai';

CREATE INDEX IF NOT EXISTS idx_tags_source ON tags(source);
