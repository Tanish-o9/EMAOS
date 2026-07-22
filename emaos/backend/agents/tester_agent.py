"""
EMAOS — Tester Agent
Real Python execution sandbox + feedback loop with retry routing.
"""
import ast
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import traceback
from contextlib import redirect_stdout, redirect_stderr
from typing import Any, Dict, List, Optional, Tuple

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from orchestration.state import GraphState
from memory.episodic_memory import episodic_memory
from memory.semantic_memory import semantic_memory
from memory.procedural_memory import procedural_memory

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

TESTER_SYSTEM_PROMPT = """You are the Tester Agent of EMAOS.

Your job is to:
1. Write comprehensive test cases for the provided code
2. Analyse test results and identify root causes of failures
3. Provide actionable feedback for the Developer agent

Return ONLY valid JSON:
{
  "test_cases": [
    {
      "name": "test_name",
      "code": "executable Python test code as a string",
      "expected": "what the test should verify",
      "category": "unit|integration|edge_case"
    }
  ],
  "test_plan": "brief description of testing strategy",
  "coverage_areas": ["list of what is being tested"]
}
"""

ANALYSIS_SYSTEM_PROMPT = """You are a senior QA engineer. Analyse these test results and provide feedback.

Return ONLY valid JSON:
{
  "overall_status": "pass|fail|partial",
  "pass_count": 0,
  "fail_count": 0,
  "failures": [
    {
      "test_name": "name",
      "error": "error message",
      "root_cause": "likely cause",
      "fix_suggestion": "concrete suggestion for the developer"
    }
  ],
  "quality_score": 0.0,
  "recommendation": "proceed|retry_developer|human_review"
}
"""


