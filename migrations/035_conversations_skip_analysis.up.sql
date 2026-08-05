-- 035: conversations.skip_analysis 欄位
--
-- 背景：
--   P0 匯入 (scripts/db_importer.py) 會在 INSERT 時寫入 skip_analysis，
--   P1/P2 (signal_scanner_db.py、semantic_summarizer.py) 以
--   「skip_analysis IS NOT NULL 即排除」過濾 pipeline 自產 session，
--   scripts/backfill_pipeline_skip.sql 也直接 UPDATE 此欄位。
--   但欄位從未進過版控的 schema（開發機是手動 ALTER 加的），導致外部環境
--   db_importer 每個 jsonl 都以
--   「column "skip_analysis" of relation "conversations" does not exist」失敗，
--   公司端自 2026-07-23 起匯入全數停擺 12 天（每 10 分鐘排程空轉）。
--
-- 編號說明：
--   公司端 2026-08-05 本地補的是 032，但 GitHub 的 032~034 已發布，故 2026-10-15
--   合併時改編為 035。內容全程冪等，對已手動套用過的環境（公司端、開發機）重跑無副作用。
--
-- 語義：
--   NULL       = 正常對話，需要 P1/P2 分析
--   'pipeline' = pipeline 自產 session（避免自我循環污染）
--   'discard'  = 人工判定丟棄
--   'no_analyze' = 明確不分析
--   採 TEXT 而非 boolean/enum：值域仍在演進，且需保留「為何跳過」的原因。
--
-- 執行方式：
--   psql -U beak_broodnest -d beak_broodnest -f migrations/035_conversations_skip_analysis.up.sql
--   套用後可再執行 scripts/backfill_pipeline_skip.sql 回補歷史資料。
--   install.sh（全新安裝與 --update）會自動套用。

BEGIN;

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS skip_analysis TEXT;

-- P1/P2 的過濾條件是 skip_analysis IS NULL，故索引只收非 NULL 值即可。
-- 既有環境可能已用別的名字建過同欄位索引（開發機 idx_conv_skip_analysis、
-- 公司端 idx_conversations_skip_analysis），有任何一個就不再重建，避免重複索引。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = current_schema()
          AND tablename = 'conversations'
          AND indexdef LIKE '%(skip_analysis)%'
    ) THEN
        CREATE INDEX idx_conv_skip_analysis
            ON conversations (skip_analysis) WHERE skip_analysis IS NOT NULL;
    END IF;
END $$;

COMMENT ON COLUMN conversations.skip_analysis IS
    'NULL=需分析；pipeline=pipeline 自產 session；discard=人工丟棄；no_analyze=明確不分析。P1/P2 以 IS NOT NULL 排除。';

COMMIT;
