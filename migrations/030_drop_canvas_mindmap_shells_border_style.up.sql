-- 心智圖 v1 改造後殼框被 CSS 強制隱身(whiteboard.css `border: none !important`),
-- border_style 欄位在 v1 起即為死碼;UI 已於 2026-05-19 移除,本 migration drop 掉欄位
ALTER TABLE canvas_mindmap_shells DROP COLUMN IF EXISTS border_style;
