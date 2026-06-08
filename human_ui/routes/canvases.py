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
    CanvasGroup, CanvasTextbox, CanvasMindmapShell,
    Tag, atom_tags, canvas_group_members, canvas_tags,
    AtomEntry, EntrySchema, EntrySchemaField, EntryFieldValue,
    StandaloneEntry, CanvasStandaloneEntry,
)
from core.tiptap_node_id import allocate_node_id
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
            'mindmap_shell_id': ca.mindmap_shell_id,
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

    # 心智圖殼
    shells = s.query(CanvasMindmapShell).filter(CanvasMindmapShell.canvas_id == canvas_id).all()
    snap_shells = [sh.to_dict() for sh in shells]

    # 樹結構（tree_parent relations）-- 限該白板上的 atom
    tree_parents = []
    if atom_ids:
        tp_rows = (
            s.query(
                UnifiedRelation.from_atom_id,
                UnifiedRelation.to_atom_id,
                UnifiedRelation.sort_order,
            )
            .filter(
                UnifiedRelation.relation_type == 'tree_parent',
                UnifiedRelation.is_deleted == False,
                UnifiedRelation.from_atom_id.in_(atom_ids),
            )
            .all()
        )
        tree_parents = [
            {'child_atom_id': r[0], 'parent_atom_id': r[1], 'sort_order': r[2]}
            for r in tp_rows
        ]

    # 獨立 entry（P3a：白板上與卡片同階層的 structuredEntry）
    se_rows = (
        s.query(CanvasStandaloneEntry, StandaloneEntry)
        .join(StandaloneEntry, StandaloneEntry.id == CanvasStandaloneEntry.standalone_entry_id)
        .filter(
            CanvasStandaloneEntry.canvas_id == canvas_id,
            StandaloneEntry.is_deleted == False,  # noqa: E712
        )
        .all()
    )
    snap_standalone_entries = []
    for cse, se in se_rows:
        snap_standalone_entries.append({
            'id': cse.id,
            'canvas_id': cse.canvas_id,
            'standalone_entry_id': cse.standalone_entry_id,
            'pos_x': cse.pos_x,
            'pos_y': cse.pos_y,
            'width': cse.width,
            'height': cse.height,
            'z_index': cse.z_index,
            'visual_style': cse.visual_style,
            'entry': se.to_dict(),
        })

    return {
        'atoms': atoms,
        'groups': snap_groups,
        'connections': snap_conns,
        'textboxes': snap_textboxes,
        'mindmap_shells': snap_shells,
        'tree_parents': tree_parents,
        'standalone_entries': snap_standalone_entries,
    }


# ============================================================
# Canvas CRUD
# ============================================================

@bp.route('/api/canvases', methods=['GET'])
def list_canvases():
    from sqlalchemy.orm import joinedload
    include_archived = request.args.get('include_archived', '0') == '1'
    only_projects = request.args.get('only_projects', '0') == '1'
    # tag_ids=1,2,3 -> ANY 命中即列入（多選 OR 語意）
    tag_ids_raw = request.args.get('tag_ids', '').strip()
    tag_ids = [int(x) for x in tag_ids_raw.split(',') if x.strip().isdigit()] if tag_ids_raw else []
    with session_scope() as s:
        q = s.query(Canvas).options(joinedload(Canvas.tags))
        if not include_archived:
            q = q.filter(Canvas.is_archived == False)
        if only_projects:
            q = q.filter(Canvas.is_project == True)
        if tag_ids:
            q = q.filter(Canvas.tags.any(Tag.id.in_(tag_ids)))
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
            result['mindmap_shells'] = canvas.snapshot.get('mindmap_shells', [])
            result['tree_parents'] = canvas.snapshot.get('tree_parents', [])
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
                CanvasAtom.mindmap_shell_id,
                KnowledgeAtom.id.label('ka_id'),
                KnowledgeAtom.title,
                func.left(KnowledgeAtom.content, CONTENT_PREVIEW_LEN).label('content_preview'),
                func.length(func.trim(func.coalesce(KnowledgeAtom.content_plain, ''))).label('content_plain_len'),
                KnowledgeAtom.content_type,
                KnowledgeAtom.content_json,
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

            # 對 idcard / image entries 補上 field_values，供白板渲染縮圖
            thumb_schema_codes = ('idcard', 'image')
            thumb_entry_ids = [
                e['id']
                for elist in entries_map.values()
                for e in elist
                if e.get('schema_code') in thumb_schema_codes
            ]
            if thumb_entry_ids:
                fv_rows = (
                    s.query(
                        EntryFieldValue.entry_id,
                        EntrySchemaField.name,
                        EntryFieldValue.value,
                    )
                    .join(
                        EntrySchemaField,
                        EntrySchemaField.id == EntryFieldValue.field_id,
                    )
                    .filter(EntryFieldValue.entry_id.in_(thumb_entry_ids))
                    .all()
                )
                fv_map = {}
                for eid, fname, fvalue in fv_rows:
                    fv_map.setdefault(eid, {})[fname] = fvalue
                for elist in entries_map.values():
                    for e in elist:
                        if e.get('schema_code') in thumb_schema_codes:
                            e['field_values'] = fv_map.get(e['id'], {})

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
        # media 卡片(PDF/圖片)需要 content_json 才能在白板正確渲染縮圖；
        # 一般卡片仍只回 content_preview 維持 payload 輕量
        result['atoms'] = []
        for r in ca_rows:
            atom_dict = {
                'id': r.ka_id,
                'title': r.title,
                'content': r.content_preview or '',
                'has_content': (r.content_plain_len or 0) > 0,
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
            }
            if r.content_type == 'media':
                atom_dict['content_json'] = r.content_json
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
                'mindmap_shell_id': r.mindmap_shell_id,
                'atom': atom_dict,
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
                CanvasConnection.source_standalone_entry_id,
                CanvasConnection.target_standalone_entry_id,
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
            'source_standalone_entry_id': cr.source_standalone_entry_id,
            'target_standalone_entry_id': cr.target_standalone_entry_id,
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

        # --- 7. 心智圖殼 ---
        shells = (
            s.query(CanvasMindmapShell)
            .filter(CanvasMindmapShell.canvas_id == canvas_id)
            .all()
        )
        result['mindmap_shells'] = [sh.to_dict() for sh in shells]

        # --- 8. 樹結構（tree_parent relations，僅限本白板的 atom）---
        result['tree_parents'] = []
        if atom_ids:
            tp_rows = (
                s.query(
                    UnifiedRelation.from_atom_id,
                    UnifiedRelation.to_atom_id,
                    UnifiedRelation.sort_order,
                )
                .filter(
                    UnifiedRelation.relation_type == 'tree_parent',
                    UnifiedRelation.is_deleted == False,
                    UnifiedRelation.from_atom_id.in_(atom_ids),
                )
                .all()
            )
            result['tree_parents'] = [
                {'child_atom_id': r[0], 'parent_atom_id': r[1], 'sort_order': r[2]}
                for r in tp_rows
            ]

        # --- 9. 獨立 entry (P3a) ---
        se_rows = (
            s.query(CanvasStandaloneEntry, StandaloneEntry)
            .join(StandaloneEntry, StandaloneEntry.id == CanvasStandaloneEntry.standalone_entry_id)
            .filter(
                CanvasStandaloneEntry.canvas_id == canvas_id,
                StandaloneEntry.is_deleted == False,  # noqa: E712
            )
            .all()
        )
        result['standalone_entries'] = [
            {
                'id': cse.id,
                'canvas_id': cse.canvas_id,
                'standalone_entry_id': cse.standalone_entry_id,
                'pos_x': cse.pos_x,
                'pos_y': cse.pos_y,
                'width': cse.width,
                'height': cse.height,
                'z_index': cse.z_index,
                'visual_style': cse.visual_style,
                'entry': se.to_dict(),
            }
            for cse, se in se_rows
        ]

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
                       'is_project',
                       'viewport_x', 'viewport_y', 'viewport_zoom', 'settings'):
            if field in data:
                setattr(canvas, field, data[field])
        if 'tag_ids' in data:
            ids = data['tag_ids'] or []
            tags = s.query(Tag).filter(Tag.id.in_(ids)).all() if ids else []
            canvas.tags = tags
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
            for field in ('pos_x', 'pos_y', 'width', 'height', 'z_index', 'visual_style', 'mindmap_shell_id'):
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
            mindmap_shell_id=data.get('mindmap_shell_id'),
        )
        s.add(ca)
        s.flush()
        return jsonify(ca.to_dict()), 201


