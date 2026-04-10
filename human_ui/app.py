#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakNote -- 人類介面 Flask 入口
Phase 0: 知識原子 / 因果鍊 / 白板 / 標籤 CRUD API
"""
import argparse
import sys
import os
import json
import datetime
import configparser
import logging
from pathlib import Path

# 讓 core 可以被 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, request, jsonify, render_template
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from core.db import init_engine, get_session, session_scope, create_all_tables, Base, get_engine
from core.models import (
    KnowledgeAtom, AtomRelation, Canvas, CanvasAtom, CanvasConnection,
    Tag, atom_tags, AtomSchema, SchemaField, AtomFieldValue,
)
from core import relations as rel_service


app = Flask(__name__)
logger = logging.getLogger('beak_note')


# ============================================================
# 首頁
# ============================================================

@app.route('/')
def index():
    return jsonify({
        'name': 'BeakNote',
        'phase': 0,
        'status': 'running',
        'endpoints': {
            'atoms': '/api/atoms',
            'relations': '/api/relations',
            'canvases': '/api/canvases',
            'tags': '/api/tags',
        }
    })


# ============================================================
# Knowledge Atoms API
# ============================================================

@app.route('/api/atoms', methods=['GET'])
def list_atoms():
    """列出知識原子，支援篩選（ILIKE + pg_trgm 相似度排序）"""
    with session_scope() as s:
        keyword = request.args.get('q')
        use_trgm = keyword and len(keyword) > 2

        sim_expr = None
        if use_trgm:
            sim_expr = func.greatest(
                func.similarity(KnowledgeAtom.title, keyword),
                func.similarity(KnowledgeAtom.content, keyword),
            )
            pattern = f'%{keyword}%'
            q = (
                s.query(KnowledgeAtom, sim_expr.label('sim'))
                .filter(KnowledgeAtom.is_deleted == False)
                .filter(
                    KnowledgeAtom.title.ilike(pattern) |
                    KnowledgeAtom.content.ilike(pattern)
                )
            )
        else:
            q = s.query(KnowledgeAtom).filter(KnowledgeAtom.is_deleted == False)

            if keyword:
                pattern = f'%{keyword}%'
                q = q.filter(
                    KnowledgeAtom.title.ilike(pattern) |
                    KnowledgeAtom.content.ilike(pattern)
                )

        # 篩選參數
        atom_type = request.args.get('type')
        if atom_type:
            q = q.filter(KnowledgeAtom.atom_type == atom_type)

        lifecycle = request.args.get('lifecycle')
        if lifecycle:
            q = q.filter(KnowledgeAtom.lifecycle == lifecycle)

        source = request.args.get('source')
        if source:
            q = q.filter(KnowledgeAtom.source == source)

        # 排序
        sort = request.args.get('sort', 'updated_at')
        if use_trgm:
            q = q.order_by(
                sim_expr.desc(),
                KnowledgeAtom.vitality_score.desc(),
            )
        elif sort == 'vitality':
            q = q.order_by(KnowledgeAtom.vitality_score.desc())
        elif sort == 'created_at':
            q = q.order_by(KnowledgeAtom.created_at.desc())
        else:
            q = q.order_by(KnowledgeAtom.updated_at.desc())

        # 分頁
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        per_page = min(per_page, 200)
        total = q.count()

        rows = q.offset((page - 1) * per_page).limit(per_page).all()
        atoms = [row[0] for row in rows] if use_trgm else rows

        return jsonify({
            'total': total,
            'page': page,
            'per_page': per_page,
            'items': [a.to_dict(include_tags=True) for a in atoms],
        })


@app.route('/api/atoms', methods=['POST'])
def create_atom():
    """建立知識原子"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '需要 JSON body'}), 400

    with session_scope() as s:
        atom = KnowledgeAtom(
            title=data.get('title', ''),
            content=data.get('content', ''),
            content_type=data.get('content_type', 'markdown'),
            atom_type=data.get('atom_type', 'F'),
            schema_id=data.get('schema_id'),
            lifecycle=data.get('lifecycle', 'active'),
            source=data.get('source', 'human'),
            source_detail=data.get('source_detail', ''),
        )
        s.add(atom)
        s.flush()

        # 處理標籤
        tag_ids = data.get('tag_ids', [])
        if tag_ids:
            tags = s.query(Tag).filter(Tag.id.in_(tag_ids)).all()
            atom.tags = tags

        s.flush()
        result = atom.to_dict(include_tags=True)
        return jsonify(result), 201


