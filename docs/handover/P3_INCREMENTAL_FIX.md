# 交接：P3 複盤分析器增量化修復

- 建立：2026-07-19（Fable 5 診斷後交接）
- 交接原子：#4860（完成後 note_update 此原子）
- 執行者：主 CC（Opus）撰寫 spec 派給 codex 開發，Opus 負責審查驗收
- 急迫度：高——nightly_pipeline 自 2026-07-15 起每晚 status=failed

## 背景與根因（本 session 已診斷完成，不必重查）

`scripts/nightly_pipeline.py` 每晚 08:45 執行四階段，P3 呼叫：

```
/opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/scripts/review_analyzer.py --all --skip-claude
```

nightly_pipeline 對 P3 設 600 秒 timeout。根因在 `scripts/review_analyzer.py:527` 的 `analyze_all()`：

```python
cur.execute("SELECT id FROM conversations ORDER BY last_timestamp DESC")
```

**無任何增量過濾**，每晚全量重掃約 1.9 萬場對話。實測數據（2026-07-19 查證）：

- `pipeline_runs` 表 `pipeline_name='p3_review'` 已累積 757,011 筆
- 同一 conversation 被重複分析近 60 次（每晚一次）
- 7/6~7/14 執行時間 536~595 秒（貼著上限），7/15 起連續 4 晚 timeout 600s

## 修復規格

1. `analyze_all()` 改為增量：只分析「從未被 P3 成功分析過」或「`conversations.last_timestamp` 晚於該對話最近一次成功分析」的對話。「最近一次成功分析」= `pipeline_runs` 中 `pipeline_name='p3_review'` **且 `status='completed'`** 的 max(`started_at`)；failed/timeout/running 不算已分析。`conversation_id IS NULL` 的 rows 不參與增量判斷（忽略）。實作方式建議直接 SQL 過濾（LEFT JOIN LATERAL 或子查詢），不要撈全部再在 Python 過濾。
2. 新增 `--force-all` 參數保留舊行為（全量重掃），預設走增量。
3. `pipeline_runs` 舊資料清理：提供一次性清理選項 `--prune-runs`，只清 `pipeline_name='p3_review'`，每個 conversation_id 保留 `started_at` 最新一筆（同時間戳以 id 大者為準）；`conversation_id IS NULL` 的 rows 一律保留。**預設不執行**；程式先印出將刪除筆數，未帶 `--yes` 時不刪除並 exit 1，支援 `--dry-run`。
4. 中文參數說明（無參數顯示 usage）維持專案慣例；錯誤處理完整。
5. 不動 `analyze_conversation()` 內部邏輯與輸出格式（pipeline_runs INSERT、JSON 檔），只改挑選對話的範圍。

## 環境上下文（照抄可用，本 session 驗證過）

DB 存取一律用專案 DB 層，**不要**自己 parse config.ini（section 名不是 postgresql，會踩雷）：

```bash
cd /opt/BeakBroodNest && venv/bin/python - <<'EOF'
from core.db import get_session
from sqlalchemy import text
s = get_session()
for row in s.execute(text("SELECT pipeline_name, status, count(*), max(started_at) FROM pipeline_runs GROUP BY 1,2 ORDER BY 4 DESC NULLS LAST LIMIT 12")):
    print(row)
EOF
```

`pipeline_runs` 欄位（實查）：`id, pipeline_name, trigger_type, session_id, conversation_id, stages, current_stage, status, started_at, completed_at, error_detail, total_turns_processed, signals_found, topics_generated`

重複分析驗證查詢（修復後此值不應再每日 +1）：

```sql
SELECT conversation_id, count(*) FROM pipeline_runs
WHERE pipeline_name='p3_review' GROUP BY 1 ORDER BY 2 DESC LIMIT 5;
-- 修復前實測：每對話 59~60 筆
```

nightly 結果確認：

```bash
grep 'status=' /opt/tmp/scripts-nightly_pipeline.log | tail -5
# 修復前：7/15 起連續 p3_review=timeout/600.0s status=failed
```

## codex 呼叫規範（本機限定，見專案 CLAUDE.md）

```bash
timeout 600 sudo -u ethan codex exec \
  --sandbox danger-full-access \
  --skip-git-repo-check \
  -C /opt/BeakBroodNest \
  -o /tmp/codex_result.txt \
  "<spec>" 2>&1
```

必須保留 stderr 並外掛 timeout（429 限流會靜默重試）。模型不必指定，帳號預設即為 `gpt-5.5`（`-m` 留空即可）。

**分工**：接手的主 CC（Opus）不直接改程式，把本文件「修復規格」段落連同相關開發規範組成 spec，用上面指令派給 codex 實作；Opus 只做審查驗收。codex 連續失敗 2 次或限流時，依全域 CLAUDE.md 例外條款改由 Opus 直接修。

## 驗收步驟（Opus 審查）

1. 讀 diff：確認只改對話挑選邏輯、無硬編碼認證、參數說明為中文。
2. **先記錄基準**：跑上面的重複筆數 SQL，記下 top 5 的 count（2026-07-19 實測為 59~60）。
3. 手動跑 `venv/bin/python scripts/review_analyzer.py --all --skip-claude` 兩次：第一次處理的對話數應遠小於 1.9 萬（實際數量取決於距上次成功分析累積的新對話，7/15 起 P3 全掛，預估數百場）；**緊接著跑第二次應為 0 筆、秒級結束**——第二跑歸零才是硬判準。
4. 重跑基準 SQL，count 對比步驟 2 不得增加。
5. 隔天檢查 `grep 'status=' /opt/tmp/scripts-nightly_pipeline.log | tail -1` 應為 status=completed。
6. 完成後 `note_update` 更新交接原子（id 見本文件開頭），commit（繁中訊息、簡述 why）+ push origin 與 github 兩個 remote；工作區若有他人變更先確認範圍再 add，只 add 本任務相關檔案。
