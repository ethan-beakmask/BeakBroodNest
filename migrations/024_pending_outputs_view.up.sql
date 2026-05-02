-- 024_pending_outputs_view.up.sql
-- 主線「未讀通知」需跨 worker_reports（一次性派遣結果）與 worker_inbox（多輪會話訊息）
-- 儲存分流（schema 純度），查詢統一（pending_outputs view）
--
-- 來源：inbox 13 補丁（reply_to=12）

-- 1) worker_reports 加「主線是否讀過」語意欄位
--    review_status 是審查狀態（pending/approved/rejected/promoted），與「主線已讀」屬不同關注點
ALTER TABLE worker_reports
    ADD COLUMN IF NOT EXISTS read_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS idx_worker_reports_unread
    ON worker_reports(read_at);

COMMENT ON COLUMN worker_reports.read_at IS
    '主線讀取時間（與 review_status 無關；與 worker_inbox.read_at 對齊，供 pending_outputs view 使用）';

-- Backfill：欄位剛建立，既有歷史 report 視為已讀，避免 pending_outputs 把所有舊資料當未讀污染主線
UPDATE worker_reports SET read_at = NOW() WHERE read_at IS NULL;

-- 2) 統一未讀查詢視圖
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
    '主線未讀彙總視圖：UNION worker_reports 與 worker_inbox 的未讀（read_at IS NULL）。儲存分流、查詢統一。';
