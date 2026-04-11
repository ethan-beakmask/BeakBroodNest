# BeakCortex -- 知識白板與 AI 共用知識庫

> 建立日期：2026-04-09
> 狀態：規劃討論中（2026-04-09 第一輪討論完成，2026-04-10 追加因果卡控與應用場景）
> 前身：Ethan_Lab/test9_Heptabase（MVP）、FormFlow_legacy/a6 筆記平台計劃

---

## 1. 產品定位

**不是什麼**：不是 Heptabase 的競品，不是商業化產品

**是什麼**：給學術界與深度思考人士的第二腦，人類與 AI 共用的知識基礎設施

**核心信念**：
- 外觀與流暢度不能破壞思考（思考中的摩擦就是知識的損耗）
- 能找到才能再利用，能再利用才算知識
- 知識有生命週期，不是越多越好，失焦的資訊是噪音
- 人類的筆記與 AI 的記憶本質上是同一件事：結構化的知識紀錄

---

## 1.1 應用場景：Vibe Coding 開發管理

筆記整理和專案管理的行為模式是同構的：

| 階段 | 知識產出 | 軟體開發 |
|------|---------|---------|
| 起點 | 收斂或發散或記錄 | 目標明確或 MVP 試作 |
| 演化 | 就算沒偏離也會有新項目 | 通常會新增需求改規格 |
| 收束 | 發散的可結合（收斂） | 得收斂才能結案，好的 IDEA 另開 |
| 產出 | 多個收斂結果 + 進行中的筆記 | 多項產品 |

現有工具的盲區：
- **Trello/Kanban**：知道「什麼要做」，不知道「為什麼卡住」
- **Gantt/Project**：有依賴關係，但門檻高，非傳統程式設計師不會用
- **Obsidian/Notion**：記錄自由，但沒有因果卡控，筆記堆成山看不出阻塞點

BeakCortex 的因果鍊 + 時間軸 + `blocks` 關係 + lifecycle 狀態，天然能回答：
- **卡在哪** -- 哪些上游原子未完成
- **為什麼不開始** -- 追溯阻塞鍊的根節點
- **缺少什麼才能開始** -- 列出所有未完成的前置條件

Vibe coding 開發者（極大比例非傳統程式設計師）不需要學 Project，
只要在白板上記錄想法、拉因果線、標完成狀態，系統自動產生進度視圖。
資料模型是通用的，人類和 AI 只是存取介面不同。

---

## 2. 兩個專案，一個資料層

```
共用資料層（SQLite/PostgreSQL）
    |
    +-- Project A: 人類介面（白板/筆記 UI）
    |     - 視覺化操作：拖拉、連線、縮放
    |     - 引導 B -> C -> D 的思考過程
    |     - 不限定 Web，可考慮桌面應用
    |
    +-- Project B: AI 知識庫（取代 MEMORY.md / CLAUDE.md）
          - 結構化存取取代平面文字檔
          - 依知識生命週期決定檢索優先度
          - 因果鍊提供推理上下文，而非羅列事實
          - 減少 AI context 膨脹，保持清晰
```

**為什麼一開始就要共用資料結構**：
如果資料模型各做各的，日後整合成本遠大於設計成本。
人類寫的筆記與 AI 的記憶，差異只在 UI 和存取方式，底層的知識原子是同一種東西。

---

## 3. 筆記的本質分類

不是依軟體功能分類，是依思維模式分類：

| 代號 | 類型 | 代表工具 | 思維特徵 | 資料結構特徵 |
|------|------|----------|----------|------------|
| **A** | 萬用型 | 白紙+筆 | 最自由也最難 | 非結構化，混合媒體 |
| **B** | 創意發散型 | 心智圖、白板 | 從一點出發，發散，不需結論 | 樹/圖，弱連結 |
| **C** | 思考過程輔助型 | 流程圖、泳道圖 | 收斂，必須導向結果 | DAG（有向無環圖） |
| **D** | 總結歸納型 | 康乃爾筆記、麥肯錫 | 結論優先，有論據支撐 | 結構化文件，引用鍊 |
| **E** | 套表分類型 | Notion、會議記錄 | 填表式，結構先於內容 | Schema + EAV |
| **F** | 碎片型 | 卡片筆記、OneNote | 低結構，先記再說 | 鍵值對，自由標籤 |

