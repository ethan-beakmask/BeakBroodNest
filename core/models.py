"""
知識原子 ORM 模型 -- Phase 0 核心表
對應 VISION.md Section 5 的資料模型
"""
import datetime
import secrets
from sqlalchemy import (
    Integer, BigInteger, String, Text, Float, Boolean, DateTime, Date,
    ForeignKey, UniqueConstraint, Index, CheckConstraint, Numeric,
    event,
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
    thumbnail_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # 分類
    atom_type: Mapped[str] = mapped_column(
        String(1), nullable=False, default='F'
    )  # A=萬用, B=發散, C=流程, D=歸納, E=套表, F=碎片
    schema_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('atom_schemas.id'), nullable=True
    )  # E 類型時關聯的 schema
    ref_code: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # 人類與 LLM 共用的全域短代號（如 BBN-137）
    project_canvas_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('canvases.id', ondelete='SET NULL'), nullable=True
    )  # 卡片所屬專案白板，與 canvas_atoms 的擺放位置分離

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

    # Embedding 排程
    needs_embedding: Mapped[bool] = mapped_column(Boolean, default=True)

    # 軟刪除
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    # HTML strip 後的純文字（搜尋與 embedding 用，由 ORM event hook 維護）
    content_plain: Mapped[str | None] = mapped_column(Text, nullable=True)

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
        Index('idx_atoms_needs_embedding', 'needs_embedding'),
    )

    @staticmethod
    def _sync_content_plain(_mapper, _connection, target):
        """ORM event：每次 INSERT/UPDATE 從 content 重算 content_plain。
        所有 11 個寫入路徑（routes/MCP/scripts）都會自動觸發，呼叫端零改動。
        若 content 為 None，content_plain 為空字串。
        """
        from core.html_strip import strip_html
        target.content_plain = strip_html(target.content or '')

    def to_dict(self, include_tags=False, include_values=False):
        d = {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'content_plain': self.content_plain,
            'has_content': bool((self.content_plain or '').strip()),
            'content_json': self.content_json,
            'content_type': self.content_type,
            'thumbnail_url': self.thumbnail_url,
            'atom_type': self.atom_type,
            'schema_id': self.schema_id,
            'ref_code': self.ref_code,
            'project_canvas_id': self.project_canvas_id,
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


# 註冊 KnowledgeAtom 的 content -> content_plain 自動同步
event.listen(KnowledgeAtom, 'before_insert', KnowledgeAtom._sync_content_plain)
event.listen(KnowledgeAtom, 'before_update', KnowledgeAtom._sync_content_plain)


# ============================================================
# 5.2 因果鍊
# ============================================================

class RelationTypeRegistry(Base):
    """關係類型參照表：graph_family 決定寫入驗證，semantic_layer 決定下游視圖過濾。"""
    __tablename__ = 'relation_type_registry'

    relation_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    graph_family: Mapped[str] = mapped_column(String(20), nullable=False)
    semantic_layer: Mapped[str] = mapped_column(String(20), nullable=False)
    affects_scheduling: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_directed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str] = mapped_column(Text, default='')
    default_color: Mapped[str] = mapped_column(String(20), default='#6b7280')
    default_style: Mapped[str] = mapped_column(String(30), default='solid')
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    def to_dict(self):
        return {
            'relation_type': self.relation_type,
            'graph_family': self.graph_family,
            'semantic_layer': self.semantic_layer,
            'affects_scheduling': self.affects_scheduling,
            'display_name': self.display_name,
            'is_directed': self.is_directed,
            'description': self.description,
            'default_color': self.default_color,
            'default_style': self.default_style,
            'sort_order': self.sort_order,
        }


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
        String(30), ForeignKey('relation_type_registry.relation_type'),
        nullable=False
    )
    label: Mapped[str] = mapped_column(Text, default='')
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_by: Mapped[str] = mapped_column(String(20), default='human')
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )

    # Phase 1 衍生欄位（由 DB trigger 從 registry 自動填入）
    graph_family: Mapped[str] = mapped_column(String(20), nullable=False)
    semantic_layer: Mapped[str] = mapped_column(String(20), nullable=False)
    affects_scheduling: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Phase 1 擴充欄位
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    rel_metadata: Mapped[dict | None] = mapped_column('metadata', JSONB, default=dict)

    from_atom: Mapped["KnowledgeAtom"] = relationship(foreign_keys=[from_atom_id])
    to_atom: Mapped["KnowledgeAtom"] = relationship(foreign_keys=[to_atom_id])
    registry: Mapped["RelationTypeRegistry"] = relationship(
        foreign_keys=[relation_type], viewonly=True
    )

    __table_args__ = (
        UniqueConstraint('from_atom_id', 'to_atom_id', 'relation_type',
                         name='uq_atom_relation'),
        CheckConstraint('from_atom_id <> to_atom_id', name='ck_no_self_loop'),
        Index('idx_relations_from', 'from_atom_id'),
        Index('idx_relations_to', 'to_atom_id'),
        Index('idx_relations_type', 'relation_type'),
    )

    VALID_TYPES = (
        'freeform',
        'contains',
        'blocks', 'follows', 'enables', 'causes',
        'derives_from', 'supersedes',
        'supports', 'contradicts', 'references',
    )

    def to_dict(self, include_atoms=False):
        d = {
            'id': self.id,
            'from_atom_id': self.from_atom_id,
            'to_atom_id': self.to_atom_id,
            'relation_type': self.relation_type,
            'graph_family': self.graph_family,
            'semantic_layer': self.semantic_layer,
            'affects_scheduling': self.affects_scheduling,
            'label': self.label,
            'confidence': self.confidence,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_deleted': self.is_deleted,
            'sort_order': self.sort_order,
            'metadata': self.rel_metadata,
        }
        if include_atoms:
            d['from_atom'] = {'id': self.from_atom.id, 'title': self.from_atom.title} if self.from_atom else None
            d['to_atom'] = {'id': self.to_atom.id, 'title': self.to_atom.title} if self.to_atom else None
        return d


