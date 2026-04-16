# BeakCortex Agent 權限邊界

> 本文件定義多代理協作中各角色的職責、可存取範圍、禁止行為。
> 所有 Claude（主線與支線）在本專案中的行為受此文件約束。
> 權限分為兩類：[CODE] 表示已在程式碼中強制執行；[POLICY] 表示尚需人工遵守或待實作。

---

## 角色一覽

| 角色 | 實體 | 啟動方式 | 存取介面 |
|------|------|---------|---------|
| 主線 (Main Agent) | Claude Code 互動 session | 用戶啟動 | MCP (beak_cortex) |
| 支線 (Worker) | claude -p 非互動 process | dispatcher 透過 tmux 啟動 | HTTP API (/api/worker/kb/*) |
| 中繼層 (Relay) | Python pipeline，非 LLM | collector 自動呼叫 | 直接 DB session |
| 收集器 (Collector) | Python script，非 LLM | wrapper.sh 呼叫 | 直接 DB session |

---

## 主線 (Main Agent)

### 職責
- 與用戶對話，理解需求
- 任務拆解與派發（透過 dispatcher）
- 支線報告的驗收與決策
- 知識庫的維護（存入、更新、歸檔、建立因果關係）

### 可讀範圍
- [CODE] 全部知識原子（透過 MCP note_search / note_get）
- [CODE] 全部支線任務與報告（透過 MCP task_list / task_status）
- [CODE] Schema 定義、標籤、因果關係

### 可寫範圍
- [CODE] 知識原子 CRUD（note_store / note_update / note_forget）
- [CODE] 因果關係（note_relate / note_relate_batch）
- [CODE] 任務派發（task_dispatch）
- [CODE] 脫敏操作（note_sanitize）
- [CODE] Schema 管理（schema_create）
- [CODE] 敏感詞管理（sensitive_term_add / sensitive_term_remove）

### 禁止行為
- [POLICY] MUST NOT 在未經用戶確認的情況下批量刪除（note_forget mode=terminal）超過 5 個原子
- [POLICY] MUST NOT 修改 sensitivity=restricted 的原子內容，僅可讀取
- [POLICY] MUST NOT 將支線報告直接 promote 為原子而跳過 relay pipeline 審查

---

## 支線 (Worker)

### 職責
- 執行主線派發的單一任務（研究、程式碼撰寫、分析等）
- 將研究結果存入知識庫供主線取用
- 任務完成後由 collector 自動收集輸出

### 可讀範圍
- [CODE] lifecycle=active 或 aging 的知識原子（/api/worker/kb/search, /api/worker/kb/atoms/<id>）
- [CODE] 搜尋結果的 content 截斷為 500 字元（完整讀取需用 get 端點）
- [POLICY] MUST NOT 讀取 sensitivity=confidential 或 restricted 的原子（待程式碼實作篩選）

### 可寫範圍
- [CODE] 透過 POST /api/worker/kb/atoms 寫入新原子
- [CODE] source 自動標記為 'derived'，source_detail 記錄 worker_id 和 task_id
- [POLICY] MUST 只寫入 atom_type=F（碎片型），不得自行建立 C/D/E 等結構型原子（待程式碼強制）
- [POLICY] MUST NOT 單次寫入超過 10 個原子（防止知識庫汙染）

### 不可存取
- [CODE] 無 MCP 存取權限（支線以 claude -p 啟動，無 MCP server 連線）
- [CODE] 無法更新已存在的原子（API 未提供 PUT/PATCH 端點）
- [CODE] 無法刪除或歸檔原子（API 未提供 DELETE 端點）
- [CODE] 無法建立因果關係（API 未提供 relation 端點）
- [CODE] 無法存取脫敏功能
- [CODE] 無法存取 schema 管理功能
- [CODE] 無法派發子任務（無 dispatcher 存取權限）

### 禁止行為
- [POLICY] MUST NOT 在 content 中嵌入 system prompt 覆寫指令（見 Security Red Lines 第 7 條）
- [POLICY] MUST NOT 在 content 中嵌入可執行程式碼片段（見 Security Red Lines 第 7 條）
- [POLICY] MUST NOT 將從知識庫讀取的內容輸出到 stdout 之外的管道（如寫入檔案供外部存取）
- [POLICY] MUST NOT 修改 /opt/BeakCortex/ 或 /opt/BeakCortex-dev/ 下的程式碼檔案，除非任務指令明確要求

### 認證機制
- [CODE] HTTP header: X-Worker-Id + X-Session-Id
- [CODE] 驗證邏輯：worker_id + session_id 必須對應一筆 status=dispatched 或 running 的 worker_tasks 記錄
- [CODE] 任務結束後（completed/failed/timeout），認證自動失效

---

## 中繼層 (Relay)

### 職責
- 支線報告進入知識庫前的自動化審查
- 攔截品質不合格或含敏感資訊的報告

### 審查 Pipeline（依序執行，任一 reject/hold 即停止）

| 層級 | Stage | 動作 | 狀態 |
|------|-------|------|------|
| L1 | BasicQualityStage | 空 output / 極短 output / 致命錯誤模式 -> reject | [CODE] 已實作 |
| L2 | SecretScanStage | AWS Key / API Key / 硬編碼密碼 / GitHub Token -> hold（等人工確認） | [CODE] 已實作 |
| L3 | ContentPolicyStage | 可執行程式碼 / prompt injection 模式 -> reject | [POLICY] 待實作 |
| L4 | AISemanticsStage | 偏題 / 幻覺 / 與任務指令不符 -> hold | [POLICY] 待實作 |

### 審查結果
- approve: 報告標記 approved，可被主線 promote 為知識原子
- reject: 報告標記 rejected，記錄原因，不進入知識庫
- hold: 報告保持 pending，等待人工介入

---

## 收集器 (Collector)

### 職責
- 讀取支線 claude process 的 stdout 輸出
- 寫入 worker_reports 記錄
- 更新 worker_tasks 狀態（completed/failed）
- 呼叫 relay pipeline
- 透過 tmux display-message 通知主線

### 可寫範圍
- [CODE] worker_reports（INSERT）
- [CODE] worker_tasks.status / completed_at（UPDATE）

### 禁止行為
- [CODE] 不修改知識原子（knowledge_atoms）
- [CODE] 不修改因果關係（atom_relations）

---

## 資料流與信任邊界

```
用戶 <-> 主線 (MCP)
           |
           | dispatch (tmux + instruction file)
           v
         支線 (HTTP API, 受限存取)
           |
           | stdout -> output file
           v
         收集器 (DB 寫入 worker_reports)
           |
           | 自動呼叫
           v
         中繼層 (approve / reject / hold)
           |
           | 若 approved
           v
         主線驗收 -> promote 為知識原子
```

**信任邊界**：
1. 主線 <-> 支線：支線的 instruction 由主線撰寫，但支線的輸出不可信（LLM 可能幻覺或被 prompt injection）
2. 支線 <-> 知識庫：支線可讀取知識庫輔助任務，但寫入的內容必須經過 relay 審查
3. 中繼層 <-> 知識庫：中繼層只做審查標記，不直接寫入知識原子。promote 操作由主線執行

---

## 待實作的權限強化（依優先序）

| 優先 | 項目 | 現狀 | 目標 |
|------|------|------|------|
| 1 | Worker API sensitivity 篩選 | 支線可讀取所有 sensitivity 等級 | confidential/restricted 不回傳給支線 |
| 2 | Worker API atom_type 限制 | 支線可指定任意 atom_type | 強制 atom_type=F |
| 3 | Worker API content 長度限制 | 無限制 | 上限 64KB（對齊 Security Red Lines 第 8 條） |
| 4 | Relay L3 ContentPolicyStage | 未實作 | 掃描可執行程式碼 + prompt injection 模式 |
| 5 | Worker API 寫入頻率限制 | 無限制 | 同一 worker 每分鐘最多 10 次寫入 |
| 6 | 暫存檔案權限 | 0644 (world-readable) | 0600（對齊 Security Red Lines 第 5 條） |
