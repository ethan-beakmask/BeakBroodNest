# -*- coding: utf-8 -*-
"""Gantt 資料驗證器

功能：
- 循環依賴偵測（DFS）
- 日期合理性檢查（start <= end）
- baseline / actual 時差警告（不拒絕，只標記）
- 依賴違反偵測（A.actual_end > B.actual_start）
"""

from datetime import datetime


def validate_gantt_data(tasks, deps):
    """驗證甘特圖資料，回傳 (errors, warnings)。

    Parameters
    ----------
    tasks : list[dict]
        每筆至少有 entry_id, baseline_start, baseline_end,
        actual_start (可 None), actual_end (可 None)
    deps : list[dict]
        每筆有 from_entry_id, to_entry_id

    Returns
    -------
    tuple[list[str], list[str]]
        (errors, warnings) -- errors 非空表示資料不合法
    """
    errors = []
    warnings = []

    _check_dates(tasks, errors, warnings)
    _check_cycles(tasks, deps, errors)
    _check_dep_violations(tasks, deps, warnings)

    return errors, warnings


def _check_dates(tasks, errors, warnings):
    """日期合理性：start <= end，baseline/actual 時差警告。"""
    for t in tasks:
        title = t.get('title', f"entry#{t.get('entry_id', '?')}")

        bs = _parse_date(t.get('baseline_start'))
        be = _parse_date(t.get('baseline_end'))
        if bs and be and bs > be:
            errors.append(
                f'{title}: 原計畫開始 ({t["baseline_start"]}) '
                f'晚於原計畫結束 ({t["baseline_end"]})'
            )

        a_s = _parse_date(t.get('actual_start'))
        a_e = _parse_date(t.get('actual_end'))
        if a_s and a_e and a_s > a_e:
            errors.append(
                f'{title}: 實際開始 ({t["actual_start"]}) '
                f'晚於實際結束 ({t["actual_end"]})'
            )

        # baseline/actual 時差警告
        if be and a_e:
            delta = (a_e - be).days
            if delta > 0:
                warnings.append(
                    f'{title}: 實際結束比原計畫晚 {delta} 天'
                )
            elif delta < 0:
                warnings.append(
                    f'{title}: ��際結束比原計畫早 {abs(delta)} 天'
                )

        # 只有 actual 沒 baseline 是資料異常
        if (a_s or a_e) and not (bs or be):
            errors.append(
                f'{title}: 有實際日期但缺少原計畫��baseline）'
            )


def _check_cycles(tasks, deps, errors):
    """用 DFS 偵測循環依賴。

    blocks 語意：from blocks to（from 完成前 to 不能開始）
    等同有向圖 from -> to，偵測有向環。
    """
    task_ids = {t['entry_id'] for t in tasks}

    adj = {}
    for d in deps:
        f = d['from_entry_id']
        t = d['to_entry_id']
        if f in task_ids and t in task_ids:
            adj.setdefault(f, []).append(t)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {tid: WHITE for tid in task_ids}
    parent = {}

    def dfs(node):
        color[node] = GRAY
        for nb in adj.get(node, []):
            if color[nb] == GRAY:
                cycle = _trace_cycle(parent, node, nb)
                return cycle
            if color[nb] == WHITE:
                parent[nb] = node
                result = dfs(nb)
                if result is not None:
                    return result
        color[node] = BLACK
        return None

    for tid in task_ids:
        if color[tid] == WHITE:
            parent[tid] = None
            cycle = dfs(tid)
            if cycle is not None:
                errors.append(
                    f'循環依賴: {" -> ".join(str(x) for x in cycle)}'
                )
                return  # 一個循環就夠了，不繼續找


def _trace_cycle(parent, start, back_to):
    """從 DFS parent chain 回溯出循環路徑。"""
    path = [back_to, start]
    node = start
    while parent.get(node) is not None and parent[node] != back_to:
        node = parent[node]
        path.append(node)
    path.append(back_to)
    path.reverse()
    return path


def _check_dep_violations(tasks, deps, warnings):
    """依賴違反偵測��A blocks B 但 A.actual_end > B.actual_start。"""
    task_map = {t['entry_id']: t for t in tasks}

    for d in deps:
        from_t = task_map.get(d['from_entry_id'])
        to_t = task_map.get(d['to_entry_id'])
        if not from_t or not to_t:
            continue

        a_end = _parse_date(from_t.get('actual_end'))
        b_start = _parse_date(to_t.get('actual_start'))

        if a_end and b_start and a_end > b_start:
            from_title = from_t.get('title', str(d['from_entry_id']))
            to_title = to_t.get('title', str(d['to_entry_id']))
            warnings.append(
                f'依賴違反: {from_title} 實際結束 '
                f'({from_t["actual_end"]}) 晚於 '
                f'{to_title} 實際開始 ({to_t["actual_start"]})'
            )


def _parse_date(val):
    """解析日期字串，支援 YYYY-MM-DD 和 YYYY-MM-DDTHH:MM 格式。"""
    if not val:
        return None
    try:
        if 'T' in val:
            return datetime.fromisoformat(val)
        return datetime.strptime(val, '%Y-%m-%d')
    except (ValueError, TypeError):
        return None
