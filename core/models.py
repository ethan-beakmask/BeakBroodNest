"""
知識原子 ORM 模型 -- Phase 0 核心表
對應 VISION.md Section 5 的資料模型
"""
import datetime
from sqlalchemy import (
    Integer, String, Text, Float, Boolean, DateTime,
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from core.db import Base


# ============================================================
# 5.4 動態 Schema（E 類型用）
# ============================================================

class AtomSchema(Base):
    __tablename__ = 'atom_schemas'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default='')
    icon: Mapped[str] = mapped_column(String(50), default='')
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now
    )

    fields: Mapped[list["SchemaField"]] = relationship(
        back_populates='schema', cascade='all, delete-orphan',
        order_by='SchemaField.sort_order'
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'icon': self.icon,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class SchemaField(Base):
    __tablename__ = 'schema_fields'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schema_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('atom_schemas.id', ondelete='CASCADE'), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    field_type: Mapped[str] = mapped_column(String(50), nullable=False)
    options: Mapped[str] = mapped_column(Text, default='')
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    required: Mapped[bool] = mapped_column(Boolean, default=False)

    schema: Mapped["AtomSchema"] = relationship(back_populates='fields')

    def to_dict(self):
        return {
            'id': self.id,
            'schema_id': self.schema_id,
            'name': self.name,
            'label': self.label,
            'field_type': self.field_type,
            'options': self.options,
            'sort_order': self.sort_order,
            'required': self.required,
        }


# ============================================================
# 5.1 核心表：知識原子
# ============================================================

class KnowledgeAtom(Base):
    __tablename__ = 'knowledge_atoms'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 內容
    title: Mapped[str] = mapped_column(Text, nullable=False, default='')
    content: Mapped[str] = mapped_column(Text, default='')
    content_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    content_type: Mapped[str] = mapped_column(
        String(50), default='markdown'
    )  # markdown, text, checklist, table, image_ref, url, media_ref, ai_io

    # 分類
    atom_type: Mapped[str] = mapped_column(
        String(1), nullable=False, default='F'
    )  # A=萬用, B=發散, C=流程, D=歸納, E=套表, F=碎片
    schema_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('atom_schemas.id'), nullable=True
    )  # E 類型時關聯的 schema

    # 生命週期
    lifecycle: Mapped[str] = mapped_column(
        String(20), default='active'
    )  # active, aging, archived, terminal
    vitality_score: Mapped[float] = mapped_column(Float, default=1.0)

    # 時間軸
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now
    )
    last_accessed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )
    access_count: Mapped[int] = mapped_column(Integer, default=0)

    # 來源追蹤
    source: Mapped[str] = mapped_column(
        String(20), default='human'
    )  # human, ai, import, derived
    source_detail: Mapped[str] = mapped_column(Text, default='')

    # 擁有者（身份標記，非認證）
    owner: Mapped[str] = mapped_column(
        String(100), default='ethan'
    )  # ethan, claude, agent:<task_id>, claude@<host>, tool:<name>

    # 敏感度標記（為 #3013 跨機同步 / #3014 匿名共享 預埋）
    sensitivity: Mapped[str] = mapped_column(
        String(20), default='internal'
    )  # public, internal, confidential, restricted

    # 軟刪除
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    # 關聯
    schema: Mapped["AtomSchema | None"] = relationship()
    tags: Mapped[list["Tag"]] = relationship(
        secondary='atom_tags', back_populates='atoms'
    )
    field_values: Mapped[list["AtomFieldValue"]] = relationship(
        back_populates='atom', cascade='all, delete-orphan'
    )

    __table_args__ = (
        Index('idx_atoms_lifecycle', 'lifecycle'),
        Index('idx_atoms_atom_type', 'atom_type'),
        Index('idx_atoms_is_deleted', 'is_deleted'),
        Index('idx_atoms_sensitivity', 'sensitivity'),
        Index('idx_atoms_owner', 'owner'),
    )

    def to_dict(self, include_tags=False, include_values=False):
        d = {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'content_json': self.content_json,
            'content_type': self.content_type,
            'atom_type': self.atom_type,
            'schema_id': self.schema_id,
            'lifecycle': self.lifecycle,
            'vitality_score': self.vitality_score,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_accessed_at': self.last_accessed_at.isoformat() if self.last_accessed_at else None,
            'access_count': self.access_count,
            'source': self.source,
            'source_detail': self.source_detail,
            'owner': self.owner,
            'sensitivity': self.sensitivity,
        }
        if include_tags:
            d['tags'] = [t.to_dict() for t in self.tags]
        if include_values and self.field_values:
            d['field_values'] = {fv.field.name: fv.value for fv in self.field_values if fv.field}
        return d


