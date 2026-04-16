# Claude 工作流 .md 檔案生態系統指南

> 來源：Claude 對話整理，適用於 BeakCortex / BeakPlatform 多代理開發場景
> 對象：資安 + vibe coding 開發者，使用 claude -p 子代理架構

---

## 一、VISION.md 與 DESIGN.md 基本定義

### VISION.md — 回答「為什麼」

產品／專案願景文件，內容包含：

- 專案存在的理由、要解決什麼痛點
- 目標使用者（Persona）與核心使用情境
- 核心價值主張、北極星指標
- 不做什麼（Non-goals）
- 長期方向與成功的定義

特性：抽象、少變動、不談技術細節。寫給自己、團隊、貢獻者，讓所有人對「方向」有共識。

### DESIGN.md — 回答「怎麼做」

技術設計文件，比 ARCHITECTURE.md 更貼近實作層面：

- 關鍵設計決策與 trade-off（通常附 ADR 風格的理由）
- 資料模型、Schema、API 介面設計
- 重要流程的 sequence / flow
- 元件之間的契約（contract）
- 已知限制與未來擴充點

### 三份核心文件的分工

| 文件 | 層級 | 問題 | 變動頻率 |
|---|---|---|---|
| VISION.md | 產品 | 為什麼做、為誰做 | 極低 |
| ARCHITECTURE.md | 系統 | 整體長什麼樣（模組、部署、資料流） | 低 |
| DESIGN.md | 子系統／模組 | 這個部分怎麼設計、為什麼這樣選 | 中 |

---

## 二、完整 .md 檔案全景圖（按語境層級排列）

分層原則：越穩定的文件越應該被所有子代理讀到，越動態的文件越應該只餵給當前任務。這是控制 context window 壓力的核心策略。

### L1：方向層（極少變動，幾乎所有代理都該讀）

| 檔案 | 回答什麼 | 對 BeakCortex 的意義 |
|---|---|---|
| **VISION.md** | 為什麼做、為誰做、不做什麼 | 防止子代理把 Cortex 越改越像 LangGraph 或 AutoGen |
| **GLOSSARY.md** | 領域術語的精確定義 | 極度關鍵。Tenant、Agent、Subagent、Session、Memory、Artifact 在系統裡各有特定含義，不定義就幻覺 |
| **README.md** | 給人類（非 Claude）的入口 | 開源前的門面，Claude 讀它幫助不大 |

### L2：系統層（重大決策才改）

| 檔案 | 回答什麼 | 對 BeakCortex 的意義 |
|---|---|---|
| **ARCHITECTURE.md** | 整體長什麼樣：模組、部署、資料流 | 定義 Flask / PostgreSQL / tmux 代理拓撲 |
| **ADR/NNNN-*.md** | 某個決策為何這樣選、替代方案、取捨 | 資安產品必備。審計時要能回答「為什麼選 ltree 不選 Neo4j」 |
| **SECURITY.md** | 漏洞回報管道、支援版本 | 開源標配，GitHub 會自動識別 |
| **THREAT_MODEL.md** | 資產、威脅、信任邊界、緩解措施 | BeakCortex 特別需要：子代理可存取哪些資料？Prompt injection 邊界在哪？ |

### L3：子系統層（每個功能一份）

| 檔案 | 回答什麼 | 對 BeakCortex 的意義 |
|---|---|---|
| **DESIGN.md** | 某子系統怎麼設計、契約、Schema | 搭配 SPEC 系統，form.io ↔ JSONB ↔ SQL 三向同步的設計應該在這裡 |
| **SPEC.md** / `specs/*.md` | 單一功能的正式規格 | 既有的 SPEC 機制，是防幻覺的最強工具 |
| **API.md** / `openapi.yaml` | 對外介面契約 | PostgREST 混合架構時尤其重要 |

### L4：操作層（Claude 每次執行都讀）

