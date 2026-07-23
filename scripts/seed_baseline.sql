-- =============================================================================
-- BeakBroodNest 基線種子（seed_baseline.sql）
-- =============================================================================
-- 由 install.sh 在 create_all_tables() 之後呼叫。
--
-- 【範圍變更 2026-07-23】
-- 原本散在這裡的「參考資料」INSERT（nav_menu / relation_type_registry /
-- atom_schemas / schema_fields / tag_categories 等）已全數移出，改由
-- scripts/seed_reference.sql 從開發機 DB 自動產生（見 gen_reference_seed.py）。
-- 理由：手寫 seed 靠記憶同步，曾漏掉「閱覽器」選單、entry_schemas 等整組
-- 參考資料，造成「開發機正常、外部使用者靜默壞掉」。改由產生器 + git diff 納管後
-- 結構上不可能再漏。install.sh 會在本檔之後接著套用 seed_reference.sql。
--
-- 本檔現在只保留「非參考資料、需手寫」的結構性 seed：
--   - pending_outputs view  跨 worker_reports / worker_inbox 的未讀統一視圖
--
-- 仍不包含：
--   - sensitive_terms（環境特定，請透過 UI 或 sensitive_term_add MCP tool 設定）
--   - system_config（密鑰 / auth，install.sh 每台各自產生）
--   - 對話、白板、上傳檔等使用者資料
--
-- 可重複執行。
-- =============================================================================

BEGIN;

-- =============================================================================
-- pending_outputs view：跨 worker_reports / worker_inbox 統一未讀查詢
-- 來自 migrations/024_pending_outputs_view.up.sql
-- =============================================================================

ALTER TABLE worker_reports
    ADD COLUMN IF NOT EXISTS read_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS idx_worker_reports_unread
    ON worker_reports(read_at);

COMMENT ON COLUMN worker_reports.read_at IS
    '主線讀取時間（與 review_status 無關；與 worker_inbox.read_at 對齊，供 pending_outputs view 使用）';

CREATE OR REPLACE VIEW pending_outputs AS
SELECT 'task'           AS source,
       wr.id            AS row_id,
       NULL::text       AS session_name,
       wr.task_id       AS task_id,
       'result'::varchar AS kind,
       wr.content       AS content,
       wr.created_at    AS created_at,
       wr.read_at       AS read_at
FROM worker_reports wr
WHERE wr.read_at IS NULL
UNION ALL
SELECT 'session'        AS source,
       wi.id            AS row_id,
       wi.session_name  AS session_name,
       NULL::integer    AS task_id,
       wi.kind          AS kind,
       wi.content       AS content,
       wi.created_at    AS created_at,
       wi.read_at       AS read_at
FROM worker_inbox wi
WHERE wi.read_at IS NULL;

COMMENT ON VIEW pending_outputs IS
    '主線未讀彙總視圖：UNION worker_reports 與 worker_inbox 的未讀（read_at IS NULL）。';

COMMIT;
