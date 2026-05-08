# -*- coding: utf-8 -*-
"""行事曆：以 entry.planned_start 為資料來源的年/月/日視角"""

import datetime
from flask import Blueprint, jsonify, request, render_template
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import (
    Canvas, CanvasAtom, AtomEntry, EntrySchemaField, EntryFieldValue,
)

bp = Blueprint('calendar', __name__)


@bp.route('/calendar')
def calendar_page():
    return render_template('calendar.html')


@bp.route('/calendar/api/canvases')
def calendar_canvases():
    """列出所有未歸檔白板，含 is_project 旗標"""
    with session_scope() as s:
        rows = (
            s.query(Canvas)
            .filter(Canvas.is_archived == False)
            .order_by(Canvas.is_project.desc(), Canvas.name)
            .all()
        )
        return jsonify([
            {
                'slug': c.slug,
                'name': c.name,
                'is_project': c.is_project,
            }
            for c in rows
        ])


def _parse_date(s, default):
    if not s:
        return default
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return default


@bp.route('/calendar/api/events')
def calendar_events():
    """查詢區間內具備 planned_start 的 entries

    參數：
      from, to: YYYY-MM-DD（含端點）
      include_project: '1'/'0'（預設 1）
      include_free: '1'/'0'（預設 1）
      canvas_slugs: 逗號分隔，若有則取交集
    """
    today = datetime.date.today()
    d_from = _parse_date(request.args.get('from'), today.replace(day=1))
    d_to = _parse_date(
        request.args.get('to'),
        (d_from.replace(day=28) + datetime.timedelta(days=10)).replace(day=1)
        - datetime.timedelta(days=1),
    )
    if d_to < d_from:
        d_from, d_to = d_to, d_from

    include_project = request.args.get('include_project', '1') == '1'
    include_free = request.args.get('include_free', '1') == '1'
    slug_filter = request.args.get('canvas_slugs', '').strip()
    slug_set = set(s.strip() for s in slug_filter.split(',') if s.strip()) if slug_filter else None

    dt_from = datetime.datetime.combine(d_from, datetime.time.min)
    dt_to = datetime.datetime.combine(d_to, datetime.time.max)

    with session_scope() as s:
        # 找 planned_start field id（多 schema 可能各有同名欄位）
        field_ids = [
            row[0] for row in
            s.query(EntrySchemaField.id)
            .filter(EntrySchemaField.name == 'planned_start')
            .all()
        ]
        if not field_ids:
            return jsonify({'events': [], 'range': {'from': d_from.isoformat(), 'to': d_to.isoformat()}})

        # 取出在區間內、有 value_datetime 的 entry field values
        fv_rows = (
            s.query(EntryFieldValue)
            .filter(
                EntryFieldValue.field_id.in_(field_ids),
                EntryFieldValue.value_datetime != None,  # noqa: E711
                EntryFieldValue.value_datetime >= dt_from,
                EntryFieldValue.value_datetime <= dt_to,
            )
            .all()
        )
        if not fv_rows:
            return jsonify({'events': [], 'range': {'from': d_from.isoformat(), 'to': d_to.isoformat()}})

        entry_ids = list({fv.entry_id for fv in fv_rows})
        entries = (
            s.query(AtomEntry)
            .options(joinedload(AtomEntry.atom))
            .filter(AtomEntry.id.in_(entry_ids))
            .all()
        )
        atom_ids = list({e.atom_id for e in entries})

        # 取每個 atom 所屬的 canvas（同一 atom 可能在多張 canvas 上，取最新更新者）
        ca_rows = (
            s.query(CanvasAtom, Canvas)
            .join(Canvas, Canvas.id == CanvasAtom.canvas_id)
            .filter(CanvasAtom.atom_id.in_(atom_ids), Canvas.is_archived == False)
            .order_by(Canvas.updated_at.desc())
            .all()
        )
        atom_canvas = {}
        for ca, canvas in ca_rows:
            if ca.atom_id not in atom_canvas:
                atom_canvas[ca.atom_id] = canvas

        # 同 entry 也可能拿到同 field 多筆（理論上 unique），取第一筆
        entry_start = {}
        for fv in fv_rows:
            entry_start.setdefault(fv.entry_id, fv.value_datetime)

        # 取 status / urgency / planned_end 補資訊
        info_field_names = {'status', 'urgency', 'planned_end'}
        info_field_ids = [
            row[0] for row in
            s.query(EntrySchemaField.id)
            .filter(EntrySchemaField.name.in_(info_field_names))
            .all()
        ]
        info_rows = (
            s.query(EntryFieldValue)
            .options(joinedload(EntryFieldValue.field))
            .filter(
                EntryFieldValue.entry_id.in_(entry_ids),
                EntryFieldValue.field_id.in_(info_field_ids),
            )
            .all()
        ) if info_field_ids else []
        entry_info = {}
        for fv in info_rows:
            if not fv.field:
                continue
            entry_info.setdefault(fv.entry_id, {})[fv.field.name] = fv.value

        events = []
        for entry in entries:
            canvas = atom_canvas.get(entry.atom_id)
            if not canvas:
                continue
            if canvas.is_project and not include_project:
                continue
            if (not canvas.is_project) and not include_free:
                continue
            if slug_set is not None and canvas.slug not in slug_set:
                continue

            start_dt = entry_start.get(entry.id)
            if not start_dt:
                continue

            info = entry_info.get(entry.id, {})
            title = entry.atom.title if entry.atom else ''
            if not title:
                title = (entry.summary or entry.raw_text or '')[:60]

            events.append({
                'entry_id': entry.id,
                'atom_id': entry.atom_id,
                'title': title,
                'date': start_dt.date().isoformat(),
                'datetime': start_dt.isoformat(),
                'canvas_slug': canvas.slug,
                'canvas_name': canvas.name,
                'is_project': canvas.is_project,
                'status': info.get('status', ''),
                'urgency': info.get('urgency', ''),
                'planned_end': info.get('planned_end', ''),
            })

        events.sort(key=lambda x: (x['date'], x['title']))
        return jsonify({
            'events': events,
            'range': {'from': d_from.isoformat(), 'to': d_to.isoformat()},
        })
