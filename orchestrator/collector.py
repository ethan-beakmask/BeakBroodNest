#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collector.py -- 支線結果收集器

由 wrapper.sh 在 claude process 結束後呼叫。
1. 讀取輸出檔
2. 寫入 worker_reports
3. 更新 worker_tasks 狀態
4. 經由 relay 處理（MVP: passthrough）
5. tmux 通知主線
"""
import argparse
import datetime
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import init_engine, session_scope
from core.models import KnowledgeAtom  # noqa: F401 -- 讓 SQLAlchemy 知道 knowledge_atoms 表（FK 依賴）
from orchestrator.models import WorkerTask, WorkerReport
from orchestrator.relay import process_report


def collect(task_id: int, exit_code: int, output_file: str, main_pane: str = ''):
    """收集支線結果並儲存"""
    init_engine()

    # 讀取輸出
    raw_output = ''
    if output_file:
        try:
            raw_output = Path(output_file).read_text(encoding='utf-8', errors='replace')
        except FileNotFoundError:
            raw_output = '(output file not found)'

    with session_scope() as s:
        task = s.query(WorkerTask).filter(WorkerTask.id == task_id).first()
        if not task:
            print(f'ERROR: task #{task_id} not found', file=sys.stderr)
            return

        # 更新任務狀態
        task.status = 'completed' if exit_code == 0 else 'failed'
        task.completed_at = datetime.datetime.now()

        # 建立 report
        report = WorkerReport(
            task_id=task.id,
            worker_id=task.worker_id,
            model=task.model,
            content=raw_output,
            content_type='text',
            raw_output=raw_output,
            exit_code=exit_code,
            review_status='pending',
        )
        s.add(report)
        s.flush()

        report_id = report.id
        report_dict = report.to_dict()

    # 經由 relay 處理（MVP: passthrough）
    relay_result = process_report(report_id)

    # 通知主線
    if main_pane:
        _notify_main(main_pane, task_id, exit_code, report_id)


def _notify_main(main_pane: str, task_id: int, exit_code: int, report_id: int):
    """透過 tmux display-message 通知主線"""
    status_text = '完成' if exit_code == 0 else f'失敗(exit={exit_code})'
    msg = f'[Worker] #{task_id} {status_text} -> report #{report_id}'
    try:
        subprocess.run(
            ['tmux', 'display-message', '-t', main_pane, '-d', '5000', msg],
            capture_output=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def main():
    parser = argparse.ArgumentParser(description='BeakNote Worker 結果收集器')
    parser.add_argument('--task-id', type=int, required=True, help='任務 ID')
    parser.add_argument('--exit-code', type=int, required=True, help='claude process exit code')
    parser.add_argument('--output-file', type=str, default='', help='輸出檔路徑')
    parser.add_argument('--main-pane', type=str, default='', help='主線 tmux pane ID')

    if len(sys.argv) == 1:
        print('BeakNote Worker 結果收集器')
        print()
        print('此程式由 wrapper.sh 自動呼叫，不需手動執行。')
        print()
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()
    collect(args.task_id, args.exit_code, args.output_file, args.main_pane)


if __name__ == '__main__':
    main()
