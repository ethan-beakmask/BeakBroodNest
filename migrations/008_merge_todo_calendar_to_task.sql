-- 008: 合併 todo + calendar → task schema
-- 2026-04-25
-- 背景：待辦事項和行事曆本質相同，差別只在有沒有填時間欄位。
--        合併為單一 task schema，UI 用欄位差異營造兩種呈現模式。

BEGIN;

-- ============================================================
-- 1. 清除 calendar (schema_id=4) 的資料（測試資料，不遷移）
-- ============================================================

-- 刪除 calendar entries 的欄位值
DELETE FROM entry_field_values
WHERE entry_id IN (
    SELECT id FROM atom_entries WHERE schema_id = (
        SELECT id FROM entry_schemas WHERE code = 'calendar'
    )
);

-- 刪除 calendar entries
DELETE FROM atom_entries
WHERE schema_id = (
    SELECT id FROM entry_schemas WHERE code = 'calendar'
);

-- 刪除 calendar schema 的欄位定義
DELETE FROM entry_schema_fields
WHERE schema_id = (
    SELECT id FROM entry_schemas WHERE code = 'calendar'
);

-- 刪��� calendar schema 本身
DELETE FROM entry_schemas WHERE code = 'calendar';

-- ============================================================
-- 2. Rename todo → task
-- ============================================================

UPDATE entry_schemas
SET code = 'task', name = '待辦事項'
WHERE code = 'todo';

-- ============================================================
-- 3. 新增欄位（合併自 calendar + 新增 planned_end）
-- ============================================================

-- 取得 task schema id
DO $$
DECLARE
    v_schema_id INT;
BEGIN
    SELECT id INTO v_schema_id FROM entry_schemas WHERE code = 'task';

    -- planned_end（預計結束）
    INSERT INTO entry_schema_fields (schema_id, name, label, field_type, options, required, sort_order, dimension, is_frozen)
    SELECT v_schema_id, 'planned_end', '預計結束', 'datetime', '', false, 3, 'T', false
    WHERE NOT EXISTS (SELECT 1 FROM entry_schema_fields WHERE schema_id = v_schema_id AND name = 'planned_end');

    -- location（地點，從 calendar 併入）
    INSERT INTO entry_schema_fields (schema_id, name, label, field_type, options, required, sort_order, dimension, is_frozen)
    SELECT v_schema_id, 'location', '地點', 'text', '', false, 8, 'P', false
    WHERE NOT EXISTS (SELECT 1 FROM entry_schema_fields WHERE schema_id = v_schema_id AND name = 'location');

    -- attendees（出席者，從 calendar 併入）
    INSERT INTO entry_schema_fields (schema_id, name, label, field_type, options, required, sort_order, dimension, is_frozen)
    SELECT v_schema_id, 'attendees', '出席者', 'text', '', false, 9, 'W', false
    WHERE NOT EXISTS (SELECT 1 FROM entry_schema_fields WHERE schema_id = v_schema_id AND name = 'attendees');

    -- note（備註，從 calendar 併入）
    INSERT INTO entry_schema_fields (schema_id, name, label, field_type, options, required, sort_order, dimension, is_frozen)
    SELECT v_schema_id, 'note', '備註', 'text', '', false, 13, NULL, false
    WHERE NOT EXISTS (SELECT 1 FROM entry_schema_fields WHERE schema_id = v_schema_id AND name = 'note');

    -- ============================================================
    -- 4. 調整既有欄位的 sort_order 以符合新順序
    -- ============================================================

    -- planned_duration: 3 → 4, label 更��
    UPDATE entry_schema_fields SET sort_order = 4, label = '預估耗時'
    WHERE schema_id = v_schema_id AND name = 'planned_duration';

    -- actual_start: 4 → 5
    UPDATE entry_schema_fields SET sort_order = 5
    WHERE schema_id = v_schema_id AND name = 'actual_start';

    -- actual_end: 5 → 6
    UPDATE entry_schema_fields SET sort_order = 6
    WHERE schema_id = v_schema_id AND name = 'actual_end';

    -- status: 6 → 7
    UPDATE entry_schema_fields SET sort_order = 7
    WHERE schema_id = v_schema_id AND name = 'status';

END $$;

COMMIT;
