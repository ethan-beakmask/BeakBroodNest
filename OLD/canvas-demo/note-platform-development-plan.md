# 筆記平台開發計劃

> 建立日期：2024-12-15
> 狀態：規劃中

---

## 1. 核心理念

### 1.1 設計原則

**資料再利用優先**：不被專有格式綁定，所有資料都能匯出成通用格式。

### 1.2 支援的資料格式

| 格式 | 用途 |
|------|------|
| Markdown | 主要內容格式 |
| CSV / Excel | 結構化資料 |
| JSON | 資料交換、匯出匯入 |
| Text | 純文字 |
| SQL DB | 底層儲存 |

### 1.3 核心概念

```
「心智圖不是獨立功能，而是連線整理乾淨後的白板」
```

- **白板**是基礎容器
- **卡片**是內容單位
- **關聯**是卡片之間的連線
- 心智圖 = 整理好的白板（樹狀連線結構）
- 同一張白板可同時存在：多組心智圖 + 未歸類卡片

---

## 2. 資料模型

### 2.1 資料庫結構

```sql
-- 白板
CREATE TABLE canvases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    secure_code VARCHAR(32) UNIQUE NOT NULL,
    org_secure_code VARCHAR(32) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    thumbnail TEXT,                    -- Base64 縮圖
    settings JSONB DEFAULT '{}',       -- 畫布設定（背景色、網格等）
    is_deleted BOOLEAN DEFAULT FALSE,
    created_by INTEGER,
    updated_by INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 卡片
CREATE TABLE cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    secure_code VARCHAR(32) UNIQUE NOT NULL,
    canvas_id UUID NOT NULL REFERENCES canvases(id),

    -- 內容
    title VARCHAR(255),
    content TEXT,                      -- Markdown / 純文字
    content_type VARCHAR(20) DEFAULT 'markdown',  -- markdown, text, checklist, table

    -- 位置與尺寸
    x FLOAT NOT NULL DEFAULT 0,
    y FLOAT NOT NULL DEFAULT 0,
    width FLOAT,
    height FLOAT,
    z_index INTEGER DEFAULT 10,

    -- 屬性
    card_type VARCHAR(20) DEFAULT 'card',  -- card, plan, group, mindmap-root, mindmap-branch, mindmap-leaf
    properties JSONB DEFAULT '{}',     -- 標籤、顏色、樣式等

    -- 群組關係（用於 group 類型卡片包含其他卡片）
    parent_card_id UUID REFERENCES cards(id),

    is_deleted BOOLEAN DEFAULT FALSE,
    created_by INTEGER,
    updated_by INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 關聯（連線）
CREATE TABLE connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canvas_id UUID NOT NULL REFERENCES canvases(id),
    from_card_id UUID NOT NULL REFERENCES cards(id),
    to_card_id UUID NOT NULL REFERENCES cards(id),

    -- 連線屬性
    label VARCHAR(255),
    color VARCHAR(20) DEFAULT '#3b82f6',
    line_type VARCHAR(20) DEFAULT 'bezier',  -- bezier, straight, step
    arrow_start BOOLEAN DEFAULT FALSE,
    arrow_end BOOLEAN DEFAULT FALSE,
    animated BOOLEAN DEFAULT FALSE,
    dashed BOOLEAN DEFAULT FALSE,

    properties JSONB DEFAULT '{}',

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_cards_canvas_id ON cards(canvas_id);
CREATE INDEX idx_connections_canvas_id ON connections(canvas_id);
CREATE INDEX idx_canvases_org ON canvases(org_secure_code);
```

### 2.2 卡片類型

| card_type | 說明 | 視覺樣式 |
|-----------|------|----------|
| `card` | 一般卡片 | 白色圓角方塊 |
| `plan` | 計劃單（2層結構） | 紫色標題 + 區段列表 |
| `group` | 群組框 | 藍色虛線框 |
| `mindmap-root` | 心智圖根節點 | 橘色圓形 |
| `mindmap-branch` | 心智圖分支 | 橘色膠囊 |
| `mindmap-leaf` | 心智圖葉節點 | 淡黃色方塊 |

### 2.3 JSON 匯出格式

```json
{
  "canvas": {
    "id": "uuid",
    "name": "我的白板",
    "settings": {}
  },
  "cards": [
    {
      "id": "card-1",
      "type": "card",
      "title": "專案構想",
      "content": "# 標題\n\n內容...",
      "content_type": "markdown",
      "position": { "x": 100, "y": 50 },
      "properties": {
        "tags": ["構想", "重要"],
        "color": "#3b82f6"
      }
    }
  ],
  "connections": [
    {
      "id": "conn-1",
      "from": "card-1",
      "to": "card-2",
      "label": "相關"
    }
  ]
}
```

---

## 3. 技術架構

### 3.1 系統定位

```
FormFlow 系統
├── 工作流設計器 → Cytoscape.js（維持現狀）
├── 其他頁面 → Jinja2 + Alpine.js（維持現狀）
└── 知識白板 → 純 JS + HTML + SVG（新增）
```

### 3.2 技術選型