def _gen_canvas_slug():
    return secrets.token_urlsafe(6)


# ============================================================
# 5.3 白板
# ============================================================

class Canvas(Base):
    __tablename__ = 'canvases'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=True, default=_gen_canvas_slug
    )  # URL 用，取代可猜測的數字 ID
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default='')
    canvas_type: Mapped[str] = mapped_column(
        String(30), default='whiteboard'
    )  # whiteboard, mindmap, flowchart, cornell, template
    owner: Mapped[str] = mapped_column(
        String(100), default='ethan'
    )  # ethan, claude, agent:<task_id>, claude@<host>
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_project: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )  # True=專案管理取用,False=思考用途的自由白板
    project_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )  # 關聯的本地專案目錄路徑（如 /opt/BeakBroodNest），供 AI 依 cwd 查待辦
    code: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )  # 專案短前綴，供卡片短代號使用（如 BBN）
    snapshot: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # 歸檔時凍結的完整白板快照（原子內容、連線、群組）
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
    textboxes: Mapped[list["CanvasTextbox"]] = relationship(
        back_populates='canvas', cascade='all, delete-orphan'
    )
    mindmap_shells: Mapped[list["CanvasMindmapShell"]] = relationship(
        back_populates='canvas', cascade='all, delete-orphan'
    )
    tags: Mapped[list["Tag"]] = relationship(
        secondary='canvas_tags'
    )

    def to_dict(self):
        return {
            'id': self.id,
            'slug': self.slug,
            'name': self.name,
            'description': self.description,
            'canvas_type': self.canvas_type,
            'owner': self.owner,
            'is_archived': self.is_archived,
            'is_project': self.is_project,
            'project_path': self.project_path,
            'code': self.code,
            'viewport_x': self.viewport_x,
            'viewport_y': self.viewport_y,
            'viewport_zoom': self.viewport_zoom,
            'settings': self.settings,
            'tag_ids': [t.id for t in self.tags] if self.tags else [],
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
    # deprecated: 舊單一群組 FK，保留向後相容但不再寫入
    group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('canvas_groups.id', ondelete='SET NULL'), nullable=True
    )
    # 心智圖殼歸屬（NOT NULL 表此卡為某殼的 mini 節點，render 為小尺寸 + 受 layout 控制）
    mindmap_shell_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('canvas_mindmap_shells.id', ondelete='SET NULL'), nullable=True
    )

    canvas: Mapped["Canvas"] = relationship(back_populates='atoms')
    atom: Mapped["KnowledgeAtom"] = relationship()

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
            'group_ids': [g.id for g in self.groups] if hasattr(self, 'groups') and self.groups else [],
            'mindmap_shell_id': self.mindmap_shell_id,
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
    border_style: Mapped[str] = mapped_column(String(20), default='none')

    canvas: Mapped["Canvas"] = relationship(back_populates='groups')
    # 多對多：透過 canvas_group_members junction table
    canvas_atoms: Mapped[list["CanvasAtom"]] = relationship(
        secondary='canvas_group_members', backref='groups', viewonly=False,
    )

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
            'border_style': self.border_style,
            'atom_ids': [ca.atom_id for ca in self.canvas_atoms],
        }


