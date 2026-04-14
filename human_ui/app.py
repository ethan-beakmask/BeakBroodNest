#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakCortex -- 人類介面 Flask 入口
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

from flask import Flask, request, jsonify, render_template, redirect
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from core.db import init_engine, get_session, session_scope, create_all_tables, Base, get_engine
from core.models import (
    KnowledgeAtom, AtomRelation, Canvas, CanvasAtom, CanvasConnection, CanvasGroup,
    Tag, atom_tags, AtomSchema, SchemaField, AtomFieldValue,
)
from orchestrator.models import WorkerTask, WorkerReport
from core import relations as rel_service
from core import embeddings as embed_service


app = Flask(__name__)
logger = logging.getLogger('beak_cortex')


@app.context_processor
def inject_cache_ver():
    """靜態檔快取破除：用 static/ 目錄最新修改時間當版本號"""
    try:
        static_dir = Path(app.static_folder)
        mtime = max(f.stat().st_mtime for f in static_dir.rglob('*') if f.is_file())
        return {'cache_ver': int(mtime)}
    except (ValueError, OSError):
        return {'cache_ver': 0}


# ============================================================
# 首頁
# ============================================================

@app.route('/')
def index():
    """首頁：導向第一個白板，若無則自動建立"""
    with session_scope() as s:
        canvas = s.query(Canvas).order_by(Canvas.id).first()
        if not canvas:
            canvas = Canvas(name='預設白板', description='')
            s.add(canvas)
            s.flush()
        canvas_id = canvas.id
    return redirect(f'/canvas/{canvas_id}')


@app.route('/canvas/<int:canvas_id>')
def canvas_page(canvas_id):
    """白板頁面"""
    return render_template('whiteboard.html', canvas_id=canvas_id)


@app.route('/help')
def help_page():
    """線上說明"""
    return render_template('help.html')


@app.route('/card-test')
def card_test_page():
    """Card Editor 獨立測試頁"""
    return render_template('card_test.html')


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
            content_json=data.get('content_json'),
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

        # Auto-embed（背景容錯，不阻塞回應）
        try:
            embed_service.embed_atom(s, atom.id)
        except Exception as e:
            logger.warning(f'Auto-embed failed for atom {atom.id}: {e}')

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

        for field in ('title', 'content', 'content_json', 'content_type',
                       'atom_type', 'schema_id', 'lifecycle', 'source',
                       'source_detail'):
            if field in data:
                setattr(atom, field, data[field])

        if 'tag_ids' in data:
            tags = s.query(Tag).filter(Tag.id.in_(data['tag_ids'])).all()
            atom.tags = tags

        s.flush()

        # 若 title 或 content 有變更，重新 embed
        if 'title' in data or 'content' in data:
            try:
                embed_service.embed_atom(s, atom_id)
            except Exception as e:
                logger.warning(f'Auto-embed failed for atom {atom_id}: {e}')

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
# Semantic Search API
# ============================================================

@app.route('/api/search/semantic', methods=['GET'])
def semantic_search():
    """語意搜尋：向量相似度"""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'error': '需要 q 參數'}), 400

    limit = request.args.get('limit', 10, type=int)
    limit = min(limit, 50)
    lifecycle = request.args.get('lifecycle', '')

    with session_scope() as s:
        results = embed_service.search_similar(s, q, limit=limit, lifecycle=lifecycle)
        return jsonify({
            'query': q,
            'total': len(results),
            'items': results,
        })


