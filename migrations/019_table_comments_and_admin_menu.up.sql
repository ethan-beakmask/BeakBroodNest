-- 019: 為所有現存資料表補上 COMMENT，並在 nav_menu 加入「資料表總覽」項目
-- 目的：讓 /admin/tables 頁面可動態取得每張表的用途；未來新增表只需在 migration
-- 中加 COMMENT ON TABLE 即可自動顯示，避免硬編碼維護。

BEGIN;

-- ============================================================
-- 核心：知識原子（Atom）
-- ============================================================
COMMENT ON TABLE atom_schemas             IS '原子 Schema 定義（如「方法論」「待辦」），決定 E 類原子的結構化欄位';
COMMENT ON TABLE schema_fields            IS '原子 Schema 的自訂欄位定義（key、型別、選項）';
COMMENT ON TABLE knowledge_atoms          IS '核心原子表：標題/內容/類型/生命週期/活力分數，知識庫的最小單位';
COMMENT ON TABLE atom_field_values        IS '原子在 schema 自訂欄位的實際值（key-value pairs）';
COMMENT ON TABLE atom_embeddings          IS '原子的 pgvector 向量嵌入，供語意搜尋使用';
COMMENT ON TABLE atom_tags                IS '原子-標籤多對多關聯表';
COMMENT ON TABLE lifecycle_transitions    IS '原子生命週期狀態變更紀錄（active->aging->archived 等）';

-- ============================================================
-- 關係（因果鍊）
-- ============================================================
COMMENT ON TABLE relation_type_registry   IS '關係類型註冊表（blocks/follows/supports 等），決定寫入驗證與下游視圖過濾';
COMMENT ON TABLE atom_relations           IS '原子間關係（舊版表，已被 unified_relations 取代）';
COMMENT ON TABLE unified_relations        IS '統一關係表（新版）：跨 atom/entry/canvas 的因果關係';

-- ============================================================
-- 標籤
-- ============================================================
COMMENT ON TABLE tag_categories           IS '標籤分類（如「待辦」「專案」「狀態」分組）';
COMMENT ON TABLE tag_category_members     IS '分類-標籤多對多關聯';
COMMENT ON TABLE tags                     IS '標籤主表（名稱、顏色、類型）';

-- ============================================================
-- 白板（Canvas）
-- ============================================================
COMMENT ON TABLE canvases                 IS '白板主表：名稱/slug/擁有者/快照';
COMMENT ON TABLE canvas_atoms             IS '白板上的原子位置與大小';
COMMENT ON TABLE canvas_groups            IS '白板群組（圈選多個原子成群）';
COMMENT ON TABLE canvas_group_members     IS '白板群組成員關聯';
COMMENT ON TABLE canvas_connections       IS '白板上原子之間的視覺連線';
COMMENT ON TABLE canvas_mindmap_shells    IS '白板心智圖殼框（radial layout 容器）';
COMMENT ON TABLE canvas_textboxes         IS '白板自由文字框（非原子的純註記）';
COMMENT ON TABLE canvas_trash             IS '白板回收桶：記錄被刪除的元素以便還原';

-- ============================================================
-- Entry Schema（;;指令系統）
-- ============================================================
COMMENT ON TABLE entry_schemas            IS 'Entry Schema 定義（如「帳卡」「待辦」「記帳」），對應 ;;指令';
COMMENT ON TABLE entry_schema_fields      IS 'Entry Schema 的欄位定義（label、type、options、dimension）';
COMMENT ON TABLE atom_entries             IS 'Entry 實例：依 schema 建立的結構化原子';
COMMENT ON TABLE entry_field_values       IS 'Entry 欄位實際值（多型別：text/datetime/number 等）';
COMMENT ON TABLE entry_field_change_log   IS 'Entry 欄位變更歷史紀錄（誰在何時改了什麼）';

-- ============================================================
-- 交換包（跨 Cortex 知識交換）
-- ============================================================
COMMENT ON TABLE exchange_packs           IS '交換包：可匯出/匯入的原子集合，用於跨環境同步';
COMMENT ON TABLE exchange_pack_atoms      IS '交換包與原子的多對多關聯';

-- ============================================================
-- 脫敏
-- ============================================================
COMMENT ON TABLE sensitive_terms          IS '可重複使用的敏感詞彙清單，AI 脫敏時自動替換';
COMMENT ON TABLE sanitize_sessions        IS '每次脫敏操作的 session 紀錄，保留映射表供還原';

-- ============================================================
-- 訊息與系統
-- ============================================================
COMMENT ON TABLE messages                 IS '跨專案收件匣訊息：Claude 在不同專案間的通知/請求/警示';
COMMENT ON TABLE nav_menu                 IS '前端動態導覽選單項目';
COMMENT ON TABLE system_config            IS '系統 KV 組態：認證帳密、Flask secret key、部署模式等';
COMMENT ON TABLE uploaded_files           IS '使用者上傳的檔案（圖片/附件），以 token 引用';

-- ============================================================
-- Pipeline（對話復盤）
-- ============================================================
COMMENT ON TABLE conversations            IS 'P0 匯入的 Claude 對話 session 元資料';
COMMENT ON TABLE conversation_turns       IS '對話逐輪內容（含工具呼叫、thinking、token 用量），P1/P2 處理';
COMMENT ON TABLE pipeline_runs            IS 'Pipeline 執行追蹤（daily_review 等 cron 工作）';
COMMENT ON TABLE session_logs             IS 'Claude session 元資料（每次對話的開始/結束、統計、異常標記）';

-- ============================================================
-- Orchestrator（多 Agent 協作）
-- ============================================================
COMMENT ON TABLE worker_tasks             IS '派發給支線 Claude Agent 的任務佇列';
COMMENT ON TABLE worker_reports           IS '支線 Agent 執行完成後回報的結果';

-- ============================================================
-- nav_menu 加入「資料表總覽」項目
-- ============================================================
INSERT INTO nav_menu (name, url, icon, sort_order, is_active, created_at)
SELECT '資料表總覽', '/beakbroodnest/admin/tables', '', 90, TRUE, NOW()
WHERE NOT EXISTS (
    SELECT 1 FROM nav_menu WHERE url = '/beakbroodnest/admin/tables'
);

COMMIT;