**導引邏輯**（系統內建，不是強制）：

```
宏觀：白板（A）是容器，所有類型共存於白板上
微觀引導：B（發散）-> C（收斂）-> D（歸納）
                                     |
                                     v
若紀錄有結構 -> 套用 E 模板 -> 協助導向 D
若無結構     -> 降級為 F（碎片先累積）
```

**B, C, D 是因果鍊的建構基礎**：知識不是憑空存在，因果鍊是知識不是幻想的憑證。

---

## 4. 五大資料維度

### 4.1 再利用（Reusability）

- SQL 為主 base，所有知識原子必須可查詢
- 文字格式（.md, .json, .csv）為輔，確保可匯出
- EAV 模式保留（舊 MVP 已驗證），支援動態 schema
- 同一份資料可出現在多個白板、多個上下文中（引用而非複製）

### 4.2 搜尋分類（Search & Classification）

- 傳統：標籤 + 屬性 + 分類法（圖書館式）
- 進階：全文搜尋 + schema 欄位查詢
- AI 層：語意搜尋（embedding + 向量相似度）
- 結合自建 LLM 知識庫，人類與 AI 共用同一套分類

### 4.3 時間軸（Timeline）

- 每筆知識原子記錄：建立時間、修改時間、最後存取時間、存取次數
- 時間軸視圖：知識演變的脈絡，而非只是靜態快照
- 為知識生命週期評估提供數據基礎

### 4.4 因果鍊（Causal Chain）

與一般筆記工具的「連結」最大差異：連線有方向性和語意

| 關係類型 | 說明 | 範例 |
|----------|------|------|
| `causes` | 因果 | A 導致了 B |
| `supports` | 支持 | 證據 X 支持結論 Y |
| `contradicts` | 矛盾 | 發現 A 與假設 B 矛盾 |
| `derives_from` | 衍生 | 想法 B 從觀察 A 衍生 |
| `follows` | 流程順序 | 步驟 1 之後是步驟 2 |
| `contains` | 包含 | 群組/章節包含子項 |
| `refutes` | 否定 | 新證據推翻舊結論 |
| `blocks` | 阻塞（因果卡控） | 任務 A 未完成前，任務 B 無法開始 |

這些關係構成知識圖譜，不是Obsidian那種所有邊等權的graph。

**因果卡控（blocks）**：類似甘特圖的依賴線，但嵌入知識圖譜中。
當一個原子的所有 `blocks` 上游都進入 archived（完成），該原子才「可開始」；
任一上游仍為 active 或更早狀態，該原子即為「阻塞中」，且系統能回答：
- 卡在哪 -- 哪些上游未完成
- 為什麼不開始 -- 追溯阻塞鍊的根節點
- 缺少什麼才能開始 -- 列出所有未完成的前置條件

### 4.5 知識生命終止（Knowledge End-of-Life）

知識不是永恆的。系統主動追蹤生命狀態：

```
active（活躍）-> aging（老化）-> archived（歸檔）-> terminal（終止）
```

**評估指標**：
- 再利用率：被引用/存取的頻率
- 時間衰減：距最後存取的時間
- 因果鍊活性：上下游關聯的知識是否仍 active
- 矛盾標記：是否已被更新的知識 `refutes`

**UI 行為**：
- active：正常顯示，搜尋優先
- aging：視覺弱化（降低對比度），搜尋次優先
- archived：不主動顯示，搜尋可達
- terminal：僅在明確搜尋時顯示，標記為「已過時」

**與 Obsidian 的根本差異**：Obsidian 那坨 edge 把所有筆記等價呈現，活的死的全擠在一起，失焦。BeakCortex 讓活的知識凸顯，死的知識退場但不消失。

---

## 5. 共用資料模型（草案）

### 5.1 核心表：知識原子（knowledge_atoms）

每一筆紀錄就是一個最小知識單位。

