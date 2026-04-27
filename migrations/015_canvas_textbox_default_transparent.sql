-- 015: canvas_textboxes.bg_color 預設改為透明
-- 既有資料（如有）不動，僅影響後續新建的 textbox。

BEGIN;

ALTER TABLE canvas_textboxes
    ALTER COLUMN bg_color SET DEFAULT 'transparent';

COMMIT;
