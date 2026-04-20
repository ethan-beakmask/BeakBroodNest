-- BeakCortex Pipeline 表結構
-- conversations + conversation_turns (P0~P2 pipeline 用)
-- pipeline_runs + session_logs (執行追蹤與觀察用)

BEGIN;

-- ============================================================
-- P0: 對話匯入表
-- ============================================================

CREATE TABLE IF NOT EXISTS conversations (
    id              UUID PRIMARY KEY,
    project_path    TEXT NOT NULL DEFAULT '',
    session_id      TEXT NOT NULL DEFAULT '',
    jsonl_path      TEXT NOT NULL DEFAULT '',
    jsonl_size      BIGINT DEFAULT 0,
    total_turns     INTEGER DEFAULT 0,
    first_timestamp TIMESTAMPTZ,
    last_timestamp  TIMESTAMPTZ,
    is_sidechain    BOOLEAN DEFAULT FALSE,
    parent_uuid     UUID,
    git_branch      TEXT DEFAULT '',
    imported_at     TIMESTAMPTZ DEFAULT NOW(),

    -- Pipeline 階段標記
    p1_completed_at TIMESTAMPTZ,
    p2_completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_conv_project ON conversations (project_path);
CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations (session_id);
CREATE INDEX IF NOT EXISTS idx_conv_imported ON conversations (imported_at);


CREATE TABLE IF NOT EXISTS conversation_turns (
    id                  SERIAL PRIMARY KEY,
    conversation_id     UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    project_path        TEXT NOT NULL DEFAULT '',
    turn_seq            INTEGER NOT NULL,
    role                TEXT NOT NULL DEFAULT '',
    timestamp           TIMESTAMPTZ,

    -- 內容
    content             TEXT DEFAULT '',
    tool_name           TEXT DEFAULT '',
    tool_use_id         TEXT DEFAULT '',
    tool_params         JSONB,
    tool_is_error       BOOLEAN DEFAULT FALSE,
    files_touched       TEXT DEFAULT '',
    has_thinking        BOOLEAN DEFAULT FALSE,
    thinking_text       TEXT DEFAULT '',

    -- 對話結構
    is_sidechain        BOOLEAN DEFAULT FALSE,
    parent_uuid         UUID,
    model               TEXT DEFAULT '',

    -- token 用量
    usage_input_tokens  INTEGER DEFAULT 0,
    usage_output_tokens INTEGER DEFAULT 0,

    -- P1: 訊號掃描
    p1_scanned_at       TIMESTAMPTZ,
    p1_signals          JSONB,

    -- P2: 語意摘要
    p2_topic_id         TEXT,
    p2_summarized_at    TIMESTAMPTZ,

    UNIQUE (conversation_id, turn_seq)
);

CREATE INDEX IF NOT EXISTS idx_ct_conv ON conversation_turns (conversation_id);
CREATE INDEX IF NOT EXISTS idx_ct_role ON conversation_turns (role);
CREATE INDEX IF NOT EXISTS idx_ct_p1 ON conversation_turns (p1_scanned_at);
CREATE INDEX IF NOT EXISTS idx_ct_p2 ON conversation_turns (p2_summarized_at);
CREATE INDEX IF NOT EXISTS idx_ct_timestamp ON conversation_turns (timestamp);


-- ============================================================
-- 執行追蹤表：pipeline_runs
-- 每次 pipeline 執行的完整記錄
-- ============================================================

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              SERIAL PRIMARY KEY,
    pipeline_name   TEXT NOT NULL,           -- daily_review, auto_chat, etc.
    trigger_type    TEXT NOT NULL DEFAULT 'manual',  -- cron / manual / message
    session_id      TEXT DEFAULT '',          -- 對應的 Claude 對話 session
    conversation_id UUID,                    -- 處理的對話 ID

    -- 階段追蹤
    stages          JSONB NOT NULL DEFAULT '[]',
    -- 格式: [{"name": "P0", "status": "completed", "started_at": "...", "completed_at": "...", "output_summary": "..."}]
    current_stage   TEXT DEFAULT '',

    -- 整體狀態
    status          TEXT NOT NULL DEFAULT 'pending',
    -- pending / running / completed / failed / timeout
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    error_detail    TEXT DEFAULT '',

    -- 統計
    total_turns_processed   INTEGER DEFAULT 0,
    signals_found           INTEGER DEFAULT 0,
    topics_generated        INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_pr_pipeline ON pipeline_runs (pipeline_name);
CREATE INDEX IF NOT EXISTS idx_pr_status ON pipeline_runs (status);
CREATE INDEX IF NOT EXISTS idx_pr_started ON pipeline_runs (started_at);


-- ============================================================
-- 執行追蹤表：session_logs
-- 每次 Claude 對話的元數據記錄
-- ============================================================

CREATE TABLE IF NOT EXISTS session_logs (
    id              SERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL,            -- Claude 對話 session UUID
    project_path    TEXT NOT NULL DEFAULT '',  -- 啟動時的專案路徑
    trigger_type    TEXT NOT NULL DEFAULT 'interactive',
    -- interactive / scheduled / agent

    -- 時間
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    duration_seconds INTEGER,                 -- 自動計算

    -- 對話統計
    summary         TEXT DEFAULT '',           -- 結束時自己寫的摘要
    total_turns     INTEGER DEFAULT 0,
    total_input_tokens  BIGINT DEFAULT 0,
    total_output_tokens BIGINT DEFAULT 0,

    -- 知識庫變更
    atoms_created   INTEGER DEFAULT 0,
    atoms_updated   INTEGER DEFAULT 0,
    messages_sent   INTEGER DEFAULT 0,

    -- 監控指標
    context_peak_pct    FLOAT DEFAULT 0,      -- context 使用峰值百分比
    agent_count         INTEGER DEFAULT 0,     -- 啟動的 agent 數量
    agent_max_duration  INTEGER DEFAULT 0,     -- 最長 agent 執行秒數
    error_count         INTEGER DEFAULT 0,     -- 執行過程中的錯誤數

    -- 異常標記
    abnormal        BOOLEAN DEFAULT FALSE,
    abnormal_reason TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sl_session ON session_logs (session_id);
CREATE INDEX IF NOT EXISTS idx_sl_project ON session_logs (project_path);
CREATE INDEX IF NOT EXISTS idx_sl_started ON session_logs (started_at);
CREATE INDEX IF NOT EXISTS idx_sl_abnormal ON session_logs (abnormal) WHERE abnormal = TRUE;

COMMIT;
