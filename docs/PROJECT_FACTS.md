# BeakBroodNest 固定事實速查

每個新 session 都可能用到、但靠試誤才會弄對的事實。**動工前先讀這份，不要重新摸索。**

與 `docs/SERVICES_AND_SCHEDULES.md` 的分工：那份講服務怎麼裝與管，這份講「開發時怎麼快速驗證」。

---

## 對外存取

| 用途 | 位址 |
|------|------|
| 瀏覽器實測（**規範要求用 LAN IP**） | `http://192.168.0.16:5170/beakbroodnest/` |
| nginx 前端 | `192.168.0.16:5170`（**不是 80**） |
| gunicorn 後端 | `127.0.0.1:5171`（直連會回 401） |

nginx 根路徑 `return 444`，只有 `/beakbroodnest/` 前綴會被服務。用 `http://192.168.0.16/...`（port 80）測會拿到 `HTTP 000`——那是打到別的 server block，不是服務掛了。

## API 測試：用 test_client 繞過登入

所有 `/api/observe/*` 等 API 都受 `app.before_request` 保護，未登入回 `{"error":"未登入"}` 401。登入流程有 AES 加密，curl 手動走很麻煩。**開發驗證直接用 Flask test_client 灌 session**：

```bash
cd /opt/BeakBroodNest && venv/bin/python - <<'EOF'
import sys; sys.path.insert(0,'/opt/BeakBroodNest')
from human_ui.app import app
c = app.test_client()
with c.session_transaction() as s:
    s['authenticated'] = True
    s['username'] = 'test'
r = c.get('/beakbroodnest/api/observe/conversations?limit=5')
print(r.status_code, r.get_json())
EOF
```

量測 API 效能（回應大小 + 耗時）也用同一套，把 `c.get` 包進計時即可。

## 測試：本專案沒有自動化測試套件

**`tests/` 目錄已於 2026-07-30 由用戶決定整個刪除，`pytest` 沒有東西可跑。**
不要去找它、不要以為是自己漏 clone，也不要自作主張重建一套。

驗證改動一律靠**手動 / 端對端驗證**：用上一節的 `test_client` 打 API、用下一節的方式查 DB、
用 `http://192.168.0.16:5170/beakbroodnest/` 實際操作 UI。push 前的要求見 `docs/PUSH_POLICY.md`。

需要臨時寫驗證腳本時，寫成一次性的 `venv/bin/python - <<'EOF'` 片段跑完就算，
不要在專案內留下檔案。若真要落地成檔案，先問用戶要放哪。

（歷史備份：刪除前的內容在 `backups/tests_removed_20260730.tar.gz`，該目錄不入版控。）

## DB 存取

**用專案 DB 層，不要自己 parse `config.ini`**（section 名的坑：`core/db.py` 與 `scripts/review_analyzer.py` 讀法不同）。

```bash
cd /opt/BeakBroodNest && venv/bin/python - <<'EOF'
from core.db import get_session, get_engine   # 注意：是 get_engine()，不是 engine
from sqlalchemy import text
s = get_session()
for row in s.execute(text("SELECT count(*) FROM conversations")):
    print(row)
EOF
```

需要 raw psycopg2 cursor（例如 `copy_expert` 匯出）時：`get_engine().raw_connection()`。

### UUID 型別

`conversations.id`、`conversation_turns.conversation_id` 都是 `uuid` 型別。用 Python list 當參數時**必須顯式轉型**，否則報 `operator does not exist: uuid = text`：

```python
s.execute(text("SELECT ... WHERE id = ANY(CAST(:ids AS uuid[]))"), {'ids': id_list})
```

## Claude Code JSONL 原始檔

路徑規則：`/home/ethan/.claude/projects/<專案路徑把 / 換成 ->/<conversation_id>.jsonl`

例：`/opt/BeakBroodNest` → `/home/ethan/.claude/projects/-opt-BeakBroodNest/<uuid>.jsonl`

### 區分真人發言與系統注入

JSONL 把 harness 注入的內容也記成 `type: user`。要區分看這兩個欄位：

