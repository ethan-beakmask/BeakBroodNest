# -*- coding: utf-8 -*-
"""跨專案訊息工具: note_send / note_inbox / note_inbox_read

解決 tag 廣播式通知的四大問題：
  1. 有明確收件人（recipient）
  2. 有已讀/未讀狀態
  3. 有寄件人身份（sender）+ 啟動目錄（sender_cwd）
  4. 各專案只需 CLAUDE.md 加一條 note_inbox 規則

身份格式: {scope}:{identity}
  project:beakcortex, task:daily-review, user:ethan
"""
import json
import datetime
import logging
import os

from sqlalchemy import and_

from core.db import session_scope
from core.models import Message, KnowledgeAtom

logger = logging.getLogger('beak_cortex.mcp.messaging')

# ============================================================
# 身份推斷
# ============================================================

# 工作目錄 -> 專案名稱的映射（啟動時由 mcp_server.py 設定）
_current_identity: str = ''
_current_cwd: str = ''

# 從啟動目錄推斷專案身份的對照表
_CWD_PROJECT_MAP = {
    '/opt/BeakCortex': 'project:beakcortex',
    '/opt/BeakCortex-dev': 'project:beakcortex',
    '/opt/BeakPlatform': 'project:beakplatform',
    '/opt/BeakPlatform-dev': 'project:beakplatform',
    '/opt/BeakMeshWall': 'project:beakmeshwall',
    '/opt/BeakMeshWall-dev': 'project:beakmeshwall',
    '/opt/BeakGuard': 'project:beakmeshwall',
    '/opt/BeakGuard-dev': 'project:beakmeshwall',
    '/opt/BeakRisk': 'project:beakrisk',
    '/opt/BeakRisk-dev': 'project:beakrisk',
    '/opt/BeakSeal': 'project:beakseal',
    '/opt/BeakSeal-dev': 'project:beakseal',
}


def init_identity(config_identity: str = '', cwd: str = ''):
    """初始化寄件人身份。

    優先順序：
    1. config.ini [identity] project_id（明確設定）
    2. 啟動目錄對照 _CWD_PROJECT_MAP
    3. 從啟動目錄名稱推導 project:{basename}
    """
    global _current_identity, _current_cwd

    _current_cwd = cwd or os.getcwd()

    if config_identity:
        # config 明確指定，直接用
        _current_identity = config_identity
    else:
        # 從 cwd 推斷
        resolved = os.path.realpath(_current_cwd)
        _current_identity = _CWD_PROJECT_MAP.get(resolved, '')

        if not _current_identity:
            # 檢查是否在已知路徑的子目錄
            for known_path, identity in _CWD_PROJECT_MAP.items():
                if resolved.startswith(known_path + '/'):
                    _current_identity = identity
                    break

        if not _current_identity:
            # 最後手段：用目錄名
            basename = os.path.basename(resolved).lower()
            basename = basename.replace('-dev', '')
            _current_identity = f'project:{basename}'

    logger.info(f'Messaging identity: {_current_identity} (cwd: {_current_cwd})')


def get_identity() -> str:
    if not _current_identity:
        init_identity()
    return _current_identity


def get_cwd() -> str:
    return _current_cwd


# ============================================================
# 已知收件人清單（驗證用）
# ============================================================

KNOWN_RECIPIENTS = {
    # 專案
    'project:beakcortex',
    'project:beakplatform',
    'project:beakmeshwall',
    'project:beakrisk',
    'project:beakseal',
    # 人類
    'user:ethan',
    # 任務（可動態擴充，不在此強制驗證）
}


