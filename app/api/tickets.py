"""1번 소유: /api/tickets 엔드포인트 (§8.2)."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Query

from app.api.errors import error_json
from app.schemas import AssignmentRequest, ErrorResponse, StatusRequest, Ticket, TicketCreate, TicketDetail, TicketList
from app.services import ticket_service

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

_ERR = {422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}}


@router.post("", status_code=201, response_model=Ticket, responses=_ERR)
def create_ticket(body: TicketCreate):
    """고객 문의 접수. 모델 장애여도 DB 저장 성공이면 201(REVIEW). DB 실패는 500."""
    return ticket_service.create_ticket(body.content, body.source)


@router.get("", response_model=TicketList, responses=_ERR)
def list_tickets(
    work_status: Optional[Literal["NEW", "IN_PROGRESS", "RESOLVED"]] = None,
    routing_decision: Optional[Literal["AUTO", "REVIEW"]] = None,
    assigned_team_code: Optional[Literal["CARD", "TRANSFER", "PAYMENT", "ATM", "ACCOUNT"]] = None,
    review_pending: Optional[bool] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """목록. 정렬 created_at DESC, ticket_id DESC. review_pending=true → 최초 REVIEW + 현재 팀 null."""
    filters = {
        "work_status": work_status,
        "routing_decision": routing_decision,
        "assigned_team_code": assigned_team_code,
        "review_pending": review_pending,
        "limit": limit,
        "offset": offset,
    }
    items, total = ticket_service.list_tickets(filters)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{ticket_id}", response_model=TicketDetail, responses={404: {"model": ErrorResponse}, **_ERR})
def get_ticket(ticket_id: int):
    t = ticket_service.get_ticket(ticket_id)
    if t is None:
        return error_json(404, "TICKET_NOT_FOUND", "해당 문의를 찾을 수 없습니다.")
    return t


@router.patch("/{ticket_id}/assignment", response_model=Ticket,
              responses={404: {"model": ErrorResponse}, **_ERR})
def assign(ticket_id: int, body: AssignmentRequest):
    """직원 수동 배정. 최초 routing_decision은 바뀌지 않는다. 같은 팀이면 이벤트 없이 200."""
    return ticket_service.assign_ticket(ticket_id, body.assigned_team_code, body.reason)


@router.patch("/{ticket_id}/status", response_model=Ticket,
              responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, **_ERR})
def change_status(ticket_id: int, body: StatusRequest):
    """NEW→IN_PROGRESS→RESOLVED만 허용. 미배정 진행·역방향은 409. 같은 상태는 200(멱등)."""
    return ticket_service.change_status(ticket_id, body.work_status, body.reason)
