-- 009: Entry 欄位變更歷史表
-- 記錄 entry_field_values 的每次 UPDATE，用於 L2 衝突提示和專案管理風險追蹤

CREATE TABLE IF NOT EXISTS entry_field_change_log (
    id              SERIAL PRIMARY KEY,
    entry_id        INTEGER NOT NULL REFERENCES atom_entries(id) ON DELETE CASCADE,
    field_id        INTEGER NOT NULL REFERENCES entry_schema_fields(id) ON DELETE CASCADE,
    old_value       TEXT,
    new_value       TEXT,
    changed_by      VARCHAR(50) NOT NULL DEFAULT 'user',
    changed_at      TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_efcl_entry ON entry_field_change_log(entry_id);
CREATE INDEX IF NOT EXISTS idx_efcl_changed_at ON entry_field_change_log(changed_at);
