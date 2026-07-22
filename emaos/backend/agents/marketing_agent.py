"""
EMAOS — Marketing Agent
SEO analysis, content strategy, campaign planning, market research.
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
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

MARKETING_SYSTEM_PROMPT = """You are the Marketing Agent of EMAOS.

You are an expert CMO-level marketing strategist. Your responsibilities:
- SEO strategy and keyword analysis
- Content marketing campaigns
- Target audience identification and persona creation
- Competitive analysis and market positioning
- Campaign ROI measurement frameworks

Return your response as JSON:
{
  "campaign_type": "seo|content|social|email|paid",
  "executive_summary": "2-3 sentence overview",
  "target_audience": {
    "demographics": "...",
    "psychographics": "...",
    "pain_points": ["list of user challenges"]
  },
  "strategy": [
    {
      "phase": "Phase title",
      "duration": "Duration (e.g. Month 1)",
      "actions": ["list of actions"],
      "kpis": ["list of metrics"]
    }
  ],
  "content_ideas": [
    {
      "title": "Title of content piece",
      "type": "blog|video|infographic|email",
      "keywords": ["keywords to target"]
    }
  ],
  "seo_recommendations": [
    {
      "keyword": "keyword string",
      "difficulty": "low|medium|high",
      "intent": "informational|commercial|transactional"
    }
  ],
  "metrics": {"target_metric_name": "target_value"},
  "budget_allocation": {"channel_name": "percentage_string"}
}
"""


def _web_search(query: str) -> str:
    if TAVILY_API_KEY and TAVILY_API_KEY != "optional_tavily_key_here":
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=TAVILY_API_KEY)
            result = client.search(query, max_results=3)
            return "\n".join([r.get("content", "") for r in result])
        except Exception as e:
            logger.warning(f"[MARKETING] Tavily search error: {e}")
    return "Fallback market trends context."


class MarketingAgent:
    def __init__(self):
        self.llm = ChatGroq(
            groq_api_key=GROQ_API_KEY,
            model_name=GROQ_MODEL,
            temperature=0.3,
            max_tokens=4096,
        )
        self.agent_name = "marketing"

    def run(self, state: GraphState) -> GraphState:
        start_ms = int(time.time() * 1000)
        task = state.get("current_task", {})
        task_desc = task.get("description", state["user_request"]) if task else state["user_request"]
        
        logger.info(f"[MARKETING] Compiling marketing campaign for: '{task_desc[:60]}...'")

        # 1. Market trends web search
        search_data = _web_search(task_desc)

        prompt = f"""Task to formulate: {task_desc}
Project ID: {state['project_id']}

Market research search context:
{search_data}

Formulate a detailed, CMO-level marketing campaign in JSON format."""

        messages = [
            SystemMessage(content=MARKETING_SYSTEM_PROMPT),
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
            exec_summary = parsed.get("executive_summary", "Campaign compiled.")
            
            duration_ms = int(time.time() * 1000) - start_ms

            # Format marketing plan as markdown report
            report_md = f"""# Marketing Campaign Plan ({parsed.get('campaign_type', 'SEO').upper()})

## Executive Summary
{exec_summary}

## Target Audience
- **Demographics:** {parsed.get('target_audience', {}).get('demographics', 'N/A')}
- **Psychographics:** {parsed.get('target_audience', {}).get('psychographics', 'N/A')}

### Key Pain Points
"""
            for pp in parsed.get("target_audience", {}).get("pain_points", []):
                report_md += f"- {pp}\n"

            report_md += "\n## Action Plan Strategy\n"
            for s in parsed.get("strategy", []):
                report_md += f"### {s.get('phase')} ({s.get('duration')})\n"
                report_md += "**Actions:**\n"
                for act in s.get("actions", []):
                    report_md += f"- {act}\n"
                report_md += "**KPIs:**\n"
                for kpi in s.get("kpis", []):
                    report_md += f"  - {kpi}\n"
                report_md += "\n"

            report_md += "## Content Strategy Ideas\n"
            for c in parsed.get("content_ideas", []):
                report_md += f"- **{c.get('title')}** ({c.get('type').upper()}) - *Keywords: {', '.join(c.get('keywords', []))}*\n"

            report_md += "\n## SEO Keyword Audit Recommendations\n"
            for kw in parsed.get("seo_recommendations", []):
                report_md += f"- `{kw.get('keyword')}` (Difficulty: {kw.get('difficulty').upper()} | Intent: {kw.get('intent').upper()})\n"

            # Log to episodic memory
            episodic_memory.record(
                agent_name=self.agent_name,
                content=f"Formulated marketing campaign strategy. Summary: {exec_summary[:100]}...",
                event_type="marketing",
                task_id=state["task_id"]
            )
            
            semantic_memory.add(
                text=f"Marketing agent formulated plan: {exec_summary}",
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
                "metadata": {"marketing_strategy": parsed}
            })

            procedural_memory.record_pattern(
                agent_name=self.agent_name,
                task_pattern="marketing_strategy",
                tool_sequence=["keyword_search", "persona_mapping"],
                success=True,
                duration_ms=duration_ms
            )

        except Exception as exc:
            logger.error(f"[MARKETING] Strategy compile failed: {exc}")
            state["agent_outputs"].append({
                "agent_name": self.agent_name,
                "output_type": "report",
                "content": f"Marketing campaign failed: {exc}",
                "success": False,
                "tokens_used": 0,
                "duration_ms": int(time.time() * 1000) - start_ms,
                "metadata": {}
            })
            
        return state
