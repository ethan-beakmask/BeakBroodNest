# BeakCortex Schema 三方比較報告

產出時間: 2026-04-22 03:15
目的: 為 DB 合併提供決策依據，先不執行合併

---

## 一、Schema 來源

| # | 來源 | 說明 |
|---|------|------|
| CODE | 程式碼 | models.py + lifecycle.py + orchestrator/models.py + init_pipeline_tables.sql + migration 001 |
| PROD | beak_cortex | 正式 DB，MCP server 使用中，Gunicorn port 5171 |
| DEV | beak_cortex_dev | 開發 DB，port 5175（目前未啟動） |

---

## 二、表級別比較（31 張表）

| 表名 | CODE | PROD | DEV | 備註 |
|------|:----:|:----:|:---:|------|
| knowledge_atoms | O | O (223) | O (38) | prod 資料多 |
| canvases | O | O (2) | O (2) | |
| canvas_atoms | O | O (31) | O (29) | |
| canvas_connections | O | O (1) | O (7) | |
| canvas_groups | O | O (0) | O (0) | |
| atom_relations | O | O (53) | O (15) | |
| atom_tags | O | O (323) | O (12) | |
| tags | O | O (98) | O (11) | |
| tag_categories | O | O (6) | O (0) | |
| tag_category_members | O | O (16) | O (0) | |
| atom_embeddings | O | O (202) | O (7) | |
| atom_field_values | O | O (88) | O (0) | |
| atom_schemas | O | O (2) | O (0) | |
| schema_fields | O | O (17) | O (0) | |
| messages | O | O (5) | O (1) | |
| nav_menu | O | O (4) | O (3) | |
| system_config | O | O (4) | O (4) | auth 帳密不同，不可覆蓋 |
| sensitive_terms | O | O (17) | O (0) | |
| sanitize_sessions | O | O (0) | O (0) | |
| entry_schemas | O | O (6) | O (6) | |
| entry_schema_fields | O | O (29) | O (32) | dev 多 3 筆 baseline/progress |
| atom_entries | O | O (57) | O (29) | |
| entry_field_values | O | O (91) | O (98) | dev 多因甘特圖測試 |
| unified_relations | O | O (0) | O (1) | |
| worker_tasks | O | O (16) | O (0) | |
| worker_reports | O | O (14) | O (0) | |
| **lifecycle_transitions** | O | **O (0)** | **X** | prod 有但 0 筆資料，dev 缺表 |
| **conversations** | O | O (1) | O (10) | schema 差異大 |
| **conversation_turns** | O | O (306) | O (3432) | schema 差異大，型別不同 |
| **pipeline_runs** | O | **X** | O (10) | prod 缺表 |
| **session_logs** | O | **X** | O (17) | prod 缺表 |

---

## 三、欄位級別差異（重大差異）

### 3.1 entry_schema_fields -- 甘特圖關鍵

| 欄位 | CODE | PROD | DEV |
|------|------|------|-----|
| is_frozen | `Boolean, default=False` | **缺少** | `boolean NOT NULL DEFAULT false` |

**決策要點**: 甘特圖基線功能依賴此欄位。prod 必須加入。
Migration: `001_add_baseline_fields.sql` 可直接在 prod 執行。

### 3.2 conversations -- 型別分歧

| 欄位 | CODE (SQL) | PROD | DEV |
|------|-----------|------|-----|
| session_id | `TEXT NOT NULL DEFAULT ''` | `varchar(64)`, nullable | `text NOT NULL DEFAULT ''` |
| jsonl_path | `TEXT NOT NULL DEFAULT ''` | `text`, nullable | `text NOT NULL DEFAULT ''` |
| jsonl_size | `BIGINT DEFAULT 0` | `bigint`, nullable | `bigint DEFAULT 0` |
| total_turns | `INTEGER DEFAULT 0` | `integer`, nullable | `integer DEFAULT 0` |
| git_branch | `TEXT DEFAULT ''` | `varchar(100)` | `text DEFAULT ''` |
| 索引 | 3 個 idx_conv_* | 無 | 3 個 idx_conv_* |

**決策要點**: dev 完全符合 CODE，prod 是早期手動建的。prod 只有 1 筆資料。

### 3.3 conversation_turns -- 最大分歧