@bp.route('/api/canvas-atoms/<int:ca_id>', methods=['PUT'])
def update_canvas_atom(ca_id):
    """更新原子在白板上的位置/樣式/心智圖殼歸屬"""
    data = request.get_json()
    with session_scope() as s:
        ca = s.get(CanvasAtom, ca_id)
        if not ca:
            return jsonify({'error': '不存在'}), 404
        for field in ('pos_x', 'pos_y', 'width', 'height', 'z_index', 'visual_style', 'mindmap_shell_id'):
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
# Canvas Standalone Entries（P3a：白板獨立 structuredEntry placement）
# ============================================================

@bp.route('/api/canvases/<slug>/standalone-entries', methods=['POST'])
def add_standalone_entry_to_canvas(slug):
    """放置獨立 entry 到白板。

    body 兩種模式：
      A. {standalone_entry_id, pos_x, pos_y, ...}  -- 放置既有 entry
      B. {schema_code, raw_text?, field_values?, pos_x, pos_y, ...}  -- 一次建立 + 放置
    """
    data = request.get_json() or {}
    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        se_id = data.get('standalone_entry_id')
        if se_id is None:
            # 模式 B：一次建立 + 放置
            schema_code = data.get('schema_code', 'freetext')
            schema = s.query(EntrySchema).filter_by(code=schema_code).first()
            if not schema:
                return jsonify({'error': f'未知 schema_code: {schema_code}'}), 400
            se = StandaloneEntry(
                schema_id=schema.id,
                schema_code=schema_code,
                raw_text=data.get('raw_text', ''),
                summary=data.get('summary', ''),
                field_values=data.get('field_values', {}) or {},
                node_id=allocate_node_id(s),
                owner=data.get('owner', 'ethan'),
            )
            s.add(se)
            s.flush()
            se_id = se.id

        existing = s.query(CanvasStandaloneEntry).filter(
            CanvasStandaloneEntry.canvas_id == canvas.id,
            CanvasStandaloneEntry.standalone_entry_id == se_id,
        ).first()
        if existing:
            for field in ('pos_x', 'pos_y', 'width', 'height', 'z_index', 'visual_style'):
                if field in data:
                    setattr(existing, field, data[field])
            s.flush()
            return jsonify(existing.to_dict()), 200

        cse = CanvasStandaloneEntry(
            canvas_id=canvas.id,
            standalone_entry_id=se_id,
            pos_x=data.get('pos_x', 100),
            pos_y=data.get('pos_y', 100),
            width=data.get('width'),
            height=data.get('height'),
            z_index=data.get('z_index', 0),
            visual_style=data.get('visual_style', '{}'),
        )
        s.add(cse)
        s.flush()
        s.refresh(cse)  # 確保 entry relationship 已載入供 to_dict 使用
        return jsonify(cse.to_dict()), 201


@bp.route('/api/canvas-standalone-entries/<int:cse_id>', methods=['PUT'])
def update_canvas_standalone_entry(cse_id):
    """更新獨立 entry 在白板上的位置／樣式"""
    data = request.get_json() or {}
    with session_scope() as s:
        cse = s.get(CanvasStandaloneEntry, cse_id)
        if not cse:
            return jsonify({'error': '不存在'}), 404
        for field in ('pos_x', 'pos_y', 'width', 'height', 'z_index', 'visual_style'):
            if field in data:
                setattr(cse, field, data[field])
        s.flush()
        return jsonify(cse.to_dict())


@bp.route('/api/canvas-standalone-entries/<int:cse_id>', methods=['DELETE'])
def remove_standalone_entry_from_canvas(cse_id):
    """從白板移除獨立 entry placement（不刪 entry 本體）"""
    with session_scope() as s:
        cse = s.get(CanvasStandaloneEntry, cse_id)
        if not cse:
            return jsonify({'error': '不存在'}), 404
        s.delete(cse)
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


