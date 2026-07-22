"""
EMAOS — CEO Agent
Task decomposition and routing to specialist agents via structured JSON.
Primary LLM: Groq (llama-3.3-70b-versatile)
"""
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from orchestration.state import GraphState, TaskItem
from memory.episodic_memory import episodic_memory
from memory.semantic_memory import semantic_memory
from memory.procedural_memory import procedural_memory

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

AVAILABLE_AGENTS = [
    "developer",
    "tester",
    "finance",
    "marketing",
    "hr",
    "monitoring",
    "research",
]

CEO_SYSTEM_PROMPT = """You are the CEO Agent of EMAOS — an Enterprise Multi-Agent AI Operating System.

Your role is TASK DECOMPOSITION and AGENT ROUTING. You receive a high-level task from a user and you:
1. Break it into concrete sub-tasks
2. Assign each sub-task to the most appropriate specialist agent
3. Set priority (1=highest, 10=lowest) and dependencies between tasks
4. Return a structured JSON plan

Available specialist agents:
- developer: writes, refactors, and pushes code to GitHub
- tester: writes and runs tests, validates developer output
- finance: budget analysis, financial planning, expense categorization
- marketing: SEO, content strategy, campaign planning, market research
- hr: job descriptions, resume screening, interview questions
- monitoring: system health, metrics analysis, alerting
- research: literature review, data synthesis, hypothesis testing

RULES:
- Always return ONLY valid JSON. No markdown fences, no prose outside the JSON.
- Never assign to yourself (ceo). Route everything to specialist agents.
- "dependencies" is a list of task_ids that must complete BEFORE this task.
- If unsure which agent to use, default to "research".

JSON Schema format to return:
{
  "decomposed_tasks": [
    {
      "task_id": "string-uuid-or-id",
      "title": "Short title of sub-task",
      "description": "Detailed description of what the agent needs to do",
      "assigned_agent": "developer|tester|finance|marketing|hr|monitoring|research",
      "priority": 1,
      "dependencies": []
    }
  ]
}
"""


class CEOAgent:
    def __init__(self):
        self.llm = ChatGroq(
            groq_api_key=GROQ_API_KEY,
            model_name=GROQ_MODEL,
            temperature=0.2,
            max_tokens=4096,
        )
        self.agent_name = "ceo"

    def run(self, state: GraphState) -> GraphState:
        # If tasks are already decomposed, we don't need to decompose them again
        if state.get("decomposed_tasks"):
            return state

        start_ms = int(time.time() * 1000)
        logger.info(f"[CEO] Starting task decomposition for request: '{state['user_request'][:60]}...'")

        # Query semantic memory for relevant context
        memories = semantic_memory.search(state["user_request"], limit=3)
        memory_str = "\n".join([f"- Memory: {m['content']}" for m in memories]) if memories else "None"

        prompt = f"""User Request: {state['user_request']}
Project ID: {state['project_id']}

Relevant Semantic Memories:
{memory_str}

Decompose the request into a list of sub-tasks according to the guidelines."""

        messages = [
            SystemMessage(content=CEO_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]

        try:
            resp = self.llm.invoke(messages)
            raw_text = resp.content.strip()
            
            # Extract JSON from potential markdown blocks
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()

            parsed = json.loads(raw_text)
            tasks = parsed.get("decomposed_tasks", [])
            
            decomposed_tasks: List[TaskItem] = []
            for task in tasks:
                t: TaskItem = {
                    "task_id": task.get("task_id", str(uuid.uuid4())),
                    "title": task.get("title", "Sub-task"),
                    "description": task.get("description", ""),
                    "assigned_agent": task.get("assigned_agent", "research"),
                    "priority": task.get("priority", 5),
                    "dependencies": task.get("dependencies", []),
                    "status": "pending"
                }
                decomposed_tasks.append(t)

            state["decomposed_tasks"] = decomposed_tasks
            duration_ms = int(time.time() * 1000) - start_ms

            # Log to episodic memory
            plan_str = ", ".join([f"{t['title']} ({t['assigned_agent']})" for t in decomposed_tasks])
            episodic_memory.record(
                agent_name=self.agent_name,
                content=f"Decomposed task into: {plan_str}",
                event_type="plan",
                task_id=state["task_id"]
            )
            
            # Record state output
            state["agent_outputs"].append({
                "agent_name": self.agent_name,
                "output_type": "plan",
                "content": json.dumps(decomposed_tasks, indent=2),
                "success": True,
                "tokens_used": resp.response_metadata.get("token_usage", {}).get("total_tokens", 0),
                "duration_ms": duration_ms,
                "metadata": {}
            })
            
            # Learn pattern in procedural memory
            procedural_memory.record_pattern(
                agent_name=self.agent_name,
                task_pattern="task_decomposition",
                tool_sequence=[t["assigned_agent"] for t in decomposed_tasks],
                success=True,
                duration_ms=duration_ms
            )
            
            logger.info(f"[CEO] Task decomposed into {len(decomposed_tasks)} sub-tasks.")
        except Exception as exc:
            logger.error(f"[CEO] Failed to decompose task: {exc}")
            state["error"] = f"CEO Agent failed: {exc}"
            state["agent_outputs"].append({
                "agent_name": self.agent_name,
                "output_type": "plan",
                "content": f"Decomposition failed: {exc}",
                "success": False,
                "tokens_used": 0,
                "duration_ms": int(time.time() * 1000) - start_ms,
                "metadata": {}
            })
            
        return state
