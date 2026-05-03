# BeakBroodNest 術語表

> 本文件定義 BeakBroodNest 專案中具有特定含義的術語。
> 目的：消除 Claude（主代理與子代理）對領域術語的歧義理解，防止術語漂移導致的幻覺。
> 所有 Claude 在本專案中使用這些術語時，必須符合此處的定義。

---

## 核心概念

### 知識原子 (Atom)
BeakBroodNest 的最小知識單位。對應資料庫表 `knowledge_atoms`。
不是化學概念，不是 Atom 編輯器，不是 RSS Atom。
一個原子 = 一筆獨立的知識紀錄，可以是一段文字、一份流程、一個歸納結論、一張套表、或一個碎片想法。
原子是獨立實體，不綁定在任何白板上；白板上的卡片只是原子的「投影」。

### 原子類型 (Atom Type)
每個原子必須屬於以下六種類型之一，依思維模式分類，不是依軟體功能分類：

| 代號 | 名稱 | 用途 | 資料結構特徵 |
|------|------|------|-------------|
| A | 萬用型 | 最自由的筆記形式 | 非結構化，混合媒體 |
| B | 發散型 | 從一點出發發散，不需結論 | 樹/圖，弱連結 |
| C | 流程型 | 收斂導向結果，有步驟順序 | DAG（有向無環圖） |
| D | 歸納型 | 結論優先，有論據支撐 | 結構化文件，引用鏈 |
| E | 套表型 | 填表式，結構先於內容 | Schema + EAV |
| F | 碎片型 | 低結構，先記再說 | 自由標籤，鍵值對 |

內建導引邏輯：B(發散) -> C(收斂) -> D(歸納)。這是建議路徑，不是強制流程。

### Schema / 套表
E 類型原子使用的結構定義。對應資料庫表 `atom_schemas` + `schema_fields`。
一個 schema 定義一組欄位（名稱、型別、排序、是否必填），E 類型原子透過 `schema_id` 關聯到 schema，實際值存在 `atom_field_values`（EAV 模式）。
例：methodology schema (id=2) 定義了方法論紀錄的結構化欄位。

### 欄位值 (Field Value)
E 類型原子中，某個 schema 欄位的實際填入值。對應 `atom_field_values` 表。
採 EAV（Entity-Attribute-Value）模式：atom_id + field_id + value 三元組。

---

## 生命週期

### Lifecycle / 生命週期
原子的存活狀態。知識不是永恆的，過時的知識是噪音。

| 狀態 | 含義 | 搜尋行為 | UI 表現 |
|------|------|---------|---------|
| active | 活躍使用中 | 優先回傳 | 正常顯示 |
| aging | 逐漸老化，仍有參考價值 | 次優先 | 視覺弱化 |
| archived | 已完成或已過時，保留備查 | 可達但不主動顯示 | 隱藏 |
| terminal | 已確認無效或被取代 | 僅明確搜尋時顯示 | 標記「已過時」 |

### Vitality Score / 活力分數
浮點數 0.0~1.0，量化原子的「活躍程度」。
綜合考量：存取頻率、距最後存取的時間衰減、因果鏈上下游的活躍度。
用途：排序搜尋結果、判斷 lifecycle 狀態轉換時機。

---

## 因果鏈

### 因果鏈 (Causal Chain)
原子之間的有向語意連結。對應 `atom_relations` 表。
與 Obsidian 雙向連結的根本差異：BeakBroodNest 的連結有方向性和語意類型，不是等權無向邊。

### 關係類型 (Relation Type)
`atom_relations.relation_type` 的允許值，分為五個維度：

| 維度 | 類型 | 語意（from -> to） |
|------|------|-------------------|
| 因果 | causes | from 導致了 to |
| 因果 | enables | from 使 to 成為可能 |
| 論證 | supports | from 支持 to 的結論 |
| 論證 | contradicts | from 與 to 矛盾 |
| 結構 | contains | from 包含 to |
| 時序 | follows | to 在 from 之後發生 |
| 衍生 | derives_from | to 從 from 衍生 |
| 衍生 | supersedes | to 取代了 from |
| 衍生 | references | to 引用了 from |
| 工作流 | blocks | from 未完成前，to 無法開始 |

### Blocks / 阻塞
工作流專用關係。當原子 A blocks 原子 B，表示 A 未進入 archived 狀態前，B 處於「阻塞中」。
系統可追溯阻塞鏈的根節點，回答「卡在哪」「為什麼不開始」「缺少什麼」。

