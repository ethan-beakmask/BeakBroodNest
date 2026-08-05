-- 035 rollback: 移除 conversations.skip_analysis
-- 注意：回滾會遺失所有跳過標記，之後 P1/P2 會重新分析 pipeline 自產 session。

BEGIN;

DROP INDEX IF EXISTS idx_conv_skip_analysis;
DROP INDEX IF EXISTS idx_conversations_skip_analysis;
ALTER TABLE conversations DROP COLUMN IF EXISTS skip_analysis;

COMMIT;
