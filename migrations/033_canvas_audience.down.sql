-- 033 rollback：移除白板受眾欄位
--
-- 回滾後 AI 可見性判定會失去依據，note_search 將無法隔離使用者白板的內容。

DROP INDEX IF EXISTS idx_canvases_audience;

ALTER TABLE canvases
    DROP CONSTRAINT IF EXISTS ck_canvases_audience;

ALTER TABLE canvases
    DROP COLUMN IF EXISTS audience;