def register(mcp):

    @mcp.tool()
    def note_send(
        recipient: str,
        subject: str,
        body: str = '',
        message_type: str = 'notice',
        ref_atom_id: int | None = None,
        reply_to_id: int | None = None,
        sender: str = '',
    ) -> str:
        """發送訊息給指定的專案/Claude/人類。

        recipient: 收件人身份，格式 {scope}:{identity}
          project:beakcortex     -- BeakCortex 專案的 Claude
          project:beakplatform   -- BeakPlatform 專案的 Claude
          project:beakmeshwall   -- BeakMeshWall 專案的 Claude
          project:beakrisk       -- BeakRisk 專案的 Claude
          project:beakseal       -- BeakSeal 專案的 Claude
          task:daily-review      -- 每日復盤排程
          task:{任務名}          -- 指定任務
          user:ethan             -- 人類 Ethan

        subject: 訊息主旨
        body: 訊息內容（支援 markdown）
        message_type: 訊息類型
          notice  -- 純通知，收件人知道即可（預設）
          request -- 需要收件人採取行動
          alert   -- 緊急通知（適用於人類收件人）
        ref_atom_id: 關聯的知識原子 ID（可選）
        reply_to_id: 回覆哪則訊息的 ID（可選，防止重複回覆）
        sender: 覆寫寄件人身份（通常不需要，自動從啟動環境推斷）

        自我迴圈防護：禁止寄給自己。
        """
        actual_sender = sender or get_identity()

        if not actual_sender:
            return json.dumps({
                'error': '無法判斷寄件人身份。請在 config.ini [identity] 設定 project_id，'
                         '或確認工作目錄在已知專案路徑下。'
            }, ensure_ascii=False)

        if not recipient:
            return json.dumps({'error': 'recipient 不可為空'}, ensure_ascii=False)

        if not subject.strip():
            return json.dumps({'error': 'subject 不可為空'}, ensure_ascii=False)

        # 自我迴圈防護
        if actual_sender == recipient:
            return json.dumps({
                'error': f'禁止寄給自己 ({actual_sender})。'
                         f'若需要留備忘，請用 note_store。',
            }, ensure_ascii=False)

        # 驗證 message_type
        if message_type not in Message.VALID_TYPES:
            return json.dumps({
                'error': f'無效的 message_type: {message_type}，'
                         f'允許值: {", ".join(Message.VALID_TYPES)}',
            }, ensure_ascii=False)

        # 驗證 recipient 格式
        if ':' not in recipient:
            return json.dumps({
                'error': f'recipient 格式錯誤: {recipient}，'
                         f'應為 scope:identity（如 project:beakplatform）',
            }, ensure_ascii=False)

        # 驗證 recipient 是否為已知身份（task: 開頭除外，允許動態建立）
        scope = recipient.split(':')[0]
        if scope != 'task' and recipient not in KNOWN_RECIPIENTS:
            return json.dumps({
                'error': f'未知的收件人: {recipient}。'
                         f'已知收件人: {", ".join(sorted(KNOWN_RECIPIENTS))}。'
                         f'注意: -dev 目錄與正式目錄共用同一身份，'
                         f'例如 project:beakplatform 同時代表 '
                         f'/opt/BeakPlatform 和 /opt/BeakPlatform-dev。',
            }, ensure_ascii=False)

        with session_scope() as s:
            # 驗證 ref_atom_id
            if ref_atom_id is not None:
                atom = s.query(KnowledgeAtom).filter(
                    KnowledgeAtom.id == ref_atom_id,
                    KnowledgeAtom.is_deleted == False,
                ).first()
                if not atom:
                    return json.dumps({
                        'error': f'關聯原子 {ref_atom_id} 不存在',
                    }, ensure_ascii=False)

            # 驗證 reply_to_id
            if reply_to_id is not None:
                original = s.query(Message).filter(
                    Message.id == reply_to_id
                ).first()
                if not original:
                    return json.dumps({
                        'error': f'回覆目標訊息 {reply_to_id} 不存在',
                    }, ensure_ascii=False)
                # 檢查是否已回覆過
                existing_reply = s.query(Message).filter(
                    Message.reply_to_id == reply_to_id,
                    Message.sender == actual_sender,
                ).first()
                if existing_reply:
                    return json.dumps({
                        'error': f'已回覆過訊息 {reply_to_id}（回覆 id={existing_reply.id}），'
                                 f'避免重複回覆。',
                    }, ensure_ascii=False)

            msg = Message(
                sender=actual_sender,
                sender_cwd=get_cwd(),
                recipient=recipient,
                subject=subject,
                body=body,
                message_type=message_type,
                ref_atom_id=ref_atom_id,
                reply_to_id=reply_to_id,
            )
            s.add(msg)
            s.flush()

            return json.dumps({
                'id': msg.id,
                'sender': msg.sender,
                'recipient': msg.recipient,
                'subject': msg.subject,
                'message_type': msg.message_type,
                'message': f'訊息已發送 (id={msg.id})',
            }, ensure_ascii=False)

    @mcp.tool()
    def note_inbox(
        unread_only: bool = True,
        message_type: str = '',
        sender: str = '',
        limit: int = 20,
        recipient: str = '',
    ) -> str:
        """查詢寄給我的訊息（收件匣）。

        自動以當前身份作為收件人，查詢寄給我的訊息。
        自動排除自己發的訊息（防止自我迴圈）。

        unread_only: 僅顯示未讀（預設 True）
        message_type: 篩選類型 (notice/request/alert)，空字串=全部
        sender: 篩選特定寄件人（如 project:beakmeshwall）
        limit: 回傳上限（預設 20，最大 100）
        recipient: 覆寫收件人身份（通常不需要，自動推斷）

        建議各專案 CLAUDE.md 加入: 啟動時呼叫 note_inbox 檢查未讀訊息
        """
        me = recipient or get_identity()
        if not me:
            return json.dumps({
                'error': '無法判斷收件人身份。請在 config.ini [identity] 設定 project_id。'
            }, ensure_ascii=False)

        limit = min(limit, 100)

        with session_scope() as s:
            q = s.query(Message).filter(
                Message.recipient == me,
                Message.sender != me,  # 防止自我迴圈
            )

            if unread_only:
                q = q.filter(Message.is_read == False)

            if message_type:
                if message_type not in Message.VALID_TYPES:
                    return json.dumps({
                        'error': f'無效的 message_type: {message_type}',
                    }, ensure_ascii=False)
                q = q.filter(Message.message_type == message_type)

            if sender:
                q = q.filter(Message.sender == sender)

            q = q.order_by(Message.created_at.desc())
            messages = q.limit(limit).all()

            items = [msg.to_dict() for msg in messages]
            unread_count = s.query(Message).filter(
                Message.recipient == me,
                Message.sender != me,
                Message.is_read == False,
            ).count()

            return json.dumps({
                'identity': me,
                'unread_count': unread_count,
                'returned': len(items),
                'items': items,
            }, ensure_ascii=False)

    @mcp.tool()
    def note_inbox_read(
        message_ids: list[int] | None = None,
        mark_all: bool = False,
        recipient: str = '',
    ) -> str:
        """標記訊息為已讀。

        message_ids: 指定要標記的訊息 ID 列表
        mark_all: 標記所有未讀為已讀（忽略 message_ids）
        recipient: 覆寫收件人身份（通常不需要）

        兩種用法:
          1. note_inbox_read(message_ids=[1, 2, 3]) -- 標記特定訊息
          2. note_inbox_read(mark_all=True) -- 全部已讀
        """
        me = recipient or get_identity()
        if not me:
            return json.dumps({
                'error': '無法判斷收件人身份。'
            }, ensure_ascii=False)

        if not mark_all and not message_ids:
            return json.dumps({
                'error': '需提供 message_ids 或設 mark_all=True',
            }, ensure_ascii=False)

        now = datetime.datetime.now()

        with session_scope() as s:
            q = s.query(Message).filter(
                Message.recipient == me,
                Message.is_read == False,
            )

            if not mark_all and message_ids:
                q = q.filter(Message.id.in_(message_ids))

            messages = q.all()
            count = 0
            marked_ids = []
            for msg in messages:
                msg.is_read = True
                msg.read_at = now
                count += 1
                marked_ids.append(msg.id)

            remaining = s.query(Message).filter(
                Message.recipient == me,
                Message.sender != me,
                Message.is_read == False,
            ).count()

            return json.dumps({
                'marked_count': count,
                'marked_ids': marked_ids,
                'remaining_unread': remaining,
                'message': f'已標記 {count} 則訊息為已讀',
            }, ensure_ascii=False)
