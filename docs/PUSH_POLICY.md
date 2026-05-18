# Push 前測試與隱私守則

本專案已於 GitHub 公開（`ethan-beakmask/BeakBroodNest`），任何 push 都是不可逆的對外揭露。

## 測試完整性

- **MUST** 在 push 前完成完整測試：既有 pytest 測試套件全綠 + 對受影響功能進行手動 / 端對端驗證
- 改動涉及新模組或新行為時，**MUST** 補上對應測試後才 push
- 測試未通過或無法驗證時，**MUST NOT** push 到 `github` 或 `origin`，先回報用戶
- 「commit 是本地動作可隨時改寫」「push 是不可逆的對外揭露」，兩件事的決策標準不同

## 隱私與機密控制

- **MUST** 在 push 前檢查改動內容不含：認證資訊（密碼 / API Key / Token）、內部 IP / 主機名、其他專案的私有資訊、用戶個資、知識庫實際內容快照
- **MUST** 確認 `config.ini`、`.env`、`secrets/`、`OLD/`、`orchestrator/workspaces/` 等敏感目錄仍在 `.gitignore` 排除清單內
- **MUST NOT** 自行將任何 GitHub repo 從 private 改為 public，可見性由用戶決定（背景：BeakMeshWall 曾在用戶不知情下被設為 public 多日）
- 發現可疑外洩時 **MUST** 立即停手回報用戶，不自行 force push 蓋掉歷史

## Push 指令

```bash
git push origin master   # 內部 forgejo
git push github master   # 公開 GitHub（ssh 認證）
```

`/upcom` 等自動 push 流程：對 `github` 與 `origin` 都直接 push 即可，不需要特殊跳過。

**歷史保留**（已不再強制使用，但檔案留著以備未來情境變化）：
- `scripts/push_github.sh` -- 早期過濾內部檔再 force push 的腳本（含 EXCLUDE_FILES）
- `scripts/pre-push.sample` -- 早期 pre-push hook（攔截裸 push 到 github）

> 注意：本放行**只適用本專案**。其他 /opt/* 專案（如 BeakPlatform）尚未整理為可公開狀態，全域規範仍要求過濾後才能對外推送。