class CanvasTrash(Base):
    """白板私有字紙簍：從白板 Delete 的卡片或文字框暫存區。
    kind='atom'：救回時用 original_* 欄位重建 canvas_atoms（atom 本體不動）。
    kind='textbox'：救回時用 payload 完整重建 canvas_textboxes 紀錄。
    """
    __tablename__ = 'canvas_trash'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canvas_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('canvases.id', ondelete='CASCADE'), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default='atom')
    atom_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('knowledge_atoms.id', ondelete='CASCADE'), nullable=True
    )
    deleted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, nullable=False
    )
    original_pos_x: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    original_pos_y: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    original_width: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    visual_style: Mapped[str] = mapped_column(Text, nullable=False, default='{}')
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    atom: Mapped["KnowledgeAtom"] = relationship()

    __table_args__ = (
        UniqueConstraint('canvas_id', 'atom_id', name='uq_canvas_trash'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'canvas_id': self.canvas_id,
            'kind': self.kind,
            'atom_id': self.atom_id,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'original_pos_x': self.original_pos_x,
            'original_pos_y': self.original_pos_y,
            'original_width': self.original_width,
            'original_height': self.original_height,
            'z_index': self.z_index,
            'visual_style': self.visual_style,
            'payload': self.payload,
        }


class CanvasConnection(Base):
    __tablename__ = 'canvas_connections'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canvas_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('canvases.id', ondelete='CASCADE'), nullable=False
    )
    # 端點型別：'atom' | 'textbox'
    from_kind: Mapped[str] = mapped_column(String(20), nullable=False, default='atom')
    to_kind: Mapped[str] = mapped_column(String(20), nullable=False, default='atom')
    # atom 端點時填 source/target_atom_id；textbox 端點時填 source/target_textbox_id
    source_atom_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_atom_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_textbox_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('canvas_textboxes.id', ondelete='CASCADE'), nullable=True
    )
    target_textbox_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('canvas_textboxes.id', ondelete='CASCADE'), nullable=True
    )
    source_entry_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('atom_entries.id', ondelete='SET NULL'), nullable=True
    )
    target_entry_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('atom_entries.id', ondelete='SET NULL'), nullable=True
    )
    # standalone entry 端點（P3b：白板獨立 structuredEntry 連線）
    source_standalone_entry_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('standalone_entries.id', ondelete='CASCADE'), nullable=True
    )
    target_standalone_entry_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('standalone_entries.id', ondelete='CASCADE'), nullable=True
    )
    # deprecated: 舊 FK，保留向後相容但不再寫入
    relation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('atom_relations.id'), nullable=True
    )
    # 新 FK: 指向 unified_relations
    unified_relation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('unified_relations.id', ondelete='SET NULL'), nullable=True
    )
    line_style: Mapped[str] = mapped_column(String(30), default='bezier')
    color: Mapped[str] = mapped_column(String(20), default='#3b82f6')
    label: Mapped[str] = mapped_column(Text, default='')
    animated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_disconnected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    canvas: Mapped["Canvas"] = relationship(back_populates='connections')
    relation: Mapped["AtomRelation | None"] = relationship()
    unified_relation: Mapped["UnifiedRelation | None"] = relationship()

    def to_dict(self):
        d = {
            'id': self.id,
            'canvas_id': self.canvas_id,
            'from_kind': self.from_kind,
            'to_kind': self.to_kind,
            'source_atom_id': self.source_atom_id,
            'target_atom_id': self.target_atom_id,
            'source_textbox_id': self.source_textbox_id,
            'target_textbox_id': self.target_textbox_id,
            'source_entry_id': self.source_entry_id,
            'target_entry_id': self.target_entry_id,
            'source_standalone_entry_id': self.source_standalone_entry_id,
            'target_standalone_entry_id': self.target_standalone_entry_id,
            'unified_relation_id': self.unified_relation_id,
            'line_style': self.line_style,
            'color': self.color,
            'label': self.label,
            'animated': self.animated,
            'is_disconnected': self.is_disconnected,
        }
        if self.unified_relation:
            d['relation_type'] = self.unified_relation.relation_type
            d['graph_family'] = self.unified_relation.graph_family
            d['semantic_layer'] = self.unified_relation.semantic_layer
        return d


