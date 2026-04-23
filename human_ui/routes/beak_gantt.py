# -*- coding: utf-8 -*-
"""BeakGantt API: WBS + Gantt 資料讀取與寫入

端點:
  GET   /api/project/<slug>/beak-gantt              讀取白板 WBS+Gantt 資料
  POST  /api/project/<slug>/beak-gantt              新增任務
  PATCH /api/project/<slug>/beak-gantt/<atom_id>     更新任務欄位（拖拉儲存）
"""

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import (
    KnowledgeAtom, Canvas, CanvasAtom, AtomRelation,
    AtomEntry, EntrySchema, EntrySchemaField, EntryFieldValue,
)

bp = Blueprint('beak_gantt', __name__)


@bp.route('/api/project/<slug>/beak-gantt')
def get_beak_gantt(slug):
    """讀取白板的 WBS 階層 + todo entries，轉為 BeakGantt 格式。"""
    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.slug == slug).first()
        if not canvas:
            return jsonify({'error': 'canvas not found'}), 404

        atom_ids = [
            r[0] for r in
            s.query(CanvasAtom.atom_id).filter(CanvasAtom.canvas_id == canvas.id).all()
        ]
        if not atom_ids:
            return jsonify({'tasks': [], 'links': []})

        atoms = {
            a.id: a for a in
            s.query(KnowledgeAtom).filter(KnowledgeAtom.id.in_(atom_ids)).all()
        }

        todo_schema = s.query(EntrySchema).filter_by(code='todo').first()
        entries_by_atom = {}
        if todo_schema:
            entries = (
                s.query(AtomEntry)
                .filter(AtomEntry.atom_id.in_(atom_ids), AtomEntry.schema_id == todo_schema.id)
                .all()
            )
            fv_map = _batch_fv(s, [e.id for e in entries])
            for entry in entries:
                fv = fv_map.get(entry.id, {})
                entries_by_atom[entry.atom_id] = {
                    'entry_id': entry.id,
                    'status': fv.get('status', 'pending'),
                    'urgency': fv.get('urgency', 'M'),
                    'category': fv.get('category', ''),
                    'planned_start': fv.get('planned_start', ''),
                    'actual_start': fv.get('actual_start', ''),
                    'actual_end': fv.get('actual_end', ''),
                    'progress': fv.get('progress', ''),
                }

        relations = (
            s.query(AtomRelation)
            .filter(
                AtomRelation.from_atom_id.in_(atom_ids),
                AtomRelation.to_atom_id.in_(atom_ids),
                AtomRelation.relation_type.in_(['contains', 'follows', 'blocks']),
            )
            .all()
        )

        parent_map = {}
        parent_has_children = set()
        links = []
        link_id = 0
        for rel in relations:
            if rel.relation_type == 'contains':
                parent_map[rel.to_atom_id] = rel.from_atom_id
                parent_has_children.add(rel.from_atom_id)
            elif rel.relation_type == 'blocks':
                link_id += 1
                links.append({'id': link_id, 'source': rel.from_atom_id, 'target': rel.to_atom_id, 'type': '0'})
            elif rel.relation_type == 'follows':
                link_id += 1
                links.append({'id': link_id, 'source': rel.to_atom_id, 'target': rel.from_atom_id, 'type': '0'})

        tasks = []
        for atom_id in atom_ids:
            atom = atoms.get(atom_id)
            if not atom:
                continue
            ed = entries_by_atom.get(atom_id, {})
            start_raw = ed.get('actual_start') or ed.get('planned_start') or ''
            end_raw = ed.get('actual_end') or ''
            progress = _resolve_progress(ed)
            has_children = atom_id in parent_has_children

            task = {
                'id': atom_id,
                'text': atom.title,
                'parent': parent_map.get(atom_id, 0),
                'progress': progress,
                'open': True,
                '_entry_id': ed.get('entry_id'),
                '_status': ed.get('status', ''),
                '_urgency': ed.get('urgency', ''),
                '_category': ed.get('category', ''),
                '_actual_start': ed.get('actual_start', ''),
                '_actual_end': ed.get('actual_end', ''),
                '_planned_start': ed.get('planned_start', ''),
            }

            if start_raw and end_raw:
                task['start_date'] = _date_only(start_raw)
                task['end_date'] = _add_one_day(_date_only(end_raw))
            elif start_raw:
                task['start_date'] = _date_only(start_raw)
                task['duration'] = 3
            elif has_children:
                task['type'] = 'project'
            else:
                task['unscheduled'] = True
                task['duration'] = 1

            tasks.append(task)

        return jsonify({'tasks': tasks, 'links': links})


