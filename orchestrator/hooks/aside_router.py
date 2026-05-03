#!/opt/BeakBroodNest/venv/bin/python
"""aside_router.py -- UserPromptSubmit hook，攔截 'aside:' 前綴。

機制：
  1. 從 stdin 讀 hook input JSON
  2. 若 prompt 開頭是 'aside:' → 派 hook_aside 用途的長期支線、回 block 帶結果
  3. 否則 exit 0 不輸出，主 cc 正常處理

設計原則：主 cc transcript 完全看不到 aside 對話，避免汙染。

支線查找以 purpose='hook_aside' + status='active' 為準（不再寫死 name），
未來新增 summary: / translate: 等前綴可仿此模組另開 hook，purpose='hook_<name>'。

來源：/opt/backup/mvp/hooks/aside_router.py（CC-to-CC 互動 MVP）
"""
import json
import sys
from pathlib import Path

ROOT = Path('/opt/BeakBroodNest')
sys.path.insert(0, str(ROOT))

PREFIX = 'aside:'
ASIDE_PURPOSE = 'hook_aside'
ASIDE_NAME = '__aside_default__'  # 雙底線保留識別字
ASIDE_ROLE = '處理主對話之外的臨時話題（aside hook 自建）'
ASIDE_TIMEOUT = 120


def block(reason: str) -> None:
    print(json.dumps({'decision': 'block', 'reason': reason}, ensure_ascii=False))
    sys.exit(0)


def passthrough() -> None:
    sys.exit(0)


def run_aside(question: str) -> str:
    """呼叫支線取得回答。首次建立 hook session，後續 resume。"""
    from orchestrator import dispatcher
    from orchestrator.models import WorkerSession

    existing_name = dispatcher.find_hook_session(ASIDE_PURPOSE)
    if existing_name:
        result = dispatcher.talk_session(
            session_name=existing_name,
            message=question,
            timeout=ASIDE_TIMEOUT,
        )
        return result.get('response', '') or '(支線無回應內容)'
    else:
        result = dispatcher.spawn_session(
            name=ASIDE_NAME,
            role=ASIDE_ROLE,
            first_message=question,
            model='sonnet',
            purpose=WorkerSession.PURPOSE_HOOK_ASIDE,
            inject_inbox_protocol=False,
            allow_underscore=True,
            timeout=ASIDE_TIMEOUT,
        )
        return result.get('first_response', '') or '(支線無回應內容)'


def main() -> None:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        passthrough()
        return

    prompt = data.get('prompt', '') or ''
    stripped = prompt.lstrip()

    if not stripped.lower().startswith(PREFIX):
        passthrough()
        return

    question = stripped[len(PREFIX):].lstrip()
    if not question:
        block('aside: 後面沒有問題內容\n用法: aside: <你的臨時問題>')
        return

    try:
        answer = run_aside(question)
    except Exception as e:
        block(f'[aside 失敗] {type(e).__name__}: {e}')
        return

    block(f'[aside 回覆 / 主線未受汙染]\n\n{answer}')


if __name__ == '__main__':
    main()
