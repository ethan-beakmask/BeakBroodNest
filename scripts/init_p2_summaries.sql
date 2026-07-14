-- P2 語意摘要持久化表
--
-- 背景：舊設計 update_topic_results 只在 conversation_turns 標
-- p2_topic_id / p2_summarized_at，摘要 JSON 本身只印到 stdout 就丟棄。
-- 本表讓摘要成果落地，供 P3 復盤、交接上下文、方法論萃取使用。
--
-- 執行方式（重複執行無害）：
--   psql -U beak_broodnest -d beak_broodnest -f scripts/init_p2_summaries.sql

CREATE TABLE IF NOT EXISTS p2_summaries (
    id              SERIAL PRIMARY KEY,
    topic_id        TEXT NOT NULL,
    conversation_id UUID NOT NULL,
    project_path    TEXT NOT NULL DEFAULT '',
    seq_min         INTEGER,
    seq_max         INTEGER,
    signal_count    INTEGER DEFAULT 0,
    max_severity    TEXT DEFAULT '',
    summary         JSONB NOT NULL,
    model           TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE p2_summaries IS
    'P2 語意摘要成果（goal/process/stuck_point/resolution/outcome JSON），2026-07-15 起累積';

CREATE INDEX IF NOT EXISTS idx_p2sum_conv ON p2_summaries (conversation_id);
CREATE INDEX IF NOT EXISTS idx_p2sum_created ON p2_summaries (created_at);
CREATE INDEX IF NOT EXISTS idx_p2sum_project ON p2_summaries (project_path);
