-- P3b：CanvasConnection 加上 standalone_entry 端點欄位
-- 純視覺連線（不掛 unified_relations），對齊 textbox 連線模式
-- 等冪：IF NOT EXISTS / pg_catalog 防呆

BEGIN;

ALTER TABLE canvas_connections
    ADD COLUMN IF NOT EXISTS source_standalone_entry_id INTEGER,
    ADD COLUMN IF NOT EXISTS target_standalone_entry_id INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'canvas_connections_source_standalone_entry_id_fkey'
    ) THEN
        ALTER TABLE canvas_connections
            ADD CONSTRAINT canvas_connections_source_standalone_entry_id_fkey
            FOREIGN KEY (source_standalone_entry_id)
            REFERENCES standalone_entries(id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'canvas_connections_target_standalone_entry_id_fkey'
    ) THEN
        ALTER TABLE canvas_connections
            ADD CONSTRAINT canvas_connections_target_standalone_entry_id_fkey
            FOREIGN KEY (target_standalone_entry_id)
            REFERENCES standalone_entries(id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_canvas_conn_src_se ON canvas_connections(source_standalone_entry_id);
CREATE INDEX IF NOT EXISTS idx_canvas_conn_tgt_se ON canvas_connections(target_standalone_entry_id);

-- 擴 check constraint：接受 standalone_entry kind
ALTER TABLE canvas_connections DROP CONSTRAINT IF EXISTS chk_canvas_conn_from_endpoint;
ALTER TABLE canvas_connections DROP CONSTRAINT IF EXISTS chk_canvas_conn_to_endpoint;

ALTER TABLE canvas_connections ADD CONSTRAINT chk_canvas_conn_from_endpoint CHECK (
    (from_kind = 'atom' AND source_atom_id IS NOT NULL
        AND source_textbox_id IS NULL AND source_standalone_entry_id IS NULL)
    OR (from_kind = 'textbox' AND source_textbox_id IS NOT NULL
        AND source_atom_id IS NULL AND source_standalone_entry_id IS NULL)
    OR (from_kind = 'standalone_entry' AND source_standalone_entry_id IS NOT NULL
        AND source_atom_id IS NULL AND source_textbox_id IS NULL)
);

ALTER TABLE canvas_connections ADD CONSTRAINT chk_canvas_conn_to_endpoint CHECK (
    (to_kind = 'atom' AND target_atom_id IS NOT NULL
        AND target_textbox_id IS NULL AND target_standalone_entry_id IS NULL)
    OR (to_kind = 'textbox' AND target_textbox_id IS NOT NULL
        AND target_atom_id IS NULL AND target_standalone_entry_id IS NULL)
    OR (to_kind = 'standalone_entry' AND target_standalone_entry_id IS NOT NULL
        AND target_atom_id IS NULL AND target_textbox_id IS NULL)
);

COMMIT;
