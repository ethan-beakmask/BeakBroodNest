# BeakBroodNest Relay 使用文件

跨機通訊工具：Ubuntu orchestrator -> Windows MobaXterm。
本文件對象為 Claude Code 與其他自動化代理，提供呼叫方式、設定欄位、錯誤排查的單一參考點。

---

## 1. 架構概觀

```
[Ubuntu 192.168.0.16]                           [Windows 192.168.0.10]
  notify_windows.py                               BeakBroodNest.exe
  monitor.py            ---- HTTP/JSON ---->      (系統列常駐, port 5200)
  curl                                            |
                                                  v
                                                MobaXterm
                                                  |
                                                  v
                                                target tab (例: [X390])
```

- Ubuntu 端：`orchestrator/notify_windows.py`、`orchestrator/monitor.py`
- Windows 端：`orchestrator/windows/relay/`（Go 原始碼）編譯成 `BeakBroodNest.exe`
- Python 版 `orchestrator/windows/relay_receiver.py` 為**歷史保留**，不再迭代，現役為 Go 版

---

## 2. Windows 端：BeakBroodNest.exe

### 2.1 來源
- 原始碼：`/opt/BeakBroodNest/orchestrator/windows/relay/`
- 編譯腳本：`build.sh`（在 Ubuntu 端用 `GOOS=windows GOARCH=amd64` 交叉編譯）
- 部署管道：`build.sh` 偵測到 `/mnt/smb` 已掛載時自動複製 `BeakBroodNest.exe` 與 `config.yaml`

### 2.2 啟動
Windows 端雙擊 `BeakBroodNest.exe` 或從系統列圖示啟動。
- 用 `-H windowsgui` 編譯，**無 console 視窗**
- log 寫到 exe 同目錄的 `BeakBroodNest.log`
- 設定檔預設讀同目錄的 `config.yaml`，可用 `--config` 指定其他路徑

### 2.3 端點

| 方法 | 路徑 | 用途 |
|---|---|---|
| POST | `/relay`  | 接收 paste / notify 指令 |
| GET  | `/status` | 查詢狀態、最近 10 筆訊息、stats |
| POST | `/launch` | 啟動 MobaXterm 並開啟指定 bookmark |

### 2.4 設定檔 `config.yaml`
```yaml
server:
  port: 5200
  bind: "0.0.0.0"

auth:
  token: "<隨機字串>"   # v1.2.1+ 才生效；空字串 = 不驗證

mobaxterm:
  path: 'D:\MIS\Tools\MobaXterm_Portable_v25.3\MobaXterm_Personal_25.3.exe'
  default_bookmark: 'User sessions\192.168.0.16 ([X390])'
  default_target: "[X390]"
```

### 2.5 版本差異

| 版本 | Commit | 行為 |
|---|---|---|
| v1.1.0 | `5dfb24d` | Go 版首發，**不檢查 Authorization header**（即使 `auth.token` 設了也照樣放行） |
| v1.2.1 | `191d717` | 新增 `authMiddleware`，缺/錯 token 回 401；移除啟動時的 `printUsage` 噪音 |

打 `/status` 看 server 是否啟動；無法直接從回傳判斷版本，要看啟動 log 第一行 `BeakBroodNest Relay v1.x.x 啟動`。

---

## 3. Ubuntu 端：呼叫方式

### 3.1 推薦：notify_windows.py（包了 token、target 推導）

```bash
cd /opt/<專案>
/opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/orchestrator/notify_windows.py [選項]
```

| 選項 | 說明 |
|---|---|
| `-m "訊息"` | 要送出的文字（paste/notify/clipboard 必填） |
| `--action {paste,notify,clipboard}` | 預設 `paste`。注意：Go 版 `clipboard` 會回 `success=false` |
| `--target "([X390])"` | 目標分頁關鍵字。**留空時自動從 `$PWD` 推導**：`/opt/BeakSeal` -> `([BeakSeal])` |
| `--launch` | 改打 `/launch`，啟動 MobaXterm |
| `--bookmark "User sessions\\192.168.0.16 ([X390])"` | 搭配 `--launch`，留空時自動從 `$PWD` 推導 |
| `--host` / `--port` | 覆寫 `config.ini [relay]` 的設定 |

#### 範例

```bash
# 把訊息貼到當前專案對應的 MobaXterm 分頁
cd /opt/BeakSeal
/opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/orchestrator/notify_windows.py \
  -m "支線任務完成"
# -> action=paste, target=([BeakSeal])

# 只通知，不貼字
/opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/orchestrator/notify_windows.py \
  -m "ping" --action notify

# 啟動 MobaXterm 並開特定 bookmark
cd /opt/BeakMeshWall-dev
/opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/orchestrator/notify_windows.py --launch
# -> bookmark=User sessions\192.168.0.16 ([BeakMeshWall])
```

### 3.2 直接 curl（不依賴 notify_windows.py）

從 `/opt/BeakBroodNest/config.ini [relay]` 讀 `host` / `port` / `token`：

