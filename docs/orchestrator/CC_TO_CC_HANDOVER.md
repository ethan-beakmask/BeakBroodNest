# CC-to-CC 雙向互動 MVP 移交說明（存檔）

> **本檔為歷史 reference。**
> 來源：`/opt/backup/mvp/HANDOVER.md`，由 `project:backup` 在 2026-05-02 移交給 BeakBroodNest orchestrator。
> 整合工作於同日完成（首段 commit 為 `feat(orchestrator): integrate MVP cc-to-cc bidirectional bridge`），MVP 目錄已退場。
> 保留原因：第六段（踩雷紀錄）、第二段（兩個情境是舉例不是寫死類型）對未來新增 hook（summary: / translate: / lookup: 等前綴）或除錯 cc-to-cc 通訊仍有參考價值。
> 文中提到 `/opt/backup/mvp/...` 的檔案皆已不存在；對映到 BeakBroodNest 後的位置請見 `CLAUDE.md` orchestrator 章節。

---

# 原文

**收件人**：在 `/opt/BeakBroodNest/` 工作的 Claude Code
**交付日期**：2026-05-02
**MVP 路徑**：`/opt/backup/mvp/`（已退場）
**目標路徑**：`/opt/BeakBroodNest/orchestrator/`（已合併）

---

## 一、為何讀這份文件

使用者（Ethan）在 `/opt/backup/mvp/` 完成了一個 MVP，驗證**兩個 Claude Code 互動雙向對話**的可行性。MVP 已 e2e 驗收通過，現在要把功能合併進你既有的 `orchestrator/` 模組。

不要重寫 -- 你既有的 dispatcher/collector/monitor/wrapper 框架是好的，MVP 只是補上你目前缺的兩塊：
1. **多輪互動對話**（你目前是 `claude -p` 一次性 print mode）
2. **支線→主反向通訊**（你目前 collector 只做完成通知，不做任意訊息回傳）

加上一個全新概念：
3. **場景 2 的主線純淨機制**（UserPromptSubmit hook 攔截 + 派 aside 支線）

---

## 二、解決的兩個情境（只是舉例 -- 設計需保留擴展空間）

> 用戶 Ethan 明確說明：「場景只是舉例」。設計時不要把這兩種情境寫死成兩種特殊類型，要留通用機制（見後面 `purpose` 欄位設計）。

### 場景 1：主 CC 呼叫支線 CC 進行需要互動的任務
多個支線開發同一系統的不同功能，主 CC 負責檢查整合、回覆支線提出的異議。

**關鍵需求**：
- 主→支：可多輪派指令（不只一次性）
- 支→主：支線可主動「提異議」、「報進度」、「報完成」
- session 持久化：每個支線都是長期對話，記得自己做過什麼

### 場景 2：主線維持超長對話的純淨
用戶臨時插入無關話題時，自動轉給支線處理，**主 CC 完全看不到**那個 prompt（避免幻覺）。

**關鍵需求**：
- UserPromptSubmit hook 偵測 `aside:` 前綴
- 把 prompt 交給 aside 支線處理
- 把支線回應顯示給用戶，但**不放進主 CC 的 model context**

### 可能的延伸情境（設計時要考慮）
- `summary:` -- 用支線摘要當前對話到知識庫
- `translate:` -- 翻譯某段文字
- `lookup:` -- 查文件 / 知識庫
- 任何「截走 prompt 給專門支線處理」的 hook
- 每種都該有自己的長期支線（用 `purpose='hook_<name>'` 區分）

---

## 三、MVP 架構

```
/opt/backup/mvp/
├── lib/
│   ├── db.py               SQLite 連線 + schema
│   ├── cc.py               claude -p subprocess 包裝
│   └── notify.py           tmux display-message + 旗標檔
├── bin/
│   ├── cc-spawn            建立支線（首輪訊息）
│   ├── cc-talk             對既有支線送訊息（--resume）
│   ├── cc-inbox-put        支線寫入訊息給主
│   ├── cc-inbox-get        主讀取支線訊息
│   └── cc-list             列出所有 sessions
├── hooks/
│   └── aside_router.py     UserPromptSubmit hook（場景 2）
├── state/
│   ├── cc_mvp.db           SQLite（sessions + inbox 兩張表）
│   └── notify.flag         未讀通知旗標
└── workspaces/
    ├── dev1/               每支線獨立 cwd，claude -p 從這裡跑
    ├── dev2/
    └── aside1/

/opt/backup/.claude/settings.json   全域 hook 設定（綁定 UserPromptSubmit）
```

