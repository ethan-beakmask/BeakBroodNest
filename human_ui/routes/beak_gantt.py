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
import re
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request, session
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import flag_modified

from core.db import session_scope
from core.models import (
    KnowledgeAtom, Canvas, CanvasAtom, CanvasConnection,
    UnifiedRelation, AtomEntry, EntrySchema, EntrySchemaField,
    EntryFieldValue,
    GanttColorsDefault, GanttColorsProject,
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
                    # 粗 bar = planned（排程），拖拉改的是 planned
                    ps = fv.get('planned_start', '')
                    pe = fv.get('planned_end', '')
                    start = ps[:10] if ps else _add_n_days(today, day_offset)
                    duration = _calc_duration(ps, pe) if ps else 1
                    # actual 另外傳，前端用於繪製進度細 bar
                    a_start = fv.get('actual_start', '')
                    a_end = fv.get('actual_end', '')
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
                        '_actual_start': a_start[:10] if a_start else '',
                        '_actual_end': a_end[:10] if a_end else '',
                    })
                    day_offset += 1
            else:
                # 葉子 Task（Card 無 Items） -- 查 atom_entries 取欄位值
                leaf_fv = _get_leaf_fv(entry_fv_map, atom.id, s)
                ps = leaf_fv.get('planned_start', '')
                pe = leaf_fv.get('planned_end', '')
                start = ps[:10] if ps else _add_n_days(today, day_offset)
                duration = _calc_duration(ps, pe) if ps else 1
                a_start = leaf_fv.get('actual_start', '')
                a_end = leaf_fv.get('actual_end', '')
                tasks.append({
                    'id': atom.id,
                    'text': atom.title,
                    'parent': 0,
                    '_isSummary': False,
                    'start_date': start,
                    'duration': duration,
                    'progress': _resolve_progress(leaf_fv),
                    'open': True,
                    '_status': leaf_fv.get('status', 'pending'),
                    '_urgency': leaf_fv.get('urgency', 'M'),
                    '_actual_start': a_start[:10] if a_start else '',
                    '_actual_end': a_end[:10] if a_end else '',
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
        link_seen = set()
        link_seq = 0
        for conn in connections:
            if conn.source_atom_id in atom_id_set and conn.target_atom_id in atom_id_set:
                link_seq += 1
                key = ('a', conn.source_atom_id, 'a', conn.target_atom_id)
                if key in link_seen:
                    continue
                link_seen.add(key)
                links.append({
                    'id': 'c{}'.format(link_seq),
                    'source': conn.source_atom_id,
                    'target': conn.target_atom_id,
                    'type': '0',
                })

        # 同步 UnifiedRelation 中的 blocks 邊（涵蓋 atom/entry 任意組合）
        # 在 gantt 上呈現為 link，保證刷新後仍存在
        entry_id_to_gid = {}
        for atom in atoms.values():
            entries = _extract_structured_entries(atom.content_json)
            for idx, entry in enumerate(entries):
                eid = entry.get('entry_id')
                if eid:
                    entry_id_to_gid[int(eid)] = 'e{}_{}'.format(atom.id, idx)

        block_rels = (
            s.query(UnifiedRelation)
            .filter(
                UnifiedRelation.relation_type == 'blocks',
                UnifiedRelation.is_deleted == False,  # noqa: E712
            )
            .all()
        )
        for rel in block_rels:
            src = None
            tgt = None
            if rel.from_atom_id and rel.from_atom_id in atom_id_set:
                src = rel.from_atom_id
                src_kind = 'a'
            elif rel.from_entry_id and rel.from_entry_id in entry_id_to_gid:
                src = entry_id_to_gid[rel.from_entry_id]
                src_kind = 'e'
            if rel.to_atom_id and rel.to_atom_id in atom_id_set:
                tgt = rel.to_atom_id
                tgt_kind = 'a'
            elif rel.to_entry_id and rel.to_entry_id in entry_id_to_gid:
                tgt = entry_id_to_gid[rel.to_entry_id]
                tgt_kind = 'e'
            if src is None or tgt is None:
                continue
            key = (src_kind, src, tgt_kind, tgt)
            if key in link_seen:
                continue
            link_seen.add(key)
            link_seq += 1
            links.append({
                'id': 'r{}'.format(rel.id),
                'source': src,
                'target': tgt,
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
    parent_raw = body.get('parent', 0)
    start_date = body.get('start_date', '')
    duration = body.get('duration', 1)

    # 解析 parent：可能是 atom_id（int/數字字串）或 'e<atom>_<idx>'。
    # 若 parent 指向 entry → 在同一張卡片內新增 task structuredEntry，不另開新卡片。
    parent_atom_id = 0
    parent_is_entry = False
    if isinstance(parent_raw, int):
        parent_atom_id = parent_raw
    elif isinstance(parent_raw, str):
        if parent_raw.isdigit():
            parent_atom_id = int(parent_raw)
        else:
            m = re.match(r'^e(\d+)_(\d+)$', parent_raw)
            if m:
                parent_atom_id = int(m.group(1))
                parent_is_entry = True

    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.slug == slug).first()
        if not canvas:
            return jsonify({'error': 'canvas not found'}), 404

        task_schema = s.query(EntrySchema).filter_by(code='task').first()
        if not task_schema:
            return jsonify({'error': 'task schema not found'}), 500

        field_map = {
            f.name: f for f in
            s.query(EntrySchemaField).filter_by(schema_id=task_schema.id).all()
        }
        defaults = {'status': 'pending', 'urgency': 'M'}
        if start_date:
            defaults['planned_start'] = start_date + 'T00:00'
            if duration and int(duration) > 0:
                try:
                    dt = datetime.strptime(start_date, '%Y-%m-%d')
                    end_dt = dt + timedelta(days=max(1, int(duration)) - 1)
                    defaults['planned_end'] = end_dt.strftime('%Y-%m-%d') + 'T00:00'
                except (ValueError, TypeError):
                    pass

        # 分支 A：parent 指向 entry → 在同一卡片內新增 task entry + structuredEntry node
        if parent_is_entry and parent_atom_id:
            parent_atom = s.get(KnowledgeAtom, parent_atom_id)
            if not parent_atom:
                return jsonify({'error': 'parent atom not found'}), 404

            entry = AtomEntry(atom_id=parent_atom.id, schema_id=task_schema.id, raw_text=text)
            s.add(entry)
            s.flush()
            for fname, fval in defaults.items():
                sf = field_map.get(fname)
                if sf:
                    _upsert_field(s, entry.id, sf.id, fval)

            # 把 structuredEntry node append 到 content_json
            doc = parent_atom.content_json or {}
            if not isinstance(doc, dict) or doc.get('type') != 'doc':
                doc = {'type': 'doc', 'content': []}
            content = doc.get('content', [])
            if not isinstance(content, list):
                content = []
            content.append({
                'type': 'structuredEntry',
                'attrs': {
                    'entryId': entry.id,
                    'schemaId': task_schema.id,
                    'schemaCode': 'task',
                    'collapsed': True,
                    'fieldValues': dict(defaults),
                },
                'content': [
                    {'type': 'text', 'text': text},
                ],
            })
            doc['content'] = content
            parent_atom.content_json = doc
            flag_modified(parent_atom, 'content_json')

            s.flush()
            return jsonify({
                'ok': True,
                'tid': parent_atom.id,
                'entry_id': entry.id,
                'inline': True,
            })

        # 分支 B：parent 為 atom 或無 parent → 新建獨立卡片（既有行為）
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
        for fname, fval in defaults.items():
            sf = field_map.get(fname)
            if sf:
                _upsert_field(s, entry.id, sf.id, fval)

        if parent_atom_id and parent_atom_id != 0:
            parent_atom = s.get(KnowledgeAtom, parent_atom_id)
            if parent_atom:
                s.add(UnifiedRelation(
                    from_atom_id=parent_atom_id, to_atom_id=atom.id,
                    relation_type='contains',
                ))

        s.flush()
        return jsonify({'ok': True, 'tid': atom.id, 'entry_id': entry.id})


@bp.route('/api/project/<slug>/beak-gantt/entry/<int:entry_id>', methods=['PATCH'])
def patch_beak_gantt_entry(slug, entry_id):
    """更新任務欄位（以 entry_id 為鍵，供 Item 級拖拉使用）。"""
    body = request.get_json()
    if not body:
        return jsonify({'error': 'need JSON body'}), 400

    with session_scope() as s:
        entry = s.get(AtomEntry, entry_id)
        if not entry:
            return jsonify({'error': 'entry not found'}), 404

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

        _apply_progress_consistency(s, entry.id, body, field_map, updated)

        # 觸發所屬 atom 的 updated_at 更新，讓 polling 偵測到變更
        if updated:
            atom = s.get(KnowledgeAtom, entry.atom_id)
            if atom:
                atom.updated_at = datetime.now()

        s.flush()
        return jsonify({'ok': True, 'entry_id': entry.id, 'updated': updated})


@bp.route('/api/project/<slug>/beak-gantt/<int:atom_id>', methods=['PATCH'])
def patch_beak_gantt_task(slug, atom_id):
    """更新任務欄位（以 atom_id 為鍵，供葉子 Card 級拖拉使用）。"""
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

        _apply_progress_consistency(s, entry.id, body, field_map, updated)

        # 觸發所屬 atom 的 updated_at 更新，讓 polling 偵測到變更
        if updated:
            atom = s.get(KnowledgeAtom, atom_id)
            if atom:
                atom.updated_at = datetime.now()

        s.flush()
        return jsonify({'ok': True, 'entry_id': entry.id, 'updated': updated})


@bp.route('/api/project/<slug>/beak-gantt/<task_id>', methods=['DELETE'])
def delete_beak_gantt_task(slug, task_id):
    """刪除任務：
      - task_id 為 atom_id（整數字串）→ 刪卡片（含子卡片、entries、canvas_atom、relations）
      - task_id 為 'e<atom>_<idx>' → 只刪該 structuredEntry（含 field_values、relations、content_json 節點）
    """
    with session_scope() as s:
        kind, ref_id = _parse_gantt_node_id(s, task_id)

        # 分支：刪 entry（structuredEntry）
        if kind == 'entry':
            entry = s.get(AtomEntry, ref_id)
            if not entry:
                return jsonify({'error': 'entry not found'}), 404
            atom_id = entry.atom_id

            # 1) 軟刪以此 entry 為端點的 unified_relations
            rels = (
                s.query(UnifiedRelation)
                .filter(
                    (UnifiedRelation.from_entry_id == ref_id) |
                    (UnifiedRelation.to_entry_id == ref_id),
                    UnifiedRelation.is_deleted == False,  # noqa: E712
                )
                .all()
            )
            for rel in rels:
                rel.is_deleted = True

            # 2) 刪 entry_field_values + entry
            s.query(EntryFieldValue).filter(EntryFieldValue.entry_id == ref_id).delete(
                synchronize_session='fetch'
            )
            s.delete(entry)

            # 3) 從 atom.content_json 移除對應 structuredEntry 節點
            atom = s.get(KnowledgeAtom, atom_id)
            if atom and isinstance(atom.content_json, dict):
                content = atom.content_json.get('content', [])
                if isinstance(content, list):
                    new_content = [
                        n for n in content
                        if not (
                            isinstance(n, dict)
                            and n.get('type') == 'structuredEntry'
                            and n.get('attrs', {}).get('entryId') == ref_id
                        )
                    ]
                    if len(new_content) != len(content):
                        atom.content_json['content'] = new_content
                        flag_modified(atom, 'content_json')

            s.flush()
            return jsonify({'ok': True, 'deleted': [task_id], 'entry_id': ref_id, 'atom_id': atom_id})

        # 分支：刪 atom 卡片（既有行為）
        if kind != 'atom':
            return jsonify({'error': f'invalid task_id: {task_id!r}'}), 400
        atom_id = ref_id
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


def _parse_gantt_node_id(s, raw):
    """解析 gantt task id：
      - 整數或數字字串 -> ('atom', atom_id)
      - 'e<atom_id>_<idx>'（structuredEntry 子任務） -> ('entry', entry_id)
    無法解析回傳 (None, None)。
    """
    if isinstance(raw, int):
        return 'atom', raw
    if not isinstance(raw, str):
        return None, None
    if raw.isdigit():
        return 'atom', int(raw)
    m = re.match(r'^e(\d+)_(\d+)$', raw)
    if not m:
        return None, None
    atom_id = int(m.group(1))
    idx = int(m.group(2))
    atom = s.get(KnowledgeAtom, atom_id)
    if not atom:
        return None, None
    entries = _extract_structured_entries(atom.content_json)
    if 0 <= idx < len(entries):
        eid = entries[idx].get('entry_id')
        if eid:
            return 'entry', int(eid)
    return None, None


def _build_relation_filter(query, kind, side, value):
    """side ∈ {'from','to'}, kind ∈ {'atom','entry'}"""
    col_map = {
        ('from', 'atom'):  UnifiedRelation.from_atom_id,
        ('from', 'entry'): UnifiedRelation.from_entry_id,
        ('to',   'atom'):  UnifiedRelation.to_atom_id,
        ('to',   'entry'): UnifiedRelation.to_entry_id,
    }
    other_kind = 'entry' if kind == 'atom' else 'atom'
    return query.filter(
        col_map[(side, kind)] == value,
        col_map[(side, other_kind)] == None,  # noqa: E711
    )


@bp.route('/api/project/<slug>/beak-gantt/link', methods=['POST'])
def create_beak_gantt_link(slug):
    """建立依賴關係（blocks）。body: {source: gantt_id, target: gantt_id}
    gantt_id 可為 atom_id（int / 數字字串）或 'e<atom>_<idx>'（structuredEntry）。
    """
    body = request.get_json()
    if not body:
        return jsonify({'error': 'need JSON body'}), 400

    source_raw = body.get('source')
    target_raw = body.get('target')
    if source_raw in (None, '') or target_raw in (None, ''):
        return jsonify({'error': 'need source and target'}), 400

    with session_scope() as s:
        src_kind, src_id = _parse_gantt_node_id(s, source_raw)
        tgt_kind, tgt_id = _parse_gantt_node_id(s, target_raw)
        if not src_kind or not tgt_kind:
            return jsonify({'error': f'invalid id: source={source_raw!r}, target={target_raw!r}'}), 400

        q = s.query(UnifiedRelation).filter(
            UnifiedRelation.relation_type == 'blocks',
            UnifiedRelation.is_deleted == False,  # noqa: E712
        )
        q = _build_relation_filter(q, src_kind, 'from', src_id)
        q = _build_relation_filter(q, tgt_kind, 'to',   tgt_id)
        existing = q.first()
        if existing:
            return jsonify({'ok': True, 'message': 'already exists'})

        rel = UnifiedRelation(relation_type='blocks')
        if src_kind == 'atom':
            rel.from_atom_id = src_id
        else:
            rel.from_entry_id = src_id
        if tgt_kind == 'atom':
            rel.to_atom_id = tgt_id
        else:
            rel.to_entry_id = tgt_id
        s.add(rel)
        s.flush()
        return jsonify({'ok': True, 'rel_id': rel.id})


@bp.route('/api/project/<slug>/beak-gantt/link', methods=['DELETE'])
def delete_beak_gantt_link(slug):
    """刪除依賴關係。body: {source: gantt_id, target: gantt_id}"""
    body = request.get_json()
    if not body:
        return jsonify({'error': 'need JSON body'}), 400

    source_raw = body.get('source')
    target_raw = body.get('target')
    if source_raw in (None, '') or target_raw in (None, ''):
        return jsonify({'error': 'need source and target'}), 400

    with session_scope() as s:
        src_kind, src_id = _parse_gantt_node_id(s, source_raw)
        tgt_kind, tgt_id = _parse_gantt_node_id(s, target_raw)
        if not src_kind or not tgt_kind:
            return jsonify({'error': f'invalid id: source={source_raw!r}, target={target_raw!r}'}), 400

        q = s.query(UnifiedRelation).filter(
            UnifiedRelation.relation_type == 'blocks',
            UnifiedRelation.is_deleted == False,  # noqa: E712
        )
        q = _build_relation_filter(q, src_kind, 'from', src_id)
        q = _build_relation_filter(q, tgt_kind, 'to',   tgt_id)
        rel = q.first()
        if not rel:
            return jsonify({'error': 'relation not found'}), 404
        rel.is_deleted = True
        s.flush()
        return jsonify({'ok': True})


# ============================================================
#  Gantt 配色設定
#  - 個人預設: GanttColorsDefault(username PK)
#  - 專案配色: GanttColorsProject(canvas_id PK)
#  - load 順序: project → user_default → 套件預設（前端 fallback）
# ============================================================

_DEFAULT_GANTT_COLORS = {
    'summaryBarColor': '#266ACF',
    'noBarBgColor': '#3A9CFD',
    'outlineCard': '#3A9CFD',
    'taskColors': ['#F0F0FF', '#F7FFF5', '#F0F9FF'],
}


def _validate_colors(body):
    """從 request body 萃取並驗證 colors 欄位，缺欄位以套件預設補。"""
    if not isinstance(body, dict):
        return None
    return {
        'summaryBarColor': body.get('summaryBarColor', _DEFAULT_GANTT_COLORS['summaryBarColor']),
        'noBarBgColor': body.get('noBarBgColor', _DEFAULT_GANTT_COLORS['noBarBgColor']),
        'outlineCard': body.get('outlineCard', _DEFAULT_GANTT_COLORS['outlineCard']),
        'taskColors': body.get('taskColors', _DEFAULT_GANTT_COLORS['taskColors']),
    }


def _current_username():
    return session.get('username', 'default')


# ---- 個人預設 ----

@bp.route('/api/beak-gantt/colors/default')
def get_gantt_colors_default():
    """取得當前用戶的個人預設 Gantt 配色，無設定則回套件預設。"""
    username = _current_username()
    with session_scope() as s:
        row = s.query(GanttColorsDefault).filter_by(username=username).first()
        if row and row.colors:
            return jsonify({'colors': row.colors, 'source': 'user'})
    return jsonify({'colors': _DEFAULT_GANTT_COLORS, 'source': 'fallback'})


@bp.route('/api/beak-gantt/colors/default', methods=['PUT'])
def put_gantt_colors_default():
    """儲存當前用戶的個人預設 Gantt 配色。"""
    colors = _validate_colors(request.get_json(silent=True))
    if colors is None:
        return jsonify({'error': 'need JSON body'}), 400

    username = _current_username()
    with session_scope() as s:
        row = s.query(GanttColorsDefault).filter_by(username=username).first()
        if row:
            row.colors = colors
        else:
            s.add(GanttColorsDefault(username=username, colors=colors))
        s.flush()
    return jsonify({'ok': True})


# ---- 專案配色 ----

@bp.route('/api/project/<slug>/beak-gantt/colors')
def get_gantt_colors_project(slug):
    """取得專案配色（已解析 fallback：project → user_default → 套件預設）。

    回傳 source 標示實際命中層級，供 UI 顯示徽章用。
    """
    username = _current_username()
    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.slug == slug).first()
        if not canvas:
            return jsonify({'error': 'project not found'}), 404
        proj = s.query(GanttColorsProject).filter_by(canvas_id=canvas.id).first()
        if proj and proj.colors:
            return jsonify({'colors': proj.colors, 'source': 'project'})
        user = s.query(GanttColorsDefault).filter_by(username=username).first()
        if user and user.colors:
            return jsonify({'colors': user.colors, 'source': 'user'})
    return jsonify({'colors': _DEFAULT_GANTT_COLORS, 'source': 'fallback'})


@bp.route('/api/project/<slug>/beak-gantt/colors', methods=['PUT'])
def put_gantt_colors_project(slug):
    """儲存專案配色覆寫。"""
    colors = _validate_colors(request.get_json(silent=True))
    if colors is None:
        return jsonify({'error': 'need JSON body'}), 400

    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.slug == slug).first()
        if not canvas:
            return jsonify({'error': 'project not found'}), 404
        row = s.query(GanttColorsProject).filter_by(canvas_id=canvas.id).first()
        if row:
            row.colors = colors
        else:
            s.add(GanttColorsProject(canvas_id=canvas.id, colors=colors))
        s.flush()
    return jsonify({'ok': True})


@bp.route('/api/project/<slug>/beak-gantt/colors', methods=['DELETE'])
def delete_gantt_colors_project(slug):
    """移除專案配色覆寫，後續 GET 將 fallback 至個人預設。"""
    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.slug == slug).first()
        if not canvas:
            return jsonify({'error': 'project not found'}), 404
        row = s.query(GanttColorsProject).filter_by(canvas_id=canvas.id).first()
        if row:
            s.delete(row)
            s.flush()
    return jsonify({'ok': True})


