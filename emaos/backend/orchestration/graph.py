"""
EMAOS — LangGraph Orchestration Graph
Full StateGraph with CEO + all specialist agent nodes.
"""
import logging
import os
from typing import Literal

from langgraph.graph import StateGraph, END

from orchestration.state import GraphState
from agents.ceo_agent import CEOAgent
from agents.developer_agent import DeveloperAgent
from agents.tester_agent import TesterAgent
from agents.finance_agent import FinanceAgent
from agents.marketing_agent import MarketingAgent
from agents.hr_agent import HRAgent
from agents.monitoring_agent import MonitoringAgent
from agents.research_agent import ResearchAgent

logger = logging.getLogger(__name__)


# ─── Specialist Node Wrapper Functions ────────────────────────────
def ceo_node(state: GraphState) -> GraphState:
    logger.info("[NODE] Entering CEO Node")
    agent = CEOAgent()
    return agent.run(state)


def developer_node(state: GraphState) -> GraphState:
    logger.info("[NODE] Entering Developer Node")
    agent = DeveloperAgent()
    return agent.run(state)


def tester_node(state: GraphState) -> GraphState:
    logger.info("[NODE] Entering Tester Node")
    agent = TesterAgent()
    return agent.run(state)


def finance_node(state: GraphState) -> GraphState:
    logger.info("[NODE] Entering Finance Node")
    agent = FinanceAgent()
    return agent.run(state)


def marketing_node(state: GraphState) -> GraphState:
    logger.info("[NODE] Entering Marketing Node")
    agent = MarketingAgent()
    return agent.run(state)


def hr_node(state: GraphState) -> GraphState:
    logger.info("[NODE] Entering HR Node")
    agent = HRAgent()
    return agent.run(state)


def monitoring_node(state: GraphState) -> GraphState:
    logger.info("[NODE] Entering Monitoring Node")
    agent = MonitoringAgent()
    return agent.run(state)


def research_node(state: GraphState) -> GraphState:
    logger.info("[NODE] Entering Research Node")
    agent = ResearchAgent()
    return agent.run(state)


