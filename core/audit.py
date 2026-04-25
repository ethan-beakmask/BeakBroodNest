# -*- coding: utf-8 -*-
"""欄位變更歷史記錄（Audit Log）

所有 entry_field_values 的寫入點共用此函式，
只在值真正改變時才寫入 change_log。
"""

from core.models import EntryFieldChangeLog


def log_field_change(s, entry_id, field_id, old_value, new_value, changed_by='user'):
    """記錄欄位值變更。值沒變則不記錄。

    Args:
        s: SQLAlchemy session
        entry_id: atom_entries.id
        field_id: entry_schema_fields.id
        old_value: 變更前的文字值（None 表示新建）
        new_value: 變更後的文字值
        changed_by: 變更來源標記
    """
    old_str = str(old_value) if old_value is not None else None
    new_str = str(new_value) if new_value is not None else None
    if old_str == new_str:
        return
    s.add(EntryFieldChangeLog(
        entry_id=entry_id,
        field_id=field_id,
        old_value=old_str,
        new_value=new_str,
        changed_by=changed_by,
    ))