@app.route('/api/search/hybrid', methods=['GET'])
def hybrid_search():
    """混合搜尋：向量相似度 + 文字 ILIKE，去重合併"""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'error': '需要 q 參數'}), 400

    limit = request.args.get('limit', 10, type=int)
    limit = min(limit, 50)

    with session_scope() as s:
        # 向量搜尋
        semantic_results = embed_service.search_similar(s, q, limit=limit)

        # 文字搜尋
        pattern = f'%{q}%'
        text_atoms = (
            s.query(KnowledgeAtom)
            .filter(
                KnowledgeAtom.is_deleted == False,
                KnowledgeAtom.title.ilike(pattern) |
                KnowledgeAtom.content.ilike(pattern)
            )
            .order_by(KnowledgeAtom.vitality_score.desc())
            .limit(limit)
            .all()
        )

        # 合併去重（語意優先）
        seen_ids = set()
        merged = []
        for r in semantic_results:
            if r['id'] not in seen_ids:
                r['match_type'] = 'semantic'
                merged.append(r)
                seen_ids.add(r['id'])

        for a in text_atoms:
            if a.id not in seen_ids:
                merged.append({
                    'id': a.id,
                    'title': a.title,
                    'content': a.content[:200] if a.content else '',
                    'atom_type': a.atom_type,
                    'lifecycle': a.lifecycle,
                    'vitality_score': a.vitality_score,
                    'source': a.source,
                    'similarity': 0,
                    'match_type': 'text',
                })
                seen_ids.add(a.id)

        return jsonify({
            'query': q,
            'total': len(merged),
            'items': merged[:limit],
        })


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
    """取得白板完整資料（輕量查詢：不用 joinedload，content 截斷）"""
    CONTENT_PREVIEW_LEN = 500  # 白板卡片預覽用，完整內容走 GET /api/atoms/<id>

    with session_scope() as s:
        canvas = s.get(Canvas, canvas_id)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        result = canvas.to_dict()

        # --- 1. 原子：輕量查詢，content 在 DB 層截斷 ---
        ca_rows = (
            s.query(
                CanvasAtom.id,
                CanvasAtom.canvas_id,
                CanvasAtom.atom_id,
                CanvasAtom.pos_x,
                CanvasAtom.pos_y,
                CanvasAtom.width,
                CanvasAtom.height,
                CanvasAtom.z_index,
                CanvasAtom.visual_style,
                CanvasAtom.group_id,
                KnowledgeAtom.id.label('ka_id'),
                KnowledgeAtom.title,
                func.left(KnowledgeAtom.content, CONTENT_PREVIEW_LEN).label('content_preview'),
                KnowledgeAtom.content_type,
                KnowledgeAtom.atom_type,
                KnowledgeAtom.lifecycle,
                KnowledgeAtom.vitality_score,
                KnowledgeAtom.source,
            )
            .join(KnowledgeAtom, KnowledgeAtom.id == CanvasAtom.atom_id)
            .filter(CanvasAtom.canvas_id == canvas_id)
            .all()
        )

        atom_ids = [r.atom_id for r in ca_rows]

        # --- 2. 批次載入標籤 ---
        tags_map = {}  # atom_id -> [tag_dict, ...]
        if atom_ids:
            tag_rows = (
                s.query(atom_tags.c.atom_id, Tag.id, Tag.name, Tag.color)
                .join(Tag, Tag.id == atom_tags.c.tag_id)
                .filter(atom_tags.c.atom_id.in_(atom_ids))
                .all()
            )
            for aid, tid, tname, tcolor in tag_rows:
                tags_map.setdefault(aid, []).append(
                    {'id': tid, 'name': tname, 'color': tcolor}
                )

        # --- 3. 批次檢查阻塞狀態 ---
        blocked_ids = set()
        if atom_ids:
            blocking_rels = (
                s.query(AtomRelation.to_atom_id)
                .join(KnowledgeAtom, KnowledgeAtom.id == AtomRelation.from_atom_id)
                .filter(
                    AtomRelation.to_atom_id.in_(atom_ids),
                    AtomRelation.relation_type == 'blocks',
                    KnowledgeAtom.lifecycle.in_(['active', 'aging']),
                    KnowledgeAtom.is_deleted == False,
                )
                .distinct()
                .all()
            )
            blocked_ids = {r[0] for r in blocking_rels}

        # --- 組裝原子列表 ---
        result['atoms'] = []
        for r in ca_rows:
            result['atoms'].append({
                'id': r.id,
                'canvas_id': r.canvas_id,
                'atom_id': r.atom_id,
                'pos_x': r.pos_x,
                'pos_y': r.pos_y,
                'width': r.width,
                'height': r.height,
                'z_index': r.z_index,
                'visual_style': r.visual_style,
                'group_id': r.group_id,
                'atom': {
                    'id': r.ka_id,
                    'title': r.title,
                    'content': r.content_preview or '',
                    'content_type': r.content_type,
                    'atom_type': r.atom_type,
                    'lifecycle': r.lifecycle,
                    'vitality_score': r.vitality_score,
                    'source': r.source,
                    'tags': tags_map.get(r.atom_id, []),
                },
                'is_blocked': r.atom_id in blocked_ids,
            })

        # --- 4. 群組：輕量查詢 ---
        groups = s.query(CanvasGroup).filter(CanvasGroup.canvas_id == canvas_id).all()
        # 批次取得群組成員
        group_member_rows = (
            s.query(CanvasAtom.group_id, CanvasAtom.atom_id)
            .filter(
                CanvasAtom.canvas_id == canvas_id,
                CanvasAtom.group_id.isnot(None),
            )
            .all()
        )
        group_members = {}  # group_id -> [atom_id, ...]
        for gid, aid in group_member_rows:
            group_members.setdefault(gid, []).append(aid)

        result['groups'] = [{
            'id': g.id,
            'canvas_id': g.canvas_id,
            'name': g.name,
            'color': g.color,
            'pos_x': g.pos_x,
            'pos_y': g.pos_y,
            'width': g.width,
            'height': g.height,
            'z_index': g.z_index,
            'atom_ids': group_members.get(g.id, []),
        } for g in groups]

        # --- 5. 連線：join 取 relation_type，避免 lazy load ---
        conn_rows = (
            s.query(
                CanvasConnection.id,
                CanvasConnection.canvas_id,
                CanvasConnection.source_atom_id,
                CanvasConnection.target_atom_id,
                CanvasConnection.relation_id,
                CanvasConnection.line_style,
                CanvasConnection.color,
                CanvasConnection.label,
                CanvasConnection.animated,
                AtomRelation.relation_type,
            )
            .outerjoin(AtomRelation, AtomRelation.id == CanvasConnection.relation_id)
            .filter(CanvasConnection.canvas_id == canvas_id)
            .all()
        )
        result['connections'] = [{
            'id': cr.id,
            'canvas_id': cr.canvas_id,
            'source_atom_id': cr.source_atom_id,
            'target_atom_id': cr.target_atom_id,
            'relation_id': cr.relation_id,
            'line_style': cr.line_style,
            'color': cr.color,
            'label': cr.label,
            'animated': cr.animated,
            'relation_type': cr.relation_type,
        } for cr in conn_rows]

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
        for field in ('pos_x', 'pos_y', 'width', 'height', 'z_index', 'visual_style', 'group_id'):
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
# Canvas Groups API
# ============================================================

