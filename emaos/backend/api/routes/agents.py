"""
EMAOS — Agents API Routes
"""
import os
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel

from auth.jwt_handler import TokenData, get_current_user
from memory.episodic_memory import episodic_memory
from memory.semantic_memory import semantic_memory
from memory.procedural_memory import procedural_memory

router = APIRouter(prefix="/agents", tags=["Agents"])

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://emaos:emaos_secret@localhost:5432/emaos")


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


AGENT_REGISTRY = {
    "ceo": {"name": "CEO Agent", "role": "Task decomposition & routing", "capabilities": ["decompose", "route", "plan"]},
    "developer": {"name": "Developer Agent", "role": "Code generation & GitHub automation", "capabilities": ["write_code", "create_pr", "lint"]},
    "tester": {"name": "Tester Agent", "role": "Test generation & execution", "capabilities": ["generate_tests", "execute_code", "analyse_results"]},
    "finance": {"name": "Finance Agent", "role": "Financial analysis & planning", "capabilities": ["budget_analysis", "roi_calc", "financial_forecast"]},
    "marketing": {"name": "Marketing Agent", "role": "SEO, content & campaign strategy", "capabilities": ["seo_analysis", "content_strategy", "competitor_analysis"]},
    "hr": {"name": "HR Agent", "role": "Talent management & HR content", "capabilities": ["job_descriptions", "resume_screening", "interview_questions"]},
    "monitoring": {"name": "Monitoring Agent", "role": "System health & metrics", "capabilities": ["health_check", "alert_config", "metrics_analysis"]},
    "research": {"name": "Research Agent", "role": "Literature review & synthesis", "capabilities": ["web_search", "hypothesis_test", "data_synthesis"]},
}


# ─── Schemas ──────────────────────────────────────────────────────
class AgentInfo(BaseModel):
    name: str
    role: str
    capabilities: List[str]


# ─── Routes ───────────────────────────────────────────────────────
@router.get("/", response_model=Dict[str, AgentInfo])
async def list_agents(current_user: TokenData = Depends(get_current_user)):
    """List all available specialist agents in the EMAOS registry."""
    return AGENT_REGISTRY


@router.get("/{agent_name}/memory/episodic", response_model=List[Dict[str, Any]])
async def get_agent_episodic_memory(
    agent_name: str,
    task_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: TokenData = Depends(get_current_user),
):
    """Retrieve episodic (short-term conversation log) memory for an agent."""
    if agent_name not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    memories = episodic_memory.get_recent(agent_name=agent_name, n=limit, task_id=task_id)
    return memories


@router.get("/{agent_name}/memory/procedural", response_model=List[Dict[str, Any]])
async def get_agent_procedural_memory(
    agent_name: str,
    current_user: TokenData = Depends(get_current_user),
):
    """Retrieve procedural (learned patterns & success rates) memory for an agent."""
    if agent_name not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail="Agent not found")
        
    sql = "SELECT id, task_pattern, tool_sequence, success_rate, invocation_count, avg_duration_ms, last_used FROM procedural_memory WHERE agent_name = %s"
    try:
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (agent_name,))
                return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database query failed: {exc}")


@router.get("/{agent_name}/memory/semantic", response_model=List[Dict[str, Any]])
async def get_agent_semantic_memory(
    agent_name: str,
    query: Optional[str] = Query(None),
    limit: int = Query(5, ge=1, le=50),
    current_user: TokenData = Depends(get_current_user),
):
    """Retrieve semantic (vector store) memory for an agent, optionally searching by query."""
    if agent_name not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail="Agent not found")
        
    if query:
        # Search vector memories using FAISS
        results = semantic_memory.search(query=query, limit=limit)
        # Filter locally for agent_name
        return [r for r in results if r["agent_name"] == agent_name]

    # Return raw database entries if no search query
    sql = "SELECT id, content, metadata, created_at FROM semantic_memory WHERE agent_name = %s ORDER BY created_at DESC LIMIT %s"
    try:
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (agent_name, limit))
                return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database query failed: {exc}")
