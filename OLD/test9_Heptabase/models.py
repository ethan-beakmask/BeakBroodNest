"""資料存取層 - 所有 SQL 操作封裝"""
import json
from db import get_conn


# ============================================================
# Schema 操作
# ============================================================

def get_all_schemas():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM schemas ORDER BY created_at"
    ).fetchall()
    result = [dict(r) for r in rows]
    conn.close()
    return result


def get_schema(schema_id):
    conn = get_conn()
    schema = conn.execute(
        "SELECT * FROM schemas WHERE id = ?", (schema_id,)
    ).fetchone()
    if not schema:
        conn.close()
        return None

    fields = conn.execute(
        "SELECT * FROM schema_fields WHERE schema_id = ? ORDER BY sort_order",
        (schema_id,)
    ).fetchall()

    result = dict(schema)
    result['fields'] = [dict(f) for f in fields]
    conn.close()
    return result


def create_schema(name, slug, description='', icon=''):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO schemas (name, slug, description, icon) VALUES (?, ?, ?, ?)",
        (name, slug, description, icon)
    )
    schema_id = cur.lastrowid
    conn.commit()
    conn.close()
    return schema_id


def update_schema(schema_id, name=None, slug=None, description=None, icon=None):
    conn = get_conn()
    updates = []
    params = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if slug is not None:
        updates.append("slug = ?")
        params.append(slug)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if icon is not None:
        updates.append("icon = ?")
        params.append(icon)
    if updates:
        updates.append("updated_at = datetime('now','localtime')")
        params.append(schema_id)
        conn.execute(
            f"UPDATE schemas SET {', '.join(updates)} WHERE id = ?", params
        )
        conn.commit()
    conn.close()


def delete_schema(schema_id):
    conn = get_conn()
    conn.execute("DELETE FROM schemas WHERE id = ?", (schema_id,))
    conn.commit()
    conn.close()


def update_schema_fields(schema_id, fields):
    """批次更新 schema 欄位（刪除舊的，插入新的）"""
    conn = get_conn()
    conn.execute("DELETE FROM schema_fields WHERE schema_id = ?", (schema_id,))
    for i, f in enumerate(fields):
        conn.execute(
            "INSERT INTO schema_fields (schema_id, name, label, field_type, options, sort_order, required) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (schema_id, f['name'], f['label'], f['field_type'],
             f.get('options', ''), i, f.get('required', 0))
        )
    conn.execute(
        "UPDATE schemas SET updated_at = datetime('now','localtime') WHERE id = ?",
        (schema_id,)
    )
    conn.commit()
    conn.close()


# ============================================================
# Item 操作
# ============================================================

def get_items_by_schema(schema_id):
    """取得某 schema 下所有 items（含欄位值，已 pivot）"""
    conn = get_conn()

    # 取得欄位定義
    fields = conn.execute(
        "SELECT id, name, label, field_type, options FROM schema_fields "
        "WHERE schema_id = ? ORDER BY sort_order",
        (schema_id,)
    ).fetchall()
    fields = [dict(f) for f in fields]
    field_map = {f['id']: f for f in fields}

    # 取得所有 items
    items = conn.execute(
        "SELECT * FROM items WHERE schema_id = ? ORDER BY created_at DESC",
        (schema_id,)
    ).fetchall()
    items = [dict(i) for i in items]
    item_ids = [i['id'] for i in items]

    if not item_ids:
        conn.close()
        return {'fields': fields, 'items': []}

    # 取得所有 values（一次查詢）
    placeholders = ','.join('?' * len(item_ids))
    values = conn.execute(
        f"SELECT item_id, field_id, value FROM item_values WHERE item_id IN ({placeholders})",
        item_ids
    ).fetchall()

    # pivot 組裝
    value_map = {}
    for v in values:
        key = v['item_id']
        if key not in value_map:
            value_map[key] = {}
        field = field_map.get(v['field_id'])
        if field:
            value_map[key][field['name']] = v['value']

    for item in items:
        item['values'] = value_map.get(item['id'], {})

    conn.close()
    return {'fields': fields, 'items': items}


