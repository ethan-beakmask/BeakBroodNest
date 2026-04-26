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

## 專案概述
- 路徑: `/opt/BeakCortex/`（單一目錄，含 .git 版控倉庫；2026-04-26 P1 重組合併原 dev/runtime 雙目錄）
- 技術棧: Python Flask + PostgreSQL + SQLAlchemy + MCP SDK
- Port: 5170（對外經 nginx → gunicorn 127.0.0.1:5171，由 systemd 管理）
- DB: `beak_cortex`（user: `beak_cortex`, pw: `postgres123`）
- MCP 設定: `/opt/.mcp.json`（故意置於父目錄讓所有 /opt/* 子專案向上搜尋共用 beak_cortex；`/mcp` 命令 UI 會把路徑誤標為 `/opt/BeakCortex/.mcp.json`，那是 UI 拼接 project 路徑的顯示行為，實檔在父目錄）
- 規劃文件: `docs/VISION.md`
- 舊 MVP 參考: `OLD/`（不入版控）
- 對外發佈: `scripts/push_github.sh`（過濾內部檔案後 force push 到 GitHub `ethan-beakmask/BeakCortex`）

## 修改規範
- 直接於 `/opt/BeakCortex/` 編輯任何檔案，工作區即版控倉庫
- `config.ini` 不入版控（已在 .gitignore 排除）
- 程式碼變更後若影響 gunicorn 行為，須 `sudo systemctl restart beakcortex.service`

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

## 啟動與服務管理

### 正式服務（systemd 管理）
```bash
sudo systemctl {start|stop|restart|status} beakcortex.service
```
ExecStart: `gunicorn --bind 127.0.0.1:5171 ... human_ui.app:app`，對外經 nginx 接到 192.168.0.16:5170。

### 首次初始化資料庫
```bash
/opt/BeakCortex/venv/bin/python /opt/BeakCortex/human_ui/app.py --init-db --seed
```

### 開發 Flask dev server（hot reload，5175）
```bash
/opt/BeakCortex/venv/bin/python /opt/BeakCortex/human_ui/app.py --serve --port 5175 --host 192.168.0.16
```
與正式 gunicorn (5171) 並存，皆連同一個 `beak_cortex` DB。

### 推送到 GitHub（過濾內部檔）
```bash
bash /opt/BeakCortex/scripts/push_github.sh
```
排除 `CLAUDE.md`、`scripts/push_github.sh`、`scripts/schedule.json` 後 force push 到 `github` remote。
