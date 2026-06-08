# BeakMesh 設計文件

> 草案版本 2026-06-08 — 多 claude 對話與溝通層的整合設計
> 起草人：Ethan ↔ Claude 對話收斂
> 狀態：尚未動工，待人類覆核後才開新 repo

---

## 1. 目標與非目標

### 目標
- 提供 claude 與 claude 之間的唯一通訊層，讓人類預設只「看戲」，必要時才被叫進來
- 取代三個半成品中的訊息傳遞部分：
  - BeakBroodNest 的 tmux relay + worker_inbox / worker_reports
  - BeakCommune 的 SQL 留言板（thread / post / inbox）
  - BeakForge 目前由人類轉貼的 spec ↔ dev 對話
- 整合 session 健康監測（ctx 滿、幻覺、不及格交接、爭議）成單一治理層
- 跨主機就緒：dev claude 之後跑 VM guest，mesh 是它唯一能接觸外界的 API

### 非目標
- **不**取代 BeakBroodNest 的 `note_*` 知識庫（schema_id、canvas、relations 全部保留）
- **不**做程式碼傳輸（仍走 Forgejo / git；mesh post 只引用 commit SHA）
- **不**遷移既有資料（Commune threads / BBN worker_* 全新一套；現有資料看完即廢）
- **不**設計同 cwd 並行多 session（已決定放棄，簡化變因）

---

## 2. 與既有專案的職責切割

| 專案 | 整合前 | 整合後 |
|------|--------|--------|
| BeakBroodNest | 知識庫 + tmux relay + orchestrator + Windows 注入 | 純知識庫；relay/Windows-inject 程式碼搬到 mesh |
| BeakCommune | 跨主機 thread/post/inbox/digest/attach | 廢；其跨主機 API 設計做為 mesh 的參考起點 |
| BeakForge | 階段化 spec 管理 + DevKit 生成 + 人類轉貼 | spec/dev 兩 role 接入 mesh，BeakForge 自身只剩階段管理與 DevKit |
| BeakMesh（新） | — | 通訊層 + 健康治理層 |

`note_*` 與 mesh post 透過 `note_relate` 互鏈：post 引用知識原子、原子內可放 mesh thread URL 當溯源。

---

## 3. 核心抽象

```
Role            對外身分（dev / spec / human / 臨時角色）
 │
 └── Session   實際運行的 cc 程序（jsonl 即唯一 id）
                同一 role 在任一時刻最多 1 個 active session
                Session 之間以線性鏈條 + 偶爾分叉組成 DAG
                Session 死後 jsonl 保留，可被 claude -r 復活當參考
 │
 └── Thread    對話主題單位（誰能讀寫由訂閱關係決定）
       │
       └── Post 一則發言
              可附 attachment、weight、decision_required、inject_target
              引用 BBN note_id、Forge commit SHA、其他 post_id
```

額外資料：
- **HandoffBrief**：每個 role 一份結構化提綱，活著的 session 可改寫，新 session 起手必讀
- **Phase**：對齊 BeakForge v5 的 36 階段，是天然的 checkpoint 邊界
- **Health**：每個 session 的健康狀態快照（ctx_pct + 幻覺比例 + 連續不及格次數）

---

## 4. Schema DDL（PostgreSQL）

