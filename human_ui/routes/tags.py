# -*- coding: utf-8 -*-
"""Tags & Tag Categories API"""

from flask import Blueprint, request, jsonify

from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import Tag, TagCategory, tag_category_members

bp = Blueprint('tags', __name__)


# ============================================================
# Tag Categories
# ============================================================

@bp.route('/api/tag-categories', methods=['GET'])
def list_tag_categories():
    with session_scope() as s:
        cats = s.query(TagCategory).order_by(TagCategory.sort_order, TagCategory.name).all()
        return jsonify([c.to_dict() for c in cats])


@bp.route('/api/tag-categories', methods=['POST'])
def create_tag_category():
    data = request.get_json()
    if not data or not data.get('name', '').strip():
        return jsonify({'error': '需要 name 欄位'}), 400
    with session_scope() as s:
        cat = TagCategory(
            name=data['name'].strip(),
            sort_order=data.get('sort_order', 0),
        )
        s.add(cat)
        s.flush()
        return jsonify(cat.to_dict()), 201


@bp.route('/api/tag-categories/<int:cat_id>', methods=['PUT'])
def update_tag_category(cat_id):
    data = request.get_json()
    with session_scope() as s:
        cat = s.get(TagCategory, cat_id)
        if not cat:
            return jsonify({'error': '分類不存在'}), 404
        if 'name' in data:
            cat.name = data['name'].strip()
        if 'sort_order' in data:
            cat.sort_order = data['sort_order']
        s.flush()
        return jsonify(cat.to_dict())


@bp.route('/api/tag-categories/<int:cat_id>', methods=['DELETE'])
def delete_tag_category(cat_id):
    with session_scope() as s:
        cat = s.get(TagCategory, cat_id)
        if not cat:
            return jsonify({'error': '分類不存在'}), 404
        s.delete(cat)
        return jsonify({'message': f'分類 {cat_id} 已刪除'})


# ============================================================
# Tags
# ============================================================

@bp.route('/api/tags', methods=['GET'])
def list_tags():
    with session_scope() as s:
        tags = (s.query(Tag)
                .options(joinedload(Tag.categories))
                .order_by(Tag.tag_type, Tag.name).all())
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
            category_id=data.get('category_id'),
        )
        s.add(tag)
        s.flush()
        return jsonify(tag.to_dict()), 201


@bp.route('/api/tags/<int:tag_id>', methods=['PUT'])
def update_tag(tag_id):
    data = request.get_json()
    with session_scope() as s:
        tag = s.query(Tag).options(joinedload(Tag.categories)).filter(Tag.id == tag_id).first()
        if not tag:
            return jsonify({'error': '標籤不存在'}), 404
        for field in ('name', 'color', 'parent_tag_id', 'tag_type'):
            if field in data:
                setattr(tag, field, data[field])
        # 多對多分類更新
        if 'category_ids' in data:
            cat_ids = data['category_ids'] or []
            cats = s.query(TagCategory).filter(TagCategory.id.in_(cat_ids)).all() if cat_ids else []
            tag.categories = cats
        # 向下相容：舊的 category_id 單一值
        elif 'category_id' in data:
            cid = data['category_id']
            if cid:
                cat = s.get(TagCategory, cid)
                tag.categories = [cat] if cat else []
            else:
                tag.categories = []
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
