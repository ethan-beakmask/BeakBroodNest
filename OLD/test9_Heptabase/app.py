"""Heptabase MVP - Flask 應用入口

用法:
    python3 app.py              顯示使用說明
    python3 app.py --serve      啟動 Web 伺服器
    python3 app.py --port 5000  指定埠號（預設 5555）
    python3 app.py --reset      重置資料庫（刪除後重建 + seed）
"""
import argparse
import os
import sys
import json

from flask import Flask, render_template, request, jsonify, redirect, url_for
from db import init_db, DB_PATH
from seed_templates import seed_data
import models

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

LAN_IP = '192.168.0.16'
DEFAULT_PORT = 5555


# ============================================================
# 頁面路由
# ============================================================

@app.route('/')
def index():
    """首頁：重導到預設白板"""
    wbs = models.get_all_whiteboards()
    if wbs:
        return redirect(url_for('whiteboard_page', wb_id=wbs[0]['id']))
    # 無白板則建立預設
    wb_id = models.create_whiteboard('我的白板', '預設工作白板')
    return redirect(url_for('whiteboard_page', wb_id=wb_id))


@app.route('/whiteboard/<int:wb_id>')
def whiteboard_page(wb_id):
    """白板主頁面"""
    return render_template('index.html', wb_id=wb_id)


@app.route('/schemas')
def schemas_page():
    """Schema 管理頁面"""
    return render_template('schemas.html')


@app.route('/items/<int:schema_id>')
def items_page(schema_id):
    """Item 瀏覽頁面"""
    return render_template('items.html', schema_id=schema_id)


# ============================================================
# Schema API
# ============================================================

@app.route('/api/schemas', methods=['GET'])
def api_get_schemas():
    return jsonify(models.get_all_schemas())


@app.route('/api/schemas', methods=['POST'])
def api_create_schema():
    data = request.json
    schema_id = models.create_schema(
        data['name'], data['slug'],
        data.get('description', ''), data.get('icon', '')
    )
    if 'fields' in data:
        models.update_schema_fields(schema_id, data['fields'])
    return jsonify({'id': schema_id}), 201


@app.route('/api/schemas/<int:schema_id>', methods=['GET'])
def api_get_schema(schema_id):
    schema = models.get_schema(schema_id)
    if not schema:
        return jsonify({'error': 'not found'}), 404
    return jsonify(schema)


@app.route('/api/schemas/<int:schema_id>', methods=['PUT'])
def api_update_schema(schema_id):
    data = request.json
    models.update_schema(schema_id, **{
        k: v for k, v in data.items() if k in ('name', 'slug', 'description', 'icon')
    })
    if 'fields' in data:
        models.update_schema_fields(schema_id, data['fields'])
    return jsonify({'ok': True})


@app.route('/api/schemas/<int:schema_id>', methods=['DELETE'])
def api_delete_schema(schema_id):
    models.delete_schema(schema_id)
    return jsonify({'ok': True})


# ============================================================
# Item API
# ============================================================

@app.route('/api/items', methods=['GET'])
def api_get_items():
    schema_id = request.args.get('schema_id', type=int)
    if not schema_id:
        return jsonify({'error': 'schema_id required'}), 400
    return jsonify(models.get_items_by_schema(schema_id))


@app.route('/api/items', methods=['POST'])
def api_create_item():
    data = request.json
    item_id = models.create_item(
        data['schema_id'], data.get('title', ''),
        data.get('values', {})
    )
    return jsonify({'id': item_id}), 201


@app.route('/api/items/<int:item_id>', methods=['GET'])
def api_get_item(item_id):
    item = models.get_item(item_id)
    if not item:
        return jsonify({'error': 'not found'}), 404
    return jsonify(item)


@app.route('/api/items/<int:item_id>', methods=['PUT'])
def api_update_item(item_id):
    data = request.json
    models.update_item(
        item_id,
        title=data.get('title'),
        values_dict=data.get('values')
    )
    return jsonify({'ok': True})


@app.route('/api/items/<int:item_id>', methods=['DELETE'])
def api_delete_item(item_id):
    models.delete_item(item_id)
    return jsonify({'ok': True})


@app.route('/api/items/unassigned', methods=['GET'])
def api_get_unassigned_items():
    schema_id = request.args.get('schema_id', type=int)
    return jsonify(models.get_unassigned_items(schema_id))


# ============================================================
# Whiteboard API
# ============================================================

@app.route('/api/whiteboards', methods=['GET'])
def api_get_whiteboards():
    return jsonify(models.get_all_whiteboards())


@app.route('/api/whiteboards', methods=['POST'])
def api_create_whiteboard():
    data = request.json
    wb_id = models.create_whiteboard(data['name'], data.get('description', ''))
    return jsonify({'id': wb_id}), 201


@app.route('/api/whiteboards/<int:wb_id>', methods=['GET'])
def api_get_whiteboard(wb_id):
    wb = models.get_whiteboard(wb_id)
    if not wb:
        return jsonify({'error': 'not found'}), 404
    return jsonify(wb)


@app.route('/api/whiteboards/<int:wb_id>', methods=['PUT'])
def api_update_whiteboard(wb_id):
    data = request.json
    models.update_whiteboard(wb_id, **{
        k: v for k, v in data.items()
        if k in ('name', 'description', 'viewport_x', 'viewport_y', 'viewport_zoom')
    })
    return jsonify({'ok': True})


@app.route('/api/whiteboards/<int:wb_id>', methods=['DELETE'])
def api_delete_whiteboard(wb_id):
    models.delete_whiteboard(wb_id)
    return jsonify({'ok': True})


