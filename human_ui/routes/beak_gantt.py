# -*- coding: utf-8 -*-
"""BeakGantt API: WBS + Gantt 資料讀取與寫入

資料映射：
  Card (atom with structuredEntry) -> Summary Task (WBS 根)
  Item (structuredEntry in content_json) -> Task (WBS 子)
  Card without structuredEntry -> 葉子 Task
  Canvas connections -> 依賴箭頭 (links)

端點:
  GET   /api/project/<slug>/beak-gantt              讀取白板 WBS+Gantt 資料
  POST  /api/project/<slug>/beak-gantt              新增任務
  PATCH /api/project/<slug>/beak-gantt/<atom_id>     更新任務欄位（拖拉儲存）
  DELETE /api/project/<slug>/beak-gantt/<atom_id>    刪除任務
  POST  /api/project/<slug>/beak-gantt/link          建立依賴
  DELETE /api/project/<slug>/beak-gantt/link          刪除依賴
"""

import json
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request, session
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import (
    KnowledgeAtom, Canvas, CanvasAtom, CanvasConnection,
    UnifiedRelation, AtomEntry, EntrySchema, EntrySchemaField,
    EntryFieldValue, SystemConfig,
)

bp = Blueprint('beak_gantt', __name__)


# ============================================================
#  GET -- 讀取白板 WBS+Gantt 資料
# ============================================================

@bp.route('/api/project/<slug>/beak-gantt')
def get_beak_gantt(slug):
    """讀取白板的 Card+Item 階層，轉為 BeakGantt 格式。

    Card (atom) = Summary Task = WBS 根
    Item (structuredEntry in content_json) = Task = WBS 子
    """
    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.slug == slug).first()
        if not canvas:
            return jsonify({'error': 'canvas not found'}), 404

        # 取得畫布上的原子，按位置排序（左→右）
        canvas_atoms = (
            s.query(CanvasAtom)
            .filter(CanvasAtom.canvas_id == canvas.id)
            .all()
        )
        if not canvas_atoms:
            return jsonify({'tasks': [], 'links': []})

        canvas_atoms.sort(key=lambda ca: (ca.pos_x, ca.pos_y))

        atom_ids = [ca.atom_id for ca in canvas_atoms]
        atoms = {
            a.id: a for a in
            s.query(KnowledgeAtom)
            .filter(KnowledgeAtom.id.in_(atom_ids))
            .all()
        }

        # 查詢已持久化的 entry field values（如有 entryId）
        entry_fv_map = _build_entry_fv_map(s, atom_ids)

        # 建構 tasks
        today = datetime.now().strftime('%Y-%m-%d')
        tasks = []
        day_offset = 0

        for ca in canvas_atoms:
            atom = atoms.get(ca.atom_id)
            if not atom:
                continue

            entries = _extract_structured_entries(atom.content_json)

            if entries:
                # Summary Task（Card 含有 Items）
                tasks.append({
                    'id': atom.id,
                    'text': atom.title,
                    'parent': 0,
                    '_isSummary': True,
                    'open': True,
                    'progress': 0,
                    '_status': '',
                    '_urgency': '',
                })
                # Child Tasks（Items）
                for idx, entry in enumerate(entries):
                    entry_id = entry.get('entry_id')
                    fv = entry_fv_map.get(entry_id, {}) if entry_id else {}
                    # fallback: actual_start -> planned_start -> offset
                    start_raw = fv.get('actual_start', '') or fv.get('planned_start', '')
                    start = start_raw[:10] if start_raw else _add_n_days(today, day_offset)
                    # duration: 從日期區間計算，否則預設 1 天
                    end_raw = fv.get('actual_end', '') or fv.get('planned_end', '')
                    duration = _calc_duration(start_raw, end_raw)
                    tasks.append({
                        'id': 'e{}_{}'.format(atom.id, idx),
                        'text': entry['text'],
                        'parent': atom.id,
                        '_isSummary': False,
                        'start_date': start,
                        'duration': duration,
                        'progress': _resolve_progress(fv),
                        '_entry_id': entry_id,
                        '_status': fv.get('status', 'pending'),
                        '_urgency': fv.get('urgency', 'M'),
                    })
                    day_offset += 1
            else:
                # 葉子 Task（Card 無 Items）
                start = _add_n_days(today, day_offset)
                tasks.append({
                    'id': atom.id,
                    'text': atom.title,
                    'parent': 0,
                    '_isSummary': False,
                    'start_date': start,
                    'duration': 1,
                    'progress': 0,
                    'open': True,
                    '_status': 'pending',
                    '_urgency': 'M',
                })
                day_offset += 1

        # 建構 links（從 canvas connections）
        connections = (
            s.query(CanvasConnection)
            .filter(
                CanvasConnection.canvas_id == canvas.id,
                CanvasConnection.is_disconnected == False,
            )
            .all()
        )
        atom_id_set = set(atom_ids)
        links = []
        for idx, conn in enumerate(connections):
            if conn.source_atom_id in atom_id_set and conn.target_atom_id in atom_id_set:
                links.append({
                    'id': idx + 1,
                    'source': conn.source_atom_id,
                    'target': conn.target_atom_id,
                    'type': '0',
                })

        return jsonify({'tasks': tasks, 'links': links})