class CanvasMindmapShell(Base):
    """心智圖殼:畫布層的視覺容器，內含一棵以 root_atom_id 為頂的樹。
    樹結構透過 unified_relations(relation_type='tree_parent') 表達，跨 canvas 共用。
    殼僅負責視覺呈現:邊界、標題、layout 模式。
    """
    __tablename__ = 'canvas_mindmap_shells'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canvas_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('canvases.id', ondelete='CASCADE'), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default='心智圖')
    pos_x: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    pos_y: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    width: Mapped[float] = mapped_column(Float, nullable=False, default=600)
    height: Mapped[float] = mapped_column(Float, nullable=False, default=400)
    z_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default='#3b82f6')
    layout: Mapped[str] = mapped_column(String(20), nullable=False, default='tree-right')
    line_style: Mapped[str] = mapped_column(String(20), nullable=False, default='bezier')
    root_atom_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('knowledge_atoms.id', ondelete='SET NULL'), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now, nullable=False
    )

    canvas: Mapped["Canvas"] = relationship(back_populates='mindmap_shells')
    root_atom: Mapped["KnowledgeAtom | None"] = relationship(foreign_keys=[root_atom_id])

    def to_dict(self):
        return {
            'id': self.id,
            'canvas_id': self.canvas_id,
            'title': self.title,
            'pos_x': self.pos_x,
            'pos_y': self.pos_y,
            'width': self.width,
            'height': self.height,
            'z_index': self.z_index,
            'color': self.color,
            'layout': self.layout,
            'line_style': self.line_style,
            'root_atom_id': self.root_atom_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class CanvasTextbox(Base):
    """白板獨立文字框：標題在框外、內文純文字、可拉連線。
    不依附任何 atom；資料只屬於這張白板。
    """
    __tablename__ = 'canvas_textboxes'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canvas_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('canvases.id', ondelete='CASCADE'), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default='標題')
    content: Mapped[str] = mapped_column(Text, nullable=False, default='')
    pos_x: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    pos_y: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    width: Mapped[float] = mapped_column(Float, nullable=False, default=320)
    height: Mapped[float] = mapped_column(Float, nullable=False, default=180)
    z_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    bg_color: Mapped[str] = mapped_column(String(20), nullable=False, default='transparent')
    border_color: Mapped[str] = mapped_column(String(20), nullable=False, default='#f59e0b')
    border_style: Mapped[str] = mapped_column(String(20), nullable=False, default='solid')
    text_color: Mapped[str] = mapped_column(String(20), nullable=False, default='#1f2937')
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now, nullable=False
    )

    canvas: Mapped["Canvas"] = relationship(back_populates='textboxes')

    def to_dict(self):
        return {
            'id': self.id,
            'canvas_id': self.canvas_id,
            'title': self.title,
            'content': self.content,
            'pos_x': self.pos_x,
            'pos_y': self.pos_y,
            'width': self.width,
            'height': self.height,
            'z_index': self.z_index,
            'bg_color': self.bg_color,
            'border_color': self.border_color,
            'border_style': self.border_style,
            'text_color': self.text_color,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# 5.4b 交換卡片 (Exchange Packs)
# 寄存與取出的中介倉，不屬於任何白板
# ============================================================

class ExchangePack(Base):
    __tablename__ = 'exchange_packs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    source_canvas_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('canvases.id', ondelete='SET NULL'), nullable=True
    )
    owner: Mapped[str] = mapped_column(String(100), nullable=False, default='ethan')
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )

    pack_atoms: Mapped[list["ExchangePackAtom"]] = relationship(
        back_populates='pack',
        cascade='all, delete-orphan',
        order_by='ExchangePackAtom.sort_order',
    )

    def to_dict(self, include_source_name: str | None = None, atom_count: int | None = None):
        return {
            'id': self.id,
            'name': self.name,
            'source_canvas_id': self.source_canvas_id,
            'source_canvas_name': include_source_name,
            'owner': self.owner,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'atom_count': atom_count if atom_count is not None else len(self.pack_atoms),
        }


class ExchangePackAtom(Base):
    __tablename__ = 'exchange_pack_atoms'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pack_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('exchange_packs.id', ondelete='CASCADE'), nullable=False
    )
    atom_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('knowledge_atoms.id', ondelete='CASCADE'), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    original_pos_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_pos_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_width: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )

    pack: Mapped["ExchangePack"] = relationship(back_populates='pack_atoms')
    atom: Mapped["KnowledgeAtom"] = relationship()

    __table_args__ = (
        UniqueConstraint('pack_id', 'atom_id', name='uq_exchange_pack_atom'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'pack_id': self.pack_id,
            'atom_id': self.atom_id,
            'sort_order': self.sort_order,
            'original_pos_x': self.original_pos_x,
            'original_pos_y': self.original_pos_y,
            'original_width': self.original_width,
            'original_height': self.original_height,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'atom': self.atom.to_dict() if self.atom else None,
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
    source: Mapped[str] = mapped_column(
        String(20), default='ai', nullable=False
    )  # human, ai
    # category_id 保留欄位但不再使用（多對多取代）
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('tag_categories.id', ondelete='SET NULL'), nullable=True
    )
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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
            'source': self.source,
            'hidden': bool(self.hidden),
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

canvas_tags = Table(
    'canvas_tags', Base.metadata,
    Column('canvas_id', Integer, ForeignKey('canvases.id', ondelete='CASCADE'), primary_key=True),
    Column('tag_id',    Integer, ForeignKey('tags.id',     ondelete='CASCADE'), primary_key=True),
)

canvas_group_members = Table(
    'canvas_group_members', Base.metadata,
    Column('id', Integer, primary_key=True),
    Column('canvas_atom_id', Integer, ForeignKey('canvas_atoms.id', ondelete='CASCADE'), nullable=False),
    Column('group_id', Integer, ForeignKey('canvas_groups.id', ondelete='CASCADE'), nullable=False),
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
    )  # 實際敏感字串，如 "10.0.0.1"
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


# ============================================================
# 5.9 系統組態（Standalone 認證用）
# ============================================================

# ============================================================
# 5.10 跨專案訊息（收件匣機制）
# ============================================================

class Message(Base):
    """跨專案 / 跨 Claude session 的定向訊息。

    解決 tag 廣播式通知的四大問題：
    1. 有明確收件人（recipient），不是廣播
    2. 有已讀/未讀狀態（is_read / read_at）
    3. 有寄件人身份（sender），含啟動目錄（sender_cwd）
    4. 各專案只需 CLAUDE.md 加一條 note_inbox 規則

    身份格式：{scope}:{identity}
      project:beakbroodnest     -- 專案主線 Claude
      task:daily-review      -- 排程/任務身份
      user:ethan             -- 人類
    """
    __tablename__ = 'messages'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 寄件人
    sender: Mapped[str] = mapped_column(
        String(200), nullable=False
    )  # e.g. "project:beakmeshwall"
    sender_cwd: Mapped[str] = mapped_column(
        String(500), default=''
    )  # 寄件人啟動時的工作目錄，輔助判斷來源

    # 收件人
    recipient: Mapped[str] = mapped_column(
        String(200), nullable=False
    )  # e.g. "project:beakbroodnest"

    # 內容
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, default='')

    # 訊息類型
    message_type: Mapped[str] = mapped_column(
        String(20), default='notice'
    )  # notice=純通知, request=需收件人動作, alert=緊急通知人類

    # 關聯原子（可選）
    ref_atom_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('knowledge_atoms.id', ondelete='SET NULL'),
        nullable=True
    )

    # 回覆鏈
    reply_to_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('messages.id', ondelete='SET NULL'),
        nullable=True
    )

    # 已讀狀態
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )

    # 關聯
    ref_atom: Mapped["KnowledgeAtom | None"] = relationship()
    reply_to: Mapped["Message | None"] = relationship(remote_side='Message.id')

    __table_args__ = (
        Index('idx_messages_recipient_unread', 'recipient', 'is_read'),
        Index('idx_messages_sender', 'sender'),
        Index('idx_messages_created', 'created_at'),
        Index('idx_messages_reply_to', 'reply_to_id'),
    )

    VALID_TYPES = ('notice', 'request', 'alert')

    def to_dict(self):
        return {
            'id': self.id,
            'sender': self.sender,
            'sender_cwd': self.sender_cwd,
            'recipient': self.recipient,
            'subject': self.subject,
            'body': self.body,
            'message_type': self.message_type,
            'ref_atom_id': self.ref_atom_id,
            'reply_to_id': self.reply_to_id,
            'is_read': self.is_read,
            'read_at': self.read_at.isoformat() if self.read_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class NavMenu(Base):
    """動態導覽選單項目"""
    __tablename__ = 'nav_menu'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    icon: Mapped[str] = mapped_column(String(50), default='')
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'url': self.url,
            'icon': self.icon,
            'sort_order': self.sort_order,
            'is_active': self.is_active,
        }