```bash
RELAY_HOST=$(grep -E '^host' /opt/BeakBroodNest/config.ini | head -1 | awk -F= '{print $2}' | tr -d ' ')
RELAY_PORT=$(grep -E '^port' /opt/BeakBroodNest/config.ini | head -1 | awk -F= '{print $2}' | tr -d ' ')
RELAY_TOKEN=$(grep -E '^token' /opt/BeakBroodNest/config.ini | head -1 | awk -F= '{print $2}' | tr -d ' ')

# /status
curl -s -H "Authorization: Bearer $RELAY_TOKEN" \
  "http://$RELAY_HOST:$RELAY_PORT/status" | jq .

# /relay paste
curl -X POST "http://$RELAY_HOST:$RELAY_PORT/relay" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $RELAY_TOKEN" \
  -d '{
    "action": "paste",
    "message": "echo hello",
    "target": "[X390]",
    "source": "claude-code",
    "timestamp": "'"$(date -Iseconds)"'"
  }'

# /launch
curl -X POST "http://$RELAY_HOST:$RELAY_PORT/launch" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $RELAY_TOKEN" \
  -d '{"bookmark":"User sessions\\192.168.0.16 ([X390])"}'
```

> v1.1.0 server 不驗證 token，帶不帶 `Authorization` 都行；v1.2.1 起若 `auth.token` 非空就必須帶。

---

## 4. config.ini `[relay]` 區段（Ubuntu 端）

`/opt/BeakBroodNest/config.ini`：

```ini
[relay]
host = 192.168.0.10        ; Windows 端 IP（家用環境）
port = 5200
token = <與 Windows 端 config.yaml auth.token 相同>
```

`notify_windows.py`、`monitor.py` 會自動向上搜尋（最多 5 層）找到 `config.ini` 並載入 `[relay]`。

---

## 5. action 對照表

| action    | Python 版（舊） | Go v1.1.0+ | 行為 |
|---|---|---|---|
| `paste`   | OK | OK | 找 MobaXterm 視窗 -> 切到 `target` 分頁 -> 送字 + Enter |
| `notify`  | OK | OK | 只寫 log（Windows 端 `BeakBroodNest.log`），不操作視窗 |
| `clipboard` | OK | **不支援**（回 `success=false`，要求改用 paste） | — |

`paste` 內部策略（Go 版）：
1. 找 hwnd 標題含 `MobaXterm` 或 class 含 `TMobaXterm`
2. 若當前分頁標題不含 `target`，循環 `Ctrl+Tab` 最多 10 次
3. 找到分頁底下可見的 `CMoTTY` 子控件 -> 用 `WM_CHAR` 逐字送（避開剪貼簿快捷鍵問題）
4. 找不到 `CMoTTY` 才退回 `Shift+Ctrl+Insert` 鍵盤模擬

---

## 6. 常見錯誤與排查

| 症狀 | 原因 | 處置 |
|---|---|---|
| `Connection refused` / timeout | Windows 端 `BeakBroodNest.exe` 沒跑、防火牆擋、IP 寫錯 | RDP 看 Windows 系統列；確認 `config.ini` host 是 `192.168.0.10` |
| HTTP 401 `unauthorized` | v1.2.1 開了 token 驗證但 client 沒帶／帶錯 | 對齊 Ubuntu `config.ini [relay] token` 與 Windows `config.yaml auth.token` |
| `paste` 回 `phase1-fallback` 或找不到目標分頁 | MobaXterm 沒開、bookmark 名稱對不上、target 關鍵字寫錯 | 先 `--launch` 開分頁，或調整 `target`／`default_target` |
| `paste` 成功但訊息亂碼 | `WM_CHAR` 對非 BMP 字元支援有限 | 拆短訊息或避開 emoji |
| `curl` 帶 Bearer 仍 401 | `config.yaml` token 含特殊字元（如 `$`）被 shell 展開 | token 用單引號或全字母數字 |

驗證 server 活著：
```bash
curl -fsS -m 3 -H "Authorization: Bearer $RELAY_TOKEN" \
  http://192.168.0.10:5200/status >/dev/null && echo OK || echo DOWN
```

---

## 7. 原始碼位置速查

| 用途 | 路徑 |
|---|---|
| Go server 入口 | `orchestrator/windows/relay/main.go` |
| HTTP handler | `orchestrator/windows/relay/server.go` |
| Windows 視窗操作 | `orchestrator/windows/relay/winctl_windows.go` |
| 系統列 | `orchestrator/windows/relay/tray_windows.go` |
| 設定載入 | `orchestrator/windows/relay/config.go` |
| 編譯 + 部署 | `orchestrator/windows/relay/build.sh` |
| Ubuntu 呼叫器 | `orchestrator/notify_windows.py` |
| 監控整合（帶 token） | `orchestrator/monitor.py` |
| Python 版（歷史） | `orchestrator/windows/relay_receiver.py` |
