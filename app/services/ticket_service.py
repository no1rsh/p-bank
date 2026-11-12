"""1번 소유: 접수 오케스트레이션 (기준서 v2.2 §2, §7.3, §9.1).

순서: 입력 검증(스키마) → DB 매핑 스냅샷 → build_routing_context → predict → decide
      → create_ticket_with_events (5번 단일 트랜잭션) → 응답

규칙
- 모델 오류: 접수는 성공시키고 REVIEW/MODEL_UNAVAILABLE (3번 decide가 결정)
- DB 오류: 절대 성공 응답 금지 → StorageFailure 그대로 올려 500
- 1번은 SQL/commit, 임계값 판단, 모델 재학습을 하지 않는다.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services import backends

log = logging.getLogger("bankdesk.ticket_service")

PREDICTION_FIELDS = ("predicted_intent", "prediction_score", "score_type", "model_version", "label_schema_version")

_model_cache: dict[str, Any] = {"loaded": False}


def reset_model_cache() -> None:
    """모델/설정 교체 시 호출해 다시 확인하게 한다 (§7.3 캐시 무효화)."""
    _model_cache.clear()
    _model_cache["loaded"] = False


def _load_model_state() -> tuple[dict | None, list[str] | None, str | None]:
    """(model_info, model_labels, model_error) 반환. 2번 load_model() 사용."""
    if _model_cache.get("loaded"):
        return _model_cache["info"], _model_cache["labels"], _model_cache["error"]

    info = labels = error = None
    pred = backends.predictor
    if pred is None or not hasattr(pred, "predict"):
        error = "MODEL_MODULE_MISSING"
    else:
        try:
            if hasattr(pred, "load_model"):
                loaded = pred.load_model()
                model, info = loaded[0], loaded[1]
                classes = getattr(model, "classes_", None)
                labels = [str(c) for c in classes] if classes is not None else None
        except Exception as e:  # 파일 누락/로드 실패
            log.exception("모델 로드 실패")
            error = f"MODEL_LOAD_FAILED:{type(e).__name__}"

    _model_cache.update(loaded=True, info=info, labels=labels, error=error)
    return info, labels, error


def _run_predict(content: str) -> tuple[dict | None, str | None]:
    try:
        return backends.predictor.predict(content, top_k=3), None
    except Exception as e:
        log.exception("predict() 실패")
        return None, f"PREDICT_FAILED:{type(e).__name__}"


def create_ticket(content: str, source: str = "web") -> dict:
    repo = backends.repository
    routing = backends.routing

    # (A) DB 스냅샷 — 실패하면 StorageFailure가 그대로 올라가 500
    snapshot = repo.get_mapping_snapshot()

    # (B) 모델 상태
    model_info, model_labels, model_error = _load_model_state()

    # (C) 3번 context
    context = routing.build_routing_context(model_info, model_labels, snapshot, model_error is None)

    # (D) 예측 + 결정
    prediction = None
    if model_error is None:
        prediction, model_error = _run_predict(content)
    decision = routing.decide(prediction, model_error, context)

    # 2번 키(intent_label/score) → API 키(predicted_intent/prediction_score) 명시적 변환 (§12.3)
    if prediction is not None and model_error is None:
        pred_fields = {
            "predicted_intent": prediction.get("intent_label"),
            "prediction_score": prediction.get("score"),
            "score_type": prediction.get("score_type"),
            "model_version": prediction.get("model_version"),
            "label_schema_version": prediction.get("label_schema_version"),
        }
    else:
        pred_fields = {k: None for k in PREDICTION_FIELDS}

    if model_error or (context and context.get("issues")):
        log.warning("접수 진단 model_error=%s issues=%s reason=%s",
                    model_error, (context or {}).get("issues"), decision.get("routing_reason"))

    payload = {
        "content": content,
        "source": source,
        **pred_fields,
        "routing_decision": decision["routing_decision"],
        "routing_reason": decision["routing_reason"],
        "policy_version": decision["policy_version"],
        "mapping_version": decision["mapping_version"],
        "assigned_team_code": decision["assigned_team_code"],
        "work_status": "NEW",
    }
    # (E) 5번 단일 트랜잭션
    return repo.create_ticket_with_events(payload)


def list_tickets(filters: dict) -> tuple[list[dict], int]:
    return backends.repository.list_tickets(filters)


def get_ticket(ticket_id: int) -> dict | None:
    return backends.repository.get_ticket(ticket_id, include_events=True)


def assign_ticket(ticket_id: int, team_code: str, reason: str) -> dict:
    return backends.repository.assign_ticket(ticket_id, team_code, reason, actor="demo_staff")


def change_status(ticket_id: int, new_status: str, reason: str) -> dict:
    return backends.repository.change_status(ticket_id, new_status, reason, actor="demo_staff")


def list_teams() -> list[dict]:
    return backends.repository.list_teams(active_only=True)
