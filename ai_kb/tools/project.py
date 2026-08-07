# -*- coding: utf-8 -*-
"""專案任務工具：依 cwd 查詢待辦與行事曆"""
import json
from pathlib import Path

from sqlalchemy import text

from core.db import session_scope
from core.models import Canvas
from core.ref_code import ensure_project_code
from core.task_query import query_task_entries


def _find_canvas_by_cwd(s, cwd: str) -> Canvas | None:
    """找 project_path 最長匹配 cwd 的 canvas（前綴匹配，取最深路徑優先）"""
    cwd_path = Path(cwd).resolve()
    canvases = (
        s.query(Canvas)
        .filter(
            Canvas.project_path.isnot(None),
            Canvas.project_path != '',
            Canvas.is_archived == False,  # noqa: E712
        )
        .all()
    )
    best: Canvas | None = None
    best_depth = -1
    for c in canvases:
        try:
            cp = Path(c.project_path).resolve()
            # cwd 必須以 project_path 為前綴（或完全相同）
            cwd_path.relative_to(cp)
            depth = len(cp.parts)
            if depth > best_depth:
                best = c
                best_depth = depth
        except ValueError:
            continue
    return best


def register(mcp):

    @mcp.tool()
    def project_setup(
        project_path: str,
        code: str,
        name: str = '',
        description: str = '',
    ) -> str:
        """新專案要開始收待辦時的第一步。

        一次完成白板建立、專案目錄綁定與短代號設定；可重複執行，
        同樣參數再次呼叫會回傳既有白板，不會重複建立。
        """
        normalized_path = (project_path or '').strip()
        if not normalized_path:
            return json.dumps({'error': 'project_path 不可為空'}, ensure_ascii=False)

        normalized_name = (name or '').strip()
        with session_scope() as s:
            canvas = (
                s.query(Canvas)
                .filter(
                    Canvas.project_path == normalized_path,
                    Canvas.is_archived == False,  # noqa: E712
                )
                .first()
            )
            if canvas is None and normalized_name:
                canvas = (
                    s.query(Canvas)
                    .filter(
                        Canvas.name == normalized_name,
                        Canvas.is_archived == False,  # noqa: E712
                    )
                    .first()
                )

            created = False
            if canvas is None:
                fallback_name = Path(normalized_path).name or normalized_path
                canvas = Canvas(
                    name=normalized_name or fallback_name,
                    description=description,
                    is_project=True,
                    canvas_type='whiteboard',
                    owner='claude',
                    audience='ai',
                )
                s.add(canvas)
                s.flush()
                created = True

            canvas.project_path = normalized_path
            try:
                normalized_code = ensure_project_code(s, canvas, code)
            except ValueError as e:
                s.rollback()
                return json.dumps({'error': str(e)}, ensure_ascii=False)

            next_seq = s.execute(
                text('SELECT next_seq FROM project_ref_counters WHERE canvas_id = :cid'),
                {'cid': canvas.id},
            ).scalar_one_or_none() or 1

            return json.dumps({
                'canvas_id': canvas.id,
                'slug': canvas.slug,
                'name': canvas.name,
                'code': normalized_code,
                'project_path': canvas.project_path,
                'created': created,
                'next_seq': next_seq,
            }, ensure_ascii=False)

    @mcp.tool()
    def project_tasks(cwd: str) -> str:
        """依當前工作目錄查詢對應專案的待辦與行事曆。

        cwd: 當前工作目錄路徑（Claude Code 啟動時的 primary working directory）

        回傳：
          canvas: 匹配的白板資訊，若無關聯回傳 null
          todos: 無 planned_start 的 task entries（純列表）
          calendar: 有 planned_start 的 task entries（時間軸）
          task entry 會包含 ref_code/progress/parent_ref/blocked_by 欄位
          message: 若無白板或無資料時的說明文字
        """
        with session_scope() as s:
            canvas = _find_canvas_by_cwd(s, cwd)
            if not canvas:
                return json.dumps({
                    'canvas': None,
                    'todos': [],
                    'calendar': [],
                    'message': f'找不到與路徑 {cwd} 關聯的白板，請先用 canvas_set_project_path 設定對應關係。',
                }, ensure_ascii=False)

            all_items = query_task_entries(
                s,
                canvas_ids=[canvas.id],
                include_done=False,
            )

            todos = [it for it in all_items if not it.get('field_values', {}).get('planned_start')]
            calendar = [it for it in all_items if it.get('field_values', {}).get('planned_start')]

            # 行事曆依 planned_start 排序
            calendar.sort(key=lambda x: x['field_values'].get('planned_start', ''))

            msg = None
            if not todos and not calendar:
                msg = f'專案「{canvas.name}」目前沒有待辦或行事曆項目。'

            return json.dumps({
                'canvas': {
                    'slug': canvas.slug,
                    'name': canvas.name,
                    'project_path': canvas.project_path,
                },
                'todos': todos,
                'calendar': calendar,
                'message': msg,
            }, ensure_ascii=False, default=str)

    @mcp.tool()
    def canvas_set_project_path(canvas_slug: str, project_path: str) -> str:
        """設定白板與本地專案目錄的關聯路徑。

        canvas_slug: 白板 slug（8 碼）
        project_path: 本地目錄絕對路徑，如 /opt/BeakBroodNest；傳空字串清除關聯
        """
        with session_scope() as s:
            canvas = s.query(Canvas).filter(Canvas.slug == canvas_slug).first()
            if not canvas:
                return json.dumps({'error': f'找不到白板: {canvas_slug}'}, ensure_ascii=False)

            old = canvas.project_path
            canvas.project_path = project_path.strip() or None
            return json.dumps({
                'slug': canvas.slug,
                'name': canvas.name,
                'project_path': canvas.project_path,
                'previous': old,
            }, ensure_ascii=False)