# ============================================================
# 5.2 因果鍊
# ============================================================

class AtomRelation(Base):
    __tablename__ = 'atom_relations'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_atom_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('knowledge_atoms.id', ondelete='CASCADE'), nullable=False
    )
    to_atom_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('knowledge_atoms.id', ondelete='CASCADE'), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # 見 VALID_TYPES
    label: Mapped[str] = mapped_column(Text, default='')
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_by: Mapped[str] = mapped_column(String(20), default='human')
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )

    from_atom: Mapped["KnowledgeAtom"] = relationship(foreign_keys=[from_atom_id])
    to_atom: Mapped["KnowledgeAtom"] = relationship(foreign_keys=[to_atom_id])

    __table_args__ = (
        UniqueConstraint('from_atom_id', 'to_atom_id', 'relation_type',
                         name='uq_atom_relation'),
        Index('idx_relations_from', 'from_atom_id'),
        Index('idx_relations_to', 'to_atom_id'),
        Index('idx_relations_type', 'relation_type'),
    )

    # 維度分類：
    #   因果: causes, enables
    #   論證: supports, contradicts
    #   結構: contains
    #   時序: follows
    #   衍生: derives_from, supersedes, references
    #   工作流: blocks
    VALID_TYPES = (
        'causes', 'enables',
        'supports', 'contradicts',
        'contains',
        'follows',
        'derives_from', 'supersedes', 'references',
        'blocks',
    )

    def to_dict(self, include_atoms=False):
        d = {
            'id': self.id,
            'from_atom_id': self.from_atom_id,
            'to_atom_id': self.to_atom_id,
            'relation_type': self.relation_type,
            'label': self.label,
            'confidence': self.confidence,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_atoms:
            d['from_atom'] = {'id': self.from_atom.id, 'title': self.from_atom.title} if self.from_atom else None
            d['to_atom'] = {'id': self.to_atom.id, 'title': self.to_atom.title} if self.to_atom else None
        return d


# ============================================================
# 5.3 白板
# ============================================================

class Canvas(Base):
    __tablename__ = 'canvases'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default='')
    canvas_type: Mapped[str] = mapped_column(
        String(30), default='whiteboard'
    )  # whiteboard, mindmap, flowchart, cornell, template
    owner: Mapped[str] = mapped_column(
        String(100), default='ethan'
    )  # ethan, claude, agent:<task_id>, claude@<host>
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    viewport_x: Mapped[float] = mapped_column(Float, default=0)
    viewport_y: Mapped[float] = mapped_column(Float, default=0)
    viewport_zoom: Mapped[float] = mapped_column(Float, default=1.0)
    settings: Mapped[str] = mapped_column(Text, default='{}')
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now
    )

    atoms: Mapped[list["CanvasAtom"]] = relationship(
        back_populates='canvas', cascade='all, delete-orphan'
    )
    connections: Mapped[list["CanvasConnection"]] = relationship(
        back_populates='canvas', cascade='all, delete-orphan'
    )
    groups: Mapped[list["CanvasGroup"]] = relationship(
        back_populates='canvas', cascade='all, delete-orphan'
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'canvas_type': self.canvas_type,
            'owner': self.owner,
            'is_archived': self.is_archived,
            'viewport_x': self.viewport_x,
            'viewport_y': self.viewport_y,
            'viewport_zoom': self.viewport_zoom,
            'settings': self.settings,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class CanvasAtom(Base):
    __tablename__ = 'canvas_atoms'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canvas_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('canvases.id', ondelete='CASCADE'), nullable=False
    )
    atom_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('knowledge_atoms.id', ondelete='CASCADE'), nullable=False
    )
    pos_x: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    pos_y: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    width: Mapped[float | None] = mapped_column(Float, nullable=True)
    height: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_index: Mapped[int] = mapped_column(Integer, default=0)
    visual_style: Mapped[str] = mapped_column(Text, default='{}')
    group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('canvas_groups.id', ondelete='SET NULL'), nullable=True
    )

    canvas: Mapped["Canvas"] = relationship(back_populates='atoms')
    atom: Mapped["KnowledgeAtom"] = relationship()
    group: Mapped["CanvasGroup | None"] = relationship(back_populates='atoms')

    __table_args__ = (
        UniqueConstraint('canvas_id', 'atom_id', name='uq_canvas_atom'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'canvas_id': self.canvas_id,
            'atom_id': self.atom_id,
            'pos_x': self.pos_x,
            'pos_y': self.pos_y,
            'width': self.width,
            'height': self.height,
            'z_index': self.z_index,
            'visual_style': self.visual_style,
            'group_id': self.group_id,
            'atom': self.atom.to_dict() if self.atom else None,
        }


class CanvasGroup(Base):
    __tablename__ = 'canvas_groups'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canvas_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('canvases.id', ondelete='CASCADE'), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, default='Group')
    color: Mapped[str] = mapped_column(String(20), default='#3b82f6')
    pos_x: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    pos_y: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    width: Mapped[float] = mapped_column(Float, nullable=False, default=300)
    height: Mapped[float] = mapped_column(Float, nullable=False, default=200)
    z_index: Mapped[int] = mapped_column(Integer, default=1)

    canvas: Mapped["Canvas"] = relationship(back_populates='groups')
    atoms: Mapped[list["CanvasAtom"]] = relationship(back_populates='group')

    def to_dict(self):
        return {
            'id': self.id,
            'canvas_id': self.canvas_id,
            'name': self.name,
            'color': self.color,
            'pos_x': self.pos_x,
            'pos_y': self.pos_y,
            'width': self.width,
            'height': self.height,
            'z_index': self.z_index,
            'atom_ids': [ca.atom_id for ca in self.atoms],
        }


