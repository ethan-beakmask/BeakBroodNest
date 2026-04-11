# BeakNote -- 知識白板與 AI 共用知識庫

## 專案概述
- 路徑: /opt/BeakNote/
- 技術棧: Python Flask + PostgreSQL + SQLAlchemy + MCP SDK
- Port: 5170 (http://192.168.0.16:5170)
- DB: beak_note (user: beak_note, pw: postgres123)
- 規劃文件: docs/VISION.md
- 舊 MVP 參考: OLD/test9_Heptabase/

## 每次對話必做
1. 呼叫 `mcp__beak_note__note_overview` 取得知識庫概覽（原子數、標籤、最近更新、阻塞項目）
2. 呼叫 `mcp__beak_note__note_search` 搜尋 tag=「待辦」+ tag=「BeakNote」取得當前專案待辦
3. 根據知識庫回傳的內容理解專案狀態，不要重新掃描目錄結構
4. 若用戶指定任務，用 `note_get` 讀取對應原子的完整內容再開工
5. 完成任務後用 `note_update` 更新對應原子狀態，或用 `note_forget` 歸檔已完成項目

## 知識庫使用原則
- 新的設計決策、待辦、里程碑 -> `note_store` 存入知識庫
- 任務完成 -> `note_update` 更新內容，或 `note_forget` mode=archive 歸檔
- 建立因果關係 -> `note_relate`（blocks/follows/supports 等）
- 不要重複儲存已存在的知識，先 `note_search` 確認

## 目錄結構
```
core/               共用資料層（框架無關 SQLAlchemy）
  db.py             engine + session
  models.py         10 張表 ORM (知識原子)
  relations.py      因果鍊操作 + 阻塞追溯
human_ui/           人類介面 (Flask)
  app.py            API routes
ai_kb/              AI 知識庫介面
  mcp_server.py     MCP Server (10 知識工具 + 4 orchestrator 工具)
orchestrator/       多 Agent 協作框架
  models.py         worker_tasks + worker_reports ORM
  dispatcher.py     任務派發 (tmux window + claude -p)
  wrapper.sh        支線 claude process 包裝器
  collector.py      結果收集 (output -> worker_reports)
  relay.py          中間層 (MVP: passthrough，未來: 審查/匯整)
docs/               規劃文件
OLD/                舊 MVP 歸檔
```

## 啟動方式
```bash
source venv/bin/activate
python human_ui/app.py --serve            # Web API
python human_ui/app.py --init-db --seed   # 首次初始化
```
