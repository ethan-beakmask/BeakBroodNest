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
]
