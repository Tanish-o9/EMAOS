"""
EMAOS — Database Connection Manager
Establishes SQLAlchemy connection pools, models, and hooks.
"""
import logging
import os
import time
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://emaos:emaos_secret@localhost:5432/emaos")

engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def init_database() -> None:
    """Initialize database schemas, tables, and trigger scripts."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if not os.path.exists(schema_path):
        logger.warning(f"[DB] Schema file schema.sql not found at {schema_path}")
        return

    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    # Split script into statements
    statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]

    # Connect and execute schema statements
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        
        # 1. First enable uuid extension
        try:
            cursor.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
            connection.commit()
            logger.info("[DB] Extension uuid-ossp enabled.")
        except Exception as exc:
            connection.rollback()
            logger.warning(f"[DB] Failed to enable uuid-ossp extension, attempting to proceed: {exc}")

        # 2. Run the rest of statements
        for stmt in statements:
            if "uuid-ossp" in stmt:
                continue # already run
            try:
                cursor.execute(stmt)
                connection.commit()
            except Exception as e:
                connection.rollback()
                logger.error(f"[DB] Failed statement execution: {stmt[:60]}... | Error: {e}")
                raise e
        logger.info("[DB] Schema migrations applied successfully.")
    finally:
        connection.close()


def close_database() -> None:
    engine.dispose()
    logger.info("[DB] Engine pool disposed.")


async def check_database_health() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error(f"[DB] Connection healthcheck failed: {exc}")
        return False
