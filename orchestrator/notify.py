"""通知主 cc 的工具：tmux display-message + 旗標檔 + stderr 醒目訊息。

來源：/opt/backup/mvp/lib/notify.py（CC-to-CC 互動 MVP）
"""
import json
import os
import subprocess
import sys
from pathlib import Path

STATE_DIR = Path(os.environ.get(
    'BEAKCORTEX_ORCH_STATE_DIR',
    '/opt/tmp/beakcortex-orch',
))
NOTIFY_FLAG = STATE_DIR / 'notify.flag'


def get_current_tmux_pane() -> str | None:
    """取得目前所在的 tmux pane id（給 cc-spawn 記錄主 cc 位置）"""
    try:
        r = subprocess.run(
            ['tmux', 'display-message', '-p', '#{pane_id}'],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def tmux_display_message(pane: str, message: str) -> bool:
    """對指定 pane 的 status line 顯示訊息（不干擾輸入）"""
    if not pane:
        return False
    try:
        r = subprocess.run(
            ['tmux', 'display-message', '-t', pane, message],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def write_flag(unread_count: int, last_session: str, last_kind: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    NOTIFY_FLAG.write_text(json.dumps({
        'unread_count': unread_count,
        'last_session': last_session,
        'last_kind': last_kind,
    }, ensure_ascii=False), encoding='utf-8')


def clear_flag() -> None:
    if NOTIFY_FLAG.exists():
        NOTIFY_FLAG.unlink()


def notify_main(
    pane: str | None,
    session: str,
    kind: str,
    unread_count: int,
    content_preview: str,
) -> None:
    """寫旗標檔 + tmux 提示 + stderr 醒目訊息"""
    write_flag(unread_count, session, kind)

    msg = f'[CC-Orch] {session} 送來 {kind}（共 {unread_count} 則未讀）'
    if pane:
        tmux_display_message(pane, msg)

    preview = content_preview if len(content_preview) <= 80 else content_preview[:77] + '...'
    bar = '=' * 60
    print(
        f'\n{bar}\n>>> {msg}\n>>> 預覽: {preview}\n'
        f'>>> 主 cc 請執行: cc-inbox-get --unread-only --mark-read\n{bar}\n',
        file=sys.stderr,
    )
