"""
EMAOS — HR Agent
Job description generation, resume screening, interview question generation.
"""
import json
import logging
import os
import time
from typing import Any, Dict, List

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from orchestration.state import GraphState
from memory.episodic_memory import episodic_memory
from memory.semantic_memory import semantic_memory
from memory.procedural_memory import procedural_memory

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

HR_SYSTEM_PROMPT = """You are the HR Agent of EMAOS.

You are an expert Chief People Officer (CPO). Your responsibilities:
- Job description creation (inclusive, skills-based)
- Resume screening and candidate ranking
- Interview question generation (behavioral + technical)
- Onboarding plan creation
- Employee performance framework design
- Culture and team dynamics analysis

Return your response as JSON:
{
  "task_type": "job_description|resume_screening|interview_questions|onboarding|performance",
  "executive_summary": "brief overview",
  "output": {
    "primary_content": "main deliverable (job description text, questions list, etc.)",
    "structured_data": {}
  },
  "recommendations": ["actionable HR recommendations"],
  "diversity_notes": "inclusivity considerations",
  "follow_up_actions": ["next steps"]
}
"""


class HRAgent:
    def __init__(self):
        self.llm = ChatGroq(
            groq_api_key=GROQ_API_KEY,
            model_name=GROQ_MODEL,
            temperature=0.3,
            max_tokens=4096,
        )
        self.agent_name = "hr"

    def run(self, state: GraphState) -> GraphState:
        start_ms = int(time.time() * 1000)
        task = state.get("current_task", {})
        task_desc = task.get("description", state["user_request"]) if task else state["user_request"]
        
        logger.info(f"[HR] Performing talent management task: '{task_desc[:60]}...'")

        prompt = f"""Talent task request: {task_desc}
Project ID: {state['project_id']}

Provide a highly professional HR deliverable in JSON format."""

        messages = [
            SystemMessage(content=HR_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]

        try:
            resp = self.llm.invoke(messages)
            raw_text = resp.content.strip()
            
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()

            parsed = json.loads(raw_text)
            exec_summary = parsed.get("executive_summary", "HR analysis completed.")
            output_data = parsed.get("output", {})
            primary_content = output_data.get("primary_content", "")
            
            duration_ms = int(time.time() * 1000) - start_ms

            # Format HR report as markdown
            report_md = f"""# HR Talent Plan & Deliverable ({parsed.get('task_type', 'General').upper()})

## Executive Summary
{exec_summary}

## Primary Deliverable
{primary_content}

## Actionable HR Recommendations
"""
            for rec in parsed.get("recommendations", []):
                report_md += f"- {rec}\n"

            if parsed.get("diversity_notes"):
                report_md += f"\n## Inclusivity & Diversity Notes\n{parsed.get('diversity_notes')}\n"

            report_md += "\n## Follow-up Action Items\n"
            for act in parsed.get("follow_up_actions", []):
                report_md += f"- {act}\n"

            # Log to episodic memory
            episodic_memory.record(
                agent_name=self.agent_name,
                content=f"Completed HR plan: '{parsed.get('task_type')}' - {exec_summary[:100]}...",
                event_type="hr",
                task_id=state["task_id"]
            )
            
            semantic_memory.add(
                text=f"HR agent compiled deliverable: {exec_summary}",
                agent_name=self.agent_name,
                metadata={"task_id": state["task_id"], "project_id": state["project_id"]}
            )

            state["agent_outputs"].append({
                "agent_name": self.agent_name,
                "output_type": "report",
                "content": report_md,
                "success": True,
                "tokens_used": resp.response_metadata.get("token_usage", {}).get("total_tokens", 0),
                "duration_ms": duration_ms,
                "metadata": {"hr_deliverable": parsed}
            })

            procedural_memory.record_pattern(
                agent_name=self.agent_name,
                task_pattern="hr_planning",
                tool_sequence=["formulate_job_profiles", "draft_interviews"],
                success=True,
                duration_ms=duration_ms
            )

        except Exception as exc:
            logger.error(f"[HR] Deliverable compilation failed: {exc}")
            state["agent_outputs"].append({
                "agent_name": self.agent_name,
                "output_type": "report",
                "content": f"HR task failed: {exc}",
                "success": False,
                "tokens_used": 0,
                "duration_ms": int(time.time() * 1000) - start_ms,
                "metadata": {}
            })
            
        return state
