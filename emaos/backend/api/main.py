"""
EMAOS — FastAPI Main Application
"""
import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from auth.jwt_handler import (
    TokenData,
    TokenResponse,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from middleware.error_handler import RequestLoggingMiddleware, register_exception_handlers
from api.routes import tasks, agents, reports
from database.connection import init_database, close_database, check_database_health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("emaos.main")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "emaos_admin_2024")
DATABASE_URL = os.getenv("DATABASE_URL", "")


# ─── Lifespan ─────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("═" * 60)
    logger.info("  EMAOS — Enterprise Multi-Agent AI Operating System")
    logger.info("  Starting up...")
    logger.info("═" * 60)

    # Initialize Database Schema
    try:
        await init_database()
        logger.info("  ✓ Database initialized successfully")
    except Exception as exc:
        logger.error(f"  ✗ Database initialization failed: {exc}")

    # Warm semantic memory FAISS index from DB
    try:
        from memory.semantic_memory import semantic_memory
        count = semantic_memory.warm_from_db(limit=5000)
        logger.info(f"  ✓ Semantic memory warmed ({count} vectors)")
    except Exception as exc:
        logger.warning(f"  ⚠ Semantic memory warm-up skipped: {exc}")

    # Pre-compile LangGraph
    try:
        from orchestration.graph import get_graph
        get_graph()
        logger.info("  ✓ LangGraph compiled")
    except Exception as exc:
        logger.warning(f"  ⚠ LangGraph pre-compilation failed: {exc}")

    yield

    logger.info("  Shutting down database connection...")
    close_database()
    logger.info("  ✓ Shutdown complete.")


app = FastAPI(
    title="EMAOS API Backend",
    description="Backend API for the Enterprise Multi-Agent AI Operating System",
    version="1.0.0",
    lifespan=lifespan,
)

# ─── Middleware & Error Handlers ─────────────────────────────────
app.add_middleware(RequestLoggingMiddleware)
register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Authentication Endpoints ─────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/token", response_model=TokenResponse, tags=["Authentication"])
async def login(req: LoginRequest):
    """Authenticate admin dashboard or client CLI."""
    if req.username == ADMIN_USERNAME and req.password == ADMIN_PASSWORD:
        access_token = create_access_token(
            data={"sub": req.username, "role": "admin"},
            expires_delta=timedelta(hours=24)
        )
        return TokenResponse(access_token=access_token, expires_in=86400)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ─── System Health & Metrics ─────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check():
    """Retrieve system microservices health reports."""
    db_healthy = await check_database_health()
    return {
        "status": "healthy" if db_healthy else "degraded",
        "database": "connected" if db_healthy else "disconnected",
        "version": "1.0.0"
    }


@app.get("/metrics", tags=["System"])
async def prometheus_metrics():
    """Endpoint for Prometheus metric collection scraping."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ─── Include API Routers ──────────────────────────────────────────
app.include_router(tasks.router)
app.include_router(agents.router)
app.include_router(reports.router)
