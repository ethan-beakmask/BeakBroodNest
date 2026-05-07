-- =============================================================================
-- BeakBroodNest 基線種子資料
-- =============================================================================
-- 由 install.sh 在 create_all_tables() 之後呼叫，建立系統運作所需的最小 seed。
-- 內容包含：
--   1. nav_menu          主選單 5 項（白板 / 專案 / Orchestrator / Observe / 資料表總覽）
--   2. relation_type_registry  因果鍊類型 12 種（contains / blocks / follows ...）
--   3. atom_schemas + schema_fields  atom schema 定義（效能測試報告、方法論紀錄）
--   4. tag_categories    標籤分類 6 類
--   5. pending_outputs view  跨 worker_reports / worker_inbox 的未讀統一視圖
--
-- 不包含：
--   - sensitive_terms（個人/環境特定，請自行透過 UI 或 sensitive_term_add MCP tool 設定）
--   - 對話、白板、上傳檔等使用者資料
--
-- 所有 INSERT 皆 ON CONFLICT DO NOTHING，可重複執行。
-- 執行：
--   PGPASSWORD=xxx psql -U <db_user> -d <db_name> -h 127.0.0.1 -f scripts/seed_baseline.sql
-- =============================================================================

BEGIN;

INSERT INTO atom_schemas (id, name, slug, description, icon, created_at, updated_at) VALUES (1, '效能測試報告', 'perf_test', '白板渲染效能壓測記錄，含測試環境、參數、結果', '', '2026-04-14 22:12:09.792021', '2026-04-14 22:12:09.792032') ON CONFLICT DO NOTHING;
INSERT INTO atom_schemas (id, name, slug, description, icon, created_at, updated_at) VALUES (2, '方法論紀錄', 'methodology', '復盤產出的流程經驗紀錄，記錄做事方法的 know-how，供後續任務檢索避免重蹈覆轍', '', '2026-04-15 05:38:11.473206', '2026-04-15 05:38:11.473215') ON CONFLICT DO NOTHING;
INSERT INTO nav_menu (id, name, url, icon, sort_order, is_active, created_at) VALUES (1, '白板', '/beakbroodnest/', '', 10, true, '2026-04-21 13:50:00.676771') ON CONFLICT DO NOTHING;
INSERT INTO nav_menu (id, name, url, icon, sort_order, is_active, created_at) VALUES (3, 'Observe', '/beakbroodnest/observe', '', 30, true, '2026-04-21 13:50:00.676771') ON CONFLICT DO NOTHING;
INSERT INTO nav_menu (id, name, url, icon, sort_order, is_active, created_at) VALUES (5, '資料表總覽', '/beakbroodnest/admin/tables', '', 90, true, '2026-04-29 11:06:45.594039') ON CONFLICT DO NOTHING;
INSERT INTO nav_menu (id, name, url, icon, sort_order, is_active, created_at) VALUES (4, '專案', '/beakbroodnest/project/', '', 15, true, '2026-04-21 16:19:31.073271') ON CONFLICT DO NOTHING;
INSERT INTO nav_menu (id, name, url, icon, sort_order, is_active, created_at) VALUES (2, 'Orchestrator', '/beakbroodnest/orchestrator', '', 20, true, '2026-04-21 13:50:00.676771') ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('contains', 'tree', 'structural', false, '包含', true, '父子層級分解；形成嚴格樹狀，每節點僅一個父節點，禁止成環；對應 WBS', '#6b7280', 'solid', 1) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('blocks', 'dag', 'temporal', true, '阻塞', true, '硬排程約束 Finish-to-Start，違反即排程失敗', '#dc2626', 'solid', 2) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('follows', 'dag', 'temporal', true, '順序', true, '軟排程約束，時間先後偏好，可被排程器放寬', '#f59e0b', 'solid', 3) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('enables', 'dag', 'temporal', false, '啟用', true, '前提條件，使目標成為可能，預設不進 Gantt 計算', '#10b981', 'solid', 4) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('causes', 'dag', 'temporal', false, '因果', true, '事件因果，事實描述性，預設不進 Gantt 計算', '#8b5cf6', 'solid', 5) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('supports', 'general', 'discourse', false, '支持', true, '論證支撐，A 的論點支持 B 的結論', '#3b82f6', 'solid', 6) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('contradicts', 'general', 'discourse', false, '矛盾', false, '論證衝突，A 與 B 互斥或對立', '#ef4444', 'solid', 7) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('derives_from', 'dag', 'discourse', false, '衍生', true, '知識演化，B 衍生自 A', '#6366f1', 'solid', 8) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('supersedes', 'dag', 'discourse', false, '取代', true, '版本替換，A 取代 B，舊版本作廢', '#64748b', 'solid', 9) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('freeform', 'general', 'discourse', false, '自由', true, 'A 畫一條線到 B，自由思考用', '#000000', 'solid', 0) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('references', 'general', 'discourse', false, '參考', true, '引用關係，A 引用 B 作為參考來源', '#94a3b8', 'dashed', 10) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('tree_parent', 'acyclic_tree', 'structural', false, '從屬於', true, '心智圖/樹狀結構:子節點從屬於父節點，每個節點最多一個父', '#94a3b8', 'solid', 11) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (1, 1, 'test_date', '測試日期', 'date', '', 0, true) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (2, 1, 'node_count', 'Node 數量', 'number', '', 1, true) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (3, 1, 'edge_count', 'Edge 數量', 'number', '', 2, false) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (4, 1, 'engine', '渲染引擎', 'select', 'individual,grouped', 3, false) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (5, 1, 'line_style', '線條樣式', 'select', 'curve,straight,none', 4, false) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (6, 1, 'optimization', '優化策略', 'select', 'off,8way', 5, false) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (7, 1, 'opt_per_sector', '每扇區上限', 'number', '', 6, false) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (8, 1, 'result', '測試結果', 'select', 'smooth,acceptable,lag,severe_lag', 7, true) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (9, 1, 'notes', '備註', 'text', '', 8, false) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (10, 2, 'trigger_context', '情境', 'text', '', 0, true) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (11, 2, 'original_approach', '原做法', 'text', '', 1, true) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (12, 2, 'problem', '問題', 'text', '', 2, true) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (13, 2, 'improved_approach', '改進做法', 'text', '', 3, true) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (14, 2, 'applicable_when', '適用條件', 'text', '', 4, true) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (15, 2, 'domain', '領域', 'select', 'code,schema,process,infra,security', 5, false) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (16, 2, 'confidence', '可信度', 'select', 'proven,experimental,speculative', 6, false) ON CONFLICT DO NOTHING;
INSERT INTO schema_fields (id, schema_id, name, label, field_type, options, sort_order, required) VALUES (17, 2, 'discovered_at', '發現日期', 'date', '', 7, true) ON CONFLICT DO NOTHING;
INSERT INTO tag_categories (id, name, sort_order, created_at) VALUES (2, '技術', 0, '2026-04-17 04:29:21.384765') ON CONFLICT DO NOTHING;
INSERT INTO tag_categories (id, name, sort_order, created_at) VALUES (3, '應用', 0, '2026-04-17 04:29:28.633461') ON CONFLICT DO NOTHING;
INSERT INTO tag_categories (id, name, sort_order, created_at) VALUES (4, '機敏', 0, '2026-04-17 04:29:41.094355') ON CONFLICT DO NOTHING;
INSERT INTO tag_categories (id, name, sort_order, created_at) VALUES (5, '專案開發', 0, '2026-04-17 04:30:04.511391') ON CONFLICT DO NOTHING;
INSERT INTO tag_categories (id, name, sort_order, created_at) VALUES (6, '專案名稱', 0, '2026-04-17 04:30:16.929125') ON CONFLICT DO NOTHING;
INSERT INTO tag_categories (id, name, sort_order, created_at) VALUES (7, '工具', 0, '2026-04-17 04:31:30.164456') ON CONFLICT DO NOTHING;

-- 重設 SERIAL 序列（確保下次 INSERT 不會撞到既有 id）
SELECT setval('atom_schemas_id_seq',    COALESCE((SELECT MAX(id) FROM atom_schemas), 1));
SELECT setval('nav_menu_id_seq',        COALESCE((SELECT MAX(id) FROM nav_menu), 1));
SELECT setval('schema_fields_id_seq',   COALESCE((SELECT MAX(id) FROM schema_fields), 1));
SELECT setval('tag_categories_id_seq',  COALESCE((SELECT MAX(id) FROM tag_categories), 1));

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
