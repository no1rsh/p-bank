"""1번 소유: API 요청/응답 Pydantic 계약 (bankdesk_contract_v1, 기준서 v2.2 §7.4, §8)."""
from app.schemas.ticket import (  # noqa: F401
    AssignmentRequest,
    ErrorBody,
    ErrorResponse,
    Event,
    StatusRequest,
    Team,
    TeamList,
    Ticket,
    TicketCreate,
    TicketDetail,
    TicketList,
)