# ============================================================
#  POST / PATCH / DELETE -- 任務操作（維持既有功能）
# ============================================================

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

        task_schema = s.query(EntrySchema).filter_by(code='task').first()
        if not task_schema:
            return jsonify({'error': 'task schema not found'}), 500

        atom = KnowledgeAtom(
            title=text, content='', atom_type='A',
            source='human', owner='ethan', sensitivity='internal',
        )
        s.add(atom)
        s.flush()

        s.add(CanvasAtom(canvas_id=canvas.id, atom_id=atom.id, pos_x=0, pos_y=0))

        entry = AtomEntry(atom_id=atom.id, schema_id=task_schema.id, raw_text='')
        s.add(entry)
        s.flush()

        field_map = {
            f.name: f for f in
            s.query(EntrySchemaField).filter_by(schema_id=task_schema.id).all()
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
                s.add(UnifiedRelation(from_atom_id=parent_id, to_atom_id=atom.id, relation_type='contains'))

        s.flush()
        return jsonify({'ok': True, 'tid': atom.id, 'entry_id': entry.id})


@bp.route('/api/project/<slug>/beak-gantt/<int:atom_id>', methods=['PATCH'])
def patch_beak_gantt_task(slug, atom_id):
    """更新任務欄位（拖拉儲存）。"""
    body = request.get_json()
    if not body:
        return jsonify({'error': 'need JSON body'}), 400

    with session_scope() as s:
        task_schema = s.query(EntrySchema).filter_by(code='task').first()
        if not task_schema:
            return jsonify({'error': 'task schema not found'}), 500

        entry = s.query(AtomEntry).filter_by(atom_id=atom_id, schema_id=task_schema.id).first()
        if not entry:
            return jsonify({'error': 'no task entry for this atom'}), 404

        field_map = {
            f.name: f for f in
            s.query(EntrySchemaField).filter_by(schema_id=entry.schema_id).all()
        }
        allowed = {'actual_start', 'actual_end', 'planned_start', 'planned_end', 'progress', 'status'}
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

        remove_ids = [atom_id]
        found = True
        while found:
            found = False
            child_rels = (
                s.query(UnifiedRelation)
                .filter(
                    UnifiedRelation.from_atom_id.in_(remove_ids),
                    UnifiedRelation.relation_type == 'contains',
                    UnifiedRelation.is_deleted == False,
                )
                .all()
            )
            for rel in child_rels:
                if rel.to_atom_id not in remove_ids:
                    remove_ids.append(rel.to_atom_id)
                    found = True

        rels_to_delete = (
            s.query(UnifiedRelation)
            .filter(
                (UnifiedRelation.from_atom_id.in_(remove_ids)) |
                (UnifiedRelation.to_atom_id.in_(remove_ids)),
                UnifiedRelation.is_deleted == False,
            )
            .all()
        )
        for rel in rels_to_delete:
            rel.is_deleted = True

        entries = s.query(AtomEntry).filter(AtomEntry.atom_id.in_(remove_ids)).all()
        entry_ids = [e.id for e in entries]
        if entry_ids:
            s.query(EntryFieldValue).filter(
                EntryFieldValue.entry_id.in_(entry_ids)
            ).delete(synchronize_session='fetch')
        s.query(AtomEntry).filter(AtomEntry.atom_id.in_(remove_ids)).delete(synchronize_session='fetch')
        s.query(CanvasAtom).filter(CanvasAtom.atom_id.in_(remove_ids)).delete(synchronize_session='fetch')

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
        existing = (
            s.query(UnifiedRelation)
            .filter_by(from_atom_id=source_id, to_atom_id=target_id, relation_type='blocks')
            .filter(UnifiedRelation.is_deleted == False)
            .first()
        )
        if existing:
            return jsonify({'ok': True, 'message': 'already exists'})

        s.add(UnifiedRelation(from_atom_id=source_id, to_atom_id=target_id, relation_type='blocks'))
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
            s.query(UnifiedRelation)
            .filter_by(from_atom_id=source_id, to_atom_id=target_id, relation_type='blocks')
            .filter(UnifiedRelation.is_deleted == False)
            .first()
        )
        if not rel:
            return jsonify({'error': 'relation not found'}), 404
        rel.is_deleted = True
        s.flush()
        return jsonify({'ok': True})


# ============================================================
#  Gantt 配色設定（per-user, 存 system_config）
# ============================================================

_DEFAULT_GANTT_COLORS = {
    'summaryBarColor': '#266ACF',
    'noBarBgColor': '#3A9CFD',
    'outlineCard': '#3A9CFD',
    'taskColors': ['#F0F0FF', '#F7FFF5', '#F0F9FF'],
}


