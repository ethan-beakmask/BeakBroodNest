#!/usr/bin/env python3
"""
Orchestrator 環境驗證 (smoke test)

在 tmux 內執行:
  cd /opt/BeakBroodNest && source venv/bin/activate
  python orchestrator/smoke_test.py          # 派發測試任務
  python orchestrator/smoke_test.py --check  # 查詢結果
"""
import argparse
import subprocess
import sys
import tempfile
import shlex
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import init_engine, session_scope
from core.models import KnowledgeAtom  # noqa: F401
from orchestrator.models import WorkerTask, WorkerReport


def dispatch():
    """派發一個簡單的測試任務"""
    result = subprocess.run(
        ['tmux', 'display-message', '-p', '#{session_name}\t#{pane_id}'],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0 or '\t' not in result.stdout:
        print('ERROR: 必須在 tmux 環境中執行')
        sys.exit(1)

    parts = result.stdout.strip().split('\t')
    session_name, main_pane = parts[0], parts[1]
    print(f'tmux session: {session_name}, main_pane: {main_pane}')

    with session_scope() as s:
        task = WorkerTask(
            title='smoke test',
            instruction='請回答 1+1 等於多少，只回答數字',
            model='haiku',
            working_dir='/opt/BeakBroodNest',
            main_pane=main_pane,
        )
        s.add(task)
        s.flush()
        task_id = task.id
        worker_id = task.worker_id
        print(f'Task #{task_id} created (worker_id={worker_id})')

    instr_file = tempfile.NamedTemporaryFile(
        mode='w', prefix=f'beak-task-{task_id}-', suffix='.txt',
        dir='/tmp', delete=False,
    )
    instr_file.write('請回答 1+1 等於多少，只回答數字')
    instr_file.close()

    wrapper_path = '/opt/BeakBroodNest/orchestrator/wrapper.sh'
    wrapper_cmd = (
        f'bash {shlex.quote(wrapper_path)}'
        f' {task_id}'
        f' haiku'
        f' /opt/BeakBroodNest'
        f' {shlex.quote(instr_file.name)}'
        f' {shlex.quote(main_pane)}'
    )

    window_name = f'w-{worker_id}'
    cmd = [
        'tmux', 'new-window', '-t', f'{session_name}:',
        '-n', window_name, '-d', '-P', '-F', '#{pane_id}',
        'bash', '-c', wrapper_cmd,
    ]
    create_result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

    if create_result.returncode != 0:
        print(f'FAILED: {create_result.stderr.strip()}')
        sys.exit(1)

    with session_scope() as s:
        t = s.query(WorkerTask).filter(WorkerTask.id == task_id).first()
        t.status = 'dispatched'
        t.tmux_session = session_name
        t.tmux_pane = create_result.stdout.strip()
        t.main_pane = main_pane

    print(f'Dispatched -> window: {window_name}')
    print(f'查看支線: tmux select-window -t {window_name}')
    print(f'查詢結果: python orchestrator/smoke_test.py --check')


def check():
    """查詢所有任務與報告"""
    with session_scope() as s:
        tasks = s.query(WorkerTask).order_by(WorkerTask.id).all()
        if not tasks:
            print('(no tasks)')
            return
        for t in tasks:
            print(f'Task #{t.id}: {t.title} [{t.status}] model={t.model}')
        reports = s.query(WorkerReport).order_by(WorkerReport.id).all()
        for r in reports:
            print(f'  Report #{r.id} (task #{r.task_id}) [{r.review_status}] exit={r.exit_code}')
            print(f'    content: {r.content[:300]}')


def main():
    parser = argparse.ArgumentParser(description='Orchestrator 環境驗證')
    parser.add_argument('--check', action='store_true', help='查詢任務結果')

    if len(sys.argv) == 1:
        print(__doc__.strip())
        print()

    args = parser.parse_args()
    init_engine()

    if args.check:
        check()
    else:
        dispatch()


if __name__ == '__main__':
    main()
