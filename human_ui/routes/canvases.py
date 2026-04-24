# -*- coding: utf-8 -*-
"""Canvases API: CRUD + Canvas Atoms + Groups + Connections"""

from flask import Blueprint, request, jsonify
from sqlalchemy import func

from core.db import session_scope
from core.models import (
    KnowledgeAtom, UnifiedRelation, RelationTypeRegistry,
    Canvas, CanvasAtom, CanvasConnection,
    CanvasGroup, Tag, atom_tags,
)
from core import relations as rel_service

bp = Blueprint('canvases', __name__)


def _get_canvas_by_slug(s, slug):
    """以 slug 查詢 canvas，回傳 Canvas 或 None"""
    return s.query(Canvas).filter(Canvas.slug == slug).first()


def _build_canvas_snapshot(s, canvas_id):
    """建立白板的完整快照：卡片（完整內容）、連線、群組、標籤"""

    # 卡片 + 完整內容
    ca_rows = (
        s.query(CanvasAtom, KnowledgeAtom)
        .join(KnowledgeAtom, KnowledgeAtom.id == CanvasAtom.atom_id)
        .filter(CanvasAtom.canvas_id == canvas_id)
        .all()
    )

    atom_ids = [ca.atom_id for ca, _ in ca_rows]

    # 批次標籤
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

    # 阻塞狀態（unified_relations）
    blocked_ids = set()
    if atom_ids:
        blocking = (
            s.query(UnifiedRelation.to_atom_id)
            .join(KnowledgeAtom, KnowledgeAtom.id == UnifiedRelation.from_atom_id)
            .filter(
                UnifiedRelation.to_atom_id.in_(atom_ids),
                UnifiedRelation.relation_type == 'blocks',
                UnifiedRelation.is_deleted == False,
                KnowledgeAtom.lifecycle.in_(['active', 'aging']),
                KnowledgeAtom.is_deleted == False,
            )
            .distinct().all()
        )
        blocked_ids = {r[0] for r in blocking}

    atoms = []
    for ca, ka in ca_rows:
        atoms.append({
            'id': ca.id,
            'canvas_id': ca.canvas_id,
            'atom_id': ca.atom_id,
            'pos_x': ca.pos_x,
            'pos_y': ca.pos_y,
            'width': ca.width,
            'height': ca.height,
            'z_index': ca.z_index,
            'visual_style': ca.visual_style,
            'group_id': ca.group_id,
            'atom': {
                'id': ka.id,
                'title': ka.title,
                'content': ka.content or '',
                'content_type': ka.content_type,
                'atom_type': ka.atom_type,
                'lifecycle': ka.lifecycle,
                'vitality_score': ka.vitality_score,
                'source': ka.source,
                'owner': ka.owner or 'ethan',
                'tags': tags_map.get(ca.atom_id, []),
                'updated_at': ka.updated_at.isoformat() if ka.updated_at else None,
            },
            'is_blocked': ca.atom_id in blocked_ids,
        })

    # 群組
    groups = s.query(CanvasGroup).filter(CanvasGroup.canvas_id == canvas_id).all()
    group_member_rows = (
        s.query(CanvasAtom.group_id, CanvasAtom.atom_id)
        .filter(CanvasAtom.canvas_id == canvas_id, CanvasAtom.group_id.isnot(None))
        .all()
    )
    group_members = {}
    for gid, aid in group_member_rows:
        group_members.setdefault(gid, []).append(aid)

    snap_groups = [{
        'id': g.id, 'canvas_id': g.canvas_id, 'name': g.name, 'color': g.color,
        'pos_x': g.pos_x, 'pos_y': g.pos_y, 'width': g.width, 'height': g.height,
        'z_index': g.z_index, 'atom_ids': group_members.get(g.id, []),
    } for g in groups]

    # 連線（unified_relations）
    conn_rows = (
        s.query(
            CanvasConnection.id, CanvasConnection.canvas_id,
            CanvasConnection.source_atom_id, CanvasConnection.target_atom_id,
            CanvasConnection.unified_relation_id, CanvasConnection.line_style,
            CanvasConnection.color, CanvasConnection.label, CanvasConnection.animated,
            UnifiedRelation.relation_type,
            UnifiedRelation.graph_family,
            UnifiedRelation.semantic_layer,
        )
        .outerjoin(UnifiedRelation, UnifiedRelation.id == CanvasConnection.unified_relation_id)
        .filter(CanvasConnection.canvas_id == canvas_id)
        .all()
    )
    snap_conns = [{
        'id': cr.id, 'canvas_id': cr.canvas_id,
        'source_atom_id': cr.source_atom_id, 'target_atom_id': cr.target_atom_id,
        'unified_relation_id': cr.unified_relation_id,
        'line_style': cr.line_style,
        'color': cr.color, 'label': cr.label, 'animated': cr.animated,
        'relation_type': cr.relation_type,
        'graph_family': cr.graph_family,
        'semantic_layer': cr.semantic_layer,
    } for cr in conn_rows]

    return {
        'atoms': atoms,
        'groups': snap_groups,
        'connections': snap_conns,
    }


