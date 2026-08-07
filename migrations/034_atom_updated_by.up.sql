-- 034: knowledge_atoms 最後寫入歸屬訊號
--
-- 背景：knowledge_atoms 原本只有 updated_at，無法分辨最後一次寫入是人類、AI，
-- 或是從哪個入口進來。尤其人類從待辦頁編輯 AI 建立的卡片後，AI 透過 MCP 讀取
-- 時看不出這是人類回覆/修正。新增 updated_by / updated_via 兩個獨立欄位：
-- 身份與入口分開存，純紀錄用途，不參與 owner 既有權限判斷。
--
-- 語意固定為「最後一次更新」，建立時不填：
--   NULL          = 這張卡建立後從未被更新（或是本 migration 之前的舊更新）
--   ethan / ui    = 人類在白板一般編輯
--   ethan / todos = 人類從 /todos 待辦頁進來編輯（入口即意圖，BBN-25 會用這條訊號）
--   claude / mcp  = AI 透過 MCP 工具更新
--
-- 全程冪等；歷史資料不 backfill。

ALTER TABLE knowledge_atoms
    ADD COLUMN IF NOT EXISTS updated_by VARCHAR(100);

ALTER TABLE knowledge_atoms
    ADD COLUMN IF NOT EXISTS updated_via VARCHAR(30);

ALTER TABLE knowledge_atoms
    DROP CONSTRAINT IF EXISTS ck_knowledge_atoms_updated_via;

ALTER TABLE knowledge_atoms
    ADD CONSTRAINT ck_knowledge_atoms_updated_via
    CHECK (updated_via IS NULL OR updated_via IN ('ui', 'todos', 'mcp'));