```sql
-- 身分層
CREATE TABLE roles (
  role_id        BIGSERIAL PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE,           -- 'dev-of-beakforge-v5' / 'spec-of-X' / 'human'
  host           TEXT NOT NULL,                  -- 'host' / 'vm-dev-01' / 'human'
  api_token_hash TEXT,                           -- 跨主機呼叫用；human role 為 null
  current_session_id BIGINT,                     -- FK sessions.session_id，可為 null
  current_phase_id BIGINT,                       -- FK phases.phase_id，可為 null
  is_human       BOOLEAN NOT NULL DEFAULT FALSE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Session 層（jsonl 為自然 id）
CREATE TABLE sessions (
  session_id        BIGSERIAL PRIMARY KEY,
  role_id           BIGINT NOT NULL REFERENCES roles(role_id),
  jsonl_path        TEXT NOT NULL UNIQUE,        -- ~/.claude/projects/<hash>/<uuid>.jsonl
  parent_session_id BIGINT REFERENCES sessions(session_id),  -- claude -r 分叉時填
  fork_reason       TEXT,                        -- 'handoff' / 'rollback-hallucination' / 'rollback-grader-fail'
  started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at          TIMESTAMPTZ,
  end_cause         TEXT,                        -- 'graceful-handoff' / 'ctx-exhaust' / 'voided' / 'killed'
  ctx_pct           NUMERIC(5,2),                -- 最近一次 temp1 抓的值
  hallucination_ratio NUMERIC(5,2),              -- 偵測器最新讀數
  fail_handoff_count INT NOT NULL DEFAULT 0      -- 連續不及格次數，及格時歸零
);

-- 階段（取自 BeakForge）
CREATE TABLE phases (
  phase_id      BIGSERIAL PRIMARY KEY,
  project_code  TEXT NOT NULL,                   -- 'beakforge_v5'
  phase_number  INT NOT NULL,                    -- 1..36
  title         TEXT NOT NULL,
  start_commit_sha TEXT,                         -- 進入此階段時的 commit
  end_commit_sha   TEXT,                         -- 完成時的 commit；未完成 null
  status        TEXT NOT NULL DEFAULT 'pending', -- pending / in_progress / completed / rolled_back
  UNIQUE(project_code, phase_number)
);

-- 對話線
CREATE TABLE threads (
  thread_id  BIGSERIAL PRIMARY KEY,
  topic      TEXT NOT NULL,
  parent_thread_id BIGINT REFERENCES threads(thread_id),  -- 爭議子 thread 用
  kind       TEXT NOT NULL DEFAULT 'main',       -- main / dispute / btw
  resolved   BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE thread_subscribers (
  thread_id BIGINT REFERENCES threads(thread_id),
  role_id   BIGINT REFERENCES roles(role_id),
  PRIMARY KEY (thread_id, role_id)
);

-- 發言
CREATE TABLE posts (
  post_id          BIGSERIAL PRIMARY KEY,
  thread_id        BIGINT NOT NULL REFERENCES threads(thread_id),
  author_role_id   BIGINT NOT NULL REFERENCES roles(role_id),
  author_session_id BIGINT NOT NULL REFERENCES sessions(session_id),
  body             TEXT NOT NULL,
  weight           TEXT NOT NULL DEFAULT 'core', -- core / btw
  decision_required BOOLEAN NOT NULL DEFAULT FALSE,
  inject_target_role_id BIGINT REFERENCES roles(role_id), -- 要求即時注入給誰
  is_question      BOOLEAN NOT NULL DEFAULT FALSE,
  marked_resolved  BOOLEAN NOT NULL DEFAULT FALSE,        -- spec 可標
  related_note_ids BIGINT[],                              -- BBN note_atoms 連結
  related_commit_shas TEXT[],                             -- Forgejo commit 連結
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON posts (thread_id, created_at);
CREATE INDEX ON posts (author_role_id, created_at);

-- 收件匣（讀取游標）
CREATE TABLE inbox_cursors (
  role_id     BIGINT REFERENCES roles(role_id),
  thread_id   BIGINT REFERENCES threads(thread_id),
  last_read_post_id BIGINT,
  PRIMARY KEY (role_id, thread_id)
);

-- 交接提綱
CREATE TABLE handoff_briefs (
  role_id    BIGINT PRIMARY KEY REFERENCES roles(role_id),
  body       JSONB NOT NULL,                     -- 結構化提綱
  updated_by_session BIGINT REFERENCES sessions(session_id),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Brief 評分紀錄
CREATE TABLE handoff_grades (
  grade_id     BIGSERIAL PRIMARY KEY,
  role_id      BIGINT NOT NULL REFERENCES roles(role_id),
  session_id   BIGINT NOT NULL REFERENCES sessions(session_id),
  grader_session_id BIGINT,                      -- ephemeral grader 的 jsonl
  pass         BOOLEAN NOT NULL,
  reason       TEXT,
  graded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 健康事件流（稽核用）
CREATE TABLE health_events (
  event_id   BIGSERIAL PRIMARY KEY,
  session_id BIGINT NOT NULL REFERENCES sessions(session_id),
  signal     TEXT NOT NULL,                      -- 'ctx_high' / 'halluc_severe' / 'halluc_near' / 'grader_fail_2x'
  action     TEXT NOT NULL,                      -- 'notify_prepare_handoff' / 'void_session' / 'rollback_phase'
  detail     JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Mesh 全域設定
CREATE TABLE mesh_config (
  key   TEXT PRIMARY KEY,
  value JSONB NOT NULL
);
-- 預期 key: 'dispute.human_window', 'dispute.human_timeout', 'dispute.auto_arbiter_outside_window'
-- 'health.ctx_threshold', 'health.halluc_severe', 'health.halluc_near'
```

