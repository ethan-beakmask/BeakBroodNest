-- 011: knowledge_atoms 加 thumbnail_url 欄位
-- 用於白板上將卡片以縮圖形式呈現；單一欄位天然單選，避免歧義
-- 值是 image src（通常 /beakbroodnest/files/{token}，也接受外部 URL）
-- NULL = 此卡不以縮圖呈現

ALTER TABLE knowledge_atoms
    ADD COLUMN IF NOT EXISTS thumbnail_url VARCHAR(2000) NULL;
