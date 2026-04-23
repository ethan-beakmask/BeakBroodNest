-- Migration 004 UP: contains 單親約束
-- partial unique index 強制每個卡片在 contains 關係中只能有一個父節點
-- 前提：003 (atom_relations 已有 is_deleted 欄位)
-- 回滾：004_contains_single_parent.down.sql

BEGIN;

CREATE UNIQUE INDEX idx_contains_single_parent
    ON atom_relations(to_atom_id)
    WHERE relation_type = 'contains' AND is_deleted = FALSE;

COMMENT ON INDEX idx_contains_single_parent IS
    'Phase 1: 強制 contains 樹結構的單親約束，每個子卡片只能有一個父卡片';

COMMIT;
