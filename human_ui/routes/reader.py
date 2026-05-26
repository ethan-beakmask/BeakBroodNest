# -*- coding: utf-8 -*-
"""Reader -- 對話歸檔閱覽器

移植自 BeakArchive 的兩欄 + 頂部 chips 布局，呈現 BBN 自己的
conversations / conversation_turns（即 Claude Code 對話歸檔）。

純讀。資料源是 BBN P0 已 import 的對話表，與 KnowledgeAtom 無關。

URL：
  /beakbroodnest/reader/             全部對話 thread list
  /beakbroodnest/reader/?proj=<b32>  指定 project 過濾
  /beakbroodnest/reader/t/<conv_id>  對話詳情（保留 ?proj/?lp/?lq）
  /beakbroodnest/reader/t/<conv_id>/sidechain  AJAX sidechain 子 thread partial
"""
import base64
import math
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

from flask import Blueprint, abort, render_template, request

import markdown as md
import bleach
from sqlalchemy import text

from core.db import session_scope


bp = Blueprint('reader', __name__)


# ----- markdown safe render -----

_MD_ALLOWED_TAGS = {
    'p', 'br', 'hr', 'pre', 'code', 'blockquote',
    'strong', 'em', 'b', 'i', 'u', 's', 'del', 'ins', 'mark', 'sub', 'sup',
    'ul', 'ol', 'li', 'dl', 'dt', 'dd',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'a', 'img',
    'table', 'thead', 'tbody', 'tr', 'th', 'td', 'caption',
    'details', 'summary', 'span', 'div',
}
_MD_ALLOWED_ATTRS = {
    '*': ['class', 'id', 'title'],
    'a': ['href', 'title', 'rel', 'target', 'class'],
    'img': ['src', 'alt', 'title', 'width', 'height', 'class'],
    'th': ['align', 'colspan', 'rowspan', 'scope'],
    'td': ['align', 'colspan', 'rowspan'],
    'code': ['class'],
    'pre': ['class'],
}
_MD_ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']


def _md(textstr: str) -> str:
    if not textstr:
        return ''
    html = md.markdown(textstr, extensions=['fenced_code', 'tables', 'nl2br'])
    return bleach.clean(html,
                        tags=_MD_ALLOWED_TAGS,
                        attributes=_MD_ALLOWED_ATTRS,
                        protocols=_MD_ALLOWED_PROTOCOLS,
                        strip=False)


@bp.app_template_filter('reader_md')
def reader_md_filter(s):
    return _md(s)


@bp.app_template_filter('reader_dt')
def reader_dt_filter(dt: Optional[datetime]) -> str:
    if not dt:
        return ''
    return dt.strftime('%Y-%m-%d %H:%M')


# ----- project slug helpers -----

def _proj_to_slug(path: str) -> str:
    if not path:
        return ''
    return base64.urlsafe_b64encode(path.encode('utf-8')).rstrip(b'=').decode('ascii')


def _slug_to_proj(slug: str) -> Optional[str]:
    if not slug:
        return None
    try:
        pad = '=' * (-len(slug) % 4)
        return base64.urlsafe_b64decode(slug + pad).decode('utf-8')
    except Exception:
        return None


def _proj_display(path: str) -> str:
    if not path:
        return '(unknown)'
    # 取末段
    return path.rsplit('/', 1)[-1] or path


# ----- title derive -----

_TITLE_PREFIX = re.compile(r'^\[CC-[A-Z-]+(?:=[^\]]+)?\]\s*', re.MULTILINE)


def _derive_title(first_user: Optional[str], project_path: Optional[str],
                  conv_id: str) -> str:
    if first_user:
        body = _TITLE_PREFIX.sub('', first_user).strip()
        body = body.split('\n', 1)[0]
        if len(body) > 80:
            body = body[:80] + '…'
        if body:
            return body
    proj = _proj_display(project_path or '')
    return f'[{proj}] {conv_id[:8]}'


# ----- project chips -----

_SUMMARY_TOPIC_PREFIX = '請對以下 topic 產出結構化摘要。'
_CC_PREFIX_REGEX = r'^\[CC-[A-Z-]+(=[^\]]+)?\]\s*'