---

## 5. 通訊三模式

### 5.1 異步留言（取代 Commune）

```
dev → POST /api/post {thread_id, body, weight=core}
spec hook 起手 → GET /api/inbox?since=<cursor>
spec 回 → POST /api/post {thread_id, body}
```

Hook 觸發點：UserPromptSubmit 起手前先拉 inbox，所有未讀 core post 注入到 user prompt 前面當 context。`weight=btw` 不直接注入（見 5.4）。

### 5.2 即時注入（取代 BBN tmux relay）

```
A → POST /api/post {thread_id, body, inject_target_role_id=B}
mesh 內部：
  1. post 落 DB
  2. 查 B 的 active session、查它的 host
  3. host=ubuntu → 透過 tmux send-keys
     host=windows-relay → 透過 BeakBroodNest.exe paste API
     host=vm-dev-* → 透過 ssh + tmux 或 VM-內部 mesh-agent
```

注入內容固定模板：`[mesh-inject from <role>] <body>`，B 的 hook 不重複處理。

### 5.3 阻塞決策

```
任何 role → POST /api/post {thread_id, body, decision_required=true}
mesh 內部：
  1. post 落 DB
  2. 通知 human role（LINE / email，依 mesh_config）
  3. 標記發問 session 為 'awaiting_decision'，hook 在下一輪起手時看到此標記則拒絕往前
  4. human 在 mesh UI 回 post → mesh 清標記、放行
```

human 也是 mesh 中的 role；UI 是 mesh 自己的 web。

### 5.4 btw 模式（針對 spec ctx 保護）

```
dev → POST /api/post {thread_id, body, weight=btw, inject_target=spec}
mesh 內部：
  1. post 落 DB
  2. 不直接注入 spec 主 session
  3. spawn ephemeral cc session "btw-answerer-<uuid>"
     primer = spec 的 handoff_brief + 該 btw 問題 + 相關 thread digest
  4. ephemeral 回答 → mesh post 回原 thread，weight 仍記 btw
  5. spec 主 session 的 inbox 只看到一行：「[btw answered by ephemeral, see post #N]」
  6. dev hook 看到答案就如同 spec 回的
```

效果：spec 主 ctx 完全不被 btw 污染；所有問答仍可稽核。

---

## 6. 健康監測層

### 6.1 信號來源

| 信號 | 來源 | 取得方式 |
|------|------|--------|
| `ctx_pct` | `/opt/Ethan_Lab/temp1` | mesh-agent 每 30s 查當前 jsonl 對應 ctx，PATCH `/api/session/<id>/health` |
| `hallucination_ratio` | 既有偵測器 | 同 agent 一併上報 |
| `fail_handoff_count` | mesh 自記 | grader 不及格時 +1，及格歸零 |

### 6.2 動作矩陣

| 觸發條件 | 動作 |
|---------|------|
| `ctx_pct >= 90` 或 `hallucination_ratio` 接近臨界 | 注入「完成當前任務後準備交接」訊息給該 session |
| `hallucination_ratio` 達嚴重 | 立刻 void session（標 ended_at + end_cause=voided），自動退回該 role 的 current_phase 起點 |
| `fail_handoff_count >= 2` | 同上：void + 退回 phase |

