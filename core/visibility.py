# -*- coding: utf-8 -*-
"""AI 可見性判定：哪些卡片預設不該進到 AI 的搜尋結果。

背景：白板原本人機共用，使用者在上面隨手記錄想法，AI 搜尋知識庫時會把這些
草稿當成知識引用。2026-08-07 把白板拆成人機兩套，但白板歸屬只擋得住
project_tasks 一條路徑 -- note_search 查的是 knowledge_atoms，與白板無關，
因此另外在 atom 層做判定。

判準掛在白板的 audience 欄位，不掛 owner：
  * owner 已經兼任「建立者識別」與「寫入權限閘門」（見 note_update 與
    human_ui/routes/atoms.py 的雙向互鎖），再兼「給誰看」會讓三個語意綁死，
    調整可見性就會連帶動到寫入權限
  * owner 當判準也不準 -- 有幾張使用者的主題白板是 owner='claude'
  * 建立者必須在卡片搬動、複製後保持不變，可見性卻要跟著白板走，兩者本質不同

不用標籤而用白板欄位的理由：標籤是貼上去那一刻的快照，使用者新建的卡不會自動
帶標籤，隔離會隨時間腐爛。白板欄位是即時判定，新卡自動繼承所在白板的設定。

隔離條件：卡片出現的白板全都是 audience='human'。只要它同時出現在任何一張
ai 或 shared 白板上，就視為使用者刻意要給 AI 看，不隔離。不在任何白板上的
卡片（多半是透過對話存進知識庫的正式知識）一律不隔離。
"""
from sqlalchemy import text

# 使用者自用白板的 audience 值
HUMAN_AUDIENCE = 'human'

_SQL_EXCLUDE = """(
    NOT EXISTS (SELECT 1 FROM canvas_atoms _ca WHERE _ca.atom_id = {alias}.id)
    OR EXISTS (
        SELECT 1 FROM canvas_atoms _ca
        JOIN canvases _cv ON _cv.id = _ca.canvas_id
        WHERE _ca.atom_id = {alias}.id AND _cv.audience <> :human_audience
    )
)"""

_SQL_COUNT_HIDDEN = """
SELECT count(*) FROM knowledge_atoms a
WHERE a.is_deleted = FALSE
  AND EXISTS (SELECT 1 FROM canvas_atoms _ca WHERE _ca.atom_id = a.id)
  AND NOT EXISTS (
      SELECT 1 FROM canvas_atoms _ca
      JOIN canvases _cv ON _cv.id = _ca.canvas_id
      WHERE _ca.atom_id = a.id AND _cv.audience <> :human_audience
  )
"""


def should_exclude(include_human_boards: bool) -> bool:
    """判斷這次查詢要不要排除使用者白板的內容。"""
    return not include_human_boards


def sql_condition(alias: str = 'a') -> str:
    """給原生 SQL 用的可見性條件；需搭配 :human_audience 參數。"""
    return _SQL_EXCLUDE.format(alias=alias)


def bind_params() -> dict:
    """sql_condition 需要的參數。"""
    return {'human_audience': HUMAN_AUDIENCE}


def count_hidden(s, lifecycle: str = '', scope: str = 'default') -> int:
    """算出被隔離的卡片總數，讓呼叫端知道有東西沒回傳。"""
    sql = _SQL_COUNT_HIDDEN
    params = bind_params()
    if lifecycle:
        sql += " AND a.lifecycle = :lifecycle"
        params['lifecycle'] = lifecycle
    elif scope != 'full':
        sql += " AND a.lifecycle IN ('active', 'aging')"
    return s.execute(text(sql), params).scalar() or 0
