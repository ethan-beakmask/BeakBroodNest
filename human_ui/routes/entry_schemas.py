# -*- coding: utf-8 -*-
"""Entry Schema & Fields CRUD API"""

from flask import Blueprint, request, jsonify
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import EntrySchema, EntrySchemaField

bp = Blueprint('entry_schemas', __name__)


# ============================================================
# Entry Schemas
# ============================================================

@bp.route('/api/entry-schemas', methods=['GET'])
def list_entry_schemas():
    with session_scope() as s:
        schemas = (
            s.query(EntrySchema)
            .options(joinedload(EntrySchema.fields))
            .order_by(EntrySchema.sort_order, EntrySchema.name)
            .all()
        )
        return jsonify([es.to_dict(include_fields=True) for es in schemas])


@bp.route('/api/entry-schemas', methods=['POST'])
def create_entry_schema():
    data = request.get_json()
    if not data or not data.get('name', '').strip():
        return jsonify({'error': '需要 name 欄位'}), 400
    if not data.get('code', '').strip():
        return jsonify({'error': '需要 code 欄位'}), 400

    with session_scope() as s:
        existing = s.query(EntrySchema).filter_by(code=data['code'].strip()).first()
        if existing:
            return jsonify({'error': f"code '{data['code']}' 已存在"}), 409

        alias = data.get('slash_alias', '').strip() or None
        if alias:
            dup = s.query(EntrySchema).filter_by(slash_alias=alias).first()
            if dup:
                return jsonify({'error': f"slash_alias '{alias}' 已被 {dup.code} 使用"}), 409

        es = EntrySchema(
            code=data['code'].strip(),
            name=data['name'].strip(),
            icon=data.get('icon', ''),
            color=data.get('color', '#6b7280'),
            slash_alias=alias,
            is_system=False,
            sort_order=data.get('sort_order', 0),
        )
        s.add(es)
        s.flush()
        return jsonify(es.to_dict(include_fields=True)), 201


@bp.route('/api/entry-schemas/<int:schema_id>', methods=['PUT'])
def update_entry_schema(schema_id):
    data = request.get_json()
    with session_scope() as s:
        es = s.query(EntrySchema).options(joinedload(EntrySchema.fields)).get(schema_id)
        if not es:
            return jsonify({'error': '記錄類型不存在'}), 404

        for field in ('name', 'icon', 'color', 'sort_order'):
            if field in data:
                setattr(es, field, data[field])

        if 'slash_alias' in data:
            alias = data['slash_alias'].strip() if data['slash_alias'] else None
            if alias:
                dup = (
                    s.query(EntrySchema)
                    .filter(EntrySchema.slash_alias == alias, EntrySchema.id != schema_id)
                    .first()
                )
                if dup:
                    return jsonify({'error': f"slash_alias '{alias}' 已被 {dup.code} 使用"}), 409
            es.slash_alias = alias

        # 系統類型不允許改 code
        if 'code' in data and not es.is_system:
            new_code = data['code'].strip()
            dup = (
                s.query(EntrySchema)
                .filter(EntrySchema.code == new_code, EntrySchema.id != schema_id)
                .first()
            )
            if dup:
                return jsonify({'error': f"code '{new_code}' 已存在"}), 409
            es.code = new_code

        s.flush()
        return jsonify(es.to_dict(include_fields=True))


@bp.route('/api/entry-schemas/<int:schema_id>', methods=['DELETE'])
def delete_entry_schema(schema_id):
    with session_scope() as s:
        es = s.get(EntrySchema, schema_id)
        if not es:
            return jsonify({'error': '記錄類型不存在'}), 404
        if es.is_system:
            return jsonify({'error': '系統內建類型不可刪除'}), 403
        s.delete(es)
        return jsonify({'message': f'記錄類型 {es.code} 已刪除'})


# ============================================================
# Entry Schema Fields
# ============================================================

@bp.route('/api/entry-schemas/<int:schema_id>/fields', methods=['GET'])
def list_fields(schema_id):
    with session_scope() as s:
        es = s.get(EntrySchema, schema_id)
        if not es:
            return jsonify({'error': '記錄類型不存在'}), 404
        fields = (
            s.query(EntrySchemaField)
            .filter_by(schema_id=schema_id)
            .order_by(EntrySchemaField.sort_order)
            .all()
        )
        return jsonify([f.to_dict() for f in fields])