def get_item(item_id):
    """取得單一 item 含欄位值"""
    conn = get_conn()
    item = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        conn.close()
        return None

    item = dict(item)
    fields = conn.execute(
        "SELECT sf.id, sf.name, sf.label, sf.field_type, sf.options "
        "FROM schema_fields sf WHERE sf.schema_id = ? ORDER BY sf.sort_order",
        (item['schema_id'],)
    ).fetchall()

    values = conn.execute(
        "SELECT field_id, value FROM item_values WHERE item_id = ?",
        (item_id,)
    ).fetchall()

    field_map = {f['id']: dict(f) for f in fields}
    item['fields'] = [dict(f) for f in fields]
    item['values'] = {}
    for v in values:
        field = field_map.get(v['field_id'])
        if field:
            item['values'][field['name']] = v['value']

    conn.close()
    return item


def create_item(schema_id, title, values_dict):
    """建立 item 及其欄位值"""
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO items (schema_id, title) VALUES (?, ?)",
        (schema_id, title)
    )
    item_id = cur.lastrowid

    # 取得 field name -> id 對照
    fields = conn.execute(
        "SELECT id, name FROM schema_fields WHERE schema_id = ?",
        (schema_id,)
    ).fetchall()
    field_name_to_id = {f['name']: f['id'] for f in fields}

    for name, value in values_dict.items():
        field_id = field_name_to_id.get(name)
        if field_id and value:
            conn.execute(
                "INSERT INTO item_values (item_id, field_id, value) VALUES (?, ?, ?)",
                (item_id, field_id, str(value))
            )

    conn.commit()
    conn.close()
    return item_id


def update_item(item_id, title=None, values_dict=None):
    """更新 item 及其欄位值"""
    conn = get_conn()

    if title is not None:
        conn.execute(
            "UPDATE items SET title = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (title, item_id)
        )

    if values_dict is not None:
        item = conn.execute("SELECT schema_id FROM items WHERE id = ?", (item_id,)).fetchone()
        if item:
            fields = conn.execute(
                "SELECT id, name FROM schema_fields WHERE schema_id = ?",
                (item['schema_id'],)
            ).fetchall()
            field_name_to_id = {f['name']: f['id'] for f in fields}

            for name, value in values_dict.items():
                field_id = field_name_to_id.get(name)
                if field_id:
                    conn.execute(
                        "INSERT INTO item_values (item_id, field_id, value) VALUES (?, ?, ?) "
                        "ON CONFLICT(item_id, field_id) DO UPDATE SET value = ?",
                        (item_id, field_id, str(value), str(value))
                    )

            conn.execute(
                "UPDATE items SET updated_at = datetime('now','localtime') WHERE id = ?",
                (item_id,)
            )

    conn.commit()
    conn.close()


def delete_item(item_id):
    conn = get_conn()
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


# ============================================================
# Whiteboard 操作
# ============================================================

def get_all_whiteboards():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM whiteboards ORDER BY created_at").fetchall()
    result = [dict(r) for r in rows]
    conn.close()
    return result


