# -*- coding: utf-8 -*-
"""統一 task entries 查詢 helper

union 兩個資料源：
  1) atom_entries (schema=task)：卡片內部 task entry，
     field_values 走 normalized 表 entry_field_values
  2) standalone_entries (schema_code=task)：白板獨立 task entry，
     field_values 是 JSONB dict

輸出統一 dict 格式給 /calendar /project /todos 共用。
"""
from __future__ import annotations

from typing import Iterable
from sqlalchemy.orm import joinedload

from core.models import (
    Canvas, CanvasAtom, CanvasStandaloneEntry,
    AtomEntry, EntrySchema, EntrySchemaField, EntryFieldValue,
    StandaloneEntry, KnowledgeAtom,
)


# 哪些 field 要從 entry_field_values 撈出來合進 unified field_values dict
TASK_FIELD_NAMES = (
    'urgency', 'category', 'planned_start', 'planned_duration',
    'actual_start', 'actual_end', 'status', 'baseline_start',
    'baseline_end', 'progress', 'planned_end', 'location',
    'attendees', 'note', 'pause_log', 'cancel_info', 'reopen_log',
)


def _atom_entry_field_values_map(s, entry_ids: Iterable[int]) -> dict:
    """批次取 atom_entry 的 field_values，回 {entry_id: {field_name: str_value}}

    value_datetime 優先，其次 value，統一成字串輸出與 standalone 對齊。
    """
    entry_ids = list(entry_ids)
    if not entry_ids:
        return {}
    rows = (
        s.query(EntryFieldValue)
        .options(joinedload(EntryFieldValue.field))
        .filter(EntryFieldValue.entry_id.in_(entry_ids))
        .all()
    )
    result: dict[int, dict[str, str]] = {}
    for fv in rows:
        if not fv.field:
            continue
        name = fv.field.name
        # 統一輸出字串（standalone 的 JSONB 也是字串）
        if fv.value_datetime is not None:
            val = fv.value_datetime.isoformat()
        elif fv.value_date is not None:
            val = fv.value_date.isoformat()
        elif fv.value is not None:
            val = fv.value
        elif fv.value_int is not None:
            val = str(fv.value_int)
        elif fv.value_decimal is not None:
            val = str(fv.value_decimal)
        else:
            val = ''
        result.setdefault(fv.entry_id, {})[name] = val
    return result


def _canvas_for_atoms(s, atom_ids: Iterable[int]) -> dict:
    """{atom_id: (canvas, canvas_atom_pos_x, pos_y)}，同 atom 在多白板取最新更新者"""
    atom_ids = list(atom_ids)
    if not atom_ids:
        return {}
    rows = (
        s.query(CanvasAtom, Canvas)
        .join(Canvas, Canvas.id == CanvasAtom.canvas_id)
        .filter(CanvasAtom.atom_id.in_(atom_ids), Canvas.is_archived == False)  # noqa: E712
        .order_by(Canvas.updated_at.desc())
        .all()
    )
    out: dict[int, tuple[Canvas, float, float]] = {}
    for ca, canvas in rows:
        if ca.atom_id not in out:
            out[ca.atom_id] = (canvas, ca.pos_x, ca.pos_y)
    return out


def _canvas_for_standalones(s, se_ids: Iterable[int]) -> dict:
    """{standalone_entry_id: (canvas, cse_id, pos_x, pos_y)}

    P3a UNIQUE(canvas_id, entry_id) 確保 1:1，但同 entry 跨白板 placement 仍可能多筆，
    這裡選最新更新的 canvas（與 atom 行為對齊）。
    """
    se_ids = list(se_ids)
    if not se_ids:
        return {}
    rows = (
        s.query(CanvasStandaloneEntry, Canvas)
        .join(Canvas, Canvas.id == CanvasStandaloneEntry.canvas_id)
        .filter(
            CanvasStandaloneEntry.standalone_entry_id.in_(se_ids),
            Canvas.is_archived == False,  # noqa: E712
        )
        .order_by(Canvas.updated_at.desc())
        .all()
    )
    out: dict[int, tuple[Canvas, int, float, float]] = {}
    for cse, canvas in rows:
        if cse.standalone_entry_id not in out:
            out[cse.standalone_entry_id] = (canvas, cse.id, cse.pos_x, cse.pos_y)
    return out


