"""SQLite 資料庫初始化與連線管理"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'heptabase.db')


def get_conn():
    """取得 SQLite 連線，啟用 WAL 模式與外鍵約束"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """建立所有資料表"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schemas (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            slug        TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            icon        TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS schema_fields (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            schema_id   INTEGER NOT NULL REFERENCES schemas(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            label       TEXT NOT NULL,
            field_type  TEXT NOT NULL,
            options     TEXT DEFAULT '',
            sort_order  INTEGER DEFAULT 0,
            required    INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(schema_id, name)
        );

        CREATE TABLE IF NOT EXISTS items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            schema_id   INTEGER NOT NULL REFERENCES schemas(id) ON DELETE CASCADE,
            title       TEXT NOT NULL DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS item_values (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id     INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            field_id    INTEGER NOT NULL REFERENCES schema_fields(id) ON DELETE CASCADE,
            value       TEXT DEFAULT '',
            UNIQUE(item_id, field_id)
        );

        CREATE TABLE IF NOT EXISTS whiteboards (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            description TEXT DEFAULT '',
            viewport_x  REAL DEFAULT 0,
            viewport_y  REAL DEFAULT 0,
            viewport_zoom REAL DEFAULT 1.0,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS cards (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            whiteboard_id INTEGER NOT NULL REFERENCES whiteboards(id) ON DELETE CASCADE,
            title       TEXT NOT NULL DEFAULT '',
            schema_id   INTEGER REFERENCES schemas(id) ON DELETE SET NULL,
            pos_x       REAL DEFAULT 100,
            pos_y       REAL DEFAULT 100,
            width       REAL DEFAULT 280,
            height      REAL DEFAULT 0,
            color       TEXT DEFAULT '#ffffff',
            z_index     INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS card_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id     INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
            item_id     INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            sort_order  INTEGER DEFAULT 0,
            UNIQUE(card_id, item_id)
        );

        CREATE TABLE IF NOT EXISTS tags (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            color       TEXT DEFAULT '#6b7280',
            is_group    INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS card_tags (
            card_id     INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
            tag_id      INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (card_id, tag_id)
        );

        CREATE TABLE IF NOT EXISTS connections (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            whiteboard_id INTEGER NOT NULL REFERENCES whiteboards(id) ON DELETE CASCADE,
            source_card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
            target_card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
            label       TEXT DEFAULT '',
            line_style  TEXT DEFAULT 'solid',
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(whiteboard_id, source_card_id, target_card_id)
        );

        CREATE INDEX IF NOT EXISTS idx_schema_fields_schema ON schema_fields(schema_id);
        CREATE INDEX IF NOT EXISTS idx_items_schema ON items(schema_id);
        CREATE INDEX IF NOT EXISTS idx_item_values_item ON item_values(item_id);
        CREATE INDEX IF NOT EXISTS idx_item_values_field ON item_values(field_id);
        CREATE INDEX IF NOT EXISTS idx_cards_whiteboard ON cards(whiteboard_id);
        CREATE INDEX IF NOT EXISTS idx_card_items_card ON card_items(card_id);
        CREATE INDEX IF NOT EXISTS idx_card_items_item ON card_items(item_id);
        CREATE INDEX IF NOT EXISTS idx_connections_whiteboard ON connections(whiteboard_id);
    """)
    conn.commit()
    conn.close()
