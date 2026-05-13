# -*- coding: utf-8 -*-
"""搜尋前置詞典：將查詢字串中的 alias 替換為 canonical 形式。

設計：
- alias → canonical 單向映射（避免雙向群組維護複雜度）
- 程式內 TTL 快取（預設 60 秒），不打 Redis
- 長度長的 alias 先替換，避免短詞先吃掉長詞
- 替換不關聯 atom，純查詢預處理器
"""
import time
import threading
import logging

from core.db import session_scope
from core.models import TermAlias

logger = logging.getLogger('beak_broodnest.term_dict')

_TTL_SECONDS = 60
_CACHE = {'pairs': [], 'loaded_at': 0.0}
_LOCK = threading.Lock()


def _load_from_db():
    with session_scope() as s:
        rows = (
            s.query(TermAlias)
            .filter(TermAlias.enabled == True)  # noqa: E712
            .all()
        )
        pairs = [(r.alias, r.canonical) for r in rows if r.alias and r.canonical]
    # 長 alias 優先替換，避免 "復盤" 先吃掉 "覆盤" 之類的場景
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    return pairs


def get_pairs(force_reload: bool = False) -> list[tuple[str, str]]:
    """取得 (alias, canonical) 配對列表，帶 TTL 快取。"""
    now = time.time()
    with _LOCK:
        if force_reload or (now - _CACHE['loaded_at']) > _TTL_SECONDS:
            try:
                _CACHE['pairs'] = _load_from_db()
                _CACHE['loaded_at'] = now
            except Exception as e:
                logger.warning(f'term_dict load failed: {e}')
        return list(_CACHE['pairs'])


def normalize(query: str) -> tuple[str, list[tuple[str, str]]]:
    """將 query 中的 alias 替換為 canonical。

    回傳 (normalized_query, applied)，applied 是實際生效的 (alias, canonical) 列表。
    若 alias == canonical 或未命中則不變更。
    """
    if not query:
        return query, []
    out = query
    applied: list[tuple[str, str]] = []
    for alias, canonical in get_pairs():
        if alias == canonical:
            continue
        if alias in out:
            out = out.replace(alias, canonical)
            applied.append((alias, canonical))
    return out, applied


def invalidate_cache():
    """強制下次查詢重新載入。CLI/UI 變更後呼叫。"""
    with _LOCK:
        _CACHE['loaded_at'] = 0.0
