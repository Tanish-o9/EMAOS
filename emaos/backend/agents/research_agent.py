"""
EMAOS — Research Agent
Literature review, data synthesis, hypothesis testing, evaluation harness.
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

RESEARCH_SYSTEM_PROMPT = """You are the Research Agent of EMAOS.

You are an expert AI researcher. Your responsibilities:
- Literature synthesis and research summaries
- Hypothesis formation and testing frameworks
- Data analysis and interpretation
- Comparative evaluation of approaches
- Academic paper structuring

Return your response as JSON:
{
  "research_type": "literature_review|hypothesis_test|data_analysis|comparative|synthesis",
  "title": "research title",
  "abstract": "150-word abstract",
  "methodology": "research approach used",
  "findings": [{"finding": "...", "evidence": "...", "confidence": "low|medium|high"}],
  "hypothesis": {"statement": "...", "supported": true|false, "reasoning": "..."},
  "future_work": ["suggested follow-up research"],
  "references": ["key references or data sources used"],
  "limitations": ["known limitations of this analysis"]
}
"""


def _web_search(query: str, n: int = 5) -> str:
    if TAVILY_API_KEY and TAVILY_API_KEY != "optional_tavily_key_here":
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=TAVILY_API_KEY)
            result = client.search(query, max_results=n)
            return "\n\n".join([
                f"[{r.get('url', '')}] {r.get('title', '')}:\n{r.get('content', '')}"
                for r in result
            ])
        except Exception as e:
            logger.warning(f"[RESEARCH] Tavily search error: {e}")
    
    # Fallback/Mock search for testing when key is missing
    logger.info(f"[RESEARCH] Falling back to mock search for query: '{query}'")
    return f"""Mock search results for query: '{query}'
- [https://example.org/multi-agent] Multi-agent system orchestration is a rapidly growing area in AI.
- [https://arxiv.org/abs/2401] Recent papers show that task decomposition by specialized LLM agents increases accuracy by 25-40% compared to monolithic systems.
- [https://github.com/langchain-ai] LangGraph provides cyclic graph states which are ideal for multi-agent feedback loops (e.g. Developer-Tester combinations).
"""


class ResearchAgent:
    def __init__(self):
        self.llm = ChatGroq(
            groq_api_key=GROQ_API_KEY,
            model_name=GROQ_MODEL,
            temperature=0.3,
            max_tokens=4096,
        )
        self.agent_name = "research"

    def run(self, state: GraphState) -> GraphState:
        start_ms = int(time.time() * 1000)
        task = state.get("current_task", {})
        task_desc = task.get("description", state["user_request"]) if task else state["user_request"]
        
        logger.info(f"[RESEARCH] Commencing research on: '{task_desc[:60]}...'")

        # 1. Execute Web Search
        search_results = _web_search(task_desc)

        prompt = f"""Task description to research: {task_desc}
Project ID: {state['project_id']}

Web search results:
{search_results}

Please synthesize these findings and compile a structured research report in JSON."""

        messages = [
            SystemMessage(content=RESEARCH_SYSTEM_PROMPT),
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
            title = parsed.get("title", "Research Summary")
            abstract = parsed.get("abstract", "")
            
            duration_ms = int(time.time() * 1000) - start_ms
            
            # Format report content
            report_markdown = f"""# {title}

**Abstract:**
{abstract}

**Methodology:**
{parsed.get('methodology', '')}

## Key Findings
"""
            for idx, f in enumerate(parsed.get("findings", []), 1):
                report_markdown += f"\n{idx}. **{f.get('finding')}** (Confidence: {f.get('confidence', '').upper()})\n   *Evidence:* {f.get('evidence')}\n"
                
            report_markdown += f"""
## Hypothesis Review
*Statement:* {parsed.get('hypothesis', {}).get('statement', 'N/A')}
*Supported:* {parsed.get('hypothesis', {}).get('supported', 'N/A')}
*Reasoning:* {parsed.get('hypothesis', {}).get('reasoning', 'N/A')}

## Limitations
"""
            for lim in parsed.get("limitations", []):
                report_markdown += f"- {lim}\n"

            report_markdown += "\n## References\n"
            for ref in parsed.get("references", []):
                report_markdown += f"- {ref}\n"

            # Log to episodic memory
            episodic_memory.record(
                agent_name=self.agent_name,
                content=f"Researched '{title}'. Findings count: {len(parsed.get('findings', []))}",
                event_type="research",
                task_id=state["task_id"]
            )
            
            # Add semantic memories for the findings
            semantic_memory.add(
                text=f"Research on '{title}' found: {abstract[:100]}...",
                agent_name=self.agent_name,
                metadata={"task_id": state["task_id"], "project_id": state["project_id"]}
            )

            state["agent_outputs"].append({
                "agent_name": self.agent_name,
                "output_type": "report",
                "content": report_markdown,
                "success": True,
                "tokens_used": resp.response_metadata.get("token_usage", {}).get("total_tokens", 0),
                "duration_ms": duration_ms,
                "metadata": {"research_report": parsed, "search_results": search_results}
            })

            procedural_memory.record_pattern(
                agent_name=self.agent_name,
                task_pattern="literature_research",
                tool_sequence=["web_search", "synthesize_report"],
                success=True,
                duration_ms=duration_ms
            )

        except Exception as exc:
            logger.error(f"[RESEARCH] Research failed: {exc}")
            state["agent_outputs"].append({
                "agent_name": self.agent_name,
                "output_type": "report",
                "content": f"Research failed: {exc}",
                "success": False,
                "tokens_used": 0,
                "duration_ms": int(time.time() * 1000) - start_ms,
                "metadata": {}
            })
            
        return state
