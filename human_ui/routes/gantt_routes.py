# -*- coding: utf-8 -*-
"""Gantt API: 甘特圖資料讀取與更新

提供兩個端點：
  GET   /gantt-mvp/api/gantt/<slug>             讀取白板的 gantt 資料
  PATCH /gantt-mvp/api/gantt/<slug>/<entry_id>  更新單一任務欄位

所有端點免登入（gantt-mvp 開發用）。
"""

from flask import Blueprint, jsonify, request, abort, render_template
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import (
    KnowledgeAtom, Canvas, CanvasAtom, UnifiedRelation,
    AtomEntry, EntrySchema, EntrySchemaField, EntryFieldValue,
)
from human_ui.validators.gantt_validator import validate_gantt_data

bp = Blueprint('gantt_routes', __name__)


# ============================================================
# Page
# ============================================================

@bp.route('/gantt-mvp/gantt/<slug>')
def gantt_page(slug):
    """甘特圖頁面（模組化版，免登入）。"""
    return render_template('gantt.html', canvas_slug=slug)


# ============================================================
# GET -- 讀取甘特圖資料
# ============================================================

@bp.route('/gantt-mvp/api/gantt/<slug>')
def get_gantt(slug):
    """讀取白板的 task entries，轉為 Frappe Gantt 格式。"""
    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.slug == slug).first()
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        tasks_raw = _fetch_tasks(s, canvas.id)
        deps_raw = _fetch_deps(s, canvas.id)
        result = _transform_to_frappe(tasks_raw, deps_raw)

        # 驗證並附�� warnings
        errors, warnings = validate_gantt_data(tasks_raw, deps_raw)
        result['warnings'] = warnings
        result['errors'] = errors
        result['canvas_name'] = canvas.name

        return jsonify(result)


def _fetch_tasks(s, canvas_id):
    """從 atom_entries + entry_field_values 讀出白板上所有 task 任務。"""
    atom_ids = [
        row[0] for row in
        s.query(CanvasAtom.atom_id)
        .filter(CanvasAtom.canvas_id == canvas_id)
        .all()
    ]
    if not atom_ids:
        return []

    task_schema = s.query(EntrySchema).filter_by(code='task').first()
    if not task_schema:
        return []

    entries = (
        s.query(AtomEntry)
        .options(joinedload(AtomEntry.atom))
        .filter(
            AtomEntry.atom_id.in_(atom_ids),
            AtomEntry.schema_id == task_schema.id,
        )
        .all()
    )

    entry_ids = [e.id for e in entries]
    fv_map = _batch_field_values(s, entry_ids)

    tasks = []
    for entry in entries:
        fv = fv_map.get(entry.id, {})
        tasks.append({
            'entry_id': entry.id,
            'atom_id': entry.atom_id,
            'title': entry.atom.title if entry.atom else f'#{entry.atom_id}',
            'status': fv.get('status', 'pending'),
            'urgency': fv.get('urgency', 'M'),
            'category': fv.get('category', ''),
            'planned_start': fv.get('planned_start', ''),
            'planned_end': fv.get('planned_end', ''),
            'actual_end': fv.get('actual_end', ''),
            'actual_start': fv.get('actual_start', ''),
            'baseline_start': fv.get('baseline_start', ''),
            'baseline_end': fv.get('baseline_end', ''),
            'progress': fv.get('progress', ''),
        })

    return tasks


def _fetch_deps(s, canvas_id):
    """從 atom_relations 讀取白板內的 blocks 依賴。"""
    atom_ids = [
        row[0] for row in
        s.query(CanvasAtom.atom_id)
        .filter(CanvasAtom.canvas_id == canvas_id)
        .all()
    ]
    if not atom_ids:
        return []

    # 建 atom_id -> entry_id 對照表
    task_schema = s.query(EntrySchema).filter_by(code='task').first()
    if not task_schema:
        return []

    entries = (
        s.query(AtomEntry)
        .filter(
            AtomEntry.atom_id.in_(atom_ids),
            AtomEntry.schema_id == task_schema.id,
        )
        .all()
    )
    atom_to_entry = {e.atom_id: e.id for e in entries}

    rels = (
        s.query(UnifiedRelation)
        .filter(
            UnifiedRelation.from_atom_id.in_(atom_ids),
            UnifiedRelation.to_atom_id.in_(atom_ids),
            UnifiedRelation.relation_type == 'blocks',
            UnifiedRelation.is_deleted == False,
        )
        .all()
    )

    deps = []
    for rel in rels:
        from_eid = atom_to_entry.get(rel.from_atom_id)
        to_eid = atom_to_entry.get(rel.to_atom_id)
        if from_eid and to_eid:
            deps.append({
                'from_entry_id': from_eid,
                'to_entry_id': to_eid,
            })

    return deps


