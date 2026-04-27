# -*- coding: utf-8 -*-
"""Canvases API: CRUD + Canvas Atoms + Groups + Connections"""

import datetime

from flask import Blueprint, request, jsonify
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.db import session_scope
from core.models import (
    KnowledgeAtom, UnifiedRelation, RelationTypeRegistry,
    Canvas, CanvasAtom, CanvasConnection, CanvasTrash,
    CanvasGroup, CanvasTextbox, Tag, atom_tags, canvas_group_members,
    AtomEntry, EntrySchema,
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
                'thumbnail_url': ka.thumbnail_url,
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

    # 群組（多對多 via junction table）
    groups = s.query(CanvasGroup).filter(CanvasGroup.canvas_id == canvas_id).all()
    group_member_rows = (
        s.query(canvas_group_members.c.group_id, CanvasAtom.atom_id)
        .join(CanvasAtom, CanvasAtom.id == canvas_group_members.c.canvas_atom_id)
        .filter(CanvasAtom.canvas_id == canvas_id)
        .all()
    )
    group_members = {}
    for gid, aid in group_member_rows:
        group_members.setdefault(gid, []).append(aid)

    snap_groups = [{
        'id': g.id, 'canvas_id': g.canvas_id, 'name': g.name, 'color': g.color,
        'pos_x': g.pos_x, 'pos_y': g.pos_y, 'width': g.width, 'height': g.height,
        'z_index': g.z_index, 'border_style': g.border_style,
        'atom_ids': group_members.get(g.id, []),
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
    # snapshot 連線端點需含 kind 與 textbox_id（textbox 連線在歸檔時也要保留）
    conn_full = (
        s.query(CanvasConnection)
        .filter(CanvasConnection.canvas_id == canvas_id)
        .all()
    )
    snap_conns = []
    for c in conn_full:
        d = c.to_dict()
        snap_conns.append(d)

    # 文字框
    textboxes = s.query(CanvasTextbox).filter(CanvasTextbox.canvas_id == canvas_id).all()
    snap_textboxes = [t.to_dict() for t in textboxes]

    return {
        'atoms': atoms,
        'groups': snap_groups,
        'connections': snap_conns,
        'textboxes': snap_textboxes,
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
            result['textboxes'] = canvas.snapshot.get('textboxes', [])
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
                KnowledgeAtom.id.label('ka_id'),
                KnowledgeAtom.title,
                func.left(KnowledgeAtom.content, CONTENT_PREVIEW_LEN).label('content_preview'),
                KnowledgeAtom.content_type,
                KnowledgeAtom.thumbnail_url,
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

        # --- 1b. 批次載入 entries（含 schema 資訊）---
        entries_map = {}
        if atom_ids:
            entry_rows = (
                s.query(
                    AtomEntry.id,
                    AtomEntry.atom_id,
                    AtomEntry.schema_id,
                    AtomEntry.sort_order,
                    AtomEntry.raw_text,
                    AtomEntry.summary,
                    EntrySchema.code.label('schema_code'),
                    EntrySchema.name.label('schema_name'),
                    EntrySchema.icon.label('schema_icon'),
                    EntrySchema.color.label('schema_color'),
                )
                .join(EntrySchema, EntrySchema.id == AtomEntry.schema_id)
                .filter(AtomEntry.atom_id.in_(atom_ids))
                .order_by(AtomEntry.atom_id, AtomEntry.sort_order)
                .all()
            )
            for er in entry_rows:
                entries_map.setdefault(er.atom_id, []).append({
                    'id': er.id,
                    'schema_id': er.schema_id,
                    'sort_order': er.sort_order,
                    'raw_text': er.raw_text,
                    'summary': er.summary or '',
                    'schema_code': er.schema_code,
                    'schema_name': er.schema_name,
                    'schema_icon': er.schema_icon,
                    'schema_color': er.schema_color,
                })

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

        # --- 3b. 批次載入群組歸屬（多對多）---
        ca_ids = [r.id for r in ca_rows]
        group_ids_map = {}
        if ca_ids:
            gm_rows = (
                s.query(
                    canvas_group_members.c.canvas_atom_id,
                    canvas_group_members.c.group_id,
                )
                .filter(canvas_group_members.c.canvas_atom_id.in_(ca_ids))
                .all()
            )
            for ca_id, gid in gm_rows:
                group_ids_map.setdefault(ca_id, []).append(gid)

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
                'group_ids': group_ids_map.get(r.id, []),
                'atom': {
                    'id': r.ka_id,
                    'title': r.title,
                    'content': r.content_preview or '',
                    'content_type': r.content_type,
                    'thumbnail_url': r.thumbnail_url,
                    'atom_type': r.atom_type,
                    'lifecycle': r.lifecycle,
                    'vitality_score': r.vitality_score,
                    'source': r.source,
                    'owner': r.atom_owner or 'ethan',
                    'tags': tags_map.get(r.atom_id, []),
                    'updated_at': r.atom_updated_at.isoformat() if r.atom_updated_at else None,
                    'entries': entries_map.get(r.atom_id, []),
                },
                'is_blocked': r.atom_id in blocked_ids,
            })

        # --- 4. 群組：輕量查詢（多對多 via junction table）---
        groups = s.query(CanvasGroup).filter(CanvasGroup.canvas_id == canvas_id).all()
        group_member_rows = (
            s.query(
                canvas_group_members.c.group_id,
                CanvasAtom.atom_id,
            )
            .join(CanvasAtom, CanvasAtom.id == canvas_group_members.c.canvas_atom_id)
            .filter(CanvasAtom.canvas_id == canvas_id)
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
            'border_style': g.border_style,
            'atom_ids': group_members.get(g.id, []),
        } for g in groups]

        # --- 5. 連線（unified_relations） ---
        conn_rows = (
            s.query(
                CanvasConnection.id,
                CanvasConnection.canvas_id,
                CanvasConnection.from_kind,
                CanvasConnection.to_kind,
                CanvasConnection.source_atom_id,
                CanvasConnection.target_atom_id,
                CanvasConnection.source_textbox_id,
                CanvasConnection.target_textbox_id,
                CanvasConnection.source_entry_id,
                CanvasConnection.target_entry_id,
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
            'from_kind': cr.from_kind,
            'to_kind': cr.to_kind,
            'source_atom_id': cr.source_atom_id,
            'target_atom_id': cr.target_atom_id,
            'source_textbox_id': cr.source_textbox_id,
            'target_textbox_id': cr.target_textbox_id,
            'source_entry_id': cr.source_entry_id,
            'target_entry_id': cr.target_entry_id,
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

        # --- 6. 文字框 ---
        textboxes = s.query(CanvasTextbox).filter(CanvasTextbox.canvas_id == canvas_id).all()
        result['textboxes'] = [t.to_dict() for t in textboxes]

        return jsonify(result)


@bp.route('/api/canvases/<slug>/poll')
def poll_canvas(slug):
    """輕量 polling：回傳白板上所有原子的 atom_id + updated_at。

    前端定期呼叫，比對本地快取的 updated_at，
    只對有差異的原子做進一步處理（靜默更新或衝突提示）。

    可選 ?since=ISO_TIMESTAMP，回傳該時間之後的欄位變更明細（L2 衝突提示）。
    """
    from core.models import AtomEntry, EntryFieldChangeLog, EntrySchemaField

    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        rows = (
            s.query(CanvasAtom.atom_id, KnowledgeAtom.updated_at)
            .join(KnowledgeAtom, KnowledgeAtom.id == CanvasAtom.atom_id)
            .filter(CanvasAtom.canvas_id == canvas.id)
            .all()
        )
        result = {
            'atoms': [
                {'atom_id': r.atom_id, 'updated_at': r.updated_at.isoformat()}
                for r in rows
            ],
        }

        # L2: 具體欄位變更明細
        since = request.args.get('since', '')
        if since:
            import datetime as dt
            try:
                since_dt = dt.datetime.fromisoformat(since)
            except (ValueError, TypeError):
                since_dt = None

            if since_dt:
                atom_ids = [r.atom_id for r in rows]
                changes = (
                    s.query(
                        AtomEntry.atom_id,
                        EntrySchemaField.name.label('field_name'),
                        EntrySchemaField.label.label('field_label'),
                        EntryFieldChangeLog.old_value,
                        EntryFieldChangeLog.new_value,
                        EntryFieldChangeLog.changed_by,
                        EntryFieldChangeLog.changed_at,
                    )
                    .join(AtomEntry, AtomEntry.id == EntryFieldChangeLog.entry_id)
                    .join(EntrySchemaField, EntrySchemaField.id == EntryFieldChangeLog.field_id)
                    .filter(
                        AtomEntry.atom_id.in_(atom_ids),
                        EntryFieldChangeLog.changed_at > since_dt,
                    )
                    .order_by(EntryFieldChangeLog.changed_at.desc())
                    .limit(100)
                    .all()
                )
                result['changes'] = [
                    {
                        'atom_id': c.atom_id,
                        'field': c.field_name,
                        'label': c.field_label,
                        'old': c.old_value,
                        'new': c.new_value,
                        'by': c.changed_by,
                        'at': c.changed_at.isoformat(),
                    }
                    for c in changes
                ]

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
    """在白板上放置原子（idempotent：已存在則更新位置/尺寸而非報錯，
    支援 undo/redo 重新放置同一張卡時不踩 uq_canvas_atom）"""
    data = request.get_json()
    if not data or 'atom_id' not in data:
        return jsonify({'error': '需要 atom_id'}), 400

    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        existing = s.query(CanvasAtom).filter(
            CanvasAtom.canvas_id == canvas.id,
            CanvasAtom.atom_id == data['atom_id'],
        ).first()
        if existing:
            for field in ('pos_x', 'pos_y', 'width', 'height', 'z_index', 'visual_style'):
                if field in data:
                    setattr(existing, field, data[field])
            s.flush()
            return jsonify(existing.to_dict()), 200

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
        for field in ('pos_x', 'pos_y', 'width', 'height', 'z_index', 'visual_style'):
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

def _group_to_dict(s, g):
    """群組序列化（含 junction table 成員查詢）"""
    member_rows = (
        s.query(CanvasAtom.atom_id)
        .join(canvas_group_members, canvas_group_members.c.canvas_atom_id == CanvasAtom.id)
        .filter(canvas_group_members.c.group_id == g.id)
        .all()
    )
    return {
        'id': g.id, 'canvas_id': g.canvas_id,
        'name': g.name, 'color': g.color,
        'pos_x': g.pos_x, 'pos_y': g.pos_y,
        'width': g.width, 'height': g.height,
        'z_index': g.z_index,
        'border_style': g.border_style,
        'atom_ids': [r[0] for r in member_rows],
    }


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
            border_style=data.get('border_style', 'none'),
        )
        s.add(g)
        s.flush()
        atom_ids = data.get('atom_ids', [])
        if atom_ids:
            # 多對多：新增 membership（不移除現有群組歸屬）
            ca_rows = (
                s.query(CanvasAtom.id)
                .filter(CanvasAtom.canvas_id == canvas.id, CanvasAtom.atom_id.in_(atom_ids))
                .all()
            )
            for (ca_id,) in ca_rows:
                s.execute(
                    canvas_group_members.insert().values(canvas_atom_id=ca_id, group_id=g.id)
                )
            s.flush()
        return jsonify(_group_to_dict(s, g)), 201


@bp.route('/api/canvas-groups/<int:group_id>', methods=['PUT'])
def update_canvas_group(group_id):
    """更新群組"""
    data = request.get_json()
    with session_scope() as s:
        g = s.get(CanvasGroup, group_id)
        if not g:
            return jsonify({'error': '群組不存在'}), 404
        for field in ('name', 'color', 'pos_x', 'pos_y', 'width', 'height', 'z_index', 'border_style'):
            if field in data:
                setattr(g, field, data[field])
        if 'atom_ids' in data:
            # 多對多：清除此群組的舊 membership，重建
            s.execute(
                canvas_group_members.delete().where(
                    canvas_group_members.c.group_id == g.id
                )
            )
            if data['atom_ids']:
                ca_rows = (
                    s.query(CanvasAtom.id)
                    .filter(CanvasAtom.canvas_id == g.canvas_id,
                            CanvasAtom.atom_id.in_(data['atom_ids']))
                    .all()
                )
                for (ca_id,) in ca_rows:
                    s.execute(
                        canvas_group_members.insert().values(
                            canvas_atom_id=ca_id, group_id=g.id
                        )
                    )
        s.flush()
        return jsonify(_group_to_dict(s, g))


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
# Canvas Textboxes (獨立文字框)
# ============================================================

_TEXTBOX_FIELDS = (
    'title', 'content', 'pos_x', 'pos_y', 'width', 'height', 'z_index',
    'bg_color', 'border_color', 'border_style', 'text_color',
)


@bp.route('/api/canvases/<slug>/textboxes', methods=['POST'])
def create_canvas_textbox(slug):
    """在白板上建立獨立文字框"""
    data = request.get_json() or {}
    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        tb = CanvasTextbox(canvas_id=canvas.id)
        for f in _TEXTBOX_FIELDS:
            if f in data:
                setattr(tb, f, data[f])
        s.add(tb)
        s.flush()
        return jsonify(tb.to_dict()), 201


@bp.route('/api/canvas-textboxes/<int:tb_id>', methods=['PUT'])
def update_canvas_textbox(tb_id):
    """更新文字框（位置/尺寸/標題/內文/顏色/邊框）"""
    data = request.get_json() or {}
    with session_scope() as s:
        tb = s.get(CanvasTextbox, tb_id)
        if not tb:
            return jsonify({'error': '文字框不存在'}), 404
        for f in _TEXTBOX_FIELDS:
            if f in data:
                setattr(tb, f, data[f])
        s.flush()
        return jsonify(tb.to_dict())


@bp.route('/api/canvas-textboxes/<int:tb_id>', methods=['DELETE'])
def delete_canvas_textbox(tb_id):
    """刪除文字框（hard delete；走字紙簍請改用 /trash 端點）"""
    with session_scope() as s:
        tb = s.get(CanvasTextbox, tb_id)
        if not tb:
            return jsonify({'error': '文字框不存在'}), 404
        s.delete(tb)
        return jsonify({'message': f'文字框 {tb_id} 已刪除'})


# ============================================================
# Canvas Trash (白板私有字紙簍)
# 從白板 Delete 的卡片暫存於此，可救回到當前白板
# atom 本體不動 -- 不影響其他白板的引用
# ============================================================

def _trash_to_dict_with_atom(s, t: CanvasTrash) -> dict:
    """字紙簍紀錄序列化，附帶卡片預覽用資料"""
    d = t.to_dict()
    if t.kind == 'atom' and t.atom:
        a = t.atom
        d['atom'] = {
            'id': a.id,
            'title': a.title,
            'atom_type': a.atom_type,
            'lifecycle': a.lifecycle,
            'thumbnail_url': a.thumbnail_url,
            'content_type': a.content_type,
            'content_preview': (a.content or '')[:200],
        }
    elif t.kind == 'textbox' and t.payload:
        d['textbox_preview'] = {
            'title': t.payload.get('title', ''),
            'content_preview': (t.payload.get('content') or '')[:200],
        }
    return d


@bp.route('/api/canvases/<slug>/trash', methods=['POST'])
def add_to_canvas_trash(slug):
    """把當前白板上選中的卡片送入此白板的字紙簍。
    body: {atom_ids: [int]}
    動作：對每張 atom -- 把 canvas_atoms 紀錄複製到 canvas_trash，刪除 canvas_atoms。
    """
    data = request.get_json() or {}
    atom_ids = data.get('atom_ids') or []
    if not isinstance(atom_ids, list) or not atom_ids:
        return jsonify({'error': '需要 atom_ids（非空陣列）'}), 400

    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        cas = s.query(CanvasAtom).filter(
            CanvasAtom.canvas_id == canvas.id,
            CanvasAtom.atom_id.in_(atom_ids),
        ).all()
        if not cas:
            return jsonify({'trashed_count': 0, 'items': []}), 200

        # UPSERT 處理並發：若已有 (canvas_id, atom_id) 紀錄，更新位置與時間
        # 這避免「同一 atom 短時間內兩次 Delete」並發時 race condition 撞 UNIQUE
        now = datetime.datetime.now()
        rows = [{
            'canvas_id': canvas.id,
            'atom_id': ca.atom_id,
            'deleted_at': now,
            'original_pos_x': ca.pos_x,
            'original_pos_y': ca.pos_y,
            'original_width': ca.width,
            'original_height': ca.height,
            'z_index': ca.z_index,
            'visual_style': ca.visual_style,
        } for ca in cas]
        stmt = pg_insert(CanvasTrash.__table__).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint='uq_canvas_trash',
            set_={
                'deleted_at': stmt.excluded.deleted_at,
                'original_pos_x': stmt.excluded.original_pos_x,
                'original_pos_y': stmt.excluded.original_pos_y,
                'original_width': stmt.excluded.original_width,
                'original_height': stmt.excluded.original_height,
                'z_index': stmt.excluded.z_index,
                'visual_style': stmt.excluded.visual_style,
            },
        )
        s.execute(stmt)
        # 刪除 canvas_atoms 紀錄
        for ca in cas:
            s.delete(ca)
        s.flush()

        # 重查回傳
        trashed = s.query(CanvasTrash).filter(
            CanvasTrash.canvas_id == canvas.id,
            CanvasTrash.atom_id.in_([ca.atom_id for ca in cas]),
        ).all()
        return jsonify({
            'trashed_count': len(trashed),
            'items': [_trash_to_dict_with_atom(s, t) for t in trashed],
        }), 201


@bp.route('/api/canvases/<slug>/trash', methods=['GET'])
def list_canvas_trash(slug):
    """列出當前白板的字紙簍，按 deleted_at desc"""
    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        rows = (
            s.query(CanvasTrash)
            .filter(CanvasTrash.canvas_id == canvas.id)
            .order_by(CanvasTrash.deleted_at.desc())
            .all()
        )
        return jsonify({
            'total': len(rows),
            'items': [_trash_to_dict_with_atom(s, t) for t in rows],
        })


@bp.route('/api/canvases/<slug>/trash/restore', methods=['POST'])
def restore_from_canvas_trash(slug):
    """從當前白板字紙簍救回卡片（單張或多張）。
    body: {atom_ids: [int]}
    每張卡片重建 canvas_atoms（用原座標），刪除字紙簍紀錄。
    若 canvas_atoms 已存在（被外部建出來），更新位置而非新增（idempotent）。
    """
    data = request.get_json() or {}
    atom_ids = data.get('atom_ids') or []
    if not isinstance(atom_ids, list) or not atom_ids:
        return jsonify({'error': '需要 atom_ids（非空陣列）'}), 400

    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        trash_rows = s.query(CanvasTrash).filter(
            CanvasTrash.canvas_id == canvas.id,
            CanvasTrash.atom_id.in_(atom_ids),
        ).all()

        restored_cas = []
        for t in trash_rows:
            existing = s.query(CanvasAtom).filter(
                CanvasAtom.canvas_id == canvas.id,
                CanvasAtom.atom_id == t.atom_id,
            ).first()
            if existing:
                existing.pos_x = t.original_pos_x
                existing.pos_y = t.original_pos_y
                if t.original_width is not None:
                    existing.width = t.original_width
                if t.original_height is not None:
                    existing.height = t.original_height
                existing.z_index = t.z_index
                existing.visual_style = t.visual_style
                ca = existing
            else:
                ca = CanvasAtom(
                    canvas_id=canvas.id,
                    atom_id=t.atom_id,
                    pos_x=t.original_pos_x,
                    pos_y=t.original_pos_y,
                    width=t.original_width,
                    height=t.original_height,
                    z_index=t.z_index,
                    visual_style=t.visual_style,
                )
                s.add(ca)
            s.delete(t)
            restored_cas.append(ca)
        s.flush()
        return jsonify({
            'restored_count': len(restored_cas),
            'canvas_atoms': [ca.to_dict() for ca in restored_cas],
        })


@bp.route('/api/canvases/<slug>/trash', methods=['DELETE'])
def empty_canvas_trash(slug):
    """清空當前白板字紙簍（不影響 atom 本體）。"""
    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404
        deleted = s.query(CanvasTrash).filter(
            CanvasTrash.canvas_id == canvas.id
        ).delete(synchronize_session=False)
        s.flush()
        return jsonify({'message': f'已清空 {deleted} 筆', 'deleted': deleted})


@bp.route('/api/canvases/<slug>/trash/textboxes', methods=['POST'])
def add_textboxes_to_canvas_trash(slug):
    """把指定文字框送進字紙簍。
    body: {textbox_ids: [int]}
    """
    data = request.get_json() or {}
    tb_ids = data.get('textbox_ids') or []
    if not isinstance(tb_ids, list) or not tb_ids:
        return jsonify({'error': '需要 textbox_ids（非空陣列）'}), 400

    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        tbs = s.query(CanvasTextbox).filter(
            CanvasTextbox.canvas_id == canvas.id,
            CanvasTextbox.id.in_(tb_ids),
        ).all()
        if not tbs:
            return jsonify({'trashed_count': 0, 'items': []}), 200

        now = datetime.datetime.now()
        trash_rows = []
        for tb in tbs:
            t = CanvasTrash(
                canvas_id=canvas.id,
                kind='textbox',
                deleted_at=now,
                original_pos_x=tb.pos_x,
                original_pos_y=tb.pos_y,
                original_width=tb.width,
                original_height=tb.height,
                z_index=tb.z_index,
                payload=tb.to_dict(),
            )
            s.add(t)
            trash_rows.append(t)
        # 刪除原文字框（連帶 cascade 刪相關 canvas_connections）
        for tb in tbs:
            s.delete(tb)
        s.flush()

        return jsonify({
            'trashed_count': len(trash_rows),
            'items': [_trash_to_dict_with_atom(s, t) for t in trash_rows],
        }), 201


@bp.route('/api/canvases/<slug>/trash/textboxes/restore', methods=['POST'])
def restore_textboxes_from_canvas_trash(slug):
    """從字紙簍救回文字框。
    body: {trash_ids: [int]}（textbox 沒有穩定主鍵可指定，故用 trash 紀錄 ID）
    """
    data = request.get_json() or {}
    trash_ids = data.get('trash_ids') or []
    if not isinstance(trash_ids, list) or not trash_ids:
        return jsonify({'error': '需要 trash_ids（非空陣列）'}), 400

    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        rows = s.query(CanvasTrash).filter(
            CanvasTrash.canvas_id == canvas.id,
            CanvasTrash.id.in_(trash_ids),
            CanvasTrash.kind == 'textbox',
        ).all()

        restored = []
        for t in rows:
            p = t.payload or {}
            tb = CanvasTextbox(
                canvas_id=canvas.id,
                title=p.get('title', '標題'),
                content=p.get('content', ''),
                pos_x=t.original_pos_x,
                pos_y=t.original_pos_y,
                width=t.original_width or 320,
                height=t.original_height or 180,
                z_index=t.z_index,
                bg_color=p.get('bg_color', '#fffbe6'),
                border_color=p.get('border_color', '#f59e0b'),
                border_style=p.get('border_style', 'solid'),
                text_color=p.get('text_color', '#1f2937'),
            )
            s.add(tb)
            s.delete(t)
            restored.append(tb)
        s.flush()
        return jsonify({
            'restored_count': len(restored),
            'textboxes': [tb.to_dict() for tb in restored],
        })


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
    """建立視覺連線。

    端點種類由 from_kind / to_kind 決定（'atom' | 'textbox'，未指定預設 'atom'）。
    - 兩端皆 atom：建立或重用 UnifiedRelation（行為與舊版一致）
    - 任一端是 textbox：純粹的視覺連線，不掛 UnifiedRelation，relation_type 可省略
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': '需要 JSON body'}), 400

    if 'canvas_id' not in data:
        return jsonify({'error': '缺少必要欄位: canvas_id'}), 400

    from_kind = data.get('from_kind', 'atom')
    to_kind = data.get('to_kind', 'atom')
    if from_kind not in ('atom', 'textbox') or to_kind not in ('atom', 'textbox'):
        return jsonify({'error': "from_kind/to_kind 必須是 'atom' 或 'textbox'"}), 400

    # 端點 ID 一致性檢查
    src_atom_id = data.get('source_atom_id')
    tgt_atom_id = data.get('target_atom_id')
    src_tb_id = data.get('source_textbox_id')
    tgt_tb_id = data.get('target_textbox_id')

    if from_kind == 'atom' and not src_atom_id:
        return jsonify({'error': 'from_kind=atom 需要 source_atom_id'}), 400
    if from_kind == 'textbox' and not src_tb_id:
        return jsonify({'error': 'from_kind=textbox 需要 source_textbox_id'}), 400
    if to_kind == 'atom' and not tgt_atom_id:
        return jsonify({'error': 'to_kind=atom 需要 target_atom_id'}), 400
    if to_kind == 'textbox' and not tgt_tb_id:
        return jsonify({'error': 'to_kind=textbox 需要 target_textbox_id'}), 400

    is_pure_atom = (from_kind == 'atom' and to_kind == 'atom')

    rel_type = data.get('relation_type')
    if is_pure_atom:
        if not rel_type:
            return jsonify({'error': '缺少必要欄位: relation_type'}), 400
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

        # entry-level 連線只在 atom-atom 情境下成立
        src_entry_id = data.get('source_entry_id') if is_pure_atom else None
        tgt_entry_id = data.get('target_entry_id') if is_pure_atom else None

        relation = None
        style = {'color': '#94a3b8', 'line_style': 'solid'}

        if is_pure_atom:
            # unified_relation 端點：entry 優先，否則 atom
            ur_from_atom = None if src_entry_id else src_atom_id
            ur_from_entry = src_entry_id
            ur_to_atom = None if tgt_entry_id else tgt_atom_id
            ur_to_entry = tgt_entry_id

            filter_conds = [
                UnifiedRelation.relation_type == rel_type,
                UnifiedRelation.is_deleted == False,
            ]
            if ur_from_atom:
                filter_conds.append(UnifiedRelation.from_atom_id == ur_from_atom)
            if ur_from_entry:
                filter_conds.append(UnifiedRelation.from_entry_id == ur_from_entry)
            if ur_to_atom:
                filter_conds.append(UnifiedRelation.to_atom_id == ur_to_atom)
            if ur_to_entry:
                filter_conds.append(UnifiedRelation.to_entry_id == ur_to_entry)

            relation = s.query(UnifiedRelation).filter(*filter_conds).first()

            if not relation:
                try:
                    relation = rel_service.create_relation(
                        s,
                        relation_type=rel_type,
                        from_atom_id=ur_from_atom,
                        to_atom_id=ur_to_atom,
                        from_entry_id=ur_from_entry,
                        to_entry_id=ur_to_entry,
                        label=data.get('label', ''),
                        created_by='human',
                    )
                except ValueError as e:
                    return jsonify({'error': str(e)}), 400

            style = _get_relation_style(s, rel_type)

        conn = CanvasConnection(
            canvas_id=canvas_id,
            from_kind=from_kind,
            to_kind=to_kind,
            source_atom_id=src_atom_id if from_kind == 'atom' else None,
            target_atom_id=tgt_atom_id if to_kind == 'atom' else None,
            source_textbox_id=src_tb_id if from_kind == 'textbox' else None,
            target_textbox_id=tgt_tb_id if to_kind == 'textbox' else None,
            source_entry_id=src_entry_id,
            target_entry_id=tgt_entry_id,
            unified_relation_id=relation.id if relation else None,
            line_style=style['line_style'],
            color=style['color'],
            label=data.get('label', '') or (relation.label if relation else ''),
        )
        s.add(conn)
        s.flush()

        result = conn.to_dict()
        if rel_type:
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
