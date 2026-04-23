-- Migration 003 UP: 增強 atom_relations
-- 加入圖族/語意層衍生欄位、軟刪除、排序、metadata
-- 建立自動填入 trigger、回填既有資料、設定 NOT NULL、建索引
-- 前提：002 (relation_type_registry) 已執行
-- 回滾：003_enhance_atom_relations.down.sql

BEGIN;

-- ============================================================
-- Step A: 加入欄位（先允許 NULL，回填後再設 NOT NULL）
-- ============================================================

ALTER TABLE atom_relations
    ADD COLUMN graph_family VARCHAR(20),
    ADD COLUMN semantic_layer VARCHAR(20),
    ADD COLUMN affects_scheduling BOOLEAN,
    ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN sort_order INTEGER DEFAULT 0,
    ADD COLUMN metadata JSONB DEFAULT '{}';

-- ============================================================
-- Step B: 加入 FK 到 registry
-- ============================================================

ALTER TABLE atom_relations
    ADD CONSTRAINT fk_relation_type
    FOREIGN KEY (relation_type)
    REFERENCES relation_type_registry(relation_type);

-- ============================================================
-- Step C: 建立 trigger（此後新 INSERT/UPDATE 自動填值）
-- ============================================================

CREATE OR REPLACE FUNCTION trg_fill_relation_metadata()
RETURNS TRIGGER AS $$
BEGIN
    SELECT graph_family, semantic_layer, affects_scheduling
    INTO NEW.graph_family, NEW.semantic_layer, NEW.affects_scheduling
    FROM relation_type_registry
    WHERE relation_type = NEW.relation_type;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER atom_relations_fill_metadata
    BEFORE INSERT OR UPDATE OF relation_type
    ON atom_relations
    FOR EACH ROW
    EXECUTE FUNCTION trg_fill_relation_metadata();

-- ============================================================
-- Step D: 回填既有資料
-- ============================================================

UPDATE atom_relations ar
SET graph_family = rtr.graph_family,
    semantic_layer = rtr.semantic_layer,
    affects_scheduling = rtr.affects_scheduling
FROM relation_type_registry rtr
WHERE ar.relation_type = rtr.relation_type
  AND ar.graph_family IS NULL;

-- ============================================================
-- Step E: 確認無遺漏後，設定 NOT NULL 約束（fail fast 策略）
-- ============================================================

ALTER TABLE atom_relations
    ALTER COLUMN graph_family SET NOT NULL,
    ALTER COLUMN semantic_layer SET NOT NULL,
    ALTER COLUMN affects_scheduling SET NOT NULL;

-- ============================================================
-- Step F: 建立索引
-- ============================================================

-- 圖族索引（環偵測的查詢路徑）
CREATE INDEX idx_relations_graph_family
    ON atom_relations(graph_family)
    WHERE is_deleted = FALSE;

-- 語意層索引（下游視圖過濾）
CREATE INDEX idx_relations_semantic_layer
    ON atom_relations(semantic_layer)
    WHERE is_deleted = FALSE;

-- 排程型關係索引（Gantt 視圖核心路徑）
CREATE INDEX idx_relations_scheduling
    ON atom_relations(to_atom_id, from_atom_id)
    WHERE affects_scheduling = TRUE AND is_deleted = FALSE;

-- 複合索引：某卡片的所有非刪除關係
CREATE INDEX idx_relations_from_active
    ON atom_relations(from_atom_id, relation_type)
    WHERE is_deleted = FALSE;

CREATE INDEX idx_relations_to_active
    ON atom_relations(to_atom_id, relation_type)
    WHERE is_deleted = FALSE;

COMMIT;
