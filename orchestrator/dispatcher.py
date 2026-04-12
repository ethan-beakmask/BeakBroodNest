"""
任務派發器 -- 建立 tmux window 並啟動 claude process

流程:
  1. 在 DB 建立 WorkerTask (pending)
  2. 將 instruction 寫入暫存檔
  3. 在 tmux 新建 window 執行 wrapper.sh
  4. 更新狀態為 dispatched
"""
import datetime
import logging
import os
import shlex
import subprocess
import tempfile

from core.db import session_scope
from orchestrator.models import WorkerTask

logger = logging.getLogger('orchestrator.dispatcher')

WRAPPER_PATH = os.path.join(os.path.dirname(__file__), 'wrapper.sh')


# ============================================================
# tmux 操作
# ============================================================

def get_current_tmux_info() -> dict:
    """取得當前 tmux session/window/pane 資訊"""
    try:
        result = subprocess.run(
            ['tmux', 'display-message', '-p',
             '#{session_name}\t#{window_index}.#{pane_index}\t#{pane_id}'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return {}
        parts = result.stdout.strip().split('\t')
        if len(parts) == 3:
            return {
                'session': parts[0],
                'window_pane': parts[1],
                'pane_id': parts[2],
            }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return {}


def _create_tmux_window(session_name: str, window_name: str, cmd: str) -> str:
    """建立 tmux window (背景)，回傳 pane_id"""
    # 用 session_name: (帶冒號) 確保 tmux 把它解讀為 session 而非 window index
    target = f'{session_name}:'
    create_result = subprocess.run(
        ['tmux', 'new-window', '-t', target,
         '-n', window_name, '-d', '-P', '-F', '#{pane_id}',
         'bash', '-c', cmd],
        capture_output=True, text=True, timeout=10,
    )
    if create_result.returncode != 0:
        raise RuntimeError(f'tmux new-window 失敗: {create_result.stderr.strip()}')
    return create_result.stdout.strip()


# ============================================================
# 任務建立 + 派發
# ============================================================

def create_task(
    title: str,
    instruction: str,
    model: str = 'sonnet',
    working_dir: str = '/opt/BeakCortex',
    priority: int = 5,
    timeout_seconds: int = 600,
    main_pane: str = '',
) -> WorkerTask:
    """在 DB 建立 pending 任務"""
    with session_scope() as s:
        task = WorkerTask(
            title=title,
            instruction=instruction,
            model=model,
            working_dir=working_dir,
            priority=priority,
            timeout_seconds=timeout_seconds,
            main_pane=main_pane,
        )
        s.add(task)
        s.flush()
        # detach 以便回傳（避免 session close 後存取）
        task_dict = task.to_dict()
        task_id = task.id
    return task_id, task_dict


def dispatch_task(task_id: int) -> dict:
    """
    派發 pending 任務到 tmux window。
    將 instruction 寫入暫存檔，由 wrapper.sh 讀取後執行 claude -p。
    """
    with session_scope() as s:
        task = s.query(WorkerTask).filter(WorkerTask.id == task_id).first()
        if not task:
            return {'error': f'任務 #{task_id} 不存在'}
        if task.status != 'pending':
            return {'error': f'任務 #{task_id} 狀態為 {task.status}，僅 pending 可派發'}

        # 偵測 tmux session
        tmux_info = get_current_tmux_info()
        session_name = tmux_info.get('session', '')
        if not session_name:
            return {'error': '未偵測到 tmux session，請確認在 tmux 環境中執行'}

        main_pane = task.main_pane or tmux_info.get('pane_id', '')

        # 將 instruction 寫入暫存檔（避免 shell 引號問題）
        instr_file = tempfile.NamedTemporaryFile(
            mode='w', prefix=f'beak-task-{task_id}-', suffix='.txt',
            dir='/tmp', delete=False,
        )
        instr_file.write(task.instruction)
        instr_file.close()

        # 組裝 wrapper 指令
        wrapper_cmd = (
            f'bash {shlex.quote(WRAPPER_PATH)}'
            f' {task.id}'
            f' {shlex.quote(task.model)}'
            f' {shlex.quote(task.working_dir)}'
            f' {shlex.quote(instr_file.name)}'
            f' {shlex.quote(main_pane)}'
        )

        window_name = f'w-{task.worker_id}'
        try:
            pane_id = _create_tmux_window(session_name, window_name, wrapper_cmd)
        except RuntimeError as e:
            os.unlink(instr_file.name)
            return {'error': str(e)}

        task.status = 'dispatched'
        task.dispatched_at = datetime.datetime.now()
        task.tmux_session = session_name
        task.tmux_pane = pane_id
        task.main_pane = main_pane

        return task.to_dict(brief=True)


def create_and_dispatch(
    title: str,
    instruction: str,
    model: str = 'sonnet',
    working_dir: str = '/opt/BeakCortex',
    priority: int = 5,
    timeout_seconds: int = 600,
    main_pane: str = '',
) -> dict:
    """建立任務並立即派發（主線最常用的入口）"""
    task_id, task_dict = create_task(
        title=title,
        instruction=instruction,
        model=model,
        working_dir=working_dir,
        priority=priority,
        timeout_seconds=timeout_seconds,
        main_pane=main_pane,
    )
    result = dispatch_task(task_id)
    return result
