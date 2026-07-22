"""
EMAOS — Research Evaluation Harness
Implements evaluation metrics from the EMAOS paper.
"""
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from orchestration.state import GraphState, initial_state
from orchestration.graph import run_graph

logger = logging.getLogger(__name__)

# ─── Benchmark task suite ─────────────────────────────────────────
BENCHMARK_TASKS = [
    {
        "id": "task_01",
        "description": "Build a REST API endpoint in Python using FastAPI that accepts a POST request with a JSON body containing 'name' and 'email' fields, validates them, and returns a UUID user ID.",
        "expected_agents": ["developer", "tester"],
        "category": "coding",
    },
    {
        "id": "task_02",
        "description": "Analyse the financial viability of launching a B2B SaaS product targeting mid-market companies. Include break-even analysis and 12-month cash flow projection.",
        "expected_agents": ["finance"],
        "category": "finance",
    },
    {
        "id": "task_03",
        "description": "Create a comprehensive SEO content strategy for a startup in the AI productivity tools space. Include keyword analysis, content calendar for Q1, and success metrics.",
        "expected_agents": ["marketing"],
        "category": "marketing",
    },
    {
        "id": "task_04",
        "description": "Write a senior Python engineer job description, 10 behavioral interview questions, and a technical screening rubric.",
        "expected_agents": ["hr"],
        "category": "hr",
    },
    {
        "id": "task_05",
        "description": "Research the current state of multi-agent AI systems in enterprise settings. Synthesise findings from recent papers and identify key challenges and opportunities.",
        "expected_agents": ["research"],
        "category": "research",
    },
]


class EvaluationHarness:
    def __init__(self):
        pass

    def run_benchmark(self) -> Dict[str, Any]:
        """Execute the entire benchmark suite and compile metrics."""
        logger.info(f"=== Starting EMAOS Benchmark Evaluation ({len(BENCHMARK_TASKS)} tasks) ===")
        
        results = []
        total_tasks = len(BENCHMARK_TASKS)
        successful_tasks = 0
        total_tokens = 0
        total_duration_ms = 0
        
        for task in BENCHMARK_TASKS:
            logger.info(f"\n--- Running Task {task['id']} ({task['category'].upper()}) ---")
            logger.info(f"Goal: {task['description']}")
            
            start_ms = int(time.time() * 1000)
            state = initial_state(task["description"], project_id=f"eval-{task['id']}")
            
            try:
                final_state = run_graph(state)
                duration = int(time.time() * 1000) - start_ms
                success = not final_state.get("error")
                
                # Sum metrics
                task_tokens = sum([o.get("tokens_used", 0) for o in final_state["agent_outputs"]])
                total_tokens += task_tokens
                total_duration_ms += duration
                
                if success:
                    successful_tasks += 1
                
                results.append({
                    "task_id": task["id"],
                    "category": task["category"],
                    "success": success,
                    "duration_ms": duration,
                    "tokens_used": task_tokens,
                    "iterations": final_state.get("iteration_count", 0),
                    "agents_used": [o["agent_name"] for o in final_state["agent_outputs"]],
                    "error": final_state.get("error")
                })
                
                logger.info(f"Result Task {task['id']}: {'SUCCESS' if success else 'FAILED'} ({duration/1000:.2f}s, {task_tokens} tokens)")
            except Exception as e:
                logger.error(f"Task {task['id']} crashed: {e}")
                results.append({
                    "task_id": task["id"],
                    "category": task["category"],
                    "success": False,
                    "duration_ms": int(time.time() * 1000) - start_ms,
                    "tokens_used": 0,
                    "iterations": 0,
                    "agents_used": [],
                    "error": str(e)
                })

        # Compile final stats
        success_rate = (successful_tasks / total_tasks) * 100.0 if total_tasks else 0.0
        avg_duration = (total_duration_ms / total_tasks) / 1000.0 if total_tasks else 0.0
        avg_tokens = total_tokens / total_tasks if total_tasks else 0.0

        summary = {
            "total_tasks": total_tasks,
            "successful_tasks": successful_tasks,
            "success_rate_percentage": success_rate,
            "total_tokens_consumed": total_tokens,
            "avg_tokens_per_task": avg_tokens,
            "total_duration_seconds": total_duration_ms / 1000.0,
            "avg_duration_seconds": avg_duration,
            "task_results": results
        }
        
        logger.info("\n=== Benchmark Evaluation Summary ===")
        logger.info(json.dumps(summary, indent=2))
        return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    harness = EvaluationHarness()
    harness.run_benchmark()