@bp.route('/api/canvas-textboxes/<int:tb_id>/transfer', methods=['POST'])
def transfer_canvas_textbox(tb_id):
    """轉移文字框到另一個白板。

    mode='move': 更新 canvas_id（文字框本身及其連線移到目標白板）
    mode='copy': 在目標白板建立一份複本（原白板保留）

    body: { target_canvas_slug: str, mode: 'move'|'copy' }
    """
    data = request.get_json() or {}
    target_slug = data.get('target_canvas_slug')
    mode = data.get('mode', 'move')

    if not target_slug:
        return jsonify({'error': '缺少 target_canvas_slug'}), 400
    if mode not in ('move', 'copy'):
        return jsonify({'error': 'mode 必須是 move 或 copy'}), 400

    with session_scope() as s:
        tb = s.get(CanvasTextbox, tb_id)
        if not tb:
            return jsonify({'error': '文字框不存在'}), 404

        target_canvas = _get_canvas_by_slug(s, target_slug)
        if not target_canvas:
            return jsonify({'error': '目標白板不存在'}), 404

        if target_canvas.id == tb.canvas_id:
            return jsonify({'error': '來源與目標白板相同'}), 400

        src_canvas_id = tb.canvas_id

        if mode == 'move':
            # 目標白板上已存在的 atom_id 集合
            target_atom_ids = {
                row[0] for row in
                s.query(CanvasAtom.atom_id)
                .filter(CanvasAtom.canvas_id == target_canvas.id)
                .all()
            }

            # 取所有涉及此文字框的連線，逐條判斷另一端是否在目標白板
            all_conns = (
                s.query(CanvasConnection)
                .filter(
                    CanvasConnection.canvas_id == src_canvas_id,
                    (CanvasConnection.source_textbox_id == tb_id) |
                    (CanvasConnection.target_textbox_id == tb_id),
                )
                .all()
            )
            for conn in all_conns:
                other_atom_id = (
                    conn.source_atom_id if conn.to_kind == 'textbox' and conn.target_textbox_id == tb_id
                    else conn.target_atom_id if conn.from_kind == 'textbox' and conn.source_textbox_id == tb_id
                    else None
                )
                other_tb_id = (
                    conn.source_textbox_id if conn.target_textbox_id == tb_id and conn.source_textbox_id != tb_id
                    else conn.target_textbox_id if conn.source_textbox_id == tb_id and conn.target_textbox_id != tb_id
                    else None
                )
                if other_atom_id is not None:
                    # 另一端是 atom：只在目標白板有此 atom 時才保留
                    if other_atom_id in target_atom_ids:
                        conn.canvas_id = target_canvas.id
                    else:
                        s.delete(conn)
                elif other_tb_id is not None:
                    # 另一端是不同的文字框（不跟著移動）→ 丟棄
                    s.delete(conn)
                else:
                    # 兩端都是此文字框（self-loop）→ 移動
                    conn.canvas_id = target_canvas.id

            tb.canvas_id = target_canvas.id
            s.flush()
            return jsonify({'message': f'文字框已移動到白板 {target_slug}', 'textbox': tb.to_dict()})

        else:  # copy
            new_tb = CanvasTextbox(
                canvas_id=target_canvas.id,
                title=tb.title,
                content=tb.content,
                pos_x=tb.pos_x,
                pos_y=tb.pos_y,
                width=tb.width,
                height=tb.height,
                z_index=tb.z_index,
                bg_color=tb.bg_color,
                border_color=tb.border_color,
                border_style=tb.border_style,
                text_color=tb.text_color,
            )
            s.add(new_tb)
            s.flush()
            return jsonify({'message': f'文字框已複製到白板 {target_slug}', 'textbox': new_tb.to_dict()}), 201


# ============================================================
# Canvas Mindmap Shells + Tree Operations
# 殼 = 視覺容器（canvas_mindmap_shells）
# 樹 = unified_relations(relation_type='tree_parent')，方向 child -> parent
# 殼內節點 = canvas_atoms.mindmap_shell_id IS NOT NULL，render 為 mini 卡
# ============================================================

_SHELL_FIELDS = (
    'title', 'pos_x', 'pos_y', 'width', 'height', 'z_index',
    'color', 'layout', 'line_style', 'root_atom_id',
)


def _tree_descendants(s, root_atom_id):
    """BFS 取得 root_atom 的所有後代 atom_id（含 root），透過 tree_parent relations 走訪。"""
    seen = {root_atom_id}
    queue = [root_atom_id]
    while queue:
        next_q = []
        children = (
            s.query(UnifiedRelation.from_atom_id)
            .filter(
                UnifiedRelation.relation_type == 'tree_parent',
                UnifiedRelation.is_deleted == False,
                UnifiedRelation.to_atom_id.in_(queue),
            )
            .all()
        )
        for (cid,) in children:
            if cid not in seen:
                seen.add(cid)
                next_q.append(cid)
        queue = next_q
    return seen


def _next_sibling_sort_order(s, parent_atom_id):
    """同層次序：取現有最大 sort_order + 1（同 parent 下）"""
    if parent_atom_id is None:
        return 0
    max_order = (
        s.query(func.max(UnifiedRelation.sort_order))
        .filter(
            UnifiedRelation.relation_type == 'tree_parent',
            UnifiedRelation.is_deleted == False,
            UnifiedRelation.to_atom_id == parent_atom_id,
        )
        .scalar()
    )
    return (max_order or 0) + 1


def _get_tree_parent(s, child_atom_id):
    """取得 child 的 tree_parent relation（單一），不存在回 None"""
    return (
        s.query(UnifiedRelation)
        .filter(
            UnifiedRelation.relation_type == 'tree_parent',
            UnifiedRelation.is_deleted == False,
            UnifiedRelation.from_atom_id == child_atom_id,
        )
        .first()
    )


