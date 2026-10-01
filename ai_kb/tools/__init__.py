# -*- coding: utf-8 -*-
"""MCP 工具註冊入口"""

from . import knowledge, schema, orchestrator, canvas, sanitize, messaging, project, task
from .param_guard import GuardedMCP


def register_all(mcp):
    """將所有工具註冊到 FastMCP 實例"""
    guarded = GuardedMCP(mcp)
    knowledge.register(guarded)
    schema.register(guarded)
    orchestrator.register(guarded)
    canvas.register(guarded)
    sanitize.register(guarded)
    messaging.register(guarded)
    project.register(guarded)
    task.register(guarded)