@app.route('/api/canvases/<int:canvas_id>/groups', methods=['POST'])
def create_canvas_group(canvas_id):
    """建立群組"""
    data = request.get_json() or {}
    with session_scope() as s:
        g = CanvasGroup(
            canvas_id=canvas_id,
            name=data.get('name', 'Group'),
            color=data.get('color', '#3b82f6'),
            pos_x=data.get('pos_x', 0),
            pos_y=data.get('pos_y', 0),
            width=data.get('width', 300),
            height=data.get('height', 200),
            z_index=data.get('z_index', 1),
        )
        s.add(g)
        s.flush()
        # 將指定的 canvas_atoms 加入群組
        atom_ids = data.get('atom_ids', [])
        if atom_ids:
            s.query(CanvasAtom).filter(
                CanvasAtom.canvas_id == canvas_id,
                CanvasAtom.atom_id.in_(atom_ids),
            ).update({CanvasAtom.group_id: g.id}, synchronize_session='fetch')
            s.flush()
        # 重新載入以取得 atoms 關係
        s.refresh(g)
        return jsonify(g.to_dict()), 201


@app.route('/api/canvas-groups/<int:group_id>', methods=['PUT'])
def update_canvas_group(group_id):
    """更新群組"""
    data = request.get_json()
    with session_scope() as s:
        g = s.get(CanvasGroup, group_id)
        if not g:
            return jsonify({'error': '群組不存在'}), 404
        for field in ('name', 'color', 'pos_x', 'pos_y', 'width', 'height', 'z_index'):
            if field in data:
                setattr(g, field, data[field])
        # 更新成員
        if 'atom_ids' in data:
            # 先清除舊成員
            s.query(CanvasAtom).filter(
                CanvasAtom.group_id == g.id,
            ).update({CanvasAtom.group_id: None}, synchronize_session='fetch')
            # 設定新成員
            if data['atom_ids']:
                s.query(CanvasAtom).filter(
                    CanvasAtom.canvas_id == g.canvas_id,
                    CanvasAtom.atom_id.in_(data['atom_ids']),
                ).update({CanvasAtom.group_id: g.id}, synchronize_session='fetch')
        s.flush()
        s.refresh(g)
        return jsonify(g.to_dict())


