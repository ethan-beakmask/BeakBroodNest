# Heptabase MVP - 類 Heptabase 知識白板系統

## 專案定位
Local 版類 Heptabase 知識白板，強調資料粒度到欄位層級的再利用。
未來將整合為 BeakMaskPlatform 模組。

## 技術棧
- 後端：Python Flask + SQLite
- 前端：Alpine.js + 純 JS（無 React）
- 連線渲染：SVG
- 埠號：5555

## 啟動方式
```bash
python3 app.py --serve           # 啟動（預設 port 5555）
python3 app.py --reset --serve   # 重置資料庫並啟動
```

## 核心架構
- **Schema**：使用者自訂表結構（欄位名稱、型別、選項）
- **Item**：依 schema 建立的資料列（EAV 模式儲存欄位值）
- **Card**：白板上的卡片，關聯多個 item（多對多）
- **Whiteboard**：白板，包含多張卡片與連線
- **Tag**：標籤/群組，用於卡片分類

## 資料庫
- SQLite，檔案：`heptabase.db`
- 9 張表：schemas, schema_fields, items, item_values, whiteboards, cards, card_items, tags, card_tags, connections
- EAV 模式支援動態 schema

## 預設模板
- 行事曆（calendar）
- 採購單（shopping-list）
- 開會前置準備（meeting-prep）

## 檔案結構
```
app.py              # Flask 入口 + 所有 API 路由
db.py               # SQLite 初始化
models.py           # 資料存取層
seed_templates.py   # 測試模板資料
templates/
  base.html         # 基礎模板
  index.html        # 白板主頁面
  schemas.html      # Schema 管理
  items.html        # Item CRUD
static/
  vendor/alpine.min.js
  css/main.css, whiteboard.css
  js/api.js, whiteboard.js
```