| | `origin.kind` | `promptSource` |
|---|---|---|
| 真人打字 | `human` | `typed` |
| 系統注入（背景任務通知等） | `task-notification` | `system` |

目前 `parse_conversation.py` 與 `db_importer.py` 都沒讀這兩欄，`conversation_turns` 也無對應欄位——待辦見知識庫 atom 4865。

## P3 複盤增量判準（改動前必讀）

`scripts/review_analyzer.py` 自 commit `d8425de` 起為增量模式，判準是：

> `conversations.last_timestamp` > 該對話最近一次 `pipeline_runs` 中 `pipeline_name='p3_review' AND status='completed'` 的 `started_at`

**任何會刷新 `conversations.last_timestamp` 的批次操作（例如重跑 `db_importer` 的 upsert，見 `scripts/db_importer.py:679`），都會讓 P3 判定全部 2 萬場需重分析，直接打回 600 秒 timeout。** backfill 類工作必須只 UPDATE 目標欄位，不走 upsert 路徑。

驗證 P3 是否正常：
```bash
# 連跑兩次，第二次應為 0 筆、秒級結束
cd /opt/BeakBroodNest && venv/bin/python scripts/review_analyzer.py --all --skip-claude

# nightly 結果
grep 'status=' /opt/tmp/scripts-nightly_pipeline.log | tail -3
```

## Schema migration 慣例

**沒有自動 runner。** `human_ui/app.py:92` 的 `_migrations_done` 只呼叫 `ensure_canvas_slugs()`，不會掃 `migrations/` 目錄；`scripts/install.sh` 也不引用該目錄（它另走「Schema 補丁」路徑，跑的是 `scripts/init_*.sql` 那批 `CREATE TABLE IF NOT EXISTS`）。

`migrations/NNN_名稱.up.sql` / `.down.sql` 是**人工撰寫、人工套用**的。慣例（照 `031_turn_evaluations.up.sql`）：

- 三位數流水號遞增，up/down 成對
- 檔頭用註解寫「背景」段落說明為何這樣設計，不只寫 what
- 內容包在 `BEGIN; ... COMMIT;`，用 `CREATE TABLE IF NOT EXISTS` 等冪等寫法

套用方式為手動執行 SQL（psql 或 `get_engine()` 跑）。新增 migration 後**必須自己套用並確認**，不會有人幫你跑：

```bash
cd /opt/BeakBroodNest && venv/bin/python - <<'EOF'
from core.db import get_engine
from sqlalchemy import text
sql = open('migrations/032_xxx.up.sql', encoding='utf-8').read()
with get_engine().begin() as c:
    c.execute(text(sql))
print('已套用')
EOF

# 確認結果（表/欄位是否真的存在）
venv/bin/python -c "
from core.db import get_session; from sqlalchemy import text
print(get_session().execute(text(\"SELECT to_regclass('新表名')\")).scalar())"
```

## JSONL record 與 DB turn 不是一對一

`scripts/db_importer.py:368` 起的拆分邏輯：

- 一個 JSONL record 的 `message.content` 若是 list，會被**拆成多個 turn**（每個 tool_use / tool_result / text block 各一筆）
- `SILENT_SKIP_TYPES` 內的 record 會被整筆跳過
- `turn_seq` 是 importer 自己從 1 遞增的序號，**與 JSONL 行號無關**
- **JSONL record 的 `uuid` 沒有存進 `conversation_turns`**（只存了 `parent_uuid`）

**後果**：任何要「從 JSONL 補欄位回既有 turn」的 backfill，無法用 uuid 做 join，只能重跑相同的拆分邏輯來重建對應關係，或改為在 importer 內處理。動這類工作前先讀 `db_importer.py` 的拆分段落，別假設一行對一筆。

## 批次操作前的安全檢查

改動 `conversations` 或 `conversation_turns` 的批次作業，執行前後各跑一次，比對數值不得漂移（尤其 `last_timestamp`，見上節 P3 增量判準）：