class CanvasConnection(Base):
    __tablename__ = 'canvas_connections'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canvas_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('canvases.id', ondelete='CASCADE'), nullable=False
    )
    source_atom_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_atom_id: Mapped[int] = mapped_column(Integer, nullable=False)
    relation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('atom_relations.id'), nullable=True
    )
    line_style: Mapped[str] = mapped_column(String(30), default='bezier')
    color: Mapped[str] = mapped_column(String(20), default='#3b82f6')
    label: Mapped[str] = mapped_column(Text, default='')
    animated: Mapped[bool] = mapped_column(Boolean, default=False)

    canvas: Mapped["Canvas"] = relationship(back_populates='connections')
    relation: Mapped["AtomRelation | None"] = relationship()

    def to_dict(self):
        return {
            'id': self.id,
            'canvas_id': self.canvas_id,
            'source_atom_id': self.source_atom_id,
            'target_atom_id': self.target_atom_id,
            'relation_id': self.relation_id,
            'line_style': self.line_style,
            'color': self.color,
            'label': self.label,
            'animated': self.animated,
        }


# ============================================================
# 5.5 分類系統
# ============================================================

class TagCategory(Base):
    __tablename__ = 'tag_categories'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )

    tags: Mapped[list["Tag"]] = relationship(
        secondary='tag_category_members', back_populates='categories'
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'sort_order': self.sort_order,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Tag(Base):
    __tablename__ = 'tags'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    color: Mapped[str] = mapped_column(String(20), default='#6b7280')
    parent_tag_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('tags.id'), nullable=True
    )
    tag_type: Mapped[str] = mapped_column(
        String(20), default='tag'
    )  # tag, group, domain
    # category_id 保留欄位但不再使用（多對多取代）
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('tag_categories.id', ondelete='SET NULL'), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )

    parent: Mapped["Tag | None"] = relationship(remote_side='Tag.id')
    categories: Mapped[list["TagCategory"]] = relationship(
        secondary='tag_category_members', back_populates='tags'
    )
    atoms: Mapped[list["KnowledgeAtom"]] = relationship(
        secondary='atom_tags', back_populates='tags'
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'color': self.color,
            'parent_tag_id': self.parent_tag_id,
            'tag_type': self.tag_type,
            'category_ids': [c.id for c in self.categories] if self.categories else [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# 多對多關聯表
from sqlalchemy import Table, Column

atom_tags = Table(
    'atom_tags', Base.metadata,
    Column('atom_id', Integer, ForeignKey('knowledge_atoms.id', ondelete='CASCADE'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True),
)

tag_category_members = Table(
    'tag_category_members', Base.metadata,
    Column('tag_id', Integer, ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True),
    Column('category_id', Integer, ForeignKey('tag_categories.id', ondelete='CASCADE'), primary_key=True),
)


# ============================================================
# 5.4 EAV 欄位值
# ============================================================

class AtomFieldValue(Base):
    __tablename__ = 'atom_field_values'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    atom_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('knowledge_atoms.id', ondelete='CASCADE'), nullable=False
    )
    field_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('schema_fields.id', ondelete='CASCADE'), nullable=False
    )
    value: Mapped[str | None] = mapped_column(Text, nullable=True)

    atom: Mapped["KnowledgeAtom"] = relationship(back_populates='field_values')
    field: Mapped["SchemaField"] = relationship()

    __table_args__ = (
        UniqueConstraint('atom_id', 'field_id', name='uq_atom_field_value'),
    )


# ============================================================
# 5.6 向量嵌入（語意搜尋用）
# ============================================================

class AtomEmbedding(Base):
    __tablename__ = 'atom_embeddings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    atom_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('knowledge_atoms.id', ondelete='CASCADE'), nullable=False
    )
    embedding = mapped_column(Vector(384), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )

    atom: Mapped["KnowledgeAtom"] = relationship()

    __table_args__ = (
        UniqueConstraint('atom_id', 'model_name', name='uq_atom_embedding'),
        Index('idx_embeddings_atom', 'atom_id'),
    )