class SystemConfig(Base):
    """鍵值對儲存：認證帳密、Flask secret key、部署模式等。"""
    __tablename__ = 'system_config'

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default='')
    description: Mapped[str] = mapped_column(Text, default='')
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now
    )


# ============================================================
# 6.0 結構化 Entry 系統（卡片內容細化）
# ============================================================

class EntrySchema(Base):
    """記錄類型定義（Lookup 模式：用戶自訂 + 系統預設）。

    每種 schema 代表一種結構化記錄格式，如待辦事項、記帳、行事曆等。
    用戶可自建新類型，也可修改系統預設類型的欄位。
    """
    __tablename__ = 'entry_schemas'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False
    )  # 識別碼：freetext, todo, expense, calendar...
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[str] = mapped_column(String(30), default='')
    color: Mapped[str] = mapped_column(String(10), default='#6b7280')
    slash_alias: Mapped[str | None] = mapped_column(
        String(20), nullable=True, unique=True
    )  # / 觸發詞，如 td, exp, cal
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now
    )

    fields: Mapped[list["EntrySchemaField"]] = relationship(
        back_populates='schema', cascade='all, delete-orphan',
        order_by='EntrySchemaField.sort_order'
    )

    def to_dict(self, include_fields=False):
        d = {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'icon': self.icon,
            'color': self.color,
            'slash_alias': self.slash_alias,
            'is_system': self.is_system,
            'sort_order': self.sort_order,
        }
        if include_fields:
            d['fields'] = [f.to_dict() for f in self.fields]
        return d


