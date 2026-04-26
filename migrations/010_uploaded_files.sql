-- 010: 檔案上傳資料表
-- 用於圖片上傳與檔案附件，token 為公開隨機識別碼，
-- stored_path 是磁碟上的實際路徑（用 token 命名，不洩漏原檔名）

CREATE TABLE IF NOT EXISTS uploaded_files (
    id                SERIAL PRIMARY KEY,
    token             VARCHAR(64) NOT NULL UNIQUE,
    original_filename VARCHAR(500) NOT NULL,
    stored_path       VARCHAR(1000) NOT NULL,
    mime_type         VARCHAR(200) NOT NULL DEFAULT 'application/octet-stream',
    size_bytes        BIGINT NOT NULL DEFAULT 0,
    kind              VARCHAR(20) NOT NULL DEFAULT 'file',  -- image, file
    uploaded_by       VARCHAR(100) NOT NULL DEFAULT 'ethan',
    uploaded_at       TIMESTAMP NOT NULL DEFAULT now(),
    is_deleted        BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_uploaded_files_kind ON uploaded_files(kind);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_uploaded_at ON uploaded_files(uploaded_at);