| 欄位 | CODE (SQL) | PROD | DEV |
|------|-----------|------|-----|
| role | `TEXT NOT NULL DEFAULT ''` | `varchar(20) NOT NULL` | `text NOT NULL DEFAULT ''` |
| tool_name | `TEXT DEFAULT ''` | `varchar(100)` | `text DEFAULT ''` |
| tool_use_id | `TEXT DEFAULT ''` | `varchar(64)` | `text DEFAULT ''` |
| tool_is_error | `BOOLEAN DEFAULT FALSE` | `boolean`, no default | `boolean DEFAULT false` |
| **files_touched** | **`TEXT DEFAULT ''`** | **`text[]`** | **`text DEFAULT ''`** |
| thinking_text | `TEXT DEFAULT ''` | `text` | `text DEFAULT ''` |
| model | `TEXT DEFAULT ''` | `varchar(50)` | `text DEFAULT ''` |
| usage_input_tokens | `INTEGER DEFAULT 0` | `integer`, no default | `integer DEFAULT 0` |
| usage_output_tokens | `INTEGER DEFAULT 0` | `integer`, no default | `integer DEFAULT 0` |
| **p0_imported_at** | **不存在** | **有** | **不存在** |
| FK to conversations | **有** | **無** | **有** |
| 索引 | idx_ct_conv, ct_p1, ct_p2 | idx_ct_conversation, ct_p1_null, ct_project | idx_ct_conv, ct_p1, ct_p2 |

**決策要點**:
- `files_touched`: prod 是 `text[]`（陣列），CODE 和 dev 是 `text`。prod 的 306 筆資料需要 `array_to_string` 轉換。
- `p0_imported_at`: prod 獨有欄位，CODE 中不存在，可判定為早期殘留。
- FK: CODE 有定義（ON DELETE CASCADE），prod 缺少。

### 3.4 canvas_groups -- DEFAULT 值差異

| 欄位 | CODE | PROD | DEV |
|------|------|------|-----|
| name | `default='Group'` | `DEFAULT 'Group'` | `NOT NULL` 無 DEFAULT |
| color | `default='#3b82f6'` | `DEFAULT '#3b82f6'` | `NOT NULL` 無 DEFAULT |
| pos_x/y | `default=0` | `DEFAULT 0` | `NOT NULL` 無 DEFAULT |
| width | `default=300` | `DEFAULT 300` | `NOT NULL` 無 DEFAULT |
| height | `default=200` | `DEFAULT 200` | `NOT NULL` 無 DEFAULT |

**決策要點**: CODE 有 DEFAULT，prod 符合 CODE，dev 缺少 DEFAULT。兩邊都 0 筆資料，無資料影響。
建議: 以 CODE 為準（有 DEFAULT）。

### 3.5 canvases -- 欄位順序 + DEFAULT

| 欄位 | CODE | PROD | DEV |
|------|------|------|-----|
| owner | `default='ethan'` | `DEFAULT 'ethan'` | `NOT NULL` 無 DEFAULT |
| is_archived | `default=False` | `DEFAULT false` | `NOT NULL` 無 DEFAULT |
| slug | `unique=True, nullable=True` | 有 UNIQUE index | 有 UNIQUE constraint |

**決策要點**: CODE 有 DEFAULT，prod 符合。dev 缺少 DEFAULT 但程式端會給值。
兩邊各 2 筆 canvases 資料，需比對是否為相同白板。

### 3.6 knowledge_atoms -- 欄位順序

| 欄位 | CODE | PROD | DEV |
|------|------|------|-----|
| content_json | 在 content 後 | 在 is_deleted 後 | 在 sensitivity 前 |
| owner | `default='ethan'` | `DEFAULT 'ethan'` | `NOT NULL` |
| sensitivity | `default='internal'` | `DEFAULT 'internal'` | `NOT NULL` |
| needs_embedding | `default=True` | `DEFAULT false` | `NOT NULL` |

**決策要點**: 欄位順序不影響功能。prod 更接近 CODE。

### 3.7 worker_tasks / worker_reports -- session_id 位置

| 欄位 | CODE | PROD | DEV |
|------|------|------|-----|
| session_id | ORM 定義有 | 欄位在尾部（後加的） | 欄位在 worker_id 後 |

**決策要點**: 欄位順序不影響功能。prod 有 16 tasks + 14 reports 的實際資料。

---

## 四、5 天內活躍資料（判斷「真的有使用」）

### PROD（MCP 服務活躍）