class EntrySchemaField(Base):
    """記錄類型的欄位定義（Lookup 細項概念）。

    field_type 支援：
      text, number, decimal, date, datetime, duration,
      select, multiselect, checkbox, relation, attachment
    dimension 為 5W 語義標記，AI 分析跨類型關聯時使用：
      W=who, H=what, T=when, P=where, Y=why
    """
    __tablename__ = 'entry_schema_fields'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schema_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('entry_schemas.id', ondelete='CASCADE'), nullable=False
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    field_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    options: Mapped[str] = mapped_column(Text, default='')
    default_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    dimension: Mapped[str | None] = mapped_column(
        String(1), nullable=True
    )  # W=who, H=what, T=when, P=where, Y=why
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False)

    schema: Mapped["EntrySchema"] = relationship(back_populates='fields')

    VALID_FIELD_TYPES = (
        'text', 'number', 'decimal', 'date', 'datetime', 'duration',
        'select', 'multiselect', 'checkbox', 'relation', 'attachment',
    )
    VALID_DIMENSIONS = ('W', 'H', 'T', 'P', 'Y')

    __table_args__ = (
        UniqueConstraint('schema_id', 'name', name='uq_entry_schema_field'),
        Index('idx_esf_schema', 'schema_id'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'schema_id': self.schema_id,
            'name': self.name,
            'label': self.label,
            'field_type': self.field_type,
            'options': self.options,
            'default_value': self.default_value,
            'required': self.required,
            'sort_order': self.sort_order,
            'dimension': self.dimension,
        }


class AtomEntry(Base):
    """卡片內的結構化記錄（每筆是獨立 DB row）。

    一張卡片的內容 = 一組有序的 AtomEntry。
    自由文字也是 entry（schema code='freetext'），統一模型。
    """
    __tablename__ = 'atom_entries'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    atom_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('knowledge_atoms.id', ondelete='CASCADE'), nullable=False
    )
    schema_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('entry_schemas.id'), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_text: Mapped[str] = mapped_column(Text, default='')
    summary: Mapped[str] = mapped_column(String(200), default='')
    promoted_atom_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('knowledge_atoms.id', ondelete='SET NULL'), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now
    )

    atom: Mapped["KnowledgeAtom"] = relationship(
        foreign_keys=[atom_id], backref='entries'
    )
    schema: Mapped["EntrySchema"] = relationship()
    promoted_atom: Mapped["KnowledgeAtom | None"] = relationship(
        foreign_keys=[promoted_atom_id]
    )
    field_values: Mapped[list["EntryFieldValue"]] = relationship(
        back_populates='entry', cascade='all, delete-orphan'
    )

    __table_args__ = (
        Index('idx_atom_entries_atom_order', 'atom_id', 'sort_order'),
        Index('idx_atom_entries_schema', 'schema_id'),
    )

    def to_dict(self, include_values=False):
        d = {
            'id': self.id,
            'atom_id': self.atom_id,
            'schema_id': self.schema_id,
            'sort_order': self.sort_order,
            'raw_text': self.raw_text,
            'summary': self.summary,
            'promoted_atom_id': self.promoted_atom_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_values and self.field_values:
            d['field_values'] = {
                fv.field.name: fv.value for fv in self.field_values if fv.field
            }
        return d


class EntryFieldValue(Base):
    """Entry 的欄位值（EAV 模式，多型別欄位）。

    寫入時根據 field_type 寫對應型別欄位，value 永遠存文字版。
    沿用 BeakPlatform LookupItem 的多型別設計。
    """
    __tablename__ = 'entry_field_values'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('atom_entries.id', ondelete='CASCADE'), nullable=False
    )
    field_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('entry_schema_fields.id', ondelete='CASCADE'), nullable=False
    )
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_int: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value_decimal = mapped_column(Numeric(20, 2), nullable=True)
    value_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    value_datetime: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    entry: Mapped["AtomEntry"] = relationship(back_populates='field_values')
    field: Mapped["EntrySchemaField"] = relationship()

    __table_args__ = (
        UniqueConstraint('entry_id', 'field_id', name='uq_entry_field_value'),
        Index('idx_efv_entry', 'entry_id'),
    )

    def to_dict(self):
        dec = self.value_decimal
        return {
            'entry_id': self.entry_id,
            'field_id': self.field_id,
            'value': self.value,
            'value_int': self.value_int,
            'value_decimal': float(dec) if dec is not None else None,
            'value_date': self.value_date.isoformat() if self.value_date else None,
            'value_datetime': self.value_datetime.isoformat() if self.value_datetime else None,
        }