@app.route('/api/atoms/<int:atom_id>', methods=['GET'])
def get_atom(atom_id):
    """取得單一知識原子"""
    with session_scope() as s:
        atom = (
            s.query(KnowledgeAtom)
            .options(joinedload(KnowledgeAtom.tags))
            .filter(KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False)
            .first()
        )
        if not atom:
            return jsonify({'error': '原子不存在'}), 404

        # 更新存取紀錄
        atom.last_accessed_at = datetime.datetime.now()
        atom.access_count += 1

        result = atom.to_dict(include_tags=True, include_values=True)

        # 附加關係
        outgoing = rel_service.get_relations_from(s, atom_id)
        incoming = rel_service.get_relations_to(s, atom_id)
        result['relations_from'] = [r.to_dict(include_atoms=True) for r in outgoing]
        result['relations_to'] = [r.to_dict(include_atoms=True) for r in incoming]

        # 附加阻塞資訊
        blockers = rel_service.get_blockers(s, atom_id)
        result['is_blocked'] = len(blockers) > 0
        result['blockers'] = [{'id': b.id, 'title': b.title, 'lifecycle': b.lifecycle} for b in blockers]

        return jsonify(result)


@app.route('/api/atoms/<int:atom_id>', methods=['PUT'])
def update_atom(atom_id):
    """更新知識原子"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '需要 JSON body'}), 400

    with session_scope() as s:
        atom = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False
        ).first()
        if not atom:
            return jsonify({'error': '原子不存在'}), 404

        for field in ('title', 'content', 'content_type', 'atom_type',
                       'schema_id', 'lifecycle', 'source', 'source_detail'):
            if field in data:
                setattr(atom, field, data[field])

        if 'tag_ids' in data:
            tags = s.query(Tag).filter(Tag.id.in_(data['tag_ids'])).all()
            atom.tags = tags

        s.flush()
        return jsonify(atom.to_dict(include_tags=True))


@app.route('/api/atoms/<int:atom_id>', methods=['DELETE'])
def delete_atom(atom_id):
    """軟刪除知識原子"""
    with session_scope() as s:
        atom = s.query(KnowledgeAtom).filter(KnowledgeAtom.id == atom_id).first()
        if not atom:
            return jsonify({'error': '原子不存在'}), 404
        atom.is_deleted = True
        return jsonify({'message': f'原子 {atom_id} 已刪除'})


# ============================================================
# Relations API
# ============================================================

@app.route('/api/relations', methods=['POST'])
def create_relation():
    """建立因果關係"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '需要 JSON body'}), 400

    required = ('from_atom_id', 'to_atom_id', 'relation_type')
    for f in required:
        if f not in data:
            return jsonify({'error': f'缺少必要欄位: {f}'}), 400

    with session_scope() as s:
        try:
            rel = rel_service.create_relation(
                s,
                from_atom_id=data['from_atom_id'],
                to_atom_id=data['to_atom_id'],
                relation_type=data['relation_type'],
                label=data.get('label', ''),
                confidence=data.get('confidence', 1.0),
                created_by=data.get('created_by', 'human'),
            )
            return jsonify(rel.to_dict()), 201
        except ValueError as e:
            return jsonify({'error': str(e)}), 400


