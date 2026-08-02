# -*- coding: utf-8 -*-
"""MCP 待辦任務工具。"""
import datetime
import json

from sqlalchemy import func

from core.db import session_scope
from core.models import Canvas, CanvasAtom, KnowledgeAtom, Tag
from core import relations as rel_service
from core.ref_code import assign_ref_code, resolve_ref
from core.task_service import (
    TaskError, apply_action, complete_task, create_task_entry,
    ensure_freetext_entries, get_field_map, get_task_entry, set_field,
    unfinished_children, update_task_fields,
)
from ai_kb.tools.project import _find_canvas_by_cwd


def _error(message: str) -> str:
    return json.dumps({'error': message}, ensure_ascii=False)


def _resolve_project(s, project, parent_atom=None) -> Canvas:
    """依專案代號、白板 slug 或專案路徑解析白板。"""
    project = (project or '').strip()
    canvas = None

    if project:
        if project.startswith('/'):
            canvas = _find_canvas_by_cwd(s, project)
        else:
            canvas = (
                s.query(Canvas)
                .filter(
                    func.upper(Canvas.code) == project.upper(),
                    Canvas.is_archived == False,  # noqa: E712
                )
                .first()
            )
            if not canvas:
                canvas = (
                    s.query(Canvas)
                    .filter(Canvas.slug == project, Canvas.is_archived == False)  # noqa: E712
                    .first()
                )
    elif parent_atom is not None and parent_atom.project_canvas_id:
        canvas = s.get(Canvas, parent_atom.project_canvas_id)
    else:
        raise TaskError('必須指定 project（專案代號 / 白板 slug / 專案目錄路徑）')

    if not canvas:
        raise TaskError(f'找不到專案白板：{project}')
    if not canvas.code:
        raise TaskError(f'白板「{canvas.name}」尚未設定專案代號，無法發短代號')
    return canvas


def _ensure_canvas_atom(s, canvas_id: int, atom_id: int) -> CanvasAtom:
    existing = (
        s.query(CanvasAtom)
        .filter_by(canvas_id=canvas_id, atom_id=atom_id)
        .first()
    )
    if existing:
        return existing
    max_y = s.query(func.max(CanvasAtom.pos_y)).filter_by(canvas_id=canvas_id).scalar()
    ca = CanvasAtom(
        canvas_id=canvas_id,
        atom_id=atom_id,
        pos_x=0,
        pos_y=(max_y + 160) if max_y is not None else 0,
    )
    s.add(ca)
    s.flush()
    return ca


def _create_relation_once(s, from_atom_id: int, to_atom_id: int, relation_type: str):
    from core.models import UnifiedRelation
    existing = (
        s.query(UnifiedRelation)
        .filter(
            UnifiedRelation.from_atom_id == from_atom_id,
            UnifiedRelation.to_atom_id == to_atom_id,
            UnifiedRelation.relation_type == relation_type,
            UnifiedRelation.is_deleted == False,  # noqa: E712
        )
        .first()
    )
    if existing:
        return existing
    return rel_service.create_relation(
        s,
        relation_type=relation_type,
        from_atom_id=from_atom_id,
        to_atom_id=to_atom_id,
        created_by='ai',
    )


def _attach_tags(s, atom, tags):
    if not tags:
        return
    tag_objects = []
    for tag_name in tags:
        if not tag_name:
            continue
        tag = s.query(Tag).filter(Tag.name == tag_name).first()
        if not tag:
            tag = Tag(name=tag_name, tag_type='tag')
            s.add(tag)
            s.flush()
        tag_objects.append(tag)
    atom.tags = tag_objects


def _current_status(s, entry, field_map):
    sf = field_map.get('status')
    if not sf:
        raise TaskError('task schema 缺 status 欄位')
    for fv in entry.field_values:
        if fv.field_id == sf.id:
            return (fv.value or '').strip() or 'planning'
    return 'planning'


def _resolve_task_entry(s, ref: str):
    atom = resolve_ref(s, ref)
    if not atom:
        raise TaskError(f'找不到卡片：{ref}')
    entry, schema = get_task_entry(s, atom.id)
    if not entry:
        raise TaskError(f'卡片 {atom.ref_code or atom.id} 沒有 task entry')
    return atom, entry, schema


