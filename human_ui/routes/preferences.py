# -*- coding: utf-8 -*-
"""User Preferences API: 跨頁面保存使用者偏好(KV 結構)。

身份一律從 session.username 取,不接受 query/body 覆寫。
"""
from flask import Blueprint, request, jsonify, session

from core.db import session_scope
from core.models import UserPreference

bp = Blueprint('preferences', __name__)


def _current_user():
    return session.get('username') or 'default'


@bp.route('/api/preferences/<key>', methods=['GET'])
def get_preference(key):
    user = _current_user()
    with session_scope() as s:
        pref = s.get(UserPreference, (user, key))
        if not pref:
            return jsonify({'key': key, 'value': None})
        return jsonify(pref.to_dict())


@bp.route('/api/preferences/<key>', methods=['PUT'])
def set_preference(key):
    data = request.get_json() or {}
    if 'value' not in data:
        return jsonify({'error': '需要 value 欄位'}), 400
    value = data['value']
    if value is None:
        value = ''
    if not isinstance(value, str):
        value = str(value)
    user = _current_user()
    with session_scope() as s:
        pref = s.get(UserPreference, (user, key))
        if pref:
            pref.value = value
        else:
            pref = UserPreference(username=user, key=key, value=value)
            s.add(pref)
        s.flush()
        return jsonify(pref.to_dict())


@bp.route('/api/preferences/<key>', methods=['DELETE'])
def delete_preference(key):
    user = _current_user()
    with session_scope() as s:
        pref = s.get(UserPreference, (user, key))
        if pref:
            s.delete(pref)
        return jsonify({'ok': True})
