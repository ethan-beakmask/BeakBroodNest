-- 032 down: 移除短代號 ref_code 與專案歸屬 schema 地基
--
-- 背景：
--   032 migration 將專案短前綴、卡片短代號、明確專案歸屬與流水號計數器加入資料庫。
--   回滾時需移除取號函式、計數表、索引、外鍵、檢查約束與欄位，讓 schema 回到導入前狀態。

BEGIN;

DROP FUNCTION IF EXISTS next_ref_code(INTEGER);

DROP TABLE IF EXISTS project_ref_counters;

DROP INDEX IF EXISTS idx_atoms_project_canvas;
DROP INDEX IF EXISTS uq_atoms_ref_code;
DROP INDEX IF EXISTS uq_canvases_code;

ALTER TABLE knowledge_atoms
    DROP CONSTRAINT IF EXISTS fk_atoms_project_canvas;

ALTER TABLE knowledge_atoms
    DROP COLUMN IF EXISTS project_canvas_id;

ALTER TABLE knowledge_atoms
    DROP COLUMN IF EXISTS ref_code;

ALTER TABLE canvases
    DROP CONSTRAINT IF EXISTS ck_canvases_code_format;

ALTER TABLE canvases
    DROP COLUMN IF EXISTS code;

COMMIT;
