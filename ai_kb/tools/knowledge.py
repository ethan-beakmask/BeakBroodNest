# -*- coding: utf-8 -*-
"""核心知識工具: note_store/get/update/forget/check"""
import json
import datetime

from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import (
    KnowledgeAtom, Tag,
    AtomSchema, SchemaField, AtomFieldValue,
)
from core import relations as rel_service
from core import consistency as consistency_service
from .param_forms import (
    ParamFormatError,
    param_format_error_payload,
    parse_field_values,
    normalize_tags,
)


def register(mcp):

    @mcp.tool()
    def note_store(
        title: str,
        content: str = '',
        atom_type: str = 'F',
        content_type: str = 'markdown',
        source: str = 'ai',
        source_detail: str = '',
        owner: str = 'claude',
        tags: str | list[str] | None = None,
        lifecycle: str = 'active',
        schema_id: int | None = None,
        field_values: str | dict[str, str] | None = None,
        sensitivity: str = 'internal',
    ) -> str:
        """儲存一筆知識原子到知識庫。

        atom_type 分類:
          A=萬用  B=創意發散  C=思考過程/流程  D=總結歸納  E=套表  F=碎片
        lifecycle: active(活躍) / aging(老化) / archived(歸檔) / terminal(終止)
        source: human / ai / import / derived
        owner: 擁有者 (ethan/claude/agent:xxx/claude@host/tool:name)，預設 claude
        tags: 逗號分隔字串（例 'BeakAgent,待辦'；請用字串不要用陣列），不存在的標籤會自動建立
        schema_id: E 類型時關聯的 schema ID
        field_values: 推薦字串形式，多行「欄位name=值」，續行直接換行接在上一個欄位值後，例如:
          status=進行中
          note=第一行
            第二行補充
          請勿用陣列 / 物件傳中文，會被拒絕。相容形式為 dict（僅限純 ASCII）。
        sensitivity: 敏感度 (public/internal/confidential/restricted)，預設 internal

        回傳建立的原子 ID 與摘要。
        """
        valid_types = ('A', 'B', 'C', 'D', 'E', 'F')
        if atom_type not in valid_types:
            return json.dumps({'error': f'無效的 atom_type: {atom_type}，允許值: {", ".join(valid_types)}'})

        valid_sensitivity = ('public', 'internal', 'confidential', 'restricted')
        if sensitivity not in valid_sensitivity:
            return json.dumps({'error': f'無效的 sensitivity: {sensitivity}，允許值: {", ".join(valid_sensitivity)}'})

        field_values_from_string = False
        if isinstance(field_values, str):
            try:
                field_values = parse_field_values(field_values)
            except ParamFormatError as e:
                return json.dumps(param_format_error_payload(e), ensure_ascii=False)
            # 空字串視同沒給，不觸發字串形式的嚴格檢查
            field_values_from_string = bool(field_values)
            if field_values_from_string and not schema_id:
                return json.dumps({'error': 'field_values 需要搭配 schema_id'}, ensure_ascii=False)

        with session_scope() as s:
            if (atom_type == 'E' and schema_id) or field_values_from_string:
                schema = s.query(AtomSchema).filter(AtomSchema.id == schema_id).first()
                if not schema:
                    return json.dumps({'error': f'Schema {schema_id} 不存在'})
                if field_values_from_string:
                    valid_fields = [f.name for f in schema.fields]
                    valid_field_set = set(valid_fields)
                    unknown_fields = sorted(
                        name for name in field_values
                        if name not in valid_field_set
                    )
                    if unknown_fields:
                        return json.dumps({
                            'error': f'未知欄位: {", ".join(unknown_fields)}',
                            'valid_fields': valid_fields,
                        }, ensure_ascii=False)

            atom = KnowledgeAtom(
                title=title,
                content=content,
                content_type=content_type,
                atom_type=atom_type,
                lifecycle=lifecycle,
                source=source,
                source_detail=source_detail,
                owner=owner,
                schema_id=schema_id,
                sensitivity=sensitivity,
            )
            s.add(atom)
            s.flush()

            tags = normalize_tags(tags)
            if tags:
                tag_objects = []
                for tag_name in tags:
                    tag = s.query(Tag).filter(Tag.name == tag_name).first()
                    if not tag:
                        tag = Tag(name=tag_name, tag_type='tag')
                        s.add(tag)
                        s.flush()
                    tag_objects.append(tag)
                atom.tags = tag_objects

            if field_values and schema_id:
                schema_fields = s.query(SchemaField).filter(
                    SchemaField.schema_id == schema_id
                ).all()
                field_map = {f.name: f for f in schema_fields}
                for fname, fval in field_values.items():
                    if fname in field_map:
                        s.add(AtomFieldValue(
                            atom_id=atom.id,
                            field_id=field_map[fname].id,
                            value=str(fval) if fval is not None else None,
                        ))

            s.flush()
            # needs_embedding=True (default)，由背景 embedder 處理

            result = {
                'id': atom.id,
                'title': atom.title,
                'atom_type': atom.atom_type,
                'lifecycle': atom.lifecycle,
                'owner': atom.owner,
                'tags': [t.name for t in atom.tags],
                'message': f'知識原子已建立 (id={atom.id})',
            }
            if schema_id:
                result['schema_id'] = schema_id
            if field_values:
                result['field_values'] = field_values
            return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    def note_get(atom_id: int) -> str:
        """取得單一知識原子的完整資訊，包含因果關係與阻塞狀態。

        自動更新存取紀錄（last_accessed_at, access_count）。
        """
        with session_scope() as s:
            atom = (
                s.query(KnowledgeAtom)
                .options(
                    joinedload(KnowledgeAtom.tags),
                    joinedload(KnowledgeAtom.field_values).joinedload(AtomFieldValue.field),
                )
                .filter(KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False)
                .first()
            )
            if not atom:
                return json.dumps({'error': f'原子 {atom_id} 不存在'})

            atom.last_accessed_at = datetime.datetime.now()
            atom.access_count += 1

            result = atom.to_dict(include_tags=True, include_values=True)

            if atom.schema_id and atom.schema:
                result['schema'] = atom.schema.to_dict()
                result['schema']['fields'] = [f.to_dict() for f in atom.schema.fields]

            outgoing = rel_service.get_relations_from(s, atom_id)
            incoming = rel_service.get_relations_to(s, atom_id)
            result['relations_from'] = [
                {
                    'id': r.id,
                    'to_atom_id': r.to_atom_id,
                    'to_title': r.to_atom.title if r.to_atom else '',
                    'type': r.relation_type,
                    'label': r.label,
                }
                for r in outgoing
            ]
            result['relations_to'] = [
                {
                    'id': r.id,
                    'from_atom_id': r.from_atom_id,
                    'from_title': r.from_atom.title if r.from_atom else '',
                    'type': r.relation_type,
                    'label': r.label,
                }
                for r in incoming
            ]

            blockers = rel_service.get_blockers(s, atom_id)
            result['is_blocked'] = len(blockers) > 0
            result['blockers'] = [
                {'id': b.id, 'title': b.title, 'lifecycle': b.lifecycle}
                for b in blockers
            ]

            return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    def note_update(
        atom_id: int,
        title: str = '',
        content: str = '',
        atom_type: str = '',
        lifecycle: str = '',
        tags: str | list[str] | None = None,
        append_content: str = '',
        sensitivity: str = '',
        force_owner_override: bool = False,
    ) -> str:
        """更新現有知識原子的欄位。

        只有提供的欄位會被更新（空字串表示不更新）。
        append_content: 在現有內容後追加（不覆蓋），適合漸進式補充。
        tags: 逗號分隔字串（例 'BeakAgent,已完成'；請用字串不要用陣列）；提供時會替換所有標籤，不存在的標籤會自動建立。
        sensitivity: 敏感度 (public/internal/confidential/restricted)
        force_owner_override: 強制覆寫非自己擁有的原子（預設 False，需明確啟用）

        owner 保護：MCP 呼叫者預設身份為 claude，無法修改 owner != claude 的原子。
        需跨 owner 寫入時設 force_owner_override=True。
        """
        valid_sensitivity = ('public', 'internal', 'confidential', 'restricted')
        if sensitivity and sensitivity not in valid_sensitivity:
            return json.dumps({'error': f'無效的 sensitivity: {sensitivity}，允許值: {", ".join(valid_sensitivity)}'})

        with session_scope() as s:
            atom = s.query(KnowledgeAtom).filter(
                KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False
            ).first()
            if not atom:
                return json.dumps({'error': f'原子 {atom_id} 不存在'})

            if atom.owner != 'claude' and not force_owner_override:
                return json.dumps({
                    'error': f'原子 {atom_id} 屬於 {atom.owner}，MCP 預設不可修改。'
                             f'需要跨 owner 寫入請設 force_owner_override=True',
                    'owner': atom.owner,
                })

            if title:
                atom.title = title
            if content:
                atom.content = content
            if append_content:
                atom.content = (atom.content or '') + '\n' + append_content
            if atom_type:
                atom.atom_type = atom_type
            if lifecycle:
                atom.lifecycle = lifecycle
            if sensitivity:
                atom.sensitivity = sensitivity

            tags = normalize_tags(tags)
            if tags is not None:
                tag_objects = []
                for tag_name in tags:
                    tag = s.query(Tag).filter(Tag.name == tag_name).first()
                    if not tag:
                        tag = Tag(name=tag_name, tag_type='tag')
                        s.add(tag)
                        s.flush()
                    tag_objects.append(tag)
                atom.tags = tag_objects

            if title or content or append_content:
                atom.needs_embedding = True

            atom.updated_by = 'claude'
            atom.updated_via = 'mcp'

            s.flush()

            return json.dumps({
                'id': atom.id,
                'title': atom.title,
                'lifecycle': atom.lifecycle,
                'owner': atom.owner,
                'sensitivity': atom.sensitivity,
                'tags': [t.name for t in atom.tags],
                'message': f'原子 {atom_id} 已更新',
            }, ensure_ascii=False)

    @mcp.tool()
    def note_forget(
        atom_id: int,
        mode: str = 'archive',
    ) -> str:
        """將知識原子標記為過時或刪除。

        mode:
          archive  -- 設為 archived（歸檔，搜尋仍可達但不主動顯示）
          terminal -- 設為 terminal（終止，僅明確搜尋時顯示）
          delete   -- 軟刪除（is_deleted=True，一般搜尋不會出現）
        """
        valid_modes = ('archive', 'terminal', 'delete')
        if mode not in valid_modes:
            return json.dumps({'error': f'無效的 mode: {mode}，允許值: {", ".join(valid_modes)}'})

        with session_scope() as s:
            atom = s.query(KnowledgeAtom).filter(KnowledgeAtom.id == atom_id).first()
            if not atom:
                return json.dumps({'error': f'原子 {atom_id} 不存在'})

            if mode == 'delete':
                atom.is_deleted = True
                action = '已軟刪除'
            elif mode == 'terminal':
                atom.lifecycle = 'terminal'
                action = '已標記為終止'
            else:
                atom.lifecycle = 'archived'
                action = '已歸檔'

            return json.dumps({
                'id': atom.id,
                'title': atom.title,
                'message': f'原子 {atom_id} {action}',
            }, ensure_ascii=False)

    @mcp.tool()
    def note_check(
        content: str,
        check_scope: str = 'all',
        limit: int = 10,
    ) -> str:
        """比對一段文字與既有知識庫，回報重複、矛盾、相關原子。

        用途：新想法進來時，檢查是否與既有知識重複或矛盾。

        content: 要檢查的文字內容
        check_scope: 'all' 或指定 tag 名稱縮小檢查範圍
        limit: 回傳相似原子上限（預設 10，最大 50）

        回傳:
          similar: 相似度最高的原子列表（含 similarity 分數）
          contradictions: 相似原子的 contradicts 關係鏈
          suggestion: 'duplicate_suspect' / 'contradiction_found' / 'novel'
        """
        with session_scope() as s:
            result = consistency_service.check_consistency(
                s, content,
                check_scope=check_scope,
                limit=min(limit, 50),
            )
            return json.dumps(result, ensure_ascii=False)
