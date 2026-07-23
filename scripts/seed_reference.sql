-- =============================================================================
-- BeakBroodNest 參考資料種子（seed_reference.sql）
-- =============================================================================
-- !!! 本檔為「產生檔」，請勿手動編輯 !!!
-- 由 scripts/gen_reference_seed.py 從開發機 DB 自動產生。
-- 要變更內容：改開發機 DB -> 執行 gen_reference_seed.py --write -> commit。
-- push 前請跑 gen_reference_seed.py --check 確認無未回寫的 drift。
--
-- 涵蓋的參考表（白名單，父表在前）：
--   atom_schemas             atom 動態 schema 定義
--   schema_fields            atom schema 的欄位（FK -> atom_schemas）
--   entry_schemas            ;;物件 結構化物件類型（自由文字 / 待辦 / 記帳 ...）
--   entry_schema_fields      結構化物件的欄位定義（FK -> entry_schemas）
--   nav_menu                 主選單項目
--   relation_type_registry   因果鍊關係類型
--   tag_categories           標籤分類
--   gantt_colors_default     甘特圖預設配色
--
-- 全部 INSERT 皆 ON CONFLICT DO NOTHING，可安全重複執行；
-- 既有列不會被覆寫（只補缺列）。
-- =============================================================================

BEGIN;

-- ----- atom_schemas (2 列) -----
INSERT INTO atom_schemas (id, name, slug, description, icon, created_at, updated_at) VALUES (1, '效能測試報告', 'perf_test', '白板渲染效能壓測記錄，含測試環境、參數、結果', '', '2026-04-14 22:12:09.792021', '2026-04-14 22:12:09.792032') ON CONFLICT DO NOTHING;
INSERT INTO atom_schemas (id, name, slug, description, icon, created_at, updated_at) VALUES (2, '方法論紀錄', 'methodology', '復盤產出的流程經驗紀錄，記錄做事方法的 know-how，供後續任務檢索避免重蹈覆轍', '', '2026-04-15 05:38:11.473206', '2026-04-15 05:38:11.473215') ON CONFLICT DO NOTHING;

-- ----- schema_fields (17 列) -----
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

-- ----- entry_schemas (8 列) -----
INSERT INTO entry_schemas (id, code, name, icon, color, slash_alias, is_system, sort_order, created_at, updated_at) VALUES (1, 'freetext', '自由文字', 'bi-text-left', '#6b7280', NULL, true, 0, '2026-04-21 10:38:41.225055', '2026-04-21 10:38:41.225063') ON CONFLICT DO NOTHING;
INSERT INTO entry_schemas (id, code, name, icon, color, slash_alias, is_system, sort_order, created_at, updated_at) VALUES (2, 'task', '待辦事項', 'bi-check2-square', '#3b82f6', 'td', true, 1, '2026-04-21 10:38:41.227750', '2026-04-21 10:38:41.227755') ON CONFLICT DO NOTHING;
INSERT INTO entry_schemas (id, code, name, icon, color, slash_alias, is_system, sort_order, created_at, updated_at) VALUES (3, 'expense', '記帳', 'bi-wallet2', '#10b981', 'exp', true, 2, '2026-04-21 10:38:41.234457', '2026-04-21 10:38:41.234464') ON CONFLICT DO NOTHING;
INSERT INTO entry_schemas (id, code, name, icon, color, slash_alias, is_system, sort_order, created_at, updated_at) VALUES (5, 'diary', '日記', 'bi-journal-text', '#a855f7', 'diary', true, 4, '2026-04-21 10:38:41.242293', '2026-04-21 10:38:41.242299') ON CONFLICT DO NOTHING;
INSERT INTO entry_schemas (id, code, name, icon, color, slash_alias, is_system, sort_order, created_at, updated_at) VALUES (6, 'health', '健康記錄', 'bi-heart-pulse', '#ef4444', 'hp', true, 5, '2026-04-21 10:38:41.246644', '2026-04-21 10:38:41.246651') ON CONFLICT DO NOTHING;
INSERT INTO entry_schemas (id, code, name, icon, color, slash_alias, is_system, sort_order, created_at, updated_at) VALUES (7, 'file', '檔案', 'bi-paperclip', '#64748b', 'file', true, 6, '2026-04-26 00:19:48.641267', '2026-04-26 00:19:48.641274') ON CONFLICT DO NOTHING;
INSERT INTO entry_schemas (id, code, name, icon, color, slash_alias, is_system, sort_order, created_at, updated_at) VALUES (9, 'idcard', '帳卡', 'bi-person-badge', '#0ea5e9', 'idcard', true, 80, '2026-04-28 23:30:01.187655', '2026-04-28 23:30:01.187655') ON CONFLICT DO NOTHING;
INSERT INTO entry_schemas (id, code, name, icon, color, slash_alias, is_system, sort_order, created_at, updated_at) VALUES (10, 'image', '圖片', 'bi-image', '#14b8a6', 'image', true, 81, '2026-05-19 15:05:59.500539', '2026-05-19 15:05:59.500539') ON CONFLICT DO NOTHING;

