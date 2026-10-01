# MCP 參數守門規格（最小修補，不改資料模型）

版本：v1.1（2026-10-01；v1.0 派工前對照現況後修訂，差異見文末）
狀態：已實作並驗收（BBN-38，2026-10-01）。範圍刻意縮小——BBN 日後依 BeakScribe 改版時會整套採用
`/opt/BeakScribe/docs/AI_INTERFACE_RULES.md`（識別子 ASCII、未知識別子拒絕），
現版只堵住會觸發 `\uXXXX` escape 的介面形狀，不動 tag / schema 資料模型。

## 背景
LLM 在工具呼叫 JSON 的陣列 / 物件內寫中文時傾向用 `\uXXXX` escape，手打會錯碼
（實證：tags 表 2026-08-08 同日出現 `隱患` 與 `險患`）。escape 在解析階段就被還原，
server 無法事後偵測，只能從參數形狀上避免。2026-10-01 已完成第一步：
`note_store` / `note_search` / `note_update` / `note_task_create` 的 `tags` 接受逗號分隔字串
（commit `420bc89`）。本規格是第二步。

## 現況盤點（含自然語言的陣列 / 物件參數）

| 工具.參數 | 型別 | 內含中文的可能 |
|-----------|------|----------------|
| `note_store.field_values` | `dict[str,str]` | 值一定是中文（E 類型欄位值） |
| `note_relate_batch.relations` | `list[dict]` | `label` 是中文 |
| `schema_create.fields` | `list[dict]` | 欄位 name / label 是中文 |
| `note_sanitize.extra_replacements` | `dict[str,str]` | 替換前後文字是中文 |
| `*.tags` | `str \| list[str]` | 已可用字串；列表形式仍開放 |
| 其餘（atom_ids、message_ids、relation_types） | int / ASCII enum | 無 |

## 要做的事

### 1. 通用守門（所有工具）
`ai_kb/tools/param_guard.py` 的 `GuardedMCP` 代理包住 FastMCP，於 `register_all()` 單一掛點套用：
每個 `@mcp.tool()` 註冊時自動包一層 `guard_tool`，遞迴走訪 `list` / `dict` 型參數，
任何字串元素、dict 的**鍵**或值含非 ASCII
→ 回 `{"error": "...", "param": "<參數名>", "hint": "<該參數的字串寫法>"}`，不執行。
（mcp SDK 的 FastMCP 沒有 middleware 機制；逐工具手動呼叫容易漏，故採註冊點代理。
守門看到的是 FastMCP 驗證 / 轉型後的值，JSON 字串被預解析成陣列的情況也擋得到。）
`hint` 依參數名給具體寫法（見第 2 節各參數的字串形式）；未列的參數給通用訊息
「陣列 / 物件內請勿放中文，改用字串參數」。
頂層 `str` 參數不檢查。

### 2. 各參數提供字串形式（舊形式保留相容，docstring 改為推薦字串）

| 參數 | 字串形式 | 解析規則 |
|------|----------|----------|
| `field_values` | 多行 `欄位name=值` | 行首（第 0 欄）符合 `識別子=` 即新欄位；其餘行（含縮排行、空行）是上一欄位值的續行，多行值可表達。name 重複報錯 |
| `relations` | 多行 `from_ref -> to_ref : relation_type [: label]` | 第一個 `->` 切左右；右半 `:` 最多切 2 次，label 可省略且可含 `:`；ref 接受 `BBN-137` 或純數字。不支援 confidence（固定 1.0） |
| `schema_create.fields` | 多行 `name|label|field_type[|required[|options]]` | `|` 最多切 4 次；field_type 沿用現有 enum；required 接受 `required/true/1/yes`；options 為逗號分隔字串；sort_order 取行序 |
| `extra_replacements` | 多行 `原文=>佔位前綴` | 第一個 `=>` 切分；原文重複報錯 |
| `tags` | 已完成（`,` `，` `、` 切分） | — |

解析器是 `ai_kb/tools/param_forms.py` 的純函式。解析失敗回
`{"error": "第 N 行格式錯誤: <原文>", "format": "<格式說明>"}`，且**整個呼叫不執行**
（解析一律在 `session_scope()` 之前，避免留下半成品）。

`field_values` 字串形式另有兩個 fail-closed 檢查（dict 形式維持原行為不動）：
沒給 `schema_id` 直接報錯；欄位 name 不在該 schema 內報錯並列出合法欄位。
理由：續行規則下，值裡若有一行恰好長得像 `foo=bar` 會被當成新欄位，
原本「未知欄位靜默略過」會變成靜默掉資料，必須讓它當場可見。

### 3. docstring
每個受影響工具的 docstring 第一段加一行正確範例（字串形式），並明寫「請勿用陣列 / 物件傳中文」。
工具描述是模型呼叫當下讀的，比 CLAUDE.md 有效。

### 4. 測試（一次性 pytest，放專案外）
本專案沒有 `tests/`（2026-07-30 使用者決定刪除，見 `docs/PUSH_POLICY.md`），不為本案重建。
pytest 檔寫在 `/opt/tmp/codex/20261001-mcp-guard/`，不入版控、不連 DB。
- 每個表列參數：送含中文的陣列 / 物件 → 回 error 且 hint 含該參數字串格式
- 每個字串形式：正常解析、格式錯誤回行號
- 純 ASCII 的陣列（atom_ids、relation_types）不受影響
- `tags` 字串與列表行為一致

## 不在範圍
- tag 改 slug + display_name、未知 tag 拒絕（屬 BeakScribe 改版）
- 既有資料清理（`險患` 等錯碼 tag 由人工處理）
- Claude Code 自身工具（AskUserQuestion 等）

## 驗收（Claude）
- 反向檢查：grep 所有 `@mcp.tool()` 函式的 `list` / `dict` 參數，逐一確認守門有覆蓋，不是只檢查表列的四個
- 重啟 MCP（新 session）後實呼叫一次中文陣列確認被擋
- `sudo systemctl restart beakbroodnest.service` 不受影響（守門只在 MCP 層）

## v1.0 → v1.1 修訂（派工前對照現況發現的出入）
| 項目 | v1.0 | 現況 / 問題 | v1.1 |
|------|------|-------------|------|
| 測試位置 | 沿用 `tests/` 慣例 | `tests/` 已刪且 `.gitignore` 擋著 | 一次性 pytest 放專案外 |
| `field_values` | 每行一組 | 既有資料有多行值（`methodology.improved_approach`） | 加續行規則 + 未知欄位報錯 |
| `schema_create.fields` | `code|label|type[|required]` | 實際鍵是 `name/label/field_type/options/required/sort_order`，現有 17 個欄位有 6 個 select 需要 options | 補 `options` 段，名稱對齊實際鍵 |
| 守門檢查對象 | 字串元素 / 值 | `extra_replacements` 的中文在**鍵** | 鍵也檢查 |
