-- Migration 005 DOWN: 移除自環約束

BEGIN;

ALTER TABLE atom_relations
    DROP CONSTRAINT IF EXISTS ck_no_self_loop;

COMMIT;
