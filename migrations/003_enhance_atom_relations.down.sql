-- Migration 003 DOWN: 回滾 atom_relations 增強
-- 移除索引、約束、trigger、欄位

BEGIN;

-- 索引
DROP INDEX IF EXISTS idx_relations_from_active;
DROP INDEX IF EXISTS idx_relations_to_active;
DROP INDEX IF EXISTS idx_relations_scheduling;
DROP INDEX IF EXISTS idx_relations_semantic_layer;
DROP INDEX IF EXISTS idx_relations_graph_family;

-- trigger
DROP TRIGGER IF EXISTS atom_relations_fill_metadata ON atom_relations;
DROP FUNCTION IF EXISTS trg_fill_relation_metadata();

-- FK
ALTER TABLE atom_relations
    DROP CONSTRAINT IF EXISTS fk_relation_type;

-- 欄位
ALTER TABLE atom_relations
    DROP COLUMN IF EXISTS graph_family,
    DROP COLUMN IF EXISTS semantic_layer,
    DROP COLUMN IF EXISTS affects_scheduling,
    DROP COLUMN IF EXISTS is_deleted,
    DROP COLUMN IF EXISTS sort_order,
    DROP COLUMN IF EXISTS metadata;

COMMIT;
