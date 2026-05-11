# -*- coding: utf-8 -*-
"""Gantt MVP: 免登入的甘特圖展示 + 拖拉回寫 API

固定讀取 BeakBroodNest 專案 (slug=vRhORoxV) 的 task entries。
提供兩個 API：
  GET  /beakbroodnest/gantt-mvp/api/tasks  -> Frappe Gantt + Mermaid 資料
  PUT  /beakbroodnest/gantt-mvp/api/tasks/<entry_id> -> 拖拉後回寫日期
"""

from flask import Blueprint, jsonify, request, render_template
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import (
    KnowledgeAtom, Canvas, CanvasAtom, UnifiedRelation,
    AtomEntry, EntrySchema, EntrySchemaField, EntryFieldValue,
)

bp = Blueprint('gantt_mvp', __name__)

CANVAS_SLUG = 'vRhORoxV'


def _fetch_tasks(s):
    """從 DB 讀取 BeakBroodNest 專案的 task 資料，回傳結構化 list。"""
    canvas = s.query(Canvas).filter(Canvas.slug == CANVAS_SLUG).first()
    if not canvas:
        return None, 'canvas not found'

    atom_ids = [
        row[0] for row in
        s.query(CanvasAtom.atom_id)
        .filter(CanvasAtom.canvas_id == canvas.id)
        .all()
    ]
    if not atom_ids:
        return [], None

    task_schema = s.query(EntrySchema).filter_by(code='task').first()
    if not task_schema:
        return None, 'task schema not found'

    entries = (
        s.query(AtomEntry)
        .options(joinedload(AtomEntry.atom))
        .filter(
            AtomEntry.atom_id.in_(atom_ids),
            AtomEntry.schema_id == task_schema.id,
        )
        .all()
    )

    # 批次取欄位值
    entry_ids = [e.id for e in entries]
    fv_rows = (
        s.query(EntryFieldValue)
        .options(joinedload(EntryFieldValue.field))
        .filter(EntryFieldValue.entry_id.in_(entry_ids))
        .all()
    ) if entry_ids else []

    fv_map = {}
    for fv in fv_rows:
        if fv.field:
            fv_map.setdefault(fv.entry_id, {})[fv.field.name] = fv.value

    # blocks 關係
    all_blocks = (
        s.query(UnifiedRelation)
        .filter(
            UnifiedRelation.from_atom_id.in_(atom_ids),
            UnifiedRelation.to_atom_id.in_(atom_ids),
            UnifiedRelation.relation_type == 'blocks',
            UnifiedRelation.is_deleted == False,
        )
        .all()
    )

    # atom_id -> entry 快查（用於 dependency 解析）
    atom_to_entry = {e.atom_id: e for e in entries}
    atom_title_map = {}
    for e in entries:
        if e.atom:
            atom_title_map[e.atom_id] = e.atom.title

    tasks = []
    for entry in entries:
        fv = fv_map.get(entry.id, {})
        title = entry.atom.title if entry.atom else f'#{entry.atom_id}'

        # Frappe Gantt 需要 start/end 都是 YYYY-MM-DD 格式
        planned_start = fv.get('planned_start', '')
        actual_end = fv.get('actual_end', '')

        tasks.append({
            'entry_id': entry.id,
            'atom_id': entry.atom_id,
            'title': title,
            'status': fv.get('status', 'planning'),
            'urgency': fv.get('urgency', 'M'),
            'category': fv.get('category', ''),
            'planned_start': planned_start,
            'actual_end': actual_end,
            'actual_start': fv.get('actual_start', ''),
            'planned_duration': fv.get('planned_duration', ''),
        })

    deps = []
    for rel in all_blocks:
        from_entry = atom_to_entry.get(rel.from_atom_id)
        to_entry = atom_to_entry.get(rel.to_atom_id)
        if from_entry and to_entry:
            deps.append({
                'from_entry_id': from_entry.id,
                'to_entry_id': to_entry.id,
                'from_title': atom_title_map.get(rel.from_atom_id, ''),
                'to_title': atom_title_map.get(rel.to_atom_id, ''),
            })

    return {'tasks': tasks, 'deps': deps, 'canvas_name': canvas.name}, None


# ============================================================
# Page
# ============================================================

@bp.route('/gantt-mvp')
def gantt_mvp_page():
    return render_template('gantt_mvp.html')


# ============================================================
# API
# ============================================================

@bp.route('/gantt-mvp/api/tasks')
def gantt_mvp_tasks():
    with session_scope() as s:
        data, err = _fetch_tasks(s)
        if err:
            return jsonify({'error': err}), 404
        return jsonify(data)


@bp.route('/gantt-mvp/api/tasks/<int:entry_id>', methods=['PUT'])
def gantt_mvp_update_task(entry_id):
    """拖拉回寫：更新 planned_start / actual_end"""
    body = request.get_json()
    if not body:
        return jsonify({'error': 'need JSON body'}), 400

    allowed_fields = {'planned_start', 'actual_end', 'actual_start', 'status'}
    updates = {k: v for k, v in body.items() if k in allowed_fields}
    if not updates:
        return jsonify({'error': 'no valid fields'}), 400

    with session_scope() as s:
        entry = (
            s.query(AtomEntry)
            .options(joinedload(AtomEntry.schema))
            .get(entry_id)
        )
        if not entry:
            return jsonify({'error': 'entry not found'}), 404

        schema_fields = (
            s.query(EntrySchemaField)
            .filter_by(schema_id=entry.schema_id)
            .all()
        )
        field_map = {f.name: f for f in schema_fields}

        for fname, fval in updates.items():
            if fname not in field_map:
                continue
            sf = field_map[fname]
            existing = (
                s.query(EntryFieldValue)
                .filter_by(entry_id=entry.id, field_id=sf.id)
                .first()
            )
            if existing:
                existing.value = str(fval) if fval else None
            else:
                fv = EntryFieldValue(
                    entry_id=entry.id,
                    field_id=sf.id,
                    value=str(fval) if fval else None,
                )
                s.add(fv)

        s.flush()
        return jsonify({'ok': True, 'entry_id': entry_id, 'updated': updates})
