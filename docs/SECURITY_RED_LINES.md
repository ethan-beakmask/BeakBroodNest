# BeakBroodNest 安全紅線

本段落定義不可違反的安全底線。所有 Claude（主代理與子代理）在本專案的任何操作皆受此約束。

## 通用紅線

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

## BeakBroodNest 特有紅線

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