### SQLite Schema（MVP 原版）
```sql
CREATE TABLE sessions (
    name TEXT PRIMARY KEY,           -- 友善名稱，例如 dev1、aside1
    role TEXT NOT NULL,              -- 角色描述（給 system prompt）
    working_dir TEXT NOT NULL,       -- workspaces/<name>/
    model TEXT NOT NULL,             -- claude model（預設 sonnet）
    claude_session_id TEXT,          -- claude -p 自動生成的 UUID（用於 --resume）
    main_tmux_pane TEXT,             -- 主 cc 的 tmux pane id（通知用）
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    last_activity_at TEXT
);

CREATE TABLE inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_name TEXT NOT NULL,
    kind TEXT NOT NULL,              -- question / notice / result
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT
);
```

### Schema 遷移時的必要修正：加 `purpose` 欄位

MVP 把 aside hook 的長期支線寫死叫 `aside1`，這在實務上會撞名（用戶可能也想用 aside1 當工人支線名）。整合到 BeakBroodNest 時**務必**加 `purpose` 欄位區隔用途：

```sql
ALTER TABLE sessions ADD COLUMN purpose TEXT NOT NULL DEFAULT 'worker';
-- 'worker'        -- 用戶手動 spawn 的工人支線（場景 1 那類）
-- 'hook_aside'    -- aside hook 專屬長期支線
-- 'hook_summary'  -- 未來可能有的 summary hook 支線
-- 'hook_<其他>'   -- 任何 prompt-prefix hook 都自備一條
```

**設計理由（重要）**：用戶提出的兩個情境只是**舉例**。實際上 UserPromptSubmit hook 可以有多種前綴：`aside:`、`summary:`、`translate:`、`lookup:` ...，每種都該有自己的長期支線。寫死 name 撐不住擴展。

**hook 查找邏輯改寫為依 purpose**：
```python
SELECT name FROM sessions
WHERE purpose = 'hook_aside' AND status = 'active'
ORDER BY created_at ASC LIMIT 1
```
不再依 name 寫死。即使日後同 hook 多開幾條長期支線（例如「不同情境的 aside」），也能依 purpose 篩。

**命名規範**：
- hook 自建的支線 name 用**雙底線包圍**（如 `__aside_default__`）作保留識別字
- cc-spawn / spawn_session 應拒絕雙底線開頭的 name（防用戶誤建撞名）
- cc-spawn 加 `--purpose` 旗標，預設 `worker`

### 核心機制

**多輪持久化**：靠 `claude -p --resume <claude_session_id>`。第一輪存 session_id，後續輪都帶這個 id 接續。

**支線→主訊息**：支線在 system prompt 內被告知可呼叫 `cc-inbox-put`，透過 Bash 工具執行 CLI 寫進 inbox 表。寫入瞬間還會做：
- 寫 `state/notify.flag`（含未讀數）
- `tmux display-message` 對主 pane 閃通知
- stderr 印醒目訊息

**場景 2 的 hook**：
- 用戶輸入若以 `aside:` 開頭 → hook 截下 → 跑 cc-spawn（首次）/ cc-talk（後續）給 aside1 支線 → 拿回應
- hook 用 `{"decision":"block","reason":"<回應>"}` 回應
- 主 CC 完全收不到這個 prompt，model context 純淨

---

## 四、與你既有 orchestrator 的差異對照

| 元件 | 你既有 | MVP | 整合策略 |
|---|---|---|---|
| `dispatcher.py` | 派支線 via tmux + claude -p（一次性） | 拆成 `cc-spawn`（首次）+ `cc-talk`（接續） | 重構：dispatcher 加 `spawn(...)` 與 `talk(session_id, msg)` 兩個方法 |
| `wrapper.sh` | 跑 claude -p（`--no-session-persistence`） | 跑 claude -p `--resume`（要 session 持久化） | **改寫**：移除 `--no-session-persistence`，加 `--resume` 支援 |
| `collector.py` | 收結果 + tmux display-message 通知主 | inbox 表插入 + 同樣的通知 | 擴充：collector 改用 inbox 表，所有訊息都過去；把目前的「完成通知」當成 `kind=result` 的 inbox 項 |
| `monitor.py` | 監控逾時、tmux 消失 | 沒做 | 保留你的，套用到新版 sessions 表 |
| `models.py` | `WorkerTask`（一次性任務） | `Session` + `Inbox`（長期會話 + 雙向佇列） | **新增** `WorkerSession`（長期）和 `Inbox`（訊息）；保留 `WorkerTask` 給仍需一次性派遣的場景 |
| KB preamble | dispatcher 有注入 | MVP 沒做（用 `--no-inbox-protocol` 跳過） | 整合後預設注入 KB preamble + inbox 協定（兩段都加） |
| Heartbeat | 有 | 沒做 | 整合後加進 wrapper |
| SQLite vs PostgreSQL | PostgreSQL（SQLAlchemy） | SQLite（直接寫 SQL） | **轉 PostgreSQL** 配合你的 schema |
| Hook（場景 2） | 沒這概念 | aside_router.py | **新增**到你的 `.claude/settings.json` 或專案級 |

