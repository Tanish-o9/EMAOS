"""
EMAOS — Monitoring Agent
System health tracking, metrics analysis, Prometheus exposition.
"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from prometheus_client import Counter, Gauge, Histogram

from orchestration.state import GraphState
from memory.episodic_memory import episodic_memory
from memory.semantic_memory import semantic_memory
from memory.procedural_memory import procedural_memory

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# ─── Prometheus Metrics ───────────────────────────────────────────
task_counter = Counter(
    "emaos_tasks_total",
    "Total number of tasks processed",
    ["agent", "status"],
)
agent_duration = Histogram(
    "emaos_agent_duration_seconds",
    "Agent execution duration",
    ["agent"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)
active_tasks = Gauge(
    "emaos_active_tasks",
    "Number of currently active tasks",
)
llm_tokens = Counter(
    "emaos_llm_tokens_total",
    "Total LLM tokens consumed",
    ["agent", "model"],
)
error_counter = Counter(
    "emaos_errors_total",
    "Total errors by agent",
    ["agent", "error_type"],
)
memory_operations = Counter(
    "emaos_memory_operations_total",
    "Memory read/write operations",
    ["memory_type", "operation"],
)

MONITORING_SYSTEM_PROMPT = """You are the Monitoring Agent of EMAOS.

You analyse system health metrics and agent performance data. Your responsibilities:
- Detect performance anomalies and bottlenecks
- Identify agents with degraded performance
- Recommend optimisations and scaling decisions
- Trigger system status alerts

Return your response as JSON:
{
  "system_health": "healthy|degraded|unhealthy",
  "anomaly_detected": true|false,
  "anomalies": [
    {
      "metric": "metric_name",
      "value": 0.0,
      "threshold": 0.0,
      "description": "anomaly description"
    }
  ],
  "recommendations": ["list of optimisations"],
  "alerts_triggered": ["list of alerts"]
}
"""


class MonitoringAgent:
    def __init__(self):
        self.llm = ChatGroq(
            groq_api_key=GROQ_API_KEY,
            model_name=GROQ_MODEL,
            temperature=0.2,
            max_tokens=4096,
        )
        self.agent_name = "monitoring"

    def run(self, state: GraphState) -> GraphState:
        start_ms = int(time.time() * 1000)
        logger.info("[MONITORING] Running system metrics analysis...")

        # Collect metrics metrics context
        outputs = state.get("agent_outputs", [])
        
        # 1. Update Prometheus metrics gauges/counters
        active_tasks.set(len([t for t in state.get("decomposed_tasks", []) if t["status"] == "in_progress"]))
        for out in outputs:
            agent = out["agent_name"]
            status_str = "success" if out["success"] else "failed"
            
            # Counter increments
            task_counter.labels(agent=agent, status=status_str).inc()
            agent_duration.labels(agent=agent).observe(out["duration_ms"] / 1000.0)
            llm_tokens.labels(agent=agent, model=GROQ_MODEL).inc(out.get("tokens_used", 0))
            if not out["success"]:
                error_counter.labels(agent=agent, error_type=out.get("output_type", "unknown")).inc()

        # Build metrics string for the LLM review
        metrics_summary = []
        for out in outputs:
            metrics_summary.append(
                f"- Agent: {out['agent_name']} | Success: {out['success']} | "
                f"Latency: {out['duration_ms']}ms | Tokens: {out.get('tokens_used', 0)}"
            )
        metrics_str = "\n".join(metrics_summary) if metrics_summary else "No tasks run yet in this workflow."

        prompt = f"""Metrics collected from the current task execution:
{metrics_str}

Failed State errors:
{state.get('error', 'None')}

Please check these stats for bottlenecks, compute limits, or failure spikes, and output your JSON health report."""

        messages = [
            SystemMessage(content=MONITORING_SYSTEM_PROMPT),
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
            health = parsed.get("system_health", "healthy")
            anomaly = parsed.get("anomaly_detected", False)
            
            duration_ms = int(time.time() * 1000) - start_ms
            
            content_desc = f"System health: {health.upper()} | Anomalies: {anomaly} | Recommendations: {len(parsed.get('recommendations', []))}"
            
            episodic_memory.record(
                agent_name=self.agent_name,
                content=content_desc,
                event_type="monitoring",
                task_id=state["task_id"]
            )

            state["agent_outputs"].append({
                "agent_name": self.agent_name,
                "output_type": "analysis",
                "content": content_desc + f"\n\nMetrics Report:\n{json.dumps(parsed, indent=2)}",
                "success": True,
                "tokens_used": resp.response_metadata.get("token_usage", {}).get("total_tokens", 0),
                "duration_ms": duration_ms,
                "metadata": {"health_report": parsed}
            })

            procedural_memory.record_pattern(
                agent_name=self.agent_name,
                task_pattern="metrics_monitoring",
                tool_sequence=["observe_prometheus", "detect_anomalies"],
                success=True,
                duration_ms=duration_ms
            )

        except Exception as exc:
            logger.error(f"[MONITORING] Metrics review failed: {exc}")
            state["agent_outputs"].append({
                "agent_name": self.agent_name,
                "output_type": "analysis",
                "content": f"Monitoring health check failed: {exc}",
                "success": False,
                "tokens_used": 0,
                "duration_ms": int(time.time() * 1000) - start_ms,
                "metadata": {}
            })
            
        return state