# ============================================================
# Canvas CRUD
# ============================================================

@bp.route('/api/canvases', methods=['GET'])
def list_canvases():
    include_archived = request.args.get('include_archived', '0') == '1'
    with session_scope() as s:
        q = s.query(Canvas)
        if not include_archived:
            q = q.filter(Canvas.is_archived == False)
        canvases = q.order_by(Canvas.updated_at.desc()).all()
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
            owner=data.get('owner', 'ethan'),
        )
        s.add(canvas)
        s.flush()
        return jsonify(canvas.to_dict()), 201


@bp.route('/api/canvases/<slug>', methods=['GET'])
def get_canvas(slug):
    """取得白板完整資料（歸檔白板回傳快照）"""
    CONTENT_PREVIEW_LEN = 500

    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        # 歸檔白板且有快照：直接回傳凍結的資料
        if canvas.is_archived and canvas.snapshot:
            result = canvas.to_dict()
            result['atoms'] = canvas.snapshot.get('atoms', [])
            result['groups'] = canvas.snapshot.get('groups', [])
            result['connections'] = canvas.snapshot.get('connections', [])
            result['is_snapshot'] = True
            return jsonify(result)

        canvas_id = canvas.id
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
                KnowledgeAtom.owner.label('atom_owner'),
                KnowledgeAtom.updated_at.label('atom_updated_at'),
            )
            .join(KnowledgeAtom, KnowledgeAtom.id == CanvasAtom.atom_id)
            .filter(CanvasAtom.canvas_id == canvas_id)
            .filter(KnowledgeAtom.is_deleted == False)
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

        # --- 3. 批次檢查阻塞狀態（unified_relations） ---
        blocked_ids = set()
        if atom_ids:
            blocking_rels = (
                s.query(UnifiedRelation.to_atom_id)
                .join(KnowledgeAtom, KnowledgeAtom.id == UnifiedRelation.from_atom_id)
                .filter(
                    UnifiedRelation.to_atom_id.in_(atom_ids),
                    UnifiedRelation.relation_type == 'blocks',
                    UnifiedRelation.is_deleted == False,
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
                    'owner': r.atom_owner or 'ethan',
                    'tags': tags_map.get(r.atom_id, []),
                    'updated_at': r.atom_updated_at.isoformat() if r.atom_updated_at else None,
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

        # --- 5. 連線（unified_relations） ---
        conn_rows = (
            s.query(
                CanvasConnection.id,
                CanvasConnection.canvas_id,
                CanvasConnection.source_atom_id,
                CanvasConnection.target_atom_id,
                CanvasConnection.unified_relation_id,
                CanvasConnection.line_style,
                CanvasConnection.color,
                CanvasConnection.label,
                CanvasConnection.animated,
                CanvasConnection.is_disconnected,
                UnifiedRelation.relation_type,
                UnifiedRelation.graph_family,
                UnifiedRelation.semantic_layer,
            )
            .outerjoin(UnifiedRelation, UnifiedRelation.id == CanvasConnection.unified_relation_id)
            .filter(CanvasConnection.canvas_id == canvas_id)
            .all()
        )
        result['connections'] = [{
            'id': cr.id,
            'canvas_id': cr.canvas_id,
            'source_atom_id': cr.source_atom_id,
            'target_atom_id': cr.target_atom_id,
            'unified_relation_id': cr.unified_relation_id,
            'line_style': cr.line_style,
            'color': cr.color,
            'label': cr.label,
            'animated': cr.animated,
            'is_disconnected': cr.is_disconnected,
            'relation_type': cr.relation_type,
            'graph_family': cr.graph_family,
            'semantic_layer': cr.semantic_layer,
        } for cr in conn_rows]

        return jsonify(result)


@bp.route('/api/canvases/<slug>', methods=['PUT'])
def update_canvas(slug):
    data = request.get_json()
    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        # 歸檔時自動建立快照
        if data.get('is_archived') and not canvas.is_archived:
            canvas.snapshot = _build_canvas_snapshot(s, canvas.id)

        for field in ('name', 'description', 'canvas_type', 'owner', 'is_archived',
                       'viewport_x', 'viewport_y', 'viewport_zoom', 'settings'):
            if field in data:
                setattr(canvas, field, data[field])
        s.flush()
        return jsonify(canvas.to_dict())


@bp.route('/api/canvases/<slug>', methods=['DELETE'])
def delete_canvas(slug):
    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404
        s.delete(canvas)
        return jsonify({'message': f'白板已刪除'})


# ============================================================
# Canvas Atoms
# ============================================================

@bp.route('/api/canvases/<slug>/atoms', methods=['POST'])
def add_atom_to_canvas(slug):
    """在白板上放置原子"""
    data = request.get_json()
    if not data or 'atom_id' not in data:
        return jsonify({'error': '需要 atom_id'}), 400

    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        ca = CanvasAtom(
            canvas_id=canvas.id,
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

@bp.route('/api/canvases/<slug>/groups', methods=['POST'])
def create_canvas_group(slug):
    """建立群組"""
    data = request.get_json() or {}
    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        g = CanvasGroup(
            canvas_id=canvas.id,
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
                CanvasAtom.canvas_id == canvas.id,
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

def _get_relation_style(s, relation_type):
    """從 registry 取得關係類型的視覺樣式"""
    reg = s.get(RelationTypeRegistry, relation_type)
    if reg:
        return {'color': reg.default_color, 'line_style': reg.default_style}
    return {'color': '#94a3b8', 'line_style': 'solid'}


@bp.route('/api/canvas-connections', methods=['POST'])
def create_canvas_connection():
    """建立視覺連線（同時建立或重用 UnifiedRelation）"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '需要 JSON body'}), 400

    required = ('canvas_id', 'source_atom_id', 'target_atom_id', 'relation_type')
    for f in required:
        if f not in data:
            return jsonify({'error': f'缺少必要欄位: {f}'}), 400

    rel_type = data['relation_type']
    if rel_type not in UnifiedRelation.VALID_TYPES:
        return jsonify({'error': f'無效的 relation_type: {rel_type}'}), 400

    with session_scope() as s:
        # canvas_id 接受 slug 字串
        canvas_ref = data['canvas_id']
        if isinstance(canvas_ref, str):
            canvas = _get_canvas_by_slug(s, canvas_ref)
            if not canvas:
                return jsonify({'error': '白板不存在'}), 404
            canvas_id = canvas.id
        else:
            canvas_id = canvas_ref

        # 查找或建立 unified_relation（atom-atom）
        relation = s.query(UnifiedRelation).filter(
            UnifiedRelation.from_atom_id == data['source_atom_id'],
            UnifiedRelation.to_atom_id == data['target_atom_id'],
            UnifiedRelation.relation_type == rel_type,
            UnifiedRelation.is_deleted == False,
        ).first()

        if not relation:
            try:
                relation = rel_service.create_relation(
                    s,
                    relation_type=rel_type,
                    from_atom_id=data['source_atom_id'],
                    to_atom_id=data['target_atom_id'],
                    label=data.get('label', ''),
                    created_by='human',
                )
            except ValueError as e:
                return jsonify({'error': str(e)}), 400

        style = _get_relation_style(s, rel_type)

        conn = CanvasConnection(
            canvas_id=canvas_id,
            source_atom_id=data['source_atom_id'],
            target_atom_id=data['target_atom_id'],
            unified_relation_id=relation.id,
            line_style=style['line_style'],
            color=style['color'],
            label=data.get('label', '') or relation.label,
        )
        s.add(conn)
        s.flush()

        result = conn.to_dict()
        result['relation_type'] = rel_type
        return jsonify(result), 201


@bp.route('/api/canvas-connections/<int:conn_id>', methods=['PUT'])
def update_canvas_connection(conn_id):
    """更新視覺連線（標籤、關係類型等）"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '需要 JSON body'}), 400

    with session_scope() as s:
        conn = s.get(CanvasConnection, conn_id)
        if not conn:
            return jsonify({'error': '連線不存在'}), 404

        if 'label' in data:
            conn.label = data['label']
            if conn.unified_relation_id:
                rel = s.get(UnifiedRelation, conn.unified_relation_id)
                if rel:
                    rel.label = data['label']

        if 'color' in data:
            conn.color = data['color']
        if 'line_style' in data:
            conn.line_style = data['line_style']

        # 變更關係類型
        if 'relation_type' in data:
            new_type = data['relation_type']
            if new_type not in UnifiedRelation.VALID_TYPES:
                return jsonify({'error': f'無效的 relation_type: {new_type}'}), 400
            if conn.unified_relation_id:
                rel = s.get(UnifiedRelation, conn.unified_relation_id)
                if rel:
                    rel.relation_type = new_type
                    s.flush()
                    s.refresh(rel)
                    # 更新連線樣式
                    style = _get_relation_style(s, new_type)
                    conn.color = style['color']
                    conn.line_style = style['line_style']

        s.flush()
        return jsonify(conn.to_dict())


@bp.route('/api/canvas-connections/<int:conn_id>', methods=['DELETE'])
def delete_canvas_connection(conn_id):
    """刪除視覺連線，若底層 UnifiedRelation 無其他白板引用則軟刪除"""
    with session_scope() as s:
        conn = s.get(CanvasConnection, conn_id)
        if not conn:
            return jsonify({'error': '連線不存在'}), 404

        unified_rel_id = conn.unified_relation_id
        s.delete(conn)
        s.flush()

        relation_kept = False
        if unified_rel_id:
            other_refs = s.query(CanvasConnection).filter(
                CanvasConnection.unified_relation_id == unified_rel_id,
            ).count()
            if other_refs == 0:
                rel = s.get(UnifiedRelation, unified_rel_id)
                if rel:
                    rel.is_deleted = True
            else:
                relation_kept = True

        return jsonify({
            'message': f'連線 {conn_id} 已刪除',
            'relation_kept': relation_kept,
        })
