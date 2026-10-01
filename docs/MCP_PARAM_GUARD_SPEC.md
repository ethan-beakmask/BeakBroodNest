# MCP 參數守門規格（最小修補，不改資料模型）

版本：v1.0（2026-10-01）
狀態：待分派 codex。範圍刻意縮小——BBN 日後依 BeakScribe 改版時會整套採用
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
在 `ai_kb/tools/` 加一個共用檢查函式，於每個工具進入點呼叫（或用 FastMCP 的統一前置機制，
擇一，但要覆蓋全部工具）：遞迴走訪 `list` / `dict` 型參數，任何字串元素 / 值含非 ASCII
→ 回 `{"error": "...", "hint": "<該參數的字串寫法>"}`，不執行。
`hint` 依參數名給具體寫法（見第 2 節各參數的字串形式）；未列的參數給通用訊息
「陣列 / 物件內請勿放中文，改用字串參數」。
頂層 `str` 參數不檢查。

### 2. 各參數提供字串形式（舊形式保留相容，docstring 改為推薦字串）

| 參數 | 字串形式 | 解析規則 |
|------|----------|----------|
| `field_values` | 多行 `code=值`（每行一組，`=` 後到行尾全是值） | 第一個 `=` 切分；code 去空白；空行略過 |
| `relations` | 多行 `from_ref -> to_ref : relation_type [: label]` | 以 `->` 與 `:` 切；label 可省略；ref 接受 `BBN-137` 或純數字 |
| `schema_create.fields` | 多行 `code|label|type[|required]` | `|` 切分；type 沿用現有 enum |
| `extra_replacements` | 多行 `原文=>替換` | 第一個 `=>` 切分 |
| `tags` | 已完成（`,` `，` `、` 切分） | — |

解析失敗回 `{"error": "第 N 行格式錯誤: <原文>", "format": "<格式說明>"}`。

### 3. docstring
每個受影響工具的 docstring 第一段加一行正確範例（字串形式），並明寫「請勿用陣列 / 物件傳中文」。
工具描述是模型呼叫當下讀的，比 CLAUDE.md 有效。

### 4. 測試（pytest，沿用 `tests/` 慣例）
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
