"""Routes shared by both portals: who am I, demo users, health."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from wealth.api import queries
from wealth.api.deps import CurrentUser, current_user, demo_auth_allowed, get_conn

router = APIRouter(prefix="/api", tags=["common"])


@router.get("/health")
def health(conn=Depends(get_conn)):
    conn.execute("SELECT 1")
    return {"status": "ok"}


@router.get("/me")
def me(user: CurrentUser = Depends(current_user)):
    return {"kind": user.viewer.kind, "id": user.viewer.id, "name": user.name, "portal": user.portal}


@router.get("/demo/users")
def demo_users(conn=Depends(get_conn)):
    """The demo user picker. Exists only while the local demo login is enabled."""
    if not demo_auth_allowed():
        raise HTTPException(404, "Not found.")
    return {"users": queries.demo_users(conn, date.today())}
