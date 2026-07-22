"""
EMAOS — CLI Client
Rich terminal interface for submitting tasks and monitoring the system.
"""
import json
import os
import sys
import time
from typing import Any, Dict, Optional

import click
import httpx
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()

API_BASE = os.getenv("EMAOS_API_URL", "http://localhost:8000")
TOKEN_FILE = os.path.expanduser("~/.emaos_token")


# ─── Auth helpers ─────────────────────────────────────────────────
def _save_token(token: str) -> None:
    with open(TOKEN_FILE, "w") as f:
        f.write(token)


def _load_token() -> Optional[str]:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return f.read().strip() or None
    return None


def _get_headers() -> Dict[str, str]:
    token = _load_token()
    if not token:
        console.print("[bold red]✗[/] Not logged in. Run: [cyan]emaos login[/]")
        sys.exit(1)
    return {"Authorization": f"Bearer {token}"}


def _api(method: str, path: str, **kwargs) -> Dict[str, Any]:
    url = f"{API_BASE}{path}"
    try:
        resp = httpx.request(method, url, headers=_get_headers(), timeout=120, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        try:
            err = exc.response.json()
            console.print(f"[bold red]API Error {exc.response.status_code}:[/] {err.get('error', {}).get('message', str(exc))}")
        except Exception:
            console.print(f"[bold red]HTTP Error {exc.response.status_code}[/]")
        sys.exit(1)
    except httpx.ConnectError:
        console.print("[bold red]✗[/] Cannot connect to EMAOS Backend. Ensure start.ps1 or docker containers are active.")
        sys.exit(1)


# ─── CLI Group ────────────────────────────────────────────────────
@click.group()
def cli():
    """EMAOS CLI Client - Command-line interface for the Multi-Agent AI OS."""
    pass


# ─── Login ────────────────────────────────────────────────────────
@cli.command()
@click.option("--username", default="admin", help="Admin username")
@click.password_option("--password", default="emaos_admin_2024", help="Admin password")
def login(username, password):
    """Authenticate and log in to the EMAOS API backend."""
    url = f"{API_BASE}/token"
    try:
        resp = httpx.post(url, json={"username": username, "password": password})
        if resp.status_code == 200:
            token = resp.json()["access_token"]
            _save_token(token)
            console.print(f"[bold green]✓[/] Successfully logged in as [cyan]{username}[/]! Token saved.")
        else:
            console.print("[bold red]✗[/] Authentication failed. Check credentials.")
    except Exception as exc:
        console.print(f"[bold red]✗[/] Failed to connect: {exc}")


# ─── Submit ───────────────────────────────────────────────────────
@cli.command()
@click.argument("request_text")
@click.option("--project", default="default", help="Project ID context")
def submit(request_text, project):
    """Submit a high-level task to the CEO agent."""
    res = _api("POST", "/tasks/submit", json={"user_request": request_text, "project_id": project})
    task_id = res["task_id"]
    console.print(f"[bold green]✓[/] Task submitted! [bold cyan]Task ID: {task_id}[/]")
    console.print(f"Run: [cyan]emaos monitor {task_id}[/] to watch execution.")


# ─── List ─────────────────────────────────────────────────────────
@cli.command("list")
def list_tasks():
    """List historical tasks in the database."""
    tasks = _api("GET", "/tasks/")
    if not tasks:
        console.print("No tasks found.")
        return
        
    table = Table(title="EMAOS Submitted Tasks", box=box.ROUNDED)
    table.add_column("Task ID", style="cyan")
    table.add_column("Project", style="magenta")
    table.add_column("Request Details", style="white")
    table.add_column("Status", style="bold yellow")
    
    for t in tasks:
        status_style = "green" if t["status"] == "completed" else ("red" if t["status"] == "failed" else "yellow")
        table.add_row(
            t["id"][:8] + "...",
            t["project_id"],
            t["title"][:50] + "...",
            f"[bold {status_style}]{t['status']}[/]"
        )
    console.print(table)


# ─── Monitor ──────────────────────────────────────────────────────
@cli.command()
@click.argument("task_id")
def monitor(task_id):
    """Monitor task execution stream in real-time."""
    console.print(f"Streaming execution metrics for Task [bold cyan]{task_id}[/]...")
    
    with Live(Panel("Initializing stream...", title="EMAOS Agent Streams"), refresh_per_second=1) as live:
        while True:
            res = _api("GET", f"/tasks/{task_id}")
            status = res["status"]
            outputs = res["agent_outputs"]
            
            # Build Live dashboard layout
            table = Table(box=box.MINIMAL, expand=True)
            table.add_column("Agent", style="cyan", width=15)
            table.add_column("Type", style="magenta", width=15)
            table.add_column("Content Preview", style="white")
            table.add_column("Success", style="bold", width=10)
            
            for out in outputs:
                ok_marker = "[green]✓[/]" if out["success"] else "[red]✗[/]"
                content_preview = out["content"].replace("\n", " ")[:80] + "..."
                table.add_row(
                    out["agent_name"].upper(),
                    out["output_type"],
                    content_preview,
                    ok_marker
                )
                
            status_color = "green" if status == "completed" else ("red" if status == "failed" else "yellow")
            status_text = f"Status: [bold {status_color}]{status.upper()}[/] | Iterations: {res['iteration_count']}"
            
            layout = Layout()
            layout.split_column(
                Layout(Panel(status_text, style="bold white")),
                Layout(Panel(table, title="Agent Logs Stream"))
            )
            
            live.update(layout)
            
            if status in ["completed", "failed"]:
                # Show final report
                if res["final_reports"]:
                    rep = res["final_reports"][0]
                    console.print("\n[bold green]═ Final Executive Summary Report ═[/]")
                    console.print(rep["summary"])
                break
            time.sleep(2)


if __name__ == "__main__":
    cli()
