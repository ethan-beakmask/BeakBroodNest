# BeakBroodNest → BroodNest 改名任務

## 背景與決策

- 原名 BeakBroodNest 與 Palo Alto Networks 的 Cortex 系列產品有商標爭議風險（公開前發現）
- 經過撞名工具篩選與 USPTO 人工查證，選定新名 **BroodNest**
- 改名範圍：**整個 /opt/BeakBroodNest/ 專案** + 全域 CLAUDE.md 中本專案相關段落 + 資料庫 + 系統服務
- **不在本次範圍**：其他 Beak 系列專案（BeakPlatform / BeakGuard / BeakSeal / BeakMeshWall / BeakGantt）、GitHub 遠端倉庫（下階段評估清理 git history 一併處理）

## 過去教訓

從 BeakNote → BeakBroodNest 那次只改了部分檔案，遺漏 DB / *.md / changelog，導致 Claude Code 在後續對話中混用兩個名詞造成幻覺。**這次必須一次到位**：local 全改、DB 全改、文件全改、配置全改。

---

## 字串替換對照（case-sensitive）

| 舊 | 新 | 出現場景 |
|---|---|---|
| `BeakBroodNest` | `BroodNest` | PascalCase，文件、code 字串、檔案名 |
| `beakbroodnest` | `broodnest` | 小寫，systemd service 名、URL path |
| `beak_broodnest` | `brood_nest` | snake_case，DB name、DB user、MCP server name |
| `beak-broodnest` | `brood-nest` | kebab-case（如有） |
| `BEAK_BROODNEST` | `BROOD_NEST` | 環境變數、常數（如有） |
| `Beak BroodNest` | `Brood Nest` | 含空格的人類可讀版（如有） |

**重要**：只能替換**完整 token**，不可盲目把 `Beak` 全替換掉（會誤傷其他 Beak 系列描述）。

---

## 影響範圍清單

### A. 專案檔案 `/opt/BeakBroodNest/`

需要全文替換的檔案類型：
- 所有 `*.py` `*.go` `*.sh` `*.sql` `*.md` `*.ini` `*.yaml` `*.yml` `*.json` `*.html` `*.js` `*.css` `*.toml` `*.conf`
- `CHANGELOG.md`（必改）
- `CLAUDE.md`（專案根目錄，必改）
- 所有 `docs/*.md`
- 所有 `tools/*.py` 與其註解
- `orchestrator/` 與 `core/` 與 `human_ui/` 與 `ai_kb/` 全部子目錄
- 任何含 `BeakBroodNest` 字串的 .gitignore / .env.example / config.ini.example

排除：
- `.git/` 內部檔（git 自己處理）
- `venv/` `node_modules/` `__pycache__/`（執行時產物）
- `OLD/`（不入版控的舊參考）
- `data/` 內的二進位資料

### B. 資料庫 PostgreSQL

需要動三層：

1. **DB user 改名**：
   ```sql
   ALTER USER beak_broodnest RENAME TO brood_nest;
   ```

2. **DB 改名**（執行前確認無連線）：
   ```sql
   ALTER DATABASE beak_broodnest RENAME TO brood_nest;
   ```

3. **DB 內容字串替換**（atoms 與 tags 內含 BeakBroodNest 字樣）：
   ```sql
   -- 在 brood_nest DB 內執行
   UPDATE knowledge_atoms SET title = replace(title, 'BeakBroodNest', 'BroodNest')
     WHERE title LIKE '%BeakBroodNest%';
   UPDATE knowledge_atoms SET content = replace(content, 'BeakBroodNest', 'BroodNest')
     WHERE content LIKE '%BeakBroodNest%';
   UPDATE knowledge_atoms SET content = replace(content, 'beak_broodnest', 'brood_nest')
     WHERE content LIKE '%beak_broodnest%';
   UPDATE tags SET name = 'BroodNest' WHERE name = 'BeakBroodNest';
   -- 視需要對 worker_reports / worker_inbox / canvas / 其他 text 欄位重複
   ```

   執行前用 `pg_dump beak_broodnest > /tmp/beakbroodnest_backup_$(date +%Y%m%d).sql` 完整備份。

### C. MCP 配置 `/opt/.mcp.json`

