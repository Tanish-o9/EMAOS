"""
EMAOS — Episodic Memory
Sliding-window conversation history per agent, stored in PostgreSQL.
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://emaos:emaos_secret@localhost:5432/emaos")


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


class EpisodicMemory:
    """
    Stores and retrieves a sliding window of recent events for each agent.
    Uses PostgreSQL as the backing store for persistence across restarts.
    """

    def __init__(self, window_size: int = 50):
        self.window_size = window_size

    # ─── Write ────────────────────────────────────────────────────
    def record(
        self,
        agent_name: str,
        content: str,
        event_type: str = "message",
        task_id: Optional[str] = None,
        importance: float = 0.5,
    ) -> None:
        sql = """
            INSERT INTO episodic_memory (agent_name, task_id, event_type, content, importance)
            VALUES (%s, %s, %s, %s, %s)
        """
        try:
            with _get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (agent_name, task_id, event_type, content, importance))
                conn.commit()
        except Exception as exc:
            logger.error(f"[EPISODIC-MEMORY] Failed to record: {exc}")

    # ─── Read ─────────────────────────────────────────────────────
    def get_recent(
        self,
        agent_name: str,
        n: Optional[int] = None,
        task_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        limit = n or self.window_size
        try:
            if task_id:
                sql = """
                    SELECT id, agent_name, task_id, event_type, content, importance, created_at
                    FROM episodic_memory
                    WHERE agent_name = %s AND task_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """
                params = (agent_name, task_id, limit)
            else:
                sql = """
                    SELECT id, agent_name, task_id, event_type, content, importance, created_at
                    FROM episodic_memory
                    WHERE agent_name = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """
                params = (agent_name, limit)

            with _get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
                    # Reverse to make them chronological
                    return list(reversed([dict(r) for r in rows]))
        except Exception as exc:
            logger.error(f"[EPISODIC-MEMORY] Failed to fetch: {exc}")
            return []

    # ─── Clear ────────────────────────────────────────────────────
    def clear(self) -> None:
        sql = "DELETE FROM episodic_memory"
        try:
            with _get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
                conn.commit()
        except Exception as exc:
            logger.error(f"[EPISODIC-MEMORY] Failed to clear: {exc}")


episodic_memory = EpisodicMemory()
