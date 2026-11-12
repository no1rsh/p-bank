"""1번 소유: 3번(라우팅)·5번(DB)이 준비되기 전까지 쓰는 임시 Mock.

- 함수 이름·인자·반환 형식은 기준서 v2.2 §7.2, §7.3, §9.1과 똑같이 맞췄다.
- 3번 `app/routing/engine.py`, 5번 `app/db/repository.py`가 저장소에 들어오면
  `app/services/backends.py`가 자동으로 실제 모듈을 사용한다. 이 파일은 그때 삭제한다.
- Mock 라우터는 안전 기본값(auto_routing_enabled=false)만 흉내 낸다.
  즉 AUTO는 절대 나오지 않는다. 진짜 정책 판단은 3번이 구현한다.
- Mock DB는 메모리에만 저장하므로 서버를 재시작하면 데이터가 사라진다.
"""
from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Any


# ------------------------------------------------------------------
# 5번 예외 계약(§9.1)과 같은 이름. 실제 app/db/exceptions.py가 생기면 그쪽을 사용.
# ------------------------------------------------------------------
class TicketNotFound(Exception):
    pass


class InvalidTeam(Exception):
    pass


class InvalidStatus(Exception):
    pass


class InvalidTransition(Exception):
    pass


class StorageFailure(Exception):
    pass


# ------------------------------------------------------------------
# 공통 상수 (§3, §8.2.1)
# ------------------------------------------------------------------
TEAMS: list[dict[str, Any]] = [
    {"code": "CARD", "display_name": "카드 상담팀", "description": "카드 관련 문의", "enabled": True},
    {"code": "TRANSFER", "display_name": "이체·송금팀", "description": "이체 및 송금 문의", "enabled": True},
    {"code": "PAYMENT", "display_name": "결제·환불팀", "description": "결제 및 환불 문의", "enabled": True},
    {"code": "ATM", "display_name": "ATM·현금팀", "description": "현금 인출 관련 문의", "enabled": True},
    {"code": "ACCOUNT", "display_name": "계정·인증팀", "description": "계정 및 인증 문의", "enabled": True},
]

INTENT_TO_TEAM: dict[str, str] = {
    "lost_or_stolen_card": "CARD",
    "card_not_working": "CARD",
    "card_arrival": "CARD",
    "activate_my_card": "CARD",
    "failed_transfer": "TRANSFER",
    "pending_transfer": "TRANSFER",
    "transfer_not_received_by_recipient": "TRANSFER",
    "cancel_transfer": "TRANSFER",
    "transaction_charged_twice": "PAYMENT",
    "request_refund": "PAYMENT",
    "Refund_not_showing_up": "PAYMENT",
    "declined_card_payment": "PAYMENT",
    "declined_cash_withdrawal": "ATM",
    "cash_withdrawal_not_recognised": "ATM",
    "wrong_amount_of_cash_received": "ATM",
    "cash_withdrawal_charge": "ATM",
    "passcode_forgotten": "ACCOUNT",
    "pin_blocked": "ACCOUNT",
    "unable_to_verify_identity": "ACCOUNT",
    "verify_my_identity": "ACCOUNT",
}

