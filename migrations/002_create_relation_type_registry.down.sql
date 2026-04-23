-- Migration 002 DOWN: 移除 relation_type_registry
-- 前提：003 的 FK 必須先移除（先跑 003 down）

BEGIN;

DROP TABLE IF EXISTS relation_type_registry;

COMMIT;