@bp.route('/api/project/<slug>/beak-gantt', methods=['POST'])
def create_beak_gantt_task(slug):
    """新增任務：atom + todo entry + canvas 放置 + contains 關係。"""
    body = request.get_json()
    if not body:
        return jsonify({'error': 'need JSON body'}), 400

    text = (body.get('text') or '').strip() or 'New Task'
    parent_id = body.get('parent', 0)
    start_date = body.get('start_date', '')
    duration = body.get('duration', 1)

    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.slug == slug).first()
        if not canvas:
            return jsonify({'error': 'canvas not found'}), 404

        todo_schema = s.query(EntrySchema).filter_by(code='todo').first()
        if not todo_schema:
            return jsonify({'error': 'todo schema not found'}), 500

        atom = KnowledgeAtom(
            title=text, content='', atom_type='A',
            source='human', owner='ethan', sensitivity='internal',
        )
        s.add(atom)
        s.flush()

        s.add(CanvasAtom(canvas_id=canvas.id, atom_id=atom.id, pos_x=0, pos_y=0))

        entry = AtomEntry(atom_id=atom.id, schema_id=todo_schema.id, raw_text='')
        s.add(entry)
        s.flush()

        field_map = {
            f.name: f for f in
            s.query(EntrySchemaField).filter_by(schema_id=todo_schema.id).all()
        }
        defaults = {'status': 'pending', 'urgency': 'M'}
        if start_date:
            defaults['actual_start'] = start_date + 'T00:00'
            if duration and int(duration) > 0:
                try:
                    dt = datetime.strptime(start_date, '%Y-%m-%d')
                    end_dt = dt + timedelta(days=max(1, int(duration)) - 1)
                    defaults['actual_end'] = end_dt.strftime('%Y-%m-%d') + 'T00:00'
                except (ValueError, TypeError):
                    pass
        for fname, fval in defaults.items():
            sf = field_map.get(fname)
            if sf:
                _upsert_field(s, entry.id, sf.id, fval)

        if parent_id and parent_id != 0:
            parent_atom = s.get(KnowledgeAtom, parent_id)
            if parent_atom:
                s.add(AtomRelation(from_atom_id=parent_id, to_atom_id=atom.id, relation_type='contains'))

        s.flush()
        return jsonify({'ok': True, 'tid': atom.id, 'entry_id': entry.id})


@bp.route('/api/project/<slug>/beak-gantt/<int:atom_id>', methods=['PATCH'])
def patch_beak_gantt_task(slug, atom_id):
    """更新任務欄位（拖拉儲存）。"""
    body = request.get_json()
    if not body:
        return jsonify({'error': 'need JSON body'}), 400

    with session_scope() as s:
        todo_schema = s.query(EntrySchema).filter_by(code='todo').first()
        if not todo_schema:
            return jsonify({'error': 'todo schema not found'}), 500

        entry = s.query(AtomEntry).filter_by(atom_id=atom_id, schema_id=todo_schema.id).first()
        if not entry:
            return jsonify({'error': 'no todo entry for this atom'}), 404

        field_map = {
            f.name: f for f in
            s.query(EntrySchemaField).filter_by(schema_id=entry.schema_id).all()
        }
        allowed = {'actual_start', 'actual_end', 'planned_start', 'progress', 'status'}
        updated = {}
        for fname, fval in body.items():
            if fname not in allowed:
                continue
            sf = field_map.get(fname)
            if not sf:
                continue
            _upsert_field(s, entry.id, sf.id, fval)
            updated[fname] = fval

        s.flush()
        return jsonify({'ok': True, 'entry_id': entry.id, 'updated': updated})


