# -*- coding: utf-8 -*-
"""脫敏/還原工具: note_sanitize / note_restore / sensitive_term_add / sensitive_term_list"""
import json
import re
import datetime
import logging

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import (
    KnowledgeAtom, SensitiveTerm, SanitizeSession,
)

logger = logging.getLogger('beak_broodnest.mcp.sanitize')

# 敏感詞彙類別
VALID_CATEGORIES = ('pii', 'infra', 'business', 'credential')
# 敏感度等級
VALID_SENSITIVITY = ('public', 'internal', 'confidential', 'restricted')


def _build_placeholder(prefix: str, index: int) -> str:
    """產生佔位符，如 INTERNAL_HOST_1"""
    return f'{{{prefix}_{index}}}'


def _apply_term_replacements(
    text: str,
    terms: list[SensitiveTerm],
    existing_mapping: dict,
    existing_reverse: dict,
    counter: dict,
) -> str:
    """用 sensitive_terms 表的詞彙對文本做替換。

    counter: {'next': int} 用來產生不重複的佔位符序號。
    會原地更新 existing_mapping 和 existing_reverse。
    """
    for term in terms:
        if term.is_regex:
            matches = re.findall(term.pattern, text)
            for match in matches:
                if match in existing_reverse:
                    text = text.replace(match, existing_reverse[match])
                else:
                    ph = _build_placeholder(term.placeholder_prefix, counter['next'])
                    counter['next'] += 1
                    existing_mapping[ph] = match
                    existing_reverse[match] = ph
                    text = text.replace(match, ph)
        else:
            if term.pattern in text:
                if term.pattern in existing_reverse:
                    text = text.replace(term.pattern, existing_reverse[term.pattern])
                else:
                    ph = _build_placeholder(term.placeholder_prefix, counter['next'])
                    counter['next'] += 1
                    existing_mapping[ph] = term.pattern
                    existing_reverse[term.pattern] = ph
                    text = text.replace(term.pattern, ph)
    return text