def _batch_field_values(s, entry_ids):
    """批次取得 entry_field_values，回傳 {entry_id: {field_name: value}}。"""
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


def _transform_to_frappe(tasks_raw, deps_raw):
    """將 EAV 結構轉為前端吃的格式。

    start / end 直接回傳 actual 原值（允許 null），不做 fallback。
    視覺回退（actual null 時用 baseline 代入）由前端 gantt-core.js 處理。
    _baseline 和 _delta_days 用底線前綴（Frappe 不認，留給後處理用）。
    """
    dep_map = _build_dep_map(deps_raw)

    frappe_tasks = []
    for t in tasks_raw:
        task_id = str(t['entry_id'])

        actual_start = _date_only(t.get('actual_start')) or None
        actual_end = _date_only(t.get('actual_end')) or None
        progress = _resolve_progress(t)
        planned = _resolve_planned(t)
        baseline = _resolve_baseline(t)
        delta = _calc_delta_days(baseline, actual_end)
        status = _resolve_gantt_status(t, actual_start, progress)

        frappe_tasks.append({
            'id': task_id,
            'name': t['title'],
            'start': actual_start,
            'end': actual_end,
            'progress': progress,
            'dependencies': ', '.join(dep_map.get(task_id, [])),
            'custom_class': _resolve_bar_class(t),
            '_entry_id': t['entry_id'],
            '_planned': planned,
            '_baseline': baseline,
            '_delta_days': delta,
            '_status': status,
            '_urgency': t['urgency'],
            '_category': t['category'],
        })

    return {'tasks': frappe_tasks}


def _build_dep_map(deps_raw):
    """建 dependency 反查表：被依賴的 entry -> 依賴它的 entries。"""
    dep_map = {}
    for d in deps_raw:
        to_id = str(d['to_entry_id'])
        from_id = str(d['from_entry_id'])
        dep_map.setdefault(to_id, []).append(from_id)
    return dep_map


def _resolve_gantt_status(task, actual_start, progress):
    """根據 actual 與 progress 判斷甘特圖狀態。

    回傳 not_started / in_progress / completed。
    前端直接用，避免重複計算。
    """
    db_status = task.get('status', 'pending')
    if db_status == 'done' or progress == 100:
        return 'completed'
    if actual_start or db_status == 'in_progress' or (progress and progress > 0):
        return 'in_progress'
    return 'not_started'


def _resolve_progress(task):
    """解析進度百分比。"""
    p = task.get('progress', '')
    if p and p != '':
        try:
            return max(0, min(100, int(float(p))))
        except (ValueError, TypeError):
            pass
    status = task.get('status', 'pending')
    if status == 'done':
        return 100
    if status == 'in_progress':
        return 50
    return 0


def _resolve_planned(task):
    """取出預計日期，回傳 dict 或 None。"""
    ps = _date_only(task.get('planned_start'))
    pe = _date_only(task.get('planned_end'))
    if not ps and not pe:
        return None
    return {'start': ps or '', 'end': pe or ''}


def _resolve_baseline(task):
    """取出 baseline 日期，回傳 dict 或 None。"""
    bs = _date_only(task.get('baseline_start'))
    be = _date_only(task.get('baseline_end'))
    if not bs and not be:
        return None
    return {'start': bs or '', 'end': be or ''}


def _calc_delta_days(baseline, actual_end):
    """計算 actual end 與 baseline end 的天數差。"""
    if not baseline or not baseline.get('end') or not actual_end:
        return None
    from datetime import datetime
    try:
        be = datetime.strptime(baseline['end'], '%Y-%m-%d')
        ae = datetime.strptime(actual_end, '%Y-%m-%d')
        return (ae - be).days
    except (ValueError, TypeError):
        return None