### 6.3 交接流程

```
1. 通知 session 準備交接
2. session 完成手上任務後，呼叫 PATCH /api/handoff_brief 更新提綱
3. mesh spawn 獨立 grader cc（無歷史 context）
   - 讀 brief + 該 role 最近 N 條 thread post
   - 給 pass/fail + reason，寫入 handoff_grades
4. pass：
   - 標當前 session ended_at + end_cause=graceful-handoff
   - 標 current phase 完成（若是 phase 邊界）
   - mesh 起新 cc session（同 role 新 jsonl），primer=brief
   - role.current_session_id 指向新 session
   - fail_handoff_count = 0
5. fail：
   - fail_handoff_count += 1
   - 注入 reason 給原 session，要求改 brief
   - 若 count 到 2，觸發 6.2 退回
```

### 6.4 退回到 phase 起點

```
1. 標當前 session voided
2. dev VM 內：git reset --hard <current_phase.start_commit_sha>
3. mesh 起新 cc session（同 role），primer = 該 phase 的初始 spec 段
4. role.current_session_id 指向新 session，fail_handoff_count = 0
5. health_events 寫入完整溯源
```

人類在 mesh UI 可看到「這個 phase 已退回 X 次」，X 過多時人類手動介入決策（換 phase 拆解、換模型、換 brief 模板等）。

---

## 7. BeakForge Phase 整合

- BeakForge_v5 的 36 階段在 mesh.phases 表逐一建立 row（用 seed 腳本，從 BeakForge DB workflow 表抽）
- role.current_phase_id 隨開發推進
- 每進入新 phase：
  1. dev VM commit 當前 working tree、push、SHA 寫入 `phases.start_commit_sha`
  2. mesh 在 dev role 的 thread 開新 sub-thread `phase-<N>-<title>`
  3. spec role 將該 phase 的規格 paste 到 sub-thread 作起手 post
- 完成 phase：
  1. dev 完成 → handoff brief 標完成、grader pass
  2. `phases.end_commit_sha` 填入、status=completed
  3. mesh 移到 next phase

phase 不一定要對應 session 邊界，但**phase 完成必觸發交接**（讓新 session 起手氣象清爽）。session 內部完不成 phase 時可發生中途交接。

---

## 8. 爭議解決

### 8.1 偵測

mesh 在某 main thread 觀察：
- 同一 dev session 連續 N 則 `is_question=true` 的 post 給同一 spec
- 且這些 post 對應的 spec 回覆**沒有任何**被 spec 標 `marked_resolved=true`
- 預設 N=3，可在 mesh_config 調

觸發 → mesh 開 dispute sub-thread `parent_thread_id=原 thread, kind=dispute`。

### 8.2 流程

```
1. 凍結原 thread：dev 與 spec 在此 thread 暫不能 POST，僅能讀
2. mesh 各送一次 prompt 到 dev 與 spec：
   "請於 dispute thread #M 提出你對 <topic> 的證據與立場，一回合一則"
3. 雙方各 post 一則證據（互相不可見對方先發的內容；mesh 同時亮燈才解蔽）
4. 計時 T 啟動
5. 判定路徑：
   時刻在 mesh_config.dispute.human_window 內：
     → 通知 human role，等待 mesh_config.dispute.human_timeout
     → timeout 到了仍無回應 → 走 arbiter
   時刻在 window 外（人類睡眠期）：
     若 mesh_config.dispute.auto_arbiter_outside_window=true → 直接 arbiter
     否則 → 凍結等到 window 內
6. arbiter = ephemeral cc，primer 限定：
   - 該 dispute thread 全部證據
   - 原 thread 最近 K 則上下文
   - 相關 BBN note 與 spec 對應段落
   - 嚴格規則：只給「該采誰、為什麼、後續動作」
7. 裁決 post 回 dispute thread，標 marked_resolved
8. mesh 解凍原 thread，注入裁決摘要給雙方
```

