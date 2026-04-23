-- Migration 006 DOWN: 移除環偵測函式

BEGIN;

DROP FUNCTION IF EXISTS check_would_create_cycle(INTEGER, INTEGER, VARCHAR);

COMMIT;