def get_whiteboard(wb_id):
    """取得白板完整資料（含 cards、card_items、connections、tags）"""
    conn = get_conn()
    wb = conn.execute("SELECT * FROM whiteboards WHERE id = ?", (wb_id,)).fetchone()
    if not wb:
        conn.close()
        return None

    wb = dict(wb)

    # 取得卡片
    cards = conn.execute(
        "SELECT * FROM cards WHERE whiteboard_id = ? ORDER BY z_index",
        (wb_id,)
    ).fetchall()
    cards = [dict(c) for c in cards]
    card_ids = [c['id'] for c in cards]

    # 取得卡片關聯的 items
    if card_ids:
        placeholders = ','.join('?' * len(card_ids))
        card_items_rows = conn.execute(
            f"SELECT ci.card_id, ci.item_id, ci.sort_order, "
            f"i.title, i.schema_id "
            f"FROM card_items ci JOIN items i ON ci.item_id = i.id "
            f"WHERE ci.card_id IN ({placeholders}) ORDER BY ci.sort_order",
            card_ids
        ).fetchall()

        # 取得 item values
        item_ids = list(set(r['item_id'] for r in card_items_rows))
        item_values_map = {}
        if item_ids:
            ip = ','.join('?' * len(item_ids))
            vals = conn.execute(
                f"SELECT iv.item_id, sf.name, iv.value "
                f"FROM item_values iv JOIN schema_fields sf ON iv.field_id = sf.id "
                f"WHERE iv.item_id IN ({ip})",
                item_ids
            ).fetchall()
            for v in vals:
                if v['item_id'] not in item_values_map:
                    item_values_map[v['item_id']] = {}
                item_values_map[v['item_id']][v['name']] = v['value']

        card_items_map = {}
        for r in card_items_rows:
            if r['card_id'] not in card_items_map:
                card_items_map[r['card_id']] = []
            card_items_map[r['card_id']].append({
                'item_id': r['item_id'],
                'title': r['title'],
                'schema_id': r['schema_id'],
                'sort_order': r['sort_order'],
                'values': item_values_map.get(r['item_id'], {}),
            })

        # 取得 card tags
        card_tags_rows = conn.execute(
            f"SELECT ct.card_id, t.id as tag_id, t.name, t.color, t.is_group "
            f"FROM card_tags ct JOIN tags t ON ct.tag_id = t.id "
            f"WHERE ct.card_id IN ({placeholders})",
            card_ids
        ).fetchall()

        card_tags_map = {}
        for r in card_tags_rows:
            if r['card_id'] not in card_tags_map:
                card_tags_map[r['card_id']] = []
            card_tags_map[r['card_id']].append({
                'tag_id': r['tag_id'],
                'name': r['name'],
                'color': r['color'],
                'is_group': r['is_group'],
            })

        for card in cards:
            card['items'] = card_items_map.get(card['id'], [])
            card['tags'] = card_tags_map.get(card['id'], [])
    else:
        for card in cards:
            card['items'] = []
            card['tags'] = []

    wb['cards'] = cards

    # 取得連線
    connections = conn.execute(
        "SELECT * FROM connections WHERE whiteboard_id = ?",
        (wb_id,)
    ).fetchall()
    wb['connections'] = [dict(c) for c in connections]

    conn.close()
    return wb


def create_whiteboard(name, description=''):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO whiteboards (name, description) VALUES (?, ?)",
        (name, description)
    )
    wb_id = cur.lastrowid
    conn.commit()
    conn.close()
    return wb_id


def update_whiteboard(wb_id, **kwargs):
    conn = get_conn()
    updates = []
    params = []
    for key in ('name', 'description', 'viewport_x', 'viewport_y', 'viewport_zoom'):
        if key in kwargs:
            updates.append(f"{key} = ?")
            params.append(kwargs[key])
    if updates:
        updates.append("updated_at = datetime('now','localtime')")
        params.append(wb_id)
        conn.execute(
            f"UPDATE whiteboards SET {', '.join(updates)} WHERE id = ?", params
        )
        conn.commit()
    conn.close()


def delete_whiteboard(wb_id):
    conn = get_conn()
    conn.execute("DELETE FROM whiteboards WHERE id = ?", (wb_id,))
    conn.commit()
    conn.close()


# ============================================================
# Card 操作
# ============================================================

def create_card(whiteboard_id, title='', schema_id=None, pos_x=100, pos_y=100, color='#ffffff'):
    conn = get_conn()
    # 取得最大 z_index
    row = conn.execute(
        "SELECT COALESCE(MAX(z_index), 0) + 1 AS next_z FROM cards WHERE whiteboard_id = ?",
        (whiteboard_id,)
    ).fetchone()
    z = row['next_z']

    cur = conn.execute(
        "INSERT INTO cards (whiteboard_id, title, schema_id, pos_x, pos_y, color, z_index) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (whiteboard_id, title, schema_id, pos_x, pos_y, color, z)
    )
    card_id = cur.lastrowid
    conn.commit()
    conn.close()
    return card_id


