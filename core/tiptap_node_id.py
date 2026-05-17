# -*- coding: utf-8 -*-
"""Tiptap 結構性節點 nodeId 工具

提供：
- STRUCTURAL_NODE_TYPES：必須持有 nodeId 的節點型別清單（單一定義來源）
- allocate_node_id(session)：自 sequence 取下一個 ID
- backfill_missing_node_ids(session, doc)：對單一 Tiptap doc 補缺的 nodeId
                                          回傳 (補了幾個, 新 doc)

這是 atoms 儲存路徑的守門邏輯，避免前端遺漏導致 content_json 內節點缺 ID。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session


# 必須補 nodeId 的節點型別（與 scripts/backfill_tiptap_node_id.py 保持同步）
STRUCTURAL_NODE_TYPES = frozenset({
    'structuredEntry',
    'image',
    'imageAlbum',
    'htmlBlock',
    'pdfThumbnail',
    'pdfReader',
    'mermaidBlock',
    'heading',
    'table',
    'taskList',
    'taskItem',
    'bulletList',
    'orderedList',
    'blockquote',
    'codeBlock',
})


def allocate_node_id(session: Session) -> int:
    """從 sequence 取一個新 nodeId"""
    return int(session.execute(text("SELECT nextval('tiptap_node_id_seq')")).scalar())


def _walk_and_fill(node, session, stats):
    if not isinstance(node, dict):
        return
    if node.get('type') in STRUCTURAL_NODE_TYPES:
        attrs = node.get('attrs')
        if not isinstance(attrs, dict):
            attrs = {}
            node['attrs'] = attrs
        if attrs.get('nodeId') is None:
            attrs['nodeId'] = allocate_node_id(session)
            stats['filled'] += 1
    content = node.get('content')
    if isinstance(content, list):
        for child in content:
            _walk_and_fill(child, session, stats)


def backfill_missing_node_ids(session: Session, doc) -> Tuple[int, object]:
    """對單一 Tiptap doc (dict) 補缺的 nodeId。

    回傳 (補了幾個, 新 doc)。若 doc 非 dict 或無缺 ID 則回傳 (0, doc) 不複製。
    """
    if not isinstance(doc, dict):
        return 0, doc
    new_doc = deepcopy(doc)
    stats = {'filled': 0}
    _walk_and_fill(new_doc, session, stats)
    if stats['filled'] == 0:
        return 0, doc
    return stats['filled'], new_doc
