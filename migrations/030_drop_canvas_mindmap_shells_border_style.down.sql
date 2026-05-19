-- 還原 017 加的 border_style 欄位(預設 solid,與 017 原值一致)
ALTER TABLE canvas_mindmap_shells
    ADD COLUMN IF NOT EXISTS border_style VARCHAR(20) NOT NULL DEFAULT 'solid';