@app.route('/api/canvas-groups/<int:group_id>', methods=['DELETE'])
def delete_canvas_group(group_id):
    """刪除群組（卡片保留）"""
    with session_scope() as s:
        g = s.get(CanvasGroup, group_id)
        if not g:
            return jsonify({'error': '群組不存在'}), 404
        s.delete(g)
        return jsonify({'message': '群組已刪除'})


# ============================================================
# Canvas Connections API
# ============================================================

@app.route('/api/canvas-connections', methods=['POST'])
def create_canvas_connection():
    """建立視覺連線（同時建立或重用 AtomRelation）"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '需要 JSON body'}), 400

    required = ('canvas_id', 'source_atom_id', 'target_atom_id', 'relation_type')
    for f in required:
        if f not in data:
            return jsonify({'error': f'缺少必要欄位: {f}'}), 400

    with session_scope() as s:
        # 查找或建立 AtomRelation
        relation = s.query(AtomRelation).filter(
            AtomRelation.from_atom_id == data['source_atom_id'],
            AtomRelation.to_atom_id == data['target_atom_id'],
            AtomRelation.relation_type == data['relation_type'],
        ).first()

        if not relation:
            try:
                relation = rel_service.create_relation(
                    s,
                    from_atom_id=data['source_atom_id'],
                    to_atom_id=data['target_atom_id'],
                    relation_type=data['relation_type'],
                    label=data.get('label', ''),
                    created_by='human',
                )
            except ValueError as e:
                return jsonify({'error': str(e)}), 400

        # 依關係類型決定連線樣式
        rel_styles = {
            # 因果
            'causes':       {'color': '#ef4444', 'line_style': 'solid'},
            'enables':      {'color': '#f97316', 'line_style': 'solid'},
            # 論證
            'supports':     {'color': '#10b981', 'line_style': 'solid'},
            'contradicts':  {'color': '#f59e0b', 'line_style': 'dashed'},
            # 結構
            'contains':     {'color': '#6b7280', 'line_style': 'dotted'},
            # 時序
            'follows':      {'color': '#3b82f6', 'line_style': 'solid'},
            # 衍生
            'derives_from': {'color': '#8b5cf6', 'line_style': 'solid'},
            'supersedes':   {'color': '#a855f7', 'line_style': 'dashed'},
            'references':   {'color': '#64748b', 'line_style': 'dotted'},
            # 工作流
            'blocks':       {'color': '#dc2626', 'line_style': 'solid'},
        }
        style = rel_styles.get(data['relation_type'], {'color': '#94a3b8', 'line_style': 'solid'})

        conn = CanvasConnection(
            canvas_id=data['canvas_id'],
            source_atom_id=data['source_atom_id'],
            target_atom_id=data['target_atom_id'],
            relation_id=relation.id,
            line_style=style['line_style'],
            color=style['color'],
            label=data.get('label', '') or relation.label,
        )
        s.add(conn)
        s.flush()

        result = conn.to_dict()
        result['relation_type'] = data['relation_type']
        return jsonify(result), 201


@app.route('/api/canvas-connections/<int:conn_id>', methods=['PUT'])
def update_canvas_connection(conn_id):
    """更新視覺連線（標籤等）"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '需要 JSON body'}), 400

    with session_scope() as s:
        conn = s.get(CanvasConnection, conn_id)
        if not conn:
            return jsonify({'error': '連線不存在'}), 404

        if 'label' in data:
            conn.label = data['label']
            # 同步更新底層 AtomRelation 的 label
            if conn.relation_id:
                rel = s.get(AtomRelation, conn.relation_id)
                if rel:
                    rel.label = data['label']

        if 'color' in data:
            conn.color = data['color']
        if 'line_style' in data:
            conn.line_style = data['line_style']

        s.flush()
        return jsonify(conn.to_dict())


