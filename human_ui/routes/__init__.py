# -*- coding: utf-8 -*-
"""Blueprint 註冊入口"""

from .atoms import bp as atoms_bp
from .relations import bp as relations_bp
from .canvases import bp as canvases_bp
from .orchestrator import bp as orchestrator_bp
from .worker import bp as worker_bp
from .schemas import bp as schemas_bp
from .tags import bp as tags_bp
from .observe import bp as observe_bp
from .nav import bp as nav_bp
from .entry_schemas import bp as entry_schemas_bp
from .entries import bp as entries_bp
from .unified_relations import bp as unified_relations_bp
from .project import bp as project_bp
from .gantt_mvp import bp as gantt_mvp_bp
from .gantt_routes import bp as gantt_routes_bp
from .beak_gantt import bp as beak_gantt_bp
from .files import bp as files_bp
from .exchange import bp as exchange_bp
from .admin import bp as admin_bp
from .preferences import bp as preferences_bp
from .conversation_map import bp as conversation_map_bp
from .calendar import bp as calendar_bp
from .tiptap_node import bp as tiptap_node_bp
from .standalone_entries import bp as standalone_entries_bp
from .todos import bp as todos_bp
from .reader import bp as reader_bp

ALL_BLUEPRINTS = [
    atoms_bp,
    relations_bp,
    canvases_bp,
    orchestrator_bp,
    worker_bp,
    schemas_bp,
    tags_bp,
    observe_bp,
    nav_bp,
    entry_schemas_bp,
    entries_bp,
    unified_relations_bp,
    project_bp,
    gantt_mvp_bp,
    gantt_routes_bp,
    beak_gantt_bp,
    files_bp,
    exchange_bp,
    admin_bp,
    preferences_bp,
    conversation_map_bp,
    calendar_bp,
    tiptap_node_bp,
    standalone_entries_bp,
    todos_bp,
    reader_bp,
]
