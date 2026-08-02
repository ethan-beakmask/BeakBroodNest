# -*- coding: utf-8 -*-
"""任務狀態服務層。

本模組是 task entry 狀態轉移與欄位寫入的唯一實作；Flask route 與 MCP
工具都必須呼叫這裡，避免各端各自維護一套任務狀態機。
"""
import datetime
import json
from decimal import Decimal, InvalidOperation

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from core.models import (
    AtomEntry, EntryFieldValue, EntrySchema, EntrySchemaField,
    KnowledgeAtom, UnifiedRelation,
)


TASK_STATUSES = ('planning', 'in_progress', 'paused', 'completed', 'cancelled')
_STATUS_LEGACY = {'pending': 'planning', 'done': 'completed'}
_VALID_ACTIONS = ('pause', 'resume', 'cancel', 'reopen')


class TaskError(Exception):
    """任務業務規則違反。"""


def write_typed_value(fv, field_type, raw_value):
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
        pass


def get_task_schema(s):
    """取得 task schema。"""
    return s.query(EntrySchema).filter_by(code='task').first()


def ensure_freetext_entries(s, atom, changed_by='ai') -> int:
    """確保 atom.content 已轉成自由文字 entries，回傳本次新增筆數。"""
    content = atom.content or ''
    if not content.strip():
        return 0

    freetext_schema = s.query(EntrySchema).filter_by(code='freetext').first()
    if not freetext_schema:
        raise TaskError('找不到 freetext schema，無法補建自由文字 entry')

    has_freetext = (
        s.query(AtomEntry.id)
        .filter(
            AtomEntry.atom_id == atom.id,
            AtomEntry.schema_id == freetext_schema.id,
        )
        .first()
    )
    if has_freetext:
        return 0

    max_order = (
        s.query(func.max(AtomEntry.sort_order))
        .filter_by(atom_id=atom.id)
        .scalar()
    )
    sort_order = (max_order + 1) if max_order is not None else 0
    created = 0
    for line in content.splitlines():
        if not line.strip():
            continue
        entry = AtomEntry(
            atom_id=atom.id,
            schema_id=freetext_schema.id,
            sort_order=sort_order,
            raw_text=line,
            summary='',
        )
        s.add(entry)
        sort_order += 1
        created += 1

    if created:
        atom.updated_at = datetime.datetime.now()
        s.flush()
    return created


def get_task_entry(s, atom_id):
    """取得指定 atom 的 task entry。"""
    task_schema = get_task_schema(s)
    if not task_schema:
        return None, None
    entry = (
        s.query(AtomEntry)
        .filter_by(atom_id=atom_id, schema_id=task_schema.id)
        .first()
    )
    return entry, task_schema


def get_field_map(s, schema_id):
    """取得 schema 欄位對照表。"""
    fields = s.query(EntrySchemaField).filter_by(schema_id=schema_id).all()
    return {f.name: f for f in fields}


def _fv_get(s, entry_id, field_id):
    return (
        s.query(EntryFieldValue)
        .filter_by(entry_id=entry_id, field_id=field_id)
        .first()
    )


def _load_json_field(fv_value, default):
    """安全讀 JSON 欄位：空字串、None、格式錯誤時回 default。"""
    if not fv_value:
        return default
    try:
        return json.loads(fv_value)
    except (ValueError, TypeError):
        return default


def _dump_json_field(obj):
    """寫回 JSON 字串；空 list/dict 寫成空字串。"""
    if obj is None or obj == [] or obj == {}:
        return ''
    return json.dumps(obj, ensure_ascii=False)


def set_field(s, entry, field_map, name, value, changed_by):
    """單欄位更新並記錄 change log。"""
    from core.audit import log_field_change
    sf = field_map.get(name)
    if not sf:
        return
    existing = _fv_get(s, entry.id, sf.id)
    new_val = str(value) if value is not None else None
    if existing:
        log_field_change(s, entry.id, sf.id, existing.value, new_val, changed_by)
        write_typed_value(existing, sf.field_type, value)
    else:
        log_field_change(s, entry.id, sf.id, None, new_val, changed_by)
        fv = EntryFieldValue(entry_id=entry.id, field_id=sf.id)
        write_typed_value(fv, sf.field_type, value)
        s.add(fv)


