# BeakCortex -- 知識白板與 AI 共用知識庫

## Security Red Lines

本段落定義不可違反的安全底線。所有 Claude（主代理與子代理）在本專案的任何操作皆受此約束。

### 通用紅線

1. **MUST NOT** 硬編碼任何密碼、API Key、Token。
   -- 認證資訊洩漏是不可逆的；一旦進入 git 歷史，即使刪除也可被還原。

2. **MUST** 對所有 SQL 使用參數化查詢（SQLAlchemy ORM 或 `sa.text()` 搭配 `:param` 綁定）。**MUST NOT** 使用 f-string 或字串拼接組合 SQL 的 WHERE / ORDER BY 子句。
   -- 本專案已存在 f-string 拼接 SQL 的歷史程式碼（knowledge.py），新程式碼絕對禁止重蹈覆轍，舊程式碼應在觸及時修正。

3. **MUST NOT** 使用 `eval()`、`exec()`、`compile()` 執行動態程式碼。
   -- 知識庫內容來自 LLM 和人類輸入，任何一方都可能注入可執行片段。

4. **MUST** 對所有外部輸入進行 schema 驗證後才進入業務邏輯。
   -- 「外部輸入」定義：HTTP request body、MCP tool 參數、匯入的檔案內容、子代理回傳的結果。這些全部是不可信來源。

5. **MUST** 將暫存檔案權限設為 0600（僅擁有者可讀寫）。**MUST NOT** 使用 `delete=False` 的 NamedTemporaryFile 而不清理。
   -- 暫存檔可能包含知識庫內容或子代理指令，預設的 world-readable 權限會暴露敏感資訊。

### BeakCortex 特有紅線

6. **MUST** 將 MCP tool handler 的所有參數視為不可信輸入。
   -- MCP 參數由 LLM 產生，等同於外部輸入。即使呼叫者是主 Claude，參數值仍可能受 prompt injection 影響。

7. **MUST NOT** 允許子代理寫入的 content 欄位包含可執行程式碼片段（如 `<script>`、`__import__`、`subprocess.call` 等模式）。**MUST NOT** 允許 content 包含 system prompt 覆寫指令（如 `you are now`、`ignore previous instructions`、`system:` 等模式）。
   -- 知識庫原子會被注入未來 session 的 context，汙染的原子等於持久化的 prompt injection。

8. **MUST** 在 `note_store` / `note_update` 路徑上驗證 content 長度上限（建議 64KB）與 tags 數量上限（建議 20 個）。
   -- 無限制的寫入可被用於資源耗盡攻擊，也會汙染搜尋結果品質。

9. **MUST** 在 dispatcher 傳遞給子代理的指令中，明確聲明該子代理的可讀/可寫範圍。子代理 **MUST NOT** 被授予超出其任務所需的資料庫寫入權限。
   -- 最小權限原則。子代理能寫入知識庫 = 給 LLM 一個持久化的寫入通道，必須限縮。

10. **MUST** 對從外部匯入的對話紀錄（復盤 pipeline 的輸入源）執行 `note_sanitize` 淨化後才進入分析流程。
    -- 對話紀錄可能包含用戶的敏感資訊或惡意構造的 prompt injection payload。

## 開發目錄 vs 運行目錄（強制理解，每次對話必讀）

本專案有兩個目錄，角色完全不同，混淆將導致版控失效與程式碼遺失：

| | 開發主體 (source) | 工具主體 (runtime) |
|---|---|---|
| **路徑** | `/opt/BeakCortex-dev/` | `/opt/BeakCortex/` |
| **性質** | 版控倉庫（git + Forgejo） | 部署產物（無 .git） |
| **可否直接修改程式碼** | 唯一合法的修改場所 | **MUST NOT** 直接修改 |
| **更新方式** | 開發者直接編輯 | 僅透過 rsync 從 dev 部署 |
| **額外內容** | -- | config.ini、venv、OLD、temp |

**為什麼容易搞混**：MCP server、crontab、venv 都指向 `/opt/BeakCortex/`，每次對話都會大量接觸這個路徑。但它是「被使用的工具」，不是「被開發的原始碼」。類比：你不會去改 `/usr/lib/python3/` 裡的 .py，你改完 source 再部署。

