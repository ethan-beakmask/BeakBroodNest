"""
資料庫引擎與 Session 管理
框架無關：human_ui (Flask) 與 ai_kb (MCP/CLI) 共用
"""
import configparser
from pathlib import Path
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session


class Base(DeclarativeBase):
    pass


# 模組層級的 engine / SessionLocal，由 init_engine() 初始化
_engine = None
_SessionLocal = None


def init_engine(config_path: str = None, db_url: str = None):
    """
    初始化資料庫引擎。二擇一：
      - config_path: 讀取 config.ini [postgresql] 區段
      - db_url: 直接給 SQLAlchemy URL
    """
    global _engine, _SessionLocal

    if db_url is None:
        if config_path is None:
            config_path = str(Path(__file__).resolve().parent.parent / 'config.ini')
        cfg = configparser.ConfigParser()
        cfg.read(config_path, encoding='utf-8')
        pg = cfg['postgresql']
        db_url = (
            f"postgresql+psycopg2://{pg['username']}:{pg['password']}"
            f"@{pg['host']}:{pg['port']}/{pg['database']}"
        )

    _engine = create_engine(db_url, pool_size=5, max_overflow=10, echo=False)
    _SessionLocal = sessionmaker(bind=_engine)
    return _engine


def get_engine():
    if _engine is None:
        init_engine()
    return _engine


def get_session() -> Session:
    if _SessionLocal is None:
        init_engine()
    return _SessionLocal()


@contextmanager
def session_scope():
    """提供 transaction scope 的 context manager"""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all_tables():
    """建立所有 ORM 定義的表"""
    engine = get_engine()
    Base.metadata.create_all(engine)


def drop_all_tables():
    """刪除所有表（僅限開發用）"""
    engine = get_engine()
    Base.metadata.drop_all(engine)
