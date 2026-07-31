# Push 前測試與隱私守則

本專案已於 GitHub 公開（`ethan-beakmask/BeakBroodNest`），任何 push 都是不可逆的對外揭露。

## 測試完整性

**`tests/` 刻意不入版控**（`.gitignore` 排除，2026-07-30 用戶裁決維持此狀態）。
測試在開發機維護，不隨 repo 散佈。因此：

- **MUST** 在 push 前於**開發機**完成完整測試：既有 pytest 測試套件全綠
  （`cd /opt/BeakBroodNest && venv/bin/python -m pytest -q`）+ 對受影響功能進行手動 / 端對端驗證
- 改動涉及新模組或新行為時，**MUST** 在開發機補上對應測試後才 push。
  測試檔不會出現在 `git status`（被 ignore），**這不代表可以略過撰寫**
- 測試未通過或無法驗證時，**MUST NOT** push 到 `github` 或 `origin`，先回報用戶
- 例外：失敗項與本次變更明確無關（例如動的是 shell 腳本、失敗的是 web API 測試）時可 push，
  但 **MUST** 在回報中明列失敗項、判定為無關的依據，以及該由誰後續處理
- 「commit 是本地動作可隨時改寫」「push 是不可逆的對外揭露」，兩件事的決策標準不同

### 已知限制（此決策的代價，不要每次重新討論）

- 公開 repo 與所有外部部署（含公司機）**拿不到任何測試**，無法自我驗收
- 測試的修改沒有版控保護，只存在開發機，重灌即失去
- 換言之：**開發機是測試的唯一權威來源**。任何「這台機器上跑不出問題」的結論，
  都只在開發機成立

## 參考資料同步（防「開發機正常、外部壞掉」）

UI 可見性依賴 DB 參考資料（選單 `nav_menu`、`entry_schemas`、schema 定義等）。
這些只存在開發機、忘了進版控時，外部部署會靜默缺功能（曾漏「閱覽器」選單、
整組 `entry_schemas`）。防線是產生器 + git diff：

- **MUST** 在 push 前執行 `python3 scripts/gen_reference_seed.py --check`
  - 輸出 `[OK]` = 無 drift，可 push
  - 輸出 `[DRIFT]` = 開發機 DB 有未回寫的參考資料，**先** `--write` 再 commit，才 push
- `scripts/seed_reference.sql` 是**產生檔**，勿手改；要改內容改開發機 DB 後重產
- 新增「參考表」時 **MUST** 把表加進 `gen_reference_seed.py` 的 `WHITELIST`（父表在前），
  否則不會被納管
- 密鑰 / 環境特定資料（`system_config`、`sensitive_terms`）**MUST NOT** 加進白名單

另一類同源問題是**欄位級 schema drift**：model 加了欄位但 DB 沒補，舊機升級時
`create_all_tables()` 不會補欄位，ORM 查詢會整條 500（實例：舊機首頁 500，canvases 缺欄位）。

- **SHOULD** 在 push 前執行 `python3 scripts/check_schema_drift.py --check`，確認 dev DB 與 model 一致
- install.sh 升級 / 安裝時會自動跑 `check_schema_drift.py --apply` 補上缺欄位（ADD COLUMN IF NOT EXISTS，冪等），舊機升級不再因缺欄位 500

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