```bash
cd /opt/BeakBroodNest && venv/bin/python - <<'EOF'
from core.db import get_session
from sqlalchemy import text
s = get_session()
r = s.execute(text("""SELECT count(*), min(last_timestamp), max(last_timestamp),
 md5(string_agg(id::text || last_timestamp::text, ',' ORDER BY id)) AS fingerprint
 FROM conversations""")).fetchone()
print('筆數/最早/最新/指紋:', r)
EOF
```

指紋不變 = `last_timestamp` 完全沒被動到。

## 背景服務干擾

批次作業期間可能與這些併發：`nightly_pipeline`（每晚 08:45，見 `/etc/crontab`）、`pipeline_listener`（事件驅動，取代原 P1/P2 輪詢）、P0 匯入。長時間 backfill 前先確認是否需暫停，並在完成後確認 nightly 仍正常：

```bash
grep 'status=' /opt/tmp/scripts-nightly_pipeline.log | tail -3
systemctl status beakbroodnest.service --no-pager | head -5
```

## 時區

系統時區 `Asia/Taipei (CST, +0800)`。DB 內 `timestamp with time zone` 欄位取出來帶 `+08:00`。

`date` 指令行為正常，沒有時區飄移問題。

**但有個容易誤判的陷阱**：UTC 與 CST 差 8 小時，而長時間 session 中斷後的時間誤差也常落在數小時量級，兩者容易被誤認為同一回事。2026-07-19 就發生過：發言時間戳偏差 5~8 小時，一度被歸因為「`date` 回傳 UTC」，實際查證 DB 內 `conversation_turns.timestamp` 後發現是**內部推算時間**造成的（全域 CLAUDE.md 明訂「一律用 `date '+%H:%M'` 取得，禁止內部推算」，違反後又碰上用戶離開近 6 小時，誤差被放大）。

要驗證某段對話的真實時間，別靠推算或記憶，查 DB：

```bash
cd /opt/BeakBroodNest && venv/bin/python - <<'EOF'
from core.db import get_session
from sqlalchemy import text
s = get_session()
for r in s.execute(text("""SELECT turn_seq, to_char(timestamp,'MM-DD HH24:MI') t, role, left(content,50)
 FROM conversation_turns WHERE conversation_id='<conversation_id>'
 ORDER BY turn_seq DESC LIMIT 20""")):
    print(r)
EOF
```

## 服務重啟

```bash
sudo systemctl restart beakbroodnest.service && systemctl is-active beakbroodnest.service
```

改動 `human_ui/` 下的 Python 需重啟才生效；只改 `static/` 或 `templates/` 通常不必，但瀏覽器要強制重新整理。

## 待辦系統（2026-08-02 起）

### 卡片內容的真實來源是 entries，不是 `atom.content`

**動任何「幫卡片補結構」的程式前必讀。** `card-editor.js:736` 的 `loadEntries()`
最後是 `setContent({type:'doc', content})`——整份覆蓋。所以：

> 只要一張卡有 `atom_entries`，`knowledge_atoms.content` 就**永遠不會**顯示在白板上。

2026-08-02 因此出過事：`note_task_adopt` 替 18 張既有知識卡補了 task entry，
那些卡原本沒有任何 entry、內容靠 `atom.content` 顯示，收編後在白板上全部變空
（資料沒丟，只是看不到）。修法是 `core/task_service.ensure_freetext_entries()`：
把 `content` **逐行**拆成 freetext entries（逐段不行，段內換行在 tiptap 會消失）。

驗收時不能只查 DB 有沒有寫進去，要從**人類會看的入口**看一次。卡片有兩個入口且行為不同：
`/todos` 的「編號」欄開 modal（讀 `atom.content`）、「開啟」欄開白板 tiptap（讀 entries）。

### 短代號與專案代號

| 專案 | 白板 id | slug | code |
|------|---------|------|------|
| BeakBroodNest | 24 | Ghyy2Acy | `BBN` |
| BeakPlatform | 29 | tMU_fnXu | `PF` |

短代號格式 `BBN-137`，發號唯一入口是 `core/ref_code.py` 的 `assign_ref_code()`
（底層走 DB 函式 `next_ref_code()` + `project_ref_counters` 計數表，併發安全）。
**代號一旦發過號就不能改**（`ensure_project_code()` 會擋）。

