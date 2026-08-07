-- 034 rollback：移除 knowledge_atoms 最後寫入歸屬欄位
--
-- 回滾後 AI 無法再從卡片資料分辨最後一次寫入身份或入口。

ALTER TABLE knowledge_atoms
    DROP CONSTRAINT IF EXISTS ck_knowledge_atoms_updated_via;

ALTER TABLE knowledge_atoms
    DROP COLUMN IF EXISTS updated_by;

ALTER TABLE knowledge_atoms
    DROP COLUMN IF EXISTS updated_via;
