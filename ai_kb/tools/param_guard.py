# -*- coding: utf-8 -*-
"""MCP 工具參數守門。"""
import functools
import inspect
import json

from .param_forms import (
    EXTRA_REPLACEMENTS_FORMAT,
    FIELDS_FORMAT,
    FIELD_VALUES_FORMAT,
    RELATIONS_FORMAT,
)


HINTS = {
    'tags': '推薦字串形式：逗號分隔字串；例：BeakAgent,待辦',
    'field_values': f'推薦字串形式：{FIELD_VALUES_FORMAT}',
    'relations': f'推薦字串形式：{RELATIONS_FORMAT}',
    'fields': f'推薦字串形式：{FIELDS_FORMAT}',
    'extra_replacements': f'推薦字串形式：{EXTRA_REPLACEMENTS_FORMAT}',
}
DEFAULT_HINT = '陣列 / 物件內請勿放中文，改用字串參數'


def find_non_ascii(value):
    """遞迴檢查 list / tuple / dict 內的非 ASCII 字串。"""
    if isinstance(value, str):
        return value if not value.isascii() else None
    if isinstance(value, (list, tuple)):
        for item in value:
            found = find_non_ascii(item)
            if found:
                return found
    elif isinstance(value, dict):
        for key, item in value.items():
            found = find_non_ascii(key)
            if found:
                return found
            found = find_non_ascii(item)
            if found:
                return found
    return None


def guard_tool(fn):
    """包裝 MCP 工具函式，拒絕陣列 / 物件內的非 ASCII 字串。"""
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        for name, value in bound.arguments.items():
            if isinstance(value, (list, tuple, dict)) and find_non_ascii(value):
                return json.dumps({
                    'error': (
                        f'參數 {name} 的陣列 / 物件內含非 ASCII 字元，已拒絕執行'
                        '（陣列 / 物件內的中文容易被寫成錯碼的 unicode escape）'
                    ),
                    'param': name,
                    'hint': HINTS.get(name, DEFAULT_HINT),
                }, ensure_ascii=False)
        return fn(*args, **kwargs)

    return wrapper


class GuardedMCP:
    """FastMCP 代理，在註冊工具時加上參數守門。"""

    def __init__(self, mcp):
        self._mcp = mcp

    def tool(self, *args, **kwargs):
        decorator = self._mcp.tool(*args, **kwargs)

        def guarded_decorator(fn):
            return decorator(guard_tool(fn))

        return guarded_decorator

    def __getattr__(self, name):
        return getattr(self._mcp, name)
