# BeakBroodNest -- 知識白板與 AI 共用知識庫

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

### BeakBroodNest 特有紅線

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
- 路徑: `/opt/BeakBroodNest/`（單一目錄，含 .git 版控倉庫；2026-04-26 P1 重組合併原 dev/runtime 雙目錄）
- 技術棧: Python Flask + PostgreSQL + SQLAlchemy + MCP SDK
- Port: 5170（對外經 nginx → gunicorn 127.0.0.1:5171，由 systemd 管理）
- DB: `beak_broodnest`（user: `beak_broodnest`, pw: `postgres123`）
- MCP 設定: `/opt/.mcp.json`（故意置於父目錄讓所有 /opt/* 子專案向上搜尋共用 beak_broodnest；`/mcp` 命令 UI 會把路徑誤標為 `/opt/BeakBroodNest/.mcp.json`，那是 UI 拼接 project 路徑的顯示行為，實檔在父目錄）
- 規劃文件: `docs/VISION.md`
- 舊 MVP 參考: `OLD/`（不入版控）
- 對外發佈: 直接 `git push github master`（本專案已整理為適合公開，認證走 ssh：`ethan-beakmask/BeakBroodNest`）

## 修改規範
- 直接於 `/opt/BeakBroodNest/` 編輯任何檔案，工作區即版控倉庫
- `config.ini` 不入版控（已在 .gitignore 排除）
- 程式碼變更後若影響 gunicorn 行為，須 `sudo systemctl restart beakbroodnest.service`

## 文件編輯鍵盤規格（強制遵循）
- 規格文件：`docs/KEYBOARD_SPEC.md`
- 動到任何鍵盤行為（Tiptap extension、entry NodeView、modal、toolbar）前，**先讀規格**確認與既有規則不衝突；改完規格與實作一起 commit
- 設計原則：白板 = 滑鼠主場；文件 = 鍵盤主場。所有常用編輯操作都要有鍵盤路徑
- `Mod+Enter` 唯一語意 = 強制在當前最外層 block 後插空段並進入（不論一般段落 / list / table cell / entry NodeSelection 都一致）
- `;;物件` 是 atomic block，刪除只能透過 `[x]`，鍵盤的 Backspace/Delete 在邊界要吃掉

## 每次對話必做
1. 呼叫 `note_inbox` 檢查未讀訊息，有未讀則摘要告知用戶，並標記已讀
2. 呼叫 `note_overview` 取得知識庫概覽（原子數、標籤、最近更新、阻塞項目）
3. 呼叫 `note_search` 搜尋 tag=「待辦」+ tag=「BeakBroodNest」取得當前專案待辦
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
  models.py         worker_tasks + worker_reports + worker_sessions + worker_inbox ORM
  dispatcher.py     任務派發 (一次性 dispatch_task / 多輪 spawn_session+talk_session)
  wrapper.sh        一次性派遣 claude process 包裝器（dispatch_task 用）
  cc_runner.py      多輪互動 claude -p 同步呼叫（spawn/talk 用）
  collector.py      一次性派遣結果收集 (output -> worker_reports)
  notify.py         主 cc 通知（tmux display-message + 旗標檔 + stderr）
  relay.py          中間層 (MVP: passthrough，未來: 審查/匯整)
  cli/              命令列工具（cc-spawn / cc-talk / cc-inbox-{put,get} / cc-list）
  hooks/            UserPromptSubmit hook（aside_router.py 等）
  workspaces/       支線 cwd（每支線一個子目錄，不入版控）
  windows/          Windows 端 Go 程式 + relay_receiver.py（舊）
    relay/          BeakBroodNest.exe 原始碼（Go，跑在 192.168.0.10:5200）
                    對運行中的 cc 對話 paste 訊息=自我注入通道，見 #4159
  notify_windows.py Ubuntu 端呼叫 Windows Relay 的 Python wrapper
docs/               規劃文件
```

## Orchestrator: cc-to-cc 多輪互動

兩條獨立路徑並存：

| 場景 | 機制 | 入口 |
|---|---|---|
| 一次性派遣（claude -p 當 agent） | tmux window + wrapper.sh + collector | `dispatcher.dispatch_task()` |
| 多輪互動會話（場景 1） | `claude -p --resume` + worker_sessions | `dispatcher.spawn_session()` / `talk_session()` 或 CLI |
| 主線純淨 aside（場景 2） | UserPromptSubmit hook 攔 `aside:` 前綴 | `.claude/settings.json` → `orchestrator/hooks/aside_router.py` |

### 設計原則：儲存分流，查詢統一
- **儲存分流**：一次性派遣結果存 `worker_reports`（結案報告，看完就好），多輪會話訊息存 `worker_inbox`（對話訊息，需回應）。語意不同，**不合併儲存層**（避免破壞 FK 純度、避免硬塞 task_id 進 inbox 或為一次性任務假造 session）。
- **查詢統一**：兩表的 `read_at IS NULL` 透過 PostgreSQL view `pending_outputs` 統一查詢（schema：source/row_id/session_name/task_id/kind/content/created_at/read_at）。主線一個入口看全部未讀。
- **通知一致**：`worker_inbox` 寫入（cc-inbox-put）與 `worker_reports` 寫入（collector）皆走 `notify.notify_pending()`，前綴 `[CC-Orch]`、未讀數來自 view。

### CLI（路徑：`/opt/BeakBroodNest/orchestrator/cli/`）
```bash
cc-spawn --name dev1 --role "後端開發" --message "請寫個 fizzbuzz.py"
cc-talk  --session dev1 --message "改用 list comprehension"
cc-inbox-put --session dev1 --kind question --content "要不要支援負數？"   # 支線寫
cc-inbox-get --unread-only --mark-read                                    # 主線讀（僅 session）
cc-pending [--source task|session] [--mark-read]                          # 主線讀（task + session 統一）
cc-list
```

### Schema 重點
- `worker_sessions`：`name` UNIQUE、`purpose` 預設 `worker`；hook 自建支線 purpose 為 `hook_aside` / `hook_summary` / ...，name 用雙底線包圍（如 `__aside_default__`）
- `worker_inbox`：`kind ∈ {question, notice, result}`，FK 到 `worker_sessions.name`
- `cc-spawn` 拒絕雙底線開頭的 name（防撞名）；hook 內部呼叫帶 `allow_underscore=True` 旁路

### 場景 2 使用方式
在 `/opt/BeakBroodNest/` 內輸入 `aside: <你的臨時問題>` 即被攔截，由 hook_aside 長期支線處理，主 cc 完全不見此 prompt。

### 驗收測試
```bash
# 場景 1 (e2e)
cc-spawn --name e2e --role 測試 --message "1+1?" --model haiku --no-inbox-protocol
cc-talk  --session e2e --message "上題你回答是 2，那 2+2 呢?只回數字"   # 應答 4
cc-inbox-put --session e2e --kind notice --content "test"
cc-inbox-get --unread-only --mark-read
# 場景 2: 在新 cc 開 /opt/BeakBroodNest 並輸入 'aside: 列出檔案'，主 cc 不會看到此 prompt
```

## 啟動與服務管理

### 正式服務（systemd 管理）
```bash
sudo systemctl {start|stop|restart|status} beakbroodnest.service
```
ExecStart: `gunicorn --bind 127.0.0.1:5171 ... human_ui.app:app`，對外經 nginx 接到 192.168.0.16:5170。

### 首次初始化資料庫
```bash
/opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/human_ui/app.py --init-db --seed
```

### 開發 Flask dev server（hot reload，5175）
```bash
/opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/human_ui/app.py --serve --port 5175 --host 192.168.0.16
```
與正式 gunicorn (5171) 並存，皆連同一個 `beak_broodnest` DB。

### 推送到 GitHub
本專案已整理為可直接公開，所有 remote 一視同仁直接 push：
```bash
git push origin master   # 內部 forgejo
git push github master   # 公開 GitHub（ssh 認證）
```

`/upcom` 等自動 push 流程：對 `github` 與 `origin` 都直接 push 即可，不需要特殊跳過。

**歷史保留**（已不再強制使用，但檔案留著以備未來情境變化）：
- `scripts/push_github.sh` -- 早期過濾內部檔再 force push 的腳本（含 EXCLUDE_FILES）
- `scripts/pre-push.sample` -- 早期 pre-push hook（攔截裸 push 到 github）

> 注意：本放行**只適用本專案**。其他 /opt/* 專案（如 BeakPlatform）尚未整理為可公開狀態，全域規範仍要求過濾後才能對外推送。
