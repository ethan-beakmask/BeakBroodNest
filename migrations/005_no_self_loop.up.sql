-- Migration 005 UP: 禁止自環
-- CHECK constraint 阻止 from_atom_id = to_atom_id
-- 回滾：005_no_self_loop.down.sql

BEGIN;

ALTER TABLE atom_relations
    ADD CONSTRAINT ck_no_self_loop
    CHECK (from_atom_id <> to_atom_id);

COMMIT;
