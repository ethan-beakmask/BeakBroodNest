-- 025_tag_source.down.sql
DROP INDEX IF EXISTS idx_tags_source;
ALTER TABLE tags DROP COLUMN IF EXISTS source;