def query_task_entries(
    s,
    canvas_ids: Iterable[int] | None = None,
    only_no_planned_start: bool = False,
    only_with_planned_start: bool = False,
    include_done: bool = True,
) -> list[dict]:
    """查詢所有 task entries（atom_entries + standalone_entries），輸出統一格式。

    Args:
      s: session
      canvas_ids: 限制白板範圍（None = 全部）
      only_no_planned_start: 只取 planned_start 空值（/todos 用）
      only_with_planned_start: 只取 planned_start 有值（/calendar 用）
      include_done: 是否包含 status=completed/cancelled

    Returns: list of dict，每筆含：
      source: 'atom_entry' | 'standalone_entry'
      entry_id, atom_id (atom_entry only), node_id
      canvas_id, canvas_slug, canvas_name, canvas_is_project
      pos_x, pos_y
      title (atom.title 或 raw_text 開頭)
      raw_text, summary
      schema_code, schema_icon, schema_color, schema_name
      field_values: dict (urgency/category/planned_start/...)
      status, urgency, planned_start, planned_end
      created_at, updated_at
    """
    task_schema = s.query(EntrySchema).filter_by(code='task').first()
    if not task_schema:
        return []

    canvas_id_set = set(canvas_ids) if canvas_ids is not None else None
    schema_info = {
        'schema_code': task_schema.code,
        'schema_name': task_schema.name,
        'schema_icon': task_schema.icon or '',
        'schema_color': task_schema.color or '',
    }

    items: list[dict] = []

    # ----- atom_entries -----
    ae_q = s.query(AtomEntry).options(joinedload(AtomEntry.atom)).filter(
        AtomEntry.schema_id == task_schema.id,
    )
    if canvas_id_set is not None:
        atom_ids_in_canvas = [
            row[0] for row in
            s.query(CanvasAtom.atom_id)
            .filter(CanvasAtom.canvas_id.in_(canvas_id_set))
            .all()
        ]
        if not atom_ids_in_canvas:
            atom_ids_in_canvas = [-1]
        ae_q = ae_q.filter(AtomEntry.atom_id.in_(atom_ids_in_canvas))

    atom_entries = ae_q.all()
    if atom_entries:
        ae_fv_map = _atom_entry_field_values_map(s, [e.id for e in atom_entries])
        atom_canvas = _canvas_for_atoms(s, [e.atom_id for e in atom_entries])

        for ae in atom_entries:
            if not ae.atom or ae.atom.is_deleted:
                continue
            canvas_info = atom_canvas.get(ae.atom_id)
            if canvas_info is None:
                continue  # 此 atom 沒有有效白板 placement
            canvas, pos_x, pos_y = canvas_info
            if canvas_id_set is not None and canvas.id not in canvas_id_set:
                continue

            fv = ae_fv_map.get(ae.id, {})
            ps = fv.get('planned_start', '').strip()
            status = fv.get('status', 'planning')

            if only_no_planned_start and ps:
                continue
            if only_with_planned_start and not ps:
                continue
            if not include_done and status in ('completed', 'cancelled'):
                continue

            title = ae.atom.title or ''
            items.append({
                'source': 'atom_entry',
                'entry_id': ae.id,
                'atom_id': ae.atom_id,
                'node_id': None,
                'canvas_id': canvas.id,
                'canvas_slug': canvas.slug,
                'canvas_name': canvas.name,
                'canvas_is_project': canvas.is_project,
                'pos_x': pos_x,
                'pos_y': pos_y,
                'title': title,
                'raw_text': ae.raw_text or '',
                'summary': ae.summary or '',
                **schema_info,
                'field_values': fv,
                'status': status,
                'urgency': fv.get('urgency', 'M'),
                'planned_start': ps,
                'planned_end': fv.get('planned_end', ''),
                'created_at': ae.created_at.isoformat() if ae.created_at else None,
                'updated_at': ae.updated_at.isoformat() if ae.updated_at else None,
            })

    # ----- standalone_entries -----
    se_q = s.query(StandaloneEntry).filter(
        StandaloneEntry.is_deleted == False,  # noqa: E712
        StandaloneEntry.schema_id == task_schema.id,
    )
    standalone_entries = se_q.all()
    if standalone_entries:
        se_canvas = _canvas_for_standalones(s, [e.id for e in standalone_entries])

        for se in standalone_entries:
            canvas_info = se_canvas.get(se.id)
            if canvas_info is None:
                continue  # 沒有白板 placement 的獨立 entry 跳過（理論上不應發生）
            canvas, cse_id, pos_x, pos_y = canvas_info
            if canvas_id_set is not None and canvas.id not in canvas_id_set:
                continue

            fv = dict(se.field_values or {})
            # standalone 的 field_values 值可能是 None / 數字，全轉字串方便上層
            for k, v in list(fv.items()):
                if v is None:
                    fv[k] = ''
                elif not isinstance(v, str):
                    fv[k] = str(v)

            ps = fv.get('planned_start', '').strip()
            status = fv.get('status', 'planning')

            if only_no_planned_start and ps:
                continue
            if only_with_planned_start and not ps:
                continue
            if not include_done and status in ('completed', 'cancelled'):
                continue

            title = (se.summary or '').strip() or (se.raw_text or '').strip()[:80] or f'#se{se.id}'
            items.append({
                'source': 'standalone_entry',
                'entry_id': se.id,
                'atom_id': None,
                'cse_id': cse_id,
                'node_id': se.node_id,
                'canvas_id': canvas.id,
                'canvas_slug': canvas.slug,
                'canvas_name': canvas.name,
                'canvas_is_project': canvas.is_project,
                'pos_x': pos_x,
                'pos_y': pos_y,
                'title': title,
                'raw_text': se.raw_text or '',
                'summary': se.summary or '',
                **schema_info,
                'field_values': fv,
                'status': status,
                'urgency': fv.get('urgency', 'M'),
                'planned_start': ps,
                'planned_end': fv.get('planned_end', ''),
                'created_at': se.created_at.isoformat() if se.created_at else None,
                'updated_at': se.updated_at.isoformat() if se.updated_at else None,
            })

    return items