| 層面 | 技術 | 說明 |
|------|------|------|
| 後端 | Flask + SQLAlchemy | 利用現有架構 |
| 資料庫 | PostgreSQL | 利用現有資料庫 |
| 前端畫布 | **純 JavaScript** | 不引入 React |
| 節點渲染 | HTML `<div>` | 可包含任意內容 |
| 連線渲染 | SVG `<path>` | 貝茲曲線 |
| 互動 | 原生 JS 事件 | 拖拉、縮放、平移 |
| 權限控管 | 現有 RBAC | 利用現有系統 |

### 3.3 不採用 React Flow 的原因

- 避免引入 React 造成技術棧分裂
- 現有系統已是 Alpine.js + Jinja2
- 純 JS 實現已足夠滿足需求
- 降低維護複雜度

### 3.4 前端架構

```
frontend/
├── templates/
│   └── canvas/
│       ├── index.html          # 白板列表
│       └── editor.html         # 白板編輯器
├── static/
│   ├── js/
│   │   └── canvas/
│   │       ├── canvas-core.js      # 畫布核心（縮放、平移）
│   │       ├── canvas-nodes.js     # 節點渲染與拖拉
│   │       ├── canvas-connections.js # 連線渲染
│   │       ├── canvas-toolbar.js   # 工具列
│   │       └── canvas-export.js    # 匯出功能
│   └── css/
│       └── canvas.css          # 白板樣式
```

### 3.5 後端 API

```
backend/app/api/canvas.py

GET    /api/canvas/                    # 白板列表
POST   /api/canvas/                    # 新增白板
GET    /api/canvas/<id>                # 取得白板（含所有卡片與連線）
PUT    /api/canvas/<id>                # 更新白板設定
DELETE /api/canvas/<id>                # 刪除白板

POST   /api/canvas/<id>/cards          # 新增卡片
PUT    /api/canvas/<id>/cards/<card_id>  # 更新卡片
DELETE /api/canvas/<id>/cards/<card_id>  # 刪除卡片

POST   /api/canvas/<id>/connections    # 新增連線
DELETE /api/canvas/<id>/connections/<conn_id>  # 刪除連線

GET    /api/canvas/<id>/export         # 匯出 JSON
POST   /api/canvas/import              # 匯入 JSON
GET    /api/canvas/<id>/export/markdown  # 匯出 Markdown（每張卡片一個檔案）
```

---

## 4. 功能規劃

### 4.1 Phase 1：基礎功能

- [ ] 資料庫模型建立
- [ ] 基礎 API（CRUD）
- [ ] 畫布渲染（節點 + 連線）
- [ ] 節點拖拉移動
- [ ] 畫布縮放與平移
- [ ] 新增/刪除卡片
- [ ] 新增/刪除連線

### 4.2 Phase 2：編輯功能

- [ ] 卡片內容編輯（Markdown）
- [ ] 卡片標題編輯
- [ ] 卡片樣式設定（顏色、標籤）
- [ ] 群組功能（框選多個卡片）
- [ ] 連線標籤編輯

### 4.3 Phase 3：匯入匯出

- [ ] JSON 匯出
- [ ] JSON 匯入
- [ ] Markdown 匯出（每卡片一檔）
- [ ] CSV 匯出（卡片列表）

### 4.4 Phase 4：進階功能

- [ ] 搜尋功能
- [ ] 標籤篩選
- [ ] 白板縮圖預覽
- [ ] 歷史紀錄（undo/redo）
- [ ] 快捷鍵支援

---

## 5. 與現有系統的整合

### 5.1 權限控管

- 利用現有 `org_secure_code` 實現多租戶隔離
- 利用現有 `created_by` / `updated_by` 追蹤使用者
- 利用現有角色權限控制存取

### 5.2 側邊選單整合

在現有選單中新增「知識白板」入口。

### 5.3 Form.io 整合（可選）

未來可考慮將 Form.io 用於：
- 結構化資料表（類似 Notion Database）
- 卡片內嵌入表單

---

## 6. Demo 頁面

已建立概念驗證 demo：

```
/dev/canvas-demo
```

展示內容：
- 白板區（群組框 + 3 張卡片）
- 心智圖區（根節點 + 分支 + 葉節點）
- 計劃單節點（2 層結構）
- 跨區關聯線

技術實現：
- 純 JavaScript（無外部框架）
- HTML `<div>` 節點
- SVG 貝茲曲線連線
- 原生拖拉與縮放

---

## 7. 參考資料

### 7.1 類似產品

| 產品 | 特色 |
|------|------|
| Heptabase | 白板式知識管理 |
| Miro | 協作白板 |
| Obsidian Canvas | 筆記白板整合 |
| XMind | 心智圖 |
| Notion | 結構化資料庫 |

### 7.2 評估過的技術方案

| 方案 | 結論 |
|------|------|
| React Flow | 功能強但需引入 React，放棄 |
| tldraw | 商用授權問題，放棄 |
| Excalidraw | 手繪風格，卡片內容受限，放棄 |
| Cytoscape.js | 已用於工作流，但節點內容受限 |
| **純 JS + SVG** | 採用，最符合現有架構 |

---

## 8. 待討論事項

- [ ] 是否需要即時協作功能？
- [ ] Markdown 編輯器選型（Tiptap? Milkdown? CodeMirror?）
- [ ] 是否需要離線支援？
- [ ] 行動裝置支援程度？

---
##note
/dev/canvas-demo

## 變更紀錄

| 日期 | 變更內容 |
|------|----------|
| 2024-12-15 | 初版建立，確定核心理念與技術選型 |
