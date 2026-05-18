# Orchestrator: cc-to-cc 多輪互動

## 三條路徑

| 場景 | 機制 | 入口 |
|---|---|---|
| 一次性派遣（claude -p 當 agent） | tmux window + wrapper.sh + collector | `dispatcher.dispatch_task()` |
| 多輪互動會話（場景 1） | `claude -p --resume` + worker_sessions | `dispatcher.spawn_session()` / `talk_session()` 或 CLI |
| 主線純淨 aside（場景 2） | UserPromptSubmit hook 攔 `aside:` 前綴 | `.claude/settings.json` → `orchestrator/hooks/aside_router.py` |

## 設計原則：儲存分流，查詢統一

- **儲存分流**：一次性派遣結果存 `worker_reports`（結案報告，看完就好），多輪會話訊息存 `worker_inbox`（對話訊息，需回應）。語意不同，**不合併儲存層**（避免破壞 FK 純度、避免硬塞 task_id 進 inbox 或為一次性任務假造 session）。
- **查詢統一**：兩表的 `read_at IS NULL` 透過 PostgreSQL view `pending_outputs` 統一查詢（schema：source/row_id/session_name/task_id/kind/content/created_at/read_at）。主線一個入口看全部未讀。
- **通知一致**：`worker_inbox` 寫入（cc-inbox-put）與 `worker_reports` 寫入（collector）皆走 `notify.notify_pending()`，前綴 `[CC-Orch]`、未讀數來自 view。

## CLI（路徑：`/opt/BeakBroodNest/orchestrator/cli/`）

```bash
cc-spawn --name dev1 --role "後端開發" --message "請寫個 fizzbuzz.py"
cc-talk  --session dev1 --message "改用 list comprehension"
cc-inbox-put --session dev1 --kind question --content "要不要支援負數？"   # 支線寫
cc-inbox-get --unread-only --mark-read                                    # 主線讀（僅 session）
cc-pending [--source task|session] [--mark-read]                          # 主線讀（task + session 統一）
cc-list
```

## Schema 重點

- `worker_sessions`：`name` UNIQUE、`purpose` 預設 `worker`；hook 自建支線 purpose 為 `hook_aside` / `hook_summary` / ...，name 用雙底線包圍（如 `__aside_default__`）
- `worker_inbox`：`kind ∈ {question, notice, result}`，FK 到 `worker_sessions.name`
- `cc-spawn` 拒絕雙底線開頭的 name（防撞名）；hook 內部呼叫帶 `allow_underscore=True` 旁路

## 場景 2 使用方式

在 `/opt/BeakBroodNest/` 內輸入 `aside: <你的臨時問題>` 即被攔截，由 hook_aside 長期支線處理，主 cc 完全不見此 prompt。

## 驗收測試

```bash
# 場景 1 (e2e)
cc-spawn --name e2e --role 測試 --message "1+1?" --model haiku --no-inbox-protocol
cc-talk  --session e2e --message "上題你回答是 2，那 2+2 呢?只回數字"   # 應答 4
cc-inbox-put --session e2e --kind notice --content "test"
cc-inbox-get --unread-only --mark-read
# 場景 2: 在新 cc 開 /opt/BeakBroodNest 並輸入 'aside: 列出檔案'，主 cc 不會看到此 prompt
```
