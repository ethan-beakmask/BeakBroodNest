-- 016 DOWN: 回滾心智圖殼

BEGIN;

DROP INDEX IF EXISTS uq_unified_tree_parent_from;
DROP INDEX IF EXISTS idx_canvas_atoms_mindmap_shell;

ALTER TABLE canvas_atoms DROP COLUMN IF EXISTS mindmap_shell_id;

DROP INDEX IF EXISTS idx_mindmap_shells_canvas;
DROP TABLE IF EXISTS canvas_mindmap_shells;

DELETE FROM unified_relations WHERE relation_type = 'tree_parent';
DELETE FROM relation_type_registry WHERE relation_type = 'tree_parent';

COMMIT;
