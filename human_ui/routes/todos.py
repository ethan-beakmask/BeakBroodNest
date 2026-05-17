# -*- coding: utf-8 -*-
"""待辦頁：所有 task entry 中無 planned_start 者（含卡片內 + 白板獨立）

對稱於 /calendar：
  /calendar  -> 有 planned_start 的 task entry（含時間軸視圖）
  /todos     -> 無 planned_start 的 task entry（純列表）

;;td 與 ;;cal 是同一個 task schema，差別僅在 field_values.planned_start 有無值。
加上 planned_start 自動歸 /calendar，移除自動歸 /todos。
"""
from __future__ import annotations

import logging
from flask import Blueprint, jsonify, request, render_template

from core.db import session_scope
from core.models import (
    Canvas, CanvasAtom, AtomEntry, EntrySchema, EntryFieldValue, EntrySchemaField,
    StandaloneEntry, CanvasStandaloneEntry, KnowledgeAtom,
)
from core.task_query import query_task_entries

bp = Blueprint('todos', __name__)
logger = logging.getLogger('beak_broodnest')


@bp.route('/todos')
def todos_page():
    return render_template('todos.html')


@bp.route('/todos/api/canvases')
def todos_canvases():
    """列未歸檔白板，與 calendar 對稱"""
    with session_scope() as s:
        rows = (
            s.query(Canvas)
            .filter(Canvas.is_archived == False)  # noqa: E712
            .order_by(Canvas.is_project.desc(), Canvas.name)
            .all()
        )
        return jsonify([
            {'slug': c.slug, 'name': c.name, 'is_project': c.is_project}
            for c in rows
        ])


@bp.route('/todos/api/items')
def todos_items():
    """查無 planned_start 的 task entries（卡片 + 白板獨立）

    參數：
      include_project: '1'/'0'（預設 1）
      include_free: '1'/'0'（預設 1）
      canvas_slug: 限制單一白板
      include_done: '1'/'0'（預設 0）
      order: 'asc'|'desc'（依 entry_id；預設 desc）
    """
    include_project = request.args.get('include_project', '1') == '1'
    include_free = request.args.get('include_free', '1') == '1'
    include_done = request.args.get('include_done', '0') == '1'
    canvas_slug = (request.args.get('canvas_slug') or '').strip()
    order = request.args.get('order', 'desc')

    with session_scope() as s:
        canvas_ids = None
        if canvas_slug:
            c = s.query(Canvas).filter(Canvas.slug == canvas_slug).first()
            if not c:
                return jsonify({'items': [], 'canvas': None})
            canvas_ids = [c.id]

        items = query_task_entries(
            s,
            canvas_ids=canvas_ids,
            only_no_planned_start=True,
            include_done=include_done,
        )

        # is_project / is_free 過濾
        items = [
            it for it in items
            if (it['canvas_is_project'] and include_project)
            or ((not it['canvas_is_project']) and include_free)
        ]

        # 排序：依 entry_id（atom_entry 用 entry_id；standalone 用 entry_id），可選方向
        reverse = (order != 'asc')
        items.sort(key=lambda x: x['entry_id'], reverse=reverse)

        canvas_info = None
        if canvas_slug:
            cv = s.query(Canvas).filter(Canvas.slug == canvas_slug).first()
            if cv:
                canvas_info = {'slug': cv.slug, 'name': cv.name, 'is_project': cv.is_project}

        return jsonify({'items': items, 'canvas': canvas_info})


@bp.route('/todos/api/delete', methods=['POST'])
def todos_delete():
    """批次刪除：
      items: [{source: 'atom_entry'|'standalone_entry', id: int}, ...]

    atom_entry: 軟刪整個 atom（atom.is_deleted=True）
    standalone_entry: 軟刪 standalone entry
    """
    data = request.get_json(silent=True) or {}
    raw_items = data.get('items') or []
    if not isinstance(raw_items, list) or len(raw_items) > 200:
        return jsonify({'error': 'items 須為 list 且不超過 200'}), 400

    atom_ids = []
    se_ids = []
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        src = it.get('source')
        i = it.get('id')
        if not isinstance(i, int):
            continue
        if src == 'atom_entry':
            atom_ids.append(i)
        elif src == 'standalone_entry':
            se_ids.append(i)

    with session_scope() as s:
        deleted_atom = 0
        deleted_se = 0
        if atom_ids:
            # 取 atom（透過 atom_entries entry_id 反查）
            ae_rows = (
                s.query(AtomEntry)
                .filter(AtomEntry.id.in_(atom_ids))
                .all()
            )
            target_atom_ids = {e.atom_id for e in ae_rows}
            for atom in s.query(KnowledgeAtom).filter(KnowledgeAtom.id.in_(target_atom_ids)).all():
                if not atom.is_deleted:
                    atom.is_deleted = True
                    deleted_atom += 1

        if se_ids:
            for se in s.query(StandaloneEntry).filter(StandaloneEntry.id.in_(se_ids)).all():
                if not se.is_deleted:
                    se.is_deleted = True
                    deleted_se += 1
            # 清 placement
            s.query(CanvasStandaloneEntry).filter(
                CanvasStandaloneEntry.standalone_entry_id.in_(se_ids)
            ).delete(synchronize_session=False)

        logger.info(f'/todos delete: atoms={deleted_atom} standalones={deleted_se}')
        return jsonify({
            'deleted_atoms': deleted_atom,
            'deleted_standalone_entries': deleted_se,
        })