class TesterAgent:
    def __init__(self):
        self.llm = ChatGroq(
            groq_api_key=GROQ_API_KEY,
            model_name=GROQ_MODEL,
            temperature=0.2,
            max_tokens=4096,
        )
        self.agent_name = "tester"

    def run(self, state: GraphState) -> GraphState:
        start_ms = int(time.time() * 1000)
        logger.info("[TESTER] Initiating QA testing cycle...")

        # Find the latest developer output in state
        dev_out = next((o for o in reversed(state["agent_outputs"]) if o["agent_name"] == "developer"), None)
        if not dev_out or not dev_out["success"]:
            logger.warning("[TESTER] No successful developer output found to test.")
            return self._abort_test(state, "No developer code available to test", start_ms)

        files = dev_out.get("metadata", {}).get("files", [])
        if not files:
            return self._abort_test(state, "Developer output metadata contains no files to test", start_ms)

        # 1. Generate tests via LLM
        logger.info(f"[TESTER] Generating test cases for {len(files)} file(s)")
        code_str = ""
        for f in files:
            code_str += f"\nFile: {f['filename']}\nContent:\n{f['content']}\n"

        prompt = f"Please write unit and integration test cases for this code:\n{code_str}"
        try:
            resp = self.llm.invoke([
                SystemMessage(content=TESTER_SYSTEM_PROMPT),
                HumanMessage(content=prompt)
            ])
            raw_text = resp.content.strip()
            
            # Extract JSON
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()

            parsed = json.loads(raw_text)
            test_cases = parsed.get("test_cases", [])
            logger.info(f"[TESTER] Generated {len(test_cases)} test cases.")
        except Exception as exc:
            logger.error(f"[TESTER] Failed to generate test cases: {exc}")
            return self._abort_test(state, f"Failed to generate tests: {exc}", start_ms)

        # 2. Run tests in sandbox temp folder
        test_results = []
        pass_count = 0
        fail_count = 0
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            sys.path.insert(0, str(temp_path))
            
            # Write developer files to sandbox
            for file_info in files:
                filename = file_info["filename"]
                filepath = temp_path / filename
                filepath.parent.mkdir(parents=True, exist_ok=True)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(file_info["content"])

            # Execute each test case
            for tc in test_cases:
                tc_name = tc["name"]
                tc_code = tc["code"]
                tc_path = temp_path / f"{tc_name}.py"
                
                with open(tc_path, "w", encoding="utf-8") as f:
                    f.write(tc_code)
                
                logger.info(f"[TESTER] Executing test case: {tc_name}...")
                try:
                    res = subprocess.run(
                        [sys.executable, str(tc_path)],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        cwd=temp_dir
                    )
                    
                    if res.returncode == 0:
                        pass_count += 1
                        test_results.append({"name": tc_name, "status": "pass", "output": res.stdout})
                        logger.info(f"[TESTER] Test case {tc_name}: PASSED")
                    else:
                        fail_count += 1
                        test_results.append({
                            "name": tc_name,
                            "status": "fail",
                            "error": res.stderr or res.stdout,
                            "code": tc_code
                        })
                        logger.warning(f"[TESTER] Test case {tc_name}: FAILED")
                except subprocess.TimeoutExpired:
                    fail_count += 1
                    test_results.append({"name": tc_name, "status": "fail", "error": "Execution Timed Out"})
                    logger.warning(f"[TESTER] Test case {tc_name}: TIMED OUT")
                except Exception as e:
                    fail_count += 1
                    test_results.append({"name": tc_name, "status": "fail", "error": str(e)})
                    logger.warning(f"[TESTER] Test case {tc_name}: ERROR - {e}")

        # 3. Analyze test results via LLM
        analysis_prompt = f"""Test results:
Passes: {pass_count}
Failures: {fail_count}

Details:
{json.dumps(test_results, indent=2)}

Developer Code:
{code_str}

Please analyze these results and output a structured QA report."""
        
        try:
            resp_analysis = self.llm.invoke([
                SystemMessage(content=ANALYSIS_SYSTEM_PROMPT),
                HumanMessage(content=analysis_prompt)
            ])
            raw_analysis = resp_analysis.content.strip()
            
            if "```json" in raw_analysis:
                raw_analysis = raw_analysis.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_analysis:
                raw_analysis = raw_analysis.split("```")[1].split("```")[0].strip()
                
            analysis = json.loads(raw_analysis)
            overall_status = analysis.get("overall_status", "fail")
            recommendation = analysis.get("recommendation", "retry_developer")
        except Exception as exc:
            logger.error(f"[TESTER] Analysis parsing failed: {exc}")
            overall_status = "fail"
            recommendation = "retry_developer"
            analysis = {"error": f"Failed to parse analysis: {exc}"}

        duration_ms = int(time.time() * 1000) - start_ms
        success = (overall_status == "pass" and fail_count == 0)

        # Record to memory
        content_desc = f"Tested {len(test_cases)} scenarios. Passes: {pass_count}, Failures: {fail_count}. Recommendation: {recommendation}."
        episodic_memory.record(
            agent_name=self.agent_name,
            content=content_desc,
            event_type="testing",
            task_id=state["task_id"]
        )

        state["agent_outputs"].append({
            "agent_name": self.agent_name,
            "output_type": "test_result",
            "content": content_desc + f"\n\nReport:\n{json.dumps(analysis, indent=2)}",
            "success": success,
            "tokens_used": resp.response_metadata.get("token_usage", {}).get("total_tokens", 0),
            "duration_ms": duration_ms,
            "metadata": {"test_results": test_results, "pass_count": pass_count, "fail_count": fail_count, "qa_report": analysis}
        })

        procedural_memory.record_pattern(
            agent_name=self.agent_name,
            task_pattern="code_testing",
            tool_sequence=["generate_tests", "run_sandbox_tests"],
            success=success,
            duration_ms=duration_ms
        )

        # Trigger developer retry if recommended and iteration budget allows
        if not success and recommendation == "retry_developer":
            logger.warning("[TESTER] Code verification failed. Flagging error for Developer review.")
            # Set state error to notify the graph to retry developer or stop
            state["error"] = f"Code verification failed: {len(analysis.get('failures', []))} test failures."
            
        return state

    def _abort_test(self, state: GraphState, message: str, start_ms: int) -> GraphState:
        duration_ms = int(time.time() * 1000) - start_ms
        state["agent_outputs"].append({
            "agent_name": self.agent_name,
            "output_type": "test_result",
            "content": f"Test cycle aborted: {message}",
            "success": False,
            "tokens_used": 0,
            "duration_ms": duration_ms,
            "metadata": {}
        })
        state["error"] = message
        return state
