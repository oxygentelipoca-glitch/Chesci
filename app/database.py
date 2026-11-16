"""数据库连接管理：双数据库架构。

架构
----
* **主数据库 (database.db)**：SQLite，存储通用业务数据（User、Conversation、Message、File）。
* **化学数据库 (reactions.db)**：SQLite，存储 SciFinder 提取的反应数据（schemes、reactions、reaction_conditions、literature、extraction_log）。
  reactions.db 由外部 SciFinder PDF 提取程序生成和维护，本模块仅进行只读映射。

环境变量
--------
``DATABASE_URL``
    主数据库连接串。默认 ``sqlite:///database.db``。

``CHEMISTRY_DB_URL``
    化学数据库连接串。默认 ``sqlite:///reactions.db``。

``NEO4J_URI`` / ``NEO4J_USER`` / ``NEO4J_PASSWORD``
    Neo4j 凭据。未配置时图谱功能降级。
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401 — User/Conversation/Message/File

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# 主数据库（通用业务表）
# ═══════════════════════════════════════════════════════════════════════════

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///database.db")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)


def create_db_and_tables(max_retries: int = 10, retry_delay: int = 2) -> None:
    """创建主数据库表（User/Conversation/Message/File），幂等。

    注意：化学表（schemes/reactions/reaction_conditions/literature/extraction_log）
    由 reactions.db 维护，不在此建表；历史遗留的旧化学表会被清理。
    """
    # 仅创建主数据库模型对应的表（排除化学模型）
    main_tables = [models.User, models.Conversation, models.Message, models.File, models.SearchHistory]

    # 历史遗留的旧化学表（化学数据已统一由 reactions.db 管理）
    legacy_chemistry_tables = [
        "scheme",
        "compound",
        "literature",
        "reaction_record",
        "chemistry_query",
        "reaction",
    ]

    last_error: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            SQLModel.metadata.create_all(engine, tables=[t.__table__ for t in main_tables])

            # ---- 历史迁移：补充 user_id 列（兼容旧库） ----
            inspector = inspect(engine)
            existing_columns = {
                table_name: {column["name"] for column in inspector.get_columns(table_name)}
                for table_name in inspector.get_table_names()
            }

            migrations = [
                ("conversation", "user_id", "ALTER TABLE conversation ADD COLUMN user_id INTEGER"),
                ("file", "user_id", "ALTER TABLE file ADD COLUMN user_id INTEGER"),
                ("message", "user_id", "ALTER TABLE message ADD COLUMN user_id INTEGER"),
            ]

            with engine.begin() as connection:
                for table_name, column_name, ddl in migrations:
                    if table_name in existing_columns and column_name not in existing_columns[table_name]:
                        connection.execute(text(ddl))

            # ---- 清理旧化学表（database.db 只保留用户信息等通用表） ----
            existing_tables = set(inspector.get_table_names())
            with engine.begin() as connection:
                for table_name in legacy_chemistry_tables:
                    if table_name in existing_tables:
                        connection.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
                        logger.info("已删除旧化学表: %s（化学数据由 reactions.db 管理）", table_name)

            logger.info("主数据库表创建/迁移完成。")
            return
        except OperationalError as exc:
            last_error = exc
            if attempt == max_retries - 1:
                raise
            time.sleep(retry_delay)

    if last_error is not None:
        raise last_error


# 模块加载时自动建表（仅主数据库）
create_db_and_tables()


def get_session():
    """FastAPI 依赖注入：获取主数据库会话。"""
    with Session(engine) as session:
        yield session


# ═══════════════════════════════════════════════════════════════════════════
# 化学数据库（reactions.db — 外部维护，只读映射）
# ═══════════════════════════════════════════════════════════════════════════

CHEMISTRY_DB_URL = os.getenv("CHEMISTRY_DB_URL", "sqlite:///reactions.db")

chemistry_engine = create_engine(
    CHEMISTRY_DB_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in CHEMISTRY_DB_URL else {},
)


def get_chemistry_session():
    """FastAPI 依赖注入：获取化学数据库会话（reactions.db）。"""
    with Session(chemistry_engine) as session:
        yield session


def chemistry_db_available() -> bool:
    """检查化学数据库是否可用（文件存在且有核心表）。"""
    try:
        db_path = CHEMISTRY_DB_URL.replace("sqlite:///", "")
        if not os.path.exists(db_path):
            return False
        inspector = inspect(chemistry_engine)
        required = {"schemes", "reactions"}
        existing = set(inspector.get_table_names())
        return required.issubset(existing)
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Neo4j 知识图谱
# ═══════════════════════════════════════════════════════════════════════════

_NEO4J_DRIVER = None
_NEO4J_AVAILABLE = None  # None = 未探测, True/False = 已探测


def _init_neo4j():
    """惰性初始化 Neo4j 驱动（首次调用时探测）。"""
    global _NEO4J_DRIVER, _NEO4J_AVAILABLE

    if _NEO4J_AVAILABLE is not None:
        return

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "neo4j")

    try:
        from neo4j import GraphDatabase
        _NEO4J_DRIVER = GraphDatabase.driver(uri, auth=(user, password))
        _NEO4J_DRIVER.verify_connectivity()
        _NEO4J_AVAILABLE = True
        logger.info("Neo4j 连接成功: %s", uri)
    except Exception as exc:
        _NEO4J_DRIVER = None
        _NEO4J_AVAILABLE = False
        logger.warning("Neo4j 不可用 (%s)，图谱功能将降级。", exc)


def get_neo4j_driver():
    """获取 Neo4j 驱动实例（惰性初始化）。"""
    _init_neo4j()
    return _NEO4J_DRIVER


def neo4j_available() -> bool:
    """检查 Neo4j 是否已成功连接。"""
    _init_neo4j()
    return _NEO4J_AVAILABLE is True


@contextmanager
def neo4j_session():
    """Neo4j 会话上下文管理器。"""
    _init_neo4j()
    if not _NEO4J_DRIVER:
        raise RuntimeError("Neo4j 不可用，请检查 NEO4J_URI 环境变量。")
    session = _NEO4J_DRIVER.session()
    try:
        yield session
    finally:
        session.close()