@bp.route('/todos/api/move', methods=['POST'])
def todos_move():
    """批次移動 placement 到指定白板：
      items: [{source, id, source_canvas_slug}, ...]
      target_canvas_slug: str

    atom_entry: 移該 atom 在來源白板的 CanvasAtom 到目標白板（多 placement 只動來源）
    standalone_entry: 移 CanvasStandaloneEntry
    """
    data = request.get_json(silent=True) or {}
    raw_items = data.get('items') or []
    target_slug = (data.get('target_canvas_slug') or '').strip()
    if not target_slug:
        return jsonify({'error': 'target_canvas_slug 必填'}), 400
    if not isinstance(raw_items, list) or len(raw_items) > 200:
        return jsonify({'error': 'items 須為 list 且不超過 200'}), 400

    with session_scope() as s:
        target = s.query(Canvas).filter(Canvas.slug == target_slug).first()
        if not target:
            return jsonify({'error': f'目標白板不存在: {target_slug}'}), 404

        moved_atom = 0
        moved_se = 0
        skipped = []

        for it in raw_items:
            if not isinstance(it, dict):
                continue
            src = it.get('source')
            i = it.get('id')
            src_slug = (it.get('source_canvas_slug') or '').strip()
            if not isinstance(i, int):
                continue

            if src == 'atom_entry':
                ae = s.get(AtomEntry, i)
                if not ae:
                    skipped.append({'source': src, 'id': i, 'reason': 'entry 不存在'})
                    continue
                # 找來源白板 placement
                q = s.query(CanvasAtom).filter(CanvasAtom.atom_id == ae.atom_id)
                if src_slug:
                    src_canvas = s.query(Canvas).filter(Canvas.slug == src_slug).first()
                    if src_canvas:
                        q = q.filter(CanvasAtom.canvas_id == src_canvas.id)
                placement = q.first()
                if not placement:
                    skipped.append({'source': src, 'id': i, 'reason': '無 placement'})
                    continue
                if placement.canvas_id == target.id:
                    continue
                # 檢查目標是否已有同 atom placement
                existing = s.query(CanvasAtom).filter(
                    CanvasAtom.canvas_id == target.id,
                    CanvasAtom.atom_id == ae.atom_id,
                ).first()
                if existing:
                    # 已存在 → 刪來源
                    s.delete(placement)
                else:
                    placement.canvas_id = target.id
                moved_atom += 1

            elif src == 'standalone_entry':
                q = s.query(CanvasStandaloneEntry).filter(
                    CanvasStandaloneEntry.standalone_entry_id == i
                )
                if src_slug:
                    src_canvas = s.query(Canvas).filter(Canvas.slug == src_slug).first()
                    if src_canvas:
                        q = q.filter(CanvasStandaloneEntry.canvas_id == src_canvas.id)
                placement = q.first()
                if not placement:
                    skipped.append({'source': src, 'id': i, 'reason': '無 placement'})
                    continue
                if placement.canvas_id == target.id:
                    continue
                existing = s.query(CanvasStandaloneEntry).filter(
                    CanvasStandaloneEntry.canvas_id == target.id,
                    CanvasStandaloneEntry.standalone_entry_id == i,
                ).first()
                if existing:
                    s.delete(placement)
                else:
                    placement.canvas_id = target.id
                moved_se += 1

        logger.info(
            f'/todos move: atoms={moved_atom} standalones={moved_se} '
            f'target={target_slug} skipped={len(skipped)}'
        )
        return jsonify({
            'moved_atoms': moved_atom,
            'moved_standalone_entries': moved_se,
            'skipped': skipped,
            'target_canvas': {'slug': target.slug, 'name': target.name},
        })
