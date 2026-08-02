"""短代號產生與解析工具。

這個模組是卡片短代號的唯一產生入口；所有呼叫端都應透過
assign_ref_code() 取得 ref_code，避免繞過資料庫的併發安全計數器。
"""
import re

from sqlalchemy import func, text

from core.models import Canvas, KnowledgeAtom


PROJECT_CODE_RE = re.compile(r'^[A-Z][A-Z0-9]{1,7}$')


def assign_ref_code(s, atom: KnowledgeAtom, canvas_id: int | None = None) -> str:
    """替卡片指派短代號；已存在 ref_code 時直接回傳，保持冪等。"""
    if atom.ref_code:
        return atom.ref_code

    target_canvas_id = canvas_id if canvas_id is not None else atom.project_canvas_id
    if target_canvas_id is None:
        raise ValueError('卡片沒有專案歸屬，無法發號')

    ref_code = s.execute(
        text('SELECT next_ref_code(:cid)'),
        {'cid': target_canvas_id},
    ).scalar_one()

    atom.ref_code = ref_code
    if atom.project_canvas_id is None:
        atom.project_canvas_id = target_canvas_id
    return ref_code


def resolve_ref(s, ref) -> KnowledgeAtom | None:
    """用短代號或 atom id 解析卡片，軟刪除卡片視為不存在。"""
    if isinstance(ref, int):
        return (
            s.query(KnowledgeAtom)
            .filter(KnowledgeAtom.id == ref, KnowledgeAtom.is_deleted == False)
            .first()
        )

    ref_text = str(ref).strip()
    if ref_text.isdigit():
        return (
            s.query(KnowledgeAtom)
            .filter(KnowledgeAtom.id == int(ref_text), KnowledgeAtom.is_deleted == False)
            .first()
        )

    return (
        s.query(KnowledgeAtom)
        .filter(
            func.upper(KnowledgeAtom.ref_code) == ref_text.upper(),
            KnowledgeAtom.is_deleted == False,
        )
        .first()
    )


def ensure_project_code(s, canvas: Canvas, code: str) -> str:
    """設定或更新專案白板代號。

    已發過號的白板不可變更 code，因為已對外使用的舊短代號會與新前綴不一致；
    這類識別碼一旦發出就視為不可逆。
    """
    normalized = code.strip().upper()
    if not PROJECT_CODE_RE.fullmatch(normalized):
        raise ValueError('專案代號格式不符，需為 2 到 8 碼大寫英數，且第一碼為英文字母')

    owner = (
        s.query(Canvas)
        .filter(Canvas.code == normalized, Canvas.id != canvas.id)
        .first()
    )
    if owner:
        raise ValueError(f'專案代號 {normalized} 已被白板 {owner.id} 使用')

    has_counter = s.execute(
        text('SELECT 1 FROM project_ref_counters WHERE canvas_id = :cid'),
        {'cid': canvas.id},
    ).first()
    if has_counter and canvas.code != normalized:
        raise ValueError('此白板已發過短代號，不能變更專案代號 code')

    canvas.code = normalized
    return normalized