def save_field_values(s, entry, field_values_dict, changed_by='user'):
    """批次寫入 entry 的欄位值。field_values_dict: {field_name: raw_value}"""
    if not field_values_dict or not entry.schema_id:
        return
    field_map = get_field_map(s, entry.schema_id)

    for fname, fval in field_values_dict.items():
        if fname not in field_map:
            continue
        if fname == 'status' and fval in _STATUS_LEGACY:
            fval = _STATUS_LEGACY[fval]
        set_field(s, entry, field_map, fname, fval, changed_by)

    if 'progress' in field_values_dict or 'status' in field_values_dict:
        progress_val = field_values_dict.get('progress', '')
        status_val = _STATUS_LEGACY.get(
            field_values_dict.get('status', ''),
            field_values_dict.get('status', ''),
        )
        try:
            pct = int(float(progress_val)) if progress_val else -1
        except (ValueError, TypeError):
            pct = -1
        is_done = (pct >= 100) or (status_val == 'completed')
        if not is_done and 'actual_end' in field_map:
            ae_field = field_map['actual_end']
            ae_existing = _fv_get(s, entry.id, ae_field.id)
            if ae_existing and ae_existing.value:
                set_field(s, entry, field_map, 'actual_end', None, changed_by)


def _field_values_dict(s, entry):
    refreshed = (
        s.query(EntryFieldValue)
        .options(joinedload(EntryFieldValue.field))
        .filter_by(entry_id=entry.id)
        .all()
    )
    return {fv.field.name: fv.value for fv in refreshed if fv.field}


def create_task_entry(s, atom, field_values: dict, changed_by='ai') -> AtomEntry:
    """替 atom 建立 task entry；已存在時直接回傳既有 entry。"""
    entry, task_schema = get_task_entry(s, atom.id)
    if entry:
        return entry
    if not task_schema:
        raise TaskError('找不到 task schema，無法建立待辦')

    max_order = (
        s.query(func.max(AtomEntry.sort_order))
        .filter_by(atom_id=atom.id)
        .scalar()
    )
    entry = AtomEntry(
        atom_id=atom.id,
        schema_id=task_schema.id,
        sort_order=(max_order + 1) if max_order is not None else 0,
        raw_text='',
        summary='',
    )
    s.add(entry)
    s.flush()
    save_field_values(s, entry, field_values or {}, changed_by)
    return entry


def apply_action(s, atom_id, action, reason='', changed_by='ai') -> dict:
    """執行 pause / resume / cancel / reopen 狀態轉移。"""
    if action not in _VALID_ACTIONS:
        raise TaskError(f'action 必須是 {_VALID_ACTIONS}')

    entry, task_schema = get_task_entry(s, atom_id)
    if not entry:
        raise TaskError('此原子沒有 task entry')
    field_map = get_field_map(s, task_schema.id)
    status_field = field_map.get('status')
    if not status_field:
        raise TaskError('task schema 缺 status 欄位')

    current_status_fv = _fv_get(s, entry.id, status_field.id)
    current_status = (current_status_fv.value if current_status_fv else '') or 'planning'
    now_iso = datetime.datetime.now().isoformat(timespec='seconds')
    reason = (reason or '').strip()

    if action == 'pause':
        if current_status != 'in_progress':
            raise TaskError(f'只能從 in_progress 暫停，目前狀態：{current_status}')
        log_fv = _fv_get(s, entry.id, field_map['pause_log'].id) if 'pause_log' in field_map else None
        arr = _load_json_field(log_fv.value if log_fv else None, [])
        arr.append({'paused_at': now_iso, 'resumed_at': None, 'reason': reason})
        set_field(s, entry, field_map, 'pause_log', _dump_json_field(arr), changed_by)
        set_field(s, entry, field_map, 'status', 'paused', changed_by)

    elif action == 'resume':
        if current_status != 'paused':
            raise TaskError(f'只能從 paused 恢復，目前狀態：{current_status}')
        log_fv = _fv_get(s, entry.id, field_map['pause_log'].id) if 'pause_log' in field_map else None
        arr = _load_json_field(log_fv.value if log_fv else None, [])
        for item in reversed(arr):
            if item.get('resumed_at') is None:
                item['resumed_at'] = now_iso
                if reason:
                    item['resume_reason'] = reason
                break
        set_field(s, entry, field_map, 'pause_log', _dump_json_field(arr), changed_by)
        set_field(s, entry, field_map, 'status', 'in_progress', changed_by)

    elif action == 'cancel':
        if current_status in ('cancelled',):
            raise TaskError('已經是 cancelled')
        cancel_info = {'cancelled_at': now_iso, 'reason': reason}
        set_field(s, entry, field_map, 'cancel_info', _dump_json_field(cancel_info), changed_by)
        set_field(s, entry, field_map, 'status', 'cancelled', changed_by)

    elif action == 'reopen':
        if current_status not in ('completed', 'cancelled'):
            raise TaskError(f'只能從 completed / cancelled 重啟，目前狀態：{current_status}')
        log_fv = _fv_get(s, entry.id, field_map['reopen_log'].id) if 'reopen_log' in field_map else None
        arr = _load_json_field(log_fv.value if log_fv else None, [])
        arr.append({'reopened_at': now_iso, 'reason': reason, 'from_status': current_status})
        set_field(s, entry, field_map, 'reopen_log', _dump_json_field(arr), changed_by)
        set_field(s, entry, field_map, 'status', 'in_progress', changed_by)
        if 'actual_end' in field_map:
            ae_fv = _fv_get(s, entry.id, field_map['actual_end'].id)
            if ae_fv and ae_fv.value:
                set_field(s, entry, field_map, 'actual_end', '', changed_by)
        if current_status == 'cancelled' and 'cancel_info' in field_map:
            set_field(s, entry, field_map, 'cancel_info', '', changed_by)

    atom = s.get(KnowledgeAtom, atom_id)
    if atom:
        atom.updated_at = datetime.datetime.now()
    s.flush()

    return {
        'ok': True,
        'atom_id': atom_id,
        'entry_id': entry.id,
        'action': action,
        'new_status': 'paused' if action == 'pause'
                      else 'cancelled' if action == 'cancel'
                      else 'in_progress',
        'field_values': _field_values_dict(s, entry),
    }


