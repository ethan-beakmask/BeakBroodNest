# 服務與排程清單

集中列出 BeakBroodNest 部署後會建立 / 仰賴的所有系統級資源，便於：

- 部署前評估同機是否有衝突
- 解除安裝（uninstall）時知道有哪些檔案 / 條目要清掉
- 同機跑多份實例（如測試版）時知道哪些名稱要錯開

> 如果你只想跑安裝流程，看 [README 的快速開始](../README.md#快速開始) 就夠了。本文件給維運與排錯用。

---

## 1. systemd service

`scripts/install.sh` 會建立一個 systemd unit：

| 路徑 | 用途 | 是否會被 install.sh 覆寫 |
|---|---|---|
| `/etc/systemd/system/${SERVICE_NAME}.service` | gunicorn 主服務（綁 `127.0.0.1:5171`） | 是（cat > 重建） |

`SERVICE_NAME` 預設 `beakbroodnest`，可由環境變數覆蓋。同機跑多份時必須改名避免覆蓋。

控制：

```bash
sudo systemctl {start|stop|restart|status} beakbroodnest
sudo journalctl -u beakbroodnest -f
```

## 2. Nginx site

| 路徑 | 用途 |
|---|---|
| `/etc/nginx/sites-available/${SERVICE_NAME}` | reverse proxy 設定，listen `${SERVER_IP}:${BEAKBROODNEST_PORT}` |
| `/etc/nginx/sites-enabled/${SERVICE_NAME}` | symlink 啟用 |

upstream / proxy_pass 名稱也使用 `${SERVICE_NAME}`，避免同機多實例時 nginx 抱怨 duplicate upstream。

## 3. PostgreSQL

| 物件 | 預設名稱 | 是否會被 install.sh 覆寫 |
|---|---|---|
| Role / User | `beak_broodnest` | 已存在則 `ALTER USER ... PASSWORD`，密碼會被覆蓋 |
| Database | `beak_broodnest` | 已存在則跳過，不會 DROP |
| Extension `vector` | - | `CREATE EXTENSION IF NOT EXISTS`（idempotent） |
| Extension `pg_trgm` | - | `CREATE EXTENSION IF NOT EXISTS`（idempotent） |

可由環境變數 `DB_NAME` / `DB_USER` / `DB_PASS` 覆蓋。

## 4. Log 目錄

所有 log 集中於 `/opt/tmp/`（依全域規範，不寫入 `/var/log/`）：

| 檔案 | 寫入者 |
|---|---|
| `/opt/tmp/${SERVICE_NAME}-gunicorn-access.log` | gunicorn |
| `/opt/tmp/${SERVICE_NAME}-gunicorn-error.log` | gunicorn |
| `/opt/tmp/BeakBroodNest-orchestrator-monitor.log` | orchestrator/monitor.py |
| `/opt/tmp/scripts-scheduler.log` | scripts/scheduler.py |
| `/opt/tmp/scripts-embed_worker.log` | scripts/embed_worker.py |
| `/opt/tmp/BeakBroodNest-session_watchdog.log` | scripts/session_watchdog.py |
| `/opt/tmp/BeakBroodNest-scripts-db_importer.log` | scripts/db_importer.py |

## 5. crontab 條目（/etc/crontab）

`install.sh` 會在全新安裝最後一步**互動詢問是否啟用排程任務**（預設 Y），同意後自動 append 5 條條目，並包覆於 `# BEGIN BeakBroodNest <SERVICE_NAME>` / `# END ...` 標記之間方便日後移除。

非互動安裝可用環境變數控制：

```bash
sudo INSTALL_CRON=yes bash install.sh   # 強制啟用，不問
sudo INSTALL_CRON=no  bash install.sh   # 跳過排程
```

若 `/etc/crontab` 中已含 BEGIN marker 或 INSTALL_DIR 字串（涵蓋手動寫入的舊版安裝），會跳過避免重複。

下表為實際寫入的條目（路徑會用 `INSTALL_DIR`、`SERVICE_NAME`、`CRON_USER` 替換）：

| 條目 | 頻率 | 用途 |
|---|---|---|
| `orchestrator/monitor.py --start` | `* * * * *` | Orchestrator 監控 daemon（flock 防重複啟動） |
| `scripts/scheduler.py --tick` | `*/5 * * * *` | **集中式排程器入口**（meta-scheduler，派發 schedule.json 任務） |
| `scripts/embed_worker.py` | `* * * * *` | Embedding worker，掃描待嵌入原子產生 pgvector |
| `scripts/session_watchdog.py --check --alert` | `* * * * *` | 對話卡住偵測 |
| `scripts/db_importer.py -convertall` | `*/10 * * * *` | JSONL 對話增量匯入 PostgreSQL |

範例（install.sh 自動寫入的格式，`SERVICE_NAME` / `INSTALL_DIR` / `CRON_USER` 為實際值）：

```cron
# BEGIN BeakBroodNest beakbroodnest
* * * * * ethan flock -n /tmp/beakbroodnest-monitor.lock /opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/orchestrator/monitor.py --start >> /opt/tmp/beakbroodnest-orchestrator-monitor.log 2>&1
*/5 * * * * ethan /opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/scripts/scheduler.py --tick >> /opt/tmp/beakbroodnest-scheduler.log 2>&1
* * * * * ethan cd /opt/BeakBroodNest && flock -n /tmp/beakbroodnest-embed.lock venv/bin/python scripts/embed_worker.py >> /opt/tmp/beakbroodnest-embed_worker.log 2>&1
* * * * * ethan /opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/scripts/session_watchdog.py --check --alert >> /opt/tmp/beakbroodnest-session_watchdog.log 2>&1
*/10 * * * * ethan flock -n /tmp/beakbroodnest-db-importer.lock /opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/scripts/db_importer.py -convertall >> /opt/tmp/beakbroodnest-db_importer.log 2>&1
# END BeakBroodNest beakbroodnest
```

> lock 路徑與 log 檔名都帶 `SERVICE_NAME` 前綴，所以同機跑多份實例不會互相阻擋。

## 6. scripts/scheduler.py 派發的子任務

由 `scripts/scheduler.py --tick` 每 5 分鐘檢查 `scripts/schedule.json`，派發到期任務：

| 任務名稱 | Cron | 用途 |
|---|---|---|
| `vitality_decay` | `0 3 * * *` | 知識原子活力衰減（每日 03:00） |
| `pg_backup` | `30 2 * * *` | PostgreSQL 資料庫備份（每日 02:30） |
| `uploaded_files_gc` | `30 3 * * *` | 上傳檔案孤兒清理（每日 03:30） |
| `nightly_review` | `25 8 * * *` | 每日復盤 Pipeline P0~P3（每日 08:25） |
| `p1_scan_frequent` | `*/10 * * * *` | P1 訊號掃描高頻版（每 10 分鐘） |

查狀態：

```bash
/opt/BeakBroodNest/venv/bin/python scripts/scheduler.py --status
/opt/BeakBroodNest/venv/bin/python scripts/scheduler.py --run-now <task_name>   # 手動觸發
```

完整任務定義見 `scripts/schedule.json`。

## 7. 同機部署多份（測試版）建議

驗證 install.sh 時為避免踩到正式環境，所有環境變數**全部**錯開：

```bash
sudo INSTALL_DIR=/home/ethan/test-broodnest \
     SERVICE_NAME=beakbroodnest_test \
     DB_NAME=beak_broodnest_test \
     DB_USER=beak_broodnest_test \
     DB_PASS='test_password_123' \
     BEAKBROODNEST_PORT=5180 \
     bash install.sh
```

驗證項目：

- [ ] `/etc/systemd/system/beakbroodnest_test.service` 是否建立
- [ ] `/etc/nginx/sites-available/beakbroodnest_test` 是否建立
- [ ] DB `beak_broodnest_test` 是否建立並啟用 `vector` / `pg_trgm` 兩 extension
- [ ] http://${SERVER_IP}:5180/ 是否可連線
- [ ] 正式服務 `beakbroodnest` 仍正常運行（`sudo systemctl status beakbroodnest`）

驗證完拆除：

```bash
sudo systemctl stop beakbroodnest_test
sudo systemctl disable beakbroodnest_test
sudo rm /etc/systemd/system/beakbroodnest_test.service
sudo rm /etc/nginx/sites-{available,enabled}/beakbroodnest_test
sudo systemctl daemon-reload
sudo systemctl reload nginx
sudo -u postgres psql -c "DROP DATABASE beak_broodnest_test;"
sudo -u postgres psql -c "DROP USER beak_broodnest_test;"
sudo rm -rf /home/ethan/test-broodnest
```

---

## 開發常用指令

### 正式服務控制

```bash
sudo systemctl {start|stop|restart|status} beakbroodnest.service
sudo journalctl -u beakbroodnest -f
```

### 首次初始化資料庫

```bash
/opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/human_ui/app.py --init-db --seed
```

### 開發 Flask dev server（hot reload，port 5175）

```bash
/opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/human_ui/app.py --serve --port 5175 --host <HOST_IP>
```

與正式 gunicorn (5171) 並存，皆連同一個 `beak_broodnest` DB。