@bp.route('/api/canvases/<slug>/mindmap-shells', methods=['POST'])
def create_mindmap_shell(slug):
    """建立心智圖殼 + root 節點。

    body: {
        title: str (殼標題),
        pos_x, pos_y, width, height, z_index, color, layout (殼屬性),
        root_title: str (root 節點 atom 標題，預設 '主題'),
        root_atom_id: int (可選；若提供則用既有 atom 當 root，否則新建)
    }
    回傳 { shell, root_canvas_atom, root_atom }
    """
    data = request.get_json() or {}
    with session_scope() as s:
        canvas = _get_canvas_by_slug(s, slug)
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        # 1) 建立殼（暫不設 root_atom_id，下面建好 root 後再 set）
        shell = CanvasMindmapShell(canvas_id=canvas.id)
        for f in _SHELL_FIELDS:
            if f in data and f != 'root_atom_id':
                setattr(shell, f, data[f])
        s.add(shell)
        s.flush()

        # 2) root atom: 既有或新建
        if data.get('root_atom_id'):
            root_atom = s.get(KnowledgeAtom, int(data['root_atom_id']))
            if not root_atom:
                return jsonify({'error': 'root_atom_id 不存在'}), 400
        else:
            root_atom = KnowledgeAtom(
                title=data.get('root_title') or '主題',
                content='',
                atom_type='F',
                source='human',
                owner='ethan',
            )
            s.add(root_atom)
            s.flush()

        shell.root_atom_id = root_atom.id

        # 3) root 的 canvas_atom（idempotent: 若已在白板上，沿用並設 mindmap_shell_id）
        existing = s.query(CanvasAtom).filter(
            CanvasAtom.canvas_id == canvas.id,
            CanvasAtom.atom_id == root_atom.id,
        ).first()
        if existing:
            existing.mindmap_shell_id = shell.id
            existing.pos_x = shell.pos_x + 20
            existing.pos_y = shell.pos_y + 40
            root_ca = existing
        else:
            root_ca = CanvasAtom(
                canvas_id=canvas.id,
                atom_id=root_atom.id,
                pos_x=shell.pos_x + 20,
                pos_y=shell.pos_y + 40,
                mindmap_shell_id=shell.id,
            )
            s.add(root_ca)
        s.flush()

        return jsonify({
            'shell': shell.to_dict(),
            'root_canvas_atom': root_ca.to_dict(),
            'root_atom': root_atom.to_dict(),
        }), 201


@bp.route('/api/canvas-mindmap-shells/<int:shell_id>', methods=['PUT'])
def update_mindmap_shell(shell_id):
    """更新殼屬性（標題/位置/大小/顏色/layout/root_atom_id）"""
    data = request.get_json() or {}
    with session_scope() as s:
        shell = s.get(CanvasMindmapShell, shell_id)
        if not shell:
            return jsonify({'error': '心智圖殼不存在'}), 404
        for f in _SHELL_FIELDS:
            if f in data:
                setattr(shell, f, data[f])
        s.flush()
        return jsonify(shell.to_dict())


@bp.route('/api/canvas-mindmap-shells/<int:shell_id>', methods=['DELETE'])
def delete_mindmap_shell(shell_id):
    """刪除心智圖殼。

    mode='shell_only'(預設): 殼刪除，內部 atom 留在白板上變獨立卡（清 mindmap_shell_id），
                             tree_parent relations 保留（樹結構不損）
    mode='with_atoms':       殼內所有 atom 一併送入字紙簍（atom 本體不刪，可救回）
    """
    mode = (request.args.get('mode') or 'shell_only').lower()
    with session_scope() as s:
        shell = s.get(CanvasMindmapShell, shell_id)
        if not shell:
            return jsonify({'error': '心智圖殼不存在'}), 404
        canvas_id = shell.canvas_id

        members = (
            s.query(CanvasAtom)
            .filter(CanvasAtom.mindmap_shell_id == shell_id)
            .all()
        )

        if mode == 'with_atoms':
            atom_ids = [ca.atom_id for ca in members]
            tree_parents_map = _collect_tree_parents(s, atom_ids)
            shell_snapshot = _shell_to_snapshot(shell)
            # shell_snapshot 只附在 root atom 的 trash entry（restore 時重建殼）
            for ca in members:
                payload = {
                    'mindmap_shell_id': shell_id,
                    'tree_parent': tree_parents_map.get(ca.atom_id),
                }
                if shell.root_atom_id is not None and ca.atom_id == shell.root_atom_id:
                    payload['shell_snapshot'] = shell_snapshot
                trash = CanvasTrash(
                    canvas_id=canvas_id,
                    kind='atom',
                    atom_id=ca.atom_id,
                    original_pos_x=ca.pos_x,
                    original_pos_y=ca.pos_y,
                    original_width=ca.width,
                    original_height=ca.height,
                    z_index=ca.z_index,
                    visual_style=ca.visual_style,
                    payload=payload,
                )
                s.add(trash)
                s.delete(ca)
            if atom_ids:
                (
                    s.query(UnifiedRelation)
                    .filter(
                        UnifiedRelation.relation_type == 'tree_parent',
                        UnifiedRelation.from_atom_id.in_(atom_ids),
                    )
                    .update({'is_deleted': True}, synchronize_session=False)
                )
        else:
            # shell_only: 清 mindmap_shell_id，atom 留在白板上
            for ca in members:
                ca.mindmap_shell_id = None

        s.delete(shell)
        return jsonify({'message': f'心智圖殼 {shell_id} 已刪除', 'mode': mode})


