# -*- coding: utf-8 -*-
"""Relations API + Block Chain（使用 unified_relations）"""

from flask import Blueprint, request, jsonify

from core.db import session_scope
from core import relations as rel_service

bp = Blueprint('relations', __name__)


@bp.route('/api/relations', methods=['POST'])
def create_relation():
    """建立因果關係（atom-atom）"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '需要 JSON body'}), 400

    required = ('from_atom_id', 'to_atom_id', 'relation_type')
    for f in required:
        if f not in data:
            return jsonify({'error': f'缺少必要欄位: {f}'}), 400

    with session_scope() as s:
        try:
            rel = rel_service.create_relation(
                s,
                relation_type=data['relation_type'],
                from_atom_id=data['from_atom_id'],
                to_atom_id=data['to_atom_id'],
                label=data.get('label', ''),
                confidence=data.get('confidence', 1.0),
                created_by=data.get('created_by', 'human'),
            )
            return jsonify(rel.to_dict()), 201
        except ValueError as e:
            return jsonify({'error': str(e)}), 400


@bp.route('/api/relations/<int:relation_id>', methods=['DELETE'])
def delete_relation(relation_id):
    """軟刪除關係"""
    with session_scope() as s:
        if rel_service.soft_delete_relation(s, relation_id):
            return jsonify({'message': f'關係 {relation_id} 已刪除'})
        return jsonify({'error': '關係不存在'}), 404


@bp.route('/api/atoms/<int:atom_id>/block-chain', methods=['GET'])
def get_block_chain(atom_id):
    """取得某卡片的阻塞鍊"""
    max_depth = request.args.get('max_depth', 10, type=int)
    with session_scope() as s:
        chain = rel_service.trace_block_chain(s, atom_id, max_depth)
        return jsonify({
            'atom_id': atom_id,
            'is_blocked': len(chain) > 0,
            'chain': chain,
        })


@bp.route('/api/relation-types', methods=['GET'])
def list_relation_types():
    """取得所有關係類型定義（from registry）"""
    with session_scope() as s:
        types = rel_service.get_relation_types(s)
        return jsonify(types)
