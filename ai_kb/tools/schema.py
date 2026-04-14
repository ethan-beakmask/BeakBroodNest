# -*- coding: utf-8 -*-
"""Schema + Overview 工具: schema_create/list, note_overview"""
import json
import logging

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import (
    KnowledgeAtom, AtomRelation, Tag, atom_tags,
    AtomSchema, SchemaField,
)
from core import relations as rel_service

logger = logging.getLogger('beak_cortex.mcp')


def register(mcp):

    @mcp.tool()
    def schema_create(
        name: str,
        slug: str,
        description: str = '',
        icon: str = '',
        fields: list[dict] | None = None,
    ) -> str:
        """建立一個 E 類型套表的 schema 定義。

        name: schema 顯示名稱
        slug: 唯一識別碼（英文小寫+底線，如 perf_test）
        description: 用途說明
        icon: 圖示（選填）
        fields: 欄位定義列表，每個欄位為 dict:
          {
            "name": "欄位識別名（英文）",
            "label": "欄位顯示名（中文）",
            "field_type": "text|number|date|select|multiselect|checkbox|url|relation",
            "options": "select/multiselect 的選項，逗號分隔",
            "required": false,
            "sort_order": 0
          }

        回傳建立的 schema ID 與欄位列表。
        """
        with session_scope() as s:
            existing = s.query(AtomSchema).filter(AtomSchema.slug == slug).first()
            if existing:
                return json.dumps({'error': f'slug "{slug}" 已存在 (id={existing.id})'})

            schema = AtomSchema(
                name=name,
                slug=slug,
                description=description,
                icon=icon,
            )
            s.add(schema)
            s.flush()

            if fields:
                for i, fd in enumerate(fields):
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

            schema_fields = s.query(SchemaField).filter(
                SchemaField.schema_id == schema.id
            ).order_by(SchemaField.sort_order).all()

            return json.dumps({
                'id': schema.id,
                'name': schema.name,
                'slug': schema.slug,
                'description': schema.description,
                'fields': [f.to_dict() for f in schema_fields],
                'message': f'Schema "{name}" 已建立 (id={schema.id})',
            }, ensure_ascii=False)

    @mcp.tool()
    def schema_list() -> str:
        """列出所有套表 schema 及其欄位定義。

        用途：查看可用的 E 類型 schema，以便建立套表原子時指定 schema_id。
        """
        with session_scope() as s:
            schemas = (
                s.query(AtomSchema)
                .options(joinedload(AtomSchema.fields))
                .order_by(AtomSchema.id)
                .all()
            )

            result = []
            for schema in schemas:
                atom_count = s.query(KnowledgeAtom).filter(
                    KnowledgeAtom.schema_id == schema.id,
                    KnowledgeAtom.is_deleted == False,
                ).count()
                result.append({
                    'id': schema.id,
                    'name': schema.name,
                    'slug': schema.slug,
                    'description': schema.description,
                    'atom_count': atom_count,
                    'fields': [f.to_dict() for f in schema.fields],
                })

            return json.dumps({
                'total': len(result),
                'schemas': result,
            }, ensure_ascii=False)

    @mcp.tool()
    def note_overview() -> str:
        """取得知識庫整體概覽：各類型/生命週期計數、最近活躍原子、阻塞中的項目。

        用途：快速了解當前知識庫的狀態，而非逐條翻閱。
        """
        with session_scope() as s:
            base = s.query(KnowledgeAtom).filter(KnowledgeAtom.is_deleted == False)

            type_counts = dict(
                base.with_entities(
                    KnowledgeAtom.atom_type,
                    func.count(KnowledgeAtom.id),
                ).group_by(KnowledgeAtom.atom_type).all()
            )

            lifecycle_counts = dict(
                base.with_entities(
                    KnowledgeAtom.lifecycle,
                    func.count(KnowledgeAtom.id),
                ).group_by(KnowledgeAtom.lifecycle).all()
            )

            source_counts = dict(
                base.with_entities(
                    KnowledgeAtom.source,
                    func.count(KnowledgeAtom.id),
                ).group_by(KnowledgeAtom.source).all()
            )

            total = base.count()

            recent = (
                base.order_by(KnowledgeAtom.updated_at.desc())
                .limit(10)
                .all()
            )

            blocked_atom_ids = (
                s.query(AtomRelation.to_atom_id)
                .filter(AtomRelation.relation_type == 'blocks')
                .distinct()
                .subquery()
            )
            blocked_atoms = (
                s.query(KnowledgeAtom)
                .filter(
                    KnowledgeAtom.id.in_(blocked_atom_ids),
                    KnowledgeAtom.lifecycle.in_(['active', 'aging']),
                    KnowledgeAtom.is_deleted == False,
                )
                .all()
            )
            truly_blocked = []
            for ba in blocked_atoms:
                blockers = rel_service.get_blockers(s, ba.id)
                if blockers:
                    truly_blocked.append({
                        'id': ba.id,
                        'title': ba.title,
                        'blocked_by': [{'id': b.id, 'title': b.title} for b in blockers],
                    })

            tag_counts = (
                s.query(Tag.name, func.count(atom_tags.c.atom_id))
                .join(atom_tags, Tag.id == atom_tags.c.tag_id)
                .group_by(Tag.name)
                .order_by(func.count(atom_tags.c.atom_id).desc())
                .limit(20)
                .all()
            )

            type_labels = {
                'A': '萬用', 'B': '發散', 'C': '流程',
                'D': '歸納', 'E': '套表', 'F': '碎片',
            }

            return json.dumps({
                'total_atoms': total,
                'by_type': {f'{k}({type_labels.get(k, k)})': v for k, v in type_counts.items()},
                'by_lifecycle': lifecycle_counts,
                'by_source': source_counts,
                'top_tags': [{'name': name, 'count': cnt} for name, cnt in tag_counts],
                'recently_updated': [
                    {
                        'id': a.id,
                        'title': a.title,
                        'atom_type': a.atom_type,
                        'lifecycle': a.lifecycle,
                        'updated_at': a.updated_at.isoformat() if a.updated_at else None,
                    }
                    for a in recent
                ],
                'blocked_items': truly_blocked,
            }, ensure_ascii=False)