**MUST NOT** 對 `/opt/BeakCortex/` 下的 .py / .js / .html / .sh / .css 檔案執行 Edit / Write 操作。
-- 直接修改運行目錄的程式碼不會進入版控，下次 rsync 部署時會被開發目錄的舊版覆蓋，等於白做。已多次發生此問題。

**例外**：`/opt/BeakCortex/config.ini` 可直接修改（不入版控，rsync 已排除）。

## 專案概述
- 開發目錄: /opt/BeakCortex-dev/（版控，git + Forgejo） -- **改程式改這裡**
- 運行目錄: /opt/BeakCortex/（無 .git，部署產物） -- **禁止直接改程式碼**
- 技術棧: Python Flask + PostgreSQL + SQLAlchemy + MCP SDK
- Port: 5170 (http://192.168.0.16:5170)
- DB: beak_cortex (user: beak_cortex, pw: postgres123)
- MCP 設定: /opt/.mcp.json（指向運行目錄，這是正常的，不代表應該去那裡改程式）
- 規劃文件: docs/VISION.md
- 舊 MVP 參考: /opt/BeakCortex/OLD/（僅存於運行目錄，不入版控）

## 每次對話必做
1. 呼叫 `note_inbox` 檢查未讀訊息，有未讀則摘要告知用戶，並標記已讀
2. 呼叫 `note_overview` 取得知識庫概覽（原子數、標籤、最近更新、阻塞項目）
3. 呼叫 `note_search` 搜尋 tag=「待辦」+ tag=「BeakCortex」取得當前專案待辦
4. 根據知識庫回傳的內容理解專案狀態，不要重新掃描目錄結構
5. 若用戶指定任務，用 `note_get` 讀取對應原子的完整內容再開工
6. 開工前搜尋方法論紀錄：`note_search(schema_id=2, query="任務相關關鍵字")`，若有命中則閱讀 improved_approach 和 applicable_when 判斷是否適用
7. 完成任務後用 `note_update` 更新對應原子狀態，或用 `note_forget` 歸檔已完成項目

## 知識庫使用原則
- 新的設計決策、待辦、里程碑 -> `note_store` 存入知識庫
- 任務完成 -> `note_update` 更新內容，或 `note_forget` mode=archive 歸檔
- 建立因果關係 -> `note_relate`（blocks/follows/supports 等）
- 不要重複儲存已存在的知識，先 `note_search` 確認

## 目錄結構
```
core/               共用資料層（框架無關 SQLAlchemy）
  db.py             engine + session
  models.py         10 張表 ORM (知識原子)
  relations.py      因果鍊操作 + 阻塞追溯
human_ui/           人類介面 (Flask)
  app.py            API routes
ai_kb/              AI 知識庫介面
  mcp_server.py     MCP Server (10 知識工具 + 4 orchestrator 工具)
orchestrator/       多 Agent 協作框架
  models.py         worker_tasks + worker_reports ORM
  dispatcher.py     任務派發 (tmux window + claude -p)
  wrapper.sh        支線 claude process 包裝器
  collector.py      結果收集 (output -> worker_reports)
  relay.py          中間層 (MVP: passthrough，未來: 審查/匯整)
docs/               規劃文件
```

## 啟動與部署流程

### 啟動服務（在運行目錄執行，不需要 cd 過去）
```bash
/opt/BeakCortex/venv/bin/python /opt/BeakCortex/human_ui/app.py --serve
/opt/BeakCortex/venv/bin/python /opt/BeakCortex/human_ui/app.py --init-db --seed   # 首次初始化
```
注意：啟動服務不代表要去運行目錄改程式。服務出問題 -> 回 dev 改 -> 部署 -> 重啟。

### 部署流程（dev -> 運行目錄，單向）
開發在 /opt/BeakCortex-dev/ 完成後，將程式碼同步到 /opt/BeakCortex/：
```bash
rsync -av --exclude='.git' --exclude='config.ini' --exclude='venv' --exclude='OLD' --exclude='temp' /opt/BeakCortex-dev/ /opt/BeakCortex/
```
流向永遠是 **dev -> runtime**，反向操作僅限用戶明確要求的版本回退。
