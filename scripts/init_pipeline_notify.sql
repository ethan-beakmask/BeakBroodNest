-- 事件驅動 pipeline：conversation_turns 有新資料時 NOTIFY 喚醒 pipeline_listener
--
-- P0（db_importer.py）INSERT conversation_turns 後，statement-level trigger
-- 發出 pg_notify('bbn_new_turns')。NOTIFY 於 transaction commit 時才送達，
-- listener 收到時資料保證已可見。listener 端自行 debounce，
-- 因此 trigger 不需要去重、不帶 payload。
--
-- 執行方式（重複執行無害）：
--   psql -U beak_broodnest -d beak_broodnest -f scripts/init_pipeline_notify.sql

CREATE OR REPLACE FUNCTION bbn_notify_new_turns() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('bbn_new_turns', '');
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_bbn_notify_new_turns ON conversation_turns;
CREATE TRIGGER trg_bbn_notify_new_turns
    AFTER INSERT ON conversation_turns
    FOR EACH STATEMENT
    EXECUTE FUNCTION bbn_notify_new_turns();
