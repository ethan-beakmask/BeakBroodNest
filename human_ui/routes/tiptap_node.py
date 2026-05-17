# -*- coding: utf-8 -*-
"""Tiptap 結構性節點 nodeId 分配 API

POST /api/tiptap/next-id        -> {id: int}
POST /api/tiptap/next-ids       -> body {count: int}，回 {ids: [int,...]}
                                   count 上限 256，避免被濫用耗 sequence

對應 core/tiptap_node_id.py，前端 node-id-extension 透過此 API 取得新節點 ID。
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from core.db import session_scope

bp = Blueprint('tiptap_node', __name__)

MAX_BATCH = 256


@bp.route('/api/tiptap/next-id', methods=['POST'])
def next_id():
    with session_scope() as s:
        nid = int(s.execute(text("SELECT nextval('tiptap_node_id_seq')")).scalar())
    return jsonify({'id': nid})


@bp.route('/api/tiptap/next-ids', methods=['POST'])
def next_ids():
    data = request.get_json(silent=True) or {}
    try:
        count = int(data.get('count', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'count 須為整數'}), 400
    if count <= 0:
        return jsonify({'error': 'count 須 > 0'}), 400
    if count > MAX_BATCH:
        return jsonify({'error': f'count 上限 {MAX_BATCH}'}), 400

    with session_scope() as s:
        rows = s.execute(
            text("SELECT nextval('tiptap_node_id_seq') FROM generate_series(1, :n)"),
            {'n': count},
        ).fetchall()
    return jsonify({'ids': [int(r[0]) for r in rows]})
