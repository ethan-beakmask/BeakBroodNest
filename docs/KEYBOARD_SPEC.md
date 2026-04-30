# BeakCortex 文件編輯鍵盤規格

> 適用範圍：卡片編輯器 (Tiptap WYSIWYG MD)、白板上的卡片編輯、心智圖右鍵編輯卡片。
> 白板的滑鼠操作不在此規格內。

## 設計原則

1. **白板 = 滑鼠主場;文件 = 鍵盤主場**。文件編輯的所有常用操作都要有鍵盤路徑,不依賴滑鼠。
2. **業界慣例優先**。使用者熟悉 Notion / Linear / Slack 的肌肉記憶就直接套用,例如 Ctrl+Enter 是「強制送出 / 強制跳出」的肌肉記憶。
3. **`;;物件` 是 atomic block**。文件流內不可 inline 編輯,刪除只能透過 `[x]` 按鈕,鍵盤不誤刪。
4. **Mod+Enter 唯一語意 = 強制跳出當前 block 並插空段**。不論在哪個 block 內,行為一致。
5. **同一個鍵在不同情境下行為要一致或可預測**;若必須有差異,差異要符合用戶的「在哪裡」直覺。

## 完整鍵盤對照表

### 段落 / List / Heading

| 鍵 | 行為 | 來源 |
|---|---|---|
| `Enter` | splitBlock,新一段 | PM baseKeymap |
| `Shift+Enter` | hardBreak (段內換行) | PM baseKeymap |
| **`Mod+Enter`** | **在當前最外層 block 之後 force 插入空 paragraph 並進入** | `ListHotkeys` |

### List (BulletList / OrderedList / TaskList)

| 鍵 | 行為 | 來源 |
|---|---|---|
| `Tab` | 縮排 (sinkListItem) | `ListHotkeys` |
| `Shift+Tab` | 反縮排 (liftListItem) | `ListHotkeys` |
| `Enter` | 新一個 item;**空項自動退出清單**(split 失敗 → lift) | `ListHotkeys` |
| `Shift+Enter` | item 內 hardBreak | PM 預設 |

### 表格 (Table)

| 情境 | 鍵 | 行為 | 來源 |
|---|---|---|---|
| Cell 內任意位置 | `Tab` | 跨下一格;**最末格自動加新列** (`addRowAfter` + `goToNextCell`) | `ListHotkeys` |
| Cell 內任意位置 | `Shift+Tab` | 跨上一格 (`goToNextCell('previous')`) | `ListHotkeys` |
| Cell 內 (段中) | `Enter` | cell 內新一段 | PM 預設 |
| Cell 內 | `Mod+Enter` | **跳出 table 並在 table 之後插空段** | `ListHotkeys` (統一規則) |
| 最末 row 最末 cell 末位 | `ArrowDown` | 跳出到下方 textblock / entry;**若無內容自動加 paragraph** | `ListHotkeys` |
| 最首 row 最首 cell 首位 | `ArrowUp` | 對稱跳出到上方 | `ListHotkeys` |
| 任意位置 | toolbar 上排 (粉紅) `[-列][-欄][-表]` | 刪除類,非表格時 disabled | `wb_modals.html` |
| 任意位置 | toolbar 下排 (淺綠) `[Tb][+列上][+列下][+欄左][+欄右]` | 新增類,Tb 永遠 enabled,其餘非表格時 disabled | `wb_modals.html` |

> Toolbar 所有按鈕都標 `tabindex=-1`,Tab 不會跑進 toolbar 誤觸危險按鈕(如 `-表`)。

### `;;物件` (structuredEntry)