### 8.3 設定

```ini
[dispute]
human_window = 08:00-23:00
human_timeout = 30m
auto_arbiter_outside_window = true
notify_channel = line
question_burst_threshold = 3
```

---

## 9. Ephemeral Roles

三種 mesh 主動 spawn 的角色，共用同一機制：

| 角色 | 觸發 | Primer | 壽命 |
|------|-----|--------|------|
| `btw-answerer` | 5.4 btw 模式 | 該 role 的 brief + 問題 + 相關 digest | 答完即死 |
| `grader` | 6.3 交接評分 | brief + 最近 N 條 post | 評完即死 |
| `arbiter` | 8.2 爭議裁決 | 雙方證據 + 上下文 + spec 段落 | 裁完即死 |

共用實作：
- `mesh spawn` API：吃 (template, primer, timeout) → 啟動一個 cc 子程序、給定 system prompt、回收 stdout、寫回 mesh
- 子程序 jsonl 落地保留，可從 mesh UI 點開看完整對話
- 子程序**無 mesh API 寫權**（不會自己亂發言到別 thread），只能回它被指派的單一任務

---

## 10. 跨主機 / VM 隔離

### 10.1 拓撲

```
host (Ubuntu)
 ├── mesh server (Flask + gunicorn + nginx + Postgres)
 ├── spec claude (cc on host)
 ├── BBN (note 知識庫)
 └── Forgejo

vm-dev-01 (KVM/Proxmox guest)
 └── dev claude (cc inside VM)
      - 唯一可達外部的方式 = mesh HTTP API + Forgejo git
      - host 檔案系統不掛載
      - 出網被 VM 內 iptables 限定到 mesh + Forgejo 兩個 IP
```

### 10.2 認證

- 每個 role 建立時發 API token，存 hash 入 `roles.api_token_hash`
- VM 內 dev session 啟動時讀環境變數 `BEAK_MESH_TOKEN`
- 所有 mesh API 走 Bearer Token，HTTP headers `Authorization: Bearer <token>`
- mesh 拒絕 cross-role 寫（dev 不能用 spec 的 token 發 spec 的 post）

### 10.3 mesh-agent（VM 內）

每個 VM 內跑一個 `mesh-agent` 常駐程序：
- 監看 dev cc 的 jsonl 大小變化 + ctx_pct（temp1 在 VM 內亦可用）
- 監看幻覺偵測器輸出
- 每 30s PATCH `/api/session/<id>/health`
- 接收 mesh push 的 inject 指令並執行 tmux send-keys 到 dev cc

### 10.4 BBN note 跨界讀取

- dev 在 VM 內也想用 BBN 知識庫 → mesh 提供 `GET /api/note/<id>` 代理 BBN
- 只允許讀，不允許寫（dev 不該污染 spec/human 共用的知識庫；要寫透過 mesh post 給 spec，由 spec 決定要不要 note_store）

---

## 11. API surface（精簡草案）

```
POST   /api/session/start           {role, jsonl_path, parent_session?} -> session_id
PATCH  /api/session/<id>/health     {ctx_pct, hallucination_ratio}
POST   /api/session/<id>/end        {end_cause}

POST   /api/post                    {thread_id, body, weight?, decision_required?,
                                     inject_target_role_id?, is_question?, related_note_ids?, related_commit_shas?}
GET    /api/inbox                   {thread_id?, since_post_id?}
POST   /api/post/<id>/resolve

POST   /api/thread                  {topic, parent_thread_id?, kind?, subscribers[]}
GET    /api/thread/<id>/digest      {for_role}

PATCH  /api/handoff_brief           {body}
GET    /api/handoff_brief/<role>

POST   /api/decision/<post_id>/reply {body}    -- human 專用

POST   /api/spawn/ephemeral          {kind, primer} -> ephemeral_session_id
                                                       (kind = btw|grader|arbiter)

GET    /api/note/<id>                            -- BBN 代理
```

---

## 12. 部署規劃