@app.route('/api/relations/<int:relation_id>', methods=['DELETE'])
def delete_relation(relation_id):
    """刪除因果關係"""
    with session_scope() as s:
        if rel_service.delete_relation(s, relation_id):
            return jsonify({'message': f'關係 {relation_id} 已刪除'})
        return jsonify({'error': '關係不存在'}), 404


@app.route('/api/atoms/<int:atom_id>/block-chain', methods=['GET'])
def get_block_chain(atom_id):
    """取得某原子的阻塞鍊"""
    max_depth = request.args.get('max_depth', 10, type=int)
    with session_scope() as s:
        chain = rel_service.trace_block_chain(s, atom_id, max_depth)
        return jsonify({
            'atom_id': atom_id,
            'is_blocked': len(chain) > 0,
            'chain': chain,
        })


# ============================================================
# Canvases API
# ============================================================

@app.route('/api/canvases', methods=['GET'])
def list_canvases():
    with session_scope() as s:
        canvases = s.query(Canvas).order_by(Canvas.updated_at.desc()).all()
        return jsonify([c.to_dict() for c in canvases])


@app.route('/api/canvases', methods=['POST'])
def create_canvas():
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({'error': '需要 name 欄位'}), 400

    with session_scope() as s:
        canvas = Canvas(
            name=data['name'],
            description=data.get('description', ''),
            canvas_type=data.get('canvas_type', 'whiteboard'),
        )
        s.add(canvas)
        s.flush()
        return jsonify(canvas.to_dict()), 201


@app.route('/api/canvases/<int:canvas_id>', methods=['GET'])
def get_canvas(canvas_id):
    """取得白板完整資料（含原子與連線）"""
    with session_scope() as s:
        canvas = (
            s.query(Canvas)
            .options(
                joinedload(Canvas.atoms).joinedload(CanvasAtom.atom),
                joinedload(Canvas.connections),
            )
            .filter(Canvas.id == canvas_id)
            .first()
        )
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        result = canvas.to_dict()
        result['atoms'] = [ca.to_dict() for ca in canvas.atoms]
        result['connections'] = [cc.to_dict() for cc in canvas.connections]
        return jsonify(result)


@app.route('/api/canvases/<int:canvas_id>', methods=['PUT'])
def update_canvas(canvas_id):
    data = request.get_json()
    with session_scope() as s:
        canvas = s.get(Canvas, canvas_id)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404
        for field in ('name', 'description', 'canvas_type',
                       'viewport_x', 'viewport_y', 'viewport_zoom', 'settings'):
            if field in data:
                setattr(canvas, field, data[field])
        s.flush()
        return jsonify(canvas.to_dict())


@app.route('/api/canvases/<int:canvas_id>', methods=['DELETE'])
def delete_canvas(canvas_id):
    with session_scope() as s:
        canvas = s.get(Canvas, canvas_id)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404
        s.delete(canvas)
        return jsonify({'message': f'白板 {canvas_id} 已刪除'})


@app.route('/api/canvases/<int:canvas_id>/atoms', methods=['POST'])
def add_atom_to_canvas(canvas_id):
    """在白板上放置原子"""
    data = request.get_json()
    if not data or 'atom_id' not in data:
        return jsonify({'error': '需要 atom_id'}), 400

    with session_scope() as s:
        ca = CanvasAtom(
            canvas_id=canvas_id,
            atom_id=data['atom_id'],
            pos_x=data.get('pos_x', 100),
            pos_y=data.get('pos_y', 100),
            width=data.get('width'),
            height=data.get('height'),
            z_index=data.get('z_index', 0),
            visual_style=data.get('visual_style', '{}'),
        )
        s.add(ca)
        s.flush()
        return jsonify(ca.to_dict()), 201


@app.route('/api/canvas-atoms/<int:ca_id>', methods=['PUT'])
def update_canvas_atom(ca_id):
    """更新原子在白板上的位置/樣式"""
    data = request.get_json()
    with session_scope() as s:
        ca = s.get(CanvasAtom, ca_id)
        if not ca:
            return jsonify({'error': '不存在'}), 404
        for field in ('pos_x', 'pos_y', 'width', 'height', 'z_index', 'visual_style'):
            if field in data:
                setattr(ca, field, data[field])
        s.flush()
        return jsonify(ca.to_dict())