### Confidence / 信心度
`atom_relations.confidence`，浮點數 0.0~1.0。
人類建立的關係預設 1.0；AI 自動建議的關係可標註較低信心度，表示「可能相關但需人類確認」。

---

## 分類與搜尋

### Tag / 標籤
原子的分類標記。對應 `tags` 表，多對多關聯（`atom_tags`）。
支援階層式標籤（`parent_tag_id`）。
tag_type 區分三種用途：tag（分類）、group（視覺群組）、domain（知識領域）。

### Source / 來源
`knowledge_atoms.source`，記錄原子的產生者：
- human：人類手動建立
- ai：AI（主代理或子代理）建立
- import：從外部檔案匯入
- derived：由系統自動衍生（如復盤 pipeline 產出）

### Sensitivity / 敏感度
`knowledge_atoms.sensitivity`，控制原子的存取範圍：
- public：可對外分享
- internal：僅限本機使用（預設值）
- confidential：包含敏感資訊，跨機同步時需脫敏
- restricted：最高限制，不可離開本機

---

## 白板

### Canvas / 白板
原子的視覺化容器。對應 `canvases` 表。
白板不擁有原子，只擁有原子的「投影」（canvas_atoms）。同一原子可出現在多個白板上，位置不同但內容同步。

### Canvas Atom / 白板原子投影
原子在某個白板上的位置與視覺樣式。對應 `canvas_atoms` 表。
是「投影」不是「複製」-- 修改原子內容，所有白板上的投影同步更新。

### Canvas Connection / 白板連線
白板上的視覺連線。對應 `canvas_connections` 表。
可關聯底層的 `atom_relations`（語意連線），也可以是純視覺線（relation_id = NULL）。

---

## 脫敏

### Sensitive Term / 敏感詞彙
預先登記的敏感字串或正則表達式。對應 `sensitive_terms` 表。
category 分類：pii（個資）、infra（基礎設施）、business（商業機密）、credential（認證資訊）。
脫敏時，系統自動將命中的敏感詞替換為 placeholder。

### Sanitize Session / 脫敏會話
一次脫敏操作的完整記錄。對應 `sanitize_sessions` 表。
保存原文 -> 脫敏文 的映射表，支援事後還原。
用途：對外求助時去除敏感資訊，但保留還原能力。

---

## 多代理協作（Orchestrator）

### 主線 (Main Agent)
當前與用戶互動的 Claude Code session。負責任務拆解、派發、驗收。
對應 CLAUDE.md 中的「主 Claude」角色。

### 支線 / Worker
由主線透過 dispatcher 派發的子代理 `claude -p` process。
在獨立的 tmux window 中執行，有明確的任務指令和超時限制。
對應 `worker_tasks` 表。

### Dispatcher / 派發器
主線用來建立並啟動支線任務的模組。對應 `orchestrator/dispatcher.py`。
職責：寫入 worker_tasks 記錄、建立 tmux window、啟動 wrapper.sh。

### Collector / 收集器
從支線 process 的 stdout 收集執行結果的模組。對應 `orchestrator/collector.py`。
職責：讀取輸出、寫入 worker_reports 記錄。

### Relay / 中繼層
支線報告進入知識庫前的審查/匯整層。對應 `orchestrator/relay.py`。
MVP 階段為 passthrough（直接通過），未來將加入內容審查邏輯。

### Worker Report / 支線報告
支線執行完成後的輸出記錄。對應 `worker_reports` 表。
審查流程：pending -> approved/rejected -> promoted（提升為知識原子）。

### Promoted / 提升
支線報告經審查通過後，其內容被寫入 `knowledge_atoms` 成為正式原子。
`worker_reports.promoted_atom_id` 記錄對應的原子 ID。
未經提升的報告不進入知識庫。

### Session ID / 對話識別碼
同一主線對話內所有 dispatch 共用的識別碼。
用於追溯「這批支線任務是在哪次對話中派發的」。

---

## 基礎設施

### MCP Server
Model Context Protocol 伺服器，BeakBroodNest 對 AI 的存取介面。
對應 `ai_kb/mcp_server.py`。提供 note_store / note_search / note_get / note_update 等工具。
Claude Code 透過 MCP 協定直接呼叫，不需繞 Bash 或 HTTP。

### 開發目錄 vs 運行目錄
- 開發目錄：`/opt/BeakBroodNest-dev/`（有 .git，版控中）
- 運行目錄：`/opt/BeakBroodNest/`（無 .git，含 config.ini、venv、OLD）
- 開發完成後 rsync 同步到運行目錄。兩者的 config.ini 獨立，不互相覆蓋。