@bp.route('/api/canvas-mindmap-shells/<int:shell_id>/transfer', methods=['POST'])
def transfer_mindmap_shell(shell_id):
    """轉移心智圖殼到另一個白板。

    mode='move': 整個殼 + 所有節點遷移到目標白板（來源白板移除）
    mode='copy': 深度複製殼 + 所有節點到目標白板（來源白板保留，建立全新 atoms）

    body: { target_canvas_slug: str, mode: 'move'|'copy' }
    回傳: { message, shell (新殼 dict) }
    """
    data = request.get_json() or {}
    target_slug = data.get('target_canvas_slug')
    mode = data.get('mode', 'move')

    if not target_slug:
        return jsonify({'error': '缺少 target_canvas_slug'}), 400
    if mode not in ('move', 'copy'):
        return jsonify({'error': 'mode 必須是 move 或 copy'}), 400

    with session_scope() as s:
        shell = s.get(CanvasMindmapShell, shell_id)
        if not shell:
            return jsonify({'error': '心智圖殼不存在'}), 404

        target_canvas = _get_canvas_by_slug(s, target_slug)
        if not target_canvas:
            return jsonify({'error': '目標白板不存在'}), 404

        if target_canvas.id == shell.canvas_id:
            return jsonify({'error': '來源與目標白板相同'}), 400

        members = (
            s.query(CanvasAtom)
            .filter(CanvasAtom.mindmap_shell_id == shell_id)
            .all()
        )
        atom_ids = [ca.atom_id for ca in members]
        src_canvas_id = shell.canvas_id

        if mode == 'move':
            # 在目標白板建立新殼（複製所有殼屬性）
            new_shell = CanvasMindmapShell(canvas_id=target_canvas.id)
            for f in _SHELL_FIELDS:
                setattr(new_shell, f, getattr(shell, f))
            s.add(new_shell)
            s.flush()

            # 移動所有 CanvasAtom 到目標白板
            for ca in members:
                ca.canvas_id = target_canvas.id
                ca.mindmap_shell_id = new_shell.id

            # 移動來源白板上連接心智圖節點間的 CanvasConnection
            if atom_ids:
                conns = (
                    s.query(CanvasConnection)
                    .filter(
                        CanvasConnection.canvas_id == src_canvas_id,
                        CanvasConnection.from_kind == 'atom',
                        CanvasConnection.to_kind == 'atom',
                        CanvasConnection.source_atom_id.in_(atom_ids),
                        CanvasConnection.target_atom_id.in_(atom_ids),
                    )
                    .all()
                )
                for conn in conns:
                    conn.canvas_id = target_canvas.id

            s.delete(shell)
            s.flush()
            return jsonify({
                'message': f'心智圖殼已移動到白板 {target_slug}',
                'shell': new_shell.to_dict(),
            })

        else:  # copy
            # 建立 old_atom_id -> new KnowledgeAtom 映射
            atom_map = {}
            for ca in members:
                old_atom = s.get(KnowledgeAtom, ca.atom_id)
                if not old_atom:
                    continue
                new_atom = KnowledgeAtom(
                    title=old_atom.title,
                    content=old_atom.content,
                    content_plain=old_atom.content_plain,
                    content_json=old_atom.content_json,
                    content_type=old_atom.content_type,
                    atom_type=old_atom.atom_type,
                    source='human',
                    owner=old_atom.owner,
                    sensitivity=old_atom.sensitivity,
                )
                s.add(new_atom)
                atom_map[ca.atom_id] = new_atom
            s.flush()

            new_root_atom = atom_map.get(shell.root_atom_id)
            if not new_root_atom:
                return jsonify({'error': '無法複製 root 節點'}), 500

            # 建立新殼
            new_shell = CanvasMindmapShell(canvas_id=target_canvas.id)
            for f in _SHELL_FIELDS:
                if f != 'root_atom_id':
                    setattr(new_shell, f, getattr(shell, f))
            new_shell.root_atom_id = new_root_atom.id
            s.add(new_shell)
            s.flush()

            # 取 tree_parent relations
            tree_rels = (
                s.query(UnifiedRelation)
                .filter(
                    UnifiedRelation.relation_type == 'tree_parent',
                    UnifiedRelation.is_deleted == False,
                    UnifiedRelation.from_atom_id.in_(atom_ids),
                )
                .all()
            ) if atom_ids else []

            # 建立新 CanvasAtom
            for ca in members:
                new_atom = atom_map.get(ca.atom_id)
                if not new_atom:
                    continue
                s.add(CanvasAtom(
                    canvas_id=target_canvas.id,
                    atom_id=new_atom.id,
                    pos_x=ca.pos_x,
                    pos_y=ca.pos_y,
                    width=ca.width,
                    height=ca.height,
                    z_index=ca.z_index,
                    visual_style=ca.visual_style,
                    mindmap_shell_id=new_shell.id,
                ))

            # 複製 tree_parent relations（舊 id -> 新 id）
            for rel in tree_rels:
                from_new = atom_map.get(rel.from_atom_id)
                to_new = atom_map.get(rel.to_atom_id)
                if from_new and to_new:
                    s.add(UnifiedRelation(
                        relation_type='tree_parent',
                        from_atom_id=from_new.id,
                        to_atom_id=to_new.id,
                        sort_order=rel.sort_order,
                        is_deleted=False,
                    ))

            # 複製 CanvasConnections（節點間）
            if atom_ids:
                conns = (
                    s.query(CanvasConnection)
                    .filter(
                        CanvasConnection.canvas_id == src_canvas_id,
                        CanvasConnection.from_kind == 'atom',
                        CanvasConnection.to_kind == 'atom',
                        CanvasConnection.source_atom_id.in_(atom_ids),
                        CanvasConnection.target_atom_id.in_(atom_ids),
                    )
                    .all()
                )
                for conn in conns:
                    src_new = atom_map.get(conn.source_atom_id)
                    tgt_new = atom_map.get(conn.target_atom_id)
                    if src_new and tgt_new:
                        s.add(CanvasConnection(
                            canvas_id=target_canvas.id,
                            from_kind='atom',
                            to_kind='atom',
                            source_atom_id=src_new.id,
                            target_atom_id=tgt_new.id,
                            line_style=conn.line_style,
                            color=conn.color,
                            label=conn.label,
                            animated=conn.animated,
                        ))

            s.flush()
            return jsonify({
                'message': f'心智圖殼已複製到白板 {target_slug}',
                'shell': new_shell.to_dict(),
            }), 201


def _collect_tree_parents(s, atom_ids):
    """取得 atom_ids 各自的 tree_parent relation（dict: atom_id -> {to_atom_id, sort_order}）。
    必須在 mark is_deleted 之前呼叫。"""
    if not atom_ids:
        return {}
    rels = (
        s.query(UnifiedRelation)
        .filter(
            UnifiedRelation.relation_type == 'tree_parent',
            UnifiedRelation.is_deleted == False,
            UnifiedRelation.from_atom_id.in_(atom_ids),
        )
        .all()
    )
    return {
        r.from_atom_id: {'to_atom_id': r.to_atom_id, 'sort_order': r.sort_order}
        for r in rels
    }


def _shell_to_snapshot(shell):
    """殼快照（不含 id），給 trash payload 用 -- restore 時可重建殼。"""
    return {
        'title': shell.title,
        'pos_x': shell.pos_x,
        'pos_y': shell.pos_y,
        'width': shell.width,
        'height': shell.height,
        'z_index': shell.z_index,
        'color': shell.color,
        'layout': shell.layout,
    }