---

## 五、安裝/整合步驟（建議順序）

### 階段 A：先把 MVP 跑起來（驗收 MVP）
```bash
cd /opt/backup/mvp
./bin/cc-list                                    # 應顯示 dev1/dev2/aside1 三個支線
./bin/cc-inbox-get                               # 應顯示既有對話歷史
sqlite3 state/cc_mvp.db ".schema"                # 確認 schema
```

### 階段 B：把概念對映到 BeakBroodNest schema
1. 在 `orchestrator/models.py` 加 `WorkerSession`（對應 MVP 的 sessions 表）
   - **必含 `purpose` 欄位**（見第三段「Schema 遷移時的必要修正」）
   - 預設 `worker`，hook 用 `hook_aside` / `hook_summary` / ...
2. 在 `orchestrator/models.py` 加 `WorkerInbox`（對應 MVP 的 inbox 表）
3. 用 Alembic 或你既有的 migration 機制建表
4. **不要刪 `WorkerTask`** -- 一次性任務仍有用

### 階段 C：擴充 dispatcher / wrapper
1. 改 `wrapper.sh`：移除 `--no-session-persistence`，加 `--resume` 支援（讀 env 或參數）
2. 改 `dispatcher.py`：
   - 新增 `spawn_session(name, role, model, first_msg)` 方法（對映 cc-spawn）
   - 新增 `talk_session(session_name, msg)` 方法（對映 cc-talk）
   - 既有的 `dispatch_task(...)` 保留給一次性任務

### 階段 D：擴充 collector
- 改成「所有支線輸出都寫 WorkerInbox」
- 既有的「完成 = 寫 worker_tasks.result」改成「完成 = 寫 WorkerInbox kind=result」
- KB preamble 多注入一段「你可以呼叫 cc-inbox-put 提問題」

### 階段 E：實作場景 2 的 hook
1. 把 `/opt/backup/mvp/hooks/aside_router.py` 複製到 `/opt/BeakBroodNest/orchestrator/hooks/`
2. 改裡面的 ROOT 路徑 + DB 連線（從 SQLite 改 PostgreSQL）
3. **重要**：MVP 寫死 `ASIDE_NAME='aside1'`，整合時改成查 purpose：
   ```python
   # 不要再寫死 name，改查 purpose
   ASIDE_PURPOSE = 'hook_aside'
   ASIDE_NAME = '__aside_default__'  # 雙底線保留字，第一次建立用
   # 找 session: WHERE purpose='hook_aside' AND status='active' LIMIT 1
   ```
4. 在 `/opt/BeakBroodNest/.claude/settings.json` 加 UserPromptSubmit hook 設定
5. **重要**：BeakBroodNest 既有 `.claude/settings.json` 可能有其他 hooks，要 merge 不要覆蓋
6. 設計上保留擴展空間：未來可能加 `summary:`、`translate:`、`lookup:` 等其他前綴 hook，每個各自一條 hook session（purpose 不同）

### 階段 F：驗收測試（強制）
1. 場景 1：`spawn_session('dev1', '後端', 'sonnet', '寫個 fizzbuzz.py')` → dev1 提異議 → 主回 → dev1 完成
2. 場景 2：在 `/opt/BeakBroodNest/` 開新 cc，輸入 `aside: 列出檔案` → hook 攔截 → 確認主 cc 不知道
3. 主線純淨度：問主 cc「你被問過什麼 aside？」應答「沒被問過」

---

## 六、實作時的踩雷紀錄

### A. `claude -p --resume` 必須帶對 session UUID
- spawn 時從 `--output-format json` 的 `session_id` 欄位抓
- 接續時 `--resume <uuid>` 一定要帶

### B. claude 偵測非 tty 會自動降級成 print 模式
- 用 subprocess 跑 claude -p 不會啟動 TUI，這是預期的
- 真正的「互動 cc」TUI 不能這樣做（要用 tmux send-keys + capture-pane）

### C. UserPromptSubmit hook 阻擋語意
- `{"decision":"block","reason":"..."}` -- reason 顯示給用戶，**不進 model context**
- cc 的 TUI 會顯示 `Original prompt: ...` 給用戶看（讓用戶知道哪個 prompt 被擋）-- 這是 TUI 行為，model 仍看不到
- exit code 2 + stderr 也能 block，但會以紅色錯誤樣式顯示，不適合「成功的 aside 回覆」

### D. Hook 內呼叫 cc-spawn / cc-talk 會遞迴觸發 hook
- 子 cc 的工作目錄在 `workspaces/<name>/`，cc 仍會往上找 `.claude/settings.json`
- 但子 cc 收到的 prompt 沒有 `aside:` 前綴 → hook passthrough，無問題
- 額外開銷：每個子 cc 的每一輪多 ~50ms 的 hook 啟動

