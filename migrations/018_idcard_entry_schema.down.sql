-- 018 down: 移除 idcard entry schema
-- 注意：若已有 atom_entries 引用此 schema，需先清理該 entries（CASCADE 會連帶刪 entry_field_values）

DELETE FROM entry_schemas WHERE code = 'idcard';