class UnifiedRelation(Base):
    """統一關係表：支援 atom/entry 混合端點。

    四種組合：
      atom  -> atom     （Card-Card，心智圖/discourse 層）
      atom  -> entry    （Card-Item）
      entry -> atom     （Item-Card）
      entry -> entry    （Item-Item，PM/ER-model 風格）

    每個端點二擇一：atom_id 或 entry_id 必填其一。
    graph_family / semantic_layer / affects_scheduling 由 DB trigger 從 registry 自動填入。
    """
    __tablename__ = 'unified_relations'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 來源端（二擇一）
    from_atom_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('knowledge_atoms.id', ondelete='CASCADE'), nullable=True
    )
    from_entry_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('atom_entries.id', ondelete='CASCADE'), nullable=True
    )

    # 目標端（二擇一）
    to_atom_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('knowledge_atoms.id', ondelete='CASCADE'), nullable=True
    )
    to_entry_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('atom_entries.id', ondelete='CASCADE'), nullable=True
    )

    relation_type: Mapped[str] = mapped_column(
        String(30), ForeignKey('relation_type_registry.relation_type'),
        nullable=False
    )
    label: Mapped[str] = mapped_column(Text, default='')
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_by: Mapped[str] = mapped_column(String(20), default='human')
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )

    # 由 DB trigger 從 relation_type_registry 自動填入
    graph_family: Mapped[str | None] = mapped_column(String(20), nullable=True)
    semantic_layer: Mapped[str | None] = mapped_column(String(20), nullable=True)
    affects_scheduling: Mapped[bool] = mapped_column(Boolean, default=False)

    # 軟刪除 + 排序 + 擴充
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    rel_metadata: Mapped[dict | None] = mapped_column('metadata', JSONB, default=dict)

    # Relationships
    from_atom: Mapped["KnowledgeAtom | None"] = relationship(
        foreign_keys=[from_atom_id]
    )
    from_entry: Mapped["AtomEntry | None"] = relationship(
        foreign_keys=[from_entry_id]
    )
    to_atom: Mapped["KnowledgeAtom | None"] = relationship(
        foreign_keys=[to_atom_id]
    )
    to_entry: Mapped["AtomEntry | None"] = relationship(
        foreign_keys=[to_entry_id]
    )
    registry: Mapped["RelationTypeRegistry | None"] = relationship(
        foreign_keys=[relation_type], viewonly=True
    )

    VALID_TYPES = (
        'freeform',
        'contains',
        'blocks', 'follows', 'enables', 'causes',
        'derives_from', 'supersedes',
        'supports', 'contradicts', 'references',
    )

    __table_args__ = (
        # 來源端：atom_id 或 entry_id 恰好填一個
        CheckConstraint(
            '(from_atom_id IS NOT NULL)::int + (from_entry_id IS NOT NULL)::int = 1',
            name='ck_unified_rel_from_one'
        ),
        # 目標端：atom_id 或 entry_id 恰好填一個
        CheckConstraint(
            '(to_atom_id IS NOT NULL)::int + (to_entry_id IS NOT NULL)::int = 1',
            name='ck_unified_rel_to_one'
        ),
        Index('idx_urel_from_atom', 'from_atom_id'),
        Index('idx_urel_from_entry', 'from_entry_id'),
        Index('idx_urel_to_atom', 'to_atom_id'),
        Index('idx_urel_to_entry', 'to_entry_id'),
        Index('idx_urel_type', 'relation_type'),
        Index('idx_urel_is_deleted', 'is_deleted'),
    )

    def to_dict(self, include_endpoints=False):
        d = {
            'id': self.id,
            'from_atom_id': self.from_atom_id,
            'from_entry_id': self.from_entry_id,
            'to_atom_id': self.to_atom_id,
            'to_entry_id': self.to_entry_id,
            'relation_type': self.relation_type,
            'graph_family': self.graph_family,
            'semantic_layer': self.semantic_layer,
            'affects_scheduling': self.affects_scheduling,
            'label': self.label,
            'confidence': self.confidence,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_deleted': self.is_deleted,
            'sort_order': self.sort_order,
            'metadata': self.rel_metadata,
        }
        if include_endpoints:
            if self.from_atom:
                d['from_atom'] = {'id': self.from_atom.id, 'title': self.from_atom.title}
            if self.to_atom:
                d['to_atom'] = {'id': self.to_atom.id, 'title': self.to_atom.title}
        return d


# ============================================================
# 7.0 欄位變更歷史（Audit Log）
# ============================================================

# ============================================================
# 7.1 檔案上傳（圖片 / 一般檔案）
# ============================================================

class UploadedFile(Base):
    """上傳檔案的中介表。

    token 為公開隨機識別碼，作為 URL 的一部分，但下載 endpoint 仍要登入。
    stored_path 是磁碟上的實際檔案路徑（檔名 = token），原檔名只記在這裡。
    kind:
      image -- 圖片，會用 Tiptap Image node 嵌入
      file  -- 一般檔案，用 ;;file 結構化 entry 呈現
    """
    __tablename__ = 'uploaded_files'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str] = mapped_column(
        String(200), nullable=False, default='application/octet-stream'
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default='file'
    )  # image, file
    uploaded_by: Mapped[str] = mapped_column(String(100), nullable=False, default='ethan')
    uploaded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, nullable=False
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index('idx_uploaded_files_kind', 'kind'),
        Index('idx_uploaded_files_uploaded_at', 'uploaded_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'token': self.token,
            'original_filename': self.original_filename,
            'mime_type': self.mime_type,
            'size_bytes': self.size_bytes,
            'kind': self.kind,
            'uploaded_by': self.uploaded_by,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
        }


class EntryFieldChangeLog(Base):
    """Entry 欄位值的變更歷史。

    每次 entry_field_values 被 UPDATE 時記錄一筆，
    用於 L2 衝突提示（顯示具體欄位變更）和專案管理風險追蹤。
    """
    __tablename__ = 'entry_field_change_log'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('atom_entries.id', ondelete='CASCADE'), nullable=False
    )
    field_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('entry_schema_fields.id', ondelete='CASCADE'), nullable=False
    )
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str] = mapped_column(
        String(50), nullable=False, default='user'
    )  # 'user:ethan' / 'gantt:drag' / 'api' / 'system'
    changed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, nullable=False
    )

    entry: Mapped["AtomEntry"] = relationship()
    field: Mapped["EntrySchemaField"] = relationship()

    __table_args__ = (
        Index('idx_efcl_entry', 'entry_id'),
        Index('idx_efcl_changed_at', 'changed_at'),
    )


