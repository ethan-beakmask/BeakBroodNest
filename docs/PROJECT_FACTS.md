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

## 測試怎麼跑

```bash
cd /opt/BeakBroodNest && venv/bin/python -m pytest -q      # 全套，目前 57 passed
```

**不需要另外起 dev server**。測試一律走 Flask `test_client`（見上一節），2026-07-29 前
`test_gantt_*.py` 曾硬打 `http://127.0.0.1:5172`，沒起 server 就 13 個全紅——那是已修掉的舊寫法，
不要再照抄。

寫新測試時的既定慣例（照 `tests/conftest.py` 與 `tests/test_standalone_entries.py`）：

- 測試**自建 fixture 資料**，不依賴既有白板 / entry id。死寫 slug 或 id 的測試換台機器必掛
- fixture 走 `core.db.session_scope()`，它離開時會 **commit**（資料真的進 DB），
  所以 teardown 必須用**明確 id** 反向刪除，嚴禁 `title LIKE 'xxx%'` 之類掃全表的條件
- 前提不滿足（缺 schema、缺白板）時 `pytest.skip`，不要 fail
- 測試資料一律標 `owner='pytest'`，殘留檢查才有依據：
  ```bash
  cd /opt/BeakBroodNest && venv/bin/python -c "
  import sys; sys.path.insert(0,'/opt/BeakBroodNest')
  from core.db import init_engine, session_scope
  from core.models import Canvas, KnowledgeAtom
  init_engine('/opt/BeakBroodNest/config.ini')
  with session_scope() as s:
      print('殘留 canvas:', s.query(Canvas).filter(Canvas.owner=='pytest').count())
      print('殘留 atom:', s.query(KnowledgeAtom).filter(KnowledgeAtom.owner=='pytest').count())"
  ```

**`tests/` 刻意不入版控**（`.gitignore` 排除，2026-07-30 用戶裁決維持）。因此測試的修改不會
出現在 `git status`、不會隨 push 散佈、公司機那類部署也拿不到——**開發機是測試的唯一權威來源**。
不要因為 `git status` 乾淨就以為沒動到測試，也不要試圖「修好」這件事。
對 push 流程的影響見 `docs/PUSH_POLICY.md`。

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
