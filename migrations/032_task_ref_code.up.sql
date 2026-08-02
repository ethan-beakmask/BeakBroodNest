-- 032: 短代號 ref_code 與專案歸屬 schema 地基
--
-- 背景：
--   待辦目前同時存在「人類頁面上的 task entry」與「LLM 標題/tag」兩套表示法，
--   兩者缺少共同、可讀、穩定的稱呼。atom_id 對人類不友善，而從卡片擺在哪個白板
--   推導專案歸屬也會因跨白板擺放而漂移。
--
--   因此在白板上加入專案短前綴 code，在知識原子上加入全域唯一 ref_code 與
--   單一 project_canvas_id 歸屬欄位。流水號用 project_ref_counters 獨立記錄，
--   避免 SELECT max(...)+1 在併發下發出重複短代號。

BEGIN;

ALTER TABLE canvases
    ADD COLUMN IF NOT EXISTS code VARCHAR(8) NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_canvases_code_format'
          AND conrelid = 'canvases'::regclass
    ) THEN
        ALTER TABLE canvases
            ADD CONSTRAINT ck_canvases_code_format
            CHECK (code IS NULL OR code ~ '^[A-Z][A-Z0-9]{1,7}$');
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_canvases_code
    ON canvases (code)
    WHERE code IS NOT NULL;

ALTER TABLE knowledge_atoms
    ADD COLUMN IF NOT EXISTS ref_code VARCHAR(20) NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_atoms_ref_code
    ON knowledge_atoms (ref_code)
    WHERE ref_code IS NOT NULL;

ALTER TABLE knowledge_atoms
    ADD COLUMN IF NOT EXISTS project_canvas_id INTEGER NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_atoms_project_canvas'
          AND conrelid = 'knowledge_atoms'::regclass
    ) THEN
        ALTER TABLE knowledge_atoms
            ADD CONSTRAINT fk_atoms_project_canvas
            FOREIGN KEY (project_canvas_id)
            REFERENCES canvases(id)
            ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_atoms_project_canvas
    ON knowledge_atoms (project_canvas_id);

CREATE TABLE IF NOT EXISTS project_ref_counters (
    canvas_id INTEGER PRIMARY KEY REFERENCES canvases(id) ON DELETE CASCADE,
    next_seq  INTEGER NOT NULL DEFAULT 1
);

COMMENT ON TABLE project_ref_counters IS
    '每個專案白板的短代號流水號計數器。next_seq 是下一個要發出的序號。';
COMMENT ON COLUMN project_ref_counters.canvas_id IS
    '專案白板 id，刪除白板時一併移除計數器。';
COMMENT ON COLUMN project_ref_counters.next_seq IS
    '下一個要發出的流水號；用單列 upsert 更新避免併發重複。';

CREATE OR REPLACE FUNCTION next_ref_code(p_canvas_id INTEGER)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    v_code TEXT;
    v_seq INTEGER;
BEGIN
    SELECT code
      INTO v_code
      FROM canvases
     WHERE id = p_canvas_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'canvas % 不存在，無法產生短代號', p_canvas_id;
    END IF;

    IF v_code IS NULL THEN
        RAISE EXCEPTION 'canvas % 尚未設定專案代號 code，無法產生短代號', p_canvas_id;
    END IF;

    -- 單一 upsert 語句完成取號：
    --   INSERT 分支寫入 next_seq=2，代表本次發出 1。
    --   UPDATE 分支先把 next_seq 加 1，代表本次發出更新後的 next_seq - 1。
    --   因此兩個分支都可用 RETURNING next_seq - 1 取得本次序號。
    INSERT INTO project_ref_counters (canvas_id, next_seq)
    VALUES (p_canvas_id, 2)
    ON CONFLICT (canvas_id) DO UPDATE
        SET next_seq = project_ref_counters.next_seq + 1
    RETURNING next_seq - 1 INTO v_seq;

    RETURN v_code || '-' || v_seq::TEXT;
END;
$$;

COMMENT ON FUNCTION next_ref_code(INTEGER) IS
    '依專案白板 code 產生全域短代號，使用 project_ref_counters 原子取號避免併發重複。';

COMMIT;