def _task_response(atom, result) -> str:
    field_values = result.get('field_values', {})
    return json.dumps({
        'ref_code': atom.ref_code,
        'atom_id': atom.id,
        'status': field_values.get('status', 'planning'),
        'field_values': field_values,
    }, ensure_ascii=False, default=str)


def register(mcp):

    @mcp.tool()
    def note_task_create(
        title: str,
        content: str = '',
        project: str = '',
        parent_ref: str = '',
        urgency: str = 'M',
        planned_start: str = '',
        planned_duration: str = '',
        note: str = '',
        tags: list[str] | None = None,
    ) -> str:
        """AI 建立待辦的唯一入口。

        建出的待辦會直接出現在人類的 /todos 頁面。不要再用 note_store 搭配
        [待辦] 標題前綴或待辦標籤建立假待辦，舊寫法不會進入權威待辦清單。

        project 可填專案代號、白板 slug 或本地專案目錄路徑。parent_ref 可填母待辦短代號。
        """
        try:
            with session_scope() as s:
                parent_atom = resolve_ref(s, parent_ref) if parent_ref else None
                if parent_ref and not parent_atom:
                    raise TaskError(f'找不到母卡：{parent_ref}')

                canvas = _resolve_project(s, project, parent_atom)
                atom = KnowledgeAtom(
                    title=title,
                    content=content,
                    content_type='markdown',
                    atom_type='A',
                    source='ai',
                    owner='claude',
                    lifecycle='active',
                    project_canvas_id=canvas.id,
                )
                s.add(atom)
                s.flush()
                ref_code = assign_ref_code(s, atom, canvas.id)
                entry = create_task_entry(s, atom, {
                    'status': 'planning',
                    'urgency': urgency,
                    'planned_start': planned_start,
                    'planned_duration': planned_duration,
                    'note': note,
                }, changed_by='ai')
                freetext_entries = ensure_freetext_entries(s, atom, changed_by='ai')
                _ensure_canvas_atom(s, canvas.id, atom.id)
                if parent_atom:
                    _create_relation_once(s, parent_atom.id, atom.id, 'contains')
                _attach_tags(s, atom, tags)
                s.flush()
                return json.dumps({
                    'ref_code': ref_code,
                    'atom_id': atom.id,
                    'entry_id': entry.id,
                    'project': {'code': canvas.code, 'name': canvas.name},
                    'parent_ref': parent_atom.ref_code if parent_atom else '',
                    'title': atom.title,
                    'freetext_entries': freetext_entries,
                }, ensure_ascii=False)
        except (TaskError, ValueError) as e:
            return _error(str(e))

    @mcp.tool()
    def note_task_update(
        ref: str,
        progress: str = '',
        urgency: str = '',
        planned_start: str = '',
        planned_end: str = '',
        note: str = '',
    ) -> str:
        """更新待辦欄位，不改狀態。

        ref 接受短代號（如 BBN-137，大小寫不敏感）或 atom id。此工具只更新
        progress、urgency、planned_start、planned_end、note；即使沒有任何欄位有值，
        也會直接回傳目前狀態。改狀態請用 note_task_status。
        """
        try:
            with session_scope() as s:
                atom, _entry, _schema = _resolve_task_entry(s, ref)
                values = {
                    'progress': progress,
                    'urgency': urgency,
                    'planned_start': planned_start,
                    'planned_end': planned_end,
                    'note': note,
                }
                values = {k: v for k, v in values.items() if v != ''}
                result = update_task_fields(s, atom.id, values, 'ai')
                return _task_response(atom, result)
        except (TaskError, ValueError) as e:
            return _error(str(e))

    @mcp.tool()
    def note_task_status(ref: str, status: str, reason: str = '') -> str:
        """轉移待辦狀態。

        ref 接受短代號（如 BBN-137，大小寫不敏感）或 atom id。status 必填，且只能是
        planning、in_progress、paused、completed、cancelled。狀態轉移一律走任務
        服務層規則：paused 會暫停並寫入 pause_log；paused 轉 in_progress 會 resume
        並寫入 pause_log；completed 或 cancelled 轉 in_progress 會 reopen 並寫入
        reopen_log；一般 in_progress 會補 actual_start；cancelled 會取消；completed
        會 fail-closed 檢查未完成子任務；planning 只把狀態改回 planning。reason 會被
        記進 pause、resume、reopen、cancel 相關 log。
        """
        try:
            with session_scope() as s:
                atom, entry, schema = _resolve_task_entry(s, ref)

                status = (status or '').strip()
                if not status:
                    raise TaskError('status 為必填')
                if status not in ('planning', 'in_progress', 'paused', 'completed', 'cancelled'):
                    raise TaskError(f'無效的 status：{status}')
                field_map = get_field_map(s, schema.id)
                current = _current_status(s, entry, field_map)
                result = None
                if status == 'paused':
                    result = apply_action(s, atom.id, 'pause', reason, 'ai:pause')
                elif status == 'in_progress' and current == 'paused':
                    result = apply_action(s, atom.id, 'resume', reason, 'ai:resume')
                elif status == 'in_progress' and current in ('completed', 'cancelled'):
                    result = apply_action(s, atom.id, 'reopen', reason, 'ai:reopen')
                elif status == 'in_progress':
                    set_field(s, entry, field_map, 'status', 'in_progress', 'ai')
                    ae = field_map.get('actual_start')
                    has_actual_start = False
                    if ae:
                        has_actual_start = any(
                            fv.field_id == ae.id and fv.value for fv in entry.field_values
                        )
                    if ae and not has_actual_start:
                        set_field(
                            s, entry, field_map, 'actual_start',
                            datetime.datetime.now().isoformat(timespec='seconds'), 'ai',
                        )
                elif status == 'cancelled':
                    result = apply_action(s, atom.id, 'cancel', reason, 'ai:cancel')
                elif status == 'completed':
                    result = complete_task(s, atom.id, 'ai:complete')
                elif status == 'planning':
                    set_field(s, entry, field_map, 'status', 'planning', 'ai')

                if result is None:
                    result = update_task_fields(s, atom.id, {}, 'ai')
                return _task_response(atom, result)
        except TaskError as e:
            blocked = []
            with session_scope() as s:
                atom = resolve_ref(s, ref)
                if atom:
                    blocked = unfinished_children(s, atom.id)
            return json.dumps({'error': str(e), 'blocked_children': blocked}, ensure_ascii=False)

    @mcp.tool()
    def note_task_adopt(
        ref: str,
        project: str = '',
        urgency: str = 'M',
        parent_ref: str = '',
    ) -> str:
        """把既有普通卡就地升格成待辦。

        用於開始開發某專案時，臨時把知識庫裡相關舊卡收集進待辦清單。不新建卡、
        不複製內容，原卡內容、標籤與既有關係全部保留；重複呼叫保持冪等。
        """
        try:
            with session_scope() as s:
                atom = resolve_ref(s, ref)
                if not atom:
                    raise TaskError(f'找不到卡片：{ref}')
                parent_atom = resolve_ref(s, parent_ref) if parent_ref else None
                if parent_ref and not parent_atom:
                    raise TaskError(f'找不到母卡：{parent_ref}')

                inherit_atom = parent_atom or atom
                canvas = _resolve_project(s, project, inherit_atom)
                atom.project_canvas_id = canvas.id
                ref_code = assign_ref_code(s, atom, canvas.id)
                existing_entry, _schema = get_task_entry(s, atom.id)
                entry = create_task_entry(s, atom, {
                    'status': 'planning',
                    'urgency': urgency,
                }, changed_by='ai')
                freetext_entries = ensure_freetext_entries(s, atom, changed_by='ai')
                _ensure_canvas_atom(s, canvas.id, atom.id)
                if parent_atom:
                    _create_relation_once(s, parent_atom.id, atom.id, 'contains')
                s.flush()
                return json.dumps({
                    'ref_code': ref_code,
                    'atom_id': atom.id,
                    'entry_id': entry.id,
                    'project': {'code': canvas.code, 'name': canvas.name},
                    'parent_ref': parent_atom.ref_code if parent_atom else '',
                    'title': atom.title,
                    'already_task': existing_entry is not None,
                    'freetext_entries': freetext_entries,
                }, ensure_ascii=False)
        except (TaskError, ValueError) as e:
            return _error(str(e))
