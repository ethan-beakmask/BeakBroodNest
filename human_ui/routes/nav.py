# -*- coding: utf-8 -*-
"""導覽選單 API"""

from flask import Blueprint, jsonify, request
from core.db import session_scope
from core.models import NavMenu

bp = Blueprint('nav', __name__)


@bp.route('/api/nav-menu')
def list_nav_menu():
    """取得啟用中的選單項目"""
    with session_scope() as s:
        items = (
            s.query(NavMenu)
            .filter(NavMenu.is_active == True)
            .order_by(NavMenu.sort_order)
            .all()
        )
        return jsonify([i.to_dict() for i in items])
