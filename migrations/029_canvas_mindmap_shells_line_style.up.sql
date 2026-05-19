-- 加入 line_style 欄位（殼層級的樹線連線樣式）
-- 支援值: 'bezier' | 'elbow'
--   bezier = 立方 Bezier 曲線（現況，預設）
--   elbow  = 正交折線（Manhattan），三段：parent 端水平 -> child 端內側垂直 -> 進入 child
-- 影響範圍：tree-right / tree-right-diag / tree-down
-- radial / radial-rotated 不採用 elbow（同心圓本身是直線連，折線無視覺意義）
ALTER TABLE canvas_mindmap_shells
    ADD COLUMN line_style VARCHAR(20) NOT NULL DEFAULT 'bezier';
