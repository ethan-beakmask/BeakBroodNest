-- Migration 001: Gantt baseline 支援
-- 為 entry_schema_fields 加入 is_frozen 旗標
-- 為 todo schema 注入 baseline_start / baseline_end / progress 三個新欄位
-- 執行前請先備份：pg_dump -h 192.168.0.16 -U beak_cortex beak_cortex_dev > backup.sql
--
-- 欄位對照：
--   既有 actual_start (id=5), actual_end (id=6) -- 不動，Phase 4 拖拉寫入目標
--   既有 planned_start (id=3) -- 不動，project dashboard 仍讀此欄位
--   新增 baseline_start (is_frozen=TRUE) -- 原計畫開始，凍結保護
--   新增 baseline_end   (is_frozen=TRUE) -- 原計畫結束，凍結保護
--   新增 progress        -- 0-100 進度百分比
--
-- 回填策略：
--   baseline_start <- planned_start（目前計畫視為初始基線）
--   baseline_end   <- actual_end（因 MVP 階段 actual_end 被誤用為 planned_end）
--   首次執行後 baseline 與 actual 會重合，這是預期行為；
--   用戶後續拖拉 actual 後兩者才會分離，產生差異視覺

BEGIN;

-- 1. 新增 is_frozen 欄位（凍結旗標，用於保護 baseline 不被一般 PATCH 修改）
ALTER TABLE entry_schema_fields
    ADD COLUMN IF NOT EXISTS is_frozen BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN entry_schema_fields.is_frozen IS
    '凍結欄位：前端一般編輯不可修改，需透過「重設基線」動作才能變更';

-- 2. 為 todo schema (id=2) 注入 baseline 欄位
--    使用 ON CONFLICT 確保冪等（可重複執行不會出錯）

INSERT INTO entry_schema_fields (schema_id, name, label, field_type, options, required, sort_order, is_frozen)
VALUES
    (2, 'baseline_start', '原計畫開始', 'date', '', FALSE, 10, TRUE),
    (2, 'baseline_end',   '原計畫結束', 'date', '', FALSE, 11, TRUE),
    (2, 'progress',       '進度',       'number', '{"min":0,"max":100}', FALSE, 12, FALSE)
ON CONFLICT (schema_id, name) DO NOTHING;

-- 3. 把既有 planned_start 資料回填到 baseline_start（僅對有值且尚無 baseline 的記錄）
--    這是一次性 seed：把目前的計畫時間當作初始 baseline
INSERT INTO entry_field_values (entry_id, field_id, value)
SELECT
    efv_ps.entry_id,
    bsf.id,
    efv_ps.value
FROM entry_field_values efv_ps
JOIN entry_schema_fields psf ON efv_ps.field_id = psf.id
    AND psf.name = 'planned_start' AND psf.schema_id = 2
JOIN entry_schema_fields bsf ON bsf.name = 'baseline_start' AND bsf.schema_id = 2
WHERE efv_ps.value IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM entry_field_values x
        WHERE x.entry_id = efv_ps.entry_id AND x.field_id = bsf.id
    );

-- 4. 同理回填 actual_end -> baseline_end
INSERT INTO entry_field_values (entry_id, field_id, value)
SELECT
    efv_ae.entry_id,
    bef.id,
    efv_ae.value
FROM entry_field_values efv_ae
JOIN entry_schema_fields aef ON efv_ae.field_id = aef.id
    AND aef.name = 'actual_end' AND aef.schema_id = 2
JOIN entry_schema_fields bef ON bef.name = 'baseline_end' AND bef.schema_id = 2
WHERE efv_ae.value IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM entry_field_values x
        WHERE x.entry_id = efv_ae.entry_id AND x.field_id = bef.id
    );

COMMIT;