-- ----- entry_schema_fields (45 列) -----
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (1, 2, 'urgency', '緊急度', 'select', '["H","M","L"]', NULL, false, 0, 'Y', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (2, 2, 'category', '類別', 'select', '["安全性", "文件", "測試", "功能", "復盤Pipeline", "基建"]', NULL, false, 1, 'H', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (3, 2, 'planned_start', '預計開始', 'datetime', '', NULL, false, 2, 'T', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (4, 2, 'planned_duration', '預估耗時', 'duration', '', NULL, false, 4, 'T', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (5, 2, 'actual_start', '實際開始', 'datetime', '', NULL, false, 5, 'T', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (6, 2, 'actual_end', '實際結束', 'datetime', '', NULL, false, 6, 'T', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (7, 2, 'status', '狀態', 'select', '["planning", "in_progress", "paused", "completed", "cancelled"]', NULL, false, 7, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (8, 3, 'date', '日期', 'date', '', NULL, true, 0, 'T', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (9, 3, 'cat_major', '大類', 'select', '[]', NULL, false, 1, 'H', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (10, 3, 'cat_mid', '中類', 'select', '[]', NULL, false, 2, 'H', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (11, 3, 'cat_minor', '小類', 'select', '[]', NULL, false, 3, 'H', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (12, 3, 'amount', '金額', 'decimal', '', NULL, true, 4, 'H', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (13, 3, 'payment', '付款方式', 'select', '[]', NULL, false, 5, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (14, 3, 'note', '備註', 'text', '', NULL, false, 6, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (21, 5, 'date', '日期', 'date', '', NULL, true, 0, 'T', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (22, 5, 'weather', '天氣', 'select', '["sunny","cloudy","rainy","snowy","windy","foggy"]', NULL, false, 1, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (23, 5, 'mood', '心情', 'select', '["1","2","3","4","5"]', NULL, false, 2, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (24, 5, 'body', '內容', 'text', '', NULL, false, 3, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (25, 6, 'date', '日期', 'date', '', NULL, true, 0, 'T', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (26, 6, 'measure_type', '量測類型', 'select', '["blood_pressure","blood_sugar","weight","heart_rate","temperature","other"]', NULL, true, 1, 'H', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (27, 6, 'value_num', '數值', 'decimal', '', NULL, true, 2, 'H', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (28, 6, 'unit', '單位', 'text', '', NULL, false, 3, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (29, 6, 'note', '備註', 'text', '', NULL, false, 4, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (30, 2, 'baseline_start', '原計畫開始', 'datetime', '', NULL, false, 10, NULL, true) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (31, 2, 'baseline_end', '原計畫結束', 'datetime', '', NULL, false, 11, NULL, true) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (32, 2, 'progress', '進度', 'number', '{"min":0,"max":100}', NULL, false, 12, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (33, 2, 'planned_end', '預計結束', 'datetime', '', NULL, false, 3, 'T', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (34, 2, 'location', '地點', 'text', '', NULL, false, 8, 'P', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (35, 2, 'attendees', '出席者', 'text', '', NULL, false, 9, 'W', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (36, 2, 'note', '備註', 'text', '', NULL, false, 13, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (37, 7, 'filename', '檔名', 'text', '', NULL, true, 0, 'H', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (38, 7, 'file_token', '識別碼', 'text', '', NULL, true, 1, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (39, 7, 'mime_type', '類型', 'text', '', NULL, false, 2, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (40, 7, 'size_bytes', '大小(B)', 'number', '', NULL, false, 3, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (41, 9, 'line2', '副標', 'text', '', NULL, false, 2, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (42, 9, 'line4', '第四列', 'text', '', NULL, false, 4, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (43, 9, 'image_token', '圖檔', 'text', '', NULL, false, 0, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (44, 9, 'is_primary', '白板主帳卡', 'checkbox', '', NULL, false, 5, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (45, 9, 'line1', '主標', 'text', '', NULL, false, 1, 'W', false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (46, 9, 'line3', '第三列', 'text', '', NULL, false, 3, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (47, 2, 'pause_log', '暫停紀錄', 'text', '', NULL, false, 14, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (48, 2, 'cancel_info', '取消資訊', 'text', '', NULL, false, 15, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (49, 2, 'reopen_log', '重啟紀錄', 'text', '', NULL, false, 16, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (50, 10, 'image_token', '圖檔', 'text', '', NULL, false, 0, NULL, false) ON CONFLICT DO NOTHING;
INSERT INTO entry_schema_fields (id, schema_id, name, label, field_type, options, default_value, required, sort_order, dimension, is_frozen) VALUES (51, 10, 'caption', '說明', 'text', '', NULL, false, 1, NULL, false) ON CONFLICT DO NOTHING;

-- ----- nav_menu (8 列) -----
INSERT INTO nav_menu (id, name, url, icon, sort_order, is_active, created_at) VALUES (1, '白板', '/beakbroodnest/', '', 10, true, '2026-04-21 13:50:00.676771') ON CONFLICT DO NOTHING;
INSERT INTO nav_menu (id, name, url, icon, sort_order, is_active, created_at) VALUES (2, 'Orchestrator', '/beakbroodnest/orchestrator', '', 20, true, '2026-04-21 13:50:00.676771') ON CONFLICT DO NOTHING;
INSERT INTO nav_menu (id, name, url, icon, sort_order, is_active, created_at) VALUES (3, 'Observe', '/beakbroodnest/observe', '', 30, true, '2026-04-21 13:50:00.676771') ON CONFLICT DO NOTHING;
INSERT INTO nav_menu (id, name, url, icon, sort_order, is_active, created_at) VALUES (4, '專案', '/beakbroodnest/project/', '', 15, true, '2026-04-21 16:19:31.073271') ON CONFLICT DO NOTHING;
INSERT INTO nav_menu (id, name, url, icon, sort_order, is_active, created_at) VALUES (5, '資料表總覽', '/beakbroodnest/admin/tables', '', 90, true, '2026-04-29 11:06:45.594039') ON CONFLICT DO NOTHING;
INSERT INTO nav_menu (id, name, url, icon, sort_order, is_active, created_at) VALUES (7, '行事曆', '/beakbroodnest/calendar', '', 18, true, '2026-05-08 18:46:08.330858') ON CONFLICT DO NOTHING;
INSERT INTO nav_menu (id, name, url, icon, sort_order, is_active, created_at) VALUES (9, '待辦', '/beakbroodnest/todos', 'bi-check2-square', 19, true, '2026-05-17 18:41:58.605732') ON CONFLICT DO NOTHING;
INSERT INTO nav_menu (id, name, url, icon, sort_order, is_active, created_at) VALUES (10, '閱覽器', '/beakbroodnest/reader/', 'bi-journal-text', 50, true, '2026-05-26 22:33:23.042573') ON CONFLICT DO NOTHING;

-- ----- relation_type_registry (12 列) -----
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('blocks', 'dag', 'temporal', true, '阻塞', true, '硬排程約束 Finish-to-Start，違反即排程失敗', '#dc2626', 'solid', 2) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('causes', 'dag', 'temporal', false, '因果', true, '事件因果，事實描述性，預設不進 Gantt 計算', '#8b5cf6', 'solid', 5) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('contains', 'tree', 'structural', false, '包含', true, '父子層級分解；形成嚴格樹狀，每節點僅一個父節點，禁止成環；對應 WBS', '#6b7280', 'solid', 1) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('contradicts', 'general', 'discourse', false, '矛盾', false, '論證衝突，A 與 B 互斥或對立', '#ef4444', 'solid', 7) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('derives_from', 'dag', 'discourse', false, '衍生', true, '知識演化，B 衍生自 A', '#6366f1', 'solid', 8) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('enables', 'dag', 'temporal', false, '啟用', true, '前提條件，使目標成為可能，預設不進 Gantt 計算', '#10b981', 'solid', 4) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('follows', 'dag', 'temporal', true, '順序', true, '軟排程約束，時間先後偏好，可被排程器放寬', '#f59e0b', 'solid', 3) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('freeform', 'general', 'discourse', false, '自由', true, 'A 畫一條線到 B，自由思考用', '#000000', 'solid', 0) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('references', 'general', 'discourse', false, '參考', true, '引用關係，A 引用 B 作為參考來源', '#94a3b8', 'dashed', 10) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('supersedes', 'dag', 'discourse', false, '取代', true, '版本替換，A 取代 B，舊版本作廢', '#64748b', 'solid', 9) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('supports', 'general', 'discourse', false, '支持', true, '論證支撐，A 的論點支持 B 的結論', '#3b82f6', 'solid', 6) ON CONFLICT DO NOTHING;
INSERT INTO relation_type_registry (relation_type, graph_family, semantic_layer, affects_scheduling, display_name, is_directed, description, default_color, default_style, sort_order) VALUES ('tree_parent', 'acyclic_tree', 'structural', false, '從屬於', true, '心智圖/樹狀結構:子節點從屬於父節點，每個節點最多一個父', '#94a3b8', 'solid', 11) ON CONFLICT DO NOTHING;

-- ----- tag_categories (7 列) -----
INSERT INTO tag_categories (id, name, sort_order, created_at) VALUES (2, '技術', 0, '2026-04-17 04:29:21.384765') ON CONFLICT DO NOTHING;
INSERT INTO tag_categories (id, name, sort_order, created_at) VALUES (3, '應用', 0, '2026-04-17 04:29:28.633461') ON CONFLICT DO NOTHING;
INSERT INTO tag_categories (id, name, sort_order, created_at) VALUES (4, '機敏', 0, '2026-04-17 04:29:41.094355') ON CONFLICT DO NOTHING;
INSERT INTO tag_categories (id, name, sort_order, created_at) VALUES (5, '專案開發', 0, '2026-04-17 04:30:04.511391') ON CONFLICT DO NOTHING;
INSERT INTO tag_categories (id, name, sort_order, created_at) VALUES (6, '專案名稱', 0, '2026-04-17 04:30:16.929125') ON CONFLICT DO NOTHING;
INSERT INTO tag_categories (id, name, sort_order, created_at) VALUES (7, '工具', 0, '2026-04-17 04:31:30.164456') ON CONFLICT DO NOTHING;
INSERT INTO tag_categories (id, name, sort_order, created_at) VALUES (10, '公司', 0, '2026-05-18 14:35:53.911826') ON CONFLICT DO NOTHING;

-- ----- gantt_colors_default (2 列) -----
INSERT INTO gantt_colors_default (username, colors, updated_at) VALUES ('admin', '{"noBarBgColor":"#3a9cfd","outlineCard":"#3a9cfd","summaryBarColor":"#266acf","taskColors":["#f0f0ff","#f7fff5","#f0f9ff"]}', '2026-05-09 04:39:15.458336') ON CONFLICT DO NOTHING;
INSERT INTO gantt_colors_default (username, colors, updated_at) VALUES ('admin-ethan', '{"noBarBgColor":"#a0c8f0","outlineCard":"#a0c8f0","summaryBarColor":"#0d39e7","taskColors":["#f0f0ff","#f7fff5","#f0f9ff"]}', '2026-05-09 04:42:37.361802') ON CONFLICT DO NOTHING;

-- 重設 SERIAL 序列，確保下次 INSERT 不撞既有 id
SELECT setval('atom_schemas_id_seq', COALESCE((SELECT MAX(id) FROM atom_schemas), 1));
SELECT setval('schema_fields_id_seq', COALESCE((SELECT MAX(id) FROM schema_fields), 1));
SELECT setval('entry_schemas_id_seq', COALESCE((SELECT MAX(id) FROM entry_schemas), 1));
SELECT setval('entry_schema_fields_id_seq', COALESCE((SELECT MAX(id) FROM entry_schema_fields), 1));
SELECT setval('nav_menu_id_seq', COALESCE((SELECT MAX(id) FROM nav_menu), 1));
SELECT setval('tag_categories_id_seq', COALESCE((SELECT MAX(id) FROM tag_categories), 1));

COMMIT;
