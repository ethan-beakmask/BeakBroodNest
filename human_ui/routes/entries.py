# -*- coding: utf-8 -*-
"""Atom Entries & Entry Field Values CRUD API"""

import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import (
    AtomEntry, EntryFieldValue, EntrySchemaField, EntrySchema,
    KnowledgeAtom, CanvasConnection,
)

bp = Blueprint('entries', __name__)


def _write_typed_value(fv, field_type, raw_value):
    """根據 field_type 寫入對應型別欄位，value 永遠存文字版。"""
    fv.value = str(raw_value) if raw_value is not None else None
    fv.value_int = None
    fv.value_decimal = None
    fv.value_date = None
    fv.value_datetime = None

    if raw_value is None or raw_value == '':
        return

    try:
        if field_type in ('number',):
            fv.value_int = int(raw_value)
        elif field_type in ('decimal',):
            fv.value_decimal = Decimal(str(raw_value))
        elif field_type in ('date',):
            fv.value_date = datetime.date.fromisoformat(str(raw_value))
        elif field_type in ('datetime',):
            fv.value_datetime = datetime.datetime.fromisoformat(str(raw_value))
    except (ValueError, InvalidOperation):
        pass  # 保留 value 文字版，型別欄位留 None


def _save_field_values(s, entry, field_values_dict, changed_by='user'):
    """批次寫入 entry 的欄位值。field_values_dict: {field_name: raw_value}"""
    from core.audit import log_field_change
    if not field_values_dict or not entry.schema_id:
        return

    schema_fields = (
        s.query(EntrySchemaField)
        .filter_by(schema_id=entry.schema_id)
        .all()
    )
    field_map = {f.name: f for f in schema_fields}

    for fname, fval in field_values_dict.items():
        if fname not in field_map:
            continue
        sf = field_map[fname]
        new_val = str(fval) if fval is not None else None

        existing = (
            s.query(EntryFieldValue)
            .filter_by(entry_id=entry.id, field_id=sf.id)
            .first()
        )
        if existing:
            log_field_change(s, entry.id, sf.id, existing.value, new_val, changed_by)
            _write_typed_value(existing, sf.field_type, fval)
        else:
            log_field_change(s, entry.id, sf.id, None, new_val, changed_by)
            fv = EntryFieldValue(entry_id=entry.id, field_id=sf.id)
            _write_typed_value(fv, sf.field_type, fval)
            s.add(fv)

    # 進度退回邏輯：從 100% 退回時清空 actual_end
    if 'progress' in field_values_dict or 'status' in field_values_dict:
        progress_val = field_values_dict.get('progress', '')
        status_val = field_values_dict.get('status', '')
        try:
            pct = int(float(progress_val)) if progress_val else -1
        except (ValueError, TypeError):
            pct = -1
        is_done = (pct >= 100) or (status_val == 'done')
        if not is_done and 'actual_end' in field_map:
            ae_field = field_map['actual_end']
            ae_existing = (
                s.query(EntryFieldValue)
                .filter_by(entry_id=entry.id, field_id=ae_field.id)
                .first()
            )
            if ae_existing and ae_existing.value:
                log_field_change(s, entry.id, ae_field.id, ae_existing.value, None, changed_by)
                ae_existing.value = None
                ae_existing.value_datetime = None


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
        texts = []
        for e in sorted(result_entries, key=lambda x: x.sort_order):
            texts.append(e.raw_text)
        atom.content = '\n'.join(texts)
        atom.updated_at = datetime.datetime.now()

        s.flush()
        return jsonify({
            'entries': [_entry_to_dict(e, s) for e in result_entries],
            'content_snapshot': atom.content,
        })
