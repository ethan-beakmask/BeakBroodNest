# -*- coding: utf-8 -*-
"""MCP 工具註冊入口"""

from . import knowledge, schema, orchestrator, canvas, sanitize, messaging


def register_all(mcp):
    """將所有工具註冊到 FastMCP 實例"""
    knowledge.register(mcp)
    schema.register(mcp)
    orchestrator.register(mcp)
    canvas.register(mcp)
    sanitize.register(mcp)
    messaging.register(mcp)