# ============================================================
#  Helpers
# ============================================================

def _get_leaf_fv(entry_fv_map, atom_id, s):
    """取得葉子 Card（無 content_json items）的第一筆 task entry 欄位值。"""
    # entry_fv_map 已按 entry_id 索引，需從 atom_id 反查
    entries = s.query(AtomEntry).filter_by(atom_id=atom_id).all()
    for e in entries:
        fv = entry_fv_map.get(e.id, {})
        if fv:
            return fv
    return {}


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
    # 空字串視同 None（清除語意）
    new_val = str(value) if value is not None and str(value).strip() != '' else None
    if existing:
        log_field_change(s, entry_id, field_id, existing.value, new_val, changed_by)
        existing.value = new_val
    else:
        if new_val is None:
            return  # 值為空且不存在，不需要建立記錄
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


def _apply_progress_consistency(s, entry_id, body, field_map, updated):
    """確保 actual_end 與進度/狀態語意一致。

    僅在 body 顯式帶入 progress 或 status 時才介入，避免影響純拖拉時間欄位的請求。
    - 進度 < 100 且 status != done -> 清空 actual_end
    - 進度 >= 100 或 status == done -> 若 actual_end 為空，補當下時間
    """
    if 'progress' not in body and 'status' not in body:
        return

    progress_raw = body.get('progress', '')
    status_raw = body.get('status', '')

    pct = None
    if progress_raw not in (None, ''):
        try:
            pct = int(float(progress_raw))
        except (ValueError, TypeError):
            pct = None

    if pct is not None:
        is_done = pct >= 100
    elif status_raw:
        is_done = status_raw == 'done'
    else:
        return

    ae_field = field_map.get('actual_end')
    if not ae_field:
        return

    ae_existing = (
        s.query(EntryFieldValue)
        .filter_by(entry_id=entry_id, field_id=ae_field.id)
        .first()
    )

    if not is_done:
        # 進度退回 -> 清空 actual_end（前端可能沒主動送，後端兜底）
        if ae_existing and ae_existing.value:
            _upsert_field(s, entry_id, ae_field.id, '', changed_by='gantt:auto-clear')
            updated['actual_end'] = ''
    else:
        # 已完成 -> 若 actual_end 空，自動補當下時間（避免漏寫）
        already_set_in_body = body.get('actual_end') not in (None, '')
        if already_set_in_body:
            return
        if ae_existing and ae_existing.value:
            return
        now_str = datetime.now().strftime('%Y-%m-%dT%H:%M')
        _upsert_field(s, entry_id, ae_field.id, now_str, changed_by='gantt:auto-fill')
        updated['actual_end'] = now_str
