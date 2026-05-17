-- 白板獨立 structuredEntry（P3a）：與卡片同階層，直接放在白板上
-- 不寄生於 atom，獨立資料表
-- 等冪：所有 CREATE 都帶 IF NOT EXISTS

BEGIN;

CREATE TABLE IF NOT EXISTS standalone_entries (
    id              SERIAL PRIMARY KEY,
    schema_id       INTEGER NOT NULL REFERENCES entry_schemas(id),
    schema_code     TEXT NOT NULL DEFAULT 'freetext',
    raw_text        TEXT NOT NULL DEFAULT '',
    summary         VARCHAR(200) NOT NULL DEFAULT '',
    field_values    JSONB NOT NULL DEFAULT '{}'::jsonb,
    node_id         INTEGER UNIQUE,
    owner           TEXT NOT NULL DEFAULT 'ethan',
    sensitivity     TEXT NOT NULL DEFAULT 'internal',
    is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    updated_at      TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_standalone_entries_schema ON standalone_entries(schema_id);
CREATE INDEX IF NOT EXISTS idx_standalone_entries_is_deleted ON standalone_entries(is_deleted);
CREATE INDEX IF NOT EXISTS idx_standalone_entries_owner ON standalone_entries(owner);

-- 白板放置
CREATE TABLE IF NOT EXISTS canvas_standalone_entries (
    id                      SERIAL PRIMARY KEY,
    canvas_id               INTEGER NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
    standalone_entry_id     INTEGER NOT NULL REFERENCES standalone_entries(id) ON DELETE CASCADE,
    pos_x                   DOUBLE PRECISION NOT NULL DEFAULT 0,
    pos_y                   DOUBLE PRECISION NOT NULL DEFAULT 0,
    width                   DOUBLE PRECISION,
    height                  DOUBLE PRECISION,
    z_index                 INTEGER NOT NULL DEFAULT 0,
    visual_style            TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT uq_canvas_standalone_entry UNIQUE (canvas_id, standalone_entry_id)
);

CREATE INDEX IF NOT EXISTS idx_canvas_standalone_entries_canvas
    ON canvas_standalone_entries(canvas_id);

COMMIT;
