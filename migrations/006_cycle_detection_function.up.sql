-- Migration 006 UP: 環偵測函式
-- 用 recursive CTE 檢查新增邊是否會在同族子圖中產生環
-- 前提：003 (atom_relations 已有 graph_family, is_deleted 欄位)
-- 回滾：006_cycle_detection_function.down.sql

BEGIN;

CREATE OR REPLACE FUNCTION check_would_create_cycle(
    p_from_id INTEGER,
    p_to_id INTEGER,
    p_graph_family VARCHAR(20)
) RETURNS BOOLEAN AS $$
BEGIN
    -- free_graph 不檢查環
    IF p_graph_family = 'free_graph' THEN
        RETURN FALSE;
    END IF;

    -- 自環
    IF p_from_id = p_to_id THEN
        RETURN TRUE;
    END IF;

    -- 從 to_id 出發，沿同族的出邊走，看能否到達 from_id
    RETURN EXISTS (
        WITH RECURSIVE reachable AS (
            SELECT ar.to_atom_id AS node_id, 1 AS depth
            FROM atom_relations ar
            WHERE ar.from_atom_id = p_to_id
              AND ar.graph_family = p_graph_family
              AND ar.is_deleted = FALSE

            UNION ALL

            SELECT ar.to_atom_id, r.depth + 1
            FROM reachable r
            JOIN atom_relations ar
              ON ar.from_atom_id = r.node_id
              AND ar.graph_family = p_graph_family
              AND ar.is_deleted = FALSE
            WHERE r.depth < 100
              AND r.node_id <> p_from_id
        )
        SELECT 1 FROM reachable WHERE node_id = p_from_id
        LIMIT 1
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION check_would_create_cycle IS
    'Phase 1: 檢查新增邊 (from->to) 是否會在指定 graph_family 的子圖中產生環。free_graph 永遠回傳 FALSE。';

COMMIT;
