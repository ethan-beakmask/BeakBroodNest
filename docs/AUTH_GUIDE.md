# BeakBroodNest Standalone 認證管理

## 概要

BeakBroodNest 在 Standalone 模式下使用自有帳密登入。
整合 BeakPlatform 後此機制將停用，改由 BeakPlatform 統一管理帳號。

---

## 安裝時設定帳密

安裝腳本 `install.sh` 會在初始化階段互動式詢問帳號與密碼：

```
帳號: <自訂帳號>
密碼（至少 8 字元）: <自訂密碼>
確認密碼: <再次輸入>
```

## 登入

瀏覽器開啟：

```
http://<主機IP>:<PORT>/beakbroodnest/login
```

Session 有效期 365 天，期間不需重複登入。

## 變更密碼（Web UI）

1. 登入後，點擊右上角「設定」
2. 切換到「帳號」分頁
3. 填入舊密碼、新密碼、確認新密碼
4. 點擊「變更」

## 重設帳密（命令列）

適用場景：忘記密碼、需要更換帳號。

```bash
cd /opt/BeakBroodNest
venv/bin/python human_ui/app.py --reset-auth
```

執行後會互動式詢問新帳號與密碼：

```
重設 Standalone 登入帳密
----------------------------------------
  新帳號: <輸入新帳號>
  新密碼: <輸入新密碼，不會顯示>
  確認密碼: <再次輸入>
  帳號已重設: <新帳號>

請重啟服務使變更生效:
  sudo systemctl restart beakbroodnest
```

重設後既有的登入 session 仍然有效，直到使用者手動登出或 session 過期。

## 登出

點擊右上角「Logout」，或直接開啟：

```
http://<主機IP>:<PORT>/beakbroodnest/logout
```

## 安全機制

| 項目 | 說明 |
|------|------|
| 密碼儲存 | PBKDF2 hash + salt（werkzeug 預設） |
| Session | Flask signed cookie，HttpOnly + SameSite=Lax |
| 有效期 | 365 天 |
| IP 白名單 | 僅允許設定的內網 IP 存取（第一層防護） |
| URL 前綴 | `/beakbroodnest/` 避免與 Nginx 根路徑衝突 |