def _resolve_bar_class(task):
    """依 urgency/status 決定 Frappe Gantt CSS class。"""
    if task.get('status') == 'done':
        return 'bar-done'
    return 'bar-urgency-' + (task.get('urgency', 'M'))


def _date_only(val):
    """從 datetime 字串取出日期部分 YYYY-MM-DD。"""
    if not val:
        return ''
    return val[:10] if len(val) >= 10 else ''


# ============================================================
# PATCH -- 更新單一任務
# ============================================================

@bp.route('/gantt-mvp/api/gantt/<slug>/<int:entry_id>', methods=['PATCH'])
def patch_gantt_task(slug, entry_id):
    """更新單一任務的欄位值。

    body: {"field_name": "value", ...}
    支援 reset_baseline=true query param 以允許修改凍結欄位。
    """
    body = request.get_json()
    if not body:
        return jsonify({'error': '需要 JSON body'}), 400

    reset_baseline = request.args.get('reset_baseline', '').lower() == 'true'
    allowed = {
        'planned_start', 'actual_start', 'actual_end',
        'baseline_start', 'baseline_end',
        'progress', 'status',
    }
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return jsonify({'error': '無有效欄位'}), 400

    with session_scope() as s:
        entry = s.get(AtomEntry, entry_id)
        if not entry:
            return jsonify({'error': 'entry 不存在'}), 404

        field_defs = (
            s.query(EntrySchemaField)
            .filter_by(schema_id=entry.schema_id)
            .all()
        )
        field_map = {f.name: f for f in field_defs}

        updated = {}
        frozen_rejected = []

        for fname, fval in updates.items():
            sf = field_map.get(fname)
            if not sf:
                continue

            if sf.is_frozen and not reset_baseline:
                frozen_rejected.append(fname)
                continue

            _write_field(s, entry.id, sf.id, fval)
            updated[fname] = fval

        s.flush()

        result = {'ok': True, 'entry_id': entry_id, 'updated': updated}
        if frozen_rejected:
            result['frozen_rejected'] = frozen_rejected
            result['hint'] = '凍結欄位需加 ?reset_baseline=true'
        return jsonify(result)


def _write_field(s, entry_id, field_id, value, changed_by='gantt:mvp'):
    """寫入或更新單一欄位值。"""
    from core.audit import log_field_change
    new_val = str(value) if value is not None else None
    existing = (
        s.query(EntryFieldValue)
        .filter_by(entry_id=entry_id, field_id=field_id)
        .first()
    )
    if existing:
        log_field_change(s, entry_id, field_id, existing.value, new_val, changed_by)
        existing.value = new_val
    else:
        log_field_change(s, entry_id, field_id, None, new_val, changed_by)
        fv = EntryFieldValue(
            entry_id=entry_id,
            field_id=field_id,
            value=new_val,
        )
        s.add(fv)


# ============================================================
# DELETE -- 移除依賴關係
# ============================================================

@bp.route('/gantt-mvp/api/gantt/<slug>/dep', methods=['DELETE'])
def delete_dependency(slug):
    """移除兩個 entry 之間的 blocks 依賴。

    body: { from_entry_id, to_entry_id }
    透過 entry_id 反查 atom_id，再刪除 atom_relations。
    """
    body = request.get_json()
    if not body:
        return jsonify({'error': '需要 JSON body'}), 400

    from_eid = body.get('from_entry_id')
    to_eid = body.get('to_entry_id')
    if not from_eid or not to_eid:
        return jsonify({'error': '需要 from_entry_id 和 to_entry_id'}), 400

    with session_scope() as s:
        from_entry = s.get(AtomEntry, from_eid)
        to_entry = s.get(AtomEntry, to_eid)
        if not from_entry or not to_entry:
            return jsonify({'error': 'entry 不存在'}), 404

        rel = (
            s.query(UnifiedRelation)
            .filter_by(
                from_atom_id=from_entry.atom_id,
                to_atom_id=to_entry.atom_id,
                relation_type='blocks',
            )
            .filter(UnifiedRelation.is_deleted == False)
            .first()
        )
        if not rel:
            return jsonify({'error': '依賴關係不存在'}), 404

        rel.is_deleted = True
        s.flush()

        return jsonify({
            'ok': True,
            'deleted': {
                'from_atom_id': from_entry.atom_id,
                'to_atom_id': to_entry.atom_id,
            },
        })
