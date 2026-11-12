"""1번 소유: /api/teams (§8.2.1). 반드시 {items, total} 객체로 반환."""
from __future__ import annotations

from fastapi import APIRouter

from app.schemas import ErrorResponse, TeamList
from app.services import ticket_service

router = APIRouter(prefix="/api/teams", tags=["teams"])

TEAM_ORDER = ["CARD", "TRANSFER", "PAYMENT", "ATM", "ACCOUNT"]


@router.get("", response_model=TeamList, responses={500: {"model": ErrorResponse}})
def list_teams():
    teams = [t for t in ticket_service.list_teams() if t.get("enabled")]
    teams.sort(key=lambda t: TEAM_ORDER.index(t["code"]) if t["code"] in TEAM_ORDER else 99)
    return {"items": teams, "total": len(teams)}