# ============================================================
# Card API
# ============================================================

@app.route('/api/cards', methods=['POST'])
def api_create_card():
    data = request.json
    card_id = models.create_card(
        data['whiteboard_id'],
        data.get('title', ''),
        data.get('schema_id'),
        data.get('pos_x', 100),
        data.get('pos_y', 100),
        data.get('color', '#ffffff')
    )
    return jsonify({'id': card_id}), 201


@app.route('/api/cards/<int:card_id>', methods=['PUT'])
def api_update_card(card_id):
    data = request.json
    models.update_card(card_id, **{
        k: v for k, v in data.items()
        if k in ('title', 'schema_id', 'pos_x', 'pos_y', 'width', 'height', 'color', 'z_index')
    })
    return jsonify({'ok': True})


@app.route('/api/cards/<int:card_id>', methods=['DELETE'])
def api_delete_card(card_id):
    models.delete_card(card_id)
    return jsonify({'ok': True})


@app.route('/api/cards/<int:card_id>/items', methods=['POST'])
def api_add_item_to_card(card_id):
    data = request.json
    models.add_item_to_card(card_id, data['item_id'])
    return jsonify({'ok': True}), 201


@app.route('/api/cards/<int:card_id>/items/<int:item_id>', methods=['DELETE'])
def api_remove_item_from_card(card_id, item_id):
    models.remove_item_from_card(card_id, item_id)
    return jsonify({'ok': True})


@app.route('/api/card-items/move', methods=['PUT'])
def api_move_item():
    data = request.json
    models.move_item_between_cards(
        data['item_id'], data['source_card_id'], data['target_card_id']
    )
    return jsonify({'ok': True})


@app.route('/api/card-items/copy', methods=['POST'])
def api_copy_item():
    data = request.json
    models.copy_item_to_card(data['item_id'], data['target_card_id'])
    return jsonify({'ok': True})


# ============================================================
# Tag API
# ============================================================

@app.route('/api/tags', methods=['GET'])
def api_get_tags():
    return jsonify(models.get_all_tags())


@app.route('/api/tags', methods=['POST'])
def api_create_tag():
    data = request.json
    tag_id = models.create_tag(
        data['name'], data.get('color', '#6b7280'), data.get('is_group', 0)
    )
    return jsonify({'id': tag_id}), 201


@app.route('/api/tags/<int:tag_id>', methods=['PUT'])
def api_update_tag(tag_id):
    data = request.json
    models.update_tag(tag_id, **{
        k: v for k, v in data.items() if k in ('name', 'color', 'is_group')
    })
    return jsonify({'ok': True})


@app.route('/api/tags/<int:tag_id>', methods=['DELETE'])
def api_delete_tag(tag_id):
    models.delete_tag(tag_id)
    return jsonify({'ok': True})


@app.route('/api/cards/<int:card_id>/tags', methods=['POST'])
def api_add_tag_to_card(card_id):
    data = request.json
    models.add_tag_to_card(card_id, data['tag_id'])
    return jsonify({'ok': True}), 201


@app.route('/api/cards/<int:card_id>/tags/<int:tag_id>', methods=['DELETE'])
def api_remove_tag_from_card(card_id, tag_id):
    models.remove_tag_from_card(card_id, tag_id)
    return jsonify({'ok': True})


# ============================================================
# Connection API
# ============================================================

@app.route('/api/connections', methods=['POST'])
def api_create_connection():
    data = request.json
    conn_id = models.create_connection(
        data['whiteboard_id'], data['source_card_id'], data['target_card_id'],
        data.get('label', ''), data.get('line_style', 'solid')
    )
    return jsonify({'id': conn_id}), 201


@app.route('/api/connections/<int:conn_id>', methods=['PUT'])
def api_update_connection(conn_id):
    data = request.json
    models.update_connection(conn_id, **{
        k: v for k, v in data.items() if k in ('label', 'line_style')
    })
    return jsonify({'ok': True})


@app.route('/api/connections/<int:conn_id>', methods=['DELETE'])
def api_delete_connection(conn_id):
    models.delete_connection(conn_id)
    return jsonify({'ok': True})


# ============================================================
# Knowledge Map API
# ============================================================

@app.route('/api/knowledge-map/<int:wb_id>', methods=['GET'])
def api_knowledge_map(wb_id):
    return jsonify(models.get_knowledge_map(wb_id))


# ============================================================
# 啟動
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Heptabase MVP - 類 Heptabase 知識白板系統',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python3 app.py --serve           啟動伺服器（預設埠 5555）
  python3 app.py --serve --port 8080  指定埠號
  python3 app.py --reset           重置資料庫
        """
    )
    parser.add_argument('--serve', action='store_true', help='啟動 Web 伺服器')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help=f'伺服器埠號（預設 {DEFAULT_PORT}）')
    parser.add_argument('--reset', action='store_true', help='重置資料庫（刪除後重建）')

    args = parser.parse_args()

    if not args.serve and not args.reset:
        parser.print_help()
        sys.exit(0)

    if args.reset:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
            print(f"已刪除資料庫: {DB_PATH}")

    # 初始化資料庫
    init_db()
    seeded = seed_data()
    if seeded:
        print("已填入測試模板資料")

    if args.serve:
        print(f"\n啟動伺服器: http://{LAN_IP}:{args.port}")
        print(f"本機測試:   http://127.0.0.1:{args.port}")
        app.run(host='0.0.0.0', port=args.port, debug=True)


if __name__ == '__main__':
    main()
