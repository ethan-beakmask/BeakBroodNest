-- Migration 007 UP: canvas_connections 一致性與自動同步
-- 1. canvas_connections 新增 is_disconnected 欄位
-- 2. BEFORE INSERT/UPDATE trigger 驗證端點一致性
-- 3. atom_relations AFTER UPDATE trigger 自動同步 is_disconnected
-- 前提：003 (atom_relations 已有 is_deleted 欄位)
-- 回滾：007_canvas_connections_sync.down.sql

BEGIN;

-- ============================================================
-- Step A: canvas_connections 新增 is_disconnected
-- ============================================================

ALTER TABLE canvas_connections
    ADD COLUMN is_disconnected BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN canvas_connections.is_disconnected IS
    'Phase 1: 當關聯的 atom_relation 被軟刪除時，由 trigger 自動設為 TRUE';

-- ============================================================
-- Step B: 端點一致性 trigger（canvas_connections 側）
-- ============================================================

CREATE OR REPLACE FUNCTION trg_canvas_conn_consistency()
RETURNS TRIGGER AS $$
DECLARE
    rel RECORD;
BEGIN
    IF NEW.relation_id IS NOT NULL THEN
        SELECT from_atom_id, to_atom_id
        INTO rel
        FROM atom_relations
        WHERE id = NEW.relation_id;

        IF rel IS NULL THEN
            RAISE EXCEPTION '關聯的 atom_relation #% 不存在', NEW.relation_id;
        END IF;

        IF NEW.source_atom_id <> rel.from_atom_id
           OR NEW.target_atom_id <> rel.to_atom_id THEN
            RAISE EXCEPTION
                'canvas_connection 的端點 (%,%) 與 atom_relation #% 的端點 (%,%) 不一致',
                NEW.source_atom_id, NEW.target_atom_id,
                NEW.relation_id,
                rel.from_atom_id, rel.to_atom_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER canvas_connections_consistency
    BEFORE INSERT OR UPDATE
    ON canvas_connections
    FOR EACH ROW
    EXECUTE FUNCTION trg_canvas_conn_consistency();

-- ============================================================
-- Step C: is_deleted 同步 trigger（atom_relations 側）
-- ============================================================

CREATE OR REPLACE FUNCTION trg_sync_canvas_disconnected()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.is_deleted IS DISTINCT FROM NEW.is_deleted THEN
        UPDATE canvas_connections
        SET is_disconnected = NEW.is_deleted
        WHERE relation_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER atom_relations_sync_canvas
    AFTER UPDATE OF is_deleted
    ON atom_relations
    FOR EACH ROW
    EXECUTE FUNCTION trg_sync_canvas_disconnected();

-- ============================================================
-- Step D: 回填既有資料（若有 atom_relation 已軟刪除的 canvas_connection）
-- ============================================================

UPDATE canvas_connections cc
SET is_disconnected = TRUE
FROM atom_relations ar
WHERE cc.relation_id = ar.id
  AND ar.is_deleted = TRUE
  AND cc.is_disconnected = FALSE;

COMMIT;
