-- 028 rollback: 移除 ;;image entry schema
-- 注意：若已有 atom_entries / standalone_entries 引用此 schema，本 rollback 會失敗。
-- 退版前請先把 image 類型 entry 全部清掉或轉成其他類型。

DELETE FROM entry_schema_fields
WHERE schema_id IN (SELECT id FROM entry_schemas WHERE code = 'image');

DELETE FROM entry_schemas WHERE code = 'image';