@app.route('/api/canvas-atoms/<int:ca_id>', methods=['DELETE'])
def remove_atom_from_canvas(ca_id):
    """從白板移除原子（不刪除原子本身）"""
    with session_scope() as s:
        ca = s.get(CanvasAtom, ca_id)
        if not ca:
            return jsonify({'error': '不存在'}), 404
        s.delete(ca)
        return jsonify({'message': '已從白板移除'})


# ============================================================
# Tags API
# ============================================================

@app.route('/api/tags', methods=['GET'])
def list_tags():
    with session_scope() as s:
        tags = s.query(Tag).order_by(Tag.tag_type, Tag.name).all()
        return jsonify([t.to_dict() for t in tags])


@app.route('/api/tags', methods=['POST'])
def create_tag():
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({'error': '需要 name 欄位'}), 400

    with session_scope() as s:
        tag = Tag(
            name=data['name'],
            color=data.get('color', '#6b7280'),
            parent_tag_id=data.get('parent_tag_id'),
            tag_type=data.get('tag_type', 'tag'),
        )
        s.add(tag)
        s.flush()
        return jsonify(tag.to_dict()), 201


@app.route('/api/tags/<int:tag_id>', methods=['PUT'])
def update_tag(tag_id):
    data = request.get_json()
    with session_scope() as s:
        tag = s.get(Tag, tag_id)
        if not tag:
            return jsonify({'error': '標籤不存在'}), 404
        for field in ('name', 'color', 'parent_tag_id', 'tag_type'):
            if field in data:
                setattr(tag, field, data[field])
        s.flush()
        return jsonify(tag.to_dict())


@app.route('/api/tags/<int:tag_id>', methods=['DELETE'])
def delete_tag(tag_id):
    with session_scope() as s:
        tag = s.get(Tag, tag_id)
        if not tag:
            return jsonify({'error': '標籤不存在'}), 404
        s.delete(tag)
        return jsonify({'message': f'標籤 {tag_id} 已刪除'})


# ============================================================
# 啟動
# ============================================================

