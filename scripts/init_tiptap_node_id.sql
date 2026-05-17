-- Tiptap 結構性節點 stable nodeId 分配器
-- 用於 atom 內 Tiptap 文件樹中各結構性節點 (structuredEntry/image/heading/table/...)
-- 的 attrs.nodeId 來源，達成「複製→新 ID、移動→同 ID」語意統一。
--
-- 等冪：IF NOT EXISTS；可重複執行不影響 sequence 當前值。

CREATE SEQUENCE IF NOT EXISTS tiptap_node_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    MINVALUE 1
    NO MAXVALUE
    CACHE 1;

-- 應用程式帳號授權（若帳號存在）
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'beak_broodnest') THEN
        EXECUTE 'GRANT USAGE, SELECT, UPDATE ON SEQUENCE tiptap_node_id_seq TO beak_broodnest';
    END IF;
END $$;
