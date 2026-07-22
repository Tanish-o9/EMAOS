"""
EMAOS — Tasks API Routes
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth.jwt_handler import TokenData, get_current_user
from orchestration.state import GraphState, initial_state
from orchestration.graph import run_graph

import psycopg2
import psycopg2.extras
import os
import json

router = APIRouter(prefix="/tasks", tags=["Tasks"])

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://emaos:emaos_secret@localhost:5432/emaos")


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


# ─── Request/Response Models ──────────────────────────────────────
class TaskSubmitRequest(BaseModel):
    user_request: str = Field(..., min_length=10, max_length=5000)
    project_id: Optional[str] = Field(default="default")
    eval_mode: bool = Field(default=False)
    context: Optional[Dict[str, Any]] = Field(default={})


class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str
    project_id: str


class TaskDetailResponse(BaseModel):
    task_id: str
    project_id: str
    user_request: str
    status: str
    agent_outputs: List[Dict[str, Any]]
    final_reports: List[Dict[str, Any]]
    iteration_count: int
    created_at: Optional[str]
    completed_at: Optional[str]


# ─── In-memory task store (use Redis/DB in production) ────────────
_task_store: Dict[str, GraphState] = {}
_task_status: Dict[str, str] = {}


# ─── Background Orchestration Loop ────────────────────────────────
def run_task_in_background(task_id: str, req: TaskSubmitRequest):
    state = initial_state(req.user_request, req.project_id, req.context)
    state["task_id"] = task_id
    _task_store[task_id] = state
    _task_status[task_id] = "running"
    
    # Save running task to Postgres
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tasks (id, project_id, title, status)
                    VALUES (%s, %s, %s, 'running')
                    """,
                    (task_id, req.project_id, req.user_request[:100])
                )
            conn.commit()
    except Exception:
        pass

    try:
        final_state = run_graph(state)
        _task_store[task_id] = final_state
        
        status_val = "failed" if final_state.get("error") else "completed"
        _task_status[task_id] = status_val
        
        result_json = json.dumps(final_state.get("final_reports", []))
        error_log = final_state.get("error")
        
        # Update Postgres status
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE tasks
                    SET status = %s, result = %s, error_log = %s, completed_at = NOW()
                    WHERE id = %s
                    """,
                    (status_val, result_json, error_log, task_id)
                )
            conn.commit()
    except Exception as exc:
        _task_status[task_id] = "failed"
        try:
            with _get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE tasks
                        SET status = 'failed', error_log = %s, completed_at = NOW()
                        WHERE id = %s
                        """,
                        (str(exc), task_id)
                    )
                conn.commit()
        except Exception:
            pass


# ─── Routes ───────────────────────────────────────────────────────
@router.post("/submit", response_model=TaskResponse)
async def submit_task(
    request: TaskSubmitRequest,
    background_tasks: BackgroundTasks,
    current_user: TokenData = Depends(get_current_user),
):
    """Submit a task to the AI CEO orchestrator."""
    task_id = str(uuid.uuid4())
    _task_status[task_id] = "pending"
    
    background_tasks.add_task(run_task_in_background, task_id, request)
    
    return TaskResponse(
        task_id=task_id,
        status="pending",
        message="Task submitted successfully to the CEO Agent.",
        project_id=request.project_id
    )


@router.get("/", response_model=List[Dict[str, Any]])
async def list_tasks(
    project_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    current_user: TokenData = Depends(get_current_user),
):
    """List historical tasks submitted to the system."""
    try:
        if project_id:
            sql = "SELECT id, project_id, title, status, created_at FROM tasks WHERE project_id = %s ORDER BY created_at DESC LIMIT %s"
            params = (project_id, limit)
        else:
            sql = "SELECT id, project_id, title, status, created_at FROM tasks ORDER BY created_at DESC LIMIT %s"
            params = (limit,)
            
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{task_id}", response_model=TaskDetailResponse)
async def get_task_details(
    task_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    """Retrieve full execution state details for a task."""
    # Try reading from in-memory cache first (latest live state)
    state = _task_store.get(task_id)
    if state:
        return TaskDetailResponse(
            task_id=task_id,
            project_id=state.get("project_id", "default"),
            user_request=state.get("user_request", ""),
            status=_task_status.get(task_id, "unknown"),
            agent_outputs=state.get("agent_outputs", []),
            final_reports=state.get("final_reports", []),
            iteration_count=state.get("iteration_count", 0),
            created_at=None,
            completed_at=None
        )

    # Fallback to Database logs
    try:
        sql = "SELECT * FROM tasks WHERE id = %s"
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (task_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Task not found")
                
                final_reports = row["result"] if row["result"] else []
                if isinstance(final_reports, str):
                    final_reports = json.loads(final_reports)
                    
                return TaskDetailResponse(
                    task_id=task_id,
                    project_id=row["project_id"],
                    user_request=row["title"],
                    status=row["status"],
                    agent_outputs=[],  # Database contains compressed logs, outputs in final_reports
                    final_reports=final_reports,
                    iteration_count=0,
                    created_at=row["created_at"].isoformat() if row["created_at"] else None,
                    completed_at=row["completed_at"].isoformat() if row["completed_at"] else None
                )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database query failed: {exc}")
