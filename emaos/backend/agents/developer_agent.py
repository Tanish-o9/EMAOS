"""
EMAOS — Developer Agent
Real code generation + GitHub automation via PyGitHub.
"""
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
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
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO_OWNER = os.getenv("GITHUB_REPO_OWNER", "")
GITHUB_DEFAULT_REPO = os.getenv("GITHUB_DEFAULT_REPO", "")

DEVELOPER_SYSTEM_PROMPT = """You are the Developer Agent of EMAOS.

Your job is to write clean, production-quality code based on task descriptions.

RULES:
1. Write complete, working code — no placeholders, no TODOs unless explicitly requested.
2. Include proper error handling and logging.
3. Include docstrings for all functions and classes.
4. Return your response as JSON with this schema:
{
  "files": [
    {
      "filename": "path/to/file.py",
      "content": "full file content here",
      "description": "what this file does"
    }
  ],
  "explanation": "brief explanation of the implementation",
  "tests_needed": ["list of test scenarios to verify"],
  "dependencies": ["list of pip packages needed"]
}

IMPORTANT: Return ONLY valid JSON. No markdown fences, no prose outside the JSON.
"""


class DeveloperAgent:
    def __init__(self):
        self.llm = ChatGroq(
            groq_api_key=GROQ_API_KEY,
            model_name=GROQ_MODEL,
            temperature=0.2,
            max_tokens=8192,
        )
        self.agent_name = "developer"

    def run(self, state: GraphState) -> GraphState:
        start_ms = int(time.time() * 1000)
        task = state.get("current_task", {})
        task_desc = task.get("description", state["user_request"]) if task else state["user_request"]
        
        logger.info(f"[DEVELOPER] Working on task: '{task.get('title', 'Coding Task')}'")

        # Query semantic memory for relevant code context
        memories = semantic_memory.search(task_desc, limit=3)
        memory_str = "\n".join([f"- Memory: {m['content']}" for m in memories]) if memories else "None"

        prompt = f"""Task Description: {task_desc}
Project ID: {state['project_id']}

Relevant Semantic Memories:
{memory_str}

Please implement this code according to the guidelines."""

        messages = [
            SystemMessage(content=DEVELOPER_SYSTEM_PROMPT),
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
            files = parsed.get("files", [])
            explanation = parsed.get("explanation", "")
            
            # Write files locally to workspace
            written_files = []
            for file_info in files:
                filename = file_info.get("filename")
                content = file_info.get("content")
                if filename and content:
                    # Clean filename path to avoid escaping workspace root
                    clean_filename = os.path.basename(filename)
                    # Put it in a target folder: emaos/backend/dev_sandbox or similar
                    sandbox_dir = Path("c:/Users/tanis/OneDrive/Desktop/EMAOS/emaos/dev_sandbox")
                    sandbox_dir.mkdir(parents=True, exist_ok=True)
                    filepath = sandbox_dir / clean_filename
                    
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(content)
                    written_files.append(str(filepath))
                    logger.info(f"[DEVELOPER] Wrote local file: {filepath}")

            # Try GitHub integration if token is set
            github_success = False
            github_msg = "Skipped (no GitHub configuration)"
            if GITHUB_TOKEN and GITHUB_REPO_OWNER and GITHUB_DEFAULT_REPO and GITHUB_TOKEN != "your_github_token_here":
                github_success, github_msg = self._create_github_pr(files, task.get("title", "Coding Task"))

            duration_ms = int(time.time() * 1000) - start_ms
            success = len(written_files) > 0 or github_success
            
            content_desc = f"Implemented {len(files)} files: {', '.join([f['filename'] for f in files])}. Github: {github_msg}."
            
            episodic_memory.record(
                agent_name=self.agent_name,
                content=content_desc,
                event_type="code_generation",
                task_id=state["task_id"]
            )
            
            # Add semantic memories for the code generated
            for file_info in files:
                semantic_memory.add(
                    text=f"Developer generated code in {file_info['filename']}: {file_info['description']}",
                    agent_name=self.agent_name,
                    metadata={"task_id": state["task_id"], "project_id": state["project_id"]}
                )

            state["agent_outputs"].append({
                "agent_name": self.agent_name,
                "output_type": "code",
                "content": content_desc + f"\n\nExplanation:\n{explanation}",
                "success": success,
                "tokens_used": resp.response_metadata.get("token_usage", {}).get("total_tokens", 0),
                "duration_ms": duration_ms,
                "metadata": {"files": files, "written_files": written_files, "github_pr": github_msg}
            })

            # Record success stats in procedural memory
            procedural_memory.record_pattern(
                agent_name=self.agent_name,
                task_pattern="code_generation",
                tool_sequence=["write_files", "github_pr"] if GITHUB_TOKEN else ["write_files"],
                success=success,
                duration_ms=duration_ms
            )

        except Exception as exc:
            logger.error(f"[DEVELOPER] Execution failed: {exc}")
            state["error"] = f"Developer Agent failed: {exc}"
            state["agent_outputs"].append({
                "agent_name": self.agent_name,
                "output_type": "code",
                "content": f"Implementation failed: {exc}",
                "success": False,
                "tokens_used": 0,
                "duration_ms": int(time.time() * 1000) - start_ms,
                "metadata": {}
            })
            
        return state

    def _create_github_pr(self, files: List[dict], task_title: str) -> Tuple[bool, str]:
        """Automate GitHub branch creation and PR submission using pygithub."""
        try:
            from github import Github
            g = Github(GITHUB_TOKEN)
            repo_path = f"{GITHUB_REPO_OWNER}/{GITHUB_DEFAULT_REPO}"
            repo = g.get_repo(repo_path)
            
            # Create a unique branch name
            branch_name = f"emaos-dev-{int(time.time())}"
            sb = repo.get_branch("main") # default to main branch
            repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sb.commit.sha)
            
            # Commit files
            for file_info in files:
                filename = file_info.get("filename")
                content = file_info.get("content")
                try:
                    # Check if file exists to update, else create
                    contents = repo.get_contents(filename, ref=branch_name)
                    repo.update_file(
                        path=filename,
                        message=f"Update {filename} from EMAOS Developer Agent",
                        content=content,
                        sha=contents.sha,
                        branch=branch_name
                    )
                except Exception:
                    repo.create_file(
                        path=filename,
                        message=f"Create {filename} from EMAOS Developer Agent",
                        content=content,
                        branch=branch_name
                    )
            
            # Submit PR
            pr = repo.create_pull(
                title=f"EMAOS: {task_title}",
                body=f"Automated PR from EMAOS Developer Agent for task: {task_title}",
                head=branch_name,
                base="main"
            )
            logger.info(f"[DEVELOPER] Created GitHub PR: {pr.html_url}")
            return True, f"Created Branch: {branch_name} | Pull Request: {pr.html_url}"
        except Exception as e:
            logger.error(f"[DEVELOPER] GitHub automation failed: {e}")
            return False, f"Failed: {e}"