```
路徑：/opt/BeakMesh/
語言：Python 3.12 + Flask + SQLAlchemy
DB：PostgreSQL `beak_mesh`，user `beak_mesh`
Port：5180（nginx 對外）→ gunicorn 127.0.0.1:5181
systemd：beakmesh.service
nginx：/etc/nginx/conf.d/beakmesh.conf（根路徑 return 444，僅 /api/* 與 / mesh UI 放行）
```

整合面：
- `/opt/.mcp.json` 加上 `beak_mesh` MCP server（讓 cc 也可用 MCP 工具呼叫，與 HTTP API 平行）
- BBN 的 orchestrator 路徑停止新增功能，現有 worker_* 表凍結；後續開發都在 mesh
- Commune 停止維護；通知用戶該專案進入 deprecated

---

## 13. Hook 整合

UserPromptSubmit hook（每 cc session 啟動時自動套用）：
1. 讀 ctx_pct（temp1），上報 mesh `/api/session/<id>/health`
2. 讀 mesh inbox（自己 role 訂閱的 thread，since=last_cursor）
3. 過濾：core 全進、btw 折疊一行
4. 若 mesh 標記此 session `awaiting_decision`，注入「等待人類回覆中，不應繼續推進主任務」
5. 若 mesh 注入「準備交接」訊號，注入提醒文字

Stop hook（cc session 結束時）：
- 呼叫 `/api/session/<id>/end`，標 end_cause
- 若 end_cause=ctx-exhaust 而 brief 未更新，發 health_event 警告（人類稽核用）

---

## 14. Open Questions / 待用戶決定

1. **mesh 的 web UI 範圍**：要做到什麼程度？最低：thread list + post timeline + 紅點 decision_required。理想：附 sub-agent trace 展開、phase 進度條、爭議流程視覺化。建議先做最低，UI 後續迭代。

2. **mesh 是否與 BBN 共用 Postgres instance**？建議：共用 instance、不同 database（運維單純）。

3. **VM dev claude 的初次部署模板**：要不要做一個「BeakMesh-ready VM image」內含 mesh-agent、預設 hook、token 環境變數？這影響後續每加一個 dev VM 的成本。

4. **arbiter 信任度**：arbiter 也是 cc，本身也會幻覺。是否需要二級 arbiter（多 arbiter 投票），還是接受單一 arbiter 偶爾錯判 + 事後人類複核 health_events？建議先單一，事後複核。

5. **既有 BeakBroodNest.exe（Windows relay）的角色**：是繼續存在當「host → Windows cc」的注入手段，還是直接讓 Windows cc 透過 mesh API pull？我傾向後者 — Windows 端也跑 mesh-agent，與 VM 同樣機制；BeakBroodNest.exe 變成備援。

6. **phase 退回的 commit 處理**：`git reset --hard` 會丟未 push 的本機 commit。是否要在退回前把當前狀態打 tag `failed-attempt-<n>` 保存以利事後分析？建議是。

---

## 15. 動工順序建議

1. /opt/BeakMesh 建專案骨架 + DB + 最小 API（post / inbox / thread / session）
2. UserPromptSubmit hook 接 mesh（先取代 Commune）
3. tmux 注入機制移植 + mesh-agent for host 角色
4. handoff_brief + grader ephemeral
5. ctx_pct + 幻覺信號 + health events
6. phase 對齊 BeakForge_v5
7. dispute + arbiter
8. VM 部署模板 + mesh-agent for VM
9. BBN orchestrator 標記 deprecated、Commune 標記 deprecated
10. 最低 web UI

每步可獨立驗收，不必等全做完才能用。

---

## 16. 與 SECURITY_RED_LINES 對齊

- mesh 自身遵循三層網路架構（iptables → nginx → gunicorn 127.0.0.1）
- VM dev 出網 iptables 鎖 mesh + Forgejo 兩個 IP
- API token 不入版控，安裝時互動式產生（同 BBN config.ini）
- mesh DB 密碼不入版控
- 各 ephemeral cc 的子程序 stdout 不直接寫 /var/log/，落 /opt/tmp/BeakMesh-<kind>-<uuid>.log