@app.route('/api/canvas-connections/<int:conn_id>', methods=['DELETE'])
def delete_canvas_connection(conn_id):
    """刪除視覺連線，若底層 AtomRelation 無其他白板引用則一併刪除"""
    with session_scope() as s:
        conn = s.get(CanvasConnection, conn_id)
        if not conn:
            return jsonify({'error': '連線不存在'}), 404

        relation_id = conn.relation_id
        s.delete(conn)
        s.flush()

        relation_kept = False
        if relation_id:
            # 檢查是否還有其他 CanvasConnection 引用同一條 AtomRelation
            other_refs = s.query(CanvasConnection).filter(
                CanvasConnection.relation_id == relation_id,
            ).count()
            if other_refs == 0:
                rel = s.get(AtomRelation, relation_id)
                if rel:
                    s.delete(rel)
            else:
                relation_kept = True

        return jsonify({
            'message': f'連線 {conn_id} 已刪除',
            'relation_kept': relation_kept,
            'relation_kept_reason': '底層知識關係仍被其他白板引用' if relation_kept else None,
        })


# ============================================================
# Orchestrator Dashboard
# ============================================================

@app.route('/dashboard')
def dashboard_page():
    """Orchestrator 儀錶板"""
    return render_template('dashboard.html')


@app.route('/api/orchestrator/stats', methods=['GET'])
def orchestrator_stats():
    """Orchestrator 統計摘要"""
    with session_scope() as s:
        tasks = s.query(WorkerTask).all()

        by_status = {}
        sessions = set()
        for t in tasks:
            by_status[t.status] = by_status.get(t.status, 0) + 1
            if t.session_id:
                sessions.add(t.session_id)

        # 活躍 session（含 non-terminal 任務的 session）
        active_sessions = set()
        terminal = ('completed', 'failed', 'timeout', 'cancelled')
        for t in tasks:
            if t.session_id and t.status not in terminal:
                active_sessions.add(t.session_id)

        return jsonify({
            'total': len(tasks),
            'by_status': by_status,
            'session_count': len(sessions),
            'active_session_count': len(active_sessions),
        })


@app.route('/api/orchestrator/tasks', methods=['GET'])
def orchestrator_tasks():
    """列出 Orchestrator 任務"""
    with session_scope() as s:
        q = s.query(WorkerTask)

        status = request.args.get('status')
        if status:
            q = q.filter(WorkerTask.status == status)

        session_id = request.args.get('session_id')
        if session_id:
            q = q.filter(WorkerTask.session_id == session_id)

        # 排序：活躍任務優先，再按建立時間倒序
        q = q.order_by(
            WorkerTask.created_at.desc(),
        )

        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        per_page = min(per_page, 200)
        total = q.count()

        tasks = q.offset((page - 1) * per_page).limit(per_page).all()

        # 附加 report_count（避免 N+1）
        task_ids = [t.id for t in tasks]
        report_counts = {}
        if task_ids:
            rows = (
                s.query(WorkerReport.task_id, func.count(WorkerReport.id))
                .filter(WorkerReport.task_id.in_(task_ids))
                .group_by(WorkerReport.task_id)
                .all()
            )
            report_counts = dict(rows)

        items = []
        for t in tasks:
            d = t.to_dict()
            d['report_count'] = report_counts.get(t.id, 0)
            items.append(d)

        return jsonify({
            'total': total,
            'page': page,
            'per_page': per_page,
            'items': items,
        })


@app.route('/api/orchestrator/tasks/<int:task_id>', methods=['GET'])
def orchestrator_task_detail(task_id):
    """單一任務詳情含 reports"""
    with session_scope() as s:
        task = s.query(WorkerTask).filter(WorkerTask.id == task_id).first()
        if not task:
            return jsonify({'error': '任務不存在'}), 404

        result = task.to_dict()
        result['reports'] = [r.to_dict() for r in task.reports]
        return jsonify(result)


# ============================================================
# Report Review & Promote API (2.1)
# ============================================================

@app.route('/api/orchestrator/reports/<int:report_id>/review', methods=['PUT'])
def review_report(report_id):
    """審查支線報告：approve 或 reject"""
    data = request.get_json()
    if not data or 'action' not in data:
        return jsonify({'error': '需要 action 欄位 (approve/reject)'}), 400

    action = data['action']
    if action not in ('approve', 'reject'):
        return jsonify({'error': f'無效的 action: {action}，允許值: approve, reject'}), 400

    with session_scope() as s:
        report = s.query(WorkerReport).filter(WorkerReport.id == report_id).first()
        if not report:
            return jsonify({'error': f'報告 #{report_id} 不存在'}), 404

        if report.review_status not in ('pending',):
            return jsonify({
                'error': f'報告 #{report_id} 目前狀態為 {report.review_status}，僅 pending 可審查',
            }), 409

        if action == 'approve':
            report.review_status = 'approved'
        else:
            report.review_status = 'rejected'

        report.reviewer_id = data.get('reviewer_id', 'human')
        report.reviewed_at = datetime.datetime.now()
        report.review_notes = data.get('notes', '')

        return jsonify(report.to_dict())


