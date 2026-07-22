"""
EMAOS — Reports API Routes
"""
import json
import os
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from auth.jwt_handler import TokenData, get_current_user

router = APIRouter(prefix="/reports", tags=["Reports"])

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://emaos:emaos_secret@localhost:5432/emaos")


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


@router.get("/", response_model=List[Dict[str, Any]])
async def list_reports(
    limit: int = Query(20, ge=1, le=100),
    project_id: Optional[str] = Query(None),
    current_user: TokenData = Depends(get_current_user),
):
    """List generated reports."""
    try:
        if project_id:
            sql = "SELECT id, task_id, title, format, created_at FROM reports WHERE project_id = %s ORDER BY created_at DESC LIMIT %s"
            params = (project_id, limit)
        else:
            sql = "SELECT id, task_id, title, format, created_at FROM reports ORDER BY created_at DESC LIMIT %s"
            params = (limit,)
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{report_id}", response_model=Dict[str, Any])
async def get_report(
    report_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    """Get a full report by ID."""
    try:
        sql = "SELECT * FROM reports WHERE id = %s"
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (report_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Report not found")
                return dict(row)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{report_id}/raw", response_class=PlainTextResponse)
async def get_raw_report(
    report_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    """Get the raw markdown string of a report for easy reading/downloading."""
    try:
        sql = "SELECT content FROM reports WHERE id = %s"
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (report_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Report not found")
                return row[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