def _gantt_colors_key():
    username = session.get('username', 'default')
    return 'gantt_colors_' + username


@bp.route('/api/beak-gantt/colors')
def get_gantt_colors():
    """取得當前用戶的 Gantt 配色設定。"""
    with session_scope() as s:
        row = s.query(SystemConfig).filter(
            SystemConfig.key == _gantt_colors_key()
        ).first()
        if row and row.value:
            try:
                return jsonify(json.loads(row.value))
            except (json.JSONDecodeError, TypeError):
                pass
        return jsonify(_DEFAULT_GANTT_COLORS)


@bp.route('/api/beak-gantt/colors', methods=['PUT'])
def put_gantt_colors():
    """儲存當前用戶的 Gantt 配色設定。"""
    body = request.get_json()
    if not body:
        return jsonify({'error': 'need JSON body'}), 400

    # 驗證必要欄位
    colors = {
        'summaryBarColor': body.get('summaryBarColor', _DEFAULT_GANTT_COLORS['summaryBarColor']),
        'noBarBgColor': body.get('noBarBgColor', _DEFAULT_GANTT_COLORS['noBarBgColor']),
        'outlineCard': body.get('outlineCard', _DEFAULT_GANTT_COLORS['outlineCard']),
        'taskColors': body.get('taskColors', _DEFAULT_GANTT_COLORS['taskColors']),
    }

    key = _gantt_colors_key()
    with session_scope() as s:
        row = s.query(SystemConfig).filter(SystemConfig.key == key).first()
        if row:
            row.value = json.dumps(colors)
        else:
            s.add(SystemConfig(key=key, value=json.dumps(colors),
                               description='Gantt color preferences'))
        s.flush()
    return jsonify({'ok': True})


# ============================================================
#  Helpers
# ============================================================

def _extract_structured_entries(content_json):
    """從 content_json 中提取 structuredEntry 項目。

    Returns:
        list[dict]: [{'text': '...', 'entry_id': int|None}, ...]
    """
    if not content_json or not isinstance(content_json, dict):
        return []

    doc_content = content_json.get('content', [])
    entries = []
    for node in doc_content:
        if node.get('type') != 'structuredEntry':
            continue
        attrs = node.get('attrs', {})
        # 只提取 task 類型的 entries（Gantt 不顯示 diary/expense/health 等）
        if attrs.get('schemaCode') not in ('task',):
            continue
        # 遞迴收集文字
        text = _collect_text(node.get('content', []))
        if not text:
            continue
        entries.append({
            'text': text,
            'entry_id': attrs.get('entryId'),
        })
    return entries


def _collect_text(nodes):
    """遞迴收集 ProseMirror node tree 中的文字。"""
    parts = []
    for node in nodes:
        if node.get('type') == 'text':
            parts.append(node.get('text', ''))
        if 'content' in node:
            parts.append(_collect_text(node['content']))
    return ''.join(parts).strip()


def _build_entry_fv_map(s, atom_ids):
    """批次查詢已持久化 entry 的 field values。

    Returns:
        dict[int, dict]: {entry_id: {field_name: value, ...}}
    """
    if not atom_ids:
        return {}

    entries = (
        s.query(AtomEntry)
        .filter(AtomEntry.atom_id.in_(atom_ids))
        .all()
    )
    if not entries:
        return {}

    entry_ids = [e.id for e in entries]
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


def _add_n_days(date_str, n):
    """date_str + n 天。"""
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    return (dt + timedelta(days=n)).strftime('%Y-%m-%d')


def _upsert_field(s, entry_id, field_id, value, changed_by='gantt:drag'):
    from core.audit import log_field_change
    existing = s.query(EntryFieldValue).filter_by(entry_id=entry_id, field_id=field_id).first()
    new_val = str(value) if value is not None else None
    if existing:
        log_field_change(s, entry_id, field_id, existing.value, new_val, changed_by)
        existing.value = new_val
    else:
        log_field_change(s, entry_id, field_id, None, new_val, changed_by)
        s.add(EntryFieldValue(entry_id=entry_id, field_id=field_id, value=new_val))


def _calc_duration(start_raw, end_raw):
    """從起訖日期計算天數，無效或無資料時回傳 1。"""
    if not start_raw or not end_raw:
        return 1
    try:
        s = datetime.strptime(start_raw[:10], '%Y-%m-%d')
        e = datetime.strptime(end_raw[:10], '%Y-%m-%d')
        return max(1, (e - s).days + 1)
    except (ValueError, TypeError):
        return 1


def _resolve_progress(fv):
    p = fv.get('progress', '')
    if p:
        try:
            return max(0.0, min(1.0, int(float(p)) / 100))
        except (ValueError, TypeError):
            pass
    status = fv.get('status', 'pending')
    if status == 'done':
        return 1.0
    if status == 'in_progress':
        return 0.5
    return 0.0
