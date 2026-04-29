-- 020 down: 移除 content_plain 欄位與 index

BEGIN;

DROP INDEX IF EXISTS idx_atoms_content_plain_trgm;
DROP INDEX IF EXISTS idx_atoms_title_trgm;
ALTER TABLE knowledge_atoms DROP COLUMN IF EXISTS content_plain;

COMMIT;
