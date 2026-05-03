#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gantt API 整合測試

測���對象：dev server http://127.0.0.1:5172
前提：dev server 已啟動且 beak_broodnest_dev DB 有 BeakBroodNest 專案資料
"""

import json
import sys
import urllib.request

BASE = 'http://127.0.0.1:5172/beakbroodnest'
SLUG = 'vRhORoxV'


def _get(path):
    url = f'{BASE}{path}'
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _patch(path, body, query=''):
    url = f'{BASE}{path}'
    if query:
        url += '?' + query
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method='PATCH')
    req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def test_get_gantt():
    """GET /gantt-mvp/api/gantt/<slug> 回傳正確結構。"""
    data = _get(f'/gantt-mvp/api/gantt/{SLUG}')

    assert 'tasks' in data, 'Missing tasks key'
    assert 'warnings' in data, 'Missing warnings key'
    assert 'errors' in data, 'Missing errors key'
    assert 'canvas_name' in data, 'Missing canvas_name'
    assert len(data['tasks']) > 0, 'Expected at least 1 task'

    task = data['tasks'][0]
    required_keys = {'id', 'name', 'start', 'end', 'progress',
                     'dependencies', '_baseline', '_delta_days',
                     '_status', '_urgency', '_category', '_entry_id'}
    missing = required_keys - set(task.keys())
    assert not missing, f'Task missing keys: {missing}'
    print(f'PASS: GET gantt ({len(data["tasks"])} tasks)')


def test_get_gantt_has_dependencies():
    """依賴資料有正確轉成逗號分隔字串。"""
    data = _get(f'/gantt-mvp/api/gantt/{SLUG}')
    has_dep = [t for t in data['tasks'] if t['dependencies']]
    assert len(has_dep) > 0, 'Expected some tasks with dependencies'
    for t in has_dep:
        for dep_id in t['dependencies'].split(', '):
            assert dep_id.strip().isdigit(), f'Bad dep ID: {dep_id}'
    print(f'PASS: dependencies format ({len(has_dep)} tasks with deps)')


def test_patch_normal_field():
    """PATCH 更新���凍結欄位。"""
    result = _patch(f'/gantt-mvp/api/gantt/{SLUG}/70', {
        'actual_end': '2026-04-29',
    })
    assert result['ok'], f'PATCH failed: {result}'
    assert 'actual_end' in result['updated'], f'actual_end not updated: {result}'
    print('PASS: PATCH normal field')


def test_patch_frozen_rejected():
    """PATCH 凍結欄位被拒絕。"""
    result = _patch(f'/gantt-mvp/api/gantt/{SLUG}/70', {
        'baseline_end': '2026-06-01',
    })
    assert result['ok'], f'PATCH should still return ok: {result}'
    assert 'baseline_end' in result.get('frozen_rejected', []), \
        f'Expected frozen_rejected: {result}'
    assert 'baseline_end' not in result.get('updated', {}), \
        f'Frozen field should not be updated: {result}'
    print('PASS: PATCH frozen field rejected')


def test_patch_reset_baseline():
    """PATCH ?reset_baseline=true 允許修改凍結欄位。"""
    result = _patch(f'/gantt-mvp/api/gantt/{SLUG}/70', {
        'baseline_end': '2026-04-26',
    }, query='reset_baseline=true')
    assert result['ok']
    assert 'baseline_end' in result['updated']
    print('PASS: PATCH reset_baseline')


def test_get_reflects_patch():
    """PATCH 後 GET 能看到更新的資料。"""
    _patch(f'/gantt-mvp/api/gantt/{SLUG}/70', {
        'progress': '80',
    })
    data = _get(f'/gantt-mvp/api/gantt/{SLUG}')
    task70 = next((t for t in data['tasks'] if t['id'] == '70'), None)
    assert task70 is not None, 'Task 70 not found'
    assert task70['progress'] == 80, f'Expected 80, got {task70["progress"]}'
    print('PASS: GET reflects PATCH')


def test_get_nonexistent_slug():
    """GET 不存在的 slug 回 404。"""
    try:
        _get('/gantt-mvp/api/gantt/NONEXISTENT')
        assert False, 'Expected 404'
    except urllib.error.HTTPError as e:
        assert e.code == 404, f'Expected 404, got {e.code}'
    print('PASS: nonexistent slug 404')


def test_status_field():
    """_status 欄位正確判斷 not_started / in_progress / completed。"""
    data = _get(f'/gantt-mvp/api/gantt/{SLUG}')
    valid = {'not_started', 'in_progress', 'completed'}
    for t in data['tasks']:
        assert t['_status'] in valid, f'Bad _status: {t["_status"]} for {t["name"]}'
    print('PASS: _status field')


def test_null_start_for_not_started():
    """not_started 任務的 start (actual_start) 應為 null。"""
    data = _get(f'/gantt-mvp/api/gantt/{SLUG}')
    ns = [t for t in data['tasks'] if t['_status'] == 'not_started']
    for t in ns:
        assert t['start'] is None, \
            f'{t["name"]}: start should be null, got {t["start"]}'
    if ns:
        print(f'PASS: null start for not_started ({len(ns)} tasks)')
    else:
        print('PASS: null start for not_started (no not_started tasks)')


if __name__ == '__main__':
    test_get_gantt()
    test_get_gantt_has_dependencies()
    test_patch_normal_field()
    test_patch_frozen_rejected()
    test_patch_reset_baseline()
    test_get_reflects_patch()
    test_get_nonexistent_slug()
    test_status_field()
    test_null_start_for_not_started()
    print('\n=== ALL 9 API TESTS PASSED ===')