WORK_STATUSES = ("NEW", "IN_PROGRESS", "RESOLVED")
_NEXT_STATUS = {"NEW": "IN_PROGRESS", "IN_PROGRESS": "RESOLVED"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------
# 3번 Mock: build_routing_context / decide  (§7.2, §7.3)
# ------------------------------------------------------------------
def build_routing_context(
    model_info: dict | None,
    model_labels: list[str] | None,
    db_mapping_snapshot: dict,
    model_available: bool,
) -> dict:
    issues: list[str] = []
    if db_mapping_snapshot.get("intent_to_team") != INTENT_TO_TEAM:
        issues.append("DB_MAPPING_MISMATCH")
    if model_available and model_labels is not None and sorted(model_labels) != sorted(INTENT_TO_TEAM):
        issues.append("MODEL_LABEL_MISMATCH")
    return {
        "compatibility_ok": not issues,
        "issues": issues,
        "policy_version": "routing_draft_v1",
        "mapping_version": "mapping_v1",
        "expected_model_version": "tfidf_lr_v1",
        "expected_label_schema_version": "bankdesk20_draft_v1",
        "expected_score_type": "predict_proba_uncalibrated",
        "auto_routing_enabled": False,
        "auto_threshold": None,
        "intent_to_team": dict(INTENT_TO_TEAM),
        "disabled_intents": [],
    }


def decide(prediction: dict | None, model_error: str | None, routing_context: dict) -> dict:
    """안전 기본 정책만 흉내 낸다. 반환 키는 정확히 5개 (§7.2)."""
    ctx = routing_context or {}
    policy_version = ctx.get("policy_version", "routing_safe_fallback_v1")
    mapping_version = ctx.get("mapping_version", "mapping_unavailable")

    def review(reason: str) -> dict:
        return {
            "routing_decision": "REVIEW",
            "assigned_team_code": None,
            "routing_reason": reason,
            "policy_version": policy_version,
            "mapping_version": mapping_version,
        }

    if not ctx or not ctx.get("compatibility_ok"):
        return review("CONFIG_MISMATCH")
    if model_error is not None or prediction is None:
        return review("MODEL_UNAVAILABLE")
    if not ctx.get("auto_routing_enabled"):
        return review("POLICY_REVIEW")
    # Mock은 AUTO를 켜지 않는다. 여기 도달하면 설정 오류로 본다.
    return review("CONFIG_MISMATCH")


# ------------------------------------------------------------------
# 5번 Mock: repository 함수 (§9.1)
# ------------------------------------------------------------------
class _MemoryStore:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.tickets: dict[int, dict] = {}
        self.events: dict[int, list[dict]] = {}
        self.next_ticket_id = 1
        self.next_event_id = 1
        self.fail_storage = False  # 테스트용: True면 모든 DB 함수가 StorageFailure


_store = _MemoryStore()


def _check_storage() -> None:
    if _store.fail_storage:
        raise StorageFailure("mock storage failure")


def _add_event(ticket_id: int, action: str, actor: str, old: dict | None, new: dict | None,
               reason: str | None, at: str) -> None:
    _store.events.setdefault(ticket_id, []).append({
        "event_id": _store.next_event_id,
        "action": action,
        "actor": actor,
        "old_value": old,
        "new_value": new,
        "reason": reason,
        "created_at": at,
    })
    _store.next_event_id += 1


def initialize_db() -> None:
    _check_storage()


def get_mapping_snapshot() -> dict:
    _check_storage()
    return {"mapping_version": "mapping_v1", "intent_to_team": dict(INTENT_TO_TEAM), "disabled_intents": []}


def list_teams(active_only: bool = True) -> list[dict]:
    _check_storage()
    return [dict(t) for t in TEAMS if t["enabled"] or not active_only]


def create_ticket_with_events(payload: dict) -> dict:
    _check_storage()
    with _store.lock:
        now = _now()
        tid = _store.next_ticket_id
        _store.next_ticket_id += 1
        ticket = {"ticket_id": tid, **payload, "created_at": now, "updated_at": now}
        _store.tickets[tid] = ticket
        _add_event(tid, "CREATED", "system", None, {"work_status": payload["work_status"]}, None, now)
        routing_keys = ("predicted_intent", "prediction_score", "score_type", "model_version",
                        "label_schema_version", "routing_decision", "routing_reason",
                        "policy_version", "mapping_version", "assigned_team_code")
        _add_event(tid, "ROUTING_DECIDED", "system", None, {k: payload[k] for k in routing_keys}, None, now)
        return copy.deepcopy(ticket)


def list_tickets(filters: dict) -> tuple[list[dict], int]:
    _check_storage()
    rows = list(_store.tickets.values())
    for key in ("work_status", "routing_decision", "assigned_team_code"):
        if filters.get(key) is not None:
            rows = [r for r in rows if r[key] == filters[key]]
    rp = filters.get("review_pending")
    if rp is True:
        rows = [r for r in rows if r["routing_decision"] == "REVIEW" and r["assigned_team_code"] is None]
    elif rp is False:
        rows = [r for r in rows if not (r["routing_decision"] == "REVIEW" and r["assigned_team_code"] is None)]
    rows.sort(key=lambda r: (r["created_at"], r["ticket_id"]), reverse=True)
    total = len(rows)
    offset, limit = filters.get("offset", 0), filters.get("limit", 20)
    return copy.deepcopy(rows[offset:offset + limit]), total


def get_ticket(ticket_id: int, include_events: bool = False) -> dict | None:
    _check_storage()
    t = _store.tickets.get(ticket_id)
    if t is None:
        return None
    out = copy.deepcopy(t)
    if include_events:
        out["events"] = sorted(copy.deepcopy(_store.events.get(ticket_id, [])), key=lambda e: e["event_id"])
    return out


def assign_ticket(ticket_id: int, team_code: str, reason: str, actor: str = "demo_staff") -> dict:
    _check_storage()
    with _store.lock:
        t = _store.tickets.get(ticket_id)
        if t is None:
            raise TicketNotFound(ticket_id)
        if team_code not in {x["code"] for x in TEAMS if x["enabled"]}:
            raise InvalidTeam(team_code)
        if t["assigned_team_code"] != team_code:  # 같은 팀이면 멱등(이벤트 없음)
            now = _now()
            old = t["assigned_team_code"]
            t["assigned_team_code"] = team_code
            t["updated_at"] = now
            _add_event(ticket_id, "ASSIGNMENT_CHANGED", actor, {"assigned_team_code": old},
                       {"assigned_team_code": team_code}, reason, now)
        return copy.deepcopy(t)


def change_status(ticket_id: int, new_status: str, reason: str, actor: str = "demo_staff") -> dict:
    _check_storage()
    with _store.lock:
        t = _store.tickets.get(ticket_id)
        if t is None:
            raise TicketNotFound(ticket_id)
        if new_status not in WORK_STATUSES:
            raise InvalidStatus(new_status)
        cur = t["work_status"]
        if new_status == cur:  # 멱등
            return copy.deepcopy(t)
        if _NEXT_STATUS.get(cur) != new_status:
            raise InvalidTransition(f"{cur}->{new_status}")
        if t["assigned_team_code"] is None:
            raise InvalidTransition("unassigned ticket cannot progress")
        now = _now()
        t["work_status"] = new_status
        t["updated_at"] = now
        _add_event(ticket_id, "STATUS_CHANGED", actor, {"work_status": cur}, {"work_status": new_status}, reason, now)
        return copy.deepcopy(t)


def _reset_for_tests() -> None:
    _store.reset()


def _set_storage_failure(flag: bool) -> None:
    _store.fail_storage = flag