@bp.route('/api/project/<slug>/beak-gantt/<int:atom_id>', methods=['DELETE'])
def delete_beak_gantt_task(slug, atom_id):
    """刪除任務：atom + entries + canvas_atom + 相關 relations。"""
    with session_scope() as s:
        atom = s.get(KnowledgeAtom, atom_id)
        if not atom:
            return jsonify({'error': 'atom not found'}), 404

        # 收集要刪除的 atom_ids（含子孫）
        remove_ids = [atom_id]
        found = True
        while found:
            found = False
            child_rels = (
                s.query(AtomRelation)
                .filter(
                    AtomRelation.from_atom_id.in_(remove_ids),
                    AtomRelation.relation_type == 'contains',
                )
                .all()
            )
            for rel in child_rels:
                if rel.to_atom_id not in remove_ids:
                    remove_ids.append(rel.to_atom_id)
                    found = True

        # 刪除 relations（所有涉及這些 atom 的）
        s.query(AtomRelation).filter(
            (AtomRelation.from_atom_id.in_(remove_ids)) |
            (AtomRelation.to_atom_id.in_(remove_ids))
        ).delete(synchronize_session='fetch')

        # 刪除 entry field values + entries
        entries = s.query(AtomEntry).filter(AtomEntry.atom_id.in_(remove_ids)).all()
        entry_ids = [e.id for e in entries]
        if entry_ids:
            s.query(EntryFieldValue).filter(
                EntryFieldValue.entry_id.in_(entry_ids)
            ).delete(synchronize_session='fetch')
        s.query(AtomEntry).filter(AtomEntry.atom_id.in_(remove_ids)).delete(synchronize_session='fetch')

        # 刪除 canvas placement
        s.query(CanvasAtom).filter(CanvasAtom.atom_id.in_(remove_ids)).delete(synchronize_session='fetch')

        # 軟刪除 atom（設 is_deleted）
        for aid in remove_ids:
            a = s.get(KnowledgeAtom, aid)
            if a:
                a.is_deleted = True

        s.flush()
        return jsonify({'ok': True, 'deleted': remove_ids})


@bp.route('/api/project/<slug>/beak-gantt/link', methods=['POST'])
def create_beak_gantt_link(slug):
    """建立依賴關係（blocks）。body: {source: atom_id, target: atom_id}"""
    body = request.get_json()
    if not body:
        return jsonify({'error': 'need JSON body'}), 400

    source_id = body.get('source')
    target_id = body.get('target')
    if not source_id or not target_id:
        return jsonify({'error': 'need source and target'}), 400

    with session_scope() as s:
        # 檢查是否已存在
        existing = (
            s.query(AtomRelation)
            .filter_by(from_atom_id=source_id, to_atom_id=target_id, relation_type='blocks')
            .first()
        )
        if existing:
            return jsonify({'ok': True, 'message': 'already exists'})

        s.add(AtomRelation(from_atom_id=source_id, to_atom_id=target_id, relation_type='blocks'))
        s.flush()
        return jsonify({'ok': True})


@bp.route('/api/project/<slug>/beak-gantt/link', methods=['DELETE'])
def delete_beak_gantt_link(slug):
    """刪除依賴關係。body: {source: atom_id, target: atom_id}"""
    body = request.get_json()
    if not body:
        return jsonify({'error': 'need JSON body'}), 400

    source_id = body.get('source')
    target_id = body.get('target')
    if not source_id or not target_id:
        return jsonify({'error': 'need source and target'}), 400

    with session_scope() as s:
        rel = (
            s.query(AtomRelation)
            .filter_by(from_atom_id=source_id, to_atom_id=target_id, relation_type='blocks')
            .first()
        )
        if not rel:
            return jsonify({'error': 'relation not found'}), 404
        s.delete(rel)
        s.flush()
        return jsonify({'ok': True})


def _batch_fv(s, entry_ids):
    if not entry_ids:
        return {}
    rows = (
        s.query(EntryFieldValue)
        .options(joinedload(EntryFieldValue.field))
        .filter(EntryFieldValue.entry_id.in_(entry_ids))
        .all()
    )
    result = {}
    for fv in rows:
        if fv.field:
            result.setdefault(fv.entry_id, {})[fv.field.name] = fv.value
    return result


def _upsert_field(s, entry_id, field_id, value):
    existing = s.query(EntryFieldValue).filter_by(entry_id=entry_id, field_id=field_id).first()
    if existing:
        existing.value = str(value) if value is not None else None
    else:
        s.add(EntryFieldValue(entry_id=entry_id, field_id=field_id,
                              value=str(value) if value is not None else None))


def _resolve_progress(ed):
    p = ed.get('progress', '')
    if p:
        try:
            return max(0.0, min(1.0, int(float(p)) / 100))
        except (ValueError, TypeError):
            pass
    status = ed.get('status', 'pending')
    if status == 'done':
        return 1.0
    if status == 'in_progress':
        return 0.5
    return 0.0


def _date_only(val):
    if not val:
        return ''
    return val[:10] if len(val) >= 10 else val


def _add_one_day(date_str):
    if not date_str:
        return ''
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return (dt + timedelta(days=1)).strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return date_str