| 情境 | 鍵 | 行為 | 來源 |
|---|---|---|---|
| 任意段落首行 | 打 `;;td` 等觸發字 | 開 entry-modal 詢問,確認後才寫入文件;ESC 取消清掉 `;;XXX` 文字 | `slash-command.js` |
| caret 在 entry 鄰接段尾 | `ArrowDown` | 進入下一個 entry (設 NodeSelection) | `structuredEntry` |
| caret 在 entry 鄰接段首 | `ArrowUp` | 進入上一個 entry (設 NodeSelection) | `structuredEntry` |
| entry NodeSelection | `Enter` / `Shift+Enter` / `F2` / 雙擊 | 開 entry-modal 編輯 | `structuredEntry` |
| entry NodeSelection | `Mod+Enter` | (沿用全域規則) 在 entry 後插空段並進入 | `ListHotkeys` |
| entry NodeSelection | `ArrowUp` / `ArrowDown` | 跳到前/後位置 (entry 也算目標,可串接) | `structuredEntry` |
| entry NodeSelection | `Tab` / `Shift+Tab` | 同 Arrow 方向跳出 | `structuredEntry` |
| entry NodeSelection | `Backspace` / `Delete` | **吃掉(只能透過 `[x]` 刪除)** | `structuredEntry` |

### 刪除保護 (邊界誤刪防護)

| 情境 | 鍵 | 行為 | 來源 |
|---|---|---|---|
| caret 在 entry 後段首字 | `Backspace` | **吃掉** (禁從外部刪入 entry) | `structuredEntry` |
| caret 在 entry 前段末字 | `Delete` | **吃掉** (禁從外部刪入 entry) | `structuredEntry` |
| 萬一 caret 跑進 entry 內 | `Backspace` / `Delete` / `ArrowUp` / `ArrowDown` | redirect 出去 | `structuredEntry` |

### 主旨欄(理論上不可達)貼上保護

| 情境 | 行為 | 來源 |
|---|---|---|
| 在 entry 內貼上含換行的文字 | 換行 → 空格;HTML → 純文字 | `structuredEntry.addProseMirrorPlugins` |

### Modal 對話框 (entry-modal)

| 鍵 | 行為 |
|---|---|
| `Esc` | 取消 (新建場景 = 不寫入文件) |
| `Mod+Enter` | 儲存 |
| `Enter` (input) | 跳下一個欄位;末欄送出 |
| `Enter` (textarea) | 自然換行 |
| `Tab` / `Shift+Tab` | 跨欄;在 modal 內環繞 (focus trap) |

> Modal 是 `document.body` 級獨立元素,所有鍵盤事件 stopPropagation,不影響背後 PM。

---

## 實作位置速查

| 檔案 | 責任 |
|---|---|
| `human_ui/static/js/src/card-editor.js` | `ListHotkeys` extension:Mod-Enter 全域規則、Tab/Shift-Tab 跨 list/table、表格邊界 ArrowUp/Down |
| `human_ui/static/js/src/structured-entry.js` | StructuredEntry NodeView (純展示) + entry 鍵盤行為 + 邊界刪除保護 + paste 攔截 |
| `human_ui/static/js/src/entry-modal.js` | entry 編輯對話框 + 內部鍵盤 |
| `human_ui/static/js/src/slash-command.js` | `;;XX` 觸發開 modal |
| `human_ui/templates/partials/wb_modals.html` | toolbar 結構 + tabindex=-1 注入 |
| `human_ui/static/css/card-editor.css` | toolbar 雙色、entry 顯示、modal 樣式 |

## 改動規格時的協議

新增或修改鍵盤行為時:
1. **先更新本文件** (KEYBOARD_SPEC.md),確認與既有規則不衝突
2. 改動實作 (對應檔案)
3. 知識庫補方法論原子 (BeakCortex MCP `note_store`,schema_id=2)
4. commit 訊息要明確指出鍵盤規格變更

衝突檢查重點:
- 同一個鍵在多個 extension 都註冊時,**最後註冊的優先處理**(Tiptap PM keymap chain 實際行為)
- 各 extension 註冊順序見 `card-editor.js` 的 `extensions: [...]` array
- `ListHotkeys` 一律在最後,擁有最終裁決權