```sql
CREATE TABLE knowledge_atoms (
    id SERIAL PRIMARY KEY,

    -- 內容
    title TEXT NOT NULL DEFAULT '',
    content TEXT DEFAULT '',
    content_type TEXT DEFAULT 'markdown',
        -- markdown, text, checklist, table, image_ref, url, media_ref, ai_io

    -- 分類
    atom_type TEXT NOT NULL DEFAULT 'F',
        -- A=萬用, B=發散, C=流程, D=歸納, E=套表, F=碎片
    schema_id INTEGER REFERENCES atom_schemas(id),
        -- E 類型時關聯的 schema

    -- 生命週期
    lifecycle TEXT DEFAULT 'active',
        -- active, aging, archived, terminal
    vitality_score REAL DEFAULT 1.0,
        -- 系統計算：綜合再利用率、時間衰減、因果鍊活性

    -- 時間軸
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    last_accessed_at TIMESTAMP DEFAULT NOW(),
    access_count INTEGER DEFAULT 0,

    -- 來源追蹤
    source TEXT DEFAULT 'human',
        -- human, ai, import, derived
    source_detail TEXT DEFAULT '',
        -- AI 模型名稱、匯入來源、衍生自哪個 atom 等

    -- 軟刪除
    is_deleted BOOLEAN DEFAULT FALSE
);
```

### 5.2 因果鍊（atom_relations）

```sql
CREATE TABLE atom_relations (
    id SERIAL PRIMARY KEY,
    from_atom_id INTEGER NOT NULL REFERENCES knowledge_atoms(id),
    to_atom_id INTEGER NOT NULL REFERENCES knowledge_atoms(id),
    relation_type TEXT NOT NULL,
        -- causes, supports, contradicts, derives_from,
        -- follows, contains, refutes, blocks
    label TEXT DEFAULT '',
    confidence REAL DEFAULT 1.0,
        -- 0.0~1.0，AI 產生的關聯可標註信心度
    created_by TEXT DEFAULT 'human',
        -- human, ai, system
    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(from_atom_id, to_atom_id, relation_type)
);
```

### 5.3 白板定位（僅 Project A 使用）

```sql
-- 白板
CREATE TABLE canvases (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    canvas_type TEXT DEFAULT 'whiteboard',
        -- whiteboard, mindmap, flowchart, cornell, template
    viewport_x REAL DEFAULT 0,
    viewport_y REAL DEFAULT 0,
    viewport_zoom REAL DEFAULT 1.0,
    settings TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 原子在白板上的位置（多對多：同一原子可出現在多個白板）
CREATE TABLE canvas_atoms (
    id SERIAL PRIMARY KEY,
    canvas_id INTEGER NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
    atom_id INTEGER NOT NULL REFERENCES knowledge_atoms(id) ON DELETE CASCADE,
    pos_x REAL NOT NULL DEFAULT 0,
    pos_y REAL NOT NULL DEFAULT 0,
    width REAL,
    height REAL,
    z_index INTEGER DEFAULT 0,
    visual_style TEXT DEFAULT '{}',
        -- 卡片在此白板上的視覺覆寫（顏色、邊框等）
    UNIQUE(canvas_id, atom_id)
);

-- 白板上的視覺連線（引用 atom_relations 或獨立的視覺線）
CREATE TABLE canvas_connections (
    id SERIAL PRIMARY KEY,
    canvas_id INTEGER NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
    source_atom_id INTEGER NOT NULL,
    target_atom_id INTEGER NOT NULL,
    relation_id INTEGER REFERENCES atom_relations(id),
        -- 若關聯底層 atom_relation 則填入，純視覺線則 NULL
    line_style TEXT DEFAULT 'bezier',
    color TEXT DEFAULT '#3b82f6',
    label TEXT DEFAULT '',
    animated BOOLEAN DEFAULT FALSE
);
```

### 5.4 動態 Schema（E 類型用）

```sql
-- 繼承舊 MVP 的 EAV 模式
CREATE TABLE atom_schemas (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    icon TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE schema_fields (
    id SERIAL PRIMARY KEY,
    schema_id INTEGER NOT NULL REFERENCES atom_schemas(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    label TEXT NOT NULL,
    field_type TEXT NOT NULL,
        -- text, number, date, select, multiselect, checkbox, url, relation
    options TEXT DEFAULT '',
    sort_order INTEGER DEFAULT 0,
    required BOOLEAN DEFAULT FALSE
);

CREATE TABLE atom_field_values (
    id SERIAL PRIMARY KEY,
    atom_id INTEGER NOT NULL REFERENCES knowledge_atoms(id) ON DELETE CASCADE,
    field_id INTEGER NOT NULL REFERENCES schema_fields(id) ON DELETE CASCADE,
    value TEXT,
    UNIQUE(atom_id, field_id)
);
```

