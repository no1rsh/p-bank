"""1번 소유: Ticket/Team/Event/오류 스키마.

필드 이름·타입은 기준서 v2.2 §8.1, §8.2.1, §8.3, §8.4와 똑같이 맞춘다.
임의로 필드를 추가하거나 이름을 바꾸지 않는다.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

TeamCode = Literal["CARD", "TRANSFER", "PAYMENT", "ATM", "ACCOUNT"]
WorkStatus = Literal["NEW", "IN_PROGRESS", "RESOLVED"]
RoutingDecision = Literal["AUTO", "REVIEW"]
RoutingReason = Literal[
    "AUTO_POLICY_PASS",
    "LOW_SCORE",
    "UNMAPPED_INTENT",
    "POLICY_REVIEW",
    "MODEL_UNAVAILABLE",
    "CONFIG_MISMATCH",
]
EventAction = Literal["CREATED", "ROUTING_DECIDED", "ASSIGNMENT_CHANGED", "STATUS_CHANGED"]

CONTENT_MAX = 2000
REASON_MAX = 500


# ---------- 요청 ----------
class TicketCreate(BaseModel):
    """POST /api/tickets 요청 (§7.4)."""

    model_config = ConfigDict(extra="forbid")

    content: str
    source: Literal["web"] = "web"

    @field_validator("content", mode="before")
    @classmethod
    def _content_must_be_str(cls, v: Any) -> Any:
        if not isinstance(v, str):
            raise ValueError("content는 문자열이어야 합니다.")
        return v

    @field_validator("content")
    @classmethod
    def _content_length(cls, v: str) -> str:
        v = v.strip()
        if not (1 <= len(v) <= CONTENT_MAX):
            raise ValueError(f"content는 공백 제외 1~{CONTENT_MAX}자여야 합니다.")
        return v


def _check_reason(v: Any) -> str:
    if not isinstance(v, str):
        raise ValueError("reason은 문자열이어야 합니다.")
    v = v.strip()
    if not (1 <= len(v) <= REASON_MAX):
        raise ValueError(f"reason은 공백 제외 1~{REASON_MAX}자여야 합니다.")
    return v


class AssignmentRequest(BaseModel):
    """PATCH /api/tickets/{id}/assignment 요청.

    팀 코드는 문자열로 받고, 유효성은 서비스/DB 계층에서 검사해
    INVALID_TEAM(422)로 응답한다 (소문자 자동 변환 금지, §9).
    """

    model_config = ConfigDict(extra="forbid")

    assigned_team_code: str
    reason: str

    @field_validator("reason", mode="before")
    @classmethod
    def _reason(cls, v: Any) -> str:
        return _check_reason(v)


class StatusRequest(BaseModel):
    """PATCH /api/tickets/{id}/status 요청. 잘못된 상태 문자열은 INVALID_STATUS(422)."""

    model_config = ConfigDict(extra="forbid")

    work_status: str
    reason: str

    @field_validator("reason", mode="before")
    @classmethod
    def _reason(cls, v: Any) -> str:
        return _check_reason(v)


# ---------- 응답 ----------
class Ticket(BaseModel):
    """공통 Ticket 응답 (§8.1)."""

    ticket_id: int
    content: str
    source: str
    created_at: str
    updated_at: str
    predicted_intent: Optional[str] = None
    prediction_score: Optional[float] = Field(default=None, ge=0, le=1)
    score_type: Optional[str] = None
    model_version: Optional[str] = None
    label_schema_version: Optional[str] = None
    routing_decision: RoutingDecision
    routing_reason: RoutingReason
    policy_version: str
    mapping_version: str
    assigned_team_code: Optional[TeamCode] = None
    work_status: WorkStatus


class Event(BaseModel):
    """ticket_events 한 건 (§8.3). old/new는 JSON object 또는 null만."""

    event_id: int
    action: EventAction
    actor: str
    old_value: Optional[dict[str, Any]] = None
    new_value: Optional[dict[str, Any]] = None
    reason: Optional[str] = None
    created_at: str


class TicketDetail(Ticket):
    events: list[Event]


class TicketList(BaseModel):
    items: list[Ticket]
    total: int
    limit: int
    offset: int


class Team(BaseModel):
    code: TeamCode
    display_name: str
    description: str
    enabled: bool


class TeamList(BaseModel):
    """GET /api/teams 응답 (§8.2.1). 배열 단독 반환 금지."""

    items: list[Team]
    total: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ErrorResponse(BaseModel):
    """공통 오류 응답 (§8.4)."""

    error: ErrorBody