@bp.route('/api/canvas-mindmap-shells/<int:shell_id>/nodes', methods=['POST'])
def add_mindmap_node(shell_id):
    """在殼內新增節點（child 或 sibling）。

    body: {
        mode: 'child' | 'sibling',
        anchor_atom_id: int,            # mode='child': 父；mode='sibling': 兄
        title: str,                     # 新節點 atom 標題（可空）
        pos_x, pos_y: float (可選)      # 由前端 layout 決定，或預設殼內某位置
    }
    回傳 { atom, canvas_atom, tree_parent_relation }
    """
    data = request.get_json() or {}
    mode = (data.get('mode') or 'child').lower()
    anchor_id = data.get('anchor_atom_id')

    if mode not in ('child', 'sibling'):
        return jsonify({'error': "mode 必須是 'child' 或 'sibling'"}), 400
    if not anchor_id:
        return jsonify({'error': '需要 anchor_atom_id'}), 400

    with session_scope() as s:
        shell = s.get(CanvasMindmapShell, shell_id)
        if not shell:
            return jsonify({'error': '心智圖殼不存在'}), 404

        # 決定新節點的 parent
        if mode == 'child':
            parent_atom_id = int(anchor_id)
        else:
            anchor_rel = _get_tree_parent(s, int(anchor_id))
            parent_atom_id = anchor_rel.to_atom_id if anchor_rel else None
            # sibling 模式但 anchor 是 root（沒 parent）：不允許
            if parent_atom_id is None:
                return jsonify({'error': 'root 節點無同層兄弟，請改用 child 模式'}), 400

        # 1) 建立 atom
        atom = KnowledgeAtom(
            title=data.get('title') or '',
            content='',
            atom_type='F',
            source='human',
            owner='ethan',
        )
        s.add(atom)
        s.flush()

        # 2) 建立 canvas_atom（位置由前端送或預設殼內）
        ca = CanvasAtom(
            canvas_id=shell.canvas_id,
            atom_id=atom.id,
            pos_x=data.get('pos_x', shell.pos_x + 40),
            pos_y=data.get('pos_y', shell.pos_y + 40),
            mindmap_shell_id=shell_id,
        )
        s.add(ca)
        s.flush()

        # 3) tree_parent relation
        rel = UnifiedRelation(
            from_atom_id=atom.id,
            to_atom_id=parent_atom_id,
            relation_type='tree_parent',
            sort_order=_next_sibling_sort_order(s, parent_atom_id),
            created_by='human',
        )
        s.add(rel)
        s.flush()

        return jsonify({
            'atom': atom.to_dict(),
            'canvas_atom': ca.to_dict(),
            'tree_parent_relation': rel.to_dict(),
        }), 201


@bp.route('/api/canvas-mindmap-shells/<int:shell_id>/nodes/<int:atom_id>/move', methods=['PUT'])
def move_mindmap_node(shell_id, atom_id):
    """移動節點到不同 parent / 重排同層次序。

    body: { new_parent_atom_id: int|null, sort_order: int|null }
    cycle 防呆: new_parent 不能是 atom 自己或自己的後代
    """
    data = request.get_json() or {}
    new_parent_id = data.get('new_parent_atom_id')
    new_order = data.get('sort_order')

    with session_scope() as s:
        shell = s.get(CanvasMindmapShell, shell_id)
        if not shell:
            return jsonify({'error': '心智圖殼不存在'}), 404

        rel = _get_tree_parent(s, atom_id)

        # cycle 防呆
        if new_parent_id is not None:
            descendants = _tree_descendants(s, atom_id)
            if int(new_parent_id) in descendants:
                return jsonify({'error': '不能將節點移到自己或自己的後代之下（會形成迴圈）'}), 400

        if new_parent_id is None and rel:
            # 變 root：刪原 relation
            rel.is_deleted = True
        elif new_parent_id is not None and not rel:
            # 原本是 root，現在掛到某 parent 下
            rel = UnifiedRelation(
                from_atom_id=atom_id,
                to_atom_id=int(new_parent_id),
                relation_type='tree_parent',
                sort_order=new_order if new_order is not None else _next_sibling_sort_order(s, int(new_parent_id)),
                created_by='human',
            )
            s.add(rel)
        elif new_parent_id is not None and rel:
            rel.to_atom_id = int(new_parent_id)
            if new_order is not None:
                rel.sort_order = int(new_order)

        s.flush()
        return jsonify({'message': '節點已移動', 'tree_parent_relation': rel.to_dict() if rel else None})


@bp.route('/api/canvas-mindmap-shells/<int:shell_id>/nodes/<int:atom_id>', methods=['DELETE'])
def delete_mindmap_node(shell_id, atom_id):
    """刪除節點及其整個子樹（送入字紙簍，tree_parent relations 標 is_deleted）

    payload 中保存 mindmap_shell_id 與 tree_parent 資訊以便 restore 時還原為心智圖節點。
    若刪的是 root（殼也會被刪），把殼快照也存進 root atom 的 trash payload。
    """
    with session_scope() as s:
        shell = s.get(CanvasMindmapShell, shell_id)
        if not shell:
            return jsonify({'error': '心智圖殼不存在'}), 404

        subtree_ids = _tree_descendants(s, atom_id)
        canvas_id = shell.canvas_id
        is_deleting_shell = (shell.root_atom_id == atom_id)
        shell_snapshot = _shell_to_snapshot(shell) if is_deleting_shell else None

        # 取每個 atom 的 tree_parent（必須在 mark deleted 之前查）
        tree_parents_map = _collect_tree_parents(s, list(subtree_ids))

        members = (
            s.query(CanvasAtom)
            .filter(
                CanvasAtom.canvas_id == canvas_id,
                CanvasAtom.atom_id.in_(subtree_ids),
            )
            .all()
        )
        for ca in members:
            payload = {
                'mindmap_shell_id': shell_id,
                'tree_parent': tree_parents_map.get(ca.atom_id),
            }
            if is_deleting_shell and ca.atom_id == atom_id:
                payload['shell_snapshot'] = shell_snapshot
            trash = CanvasTrash(
                canvas_id=canvas_id,
                kind='atom',
                atom_id=ca.atom_id,
                original_pos_x=ca.pos_x,
                original_pos_y=ca.pos_y,
                original_width=ca.width,
                original_height=ca.height,
                z_index=ca.z_index,
                visual_style=ca.visual_style,
                payload=payload,
            )
            s.add(trash)
            s.delete(ca)

        (
            s.query(UnifiedRelation)
            .filter(
                UnifiedRelation.relation_type == 'tree_parent',
                UnifiedRelation.from_atom_id.in_(subtree_ids),
            )
            .update({'is_deleted': True}, synchronize_session=False)
        )

        if is_deleting_shell:
            s.delete(shell)
            return jsonify({
                'message': f'已刪除整個心智圖（root + 子樹），共 {len(subtree_ids)} 個節點',
                'removed_atom_ids': list(subtree_ids),
                'shell_deleted': True,
            })

        return jsonify({
            'message': f'已刪除節點及子樹，共 {len(subtree_ids)} 個節點',
            'removed_atom_ids': list(subtree_ids),
            'shell_deleted': False,
        })