@app.route('/api/orchestrator/reports/<int:report_id>/promote', methods=['POST'])
def promote_report(report_id):
    """將報告提升為正式知識原子。

    可選欄位（不傳則從 report/task 取預設值）：
      title: 原子標題（預設用 task.title）
      content: 原子內容（預設用 report.content）
      atom_type: 預設 D（歸納）
      tags: 標籤名稱列表（不存在的自動建立）
      reviewer_id: 審查者 ID
    """
    data = request.get_json() or {}

    with session_scope() as s:
        report = (
            s.query(WorkerReport)
            .filter(WorkerReport.id == report_id)
            .first()
        )
        if not report:
            return jsonify({'error': f'報告 #{report_id} 不存在'}), 404

        if report.review_status == 'promoted':
            return jsonify({
                'error': f'報告 #{report_id} 已被提升為原子 #{report.promoted_atom_id}',
            }), 409

        if report.review_status not in ('pending', 'approved'):
            return jsonify({
                'error': f'報告 #{report_id} 狀態為 {report.review_status}，僅 pending/approved 可提升',
            }), 409

        # 取得關聯 task 作為預設值來源
        task = s.query(WorkerTask).filter(WorkerTask.id == report.task_id).first()

        # 建立知識原子
        atom = KnowledgeAtom(
            title=data.get('title') or (task.title if task else f'Report #{report_id}'),
            content=data.get('content') or report.content,
            content_type=report.content_type or 'markdown',
            atom_type=data.get('atom_type', 'D'),
            lifecycle='active',
            source='derived',
            source_detail=f'promoted from report #{report_id}, task #{report.task_id}',
        )
        s.add(atom)
        s.flush()

        # 處理標籤
        tag_names = data.get('tags', [])
        if tag_names:
            tag_objects = []
            for tag_name in tag_names:
                tag = s.query(Tag).filter(Tag.name == tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name, tag_type='tag')
                    s.add(tag)
                    s.flush()
                tag_objects.append(tag)
            atom.tags = tag_objects

        # 回填 report
        report.review_status = 'promoted'
        report.promoted_atom_id = atom.id
        report.reviewer_id = data.get('reviewer_id', 'human')
        report.reviewed_at = datetime.datetime.now()

        s.flush()

        result = report.to_dict()
        result['promoted_atom'] = atom.to_dict(include_tags=True)

        # Auto-embed（背景容錯）
        try:
            embed_service.embed_atom(s, atom.id)
        except Exception as e:
            logger.warning(f'Auto-embed failed for promoted atom {atom.id}: {e}')

        return jsonify(result), 201


# ============================================================
# Worker KB API -- 支線情報共享 (2.2)
# ============================================================

def _authenticate_worker(s):
    """驗證支線身份，回傳 (worker_task, error_response)。
    支線以 X-Worker-Id + X-Session-Id header 認證。
    """
    worker_id = request.headers.get('X-Worker-Id', '').strip()
    session_id = request.headers.get('X-Session-Id', '').strip()

    if not worker_id or not session_id:
        return None, (jsonify({'error': '缺少 X-Worker-Id 或 X-Session-Id header'}), 401)

    task = (
        s.query(WorkerTask)
        .filter(
            WorkerTask.worker_id == worker_id,
            WorkerTask.session_id == session_id,
            WorkerTask.status.in_(['dispatched', 'running']),
        )
        .first()
    )
    if not task:
        return None, (jsonify({'error': '無效的 worker 憑證或任務已結束'}), 403)

    return task, None


