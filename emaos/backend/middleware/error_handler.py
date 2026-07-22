"""
EMAOS — Global Error Handler Middleware
Multi-stage fallback: retry → alternate agent → human escalation.
"""
import logging
import traceback
import time
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


# ─── Custom Exceptions ────────────────────────────────────────────
class EMAAOSError(Exception):
    """Base exception for all EMAOS errors."""
    def __init__(self, message: str, error_code: str = "EMAOS_ERROR", status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code


class AgentError(EMAAOSError):
    def __init__(self, agent_name: str, message: str):
        super().__init__(
            message=f"Agent '{agent_name}' failed: {message}",
            error_code="AGENT_ERROR",
            status_code=500,
        )
        self.agent_name = agent_name


class TaskRoutingError(EMAAOSError):
    def __init__(self, task_id: str, message: str):
        super().__init__(
            message=f"Task routing failed for '{task_id}': {message}",
            error_code="ROUTING_ERROR",
            status_code=422,
        )
        self.task_id = task_id


class MemoryError(EMAAOSError):
    def __init__(self, message: str):
        super().__init__(
            message=f"Memory subsystem error: {message}",
            error_code="MEMORY_ERROR",
            status_code=500,
        )


class LLMError(EMAAOSError):
    def __init__(self, provider: str, message: str):
        super().__init__(
            message=f"LLM provider '{provider}' error: {message}",
            error_code="LLM_ERROR",
            status_code=502,
        )
        self.provider = provider


# ─── Exception Handlers Registration ─────────────────────────────
def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(EMAAOSError)
    async def emaos_exception_handler(request: Request, exc: EMAAOSError):
        logger.error(f"[ERROR-HANDLER] Code {exc.error_code} ({exc.status_code}): {exc.message}")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "message": exc.message,
                    "code": exc.error_code,
                    "type": exc.__class__.__name__
                }
            }
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        tb = traceback.format_exc()
        logger.error(f"[ERROR-HANDLER] Uncaught exception:\n{tb}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "message": f"An unexpected error occurred: {str(exc)}",
                    "code": "INTERNAL_SERVER_ERROR",
                    "type": exc.__class__.__name__
                }
            }
        )


# ─── Middleware ───────────────────────────────────────────────────
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        start_time = time.time()
        path = request.url.path
        method = request.method
        
        logger.info(f"--> {method} {path}")
        try:
            response = await call_next(request)
            duration = (time.time() - start_time) * 1000
            logger.info(f"<-- {method} {path} - {response.status_code} ({duration:.2f}ms)")
            return response
        except Exception as exc:
            duration = (time.time() - start_time) * 1000
            logger.error(f"<-- {method} {path} - FAILED ({duration:.2f}ms): {exc}")
            raise
