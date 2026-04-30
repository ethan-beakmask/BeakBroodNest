-- Rollback for 021
BEGIN;

DROP INDEX IF EXISTS idx_conv_parent_conv;
ALTER TABLE conversations DROP COLUMN IF EXISTS parent_conversation_id;

COMMIT;
