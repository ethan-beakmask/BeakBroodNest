-- 一次性回補：將歷史上未被標記的 pipeline 自產 session 補上 skip_analysis='pipeline'
--
-- 背景：舊版 P2 用「執行後 diff 目錄猜 UUID 再 UPDATE」標記 pipeline session，
-- 但該 UPDATE 執行時 conversation row 尚未被 P0 匯入，長期靜默失敗（0 rows affected），
-- 造成 P1/P2 把自產摘要 session 當成分析對象的自我循環污染（知識庫 #4837）。
-- 新版改由 P0 匯入當下依 [CC-LAUNCH-KIND=...] marker 同步標記；本檔回補既有資料。
--
-- 執行方式（fork 用戶升級後執行一次即可，重複執行無害）：
--   psql -U beak_broodnest -d beak_broodnest -f scripts/backfill_pipeline_skip.sql

UPDATE conversations SET skip_analysis = 'pipeline'
WHERE skip_analysis IS NULL
  AND id IN (
    SELECT DISTINCT conversation_id FROM conversation_turns
    WHERE actor_id = 'p2-dispatcher'
       OR (role = 'user' AND content LIKE '[CC-LAUNCH-KIND=p2-dispatcher]%')
  );