新專案接上系統：`project_setup(project_path, code, name)`，冪等。
沒有 `code` 的白板無法發號，`note_task_create` 會直接失敗。

### MCP 工具分工

**這些都是 MCP 工具**（定義在 `ai_kb/tools/task.py` 與 `ai_kb/tools/project.py`），
在 Claude Code session 中直接呼叫即可，不需要寫 Python、不需要起 server。
下面的 `FakeMCP` 只是「想在 shell 裡驗證」時用的旁路。

| 工具 | 主要參數 | 用途 |
|------|----------|------|
| `project_setup` | `project_path`（絕對路徑，目錄不必已存在）、`code`、`name`、`description` | 新專案接上系統，冪等 |
| `note_task_create` | `title`、`content`、`project`、`parent_ref`、`urgency`（H/M/L）、`planned_start`、`planned_duration`、`note`、`tags` | 新建待辦（唯一入口，`parent_ref` 會自動建 contains 邊） |
| `note_task_adopt` | `ref`（短代號或 atom id）、`project`、`urgency`、`parent_ref` | 既有知識卡就地收編，冪等 |
| `note_task_update` | `ref`、`progress`、`urgency`、`planned_start`、`planned_end`、`note` | 只改欄位，無副作用 |
| `note_task_status` | `ref`、`status`、`reason` | 只改狀態（含 pause/reopen log、完成前檢查未完成子任務） |
| `project_tasks` | `cwd` | 依目錄查該專案待辦，與 `/todos` 同源 |

`project` 參數三種寫法都吃：專案代號（`BBN`，大小寫不敏感）、白板 slug、
以 `/` 開頭的專案目錄路徑（走 `project_path` 最長前綴匹配）。
省略 `project` 但有給 `parent_ref` 時，會繼承母卡的專案。

### 新專案端到端範例

```
project_setup(project_path='/opt/BeakGuard', code='GD', name='BeakGuard')
  -> {"canvas_id":.., "slug":"..", "code":"GD", "created":true, "next_seq":1}

note_task_create(title='規劃防火牆節點資料模型', content='...', project='GD', urgency='H')
  -> {"ref_code":"GD-1", "atom_id":.., "entry_id":.., "freetext_entries":N}

project_tasks(cwd='/opt/BeakGuard')     # 確認查得到
```

人類端確認：`http://192.168.0.16:5170/beakbroodnest/todos`，左側「單一白板」選新專案；
或直接 `/beakbroodnest/todos/api/items?canvas_slug=<slug>`。

**`code` 不要自己決定。** 代號一旦發過號就不可變更，動手前先問用戶要用什麼代號。

### 不用起 MCP server 就能測工具

```python
class FakeMCP:
    def __init__(self): self.tools = {}
    def tool(self):
        def deco(fn): self.tools[fn.__name__] = fn; return fn
        return deco
```

```bash
cd /opt/BeakBroodNest && venv/bin/python - <<'EOF'
import sys, json; sys.path.insert(0,'/opt/BeakBroodNest')
from core.db import init_engine; init_engine('/opt/BeakBroodNest/config.ini')   # 必須先做
class F:
    def __init__(s): s.tools={}
    def tool(s):
        def d(fn): s.tools[fn.__name__]=fn; return fn
        return d
m=F()
from ai_kb.tools import task; task.register(m)
print(json.loads(m.tools['note_task_create'](title='測試', project='BBN')))
EOF
```

測完記得清乾淨：刪 atom / atom_entries / entry_field_values / entry_field_change_log /
canvas_atoms / unified_relations，並把 `project_ref_counters` 的 `next_seq` 改回原值
（否則正式發號會跳號）。

### `/todos` 的收錄判準

`status` 不在 `{completed, cancelled}` 的**全部** task entry，不論有無 `planned_start`。
`/calendar` 是同一批資料中「有日期者」的視圖，不是另一個集合。
`planned_start` 只是欄位與排序依據，不決定「算不算待辦」。
