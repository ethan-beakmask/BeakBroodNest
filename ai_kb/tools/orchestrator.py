# -*- coding: utf-8 -*-
"""Orchestrator 工具: task_dispatch/status/list/collect"""
import json
import os

from core.db import session_scope
from orchestrator.models import WorkerTask, WorkerReport
from orchestrator import dispatcher as orch_dispatcher

_DEFAULT_WORKING_DIR = os.environ.get('BBN_INSTALL_DIR') or '/opt/BeakBroodNest'


def register(mcp):

    @mcp.tool()
    def task_dispatch(
        title: str,
        instruction: str,
        model: str = 'sonnet',
        working_dir: str = _DEFAULT_WORKING_DIR,
        priority: int = 5,
        timeout_seconds: int = 600,
    ) -> str:
        """派發一個任務到支線 claude process 執行。

        在 tmux 新建 window，啟動 claude -p 執行指令。
        結果會存入 worker_reports，經中間層審查後可供主線讀取。

        model: sonnet / opus / haiku (支線使用的模型)
        working_dir: 支線的工作目錄
        priority: 0-9 (目前僅記錄，未來排程用)
        timeout_seconds: 逾時秒數 (預設 600)

        回傳任務 ID 與狀態。完成後用 task_status 查詢結果。
        """
        result = orch_dispatcher.create_and_dispatch(
            title=title,
            instruction=instruction,
            model=model,
            working_dir=working_dir,
            priority=priority,
            timeout_seconds=timeout_seconds,
        )
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    def task_status(task_id: int) -> str:
        """查詢支線任務的狀態與結果。

        回傳任務詳情。若已完成，同時回傳 worker_report 內容。
        """
        with session_scope() as s:
            task = s.query(WorkerTask).filter(WorkerTask.id == task_id).first()
            if not task:
                return json.dumps({'error': f'任務 #{task_id} 不存在'})

            result = task.to_dict()
            result['reports'] = []

            if task.status in ('completed', 'failed'):
                reports = (
                    s.query(WorkerReport)
                    .filter(WorkerReport.task_id == task_id)
                    .order_by(WorkerReport.created_at.desc())
                    .all()
                )
                result['reports'] = [r.to_dict() for r in reports]

            return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    def task_list(
        status: str = '',
        limit: int = 20,
    ) -> str:
        """列出支線任務。

        status: 篩選狀態 (pending/dispatched/running/completed/failed/timeout/cancelled)
                空字串表示列出所有非 cancelled 的任務
        limit: 回傳上限 (預設 20)
        """
        limit = min(limit, 100)

        with session_scope() as s:
            q = s.query(WorkerTask)

            if status:
                q = q.filter(WorkerTask.status == status)
            else:
                q = q.filter(WorkerTask.status != 'cancelled')

            tasks = (
                q.order_by(WorkerTask.created_at.desc())
                .limit(limit)
                .all()
            )

            return json.dumps({
                'total': len(tasks),
                'items': [t.to_dict(brief=True) for t in tasks],
            }, ensure_ascii=False)

    @mcp.tool()
    def task_collect(task_id: int, include_raw: bool = False) -> str:
        """取得支線任務的完整報告。

        回傳 worker_report 的內容。
        include_raw: 是否包含 tmux capture 的原始輸出 (預設 False，避免過長)

        report 的 review_status:
          pending   -- 尚未經過中間層處理
          approved  -- 中間層審查通過
          rejected  -- 中間層審查未通過
          promoted  -- 已提升為正式知識原子 (promoted_atom_id)
        """
        with session_scope() as s:
            task = s.query(WorkerTask).filter(WorkerTask.id == task_id).first()
            if not task:
                return json.dumps({'error': f'任務 #{task_id} 不存在'})

            reports = (
                s.query(WorkerReport)
                .filter(WorkerReport.task_id == task_id)
                .order_by(WorkerReport.created_at.desc())
                .all()
            )

            if not reports:
                return json.dumps({
                    'task_id': task_id,
                    'task_status': task.status,
                    'message': '尚無報告（任務可能仍在執行中）',
                })

            return json.dumps({
                'task_id': task_id,
                'task_title': task.title,
                'task_status': task.status,
                'reports': [r.to_dict(include_raw=include_raw) for r in reports],
            }, ensure_ascii=False)
