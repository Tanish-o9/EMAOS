"""
EMAOS — Finance Agent
Budget analysis, financial planning, expense categorization.
Uses DuckDuckGo/Tavily for real financial data.
"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from orchestration.state import GraphState
from memory.episodic_memory import episodic_memory
from memory.semantic_memory import semantic_memory
from memory.procedural_memory import procedural_memory

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

FINANCE_SYSTEM_PROMPT = """You are the Finance Agent of EMAOS.

You are an expert financial analyst and CFO-level advisor. Your responsibilities:
- Budget planning and allocation
- Financial analysis and forecasting
- Expense categorization and optimization
- ROI calculations and business case development
- Risk assessment for financial decisions

Always return structured, data-driven financial analysis. Include:
- Specific numbers and percentages where applicable
- Risk levels (LOW/MEDIUM/HIGH)
- Actionable recommendations
- Time horizons for projections

Return your response as JSON:
{
  "analysis_type": "budget|forecast|roi|risk|expense",
  "executive_summary": "2-3 sentence summary",
  "findings": [{"category": "...", "amount": 0.0, "insight": "..."}],
  "recommendations": ["specific actionable items"],
  "risks": [{"risk": "...", "level": "LOW|MEDIUM|HIGH", "mitigation": "..."}],
  "metrics": {"key_metric_name": 0.0},
  "timeline": "implementation timeline if applicable"
}
"""


def _web_search(query: str) -> str:
    """Search for financial data using Tavily."""
    if TAVILY_API_KEY and TAVILY_API_KEY != "optional_tavily_key_here":
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=TAVILY_API_KEY)
            result = client.search(query, max_results=3)
            return "\n".join([r.get("content", "") for r in result])
        except Exception as e:
            logger.warning(f"[FINANCE] Web search failed: {e}")
    return "Fallback financial metrics context."


class FinanceAgent:
    def __init__(self):
        self.llm = ChatGroq(
            groq_api_key=GROQ_API_KEY,
            model_name=GROQ_MODEL,
            temperature=0.2,
            max_tokens=4096,
        )
        self.agent_name = "finance"

    def run(self, state: GraphState) -> GraphState:
        start_ms = int(time.time() * 1000)
        task = state.get("current_task", {})
        task_desc = task.get("description", state["user_request"]) if task else state["user_request"]
        
        logger.info(f"[FINANCE] Performing financial audit for: '{task_desc[:60]}...'")

        # 1. Financial metrics search
        search_data = _web_search(task_desc)

        prompt = f"""Task to audit: {task_desc}
Project ID: {state['project_id']}

Relevant web data:
{search_data}

Provide a comprehensive, CFO-level financial analysis plan in JSON format."""

        messages = [
            SystemMessage(content=FINANCE_SYSTEM_PROMPT),
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
            exec_summary = parsed.get("executive_summary", "Audit completed.")
            
            duration_ms = int(time.time() * 1000) - start_ms

            # Format report as markdown
            report_md = f"""# Financial Analysis Report ({parsed.get('analysis_type', 'General').upper()})

## Executive Summary
{exec_summary}

## Key Findings
"""
            for f in parsed.get("findings", []):
                report_md += f"- **{f.get('category')}**: ${f.get('amount', 0.0):,.2f} - *{f.get('insight')}*\n"

            report_md += "\n## Actionable Recommendations\n"
            for rec in parsed.get("recommendations", []):
                report_md += f"- {rec}\n"

            report_md += "\n## Risk Assessment & Mitigations\n"
            for r in parsed.get("risks", []):
                report_md += f"- **{r.get('risk')}** (Risk Level: {r.get('level')})\n  *Mitigation:* {r.get('mitigation')}\n"

            if parsed.get("timeline"):
                report_md += f"\n## Implementation Timeline\n{parsed.get('timeline')}\n"

            # Log to episodic memory
            episodic_memory.record(
                agent_name=self.agent_name,
                content=f"Completed financial review. Summary: {exec_summary[:100]}...",
                event_type="finance",
                task_id=state["task_id"]
            )
            
            semantic_memory.add(
                text=f"Finance agent created analysis: {exec_summary}",
                agent_name=self.agent_name,
                metadata={"task_id": state["task_id"], "project_id": state["project_id"]}
            )

            state["agent_outputs"].append({
                "agent_name": self.agent_name,
                "output_type": "analysis",
                "content": report_md,
                "success": True,
                "tokens_used": resp.response_metadata.get("token_usage", {}).get("total_tokens", 0),
                "duration_ms": duration_ms,
                "metadata": {"finance_analysis": parsed}
            })

            procedural_memory.record_pattern(
                agent_name=self.agent_name,
                task_pattern="financial_analysis",
                tool_sequence=["search_financial_market", "compile_audit"],
                success=True,
                duration_ms=duration_ms
            )

        except Exception as exc:
            logger.error(f"[FINANCE] Analysis failed: {exc}")
            state["agent_outputs"].append({
                "agent_name": self.agent_name,
                "output_type": "analysis",
                "content": f"Financial analysis failed: {exc}",
                "success": False,
                "tokens_used": 0,
                "duration_ms": int(time.time() * 1000) - start_ms,
                "metadata": {}
            })
            
        return state