def _project_stats():
    """所有 project_path 的對話計數（只算 root conv，不算 sidechain）。"""
    sql = text('''
        SELECT project_path, COUNT(*) AS n
        FROM conversations
        WHERE parent_conversation_id IS NULL AND is_sidechain = FALSE
        GROUP BY project_path
        ORDER BY n DESC
    ''')
    out = []
    with session_scope() as s:
        for row in s.execute(sql):
            path = row[0] or ''
            out.append(dict(
                path=path,
                slug=_proj_to_slug(path),
                display=_proj_display(path),
                count=row[1],
            ))
    return out


# ----- thread list -----

def _build_thread_filter(*, project_path=None, query=None, parent_id=None,
                         include_sidechain=False, show_summary=False):
    where = []
    params = {}
    if parent_id:
        where.append('c.parent_conversation_id = :parent_id')
        where.append('c.is_sidechain = TRUE')
        params['parent_id'] = parent_id
    else:
        if not include_sidechain:
            where.append('(c.is_sidechain = FALSE AND c.parent_conversation_id IS NULL)')

    if project_path:
        where.append('c.project_path = :proj')
        params['proj'] = project_path

    if query:
        where.append('''(c.project_path ILIKE :pat
            OR EXISTS (SELECT 1 FROM conversation_turns ct
                       WHERE ct.conversation_id = c.id AND ct.content ILIKE :pat))''')
        params['pat'] = f'%{query}%'

    if not show_summary and not parent_id:
        where.append('''NOT EXISTS (
            SELECT 1 FROM conversation_turns ct1
            WHERE ct1.conversation_id = c.id
              AND ct1.role IN ('user','human')
              AND ct1.content IS NOT NULL AND ct1.content <> ''
              AND ct1.turn_seq = (
                  SELECT MIN(turn_seq) FROM conversation_turns ct2
                  WHERE ct2.conversation_id = c.id
                    AND ct2.role IN ('user','human')
                    AND ct2.content IS NOT NULL AND ct2.content <> ''
              )
              AND regexp_replace(ct1.content, :cc_re, '') LIKE :sum_pat
        )''')
        params['cc_re'] = _CC_PREFIX_REGEX
        params['sum_pat'] = _SUMMARY_TOPIC_PREFIX + '%'

    wsql = ('WHERE ' + ' AND '.join(where)) if where else ''
    return wsql, params


def _list_threads(s, *, project_path=None, query=None, parent_id=None,
                  include_sidechain=False, show_summary=False,
                  limit=50, offset=0):
    wsql, params = _build_thread_filter(
        project_path=project_path, query=query, parent_id=parent_id,
        include_sidechain=include_sidechain, show_summary=show_summary,
    )
    sidechain_subq = ('0' if parent_id else
                      '(SELECT count(*) FROM conversations sc '
                      'WHERE sc.parent_conversation_id = c.id AND sc.is_sidechain = TRUE)')
    sql = text(f'''
        SELECT c.id, c.project_path, c.session_id, c.total_turns,
               c.first_timestamp, c.last_timestamp,
               c.is_sidechain, c.parent_conversation_id, c.git_branch,
               (SELECT content FROM conversation_turns ct
                WHERE ct.conversation_id = c.id
                  AND ct.role IN ('user', 'human')
                  AND ct.content IS NOT NULL AND ct.content <> ''
                ORDER BY ct.turn_seq LIMIT 1) AS first_user,
               {sidechain_subq} AS sidechain_count
        FROM conversations c
        {wsql}
        ORDER BY c.first_timestamp DESC
        LIMIT :limit OFFSET :offset
    ''')
    params['limit'] = limit
    params['offset'] = offset

    out = []
    for r in s.execute(sql, params):
        cid_s = str(r[0])
        out.append(dict(
            id=cid_s,
            project_path=r[1] or '',
            project_display=_proj_display(r[1] or ''),
            session_id=r[2],
            total_turns=r[3] or 0,
            first_timestamp=r[4],
            last_timestamp=r[5],
            is_sidechain=bool(r[6]),
            parent_id=str(r[7]) if r[7] else None,
            git_branch=r[8],
            title=_derive_title(r[9], r[1], cid_s),
            sidechain_count=r[10] or 0,
        ))
    return out


def _count_threads(s, *, project_path=None, query=None, parent_id=None,
                   include_sidechain=False, show_summary=False):
    wsql, params = _build_thread_filter(
        project_path=project_path, query=query, parent_id=parent_id,
        include_sidechain=include_sidechain, show_summary=show_summary,
    )
    sql = text(f'SELECT count(*) FROM conversations c {wsql}')
    return s.execute(sql, params).scalar() or 0


