-- 023_worker_sessions_inbox.up.sql
-- Orchestrator: 多輪互動支線會話 + 雙向收件匣
-- 來源：/opt/backup/mvp/HANDOVER.md（CC-to-CC 互動 MVP）
-- 與既有 worker_tasks/worker_reports 並存：WorkerTask=一次性派遣，WorkerSession=長期會話

CREATE TABLE IF NOT EXISTS worker_sessions (
    id                 SERIAL PRIMARY KEY,
    name               TEXT NOT NULL UNIQUE,
    role               TEXT NOT NULL,
    purpose            VARCHAR(40) NOT NULL DEFAULT 'worker',
    working_dir        TEXT NOT NULL,
    model              VARCHAR(30) NOT NULL DEFAULT 'sonnet',
    claude_session_id  TEXT,
    main_tmux_pane     TEXT NOT NULL DEFAULT '',
    status             VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    last_activity_at   TIMESTAMP
);

COMMENT ON TABLE  worker_sessions IS '長期支線會話（多輪互動，對應 claude -p --resume session_id）';
COMMENT ON COLUMN worker_sessions.purpose IS 'worker（用戶手動 spawn）/ hook_aside / hook_summary / hook_<其他> -- 區分 hook 自建支線與工人支線';
COMMENT ON COLUMN worker_sessions.claude_session_id IS 'claude -p --output-format json 回傳的 session_id，後續輪以 --resume 接續';

CREATE INDEX IF NOT EXISTS idx_worker_sessions_purpose ON worker_sessions(purpose);
CREATE INDEX IF NOT EXISTS idx_worker_sessions_status  ON worker_sessions(status);

CREATE TABLE IF NOT EXISTS worker_inbox (
    id            SERIAL PRIMARY KEY,
    session_name  TEXT NOT NULL REFERENCES worker_sessions(name) ON DELETE CASCADE,
    kind          VARCHAR(20) NOT NULL,
    content       TEXT NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    read_at       TIMESTAMP
);

COMMENT ON TABLE  worker_inbox IS '支線→主 雙向訊息佇列（kind: question/notice/result）';
COMMENT ON COLUMN worker_inbox.kind IS 'question=阻塞型提問 / notice=進度回報 / result=任務完成結果';

CREATE INDEX IF NOT EXISTS idx_worker_inbox_unread  ON worker_inbox(read_at);
CREATE INDEX IF NOT EXISTS idx_worker_inbox_session ON worker_inbox(session_name);
