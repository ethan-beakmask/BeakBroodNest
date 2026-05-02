-- 024_pending_outputs_view.down.sql
DROP VIEW IF EXISTS pending_outputs;
DROP INDEX IF EXISTS idx_worker_reports_unread;
ALTER TABLE worker_reports DROP COLUMN IF EXISTS read_at;