@bp.route('/api/canvas-mindmap-shells/<int:shell_id>/attach', methods=['POST'])
def attach_atom_to_mindmap(shell_id):
    """把既存 canvas atom 收入殼，建立 tree_parent relation。

    body: {
        atom_id: int,                # 要收入的 atom（必須已在此白板上）
        parent_atom_id: int|null,    # 父節點；null 則接到 shell.root_atom_id 之下
        include_subtree: bool        # true=連同子樹一起搬（跨殼搬移用）
    }
    防呆:cycle 偵測（不能附加到自己或自己的後代）。
    """
    data = request.get_json() or {}
    atom_id = data.get('atom_id')
    parent_atom_id = data.get('parent_atom_id')
    include_subtree = bool(data.get('include_subtree', False))
    if not atom_id:
        return jsonify({'error': '需要 atom_id'}), 400
    atom_id = int(atom_id)

    with session_scope() as s:
        shell = s.get(CanvasMindmapShell, shell_id)
        if not shell:
            return jsonify({'error': '心智圖殼不存在'}), 404

        if parent_atom_id is None:
            if shell.root_atom_id is None:
                return jsonify({'error': '殼沒有 root，無法 attach'}), 400
            parent_atom_id = shell.root_atom_id
        else:
            parent_atom_id = int(parent_atom_id)

        if parent_atom_id == atom_id:
            return jsonify({'error': '不能附加到自己之下'}), 400

        descendants = _tree_descendants(s, atom_id)
        if parent_atom_id in descendants:
            return jsonify({'error': '不能附加到自己的後代之下（會形成迴圈）'}), 400

        ca = s.query(CanvasAtom).filter(
            CanvasAtom.canvas_id == shell.canvas_id,
            CanvasAtom.atom_id == atom_id,
        ).first()
        if not ca:
            return jsonify({'error': 'atom 不在此白板上'}), 400

        old_shell_id = ca.mindmap_shell_id
        ca.mindmap_shell_id = shell_id

        # 跨殼搬移時把子樹的 mindmap_shell_id 一併改過來
        moved_subtree_count = 0
        old_shell_deleted = False
        if include_subtree and old_shell_id and old_shell_id != shell_id:
            sub_atoms = (
                s.query(CanvasAtom)
                .filter(
                    CanvasAtom.canvas_id == shell.canvas_id,
                    CanvasAtom.atom_id.in_(descendants),
                    CanvasAtom.atom_id != atom_id,
                    CanvasAtom.mindmap_shell_id == old_shell_id,
                )
                .all()
            )
            for sca in sub_atoms:
                sca.mindmap_shell_id = shell_id
            moved_subtree_count = len(sub_atoms)

            old_shell = s.get(CanvasMindmapShell, old_shell_id)
            if old_shell and old_shell.root_atom_id == atom_id:
                old_shell.root_atom_id = None

            # 舊殼若變空 -- 自動刪除收尾
            s.flush()
            remaining = (
                s.query(CanvasAtom)
                .filter(
                    CanvasAtom.canvas_id == shell.canvas_id,
                    CanvasAtom.mindmap_shell_id == old_shell_id,
                )
                .count()
            )
            if remaining == 0 and old_shell:
                s.delete(old_shell)
                old_shell_deleted = True

        existing_rel = _get_tree_parent(s, atom_id)
        if existing_rel:
            existing_rel.to_atom_id = parent_atom_id
            existing_rel.sort_order = _next_sibling_sort_order(s, parent_atom_id)
            existing_rel.is_deleted = False
            rel = existing_rel
        else:
            rel = UnifiedRelation(
                from_atom_id=atom_id,
                to_atom_id=parent_atom_id,
                relation_type='tree_parent',
                sort_order=_next_sibling_sort_order(s, parent_atom_id),
                created_by='human',
            )
            s.add(rel)
        s.flush()

        return jsonify({
            'message': '已附加到心智圖',
            'canvas_atom': ca.to_dict(),
            'tree_parent_relation': rel.to_dict(),
            'moved_subtree_count': moved_subtree_count,
            'old_shell_id': old_shell_id,
            'old_shell_deleted': old_shell_deleted,
        })


