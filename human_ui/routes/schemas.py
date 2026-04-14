# -*- coding: utf-8 -*-
"""Schema API (E-type forms) + Field Values"""

from flask import Blueprint, request, jsonify
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import KnowledgeAtom, AtomSchema, SchemaField, AtomFieldValue

bp = Blueprint('schemas', __name__)


@bp.route('/api/schemas', methods=['GET'])
def list_schemas():
    with session_scope() as s:
        schemas = s.query(AtomSchema).options(
            joinedload(AtomSchema.fields)
        ).order_by(AtomSchema.id).all()
        result = []
        for schema in schemas:
            d = schema.to_dict()
            d['fields'] = [f.to_dict() for f in schema.fields]
            d['atom_count'] = s.query(KnowledgeAtom).filter(
                KnowledgeAtom.schema_id == schema.id,
                KnowledgeAtom.is_deleted == False,
            ).count()
            result.append(d)
        return jsonify(result)


@bp.route('/api/schemas', methods=['POST'])
def create_schema():
    data = request.get_json()
    if not data or 'name' not in data or 'slug' not in data:
        return jsonify({'error': '需要 name 和 slug 欄位'}), 400

    with session_scope() as s:
        existing = s.query(AtomSchema).filter(AtomSchema.slug == data['slug']).first()
        if existing:
            return jsonify({'error': f'slug "{data["slug"]}" 已存在'}), 409

        schema = AtomSchema(
            name=data['name'],
            slug=data['slug'],
            description=data.get('description', ''),
            icon=data.get('icon', ''),
        )
        s.add(schema)
        s.flush()

        for i, fd in enumerate(data.get('fields', [])):
            sf = SchemaField(
                schema_id=schema.id,
                name=fd.get('name', ''),
                label=fd.get('label', fd.get('name', '')),
                field_type=fd.get('field_type', 'text'),
                options=fd.get('options', ''),
                required=fd.get('required', False),
                sort_order=fd.get('sort_order', i),
            )
            s.add(sf)
        s.flush()

        d = schema.to_dict()
        d['fields'] = [f.to_dict() for f in s.query(SchemaField).filter(
            SchemaField.schema_id == schema.id
        ).order_by(SchemaField.sort_order).all()]
        return jsonify(d), 201


@bp.route('/api/schemas/<int:schema_id>', methods=['GET'])
def get_schema(schema_id):
    with session_scope() as s:
        schema = s.query(AtomSchema).options(
            joinedload(AtomSchema.fields)
        ).filter(AtomSchema.id == schema_id).first()
        if not schema:
            return jsonify({'error': 'Schema 不存在'}), 404
        d = schema.to_dict()
        d['fields'] = [f.to_dict() for f in schema.fields]

        atoms = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.schema_id == schema_id,
            KnowledgeAtom.is_deleted == False,
        ).order_by(KnowledgeAtom.created_at.desc()).all()

        rows = []
        for a in atoms:
            fvs = s.query(AtomFieldValue).options(
                joinedload(AtomFieldValue.field)
            ).filter(AtomFieldValue.atom_id == a.id).all()
            rows.append({
                'atom_id': a.id,
                'title': a.title,
                'content': a.content,
                'field_values': {fv.field.name: fv.value for fv in fvs if fv.field},
                'created_at': a.created_at.isoformat() if a.created_at else None,
            })
        d['atoms'] = rows
        return jsonify(d)


@bp.route('/api/schemas/<int:schema_id>', methods=['DELETE'])
def delete_schema(schema_id):
    with session_scope() as s:
        schema = s.query(AtomSchema).filter(AtomSchema.id == schema_id).first()
        if not schema:
            return jsonify({'error': 'Schema 不存在'}), 404
        s.query(KnowledgeAtom).filter(
            KnowledgeAtom.schema_id == schema_id
        ).update({'schema_id': None})
        s.delete(schema)
        return jsonify({'message': f'Schema {schema_id} 已刪除'})


@bp.route('/api/atoms/<int:atom_id>/field-values', methods=['POST'])
def set_field_values(atom_id):
    """批量設定 E 類型原子的欄位值。body: {"values": {"field_name": "value"}}"""
    data = request.get_json()
    if not data or 'values' not in data:
        return jsonify({'error': '需要 values 欄位'}), 400

    with session_scope() as s:
        atom = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False
        ).first()
        if not atom:
            return jsonify({'error': '原子不存在'}), 404
        if not atom.schema_id:
            return jsonify({'error': '此原子未關聯 schema'}), 400

        schema_fields = s.query(SchemaField).filter(
            SchemaField.schema_id == atom.schema_id
        ).all()
        field_map = {f.name: f for f in schema_fields}

        for fname, fval in data['values'].items():
            if fname not in field_map:
                continue
            existing = s.query(AtomFieldValue).filter(
                AtomFieldValue.atom_id == atom_id,
                AtomFieldValue.field_id == field_map[fname].id,
            ).first()
            if existing:
                existing.value = str(fval) if fval is not None else None
            else:
                s.add(AtomFieldValue(
                    atom_id=atom_id,
                    field_id=field_map[fname].id,
                    value=str(fval) if fval is not None else None,
                ))
        s.flush()
        return jsonify({'message': f'原子 {atom_id} 欄位值已更新'})
