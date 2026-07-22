"""
EMAOS — Procedural Memory
Stores learned task→tool patterns, success rates, and agent performance.
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://emaos:emaos_secret@localhost:5432/emaos")


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


class ProceduralMemory:
    """
    Learns which tool sequences work best for each task pattern.
    Tracks: success_rate, invocation_count, avg_duration_ms.
    """

    # ─── Record a pattern ────────────────────────────────────────
    def record_pattern(
        self,
        agent_name: str,
        task_pattern: str,
        tool_sequence: List[str],
        success: bool,
        duration_ms: int = 0,
    ) -> None:
        """Upsert a task-pattern → tool-sequence mapping with updated stats."""
        sql_select = """
            SELECT id, success_rate, invocation_count, avg_duration_ms
            FROM procedural_memory
            WHERE agent_name = %s AND task_pattern = %s
        """
        sql_insert = """
            INSERT INTO procedural_memory
                (agent_name, task_pattern, tool_sequence, success_rate, invocation_count, avg_duration_ms)
            VALUES (%s, %s, %s, %s, 1, %s)
        """
        sql_update = """
            UPDATE procedural_memory
            SET tool_sequence = %s,
                success_rate = %s,
                invocation_count = %s,
                avg_duration_ms = %s,
                last_used = NOW()
            WHERE agent_name = %s AND task_pattern = %s
        """
        
        tool_seq_json = json.dumps(tool_sequence)
        success_val = 1.0 if success else 0.0
        
        try:
            with _get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql_select, (agent_name, task_pattern))
                    row = cur.fetchone()
                    
                    if row:
                        # Calculate updated stats
                        count = row["invocation_count"] + 1
                        old_rate = row["success_rate"]
                        new_rate = ((old_rate * row["invocation_count"]) + success_val) / count
                        
                        old_dur = row["avg_duration_ms"]
                        new_dur = ((old_dur * row["invocation_count"]) + duration_ms) / count
                        
                        cur.execute(
                            sql_update,
                            (tool_seq_json, new_rate, count, new_dur, agent_name, task_pattern)
                        )
                    else:
                        cur.execute(
                            sql_insert,
                            (agent_name, task_pattern, tool_seq_json, success_val, duration_ms)
                        )
                conn.commit()
        except Exception as exc:
            logger.error(f"[PROCEDURAL-MEMORY] Failed to record pattern: {exc}")

    # ─── Get best sequence ────────────────────────────────────────
    def get_best_sequence(
        self,
        agent_name: str,
        task_pattern: str,
        min_success_rate: float = 0.5,
    ) -> Optional[List[str]]:
        """Fetch the tool sequence that has the best success rate for a pattern."""
        sql = """
            SELECT tool_sequence, success_rate
            FROM procedural_memory
            WHERE agent_name = %s AND task_pattern = %s AND success_rate >= %s
            ORDER BY success_rate DESC, invocation_count DESC
            LIMIT 1
        """
        try:
            with _get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql, (agent_name, task_pattern, min_success_rate))
                    row = cur.fetchone()
                    if row and row["tool_sequence"]:
                        if isinstance(row["tool_sequence"], str):
                            return json.loads(row["tool_sequence"])
                        return row["tool_sequence"]
            return None
        except Exception as exc:
            logger.error(f"[PROCEDURAL-MEMORY] Failed to fetch best sequence: {exc}")
            return None


procedural_memory = ProceduralMemory()