def create_argument_parser():
    parser = argparse.ArgumentParser(
        description='BeakNote 人類介面 -- 知識白板與筆記系統',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python app.py --serve                    啟動 Web 伺服器
  python app.py --serve --port 5170        指定埠號啟動
  python app.py --init-db                  初始化資料庫（建表）
  python app.py --init-db --seed           初始化並載入測試資料
  python app.py --reset                    重置資料庫（刪除所有表後重建）
        """
    )
    parser.add_argument('--serve', action='store_true', help='啟動 Web 伺服器')
    parser.add_argument('--port', type=int, default=None, help='伺服器埠號 (預設讀取 config.ini)')
    parser.add_argument('--host', type=str, default=None, help='伺服器綁定位址')
    parser.add_argument('--init-db', action='store_true', help='初始化資料庫（建立所有表）')
    parser.add_argument('--reset', action='store_true', help='重置資料庫（刪除後重建）')
    parser.add_argument('--seed', action='store_true', help='載入測試資料')
    parser.add_argument('--config', '-c', type=str, default=None, help='組態檔路徑')
    return parser


def seed_test_data():
    """載入測試用的 seed 資料"""
    from core.db import session_scope as ss

    with ss() as s:
        # 標籤
        t1 = Tag(name='BeakNote', color='#3b82f6', tag_type='domain')
        t2 = Tag(name='架構設計', color='#10b981', tag_type='tag')
        t3 = Tag(name='待討論', color='#f59e0b', tag_type='tag')
        s.add_all([t1, t2, t3])
        s.flush()

        # 知識原子
        a1 = KnowledgeAtom(
            title='知識原子是最小知識單位',
            content='每一筆紀錄就是一個最小知識單位，可以是文字、清單、圖片參考、URL 等。',
            atom_type='D',
            source='human',
        )
        a2 = KnowledgeAtom(
            title='因果鍊讓知識有方向性',
            content='Obsidian 的雙向連結只知道「A 和 B 有關」，BeakNote 的連結知道「A 導致了 B」。',
            atom_type='D',
            source='human',
        )
        a3 = KnowledgeAtom(
            title='建立 PostgreSQL 資料層',
            content='Phase 0 的第一步：建資料庫、核心表、基本 CRUD API。',
            atom_type='C',
            source='human',
        )
        a4 = KnowledgeAtom(
            title='建立白板 UI',
            content='Phase 1A：白板渲染、拖拉、縮放、平移、B/C/D 類型視覺區分。',
            atom_type='C',
            source='human',
        )
        s.add_all([a1, a2, a3, a4])
        s.flush()

        # 標籤關聯
        a1.tags.append(t1)
        a1.tags.append(t2)
        a2.tags.append(t1)
        a2.tags.append(t2)
        a3.tags.append(t1)
        a4.tags.append(t1)
        a4.tags.append(t3)

        # 因果關係
        rel_service.create_relation(s, a1.id, a2.id, 'supports', label='概念基礎')
        rel_service.create_relation(s, a3.id, a4.id, 'blocks', label='資料層是 UI 的前置條件')

        # 白板
        canvas = Canvas(name='BeakNote 規劃', description='Phase 0~1 規劃白板')
        s.add(canvas)
        s.flush()

        # 放置原子到白板
        positions = [(a1, 100, 100), (a2, 500, 100), (a3, 100, 350), (a4, 500, 350)]
        for atom, px, py in positions:
            ca = CanvasAtom(canvas_id=canvas.id, atom_id=atom.id, pos_x=px, pos_y=py)
            s.add(ca)

    logger.info('測試資料載入完成')


def main():
    parser = create_argument_parser()

    if len(sys.argv) == 1:
        print('BeakNote -- 知識白板與 AI 共用知識庫')
        print()
        print('必要動作（擇一）:')
        print('  --serve      啟動 Web 伺服器')
        print('  --init-db    初始化資料庫')
        print()
        print('選項:')
        print('  --port N     伺服器埠號')
        print('  --host ADDR  綁定位址')
        print('  --reset      重置資料庫（搭配 --init-db）')
        print('  --seed       載入測試資料（搭配 --init-db）')
        print('  --config     組態檔路徑 (預設: ../config.ini)')
        print()
        print('使用範例:')
        print('  python app.py --init-db --seed')
        print('  python app.py --serve')
        print()
        sys.exit(1)

    args = parser.parse_args()

    # 載入組態
    config_path = args.config
    if config_path is None:
        config_path = str(Path(__file__).resolve().parent.parent / 'config.ini')

    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding='utf-8')

    # 設定 logging
    log_level = cfg.get('logging', 'level', fallback='INFO')
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # 初始化資料庫引擎
    init_engine(config_path)

    if args.init_db:
        if args.reset:
            logger.warning('正在重置資料庫...')
            from core.db import drop_all_tables
            drop_all_tables()
            logger.info('所有表已刪除')

        logger.info('正在建立資料表...')
        create_all_tables()
        logger.info('資料表建立完成')

        if args.seed:
            seed_test_data()

        if not args.serve:
            sys.exit(0)

    if args.serve:
        host = args.host or cfg.get('flask', 'host', fallback='192.168.0.16')
        port = args.port or cfg.getint('flask', 'port', fallback=5170)
        debug = cfg.getboolean('flask', 'debug', fallback=True)
        app.config['SECRET_KEY'] = cfg.get('flask', 'secret_key', fallback='dev')

        logger.info(f'BeakNote 啟動於 http://{host}:{port}')
        app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    main()
