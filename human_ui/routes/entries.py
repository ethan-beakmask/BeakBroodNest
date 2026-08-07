# -*- coding: utf-8 -*-
"""Atom Entries & Entry Field Values CRUD API"""

import datetime

from flask import Blueprint, request, jsonify
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.task_service import (
    TaskError, apply_action, save_field_values as _save_field_values,
)
from core.models import (
    AtomEntry, EntryFieldValue, EntrySchema,
    KnowledgeAtom, CanvasConnection,
)

bp = Blueprint('entries', __name__)


def _entry_to_dict(entry, s):
    """轉換 entry 為 dict，含 field_values。"""
    d = entry.to_dict()
    fvs = (
        s.query(EntryFieldValue)
        .options(joinedload(EntryFieldValue.field))
        .filter_by(entry_id=entry.id)
        .all()
    )
    d['field_values'] = {}
    for fv in fvs:
        if fv.field:
            d['field_values'][fv.field.name] = fv.value
    d['schema_code'] = entry.schema.code if entry.schema else None
    d['schema_name'] = entry.schema.name if entry.schema else None
    d['schema_color'] = entry.schema.color if entry.schema else None
    d['schema_icon'] = entry.schema.icon if entry.schema else None
    return d


# ============================================================
# Atom Entries CRUD
# ============================================================

@bp.route('/api/atoms/<int:atom_id>/entries', methods=['GET'])
def list_entries(atom_id):
    with session_scope() as s:
        atom = s.get(KnowledgeAtom, atom_id)
        if not atom:
            return jsonify({'error': '原子不存在'}), 404
        entries = (
            s.query(AtomEntry)
            .options(joinedload(AtomEntry.schema))
            .filter_by(atom_id=atom_id)
            .order_by(AtomEntry.sort_order)
            .all()
        )
        return jsonify([_entry_to_dict(e, s) for e in entries])


@bp.route('/api/atoms/<int:atom_id>/entries', methods=['POST'])
def create_entry(atom_id):
    data = request.get_json()
    if not data:
        return jsonify({'error': '需要 JSON body'}), 400

    schema_id = data.get('schema_id')
    schema_code = data.get('schema_code')

    with session_scope() as s:
        atom = s.get(KnowledgeAtom, atom_id)
        if not atom:
            return jsonify({'error': '原子不存在'}), 404

        # Resolve schema by id or code
        schema = None
        if schema_id:
            schema = s.get(EntrySchema, schema_id)
        elif schema_code:
            schema = s.query(EntrySchema).filter_by(code=schema_code).first()
        if not schema:
            return jsonify({'error': '記錄類型不存在'}), 400

        # 自動排序：放在最後
        max_order = (
            s.query(AtomEntry.sort_order)
            .filter_by(atom_id=atom_id)
            .order_by(AtomEntry.sort_order.desc())
            .first()
        )
        next_order = (max_order[0] + 1) if max_order else 0

        entry = AtomEntry(
            atom_id=atom_id,
            schema_id=schema.id,
            sort_order=data.get('sort_order', next_order),
            raw_text=data.get('raw_text', ''),
            summary=data.get('summary', ''),
        )
        s.add(entry)
        s.flush()

        # 寫入欄位值
        if data.get('field_values'):
            _save_field_values(s, entry, data['field_values'])

        s.flush()
        return jsonify(_entry_to_dict(entry, s)), 201


@bp.route('/api/entries/<int:entry_id>', methods=['GET'])
def get_entry(entry_id):
    with session_scope() as s:
        entry = (
            s.query(AtomEntry)
            .options(joinedload(AtomEntry.schema))
            .get(entry_id)
        )
        if not entry:
            return jsonify({'error': 'Entry 不存在'}), 404
        return jsonify(_entry_to_dict(entry, s))


@bp.route('/api/entries/<int:entry_id>', methods=['PUT'])
def update_entry(entry_id):
    data = request.get_json()
    with session_scope() as s:
        entry = (
            s.query(AtomEntry)
            .options(joinedload(AtomEntry.schema))
            .get(entry_id)
        )
        if not entry:
            return jsonify({'error': 'Entry 不存在'}), 404

        for attr in ('raw_text', 'summary', 'sort_order'):
            if attr in data:
                setattr(entry, attr, data[attr])

        if 'schema_id' in data:
            schema = s.get(EntrySchema, data['schema_id'])
            if not schema:
                return jsonify({'error': '記錄類型不存在'}), 400
            entry.schema_id = schema.id

        if data.get('field_values'):
            _save_field_values(s, entry, data['field_values'])
            # 觸發所屬 atom 的 updated_at 更新，讓 polling 偵測到變更
            atom = s.get(KnowledgeAtom, entry.atom_id)
            if atom:
                atom.updated_at = datetime.datetime.now()

        s.flush()
        return jsonify(_entry_to_dict(entry, s))


