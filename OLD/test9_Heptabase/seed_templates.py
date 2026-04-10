"""預設模板：行事曆、採購單、開會前置準備"""
from db import get_conn

SEED_SCHEMAS = [
    {
        'name': '行事曆',
        'slug': 'calendar',
        'description': '個人與工作行程管理',
        'icon': 'CAL',
        'fields': [
            {'name': 'category', 'label': '類別', 'field_type': 'select',
             'options': '["公司","家庭","私人"]', 'sort_order': 1, 'required': 1},
            {'name': 'event_name', 'label': '事項名稱', 'field_type': 'text', 'sort_order': 2, 'required': 1},
            {'name': 'time', 'label': '時間', 'field_type': 'datetime', 'sort_order': 3, 'required': 1},
            {'name': 'location', 'label': '地點', 'field_type': 'text', 'sort_order': 4},
            {'name': 'person', 'label': '對象', 'field_type': 'text', 'sort_order': 5},
            {'name': 'items', 'label': '相關物品', 'field_type': 'text', 'sort_order': 6},
            {'name': 'contact', 'label': '聯絡方式', 'field_type': 'text', 'sort_order': 7},
        ]
    },
    {
        'name': '採購單',
        'slug': 'shopping-list',
        'description': '採購項目追蹤',
        'icon': 'BUY',
        'fields': [
            {'name': 'item_name', 'label': '品名', 'field_type': 'text', 'sort_order': 1, 'required': 1},
            {'name': 'quantity', 'label': '數量', 'field_type': 'number', 'sort_order': 2, 'required': 1},
            {'name': 'unit', 'label': '單位', 'field_type': 'text', 'sort_order': 3},
            {'name': 'category', 'label': '分類', 'field_type': 'select',
             'options': '["食品","電子產品","辦公用品","其他"]', 'sort_order': 4},
            {'name': 'priority', 'label': '優先順序', 'field_type': 'select',
             'options': '["高","中","低"]', 'sort_order': 5},
            {'name': 'notes', 'label': '備註', 'field_type': 'textarea', 'sort_order': 6},
        ]
    },
    {
        'name': '開會前置準備',
        'slug': 'meeting-prep',
        'description': '會議準備清單與追蹤',
        'icon': 'MTG',
        'fields': [
            {'name': 'meeting_name', 'label': '會議名稱', 'field_type': 'text', 'sort_order': 1, 'required': 1},
            {'name': 'date', 'label': '日期時間', 'field_type': 'datetime', 'sort_order': 2, 'required': 1},
            {'name': 'attendees', 'label': '出席者', 'field_type': 'textarea', 'sort_order': 3},
            {'name': 'agenda', 'label': '議程', 'field_type': 'textarea', 'sort_order': 4},
            {'name': 'materials', 'label': '準備資料', 'field_type': 'textarea', 'sort_order': 5},
            {'name': 'action_items', 'label': '待辦事項', 'field_type': 'textarea', 'sort_order': 6},
        ]
    },
]

SEED_ITEMS = [
    {
        'schema_slug': 'calendar',
        'title': '季度業績檢討會議',
        'values': {
            'category': '公司',
            'event_name': '季度業績檢討會議',
            'time': '2026-03-15 09:00',
            'location': '會議室 A',
            'person': '全體主管',
            'items': '報表、簡報',
            'contact': 'ext. 200',
        }
    },
    {
        'schema_slug': 'calendar',
        'title': '家庭聚餐',
        'values': {
            'category': '家庭',
            'event_name': '家庭聚餐',
            'time': '2026-03-16 18:00',
            'location': '老字號餐廳',
            'person': '家人',
            'items': '',
            'contact': '',
        }
    },
    {
        'schema_slug': 'calendar',
        'title': '健身房',
        'values': {
            'category': '私人',
            'event_name': '健身房',
            'time': '2026-03-17 07:00',
            'location': '社區健身房',
            'person': '',
            'items': '運動服、水壺',
            'contact': '',
        }
    },
    {
        'schema_slug': 'shopping-list',
        'title': '影印紙 A4',
        'values': {
            'item_name': '影印紙 A4',
            'quantity': '5',
            'unit': '包',
            'category': '辦公用品',
            'priority': '高',
            'notes': '庫存快用完了',
        }
    },
    {
        'schema_slug': 'shopping-list',
        'title': '咖啡豆',
        'values': {
            'item_name': '咖啡豆',
            'quantity': '2',
            'unit': '磅',
            'category': '食品',
            'priority': '中',
            'notes': '中深焙',
        }
    },
    {
        'schema_slug': 'meeting-prep',
        'title': '資安週報會議',
        'values': {
            'meeting_name': '資安週報會議',
            'date': '2026-03-14 14:00',
            'attendees': '資安組全體\nIT 主管',
            'agenda': '1. 上週事件回顧\n2. 弱點掃描報告\n3. 下週排程',
            'materials': 'SIEM 報表\n弱掃結果匯出',
            'action_items': '更新防火牆規則\n完成季度報告初稿',
        }
    },
]


def seed_data():
    """填入測試模板資料"""
    conn = get_conn()
    cur = conn.cursor()

    # 檢查是否已有資料
    existing = cur.execute("SELECT COUNT(*) FROM schemas").fetchone()[0]
    if existing > 0:
        conn.close()
        return False

    # 建立 schemas 和 fields
    schema_id_map = {}
    field_name_map = {}  # {(schema_id, field_name): field_id}

    for s in SEED_SCHEMAS:
        cur.execute(
            "INSERT INTO schemas (name, slug, description, icon) VALUES (?, ?, ?, ?)",
            (s['name'], s['slug'], s['description'], s['icon'])
        )
        schema_id = cur.lastrowid
        schema_id_map[s['slug']] = schema_id

        for f in s['fields']:
            cur.execute(
                "INSERT INTO schema_fields (schema_id, name, label, field_type, options, sort_order, required) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (schema_id, f['name'], f['label'], f['field_type'],
                 f.get('options', ''), f['sort_order'], f.get('required', 0))
            )
            field_name_map[(schema_id, f['name'])] = cur.lastrowid

    # 建立 items
    for item in SEED_ITEMS:
        schema_id = schema_id_map[item['schema_slug']]
        cur.execute(
            "INSERT INTO items (schema_id, title) VALUES (?, ?)",
            (schema_id, item['title'])
        )
        item_id = cur.lastrowid

        for field_name, value in item['values'].items():
            field_id = field_name_map.get((schema_id, field_name))
            if field_id and value:
                cur.execute(
                    "INSERT INTO item_values (item_id, field_id, value) VALUES (?, ?, ?)",
                    (item_id, field_id, value)
                )

    # 建立預設白板
    cur.execute(
        "INSERT INTO whiteboards (name, description) VALUES (?, ?)",
        ('我的白板', '預設工作白板')
    )

    conn.commit()
    conn.close()
    return True
