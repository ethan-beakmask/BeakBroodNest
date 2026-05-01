-- 022: p2_failures 表 (P2 摘要驗證失敗紀錄)
--
-- 背景：
--   P2-1 取消 MAX_RETRIES (改為 0)，validation_failed 不再重試。
--   為了能事後人工檢視/重跑，把失敗的 raw_output 寫進這張表。
--   同時 claude -p timeout / non-zero exit 也記在這裡，方便巡檢。

BEGIN;

CREATE TABLE IF NOT EXISTS p2_failures (
    id              BIGSERIAL PRIMARY KEY,
    topic_id        TEXT NOT NULL,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    seq_min         INTEGER,
    seq_max         INTEGER,
    signal_count    INTEGER DEFAULT 0,
    max_severity    TEXT DEFAULT '',
    failure_kind    TEXT NOT NULL DEFAULT '',
    -- failure_kind: claude_error | claude_timeout | validation_failed | json_missing
    error_message   TEXT DEFAULT '',
    raw_output      TEXT DEFAULT '',
    model           TEXT DEFAULT '',
    failed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_p2fail_conv      ON p2_failures (conversation_id);
CREATE INDEX IF NOT EXISTS idx_p2fail_failed_at ON p2_failures (failed_at DESC);
CREATE INDEX IF NOT EXISTS idx_p2fail_kind      ON p2_failures (failure_kind);

COMMENT ON TABLE p2_failures IS
    'P2 語意摘要失敗紀錄 (取消 retry 後的人工檢視/重跑來源)。';
COMMENT ON COLUMN p2_failures.failure_kind IS
    'claude_error | claude_timeout | validation_failed | json_missing';

COMMIT;