@bp.route('/api/entry-schemas/<int:schema_id>/fields', methods=['POST'])
def create_field(schema_id):
    data = request.get_json()
    if not data or not data.get('name', '').strip():
        return jsonify({'error': '需要 name 欄位'}), 400
    if not data.get('label', '').strip():
        return jsonify({'error': '需要 label 欄位'}), 400

    ft = data.get('field_type', '')
    if ft not in EntrySchemaField.VALID_FIELD_TYPES:
        return jsonify({
            'error': f"無效的 field_type: {ft}，"
                     f"允許: {', '.join(EntrySchemaField.VALID_FIELD_TYPES)}"
        }), 400

    dim = data.get('dimension')
    if dim and dim not in EntrySchemaField.VALID_DIMENSIONS:
        return jsonify({
            'error': f"無效的 dimension: {dim}，允許: {', '.join(EntrySchemaField.VALID_DIMENSIONS)}"
        }), 400

    with session_scope() as s:
        es = s.get(EntrySchema, schema_id)
        if not es:
            return jsonify({'error': '記錄類型不存在'}), 404

        dup = (
            s.query(EntrySchemaField)
            .filter_by(schema_id=schema_id, name=data['name'].strip())
            .first()
        )
        if dup:
            return jsonify({'error': f"欄位名稱 '{data['name']}' 已存在"}), 409

        # 自動排序：放在最後
        max_order = (
            s.query(EntrySchemaField.sort_order)
            .filter_by(schema_id=schema_id)
            .order_by(EntrySchemaField.sort_order.desc())
            .first()
        )
        next_order = (max_order[0] + 1) if max_order else 0

        f = EntrySchemaField(
            schema_id=schema_id,
            name=data['name'].strip(),
            label=data['label'].strip(),
            field_type=ft,
            options=data.get('options', ''),
            default_value=data.get('default_value'),
            required=data.get('required', False),
            sort_order=data.get('sort_order', next_order),
            dimension=dim or None,
        )
        s.add(f)
        s.flush()
        return jsonify(f.to_dict()), 201


@bp.route('/api/entry-schema-fields/<int:field_id>', methods=['PUT'])
def update_field(field_id):
    data = request.get_json()
    with session_scope() as s:
        f = s.get(EntrySchemaField, field_id)
        if not f:
            return jsonify({'error': '欄位不存在'}), 404

        for attr in ('label', 'options', 'default_value', 'required', 'sort_order'):
            if attr in data:
                setattr(f, attr, data[attr])

        if 'field_type' in data:
            ft = data['field_type']
            if ft not in EntrySchemaField.VALID_FIELD_TYPES:
                return jsonify({'error': f"無效的 field_type: {ft}"}), 400
            f.field_type = ft

        if 'dimension' in data:
            dim = data['dimension']
            if dim and dim not in EntrySchemaField.VALID_DIMENSIONS:
                return jsonify({'error': f"無效的 dimension: {dim}"}), 400
            f.dimension = dim or None

        if 'name' in data:
            new_name = data['name'].strip()
            dup = (
                s.query(EntrySchemaField)
                .filter(
                    EntrySchemaField.schema_id == f.schema_id,
                    EntrySchemaField.name == new_name,
                    EntrySchemaField.id != field_id,
                )
                .first()
            )
            if dup:
                return jsonify({'error': f"欄位名稱 '{new_name}' 已存在"}), 409
            f.name = new_name

        s.flush()
        return jsonify(f.to_dict())


@bp.route('/api/entry-schema-fields/<int:field_id>', methods=['DELETE'])
def delete_field(field_id):
    with session_scope() as s:
        f = s.get(EntrySchemaField, field_id)
        if not f:
            return jsonify({'error': '欄位不存在'}), 404
        s.delete(f)
        return jsonify({'message': f'欄位 {field_id} 已刪除'})


@bp.route('/api/entry-schemas/<int:schema_id>/fields/reorder', methods=['PUT'])
def reorder_fields(schema_id):
    """批次更新欄位排序。body: {"field_ids": [3, 1, 2]}"""
    data = request.get_json()
    field_ids = data.get('field_ids', [])
    if not field_ids:
        return jsonify({'error': '需要 field_ids 陣列'}), 400

    with session_scope() as s:
        es = s.get(EntrySchema, schema_id)
        if not es:
            return jsonify({'error': '記錄類型不存在'}), 404

        fields = (
            s.query(EntrySchemaField)
            .filter(
                EntrySchemaField.schema_id == schema_id,
                EntrySchemaField.id.in_(field_ids),
            )
            .all()
        )
        field_map = {f.id: f for f in fields}
        for i, fid in enumerate(field_ids):
            if fid in field_map:
                field_map[fid].sort_order = i

        s.flush()
        updated = (
            s.query(EntrySchemaField)
            .filter_by(schema_id=schema_id)
            .order_by(EntrySchemaField.sort_order)
            .all()
        )
        return jsonify([f.to_dict() for f in updated])