| 檔案 | 回答什麼 | 對 BeakCortex 的意義 |
|---|---|---|
| **CLAUDE.md** | Claude Code 在這個 repo 的工作守則 | 最重要的一份。放編碼規範、禁止行為、指令慣例 |
| **AGENTS.md** | 多代理系統中每個 agent 的職責邊界 | 多代理協作必備：誰能寫 DB、誰只能讀、誰負責審查 |
| **.claude/commands/*.md** | 自訂斜線指令 | 如 /loop 等自動化指令 |
| **.claude/agents/*.md** | 子代理人格與工具限制 | 對應 tmux subagent 的角色分工 |
| **RUNBOOK.md** | 營運場景 playbook（備份、回滾、事故） | SOC 思維天然適合這份 |

### L5：動態層（會過期，謹慎餵給 Claude）

| 檔案 | 回答什麼 | 注意事項 |
|---|---|---|
| **PLAN.md** | 當前這次任務的執行計畫 | 用完即丟，避免進 git |
| **TODO.md** / **BACKLOG.md** | 待辦 | 容易過期誤導 Claude |
| **CHANGELOG.md** | 版本變更紀錄 | Claude 讀它通常浪費 token |
| **CONTEXT.md** / `SESSION.md` | 跨 session 延續的狀態 | PostgreSQL shared memory 已取代這個需求 |

---

## 三、彼此關係：Why → What → How → Now

```
VISION ──┐
         ├──► ARCHITECTURE ──► DESIGN/SPEC ──► CLAUDE/AGENTS ──► PLAN
ADR ─────┘         ▲                                  │
GLOSSARY ──────────┴──────────────────────────────────┘
THREAT_MODEL ─── 橫跨所有層的資安濾鏡
```

GLOSSARY 和 THREAT_MODEL 是橫切關注點，所有層都會引用。
ADR 是對 ARCHITECTURE / DESIGN 變動的理由備份。

---

## 四、對「資安 + vibe coding 的 BeakCortex」的關鍵建議

### 1. CLAUDE.md 必須有「Security Red Lines」段落

明確列出：絕對不能生成 eval、不能硬編碼 secret、所有 SQL 必須參數化、所有外部輸入必須經過 schema 驗證層。這比寫在聊天裡可靠得多，因為每個子代理都會讀到。

### 2. THREAT_MODEL.md 要定義「代理信任等級」

tmux subagent 架構裡，子代理能摸到 PostgreSQL 共享記憶體，等於給 LLM 一個可寫入的資料庫。威脅模型要明確：

- 哪些 table 是 read-only for agents
- 哪些寫入必須經過 human-in-the-loop
- prompt injection 從 WAF log 流進來時在哪一層被淨化

### 3. ADR 是未來的免責聲明

資安產品被稽核時，最致命的問題是「為什麼這裡沒有輸入驗證？」。ADR 把 vibe coding 階段的每個關鍵決策留下紀錄（含 Claude 當時的建議與你的判斷），日後能自證盡職。

建議格式：Context / Decision / Consequences / Alternatives Considered，每份不超過一頁。

### 4. GLOSSARY.md 是防幻覺的第一道牆

context 壓力導致幻覺的一大類是術語漂移 —— Claude 把 tenant 當成 multi-tenancy 概念，但在 BeakCortex 裡可能指某個資安事件的歸屬組織。一份精確的詞彙表能把這類錯誤消滅在根源。

### 5. AGENTS.md 取代口頭分工

多代理編排中，每個 agent 的「可呼叫工具、可讀 table、可寫 table、必須呼叫誰做 review」應該寫成結構化文件。這也直接對應未來做權限矩陣（ltree 權限繼承）的稽核需求。

---

## 五、實務起手式

優先建立以下三份文件（各一到兩頁），即可讓子代理產出品質明顯提升：

1. **CLAUDE.md** — 編碼守則 + Security Red Lines
2. **GLOSSARY.md** — BeakCortex 領域術語精確定義
3. **THREAT_MODEL.md** — 代理信任等級 + 資料存取邊界

這三份都是「寫一次，長期複利」的投資。