- server name `beak_broodnest` → `brood_nest`
- command 路徑 `/opt/BeakBroodNest/...` → `/opt/BroodNest/...`
- 改完後所有 MCP tool prefix 由 `mcp__beak_broodnest__*` 自動變成 `mcp__brood_nest__*`

### D. Systemd Service

- 檔案 `/etc/systemd/system/beakbroodnest.service` → `/etc/systemd/system/broodnest.service`
- 內容中 `WorkingDirectory` `ExecStart` 等路徑都改
- `sudo systemctl daemon-reload` + 重新 enable

### E. Nginx 配置

- 找到 `/etc/nginx/sites-available/` 或 `/etc/nginx/conf.d/` 中含 BeakBroodNest / beakbroodnest 的 server 或 location block
- URL path（如 `/beakbroodnest/`）改為 `/broodnest/`（如有）
- `proxy_pass` 仍指向 127.0.0.1:5171（port 不變）
- `nginx -t && systemctl reload nginx`

### F. 全域 `~/.claude/CLAUDE.md`

**只動 BeakBroodNest 相關段落**，其他 Beak 系列專案描述保留：

- 「### BeakBroodNest（知識白板與 AI 共用知識庫）」整段改為 BroodNest
- 「**MCP Server**: `beak_broodnest`」改為 `brood_nest`
- 「## Auto Memory 覆蓋指令」段落內所有 BeakBroodNest / beak_broodnest 引用改名
- 其他段落如 BeakPlatform / BeakGuard 不動

### G. 目錄重命名（最後一步）

```bash
sudo systemctl stop broodnest.service   # 改名後的 service
mv /opt/BeakBroodNest /opt/BroodNest
sudo systemctl start broodnest.service
```

### H. Git Remote

- forgejo origin (`http://192.168.0.16:3000/forgejoadmin/BeakBroodNest.git`)：建議在 forgejo Web UI 把倉庫改名為 BroodNest，然後 `git remote set-url origin http://192.168.0.16:3000/forgejoadmin/BroodNest.git`
- GitHub remote (`github.com/ethan-beakmask/BeakBroodNest.git`)：**本階段不動**（用戶決定下階段一併評估清理 git history）

---

## 執行順序（嚴格依序）

1. **備份**
   - `pg_dump beak_broodnest > /tmp/beakbroodnest_backup_$(date +%Y%m%d_%H%M).sql`
   - `tar czf /tmp/beakbroodnest_files_$(date +%Y%m%d_%H%M).tar.gz --exclude=venv --exclude=node_modules --exclude=__pycache__ /opt/BeakBroodNest/`
   - 確認備份檔可讀（`pg_restore --list` / `tar tzf | head`）

2. **停服務**
   - `sudo systemctl stop beakbroodnest.service`
   - 確認沒有 process 占用：`ss -tlnp | grep 5171`

3. **替換專案檔案內字串**（在 `/opt/BeakBroodNest/` 內，依字串長度由長到短依序執行避免互相覆蓋）：
   ```bash
   cd /opt/BeakBroodNest
   # 找出含舊字串的檔案
   grep -rIl --exclude-dir=.git --exclude-dir=venv --exclude-dir=node_modules \
     --exclude-dir=__pycache__ --exclude-dir=OLD --exclude-dir=data \
     -E 'BeakBroodNest|beakbroodnest|beak_broodnest|beak-broodnest|BEAK_BROODNEST' .
   # 逐個檔用 sed 取代（或 Edit tool）
   # 順序：BeakBroodNest → beakbroodnest → beak_broodnest → beak-broodnest → BEAK_BROODNEST
   ```

4. **DB 改名與內容替換**（依 B 段步驟）

5. **更新 `/opt/.mcp.json`**

6. **建立新 systemd service `broodnest.service`**，停用並刪除 `beakbroodnest.service`

7. **更新 nginx config + reload**

8. **更新全域 `~/.claude/CLAUDE.md`**（只動 BeakBroodNest 段落）

9. **目錄改名**：`mv /opt/BeakBroodNest /opt/BroodNest`