| 表 | 5天內異動筆數 | 說明 |
|----|-------------|------|
| knowledge_atoms | 201 | 大量 MCP 寫入（核心價值） |
| atom_embeddings | 117 | 跟隨 atoms 自動產生 |
| atom_tags | 282 | 標籤關聯 |
| entry_field_values | 91 | Entry 欄位值 |
| tags | 59 | ��標籤 |
| atom_entries | 57 | 結構化記錄 |
| canvas_atoms | 31 | 白板上的原子 |
| atom_relations | 17 | 原子關係 |
| messages | 5 | 跨專案訊息 |
| nav_menu | 4 | 導覽選單 |
| canvases | 2 | 白板本身 |

### DEV（甘特圖開發測試）

| 表 | 5天內異動筆數 | 說明 |
|----|-------------|------|
| entry_field_values | 98 | 甘特圖 baseline 測試資料 |
| knowledge_atoms | 38 | 開發用測試原子 |
| atom_entries | 29 | 甘特圖 todo entry |
| canvas_atoms | 29 | 白板測試 |
| atom_relations | 15 | 測試關係 |
| tags | 11 | 測試標籤 |
| atom_tags | 12 | |
| canvas_connections | 7 | 白板連線測試 |
| atom_embeddings | 7 | |
| nav_menu | 3 | 甘特圖選單項 |

---

## 五、甘特圖依賴分析

甘特圖功能（gantt_mvp.py, gantt_routes.py）讀寫以下表：

| 表 | 操作 | 是否有 schema 差異 |
|----|------|-------------------|
| entry_schemas | 讀（查 code='todo'） | 無差異 |
| entry_schema_fields | 讀寫（查 is_frozen） | **prod 缺 is_frozen** |
| atom_entries | 讀寫 | 無差異 |
| entry_field_values | 讀寫（baseline_start/end/progress） | 無差異 |
| knowledge_atoms | 讀 | 欄位順序不同，不影響 |
| canvases | 讀 | DEFAULT 差異，不影響讀取 |
| canvas_atoms | 讀 | 無差異 |

**結論**: 甘特圖要在 prod 跑，只需要：
1. 對 prod 執行 `001_add_baseline_fields.sql`（加 is_frozen + 注入 baseline 欄位）
2. 重啟 Gunicorn 載入新程式碼

---

## 六、合併建議（待 Ethan 決策）

### 必做（甘特圖上線前提）
- [ ] 對 prod 執行 migration 001（加 is_frozen + baseline 欄位）
- [ ] 重啟 Gunicorn

### Schema 統一方向
- [ ] **conversations / conversation_turns**: 以 CODE (init_pipeline_tables.sql) 為準，重建 prod 的這兩張表
  - prod 只有 1 conversation + 306 turns，資料量小可重灌
  - `files_touched` 需 text[] -> text 轉換
  - `p0_imported_at` 欄位丟棄
- [ ] **lifecycle_transitions**: CODE 有定義（lifecycle.py），prod 有表但 0 筆。dev 缺表。
  - 建議: 保留定義，dev 補建表即可（`ensure_table()` 會自動建）
- [ ] **pipeline_runs / session_logs**: CODE 有定義，dev 有表有資料。prod 缺表。
  - 建議: 對 prod 執行 init_pipeline_tables.sql
- [ ] **canvas_groups / canvases**: dev 缺少 DEFAULT 值
  - 建議: 以 CODE 為準，dev 加回 DEFAULT（0 筆資料無影響）

### 資料方向
- [ ] 核心知識資料以 prod 為主（223 atoms vs 38，prod 是 MCP 活躍端）
- [ ] 甘特圖測試資料以 dev 為主（entry_field_values 98 筆 baseline 資料）
- [ ] system_config 的 auth_* 各自保留，不互相覆蓋
- [ ] worker_tasks/reports 以 prod 為主（16+14 筆 vs 0）

### Schema 監控工具
- [ ] 安裝 pgquarrel 或 Atlas，二擇一
  - pgquarrel: 純比對，輕量，適合 pre-commit hook
  - Atlas: schema-as-code，較重但功能完整
  - 建議先試 pgquarrel

---

## 七、風險提醒

1. prod 的 Gunicorn 還在跑舊程式碼，rsync 更新的檔案尚未生效
2. migration 001 執行後不可逆（加欄位 + 注入資料）
3. conversations/conversation_turns 重建需要先備份 prod 的 306 筆 turns