# ─── Reporter node ────────────────────────────────────────────────
def reporter_node(state: GraphState) -> GraphState:
    """Collects all agent outputs and builds the final report."""
    import json
    from datetime import datetime, timezone

    outputs = state.get("agent_outputs", [])
    
    # Save report to DB if possible
    title = f"EMAOS Execution Report - Task {state['task_id'][:8]}"
    summary = _build_summary(outputs)
    
    final_report = {
        "task_id": state["task_id"],
        "project_id": state["project_id"],
        "title": title,
        "user_request": state["user_request"],
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "total_iterations": state.get("iteration_count", 0),
        "agents_used": list({o["agent_name"] for o in outputs}),
        "needs_human": state.get("needs_human", False),
        "error": state.get("error"),
        "summary": summary,
        "agent_outputs": outputs,
    }

    state["final_reports"] = [final_report]
    
    # Save report to reports database table
    try:
        import psycopg2
        DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://emaos:emaos_secret@localhost:5432/emaos")
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO reports (task_id, project_id, title, content, format)
                    VALUES (%s, %s, %s, %s, 'markdown')
                    ON CONFLICT (task_id) DO UPDATE SET content = EXCLUDED.content
                    """,
                    (state["task_id"], state["project_id"], title, summary)
                )
            conn.commit()
    except Exception as exc:
        logger.warning(f"[REPORTER] Failed to save report to database: {exc}")

    logger.info(
        f"[REPORTER] Final report ready. Agents: {final_report['agents_used']} | "
        f"Needs human: {final_report['needs_human']}"
    )
    return state


def _build_summary(outputs: list) -> str:
    if not outputs:
        return "No agent outputs recorded."
    parts = []
    for out in outputs:
        parts.append(f"### 🤖 {out['agent_name'].upper()} OUTPUT")
        parts.append(out['content'])
        parts.append("\n" + "═" * 40 + "\n")
    return "\n\n".join(parts)


# ─── Conditional Edge Routing Logic ──────────────────────────────
def route_next(state: GraphState) -> str:
    if state.get("error"):
        logger.warning(f"[ROUTER] Error state detected: {state.get('error')}. Routing to reporter.")
        return "reporter"
    if state.get("iteration_count", 0) >= state.get("max_iterations", 10):
        logger.warning("[ROUTER] Max iterations reached. Routing to reporter.")
        state["needs_human"] = True
        return "reporter"

    # If CEO has not run yet to decompose tasks, we must run the CEO
    if not state.get("decomposed_tasks"):
        logger.info("[ROUTER] No decomposed tasks found. Routing to ceo.")
        return "ceo"

    # Check if there is a current task that just finished
    current_task = state.get("current_task")
    if current_task:
        outputs = state.get("agent_outputs", [])
        last_output = next((o for o in reversed(outputs) if o["agent_name"] == current_task["assigned_agent"]), None)
        
        # Update the task status in the state
        for task in state["decomposed_tasks"]:
            if task["task_id"] == current_task["task_id"]:
                if last_output:
                    if last_output["success"]:
                        task["status"] = "done"
                        logger.info(f"[ROUTER] Sub-task {task['title']} completed successfully.")
                    else:
                        task["status"] = "failed"
                        state["error"] = f"Task '{task['title']}' failed: {last_output['content']}"
                        logger.error(f"[ROUTER] Sub-task {task['title']} failed.")
                        return "reporter"
                break
        state["current_task"] = None

    # Get set of completed task IDs
    done_ids = {t["task_id"] for t in state["decomposed_tasks"] if t["status"] == "done"}
    
    # Find next pending task that has all dependencies met
    next_task = None
    for task in state["decomposed_tasks"]:
        if task["status"] == "pending":
            deps_met = all(dep_id in done_ids for dep_id in task["dependencies"])
            if deps_met:
                next_task = task
                break
                
    if next_task:
        state["current_task"] = next_task
        # Update status in list to in_progress
        for t in state["decomposed_tasks"]:
            if t["task_id"] == next_task["task_id"]:
                t["status"] = "in_progress"
                break
        state["iteration_count"] = state.get("iteration_count", 0) + 1
        agent = next_task["assigned_agent"]
        logger.info(f"[ROUTER] Next task: '{next_task['title']}' routed to '{agent}' agent (Iteration {state['iteration_count']})")
        return agent

    # No pending tasks. Check if all completed successfully
    all_done = all(t["status"] == "done" for t in state["decomposed_tasks"])
    if all_done:
        logger.info("[ROUTER] All sub-tasks completed successfully. Routing to reporter.")
        return "reporter"
        
    # Blocked or failed tasks fallback
    logger.warning("[ROUTER] No runnable tasks found, but not all tasks are done. Routing to reporter.")
    return "reporter"


# ─── Compile LangGraph StateGraph ─────────────────────────────────
_workflow = None

def get_graph():
    global _workflow
    if _workflow is None:
        workflow = StateGraph(GraphState)
        
        # Add Nodes
        workflow.add_node("ceo", ceo_node)
        workflow.add_node("developer", developer_node)
        workflow.add_node("tester", tester_node)
        workflow.add_node("finance", finance_node)
        workflow.add_node("marketing", marketing_node)
        workflow.add_node("hr", hr_node)
        workflow.add_node("monitoring", monitoring_node)
        workflow.add_node("research", research_node)
        workflow.add_node("reporter", reporter_node)
        
        # Set Entrypoint
        workflow.set_entry_point("ceo")
        
        # Add Specialist transitions back to CEO for scheduling
        for agent in ["developer", "tester", "finance", "marketing", "hr", "monitoring", "research"]:
            workflow.add_edge(agent, "ceo")
            
        # Add Conditional routing from CEO
        workflow.add_conditional_edges(
            "ceo",
            route_next,
            {
                "ceo": "ceo",
                "developer": "developer",
                "tester": "tester",
                "finance": "finance",
                "marketing": "marketing",
                "hr": "hr",
                "monitoring": "monitoring",
                "research": "research",
                "reporter": "reporter"
            }
        )
        
        # End workflow at reporter
        workflow.add_edge("reporter", END)
        
        _workflow = workflow.compile()
    return _workflow


def run_graph(state: GraphState) -> GraphState:
    graph = get_graph()
    return graph.invoke(state)
