#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gantt Validator 單元測試

驗收場景：
1. 線性依賴 A->B->C 正常通過
2. 循環依賴 A->B->A 回傳 error
3. 只有 baseline 無 actual 正常通過
4. start > end 回傳 error
5. 依賴違反偵測（A.actual_end > B.actual_start）
6. 有 actual 無 baseline 回傳 error
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from human_ui.validators.gantt_validator import validate_gantt_data


def test_linear_dependency_passes():
    """驗收 1: 線性依賴 A->B->C 無錯誤。"""
    tasks = [
        {'entry_id': 1, 'title': 'A', 'baseline_start': '2026-05-01',
         'baseline_end': '2026-05-03', 'actual_start': None, 'actual_end': None},
        {'entry_id': 2, 'title': 'B', 'baseline_start': '2026-05-04',
         'baseline_end': '2026-05-06', 'actual_start': None, 'actual_end': None},
        {'entry_id': 3, 'title': 'C', 'baseline_start': '2026-05-07',
         'baseline_end': '2026-05-09', 'actual_start': None, 'actual_end': None},
    ]
    deps = [
        {'from_entry_id': 1, 'to_entry_id': 2},
        {'from_entry_id': 2, 'to_entry_id': 3},
    ]
    errors, warnings = validate_gantt_data(tasks, deps)
    assert len(errors) == 0, f'Expected no errors, got: {errors}'
    print('PASS: linear dependency')


def test_cycle_dependency_rejected():
    """驗收 2: 循環依賴 A->B->A 回 error。"""
    tasks = [
        {'entry_id': 1, 'title': 'A', 'baseline_start': '2026-05-01',
         'baseline_end': '2026-05-03', 'actual_start': None, 'actual_end': None},
        {'entry_id': 2, 'title': 'B', 'baseline_start': '2026-05-04',
         'baseline_end': '2026-05-06', 'actual_start': None, 'actual_end': None},
    ]
    deps = [
        {'from_entry_id': 1, 'to_entry_id': 2},
        {'from_entry_id': 2, 'to_entry_id': 1},
    ]
    errors, warnings = validate_gantt_data(tasks, deps)
    assert len(errors) > 0, 'Expected cycle error'
    assert any('循環' in e for e in errors), f'Expected cycle msg, got: {errors}'
    print('PASS: cycle dependency rejected')


def test_baseline_only_passes():
    """驗收 3: 只有 baseline 無 actual，正常通過。"""
    tasks = [
        {'entry_id': 1, 'title': 'A', 'baseline_start': '2026-05-01',
         'baseline_end': '2026-05-03', 'actual_start': None, 'actual_end': None},
        {'entry_id': 2, 'title': 'B', 'baseline_start': '2026-05-04',
         'baseline_end': '2026-05-06', 'actual_start': None, 'actual_end': None},
    ]
    deps = []
    errors, warnings = validate_gantt_data(tasks, deps)
    assert len(errors) == 0, f'Expected no errors, got: {errors}'
    print('PASS: baseline only')


def test_date_inversion_rejected():
    """驗收 4: start > end 回 error。"""
    tasks = [
        {'entry_id': 1, 'title': 'Bad Task', 'baseline_start': '2026-05-10',
         'baseline_end': '2026-05-03', 'actual_start': None, 'actual_end': None},
    ]
    errors, warnings = validate_gantt_data(tasks, [])
    assert len(errors) > 0, 'Expected date error'
    assert any('晚於' in e for e in errors), f'Expected date msg, got: {errors}'
    print('PASS: date inversion rejected')


def test_dep_violation_warning():
    """驗收 5: A.actual_end > B.actual_start 產生 warning。"""
    tasks = [
        {'entry_id': 1, 'title': 'A', 'baseline_start': '2026-05-01',
         'baseline_end': '2026-05-03', 'actual_start': '2026-05-01',
         'actual_end': '2026-05-06'},
        {'entry_id': 2, 'title': 'B', 'baseline_start': '2026-05-04',
         'baseline_end': '2026-05-06', 'actual_start': '2026-05-04',
         'actual_end': '2026-05-08'},
    ]
    deps = [{'from_entry_id': 1, 'to_entry_id': 2}]
    errors, warnings = validate_gantt_data(tasks, deps)
    assert len(errors) == 0, f'Dep violation should be warning not error: {errors}'
    assert any('依賴違反' in w for w in warnings), f'Expected violation warning, got: {warnings}'
    print('PASS: dep violation warning')


def test_actual_without_baseline_rejected():
    """驗收 6: 有 actual 但無 baseline 是資料異常。"""
    tasks = [
        {'entry_id': 1, 'title': 'Orphan', 'baseline_start': None,
         'baseline_end': None, 'actual_start': '2026-05-01',
         'actual_end': '2026-05-03'},
    ]
    errors, warnings = validate_gantt_data(tasks, [])
    assert len(errors) > 0, 'Expected error for actual without baseline'
    assert any('baseline' in e for e in errors), f'Expected baseline msg: {errors}'
    print('PASS: actual without baseline rejected')


def test_three_node_cycle():
    """A->B->C->A 三節點循環。"""
    tasks = [
        {'entry_id': 1, 'title': 'A', 'baseline_start': '2026-05-01',
         'baseline_end': '2026-05-02', 'actual_start': None, 'actual_end': None},
        {'entry_id': 2, 'title': 'B', 'baseline_start': '2026-05-03',
         'baseline_end': '2026-05-04', 'actual_start': None, 'actual_end': None},
        {'entry_id': 3, 'title': 'C', 'baseline_start': '2026-05-05',
         'baseline_end': '2026-05-06', 'actual_start': None, 'actual_end': None},
    ]
    deps = [
        {'from_entry_id': 1, 'to_entry_id': 2},
        {'from_entry_id': 2, 'to_entry_id': 3},
        {'from_entry_id': 3, 'to_entry_id': 1},
    ]
    errors, warnings = validate_gantt_data(tasks, deps)
    assert any('循環' in e for e in errors), f'Expected 3-node cycle: {errors}'
    print('PASS: three node cycle')


def test_delta_days_warning():
    """baseline.end 和 actual.end 差異產生 warning。"""
    tasks = [
        {'entry_id': 1, 'title': 'Late Task', 'baseline_start': '2026-05-01',
         'baseline_end': '2026-05-03', 'actual_start': '2026-05-01',
         'actual_end': '2026-05-08'},
    ]
    errors, warnings = validate_gantt_data(tasks, [])
    assert len(errors) == 0
    assert any('5 天' in w for w in warnings), f'Expected 5d warning: {warnings}'
    print('PASS: delta days warning')


if __name__ == '__main__':
    test_linear_dependency_passes()
    test_cycle_dependency_rejected()
    test_baseline_only_passes()
    test_date_inversion_rejected()
    test_dep_violation_warning()
    test_actual_without_baseline_rejected()
    test_three_node_cycle()
    test_delta_days_warning()
    print('\n=== ALL 8 TESTS PASSED ===')