# ============================================================
# 5.7 敏感詞彙登記（脫敏基礎建設）
# ============================================================

class SensitiveTerm(Base):
    """可重複使用的敏感詞彙，AI 脫敏時參照此表自動替換。"""
    __tablename__ = 'sensitive_terms'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # pii, infra, business, credential
    pattern: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # 實際敏感字串，如 "10.34.14.148"
    placeholder_prefix: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # 替換前綴，如 "INTERNAL_HOST"
    scope: Mapped[str] = mapped_column(
        String(100), default='global'
    )  # global, 或專案/domain tag 名稱
    is_regex: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )

    __table_args__ = (
        Index('idx_sensitive_terms_category', 'category'),
        Index('idx_sensitive_terms_scope', 'scope'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'category': self.category,
            'pattern': self.pattern,
            'placeholder_prefix': self.placeholder_prefix,
            'scope': self.scope,
            'is_regex': self.is_regex,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# 5.8 脫敏會話（映射表持久化）
# ============================================================

class SanitizeSession(Base):
    """每次脫敏操作產生一筆 session，保存映射表供後續還原。"""
    __tablename__ = 'sanitize_sessions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_atom_ids: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # [atom_id, ...] 被脫敏的原子來源
    original_content: Mapped[str] = mapped_column(Text, nullable=False)
    sanitized_content: Mapped[str] = mapped_column(Text, nullable=False)
    mapping: Mapped[dict] = mapped_column(
        JSONB, nullable=False
    )  # {"PLACEHOLDER_1": "原始值", ...}
    reverse_mapping: Mapped[dict] = mapped_column(
        JSONB, nullable=False
    )  # {"原始值": "PLACEHOLDER_1", ...} 快速查找用
    sensitivity_level: Mapped[str] = mapped_column(
        String(20), default='confidential'
    )  # 脫敏時套用的等級
    purpose: Mapped[str] = mapped_column(
        Text, default=''
    )  # 用途說明，如 "StackOverflow 求助 PostgreSQL 效能"
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )
    expires_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # 可選 TTL

    __table_args__ = (
        Index('idx_sanitize_sessions_created', 'created_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'source_atom_ids': self.source_atom_ids,
            'sanitized_content': self.sanitized_content,
            'mapping': self.mapping,
            'sensitivity_level': self.sensitivity_level,
            'purpose': self.purpose,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
        }