def register(mcp):

    @mcp.tool()
    def note_sanitize(
        content: str,
        atom_ids: list[int] | None = None,
        purpose: str = '',
        sensitivity_level: str = 'confidential',
        scope: str = 'global',
        extra_replacements: dict[str, str] | None = None,
    ) -> str:
        """對內容進行脫敏處理，產出可安全對外分享的文本。

        流程:
        1. 從 sensitive_terms 表載入符合 scope 的敏感詞彙
        2. 自動替換為佔位符 (如 {INTERNAL_HOST_1})
        3. 儲存映射表到 sanitize_sessions，跨對話可還原

        content: 要脫敏的原始文本
        atom_ids: 來源原子 ID 列表（可選，用於追溯）
        purpose: 用途說明，如 "StackOverflow 求助"
        sensitivity_level: 脫敏等級 (public/internal/confidential/restricted)
        scope: 詞彙表範圍篩選 (global 或專案名)
        extra_replacements: 額外的手動替換 {"原始值": "佔位前綴"}

        回傳: 脫敏後的文本 + session_id（用於 note_restore）
        """
        if sensitivity_level not in VALID_SENSITIVITY:
            return json.dumps({
                'error': f'無效的 sensitivity_level: {sensitivity_level}，'
                         f'允許值: {", ".join(VALID_SENSITIVITY)}'
            })

        with session_scope() as s:
            # 載入 sensitive_terms
            terms = (
                s.query(SensitiveTerm)
                .filter(SensitiveTerm.scope.in_([scope, 'global']))
                .order_by(
                    # 長的 pattern 先替換，避免短 pattern 部分匹配到長 pattern
                    func.length(SensitiveTerm.pattern).desc()
                )
                .all()
            )

            mapping = {}       # {placeholder: original}
            reverse = {}       # {original: placeholder}
            counter = {'next': 1}

            sanitized = content

            # 先套用 sensitive_terms
            if terms:
                sanitized = _apply_term_replacements(
                    sanitized, terms, mapping, reverse, counter
                )

            # 再套用 extra_replacements
            if extra_replacements:
                for original, prefix in extra_replacements.items():
                    if original in sanitized and original not in reverse:
                        ph = _build_placeholder(prefix, counter['next'])
                        counter['next'] += 1
                        mapping[ph] = original
                        reverse[original] = ph
                        sanitized = sanitized.replace(original, ph)

            # 儲存 session
            session = SanitizeSession(
                source_atom_ids=atom_ids,
                original_content=content,
                sanitized_content=sanitized,
                mapping=mapping,
                reverse_mapping=reverse,
                sensitivity_level=sensitivity_level,
                purpose=purpose,
            )
            s.add(session)
            s.flush()

            result = {
                'session_id': session.id,
                'sanitized_content': sanitized,
                'replacements_count': len(mapping),
                'mapping_preview': {k: '***' for k in mapping},
                'purpose': purpose,
            }
            return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    def note_restore(
        session_id: int,
        external_response: str,
    ) -> str:
        """將外部回覆中的佔位符還原為原始內容。

        session_id: note_sanitize 回傳的 session_id
        external_response: 從外部取得的回覆文本（含佔位符）

        回傳: 還原後的文本，佔位符已替換回真實值。
        """
        with session_scope() as s:
            session = s.query(SanitizeSession).filter(
                SanitizeSession.id == session_id
            ).first()

            if not session:
                return json.dumps({'error': f'找不到脫敏會話 {session_id}'})

            if session.expires_at and session.expires_at < datetime.datetime.now():
                return json.dumps({'error': f'脫敏會話 {session_id} 已過期'})

            restored = external_response
            mapping = session.mapping  # {placeholder: original}

            # 按佔位符長度降序替換，避免部分匹配
            for ph in sorted(mapping.keys(), key=len, reverse=True):
                restored = restored.replace(ph, mapping[ph])

            result = {
                'session_id': session_id,
                'restored_content': restored,
                'replacements_applied': sum(
                    1 for ph in mapping if ph in external_response
                ),
                'source_atom_ids': session.source_atom_ids,
            }
            return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    def sanitize_session_get(
        session_id: int,
    ) -> str:
        """查看脫敏會話的映射表（僅限本機使用）。

        session_id: 脫敏會話 ID
        回傳完整映射表，包含佔位符與原始值的對應。
        """
        with session_scope() as s:
            session = s.query(SanitizeSession).filter(
                SanitizeSession.id == session_id
            ).first()

            if not session:
                return json.dumps({'error': f'找不到脫敏會話 {session_id}'})

            return json.dumps(session.to_dict(), ensure_ascii=False)

    @mcp.tool()
    def sanitize_session_list(
        limit: int = 20,
    ) -> str:
        """列出最近的脫敏會話，按建立時間降序。

        limit: 回傳上限（預設 20）
        """
        with session_scope() as s:
            sessions = (
                s.query(SanitizeSession)
                .order_by(SanitizeSession.created_at.desc())
                .limit(min(limit, 100))
                .all()
            )

            items = []
            for ss in sessions:
                items.append({
                    'id': ss.id,
                    'source_atom_ids': ss.source_atom_ids,
                    'sensitivity_level': ss.sensitivity_level,
                    'purpose': ss.purpose,
                    'replacements_count': len(ss.mapping) if ss.mapping else 0,
                    'created_at': ss.created_at.isoformat() if ss.created_at else None,
                    'expires_at': ss.expires_at.isoformat() if ss.expires_at else None,
                })

            return json.dumps({
                'total': len(items),
                'items': items,
            }, ensure_ascii=False)

    @mcp.tool()
    def sensitive_term_add(
        category: str,
        pattern: str,
        placeholder_prefix: str,
        scope: str = 'global',
        is_regex: bool = False,
    ) -> str:
        """新增一筆敏感詞彙到登記表。

        AI 脫敏時會自動參照此表替換。

        category: 類別 (pii/infra/business/credential)
        pattern: 敏感字串或正則表達式
        placeholder_prefix: 替換時的前綴，如 "INTERNAL_HOST"
        scope: 適用範圍 (global 或專案名稱)
        is_regex: 是否為正則表達式（預設 False）
        """
        if category not in VALID_CATEGORIES:
            return json.dumps({
                'error': f'無效的 category: {category}，'
                         f'允許值: {", ".join(VALID_CATEGORIES)}'
            })

        if is_regex:
            try:
                re.compile(pattern)
            except re.error as e:
                return json.dumps({'error': f'無效的正則表達式: {e}'})

        with session_scope() as s:
            # 檢查重複
            existing = s.query(SensitiveTerm).filter(
                SensitiveTerm.pattern == pattern,
                SensitiveTerm.scope == scope,
            ).first()
            if existing:
                return json.dumps({
                    'error': f'相同 pattern 已存在 (id={existing.id})，'
                             f'scope={existing.scope}'
                })

            term = SensitiveTerm(
                category=category,
                pattern=pattern,
                placeholder_prefix=placeholder_prefix,
                scope=scope,
                is_regex=is_regex,
            )
            s.add(term)
            s.flush()

            return json.dumps({
                'id': term.id,
                'message': f'已新增敏感詞彙 (category={category}, scope={scope})',
            }, ensure_ascii=False)

    @mcp.tool()
    def sensitive_term_list(
        category: str = '',
        scope: str = '',
        limit: int = 50,
    ) -> str:
        """列出已登記的敏感詞彙。

        category: 篩選類別（空=全部）
        scope: 篩選範圍（空=全部）
        limit: 回傳上限
        """
        with session_scope() as s:
            q = s.query(SensitiveTerm)
            if category:
                q = q.filter(SensitiveTerm.category == category)
            if scope:
                q = q.filter(SensitiveTerm.scope == scope)

            terms = (
                q.order_by(SensitiveTerm.category, SensitiveTerm.id)
                .limit(min(limit, 200))
                .all()
            )

            return json.dumps({
                'total': len(terms),
                'items': [t.to_dict() for t in terms],
            }, ensure_ascii=False)

    @mcp.tool()
    def sensitive_term_remove(
        term_id: int,
    ) -> str:
        """移除一筆敏感詞彙。

        term_id: 要移除的詞彙 ID
        """
        with session_scope() as s:
            term = s.query(SensitiveTerm).filter(SensitiveTerm.id == term_id).first()
            if not term:
                return json.dumps({'error': f'找不到詞彙 id={term_id}'})

            info = term.to_dict()
            s.delete(term)
            return json.dumps({
                'message': f'已移除敏感詞彙 id={term_id}',
                'removed': info,
            }, ensure_ascii=False)