@app.route('/api/worker/kb/search', methods=['GET'])
def worker_kb_search():
    """支線搜尋知識原子（需 worker 認證）"""
    with session_scope() as s:
        worker_task, err = _authenticate_worker(s)
        if err:
            return err

        keyword = request.args.get('q', '').strip()
        tag_name = request.args.get('tag', '').strip()
        limit = min(request.args.get('limit', 20, type=int), 50)

        q = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.is_deleted == False,
            KnowledgeAtom.lifecycle.in_(['active', 'aging']),
        )

        if keyword:
            pattern = f'%{keyword}%'
            q = q.filter(
                KnowledgeAtom.title.ilike(pattern) |
                KnowledgeAtom.content.ilike(pattern)
            )

        if tag_name:
            tag_subq = (
                s.query(atom_tags.c.atom_id)
                .join(Tag, Tag.id == atom_tags.c.tag_id)
                .filter(Tag.name == tag_name)
            )
            q = q.filter(KnowledgeAtom.id.in_(tag_subq.subquery().select()))

        atoms = (
            q.order_by(KnowledgeAtom.vitality_score.desc(), KnowledgeAtom.updated_at.desc())
            .limit(limit)
            .all()
        )

        return jsonify({
            'total': len(atoms),
            'items': [
                {
                    'id': a.id,
                    'title': a.title,
                    'content': a.content[:500] if a.content else '',
                    'atom_type': a.atom_type,
                    'source': a.source,
                    'updated_at': a.updated_at.isoformat() if a.updated_at else None,
                }
                for a in atoms
            ],
        })


@app.route('/api/worker/kb/atoms/<int:atom_id>', methods=['GET'])
def worker_kb_get_atom(atom_id):
    """支線讀取單一知識原子（需 worker 認證）"""
    with session_scope() as s:
        worker_task, err = _authenticate_worker(s)
        if err:
            return err

        atom = (
            s.query(KnowledgeAtom)
            .filter(KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False)
            .first()
        )
        if not atom:
            return jsonify({'error': f'原子 #{atom_id} 不存在'}), 404

        atom.last_accessed_at = datetime.datetime.now()
        atom.access_count += 1

        return jsonify(atom.to_dict(include_tags=True))


@app.route('/api/worker/kb/atoms', methods=['POST'])
def worker_kb_store_atom():
    """支線寫入知識原子（需 worker 認證）。
    source 固定為 derived，source_detail 自動帶 worker 資訊。
    """
    data = request.get_json()
    if not data or 'title' not in data:
        return jsonify({'error': '需要 title 欄位'}), 400

    with session_scope() as s:
        worker_task, err = _authenticate_worker(s)
        if err:
            return err

        atom = KnowledgeAtom(
            title=data['title'],
            content=data.get('content', ''),
            content_type=data.get('content_type', 'markdown'),
            atom_type=data.get('atom_type', 'F'),
            lifecycle='active',
            source='derived',
            source_detail=f'worker:{worker_task.worker_id}, task:{worker_task.id}',
        )
        s.add(atom)
        s.flush()

        # 處理標籤
        tag_names = data.get('tags', [])
        if tag_names:
            tag_objects = []
            for tag_name in tag_names:
                tag = s.query(Tag).filter(Tag.name == tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name, tag_type='tag')
                    s.add(tag)
                    s.flush()
                tag_objects.append(tag)
            atom.tags = tag_objects

        s.flush()
        result = atom.to_dict(include_tags=True)

        # Auto-embed（背景容錯）
        try:
            embed_service.embed_atom(s, atom.id)
        except Exception as e:
            logger.warning(f'Auto-embed failed for worker atom {atom.id}: {e}')

        return jsonify(result), 201


# ============================================================
# Schema API (E 類型套表)
# ============================================================

@app.route('/api/schemas', methods=['GET'])
def list_schemas():
    with session_scope() as s:
        schemas = s.query(AtomSchema).options(
            joinedload(AtomSchema.fields)
        ).order_by(AtomSchema.id).all()
        result = []
        for schema in schemas:
            d = schema.to_dict()
            d['fields'] = [f.to_dict() for f in schema.fields]
            d['atom_count'] = s.query(KnowledgeAtom).filter(
                KnowledgeAtom.schema_id == schema.id,
                KnowledgeAtom.is_deleted == False,
            ).count()
            result.append(d)
        return jsonify(result)


