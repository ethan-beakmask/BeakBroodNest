-- 033: 白板受眾（audience）三態，取代靠 owner 猜測 AI 該不該讀的做法
--
-- 背景：owner 已經兼任「建立者識別」與「寫入權限閘門」兩個角色，再讓它兼
-- 「給誰看」會把三個語意綁死。可見性改為獨立欄位掛在白板層：使用者以白板為
-- 單位宣告草稿區，新卡自動繼承，不需要逐張標記也不會隨時間腐爛。
--
--   human  -- 使用者自用，AI 預設不讀（fail-closed 預設值）
--   ai     -- AI 工作區（待辦、專案卡），AI 讀寫；人類本來就看得到全部
--   shared -- 雙方共用，AI 預設會讀
--
-- 全程冪等。欄位可能已被 check_schema_drift.py --apply 先建成 nullable 無預設，
-- 因此 default / backfill / NOT NULL 分開補，確保最終狀態一致。

ALTER TABLE canvases
    ADD COLUMN IF NOT EXISTS audience VARCHAR(10);

ALTER TABLE canvases
    ALTER COLUMN audience SET DEFAULT 'human';

-- 既有資料：2026-08-07 人機分離後，持有 project_path 且 owner=claude 的
-- 就是 AI 白板（BeakBroodNest / BeakPlatform），其餘全是使用者自用。
UPDATE canvases
   SET audience = 'ai'
 WHERE audience IS NULL
   AND owner = 'claude'
   AND project_path IS NOT NULL;

UPDATE canvases SET audience = 'human' WHERE audience IS NULL;

ALTER TABLE canvases
    ALTER COLUMN audience SET NOT NULL;

ALTER TABLE canvases
    DROP CONSTRAINT IF EXISTS ck_canvases_audience;

ALTER TABLE canvases
    ADD CONSTRAINT ck_canvases_audience
    CHECK (audience IN ('human', 'ai', 'shared'));

CREATE INDEX IF NOT EXISTS idx_canvases_audience ON canvases (audience);
