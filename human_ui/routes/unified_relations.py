# -*- coding: utf-8 -*-
"""Unified Relations CRUD API -- atom/entry 混合端點"""

from flask import Blueprint, request, jsonify
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import (
    UnifiedRelation, AtomRelation, KnowledgeAtom, AtomEntry,
)

bp = Blueprint('unified_relations', __name__)


def _resolve_endpoint(s, data, prefix):
    """解析端點參數，回傳 (atom_id, entry_id)，二擇一。"""
    atom_id = data.get(f'{prefix}_atom_id')
    entry_id = data.get(f'{prefix}_entry_id')

    if atom_id and entry_id:
        return None, None, f'{prefix} 只能指定 atom_id 或 entry_id 其一'
    if not atom_id and not entry_id:
        return None, None, f'{prefix} 必須指定 atom_id 或 entry_id'

    if atom_id:
        obj = s.get(KnowledgeAtom, atom_id)
        if not obj:
            return None, None, f'{prefix}_atom_id={atom_id} 不存在'
        return atom_id, None, None
    else:
        obj = s.get(AtomEntry, entry_id)
        if not obj:
            return None, None, f'{prefix}_entry_id={entry_id} 不存在'
        return None, entry_id, None


def _rel_to_dict(rel, s):
    """轉換 UnifiedRelation 為 dict。"""
    d = rel.to_dict()
    # 附加來源/目標的摘要資訊
    if rel.from_atom_id:
        a = s.get(KnowledgeAtom, rel.from_atom_id)
        d['from_label'] = a.title if a else ''
        d['from_type'] = 'atom'
    else:
        e = s.get(AtomEntry, rel.from_entry_id)
        d['from_label'] = (e.raw_text[:50] if e else '')
        d['from_type'] = 'entry'
    if rel.to_atom_id:
        a = s.get(KnowledgeAtom, rel.to_atom_id)
        d['to_label'] = a.title if a else ''
        d['to_type'] = 'atom'
    else:
        e = s.get(AtomEntry, rel.to_entry_id)
        d['to_label'] = (e.raw_text[:50] if e else '')
        d['to_type'] = 'entry'
    return d


@bp.route('/api/unified-relations', methods=['GET'])
def list_unified_relations():
    """查詢 unified relations。

    Query params (全部可選):
      atom_id   - 相關的原子 ID（from 或 to）
      entry_id  - 相關的 entry ID（from 或 to）
      type      - 關係類型篩選
    """
    atom_id = request.args.get('atom_id', type=int)
    entry_id = request.args.get('entry_id', type=int)
    rel_type = request.args.get('type')

    with session_scope() as s:
        q = s.query(UnifiedRelation)

        if atom_id:
            q = q.filter(
                (UnifiedRelation.from_atom_id == atom_id) |
                (UnifiedRelation.to_atom_id == atom_id)
            )
        if entry_id:
            q = q.filter(
                (UnifiedRelation.from_entry_id == entry_id) |
                (UnifiedRelation.to_entry_id == entry_id)
            )
        if rel_type:
            q = q.filter(UnifiedRelation.relation_type == rel_type)

        rels = q.order_by(UnifiedRelation.created_at.desc()).limit(200).all()
        return jsonify([_rel_to_dict(r, s) for r in rels])


@bp.route('/api/unified-relations', methods=['POST'])
def create_unified_relation():
    """建立一條 unified relation。

    body: {
      from_atom_id / from_entry_id,
      to_atom_id / to_entry_id,
      relation_type, label?, confidence?
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': '需要 JSON body'}), 400

    rel_type = data.get('relation_type', '')
    if rel_type not in UnifiedRelation.VALID_TYPES:
        return jsonify({
            'error': f"無效的 relation_type: {rel_type}，"
                     f"允許: {', '.join(UnifiedRelation.VALID_TYPES)}"
        }), 400

    with session_scope() as s:
        from_atom, from_entry, err = _resolve_endpoint(s, data, 'from')
        if err:
            return jsonify({'error': err}), 400
        to_atom, to_entry, err = _resolve_endpoint(s, data, 'to')
        if err:
            return jsonify({'error': err}), 400

        rel = UnifiedRelation(
            from_atom_id=from_atom,
            from_entry_id=from_entry,
            to_atom_id=to_atom,
            to_entry_id=to_entry,
            relation_type=rel_type,
            label=data.get('label', ''),
            confidence=data.get('confidence', 1.0),
            created_by=data.get('created_by', 'human'),
        )
        s.add(rel)
        s.flush()
        return jsonify(_rel_to_dict(rel, s)), 201


@bp.route('/api/unified-relations/<int:rel_id>', methods=['PUT'])
def update_unified_relation(rel_id):
    data = request.get_json()
    with session_scope() as s:
        rel = s.get(UnifiedRelation, rel_id)
        if not rel:
            return jsonify({'error': '關係不存在'}), 404

        for attr in ('label', 'confidence', 'created_by'):
            if attr in data:
                setattr(rel, attr, data[attr])

        if 'relation_type' in data:
            rt = data['relation_type']
            if rt not in UnifiedRelation.VALID_TYPES:
                return jsonify({'error': f'無效的 relation_type: {rt}'}), 400
            rel.relation_type = rt

        s.flush()
        return jsonify(_rel_to_dict(rel, s))


@bp.route('/api/unified-relations/<int:rel_id>', methods=['DELETE'])
def delete_unified_relation(rel_id):
    with session_scope() as s:
        rel = s.get(UnifiedRelation, rel_id)
        if not rel:
            return jsonify({'error': '關係不存在'}), 404
        s.delete(rel)
        return jsonify({'message': f'關係 {rel_id} 已刪除'})
