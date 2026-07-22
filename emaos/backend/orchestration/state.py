"""
EMAOS — Orchestration State
Shared TypedDict used by every node in the LangGraph state machine.
"""
import uuid
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


class AgentOutput(TypedDict):
    agent_name: str
    output_type: str          # 'code' | 'report' | 'analysis' | 'plan' | 'test_result'
    content: str
    success: bool
    tokens_used: int
    duration_ms: int
    metadata: Dict[str, Any]


class TaskItem(TypedDict):
    task_id: str
    title: str
    description: str
    assigned_agent: str
    priority: int             # 1 (highest) → 10 (lowest)
    dependencies: List[str]   # list of task_ids this depends on
    status: str               # 'pending' | 'in_progress' | 'done' | 'failed'


class GraphState(TypedDict):
    # ─── Identity ─────────────────────────────────────────────────
    project_id: str
    task_id: str
    run_id: str               # unique run identifier for evaluation

    # ─── Input ────────────────────────────────────────────────────
    user_request: str         # original user task description
    context: Dict[str, Any]   # extra context (user, project metadata)

    # ─── CEO routing ──────────────────────────────────────────────
    decomposed_tasks: List[TaskItem]
    current_task: Optional[TaskItem]
    current_agent: str        # which agent node is currently active

    # ─── Agent outputs ────────────────────────────────────────────
    agent_outputs: List[AgentOutput]
    final_reports: List[Dict[str, Any]]

    # ─── Control Flow ─────────────────────────────────────────────
    iteration_count: int
    max_iterations: int
    needs_human: bool
    error: Optional[str]


def initial_state(
    user_request: str,
    project_id: str = "default",
    context: Optional[Dict[str, Any]] = None
) -> GraphState:
    """Helper to initialize a clean GraphState."""
    return {
        "project_id": project_id,
        "task_id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "user_request": user_request,
        "context": context or {},
        "decomposed_tasks": [],
        "current_task": None,
        "current_agent": "ceo",
        "agent_outputs": [],
        "final_reports": [],
        "iteration_count": 0,
        "max_iterations": 10,
        "needs_human": False,
        "error": None,
    }
