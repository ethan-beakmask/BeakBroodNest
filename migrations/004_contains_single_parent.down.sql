-- Migration 004 DOWN: 移除 contains 單親約束

BEGIN;

DROP INDEX IF EXISTS idx_contains_single_parent;

COMMIT;
