"""claude -p 同步呼叫包裝（cc-to-cc 多輪互動用）。

與 wrapper.sh + collector.py 的非同步派遣分屬兩條路徑：
- spawn_session / talk_session 用本模組（呼叫者立即拿到回應）
- dispatch_task（一次性）仍走 wrapper.sh + tmux + collector

來源：/opt/backup/mvp/lib/cc.py（CC-to-CC 互動 MVP）
"""
import json
import subprocess


def call_claude(
    prompt: str,
    working_dir: str,
    model: str = 'sonnet',
    resume_session_id: str | None = None,
    append_system_prompt: str | None = None,
    timeout: int = 600,
) -> dict:
    """呼叫 claude -p（單輪），回傳解析後的 JSON dict。

    若 resume_session_id 提供則接續既有 session，否則建立新 session。
    回傳的 dict 至少含 session_id 與 result 欄位。
    """
    cmd = [
        'claude', '-p',
        '--permission-mode', 'bypassPermissions',
        '--model', model,
        '--output-format', 'json',
    ]
    if resume_session_id:
        cmd.extend(['--resume', resume_session_id])
    if append_system_prompt:
        cmd.extend(['--append-system-prompt', append_system_prompt])

    result = subprocess.run(
        cmd,
        input=prompt,
        cwd=working_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f'claude exited with code {result.returncode}\n'
            f'stderr: {result.stderr}\n'
            f'stdout (first 500): {result.stdout[:500]}'
        )

    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError('claude 無輸出')

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        for line in reversed(stdout.split('\n')):
            line = line.strip()
            if line.startswith('{'):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        raise RuntimeError(
            f'無法解析 claude JSON 輸出（前 500 字元）: {stdout[:500]}'
        )
