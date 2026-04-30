-- 021: conversations.parent_conversation_id (sub-agent → 主對話 path-based FK)
--
-- 背景：
--   ~/.claude/projects/<proj>/<MAIN_UUID>/subagents/agent-*.jsonl 是 sub-agent 紀錄。
--   父目錄名 <MAIN_UUID> 即主對話的 conversation_id。
--   既有的 conversations.parent_uuid 是 turn-level parent (Claude Code 自帶)，
--   值來自 JSONL record 的 parentUuid，與 conversation 級別無 join 關係 (實測 0 命中)。
--   故新增 parent_conversation_id 欄位專門承接「主對話 conv_id」。
--
-- 已驗證 (2026-05-01)：對 30 天內 agent jsonl，path-based 推導成功率 99.6%。

BEGIN;

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS parent_conversation_id UUID NULL;

CREATE INDEX IF NOT EXISTS idx_conv_parent_conv
    ON conversations(parent_conversation_id);

COMMENT ON COLUMN conversations.parent_conversation_id IS
    'sub-agent jsonl 對應的呼叫者主對話 conversation id (path-based 推導)。與 turn-level parent_uuid 不同概念。';

-- Backfill：對既有 sub-agent conversation 從 jsonl_path 反推 parent
UPDATE conversations
SET parent_conversation_id = (
    regexp_replace(
        jsonl_path,
        '^.*/([0-9a-f-]{36})/subagents/[^/]+\.jsonl$',
        '\1',
        'i'
    )
)::uuid
WHERE jsonl_path ~* '/[0-9a-f-]{36}/subagents/[^/]+\.jsonl$'
  AND parent_conversation_id IS NULL;

COMMIT;