def update_card(card_id, **kwargs):
    conn = get_conn()
    updates = []
    params = []
    for key in ('title', 'schema_id', 'pos_x', 'pos_y', 'width', 'height', 'color', 'z_index'):
        if key in kwargs:
            updates.append(f"{key} = ?")
            params.append(kwargs[key])
    if updates:
        updates.append("updated_at = datetime('now','localtime')")
        params.append(card_id)
        conn.execute(
            f"UPDATE cards SET {', '.join(updates)} WHERE id = ?", params
        )
        conn.commit()
    conn.close()


def delete_card(card_id):
    conn = get_conn()
    conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    conn.commit()
    conn.close()


def add_item_to_card(card_id, item_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort FROM card_items WHERE card_id = ?",
        (card_id,)
    ).fetchone()
    conn.execute(
        "INSERT OR IGNORE INTO card_items (card_id, item_id, sort_order) VALUES (?, ?, ?)",
        (card_id, item_id, row['next_sort'])
    )
    conn.commit()
    conn.close()


def remove_item_from_card(card_id, item_id):
    conn = get_conn()
    conn.execute(
        "DELETE FROM card_items WHERE card_id = ? AND item_id = ?",
        (card_id, item_id)
    )
    conn.commit()
    conn.close()


def move_item_between_cards(item_id, source_card_id, target_card_id):
    """將 item 從一張卡片移動到另一張"""
    conn = get_conn()
    conn.execute(
        "DELETE FROM card_items WHERE card_id = ? AND item_id = ?",
        (source_card_id, item_id)
    )
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort FROM card_items WHERE card_id = ?",
        (target_card_id,)
    ).fetchone()
    conn.execute(
        "INSERT OR IGNORE INTO card_items (card_id, item_id, sort_order) VALUES (?, ?, ?)",
        (target_card_id, item_id, row['next_sort'])
    )
    conn.execute(
        "UPDATE items SET updated_at = datetime('now','localtime') WHERE id = ?",
        (item_id,)
    )
    conn.commit()
    conn.close()


def copy_item_to_card(item_id, target_card_id):
    """複製 item 關聯到另一張卡片（不移除來源）"""
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort FROM card_items WHERE card_id = ?",
        (target_card_id,)
    ).fetchone()
    conn.execute(
        "INSERT OR IGNORE INTO card_items (card_id, item_id, sort_order) VALUES (?, ?, ?)",
        (target_card_id, item_id, row['next_sort'])
    )
    conn.commit()
    conn.close()


# ============================================================
# Tag 操作
# ============================================================

def get_all_tags():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM tags ORDER BY is_group DESC, name").fetchall()
    result = [dict(r) for r in rows]
    conn.close()
    return result


def create_tag(name, color='#6b7280', is_group=0):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO tags (name, color, is_group) VALUES (?, ?, ?)",
        (name, color, is_group)
    )
    tag_id = cur.lastrowid
    conn.commit()
    conn.close()
    return tag_id


def delete_tag(tag_id):
    conn = get_conn()
    conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    conn.commit()
    conn.close()


def update_tag(tag_id, **kwargs):
    conn = get_conn()
    updates = []
    params = []
    for key in ('name', 'color', 'is_group'):
        if key in kwargs:
            updates.append(f"{key} = ?")
            params.append(kwargs[key])
    if updates:
        params.append(tag_id)
        conn.execute(
            f"UPDATE tags SET {', '.join(updates)} WHERE id = ?", params
        )
        conn.commit()
    conn.close()


def add_tag_to_card(card_id, tag_id):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO card_tags (card_id, tag_id) VALUES (?, ?)",
        (card_id, tag_id)
    )
    conn.commit()
    conn.close()


