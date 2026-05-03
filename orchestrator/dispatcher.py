"""
任務派發器 -- 建立 tmux window 並啟動 claude process

流程:
  1. 在 DB 建立 WorkerTask (pending)
  2. 將 instruction 寫入暫存檔（含 KB preamble）
  3. 在 tmux 新建 window 執行 wrapper.sh
  4. 更新狀態為 dispatched
"""
import configparser
import datetime
import logging
import os
import platform
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

from core.db import session_scope
from orchestrator import cc_runner
from orchestrator.models import WorkerTask, WorkerSession

logger = logging.getLogger('orchestrator.dispatcher')

# 對話級別 session_id（模組載入時產生一次，同一主線對話內共用）
_SESSION_ID = '{host}_{ts}'.format(
    host=platform.node().split('.')[0][:20],
    ts=format(int(time.time()), 'x'),
)

WRAPPER_PATH = os.path.join(os.path.dirname(__file__), 'wrapper.sh')


def _load_kb_url() -> str:
    """從 config.ini 讀取 BeakBroodNest HTTP base URL"""
    config_path = Path(__file__).resolve().parent.parent / 'config.ini'
    cfg = configparser.ConfigParser()
    cfg.read(str(config_path), encoding='utf-8')
    host = cfg.get('flask', 'host', fallback='192.168.0.16')
    port = cfg.getint('flask', 'port', fallback=5170)
    return f'http://{host}:{port}'


def _build_kb_preamble(worker_id: str, session_id: str) -> str:
    """生成 KB 存取說明 preamble，注入到支線 instruction 前面"""
    base_url = _load_kb_url()
    return (
        '[BeakBroodNest KB Access]\n'
        '你可以透過以下 HTTP API 存取 BeakBroodNest 知識庫（使用 Bash curl）:\n'
        f'  Base URL: {base_url}\n'
        f'  認證 Header: -H "X-Worker-Id: {worker_id}" -H "X-Session-Id: {session_id}"\n'
        '\n'
        '可用端點:\n'
        '  GET  /api/worker/kb/search?q=<keyword>&tag=<tag>&limit=<n>&schema_id=<id>  搜尋原子\n'
        '  GET  /api/worker/kb/atoms/<id>                              讀取原子\n'
        '  POST /api/worker/kb/atoms  body: {"title":"...","content":"...","atom_type":"F","tags":["..."]}  寫入原子\n'
        '\n'
        '使用時機: 需要查詢專案知識或儲存研究結果時。不強制使用。\n'
        '[/BeakBroodNest KB Access]\n\n'
        '[方法論檢索 - 開工前必做]\n'
        '開始任務前，先搜尋是否有相關的方法論紀錄（前人經驗）:\n'
        f'  curl -s -H "X-Worker-Id: {worker_id}" -H "X-Session-Id: {session_id}" '
        f'"{base_url}/api/worker/kb/search?schema_id=2&q=<任務相關關鍵字>&limit=5"\n'
        '若有命中，閱讀 improved_approach 和 applicable_when 欄位，判斷是否適用於當前任務。\n'
        '[/方法論檢索]\n\n'
    )


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

def get_session_id() -> str:
    """取得目前對話的 session_id"""
    return _SESSION_ID


