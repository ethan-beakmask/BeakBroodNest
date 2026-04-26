-- 012: 交換卡片功能 (Exchange Packs)
-- 用戶可將白板上選中的卡片「寄存」到交換包，再從交換包「取出」到任何白板
-- 取代舊「+ 取回」搜尋取回流程；永久寄存策略，取出後包仍存在

BEGIN;

-- 交換包主表
CREATE TABLE IF NOT EXISTS exchange_packs (
    id               SERIAL PRIMARY KEY,
    name             VARCHAR(300) NOT NULL,
    source_canvas_id INTEGER NULL REFERENCES canvases(id) ON DELETE SET NULL,
    owner            VARCHAR(100) NOT NULL DEFAULT 'ethan',
    created_at       TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_exchange_packs_created_at ON exchange_packs(created_at DESC);

-- 交換包與原子的多對多
-- 同一張卡片同 pack 不可重複；不同 pack 可以引用同一張卡片
CREATE TABLE IF NOT EXISTS exchange_pack_atoms (
    id              SERIAL PRIMARY KEY,
    pack_id         INTEGER NOT NULL REFERENCES exchange_packs(id) ON DELETE CASCADE,
    atom_id         INTEGER NOT NULL REFERENCES knowledge_atoms(id) ON DELETE CASCADE,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    original_pos_x  DOUBLE PRECISION,
    original_pos_y  DOUBLE PRECISION,
    original_width  DOUBLE PRECISION,
    original_height DOUBLE PRECISION,
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_exchange_pack_atom UNIQUE(pack_id, atom_id)
);
CREATE INDEX IF NOT EXISTS idx_exchange_pack_atoms_pack ON exchange_pack_atoms(pack_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_exchange_pack_atoms_atom ON exchange_pack_atoms(atom_id);

COMMIT;