def remove_tag_from_card(card_id, tag_id):
    conn = get_conn()
    conn.execute(
        "DELETE FROM card_tags WHERE card_id = ? AND tag_id = ?",
        (card_id, tag_id)
    )
    conn.commit()
    conn.close()


# ============================================================
# Connection 操作
# ============================================================

def create_connection(whiteboard_id, source_card_id, target_card_id, label='', line_style='solid'):
    conn = get_conn()
    cur = conn.execute(
        "INSERT OR IGNORE INTO connections (whiteboard_id, source_card_id, target_card_id, label, line_style) "
        "VALUES (?, ?, ?, ?, ?)",
        (whiteboard_id, source_card_id, target_card_id, label, line_style)
    )
    conn_id = cur.lastrowid
    conn.commit()
    conn.close()
    return conn_id


def update_connection(conn_id, **kwargs):
    db = get_conn()
    updates = []
    params = []
    for key in ('label', 'line_style'):
        if key in kwargs:
            updates.append(f"{key} = ?")
            params.append(kwargs[key])
    if updates:
        params.append(conn_id)
        db.execute(
            f"UPDATE connections SET {', '.join(updates)} WHERE id = ?", params
        )
        db.commit()
    db.close()


def delete_connection(conn_id):
    conn = get_conn()
    conn.execute("DELETE FROM connections WHERE id = ?", (conn_id,))
    conn.commit()
    conn.close()


# ============================================================
# 知識地圖資料
# ============================================================

def get_knowledge_map(whiteboard_id):
    """產生知識地圖資料：以 tag/group 聚合卡片"""
    conn = get_conn()

    cards = conn.execute(
        "SELECT id, title, pos_x, pos_y FROM cards WHERE whiteboard_id = ?",
        (whiteboard_id,)
    ).fetchall()
    cards = [dict(c) for c in cards]
    card_ids = [c['id'] for c in cards]

    if not card_ids:
        conn.close()
        return {'groups': [], 'tags': [], 'cards': cards, 'connections': []}

    placeholders = ','.join('?' * len(card_ids))

    # 取得 tags 與 card 關聯
    tag_cards = conn.execute(
        f"SELECT ct.card_id, t.id as tag_id, t.name, t.color, t.is_group "
        f"FROM card_tags ct JOIN tags t ON ct.tag_id = t.id "
        f"WHERE ct.card_id IN ({placeholders})",
        card_ids
    ).fetchall()

    groups = {}
    tags = {}
    for tc in tag_cards:
        target = groups if tc['is_group'] else tags
        if tc['tag_id'] not in target:
            target[tc['tag_id']] = {
                'id': tc['tag_id'],
                'name': tc['name'],
                'color': tc['color'],
                'card_ids': [],
            }
        target[tc['tag_id']]['card_ids'].append(tc['card_id'])

    connections = conn.execute(
        "SELECT * FROM connections WHERE whiteboard_id = ?",
        (whiteboard_id,)
    ).fetchall()

    conn.close()
    return {
        'groups': list(groups.values()),
        'tags': list(tags.values()),
        'cards': cards,
        'connections': [dict(c) for c in connections],
    }


def get_unassigned_items(schema_id=None):
    """取得未關聯到任何卡片的 items"""
    conn = get_conn()
    if schema_id:
        rows = conn.execute(
            "SELECT i.* FROM items i "
            "LEFT JOIN card_items ci ON i.id = ci.item_id "
            "WHERE ci.id IS NULL AND i.schema_id = ? "
            "ORDER BY i.created_at DESC",
            (schema_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT i.*, s.name as schema_name FROM items i "
            "LEFT JOIN card_items ci ON i.id = ci.item_id "
            "JOIN schemas s ON i.schema_id = s.id "
            "WHERE ci.id IS NULL "
            "ORDER BY i.created_at DESC"
        ).fetchall()
    result = [dict(r) for r in rows]
    conn.close()
    return result