### 5.5 分類系統

```sql
CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    color TEXT DEFAULT '#6b7280',
    parent_tag_id INTEGER REFERENCES tags(id),
        -- 支援階層式標籤
    tag_type TEXT DEFAULT 'tag',
        -- tag（分類）, group（視覺群組）, domain（知識領域）
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE atom_tags (
    atom_id INTEGER NOT NULL REFERENCES knowledge_atoms(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY(atom_id, tag_id)
);
```

### 5.6 AI 知識庫擴充（Project B 用）

```sql
-- AI 上下文會話（取代 MEMORY.md 的角色）
CREATE TABLE ai_contexts (
    id SERIAL PRIMARY KEY,
    context_type TEXT NOT NULL,
        -- user（用戶資訊）, feedback（行為指引）,
        -- project（專案狀態）, reference（外部資源）
        -- 對應目前 MEMORY.md 的 type 分類
    summary TEXT NOT NULL,
        -- 簡短摘要，相當於 MEMORY.md 的 description
    atom_id INTEGER REFERENCES knowledge_atoms(id),
        -- 指向完整內容的知識原子
    priority REAL DEFAULT 0.5,
        -- 檢索優先度，由 vitality_score + 相關性計算
    last_used_at TIMESTAMP DEFAULT NOW(),
    use_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE
);

-- 向量嵌入（語意搜尋用）
CREATE TABLE atom_embeddings (
    id SERIAL PRIMARY KEY,
    atom_id INTEGER NOT NULL REFERENCES knowledge_atoms(id) ON DELETE CASCADE,
    embedding vector NOT NULL,
        -- pgvector 向量型別
    model_name TEXT NOT NULL,
        -- 產生嵌入的模型
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(atom_id, model_name)
);
```

---

## 6. 與舊 MVP 的繼承關係

| 舊 MVP 概念 | 新系統對應 | 變化 |
|-------------|-----------|------|
| Schema | atom_schemas | 直接繼承，幾乎不變 |
| schema_fields | schema_fields | 直接繼承 |
| Item | knowledge_atoms (type=E) | 從獨立實體升級為知識原子的一種 |
| item_values | atom_field_values | 改名，結構相同 |
| Card | canvas_atoms | 從實體變為「原子在白板上的投影」 |
| Whiteboard | canvases | 增加 canvas_type |
| Connection | atom_relations + canvas_connections | 拆分為語意層與視覺層 |
| Tag | tags | 增加階層與 tag_type |

**關鍵架構變化**：
- 舊：Item -> Card -> Whiteboard（內容綁定在卡片上）
- 新：knowledge_atom 是獨立實體，canvas_atoms 只是它在某個白板上的投影
- 同一個知識原子可以同時出現在 5 個白板上，位置不同但內容同步

---

## 7. 舊開發計劃狀態盤點

### FormFlow 筆記平台計劃（2024-12-15）
- Phase 1~4 全部未實作，僅有 canvas-demo.html 概念驗證
- 技術選型決策仍有效：純 JS + SVG，不引入 React
- 資料模型需重新設計（已整合至上方 Section 5）
- 原計劃與 FormFlow RBAC 整合的部分，本專案不需要

### Heptabase MVP（test9_Heptabase）
- 完整可運行的原型，EAV 模式驗證成功
- 程式碼可作為 data access layer 的參考（models.py 的 SQL pattern）
- 前端 Alpine.js + SVG 連線的實作可部分復用
- 資料庫 schema 需升級（增加 lifecycle、relation_type 等）

---

## 8. 待討論事項

### 8.1 確認理解

以下是我對幾個概念的理解，請確認或修正：

**知識生命終止**：知識有保鮮期。「Python 2 的寫法」在 2026 年是 terminal，
不該跟「Python 3.12 新特性」搶搜尋排名。系統用 vitality_score 量化這件事，
UI 讓活的知識凸顯、死的退場。