@app.route('/api/schemas', methods=['POST'])
def create_schema():
    data = request.get_json()
    if not data or 'name' not in data or 'slug' not in data:
        return jsonify({'error': '需要 name 和 slug 欄位'}), 400

    with session_scope() as s:
        existing = s.query(AtomSchema).filter(AtomSchema.slug == data['slug']).first()
        if existing:
            return jsonify({'error': f'slug "{data["slug"]}" 已存在'}), 409

        schema = AtomSchema(
            name=data['name'],
            slug=data['slug'],
            description=data.get('description', ''),
            icon=data.get('icon', ''),
        )
        s.add(schema)
        s.flush()

        for i, fd in enumerate(data.get('fields', [])):
            sf = SchemaField(
                schema_id=schema.id,
                name=fd.get('name', ''),
                label=fd.get('label', fd.get('name', '')),
                field_type=fd.get('field_type', 'text'),
                options=fd.get('options', ''),
                required=fd.get('required', False),
                sort_order=fd.get('sort_order', i),
            )
            s.add(sf)
        s.flush()

        d = schema.to_dict()
        d['fields'] = [f.to_dict() for f in s.query(SchemaField).filter(
            SchemaField.schema_id == schema.id
        ).order_by(SchemaField.sort_order).all()]
        return jsonify(d), 201


@app.route('/api/schemas/<int:schema_id>', methods=['GET'])
def get_schema(schema_id):
    with session_scope() as s:
        schema = s.query(AtomSchema).options(
            joinedload(AtomSchema.fields)
        ).filter(AtomSchema.id == schema_id).first()
        if not schema:
            return jsonify({'error': 'Schema 不存在'}), 404
        d = schema.to_dict()
        d['fields'] = [f.to_dict() for f in schema.fields]

        # 附帶此 schema 的所有原子（含欄位值）
        atoms = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.schema_id == schema_id,
            KnowledgeAtom.is_deleted == False,
        ).order_by(KnowledgeAtom.created_at.desc()).all()

        rows = []
        for a in atoms:
            fvs = s.query(AtomFieldValue).options(
                joinedload(AtomFieldValue.field)
            ).filter(AtomFieldValue.atom_id == a.id).all()
            rows.append({
                'atom_id': a.id,
                'title': a.title,
                'content': a.content,
                'field_values': {fv.field.name: fv.value for fv in fvs if fv.field},
                'created_at': a.created_at.isoformat() if a.created_at else None,
            })
        d['atoms'] = rows
        return jsonify(d)


@app.route('/api/schemas/<int:schema_id>', methods=['DELETE'])
def delete_schema(schema_id):
    with session_scope() as s:
        schema = s.query(AtomSchema).filter(AtomSchema.id == schema_id).first()
        if not schema:
            return jsonify({'error': 'Schema 不存在'}), 404
        # 解除原子關聯
        s.query(KnowledgeAtom).filter(
            KnowledgeAtom.schema_id == schema_id
        ).update({'schema_id': None})
        s.delete(schema)
        return jsonify({'message': f'Schema {schema_id} 已刪除'})


@app.route('/api/atoms/<int:atom_id>/field-values', methods=['POST'])
def set_field_values(atom_id):
    """批量設定 E 類型原子的欄位值。body: {"values": {"field_name": "value"}}"""
    data = request.get_json()
    if not data or 'values' not in data:
        return jsonify({'error': '需要 values 欄位'}), 400

    with session_scope() as s:
        atom = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False
        ).first()
        if not atom:
            return jsonify({'error': '原子不存在'}), 404
        if not atom.schema_id:
            return jsonify({'error': '此原子未關聯 schema'}), 400

        schema_fields = s.query(SchemaField).filter(
            SchemaField.schema_id == atom.schema_id
        ).all()
        field_map = {f.name: f for f in schema_fields}

        for fname, fval in data['values'].items():
            if fname not in field_map:
                continue
            existing = s.query(AtomFieldValue).filter(
                AtomFieldValue.atom_id == atom_id,
                AtomFieldValue.field_id == field_map[fname].id,
            ).first()
            if existing:
                existing.value = str(fval) if fval is not None else None
            else:
                s.add(AtomFieldValue(
                    atom_id=atom_id,
                    field_id=field_map[fname].id,
                    value=str(fval) if fval is not None else None,
                ))
        s.flush()
        return jsonify({'message': f'原子 {atom_id} 欄位值已更新'})


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
        description='BeakCortex 人類介面 -- 知識白板與筆記系統',
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
        t1 = Tag(name='BeakCortex', color='#3b82f6', tag_type='domain')
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
            content='Obsidian 的雙向連結只知道「A 和 B 有關」，BeakCortex 的連結知道「A 導致了 B」。',
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
        canvas = Canvas(name='BeakCortex 規劃', description='Phase 0~1 規劃白板')
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
        print('BeakCortex -- 知識白板與 AI 共用知識庫')
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

        logger.info(f'BeakCortex 啟動於 http://{host}:{port}')
        app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    main()
