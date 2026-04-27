-- 014: 白板獨立文字框 (canvas_textboxes)
-- 在白板上獨立放置的文字註解框，標題在框外、內文純文字。
-- 不依附任何 atom，可被連線（連到 atom 或其他 textbox）。
-- 配套：
--   * canvas_connections 端點擴充為支援 atom / textbox 兩種 kind
--   * canvas_trash 擴充為可暫存 textbox

BEGIN;

-- ============================================================
-- Step A: canvas_textboxes 主表
-- ============================================================

CREATE TABLE IF NOT EXISTS canvas_textboxes (
    id              SERIAL PRIMARY KEY,
    canvas_id       INTEGER NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
    title           VARCHAR(200) NOT NULL DEFAULT '標題',
    content         TEXT NOT NULL DEFAULT '',
    pos_x           DOUBLE PRECISION NOT NULL DEFAULT 0,
    pos_y           DOUBLE PRECISION NOT NULL DEFAULT 0,
    width           DOUBLE PRECISION NOT NULL DEFAULT 320,
    height          DOUBLE PRECISION NOT NULL DEFAULT 180,
    z_index         INTEGER NOT NULL DEFAULT 1,
    bg_color        VARCHAR(20) NOT NULL DEFAULT '#fffbe6',
    border_color    VARCHAR(20) NOT NULL DEFAULT '#f59e0b',
    border_style    VARCHAR(20) NOT NULL DEFAULT 'solid',  -- none/solid/dashed
    text_color      VARCHAR(20) NOT NULL DEFAULT '#1f2937',
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    updated_at      TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_canvas_textboxes_canvas ON canvas_textboxes(canvas_id);

-- ============================================================
-- Step B: canvas_connections 端點擴充（支援 textbox kind）
-- ============================================================

-- 既有資料一律是 atom 端點，先把欄位加進來（含 default）並回填，再放寬 NOT NULL
ALTER TABLE canvas_connections
    ADD COLUMN IF NOT EXISTS from_kind         VARCHAR(20) NOT NULL DEFAULT 'atom',
    ADD COLUMN IF NOT EXISTS to_kind           VARCHAR(20) NOT NULL DEFAULT 'atom',
    ADD COLUMN IF NOT EXISTS source_textbox_id INTEGER REFERENCES canvas_textboxes(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS target_textbox_id INTEGER REFERENCES canvas_textboxes(id) ON DELETE CASCADE;

-- source/target_atom_id 改為 nullable（textbox 端點時為 NULL）
ALTER TABLE canvas_connections
    ALTER COLUMN source_atom_id DROP NOT NULL,
    ALTER COLUMN target_atom_id DROP NOT NULL;

-- 端點 kind 與 id 一致性檢查
ALTER TABLE canvas_connections
    ADD CONSTRAINT chk_canvas_conn_from_endpoint CHECK (
        (from_kind = 'atom'    AND source_atom_id    IS NOT NULL AND source_textbox_id IS NULL) OR
        (from_kind = 'textbox' AND source_textbox_id IS NOT NULL AND source_atom_id    IS NULL)
    ),
    ADD CONSTRAINT chk_canvas_conn_to_endpoint CHECK (
        (to_kind = 'atom'    AND target_atom_id    IS NOT NULL AND target_textbox_id IS NULL) OR
        (to_kind = 'textbox' AND target_textbox_id IS NOT NULL AND target_atom_id    IS NULL)
    );

-- 既有的 trg_canvas_conn_consistency 只在 NEW.relation_id IS NOT NULL 時驗證 atom 端點，
-- textbox 連線不掛 atom_relations.relation_id，trigger 不會誤觸；無需改 trigger。

CREATE INDEX IF NOT EXISTS idx_canvas_conn_src_textbox ON canvas_connections(source_textbox_id);
CREATE INDEX IF NOT EXISTS idx_canvas_conn_tgt_textbox ON canvas_connections(target_textbox_id);

-- ============================================================
-- Step C: canvas_trash 擴充支援 textbox
-- ============================================================

-- 既有資料一律是 atom kind，先加 default 再放寬 atom_id NOT NULL
ALTER TABLE canvas_trash
    ADD COLUMN IF NOT EXISTS kind        VARCHAR(20) NOT NULL DEFAULT 'atom',
    ADD COLUMN IF NOT EXISTS payload     JSONB;  -- textbox kind 用：保存 title/content/顏色等完整資料

ALTER TABLE canvas_trash
    ALTER COLUMN atom_id DROP NOT NULL;

-- 一致性：atom kind 必須有 atom_id；textbox kind 必須有 payload
ALTER TABLE canvas_trash
    ADD CONSTRAINT chk_canvas_trash_kind CHECK (
        (kind = 'atom'    AND atom_id IS NOT NULL) OR
        (kind = 'textbox' AND payload IS NOT NULL)
    );

-- 既有 UNIQUE(canvas_id, atom_id) 在 atom_id 為 NULL 時自動失效（PostgreSQL NULL 不參與 UNIQUE）
-- 無需調整既有 constraint。

CREATE INDEX IF NOT EXISTS idx_canvas_trash_kind ON canvas_trash(canvas_id, kind, deleted_at DESC);

COMMIT;
