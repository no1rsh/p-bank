"""1번 API 계약 테스트 (Mock 백엔드 기준).

실행: 프로젝트 루트에서  BANKDESK_FORCE_MOCK=1 pytest -q tests/api
기준서 v2.2 §8, §10.1 의 T01, T03, T04, T06, T07, T08(모델 없음), T09, T10, T11, CT06, CT08 일부를 다룬다.
※ Mock DB/라우터 기준이므로 실제 2·3·5번 통합 테스트를 대신하지 않는다.
"""
import os

os.environ["BANKDESK_FORCE_MOCK"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import backends, mock_backends, ticket_service  # noqa: E402

TICKET_KEYS = {
    "ticket_id", "content", "source", "created_at", "updated_at", "predicted_intent", "prediction_score",
    "score_type", "model_version", "label_schema_version", "routing_decision", "routing_reason",
    "policy_version", "mapping_version", "assigned_team_code", "work_status",
}


class FakePredictor:
    """2번 predict() 반환 형식을 흉내 낸 가짜 (§7.1). 실제 점수가 아니다."""

    class _M:
        classes_ = list(mock_backends.INTENT_TO_TEAM)

    @staticmethod
    def load_model():
        return FakePredictor._M(), {"model_version": "tfidf_lr_v1"}

    @staticmethod
    def predict(text, top_k=3):
        return {
            "intent_label": "lost_or_stolen_card",
            "score": 0.42,
            "score_type": "predict_proba_uncalibrated",
            "top_k": [{"intent_label": "lost_or_stolen_card", "score": 0.42}],
            "model_version": "tfidf_lr_v1",
            "label_schema_version": "bankdesk20_draft_v1",
        }


class BrokenPredictor(FakePredictor):
    @staticmethod
    def predict(text, top_k=3):
        raise RuntimeError("boom")


@pytest.fixture
def client(monkeypatch):
    mock_backends._reset_for_tests()
    mock_backends._set_storage_failure(False)
    ticket_service.reset_model_cache()
    monkeypatch.setattr(backends, "predictor", FakePredictor)
    with TestClient(app) as c:
        yield c
    ticket_service.reset_model_cache()


def _post(c, text="카드를 잃어버렸어요."):
    return c.post("/api/tickets", json={"content": text, "source": "web"})


# T01 + CT08
def test_create_ticket_201_and_two_initial_events(client):
    r = _post(client)
    assert r.status_code == 201
    t = r.json()
    assert set(t) == TICKET_KEYS
    assert t["work_status"] == "NEW"
    assert t["created_at"].endswith("Z")
    # 2번 키 → API 키 변환 확인
    assert t["predicted_intent"] == "lost_or_stolen_card"
    assert t["prediction_score"] == 0.42
    # 안전 기본 정책: AUTO 꺼짐 → REVIEW/POLICY_REVIEW
    assert t["routing_decision"] == "REVIEW" and t["routing_reason"] == "POLICY_REVIEW"
    assert t["assigned_team_code"] is None

    d = client.get(f"/api/tickets/{t['ticket_id']}").json()
    assert [e["action"] for e in d["events"]] == ["CREATED", "ROUTING_DECIDED"]
    assert d["events"][0]["old_value"] is None and isinstance(d["events"][1]["new_value"], dict)


# T08: 예측 예외 → 201 REVIEW/MODEL_UNAVAILABLE, 예측 필드 null
def test_model_failure_still_201_review(client, monkeypatch):
    monkeypatch.setattr(backends, "predictor", BrokenPredictor)
    ticket_service.reset_model_cache()
    r = _post(client)
    assert r.status_code == 201
    t = r.json()
    assert t["routing_reason"] == "MODEL_UNAVAILABLE"
    assert all(t[k] is None for k in ticket_service.PREDICTION_FIELDS)


def test_model_module_missing_still_201_review(client, monkeypatch):
    monkeypatch.setattr(backends, "predictor", None)
    ticket_service.reset_model_cache()
    r = _post(client)
    assert r.status_code == 201 and r.json()["routing_reason"] == "MODEL_UNAVAILABLE"


# T09: DB 실패 → 500, 성공 위장 금지
def test_storage_failure_returns_500(client):
    mock_backends._set_storage_failure(True)
    r = _post(client)
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "STORAGE_FAILURE"


# T10
@pytest.mark.parametrize("body", [
    {"content": "   "},
    {"content": "가" * 2001},
    {"content": 123},
    {"content": ["a"]},
    {},
    {"content": "ok", "source": "email"},
])
def test_invalid_input_422_and_nothing_saved(client, body):
    r = client.post("/api/tickets", json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_INPUT"
    assert client.get("/api/tickets").json()["total"] == 0


# T03 + T04: REVIEW 대기 목록 → 수동 배정 후 빠짐, 최초 REVIEW 보존
def test_review_pending_then_manual_assign(client):
    tid = _post(client).json()["ticket_id"]
    assert client.get("/api/tickets?review_pending=true").json()["total"] == 1

    r = client.patch(f"/api/tickets/{tid}/assignment", json={"assigned_team_code": "CARD", "reason": "직원 확인"})
    assert r.status_code == 200
    t = r.json()
    assert t["assigned_team_code"] == "CARD" and t["routing_decision"] == "REVIEW"
    assert client.get("/api/tickets?review_pending=true").json()["total"] == 0

    # 같은 팀 재요청은 멱등 → 이벤트 추가 없음
    client.patch(f"/api/tickets/{tid}/assignment", json={"assigned_team_code": "CARD", "reason": "재확인"})
    ev = client.get(f"/api/tickets/{tid}").json()["events"]
    assert [e["action"] for e in ev] == ["CREATED", "ROUTING_DECIDED", "ASSIGNMENT_CHANGED"]
    assert ev[2]["old_value"] == {"assigned_team_code": None}
    assert ev[2]["actor"] == "demo_staff"


# T07: 미배정 진행 → 409
def test_unassigned_cannot_progress(client):
    tid = _post(client).json()["ticket_id"]
    r = client.patch(f"/api/tickets/{tid}/status", json={"work_status": "IN_PROGRESS", "reason": "시작"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert client.get(f"/api/tickets/{tid}").json()["work_status"] == "NEW"


# T06: 정상 전이, 역방향 409, 같은 상태 멱등
def test_status_flow(client):
    tid = _post(client).json()["ticket_id"]
    client.patch(f"/api/tickets/{tid}/assignment", json={"assigned_team_code": "ATM", "reason": "배정"})
    for s in ("IN_PROGRESS", "RESOLVED"):
        r = client.patch(f"/api/tickets/{tid}/status", json={"work_status": s, "reason": "진행"})
        assert r.status_code == 200 and r.json()["work_status"] == s
    assert client.patch(f"/api/tickets/{tid}/status",
                        json={"work_status": "RESOLVED", "reason": "중복"}).status_code == 200
    assert client.patch(f"/api/tickets/{tid}/status",
                        json={"work_status": "NEW", "reason": "되돌림"}).status_code == 409
    actions = [e["action"] for e in client.get(f"/api/tickets/{tid}").json()["events"]]
    assert actions.count("STATUS_CHANGED") == 2


# T11
def test_invalid_team_and_missing_ticket(client):
    tid = _post(client).json()["ticket_id"]
    r = client.patch(f"/api/tickets/{tid}/assignment", json={"assigned_team_code": "card", "reason": "소문자"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_TEAM"
    r = client.patch(f"/api/tickets/{tid}/status", json={"work_status": "DONE", "reason": "x"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_STATUS"
    assert client.get("/api/tickets/9999").json()["error"]["code"] == "TICKET_NOT_FOUND"
    r = client.patch("/api/tickets/9999/assignment", json={"assigned_team_code": "CARD", "reason": "x"})
    assert r.status_code == 404
    r = client.patch(f"/api/tickets/{tid}/assignment", json={"assigned_team_code": "CARD", "reason": "  "})
    assert r.status_code == 422


# CT06
def test_teams_shape_and_order(client):
    body = client.get("/api/teams").json()
    assert set(body) == {"items", "total"} and body["total"] == 5
    assert [t["code"] for t in body["items"]] == ["CARD", "TRANSFER", "PAYMENT", "ATM", "ACCOUNT"]


def test_list_filters_pagination_and_order(client):
    ids = [_post(client, f"문의 {i}").json()["ticket_id"] for i in range(3)]
    body = client.get("/api/tickets?limit=2&offset=0").json()
    assert body["total"] == 3 and body["limit"] == 2 and len(body["items"]) == 2
    assert body["items"][0]["ticket_id"] == ids[-1]  # 최신순
    assert client.get("/api/tickets?limit=0").status_code == 422
    assert client.get("/api/tickets?work_status=DONE").status_code == 422