### E. tmux display-message 預設只閃 750ms
- 用戶要看清楚需 `tmux set -g display-time 5000`
- 或改用 status line 持續顯示未讀數

### F. cc-spawn 的 system prompt 模板會教支線使用 cc-inbox-put
- 對 aside 用途不要這樣做（沒人收，會白做工）
- 故 cc-spawn 加了 `--no-inbox-protocol` 旗標跳過

### G. workspaces 目錄結構與 ~/.claude/projects/ 對應
- 每個支線的 cwd 是 `workspaces/<name>/`
- 對應的 cc session 記錄在 `~/.claude/projects/-opt-backup-mvp-workspaces-<name>/`
- 多支線並存不會撞，因為 cwd 不同

### H. Hook session 與工人 session 的 namespace 衝突
- MVP 寫死 `ASIDE_NAME='aside1'`，若用戶手動 `cc-spawn --name aside1` 就會撞名
- 整合時改用 `purpose` 欄位區分（見第三段「Schema 遷移時的必要修正」）
- 命名規範：hook 自建支線用 `__name__`（雙底線包圍），cc-spawn 拒絕雙底線開頭
- 用戶提出的「場景 1 工人 / 場景 2 aside」只是舉例，未來可能還有 summary、translate、lookup 等 hook，每種都該有自己的 purpose

---

## 七、未做的後續工作（依優先級）

| 項目 | 為何重要 | 預估工作量 |
|---|---|---|
| **Stop hook 自動注入未讀 inbox** | 主 cc 不必手動 cc-inbox-get；turn 結束自動帶上待處理異議 | 0.5 天 |
| **Inbox 整合進 BeakBroodNest `note_inbox`** | 既有跨專案訊息基建已存在，schema 對齊即可 | 0.5 天 |
| **支線並發測試 + 衝突仲裁** | 場景 1 真實情境（多支線開發同一系統） | 1 天 |
| **Status line 顯示未讀數** | 不必抓 tmux display-message 的 0.75 秒閃光 | 0.5 天 |
| **支線心跳監控** | 配合你既有的 `/opt/tmp/heartbeat/` | 0.5 天 |
| **cc-talk 改用 stream-json** | 長回應可 stream 出來，不必等整輪結束 | 1 天 |

---

## 八、驗收標準（給用戶 Ethan 看的）

整合完成的判斷依據：
- [ ] BeakBroodNest orchestrator 的 dispatcher 能 spawn 多輪會話
- [ ] WorkerInbox 表存在，支線可寫、主可讀
- [ ] tmux 通知正常閃出
- [ ] aside hook 在 `/opt/BeakBroodNest/` 內生效，`aside: ...` 被攔截
- [ ] 主線純淨度測試通過（aside 內容不進主 cc context）
- [ ] 既有的一次性任務派遣（`dispatch_task`）功能未壞
- [ ] heartbeat 寫入

---

## 九、可直接複製的源檔

以下檔案的內容可直接抄進去（路徑改成 BeakBroodNest 對應位置）：

| MVP 來源 | BeakBroodNest 目標 | 是否需修改 |
|---|---|---|
| `/opt/backup/mvp/bin/cc-spawn` | `/opt/BeakBroodNest/orchestrator/cli/cc-spawn` | 改 ROOT 路徑、改 DB（PG）|
| `/opt/backup/mvp/bin/cc-talk` | `/opt/BeakBroodNest/orchestrator/cli/cc-talk` | 改 ROOT、改 DB |
| `/opt/backup/mvp/bin/cc-inbox-put` | `/opt/BeakBroodNest/orchestrator/cli/cc-inbox-put` | 改 ROOT、改 DB |
| `/opt/backup/mvp/bin/cc-inbox-get` | `/opt/BeakBroodNest/orchestrator/cli/cc-inbox-get` | 改 ROOT、改 DB |
| `/opt/backup/mvp/lib/notify.py` | `/opt/BeakBroodNest/orchestrator/notify.py` | 直接抄 |
| `/opt/backup/mvp/hooks/aside_router.py` | `/opt/BeakBroodNest/orchestrator/hooks/aside_router.py` | 改 ROOT、改 DB、改 ASIDE_NAME（避免和場景 1 撞） |
| `/opt/backup/mvp/lib/cc.py` | `/opt/BeakBroodNest/orchestrator/cc_runner.py` | 直接抄 |

---

## 十、整合完成後

請更新 `/opt/BeakBroodNest/CLAUDE.md` 的 orchestrator 章節，加上：
- 場景 1 的多輪互動使用方式
- 場景 2 的 aside hook 使用方式
- 如何驗收（測試指令）

並且把這份 `HANDOVER.md` 標為**已執行**（在開頭加日期戳記），別放著被當成待辦。

完成後 Ethan 會驗收。有疑問就問他，別自己決定取捨。