def _thread_list_payload(s, *, project_path=None, page=1, page_size=50,
                         query=None, active_thread_id=None, show_summary=False):
    page = max(1, int(page or 1))
    page_size = min(200, max(10, int(page_size or 50)))
    offset = (page - 1) * page_size

    threads = _list_threads(s, project_path=project_path, query=query,
                            show_summary=show_summary,
                            limit=page_size, offset=offset)
    total = _count_threads(s, project_path=project_path, query=query,
                           show_summary=show_summary)
    total_pages = max(1, math.ceil(total / page_size)) if total else 1

    def _link(target_page):
        args = request.args.to_dict(flat=True)
        args['lp'] = str(target_page)
        if query:
            args['lq'] = query
        else:
            args.pop('lq', None)
        return f'{request.path}?{urlencode(args)}'

    return dict(
        threads=threads,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        query=query,
        active_thread_id=active_thread_id,
        prev_url=_link(max(1, page - 1)),
        next_url=_link(min(total_pages, page + 1)),
    )


# ----- posts -----

def _get_thread(s, conv_id: str):
    sql = text('''
        SELECT c.id, c.project_path, c.session_id, c.total_turns,
               c.first_timestamp, c.last_timestamp,
               c.is_sidechain, c.parent_conversation_id, c.git_branch,
               (SELECT content FROM conversation_turns ct
                WHERE ct.conversation_id = c.id AND ct.role IN ('user', 'human')
                  AND ct.content IS NOT NULL AND ct.content <> ''
                ORDER BY ct.turn_seq LIMIT 1) AS first_user
        FROM conversations c WHERE c.id = :cid
    ''')
    r = s.execute(sql, {'cid': conv_id}).fetchone()
    if not r:
        return None
    cid_s = str(r[0])
    return dict(
        id=cid_s,
        project_path=r[1] or '',
        project_display=_proj_display(r[1] or ''),
        session_id=r[2],
        total_turns=r[3] or 0,
        first_timestamp=r[4],
        last_timestamp=r[5],
        is_sidechain=bool(r[6]),
        parent_id=str(r[7]) if r[7] else None,
        git_branch=r[8],
        title=_derive_title(r[9], r[1], cid_s),
    )


def _get_posts(s, conv_id: str, limit=None, offset=0):
    sql_str = '''
        SELECT id, turn_seq, role, content, tool_name, tool_params, tool_use_id,
               tool_is_error, has_thinking, thinking_text, is_sidechain,
               model, usage_input_tokens, usage_output_tokens, timestamp
        FROM conversation_turns
        WHERE conversation_id = :cid
        ORDER BY turn_seq ASC
    '''
    params = {'cid': conv_id}
    if limit is not None:
        sql_str += ' LIMIT :limit OFFSET :offset'
        params['limit'] = limit
        params['offset'] = offset

    out = []
    for r in s.execute(text(sql_str), params):
        (tid, seq, role, content, tname, tparams, tuid, tis_err,
         ht, tt, sc, model, in_tok, out_tok, ts) = r
        kind = 'text'
        if tname:
            kind = 'tool_use'
        elif role == 'attachment':
            kind = 'attachment'
        elif ht:
            kind = 'thinking'

        blocks = []
        if ht and tt:
            blocks.append({'type': 'thinking', 'body': tt})
        if tname:
            blocks.append({
                'type': 'tool_use', 'name': tname,
                'input': tparams, 'tool_use_id': tuid,
                'is_error': bool(tis_err) if tis_err is not None else False,
            })

        out.append(dict(
            id=str(tid),
            seq=seq,
            sender=role or '',
            kind=kind,
            body=content or '',
            timestamp=ts,
            is_sidechain=bool(sc),
            tool_name=tname,
            tool_use_id=tuid,
            tool_is_error=bool(tis_err) if tis_err is not None else False,
            has_thinking=bool(ht),
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            blocks=blocks,
        ))
    return out


def _count_posts(s, conv_id: str) -> int:
    return s.execute(
        text('SELECT count(*) FROM conversation_turns WHERE conversation_id = :cid'),
        {'cid': conv_id},
    ).scalar() or 0


# ----- routes -----

