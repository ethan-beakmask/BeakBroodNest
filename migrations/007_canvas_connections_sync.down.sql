-- Migration 007 DOWN: 回滾 canvas_connections 一致性與自動同步

BEGIN;

-- trigger (atom_relations 側)
DROP TRIGGER IF EXISTS atom_relations_sync_canvas ON atom_relations;
DROP FUNCTION IF EXISTS trg_sync_canvas_disconnected();

-- trigger (canvas_connections 側)
DROP TRIGGER IF EXISTS canvas_connections_consistency ON canvas_connections;
DROP FUNCTION IF EXISTS trg_canvas_conn_consistency();

-- 欄位
ALTER TABLE canvas_connections
    DROP COLUMN IF EXISTS is_disconnected;

COMMIT;
