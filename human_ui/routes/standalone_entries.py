# -*- coding: utf-8 -*-
"""白板獨立 structuredEntry API（P3a）

CRUD：
  GET    /api/standalone-entries                列出（含過濾）
  POST   /api/standalone-entries                建立（自動分配 node_id）
  GET    /api/standalone-entries/<id>           單一
  PUT    /api/standalone-entries/<id>           更新
  DELETE /api/standalone-entries/<id>           軟刪
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request
from sqlalchemy import desc

from core.db import session_scope
from core.models import StandaloneEntry, EntrySchema, CanvasStandaloneEntry
from core.tiptap_node_id import allocate_node_id

bp = Blueprint('standalone_entries', __name__)
logger = logging.getLogger('beak_broodnest')


MAX_RAW_TEXT = 64 * 1024
MAX_SUMMARY = 200
MAX_FV_KEYS = 64


def _validate_payload(data):
    """檢查 payload 安全限制（與 BBN security red lines 一致）"""
    if not isinstance(data, dict):
        return '需要 JSON body'
    raw_text = data.get('raw_text', '')
    if not isinstance(raw_text, str):
        return 'raw_text 須為字串'
    if len(raw_text) > MAX_RAW_TEXT:
        return f'raw_text 超過上限 {MAX_RAW_TEXT}'
    summary = data.get('summary', '')
    if not isinstance(summary, str):
        return 'summary 須為字串'
    if len(summary) > MAX_SUMMARY:
        return f'summary 超過上限 {MAX_SUMMARY}'
    fv = data.get('field_values', {})
    if fv is not None and not isinstance(fv, dict):
        return 'field_values 須為物件'
    if isinstance(fv, dict) and len(fv) > MAX_FV_KEYS:
        return f'field_values 鍵數量上限 {MAX_FV_KEYS}'
    return None


@bp.route('/api/standalone-entries', methods=['GET'])
def list_standalone_entries():
    schema_code = request.args.get('schema_code')
    include_deleted = request.args.get('include_deleted') == 'true'
    limit = min(int(request.args.get('limit', 100)), 500)

    with session_scope() as s:
        q = s.query(StandaloneEntry)
        if not include_deleted:
            q = q.filter(StandaloneEntry.is_deleted == False)  # noqa: E712
        if schema_code:
            q = q.filter(StandaloneEntry.schema_code == schema_code)
        q = q.order_by(desc(StandaloneEntry.updated_at)).limit(limit)
        rows = q.all()
        return jsonify([e.to_dict() for e in rows])


@bp.route('/api/standalone-entries', methods=['POST'])
def create_standalone_entry():
    data = request.get_json(silent=True)
    err = _validate_payload(data)
    if err:
        return jsonify({'error': err}), 400

    schema_code = data.get('schema_code', 'freetext')
    if not isinstance(schema_code, str) or not schema_code:
        return jsonify({'error': 'schema_code 必填'}), 400

    with session_scope() as s:
        schema = s.query(EntrySchema).filter_by(code=schema_code).first()
        if not schema:
            return jsonify({'error': f'未知 schema_code: {schema_code}'}), 400

        entry = StandaloneEntry(
            schema_id=schema.id,
            schema_code=schema_code,
            raw_text=data.get('raw_text', ''),
            summary=data.get('summary', ''),
            field_values=data.get('field_values', {}) or {},
            node_id=allocate_node_id(s),  # 驗證 P2 sequence 機制
            owner=data.get('owner', 'ethan'),
            sensitivity=data.get('sensitivity', 'internal'),
        )
        s.add(entry)
        s.flush()
        logger.info(f'standalone_entry {entry.id} created (node_id={entry.node_id}, schema={schema_code})')
        return jsonify(entry.to_dict()), 201


@bp.route('/api/standalone-entries/<int:entry_id>', methods=['GET'])
def get_standalone_entry(entry_id):
    with session_scope() as s:
        e = s.get(StandaloneEntry, entry_id)
        if not e:
            return jsonify({'error': 'entry 不存在'}), 404
        return jsonify(e.to_dict())


@bp.route('/api/standalone-entries/<int:entry_id>', methods=['PUT'])
def update_standalone_entry(entry_id):
    data = request.get_json(silent=True)
    err = _validate_payload(data)
    if err:
        return jsonify({'error': err}), 400

    with session_scope() as s:
        e = s.get(StandaloneEntry, entry_id)
        if not e or e.is_deleted:
            return jsonify({'error': 'entry 不存在'}), 404

        # schema_code 可變更（;;td → ;;cal 等），但 schema_id 對應 schema 必須存在
        if 'schema_code' in data:
            new_code = data['schema_code']
            if not isinstance(new_code, str) or not new_code:
                return jsonify({'error': 'schema_code 須為非空字串'}), 400
            schema = s.query(EntrySchema).filter_by(code=new_code).first()
            if not schema:
                return jsonify({'error': f'未知 schema_code: {new_code}'}), 400
            e.schema_id = schema.id
            e.schema_code = new_code

        for field in ('raw_text', 'summary'):
            if field in data:
                setattr(e, field, data[field])
        if 'field_values' in data:
            e.field_values = data['field_values'] or {}
        if 'owner' in data:
            e.owner = data['owner']
        if 'sensitivity' in data:
            e.sensitivity = data['sensitivity']

        s.flush()
        return jsonify(e.to_dict())


@bp.route('/api/standalone-entries/<int:entry_id>', methods=['DELETE'])
def delete_standalone_entry(entry_id):
    with session_scope() as s:
        e = s.get(StandaloneEntry, entry_id)
        if not e:
            return jsonify({'error': 'entry 不存在'}), 404
        e.is_deleted = True
        # 清理白板上的殘留 placement
        s.query(CanvasStandaloneEntry).filter(
            CanvasStandaloneEntry.standalone_entry_id == entry_id
        ).delete()
        return jsonify({'message': f'standalone entry {entry_id} 已刪除'})
