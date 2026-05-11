/**
 * Mermaid / HTML 範本字串
 * 每個範本內以 `%%` (Mermaid) 或 `<!-- -->` (HTML) 註解標出可修改處。
 */

export const MERMAID_TEMPLATES = {
    sequence: `sequenceDiagram
%% 參與者與訊息可自由修改
participant U as 使用者
participant S as 系統
U->>S: 送出請求
S-->>U: 回應結果
`,
    flowchart: `flowchart TD
%% 節點與連線可自由修改
A[開始] --> B{條件判斷}
B -- 是 --> C[執行任務]
B -- 否 --> D[結束]
C --> D
`,
    swimlane: `flowchart LR
%% 使用 subgraph 模擬泳道
subgraph 使用者
  U1[輸入資料]
end
subgraph 系統
  S1[驗證] --> S2[儲存]
end
U1 --> S1
S2 --> U1
`,
}

export const HTML_BLOCK_TEMPLATE = `<!-- 可直接撰寫 HTML 或內嵌 SVG。儲存時會經 DOMPurify 過濾 -->
<div style="padding:8px;border:1px solid #94a3b8;border-radius:4px;">
  <strong>HTML 區塊</strong>
  <p>放置原生標籤或 inline SVG。</p>
</div>
`