def create_task(
    title: str,
    instruction: str,
    model: str = 'sonnet',
    working_dir: str = '/opt/BeakBroodNest',
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
            session_id=_SESSION_ID,
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

        # 將 instruction 寫入暫存檔（含 KB preamble，避免 shell 引號問題）
        kb_preamble = _build_kb_preamble(task.worker_id, task.session_id)
        instr_file = tempfile.NamedTemporaryFile(
            mode='w', prefix=f'beak-task-{task_id}-', suffix='.txt',
            dir='/tmp', delete=False,
        )
        instr_file.write(kb_preamble + task.instruction)
        instr_file.close()

        # 組裝 wrapper 指令
        wrapper_cmd = (
            f'bash {shlex.quote(WRAPPER_PATH)}'
            f' {task.id}'
            f' {shlex.quote(task.model)}'
            f' {shlex.quote(task.working_dir)}'
            f' {shlex.quote(instr_file.name)}'
            f' {shlex.quote(main_pane)}'
            f' {shlex.quote(task.session_id)}'
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
    working_dir: str = '/opt/BeakBroodNest',
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


# ============================================================
# cc-to-cc 多輪互動會話（spawn_session / talk_session）
# ============================================================

WORKSPACES_DIR = Path(__file__).resolve().parent / 'workspaces'

INBOX_PROTOCOL_TEMPLATE = """\
[支線 CC 對話協定]
你是支線 cc，session 名稱: {name}, 角色: {role}
你與「主 CC」協作。當你遇到下列情況時，必須呼叫主 CC：
1. 規格不清楚需要釐清
2. 對任務範圍有異議
3. 任務完成需要主 CC 驗收
4. 與其他支線衝突需要協調

呼叫主 CC 的方法（透過 Bash 工具執行此指令）：
  /opt/BeakBroodNest/orchestrator/cli/cc-inbox-put --session {name} --kind <kind> --content "<內容>"

kind 可選值:
  question - 你需要主 CC 回答才能繼續（阻塞型）
  notice   - 進度回報（非阻塞）
  result   - 任務完成的最終結果

主 CC 會在下一輪 cc-talk 對話中回覆你。送出 question 後請結束本輪，等待主 CC 回應。

工作目錄: {working_dir}
[/支線 CC 對話協定]
"""


def _validate_session_name(name: str, allow_underscore: bool = False) -> None:
    if not name:
        raise ValueError('session name 不可為空')
    if not allow_underscore and name.startswith('__'):
        raise ValueError(
            f'session name "{name}" 以雙底線開頭為保留識別字（hook 自建支線專用），請改用其他名稱'
        )


def spawn_session(
    name: str,
    role: str,
    first_message: str,
    model: str = 'sonnet',
    main_pane: str = '',
    purpose: str = WorkerSession.PURPOSE_WORKER,
    inject_inbox_protocol: bool = True,
    allow_underscore: bool = False,
    timeout: int = 600,
) -> dict:
    """建立支線 cc 並送出第一輪訊息。

    回傳 dict 含 session_name / claude_session_id / first_response。
    """
    _validate_session_name(name, allow_underscore=allow_underscore)

    workspace = WORKSPACES_DIR / name
    workspace.mkdir(parents=True, exist_ok=True)

    pane = main_pane
    if not pane:
        try:
            tmux_info = get_current_tmux_info()
            pane = tmux_info.get('pane_id', '')
        except Exception:
            pane = ''

    with session_scope() as s:
        existing = s.query(WorkerSession).filter(WorkerSession.name == name).first()
        if existing:
            raise ValueError(f'session 名稱 "{name}" 已存在')
        sess = WorkerSession(
            name=name,
            role=role,
            purpose=purpose,
            working_dir=str(workspace),
            model=model,
            main_tmux_pane=pane,
            status='active',
        )
        s.add(sess)
        s.flush()

    system_prompt = None
    if inject_inbox_protocol:
        system_prompt = INBOX_PROTOCOL_TEMPLATE.format(
            name=name, role=role, working_dir=str(workspace),
        )

    try:
        data = cc_runner.call_claude(
            prompt=first_message,
            working_dir=str(workspace),
            model=model,
            append_system_prompt=system_prompt,
            timeout=timeout,
        )
    except Exception as e:
        with session_scope() as s:
            sess = s.query(WorkerSession).filter(WorkerSession.name == name).first()
            if sess:
                sess.status = 'failed'
        raise

    claude_sid = data.get('session_id', '')
    result_text = data.get('result', '')

    with session_scope() as s:
        sess = s.query(WorkerSession).filter(WorkerSession.name == name).first()
        sess.claude_session_id = claude_sid
        sess.last_activity_at = datetime.datetime.now()

    return {
        'session_name': name,
        'claude_session_id': claude_sid,
        'first_response': result_text,
    }


def talk_session(session_name: str, message: str, timeout: int = 600) -> dict:
    """對既有支線送訊息（接續對話）。回傳含 result 文字。"""
    with session_scope() as s:
        sess = s.query(WorkerSession).filter(WorkerSession.name == session_name).first()
        if not sess:
            raise ValueError(f'找不到 session "{session_name}"')
        if not sess.claude_session_id:
            raise ValueError(f'session "{session_name}" 尚未取得 claude_session_id')
        working_dir = sess.working_dir
        model = sess.model
        resume_id = sess.claude_session_id

    data = cc_runner.call_claude(
        prompt=message,
        working_dir=working_dir,
        model=model,
        resume_session_id=resume_id,
        timeout=timeout,
    )

    new_sid = data.get('session_id') or resume_id
    result_text = data.get('result', '')

    with session_scope() as s:
        sess = s.query(WorkerSession).filter(WorkerSession.name == session_name).first()
        sess.claude_session_id = new_sid
        sess.last_activity_at = datetime.datetime.now()

    return {
        'session_name': session_name,
        'claude_session_id': new_sid,
        'response': result_text,
    }


def find_hook_session(purpose: str) -> str | None:
    """依 purpose 找最早的 active hook session（供 aside hook 等使用）。"""
    with session_scope() as s:
        sess = (
            s.query(WorkerSession)
            .filter(WorkerSession.purpose == purpose, WorkerSession.status == 'active')
            .order_by(WorkerSession.created_at.asc())
            .first()
        )
        return sess.name if sess else None
