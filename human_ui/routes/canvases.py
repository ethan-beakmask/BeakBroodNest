# -*- coding: utf-8 -*-
"""Canvases API: CRUD + Canvas Atoms + Groups + Connections"""

from flask import Blueprint, request, jsonify
from sqlalchemy import func

from core.db import session_scope
from core.models import (
    KnowledgeAtom, AtomRelation, Canvas, CanvasAtom, CanvasConnection,
    CanvasGroup, Tag, atom_tags,
)
from core import relations as rel_service

bp = Blueprint('canvases', __name__)


# ============================================================
# Canvas CRUD
# ============================================================

@bp.route('/api/canvases', methods=['GET'])
def list_canvases():
    with session_scope() as s:
        canvases = s.query(Canvas).order_by(Canvas.updated_at.desc()).all()
        return jsonify([c.to_dict() for c in canvases])


@bp.route('/api/canvases', methods=['POST'])
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


@bp.route('/api/canvases/<int:canvas_id>', methods=['GET'])
def get_canvas(canvas_id):
    """取得白板完整資料（輕量查詢：不用 joinedload，content 截斷）"""
    CONTENT_PREVIEW_LEN = 500

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
        tags_map = {}
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
        group_member_rows = (
            s.query(CanvasAtom.group_id, CanvasAtom.atom_id)
            .filter(
                CanvasAtom.canvas_id == canvas_id,
                CanvasAtom.group_id.isnot(None),
            )
            .all()
        )
        group_members = {}
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

        # --- 5. 連線 ---
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


@bp.route('/api/canvases/<int:canvas_id>', methods=['PUT'])
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


@bp.route('/api/canvases/<int:canvas_id>', methods=['DELETE'])
def delete_canvas(canvas_id):
    with session_scope() as s:
        canvas = s.get(Canvas, canvas_id)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404
        s.delete(canvas)
        return jsonify({'message': f'白板 {canvas_id} 已刪除'})


# ============================================================
# Canvas Atoms
# ============================================================

@bp.route('/api/canvases/<int:canvas_id>/atoms', methods=['POST'])
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


@bp.route('/api/canvas-atoms/<int:ca_id>', methods=['PUT'])
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


@bp.route('/api/canvas-atoms/<int:ca_id>', methods=['DELETE'])
def remove_atom_from_canvas(ca_id):
    """從白板移除原子（不刪除原子本身）"""
    with session_scope() as s:
        ca = s.get(CanvasAtom, ca_id)
        if not ca:
            return jsonify({'error': '不存在'}), 404
        s.delete(ca)
        return jsonify({'message': '已從白板移除'})


# ============================================================
# Canvas Groups
# ============================================================

@bp.route('/api/canvases/<int:canvas_id>/groups', methods=['POST'])
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
        atom_ids = data.get('atom_ids', [])
        if atom_ids:
            s.query(CanvasAtom).filter(
                CanvasAtom.canvas_id == canvas_id,
                CanvasAtom.atom_id.in_(atom_ids),
            ).update({CanvasAtom.group_id: g.id}, synchronize_session='fetch')
            s.flush()
        s.refresh(g)
        return jsonify(g.to_dict()), 201


@bp.route('/api/canvas-groups/<int:group_id>', methods=['PUT'])
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
        if 'atom_ids' in data:
            s.query(CanvasAtom).filter(
                CanvasAtom.group_id == g.id,
            ).update({CanvasAtom.group_id: None}, synchronize_session='fetch')
            if data['atom_ids']:
                s.query(CanvasAtom).filter(
                    CanvasAtom.canvas_id == g.canvas_id,
                    CanvasAtom.atom_id.in_(data['atom_ids']),
                ).update({CanvasAtom.group_id: g.id}, synchronize_session='fetch')
        s.flush()
        s.refresh(g)
        return jsonify(g.to_dict())


@bp.route('/api/canvas-groups/<int:group_id>', methods=['DELETE'])
def delete_canvas_group(group_id):
    """刪除群組（卡片保留）"""
    with session_scope() as s:
        g = s.get(CanvasGroup, group_id)
        if not g:
            return jsonify({'error': '群組不存在'}), 404
        s.delete(g)
        return jsonify({'message': '群組已刪除'})


# ============================================================
# Canvas Connections
# ============================================================

@bp.route('/api/canvas-connections', methods=['POST'])
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
            'causes':       {'color': '#ef4444', 'line_style': 'solid'},
            'enables':      {'color': '#f97316', 'line_style': 'solid'},
            'supports':     {'color': '#10b981', 'line_style': 'solid'},
            'contradicts':  {'color': '#f59e0b', 'line_style': 'dashed'},
            'contains':     {'color': '#6b7280', 'line_style': 'dotted'},
            'follows':      {'color': '#3b82f6', 'line_style': 'solid'},
            'derives_from': {'color': '#8b5cf6', 'line_style': 'solid'},
            'supersedes':   {'color': '#a855f7', 'line_style': 'dashed'},
            'references':   {'color': '#64748b', 'line_style': 'dotted'},
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


@bp.route('/api/canvas-connections/<int:conn_id>', methods=['PUT'])
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


@bp.route('/api/canvas-connections/<int:conn_id>', methods=['DELETE'])
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