@bp.get('/reader/')
@bp.get('/reader')
def reader_home():
    proj_slug = request.args.get('proj') or ''
    project_path = _slug_to_proj(proj_slug) if proj_slug else None
    page = request.args.get('lp', 1)
    query = request.args.get('lq') or None
    show_summary = bool(request.args.get('show_summary'))

    with session_scope() as s:
        tl = _thread_list_payload(s, project_path=project_path,
                                  page=page, query=query,
                                  show_summary=show_summary)

    return render_template(
        'reader_home.html',
        projects=_project_stats(),
        current_slug=proj_slug,
        current_display=_proj_display(project_path) if project_path else '全部',
        thread_list_data=tl,
        show_summary=show_summary,
    )


@bp.get('/reader/t/<conv_id>/sidechain')
def reader_sidechain(conv_id):
    with session_scope() as s:
        children = _list_threads(s, parent_id=conv_id, include_sidechain=True,
                                 limit=100)
    return render_template('_reader_sidechain.html', children=children)


@bp.get('/reader/t/<conv_id>')
def reader_thread_detail(conv_id):
    proj_slug = request.args.get('proj') or ''
    project_path_filter = _slug_to_proj(proj_slug) if proj_slug else None

    page = max(1, int(request.args.get('page', 1)))
    page_size = min(500, max(20, int(request.args.get('size', 200))))
    mode = request.args.get('mode', 'linear')
    if mode not in ('linear', 'tree'):
        mode = 'linear'
    show_summary = bool(request.args.get('show_summary'))

    with session_scope() as s:
        thread = _get_thread(s, conv_id)
        if not thread:
            abort(404)

        total_posts = _count_posts(s, conv_id)
        use_paging = total_posts > page_size
        if use_paging:
            offset = (page - 1) * page_size
            posts = _get_posts(s, conv_id, limit=page_size, offset=offset)
            total_pages = max(1, math.ceil(total_posts / page_size))
        else:
            posts = _get_posts(s, conv_id)
            total_pages = 1

        parent_thread = None
        if thread['parent_id']:
            parent_thread = _get_thread(s, thread['parent_id'])

        tl = _thread_list_payload(
            s, project_path=project_path_filter,
            page=request.args.get('lp', 1),
            query=request.args.get('lq') or None,
            active_thread_id=thread['id'],
            show_summary=show_summary,
        )

    return render_template(
        'reader_thread.html',
        projects=_project_stats(),
        current_slug=proj_slug,
        current_display=_proj_display(project_path_filter) if project_path_filter else '全部',
        thread_list_data=tl,
        thread=thread,
        parent_thread=parent_thread,
        posts=posts,
        total_posts=total_posts,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        use_paging=use_paging,
        mode=mode,
        show_summary=show_summary,
    )


# ----- search (跨 project) -----

@bp.get('/reader/search')
def reader_search():
    query = (request.args.get('q') or '').strip()
    if not query:
        from flask import redirect, url_for
        return redirect(url_for('reader.reader_home'))

    limit = min(100, max(10, int(request.args.get('limit', 30))))
    pat = f'%{query}%'

    sql = text('''
        SELECT c.id, c.project_path, c.first_timestamp, c.is_sidechain,
               t.id AS turn_id, t.turn_seq,
               substring(t.content FROM GREATEST(1, position(:q in t.content)-60) FOR 240) AS snippet,
               (SELECT content FROM conversation_turns ct
                WHERE ct.conversation_id = c.id AND ct.role IN ('user','human')
                  AND ct.content IS NOT NULL AND ct.content <> ''
                ORDER BY ct.turn_seq LIMIT 1) AS first_user
        FROM conversations c
        JOIN LATERAL (
            SELECT id, turn_seq, content FROM conversation_turns
            WHERE conversation_id = c.id AND content ILIKE :pat
            ORDER BY turn_seq ASC LIMIT 1
        ) t ON TRUE
        ORDER BY c.first_timestamp DESC
        LIMIT :limit
    ''')

    hits = []
    with session_scope() as s:
        for r in s.execute(sql, {'q': query, 'pat': pat, 'limit': limit}):
            cid_s = str(r[0])
            title = _derive_title(r[7], r[1], cid_s)
            if r[3]:
                title = '↳ ' + title
            hits.append(dict(
                thread_id=cid_s,
                title=title,
                project_path=r[1] or '',
                project_display=_proj_display(r[1] or ''),
                created_at=r[2],
                snippet=(r[6] or '').replace('\n', ' ').strip(),
            ))

    return render_template(
        'reader_search.html',
        projects=_project_stats(),
        current_slug='',
        current_display='搜尋結果',
        thread_list_data=None,
        query=query,
        hits=hits,
        limit=limit,
    )
