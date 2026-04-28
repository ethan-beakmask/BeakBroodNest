-- 加入 border_style 欄位（預設 solid 維持現有視覺）
-- 支援值: 'solid' | 'dashed' | 'none' | 'transparent'
--   solid       = 實線邊框 + 淡背景（現況）
--   dashed      = 虛線邊框 + 淡背景
--   none        = 無邊框 + 淡背景
--   transparent = 全透明（無邊框 + 無背景）-- 殼骨架隱形,僅見節點
ALTER TABLE canvas_mindmap_shells
    ADD COLUMN border_style VARCHAR(20) NOT NULL DEFAULT 'solid';