class UserPreference(Base):
    """使用者偏好設定 KV 儲存。

    供記住跨頁面的使用者狀態,如 last_active_canvas_slug。
    """
    __tablename__ = 'user_preferences'

    username: Mapped[str] = mapped_column(String(100), primary_key=True)
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default='')
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now,
        onupdate=datetime.datetime.now, nullable=False
    )

    def to_dict(self):
        return {
            'username': self.username,
            'key': self.key,
            'value': self.value,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class GanttColorsDefault(Base):
    """每個登入帳號的 beak-gantt 個人預設配色。"""
    __tablename__ = 'gantt_colors_default'

    username: Mapped[str] = mapped_column(String(100), primary_key=True)
    colors: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now,
        onupdate=datetime.datetime.now, nullable=False
    )


class GanttColorsProject(Base):
    """每個 project（canvas with is_project=true）的 beak-gantt 配色覆寫。

    canvas 刪除時級聯刪除；無覆寫時 fallback 到個人預設。
    """
    __tablename__ = 'gantt_colors_project'

    canvas_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('canvases.id', ondelete='CASCADE'),
        primary_key=True
    )
    colors: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now,
        onupdate=datetime.datetime.now, nullable=False
    )


# ============================================================
# 5.11 搜尋前置詞典（alias → canonical 規範化）
# ============================================================

class TermAlias(Base):
    """搜尋查詢規範化詞典。

    在 note_search 入口將 alias 替換為 canonical，使
    覆盤/復盤、PG/postgresql、固定錯字等變體能命中同一組原子。
    不關聯實體原子，純粹是查詢預處理器。
    """
    __tablename__ = 'term_aliases'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alias: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    canonical: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(
        String(20), default='variant'
    )  # variant / typo / slang / personal
    note: Mapped[str] = mapped_column(Text, default='')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now,
        onupdate=datetime.datetime.now
    )

    __table_args__ = (
        Index('idx_term_aliases_canonical', 'canonical'),
        Index('idx_term_aliases_enabled', 'enabled'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'alias': self.alias,
            'canonical': self.canonical,
            'source': self.source,
            'note': self.note,
            'enabled': self.enabled,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# 白板獨立 structuredEntry（P3a）
#   - 與卡片同階層，直接放在白板上的結構化條目
#   - 不寄生於 atom，獨立資料表
#   - 沿用 entry_schemas（;;td / ;;cal / ;;idcard 等）
#   - field_values 採 JSONB 直接存（第一版簡化，不走 entry_field_values 多型別表）
#   - node_id 取自 tiptap_node_id_seq（驗證 P1/P2 的 stable ID 機制）
# ============================================================

class StandaloneEntry(Base):
    __tablename__ = 'standalone_entries'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schema_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('entry_schemas.id'), nullable=False
    )
    schema_code: Mapped[str] = mapped_column(Text, nullable=False, default='freetext')
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default='')
    summary: Mapped[str] = mapped_column(String(200), nullable=False, default='')
    field_values: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    node_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    owner: Mapped[str] = mapped_column(Text, nullable=False, default='ethan')
    sensitivity: Mapped[str] = mapped_column(Text, nullable=False, default='internal')
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now
    )

    schema: Mapped["EntrySchema"] = relationship()

    __table_args__ = (
        Index('idx_standalone_entries_schema', 'schema_id'),
        Index('idx_standalone_entries_is_deleted', 'is_deleted'),
        Index('idx_standalone_entries_owner', 'owner'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'schema_id': self.schema_id,
            'schema_code': self.schema_code,
            'raw_text': self.raw_text,
            'summary': self.summary,
            'field_values': self.field_values or {},
            'node_id': self.node_id,
            'owner': self.owner,
            'sensitivity': self.sensitivity,
            'is_deleted': self.is_deleted,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class CanvasStandaloneEntry(Base):
    __tablename__ = 'canvas_standalone_entries'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canvas_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('canvases.id', ondelete='CASCADE'), nullable=False
    )
    standalone_entry_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('standalone_entries.id', ondelete='CASCADE'), nullable=False
    )
    pos_x: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    pos_y: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    width: Mapped[float | None] = mapped_column(Float, nullable=True)
    height: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_index: Mapped[int] = mapped_column(Integer, default=0)
    visual_style: Mapped[str] = mapped_column(Text, default='{}')

    canvas: Mapped["Canvas"] = relationship()
    entry: Mapped["StandaloneEntry"] = relationship()

    __table_args__ = (
        UniqueConstraint('canvas_id', 'standalone_entry_id', name='uq_canvas_standalone_entry'),
        Index('idx_canvas_standalone_entries_canvas', 'canvas_id'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'canvas_id': self.canvas_id,
            'standalone_entry_id': self.standalone_entry_id,
            'pos_x': self.pos_x,
            'pos_y': self.pos_y,
            'width': self.width,
            'height': self.height,
            'z_index': self.z_index,
            'visual_style': self.visual_style,
            'entry': self.entry.to_dict() if self.entry else None,
        }