**因果鍊**：Obsidian 的雙向連結只知道「A 和 B 有關」，
BeakCortex 的連結知道「A 導致了 B」「C 反駁了 A」。
這讓知識不只是一堆節點的圖，而是有推理脈絡的論證網絡。
B(發散) -> C(收斂) -> D(歸納) 的過程本身就是因果鍊的建構過程。

**人類與 AI 共用知識庫**：
目前 Claude 的 MEMORY.md 是平面文字，150 行就要截斷，
而且每次對話都要全量載入。如果改成 SQL，AI 可以按需查詢，
只拉取與當前任務相關的知識原子，context window 不再被歷史記憶塞滿。
人類在白板上整理的知識，AI 直接可查詢使用，反之亦然。

### 8.2 架構決策（2026-04-09 已確認）

1. **資料庫選擇：PostgreSQL**
   - 人類 UI + AI 會同時讀寫，SQLite 單寫入鎖是硬傷
   - 全文搜尋（tsvector + pg_trgm）、向量搜尋（pgvector）生態成熟
   - JSONB 原生支援、遞迴 CTE + lateral join 更適合知識圖譜查詢
   - 開發初期可用 SQLite 快速原型驗證，正式版 PostgreSQL

2. **UI 技術：Web 優先**
   - Flask + Alpine.js + 純 JS + SVG，繼承舊 MVP 路線
   - Web 效能較差但資源多，確認採用
   - 未來可考慮桌面封裝但非優先

3. **AI 知識庫介面：MCP Server**
   - Claude Code 直接獲得 knowledge_search / knowledge_store / knowledge_relate 等原生工具
   - 不需繞 Bash/curl，不需解析輸出
   - 從「每次對話全量載入 MEMORY.md」變成「按需查詢相關知識原子」
   - 大幅減少 context window 佔用

4. **向量搜尋：pgvector**
   - 配合 PostgreSQL 決策，使用 pgvector 擴充
   - 單一資料來源，不額外引入向量 DB

### 8.3 相關脈絡

- **Karpathy AutoResearch**（2026-03-20 討論）：agent 透過 program.md 引導行為，
  迭代實驗保留進步丟棄退步。啟發：AI 知識庫的 context_type 類似 program.md 的角色，
  結構化指令取代平面文字檔，且知識生命週期的 vitality_score 就是「保留進步丟棄退步」的知識版

### 8.3 開發優先順序建議

```
Phase 0: 資料層（兩個專案的共同基礎）
  - knowledge_atoms + atom_relations + tags 核心表
  - 基本 CRUD API
  - 從舊 MVP 遷移 seed 資料驗證

Phase 1A: 人類介面基礎
  - 白板渲染（原子卡片 + SVG 連線）
  - 拖拉、縮放、平移
  - B/C/D 類型的視覺區分

Phase 1B: AI 知識庫基礎
  - MCP Server：存/取/查 知識原子
  - 取代 MEMORY.md 的讀寫流程
  - 基本全文搜尋

Phase 2: 知識生命週期
  - vitality_score 計算邏輯
  - lifecycle 狀態轉換
  - UI 的視覺弱化/退場效果

Phase 3: 因果鍊
  - 有向連線 UI（relation_type 選擇）
  - 因果鍊視圖（從任意原子展開上下游）
  - AI 自動建議關聯

Phase 4: 深度整合
  - 語意搜尋（embedding）
  - AI 輔助分類（自動判斷 atom_type）
  - 知識導引（B->C->D 提示）
```

---

## 9. 目錄結構（預想）

```
/opt/BeakCortex/
  OLD/                      # 舊檔案歸檔
  docs/                     # 規劃文件
    VISION.md               # 本文件
  core/                     # 共用資料層（Python package）
    db.py                   # 資料庫初始化
    models.py               # 知識原子 CRUD
    relations.py            # 因果鍊操作
    lifecycle.py            # 生命週期計算
    search.py               # 搜尋引擎
  human_ui/                 # Project A: 人類介面
    app.py                  # Flask 入口
    static/
    templates/
  ai_kb/                    # Project B: AI 知識庫
    cli.py                  # 命令列工具
    mcp_server.py           # MCP 伺服器（供 Claude Code 使用）
    context_manager.py      # 上下文管理
```