@bp.route('/api/canvas-mindmap-shells/<int:shell_id>/extract', methods=['POST'])
def extract_mindmap_subtree(shell_id):
    """把節點及其子樹從殼脫離。

    body: {
        atom_id: int,
        as_new_shell: bool (預設 false),
        new_shell_pos_x, new_shell_pos_y: float (僅 as_new_shell=true 用)
    }
    模式:
      as_new_shell=false -- 子樹的 mindmap_shell_id 全清,變獨立卡片群,
                            tree_parent 保留;脫離 root 則砍 top_rel(變樹根)
      as_new_shell=true  -- 建新殼接管子樹,拖出節點變新殼的 root
    若脫離的是殼的 root,殼變空,由前端決定是否刪除。
    """
    data = request.get_json() or {}
    atom_id = data.get('atom_id')
    if not atom_id:
        return jsonify({'error': '需要 atom_id'}), 400
    atom_id = int(atom_id)
    as_new_shell = bool(data.get('as_new_shell', False))

    with session_scope() as s:
        shell = s.get(CanvasMindmapShell, shell_id)
        if not shell:
            return jsonify({'error': '心智圖殼不存在'}), 404

        subtree_ids = _tree_descendants(s, atom_id)

        members = (
            s.query(CanvasAtom)
            .filter(
                CanvasAtom.canvas_id == shell.canvas_id,
                CanvasAtom.atom_id.in_(subtree_ids),
                CanvasAtom.mindmap_shell_id == shell_id,
            )
            .all()
        )

        new_shell_dict = None
        if as_new_shell:
            atom = s.get(KnowledgeAtom, atom_id)
            new_title = (atom.title or '心智圖') if atom else '心智圖'
            new_shell = CanvasMindmapShell(
                canvas_id=shell.canvas_id,
                title=new_title,
                pos_x=float(data.get('new_shell_pos_x', shell.pos_x + 40)),
                pos_y=float(data.get('new_shell_pos_y', shell.pos_y + 40)),
                width=400,
                height=240,
                color=shell.color,
                layout=shell.layout,
                z_index=shell.z_index,
            )
            s.add(new_shell)
            s.flush()
            new_shell.root_atom_id = atom_id
            for ca in members:
                ca.mindmap_shell_id = new_shell.id
            new_shell_dict = new_shell.to_dict()
        else:
            for ca in members:
                ca.mindmap_shell_id = None

        # 拖出的若不是原殼 root，砍掉它的 tree_parent relation（變成新樹/獨立的根）
        if atom_id != shell.root_atom_id:
            top_rel = _get_tree_parent(s, atom_id)
            if top_rel:
                top_rel.is_deleted = True
        else:
            # 拖出的是原殼 root -- root_atom_id 失效
            shell.root_atom_id = None

        s.flush()

        # 原殼若變空 -- 自動刪除收尾
        old_shell_deleted = False
        remaining = (
            s.query(CanvasAtom)
            .filter(
                CanvasAtom.canvas_id == shell.canvas_id,
                CanvasAtom.mindmap_shell_id == shell_id,
            )
            .count()
        )
        if remaining == 0:
            s.delete(shell)
            old_shell_deleted = True

        return jsonify({
            'message': f'已脫離 {len(members)} 個節點',
            'extracted_atom_ids': [ca.atom_id for ca in members],
            'new_shell': new_shell_dict,
            'old_shell_deleted': old_shell_deleted,
        })


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

    心智圖節點:若 trash payload 含 mindmap_shell_id / tree_parent / shell_snapshot，
    一併還原 mindmap 歸屬與樹結構。shell 已被刪除時用 shell_snapshot 重建。
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

        # Pass 1：重建被刪除的殼（shell_snapshot 在 root atom 的 payload 中）
        # old_shell_id -> 實際可用的 shell_id（既存的或新建的）
        shell_id_map = {}
        for t in trash_rows:
            if not (t.payload and isinstance(t.payload, dict)):
                continue
            old_shell_id = t.payload.get('mindmap_shell_id')
            if not old_shell_id or old_shell_id in shell_id_map:
                continue
            existing_shell = s.get(CanvasMindmapShell, old_shell_id)
            if existing_shell:
                shell_id_map[old_shell_id] = old_shell_id
            else:
                snap = t.payload.get('shell_snapshot')
                if snap:
                    new_shell = CanvasMindmapShell(
                        canvas_id=canvas.id,
                        title=snap.get('title', '心智圖'),
                        pos_x=snap.get('pos_x', 0),
                        pos_y=snap.get('pos_y', 0),
                        width=snap.get('width', 600),
                        height=snap.get('height', 400),
                        z_index=snap.get('z_index', 1),
                        color=snap.get('color', '#3b82f6'),
                        layout=snap.get('layout', 'tree-right'),
                        root_atom_id=t.atom_id,
                    )
                    s.add(new_shell)
                    s.flush()
                    shell_id_map[old_shell_id] = new_shell.id

        # Pass 2：恢復 canvas_atom + 還原 mindmap 歸屬與 tree_parent
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

            # 還原 mindmap 歸屬與樹結構
            if t.payload and isinstance(t.payload, dict):
                old_shell_id = t.payload.get('mindmap_shell_id')
                target_shell_id = shell_id_map.get(old_shell_id)
                if target_shell_id:
                    ca.mindmap_shell_id = target_shell_id
                    tree_parent = t.payload.get('tree_parent')
                    if tree_parent and tree_parent.get('to_atom_id'):
                        # 若已有「活躍」tree_parent（用戶在 trash 期間建立的）-- 不覆蓋
                        active_rel = (
                            s.query(UnifiedRelation)
                            .filter(
                                UnifiedRelation.relation_type == 'tree_parent',
                                UnifiedRelation.is_deleted == False,
                                UnifiedRelation.from_atom_id == t.atom_id,
                            )
                            .first()
                        )
                        if not active_rel:
                            # 嘗試 undelete 舊 relation，否則新建
                            old_rel = (
                                s.query(UnifiedRelation)
                                .filter(
                                    UnifiedRelation.relation_type == 'tree_parent',
                                    UnifiedRelation.from_atom_id == t.atom_id,
                                )
                                .first()
                            )
                            if old_rel:
                                old_rel.is_deleted = False
                                old_rel.to_atom_id = tree_parent['to_atom_id']
                                old_rel.sort_order = tree_parent.get('sort_order', 0)
                            else:
                                s.add(UnifiedRelation(
                                    from_atom_id=t.atom_id,
                                    to_atom_id=tree_parent['to_atom_id'],
                                    relation_type='tree_parent',
                                    sort_order=tree_parent.get('sort_order', 0),
                                    created_by='human',
                                ))

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
    VALID_KINDS = ('atom', 'textbox', 'standalone_entry')
    if from_kind not in VALID_KINDS or to_kind not in VALID_KINDS:
        return jsonify({'error': f"from_kind/to_kind 必須是 {VALID_KINDS} 之一"}), 400

    # 端點 ID 一致性檢查
    src_atom_id = data.get('source_atom_id')
    tgt_atom_id = data.get('target_atom_id')
    src_tb_id = data.get('source_textbox_id')
    tgt_tb_id = data.get('target_textbox_id')
    src_se_id = data.get('source_standalone_entry_id')
    tgt_se_id = data.get('target_standalone_entry_id')

    if from_kind == 'atom' and not src_atom_id:
        return jsonify({'error': 'from_kind=atom 需要 source_atom_id'}), 400
    if from_kind == 'textbox' and not src_tb_id:
        return jsonify({'error': 'from_kind=textbox 需要 source_textbox_id'}), 400
    if from_kind == 'standalone_entry' and not src_se_id:
        return jsonify({'error': 'from_kind=standalone_entry 需要 source_standalone_entry_id'}), 400
    if to_kind == 'atom' and not tgt_atom_id:
        return jsonify({'error': 'to_kind=atom 需要 target_atom_id'}), 400
    if to_kind == 'textbox' and not tgt_tb_id:
        return jsonify({'error': 'to_kind=textbox 需要 target_textbox_id'}), 400
    if to_kind == 'standalone_entry' and not tgt_se_id:
        return jsonify({'error': 'to_kind=standalone_entry 需要 target_standalone_entry_id'}), 400

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
            source_standalone_entry_id=src_se_id if from_kind == 'standalone_entry' else None,
            target_standalone_entry_id=tgt_se_id if to_kind == 'standalone_entry' else None,
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

        # 先處理 relation_type（會帶入 registry 預設樣式）,再讓 color/line_style 可覆寫
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
                    style = _get_relation_style(s, new_type)
                    conn.color = style['color']
                    conn.line_style = style['line_style']

        if 'color' in data:
            conn.color = data['color']
        if 'line_style' in data:
            conn.line_style = data['line_style']

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