def update_task_fields(s, atom_id, values: dict, changed_by='ai') -> dict:
    """更新 task 欄位；status 不在此處處理。"""
    entry, task_schema = get_task_entry(s, atom_id)
    if not entry:
        raise TaskError('此原子沒有 task entry')
    field_map = get_field_map(s, task_schema.id)
    clean = {k: v for k, v in (values or {}).items() if k != 'status' and k in field_map}
    for name, value in clean.items():
        set_field(s, entry, field_map, name, value, changed_by)
    atom = s.get(KnowledgeAtom, atom_id)
    if atom:
        atom.updated_at = datetime.datetime.now()
    s.flush()
    return {
        'atom_id': atom_id,
        'entry_id': entry.id,
        'field_values': _field_values_dict(s, entry),
    }


def unfinished_children(s, atom_id) -> list[dict]:
    """列出 contains 子卡中尚未完成的項目。"""
    rels = (
        s.query(UnifiedRelation)
        .filter(
            UnifiedRelation.from_atom_id == atom_id,
            UnifiedRelation.relation_type == 'contains',
            UnifiedRelation.is_deleted == False,
            UnifiedRelation.to_atom_id.isnot(None),
        )
        .all()
    )
    out = []
    for rel in rels:
        child = s.get(KnowledgeAtom, rel.to_atom_id)
        if not child or child.is_deleted:
            continue
        entry, schema = get_task_entry(s, child.id)
        status = None
        if entry and schema:
            field_map = get_field_map(s, schema.id)
            status_field = field_map.get('status')
            if status_field:
                fv = _fv_get(s, entry.id, status_field.id)
                status = (fv.value if fv else '') or 'planning'
        if status in ('completed', 'cancelled'):
            continue
        out.append({
            'atom_id': child.id,
            'ref_code': child.ref_code,
            'title': child.title,
            'status': status,
        })
    return out


def complete_task(s, atom_id, changed_by='ai') -> dict:
    """完成 task；若有未完成子任務則拒絕。"""
    children = unfinished_children(s, atom_id)
    if children:
        parts = [
            f"{c.get('ref_code') or 'a' + str(c['atom_id'])} {c.get('title') or ''}".strip()
            for c in children
        ]
        raise TaskError('仍有未完成子任務，不能完成此待辦：' + '、'.join(parts))

    entry, task_schema = get_task_entry(s, atom_id)
    if not entry:
        raise TaskError('此原子沒有 task entry')
    field_map = get_field_map(s, task_schema.id)
    now_iso = datetime.datetime.now().isoformat(timespec='seconds')
    set_field(s, entry, field_map, 'status', 'completed', changed_by)
    ae_fv = _fv_get(s, entry.id, field_map['actual_end'].id) if 'actual_end' in field_map else None
    if 'actual_end' in field_map and (not ae_fv or not ae_fv.value):
        set_field(s, entry, field_map, 'actual_end', now_iso, changed_by)
    atom = s.get(KnowledgeAtom, atom_id)
    if atom:
        atom.updated_at = datetime.datetime.now()
    s.flush()
    return {
        'ok': True,
        'atom_id': atom_id,
        'entry_id': entry.id,
        'action': 'complete',
        'new_status': 'completed',
        'field_values': _field_values_dict(s, entry),
    }