@bp.route('/api/entries/<int:entry_id>', methods=['DELETE'])
def delete_entry(entry_id):
    with session_scope() as s:
        entry = s.get(AtomEntry, entry_id)
        if not entry:
            return jsonify({'error': 'Entry 不存在'}), 404
        s.delete(entry)
        return jsonify({'message': f'Entry {entry_id} 已刪除'})


@bp.route('/api/atoms/<int:atom_id>/entries/reorder', methods=['PUT'])
def reorder_entries(atom_id):
    """批次更新 entry 排序。body: {"entry_ids": [3, 1, 2]}"""
    data = request.get_json()
    entry_ids = data.get('entry_ids', [])
    if not entry_ids:
        return jsonify({'error': '需要 entry_ids 陣列'}), 400

    with session_scope() as s:
        entries = (
            s.query(AtomEntry)
            .filter(AtomEntry.atom_id == atom_id, AtomEntry.id.in_(entry_ids))
            .all()
        )
        entry_map = {e.id: e for e in entries}
        for i, eid in enumerate(entry_ids):
            if eid in entry_map:
                entry_map[eid].sort_order = i

        s.flush()
        updated = (
            s.query(AtomEntry)
            .options(joinedload(AtomEntry.schema))
            .filter_by(atom_id=atom_id)
            .order_by(AtomEntry.sort_order)
            .all()
        )
        return jsonify([_entry_to_dict(e, s) for e in updated])


@bp.route('/api/entries/<int:entry_id>/promote', methods=['POST'])
def promote_entry(entry_id):
    """將 entry 提升為獨立原子。

    - 建立新的 knowledge_atom，內容複製自 entry
    - 設定 entry.promoted_atom_id 指向新原子
    - 若 entry 有欄位值，寫入新原子的 content 作為結構化摘要
    """
    with session_scope() as s:
        entry = (
            s.query(AtomEntry)
            .options(joinedload(AtomEntry.schema))
            .get(entry_id)
        )
        if not entry:
            return jsonify({'error': 'Entry 不存在'}), 404
        if entry.promoted_atom_id:
            return jsonify({'error': '此 entry 已提升過', 'atom_id': entry.promoted_atom_id}), 409

        # 組合 content：raw_text + 欄位值摘要
        lines = []
        if entry.raw_text:
            lines.append(entry.raw_text)

        fvs = (
            s.query(EntryFieldValue)
            .options(joinedload(EntryFieldValue.field))
            .filter_by(entry_id=entry.id)
            .all()
        )
        if fvs:
            lines.append('')
            for fv in fvs:
                if fv.field and fv.value:
                    lines.append(f'- {fv.field.label}: {fv.value}')

        content = '\n'.join(lines)
        schema_name = entry.schema.name if entry.schema else 'entry'
        title = entry.raw_text[:60] if entry.raw_text else f'{schema_name} #{entry.id}'

        new_atom = KnowledgeAtom(
            title=title,
            content=content,
            atom_type='F',
            source='derived',
            source_detail=f'promoted from entry #{entry.id} (atom #{entry.atom_id})',
        )
        s.add(new_atom)
        s.flush()

        entry.promoted_atom_id = new_atom.id
        s.flush()

        return jsonify({
            'entry_id': entry.id,
            'promoted_atom_id': new_atom.id,
            'atom': new_atom.to_dict(),
        }), 201


