# -*- coding: utf-8 -*-
"""Tags API"""

from flask import Blueprint, request, jsonify

from core.db import session_scope
from core.models import Tag

bp = Blueprint('tags', __name__)


@bp.route('/api/tags', methods=['GET'])
def list_tags():
    with session_scope() as s:
        tags = s.query(Tag).order_by(Tag.tag_type, Tag.name).all()
        return jsonify([t.to_dict() for t in tags])


@bp.route('/api/tags', methods=['POST'])
def create_tag():
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({'error': '需要 name 欄位'}), 400

    with session_scope() as s:
        tag = Tag(
            name=data['name'],
            color=data.get('color', '#6b7280'),
            parent_tag_id=data.get('parent_tag_id'),
            tag_type=data.get('tag_type', 'tag'),
        )
        s.add(tag)
        s.flush()
        return jsonify(tag.to_dict()), 201


@bp.route('/api/tags/<int:tag_id>', methods=['PUT'])
def update_tag(tag_id):
    data = request.get_json()
    with session_scope() as s:
        tag = s.get(Tag, tag_id)
        if not tag:
            return jsonify({'error': '標籤不存在'}), 404
        for field in ('name', 'color', 'parent_tag_id', 'tag_type'):
            if field in data:
                setattr(tag, field, data[field])
        s.flush()
        return jsonify(tag.to_dict())


@bp.route('/api/tags/<int:tag_id>', methods=['DELETE'])
def delete_tag(tag_id):
    with session_scope() as s:
        tag = s.get(Tag, tag_id)
        if not tag:
            return jsonify({'error': '標籤不存在'}), 404
        s.delete(tag)
        return jsonify({'message': f'標籤 {tag_id} 已刪除'})
