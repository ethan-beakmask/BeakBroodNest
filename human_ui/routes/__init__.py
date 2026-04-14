# -*- coding: utf-8 -*-
"""Blueprint 註冊入口"""

from .atoms import bp as atoms_bp
from .relations import bp as relations_bp
from .canvases import bp as canvases_bp
from .orchestrator import bp as orchestrator_bp
from .worker import bp as worker_bp
from .schemas import bp as schemas_bp
from .tags import bp as tags_bp

ALL_BLUEPRINTS = [
    atoms_bp,
    relations_bp,
    canvases_bp,
    orchestrator_bp,
    worker_bp,
    schemas_bp,
    tags_bp,
]