@bp.route('/api/atoms/<int:atom_id>/entries/sync', methods=['POST'])
def sync_entries(atom_id):
    """批次同步：接收編輯器傳來的完整 entries 陣列，對 DB 做 diff 更新。

    body: { "entries": [
        { "id": 123, "schema_code": "todo", "sort_order": 0, "raw_text": "...", "field_values": {...} },
        { "schema_code": "freetext", "sort_order": 1, "raw_text": "..." },  // 無 id = 新建
    ]}

    流程：
    1. 有 id 的 -> 更新
    2. 無 id 的 -> 新建
    3. DB 中有但 body 中沒出現的 -> 刪除
    4. 同步更新 atom.content 為全文快照
    """
    data = request.get_json()
    if not data or 'entries' not in data:
        return jsonify({'error': '需要 entries 陣列'}), 400

    with session_scope() as s:
        atom = s.get(KnowledgeAtom, atom_id)
        if not atom:
            return jsonify({'error': '原子不存在'}), 404

        incoming = data['entries']
        incoming_ids = set()
        result_entries = []

        for i, ed in enumerate(incoming):
            entry_id = ed.get('id')
            schema_code = ed.get('schema_code', 'freetext')
            schema = s.query(EntrySchema).filter_by(code=schema_code).first()
            if not schema:
                continue

            if entry_id:
                # 更新既有
                entry = s.get(AtomEntry, entry_id)
                if entry and entry.atom_id == atom_id:
                    entry.schema_id = schema.id
                    entry.sort_order = i
                    entry.raw_text = ed.get('raw_text', entry.raw_text)
                    entry.summary = ed.get('summary', entry.summary)
                    if ed.get('field_values'):
                        _save_field_values(s, entry, ed['field_values'])
                    incoming_ids.add(entry.id)
                    result_entries.append(entry)
                else:
                    # entryId 失效（DB 中已不存在或屬於別 atom）
                    # → self-heal：視為新建，避免 content_json 與 atom_entries 永久 desync
                    entry = AtomEntry(
                        atom_id=atom_id,
                        schema_id=schema.id,
                        sort_order=i,
                        raw_text=ed.get('raw_text', ''),
                        summary=ed.get('summary', ''),
                    )
                    s.add(entry)
                    s.flush()
                    if ed.get('field_values'):
                        _save_field_values(s, entry, ed['field_values'])
                    incoming_ids.add(entry.id)
                    result_entries.append(entry)
            else:
                # 新建
                entry = AtomEntry(
                    atom_id=atom_id,
                    schema_id=schema.id,
                    sort_order=i,
                    raw_text=ed.get('raw_text', ''),
                    summary=ed.get('summary', ''),
                )
                s.add(entry)
                s.flush()
                if ed.get('field_values'):
                    _save_field_values(s, entry, ed['field_values'])
                incoming_ids.add(entry.id)
                result_entries.append(entry)

        # 刪除不在 incoming 中的舊 entries（先清理引用的 canvas_connections）
        old_entries = s.query(AtomEntry).filter_by(atom_id=atom_id).all()
        deleted_entry_ids = [old.id for old in old_entries if old.id not in incoming_ids]
        if deleted_entry_ids:
            from sqlalchemy import or_
            s.query(CanvasConnection).filter(
                or_(
                    CanvasConnection.source_entry_id.in_(deleted_entry_ids),
                    CanvasConnection.target_entry_id.in_(deleted_entry_ids),
                )
            ).delete(synchronize_session='fetch')
        for old in old_entries:
            if old.id not in incoming_ids:
                s.delete(old)

        # 同步 content 全文快照
        # 用雙換行確保 markdown 渲染時每筆 entry 各自獨立段落，避免 4 張圖橫向擠成一列
        texts = []
        for e in sorted(result_entries, key=lambda x: x.sort_order):
            texts.append(e.raw_text)
        atom.content = '\n\n'.join(texts)
        atom.updated_at = datetime.datetime.now()
        # 這條也會改寫 atom.content，不記歸屬的話人類的編輯會留在舊值上（多半是 claude）。
        # 本 API 只有人類 UI 會呼叫，身份固定 ethan；edit_source 只認 'todos'，其餘一律 ui。
        atom.updated_by = 'ethan'
        atom.updated_via = 'todos' if data.get('edit_source') == 'todos' else 'ui'

        s.flush()
        return jsonify({
            'entries': [_entry_to_dict(e, s) for e in result_entries],
            'content_snapshot': atom.content,
        })


@bp.route('/api/atoms/<int:atom_id>/task/action', methods=['POST'])
def task_action(atom_id):
    """執行任務狀態轉移：pause / resume / cancel / reopen。

    Body: {
        "action": "pause" | "resume" | "cancel" | "reopen",
        "reason": "...",         # optional
        "source": "card" | "gantt"  # optional, default 'card'，用於 changed_by 標記
    }
    """
    body = request.get_json() or {}
    action = body.get('action')
    reason = (body.get('reason') or '').strip()
    source = body.get('source') or 'card'
    if source not in ('card', 'gantt'):
        source = 'card'
    changed_by = f'{source}:{action}'

    with session_scope() as s:
        try:
            result = apply_action(s, atom_id, action, reason, changed_by)
        except TaskError as e:
            return jsonify({'error': str(e)}), 400
        return jsonify(result)