10. **重啟服務 + MCP**：
    - `sudo systemctl daemon-reload && sudo systemctl enable --now broodnest.service`
    - 在新對話中確認 MCP tool 已是 `mcp__brood_nest__*` 前綴

11. **驗證**（見下節）

12. **commit + push origin**（forgejo）。GitHub remote 本階段**不 push**。

---

## 驗證步驟

執行完所有改名後逐項確認：

1. **服務起得來**：`systemctl status broodnest.service` active running
2. **網頁可達**：瀏覽器開 http://192.168.0.16:5170/ 載入 BroodNest 介面
3. **MCP 可用**：在新 Claude 對話中執行 `note_overview`，回傳資料正常
4. **DB 完整**：
   - `psql -U brood_nest -d brood_nest -c "SELECT count(*) FROM knowledge_atoms;"` 數量與改名前一致
   - `... -c "SELECT count(*) FROM tags WHERE name='BroodNest';"` 為 1
   - `... -c "SELECT count(*) FROM tags WHERE name='BeakBroodNest';"` 為 0
5. **無殘留字串**：
   ```bash
   cd /opt/BroodNest
   grep -rI --exclude-dir=.git --exclude-dir=venv --exclude-dir=node_modules \
     --exclude-dir=OLD --exclude-dir=data \
     -E 'BeakBroodNest|beakbroodnest|beak_broodnest' . | grep -v 'RENAME_TO_BROODNEST.md' | grep -v CHANGELOG.md
   ```
   只有 RENAME 文件與 CHANGELOG 應該還留有歷史名（這兩個檔本來就要保留歷史紀錄）
6. **全域 CLAUDE.md 無殘留**：`grep -E 'BeakBroodNest|beak_broodnest' ~/.claude/CLAUDE.md` 回空
7. **跨機 relay 仍可用**：執行一次 notify_windows.py 確認 token 與設定無誤

---

## 風險與回滾

| 風險 | 對策 |
|---|---|
| DB rename 失敗（有連線占用） | 確保 systemd service 已停，`SELECT pid, application_name FROM pg_stat_activity WHERE datname='beak_broodnest';` 沒有殘餘連線 |
| sed 替換誤傷其他 Beak 系列描述 | 用嚴格的完整字串比對（`BeakBroodNest` 而非 `Beak`），全域 CLAUDE.md 用 Edit 工具逐處確認 |
| MCP server 啟不來 | 檢查 `/opt/.mcp.json` 路徑與 server name 拼字；新對話會在啟動時 stderr 報錯 |
| 全域 CLAUDE.md 改壞 | 改前先 `cp ~/.claude/CLAUDE.md ~/.claude/CLAUDE.md.bak.YYYYMMDD` |

回滾步驟（若任一步驟失敗）：
1. `sudo systemctl stop broodnest.service`（如已建立）
2. `mv /opt/BroodNest /opt/BeakBroodNest`（若已改目錄）
3. DB 復原：`dropdb brood_nest && createdb beak_broodnest && psql beak_broodnest < /tmp/beakbroodnest_backup_*.sql`
4. 還原 systemd service / nginx / .mcp.json / 全域 CLAUDE.md（從備份）
5. 啟動原 service 確認回到改名前狀態

---

## 不要動的東西

- 其他 Beak 系列專案目錄（BeakPlatform / BeakGuard / BeakSeal / BeakMeshWall / BeakGantt）
- 全域 CLAUDE.md 中其他 Beak 專案的段落
- GitHub 遠端倉庫名與 git history（下階段一併評估清理）
- BeakBroodNest 知識庫內 atom 3406「公開前 GitHub git history 清理」（下階段才動）
- 過去 commit message 中的 BeakBroodNest 字樣（git log 是歷史記錄，不重寫）

---

## 待用戶確認

執行前請確認以下三點：

1. **forgejo 倉庫是否要同步改名**？建議改（forgejo 是內部，改完一致），但需要用戶到 forgejo Web UI 操作 + 同意改 git remote URL
2. **DB 密碼是否要一併改**？目前 user `beak_broodnest` 密碼 `postgres123`，改名後 user 變 `brood_nest`，密碼可保留也可改，需要決定
3. **執行時機**？此任務會中斷服務數分鐘，需確認用戶當下不會用到 BroodNest（人類介面）
