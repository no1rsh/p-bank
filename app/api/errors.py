"""1번 소유: 공통 오류 응답 통일 (§8.4).

모든 오류는 {"error": {"code", "message", "details"}} 형식.
5번 예외는 클래스 이름으로 매핑하므로 Mock/실제 DB 어느 쪽이든 동일하게 동작한다.
스택 트레이스·SQL 내용은 응답에 노출하지 않는다.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("bankdesk.errors")

# 예외 클래스 이름 → (HTTP, code, 사용자 메시지)
DB_EXCEPTION_MAP: dict[str, tuple[int, str, str]] = {
    "TicketNotFound": (404, "TICKET_NOT_FOUND", "해당 문의를 찾을 수 없습니다."),
    "InvalidTeam": (422, "INVALID_TEAM", "유효하지 않은 상담팀 코드입니다."),
    "InvalidStatus": (422, "INVALID_STATUS", "유효하지 않은 처리 상태입니다."),
    "InvalidTransition": (409, "INVALID_STATUS_TRANSITION", "허용되지 않는 상태 변경입니다."),
    "StorageFailure": (500, "STORAGE_FAILURE", "저장 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."),
}


def error_json(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details}})


def _validation_details(exc: RequestValidationError) -> list[dict]:
    out = []
    for e in exc.errors():
        out.append({"loc": [str(x) for x in e.get("loc", [])], "msg": e.get("msg", "")})
    return out


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return error_json(422, "INVALID_INPUT", "입력 내용을 확인해 주세요.", _validation_details(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return error_json(exc.status_code, code, str(exc.detail))

    # 5번 예외 클래스마다 핸들러 등록 (Mock 또는 실제 app.db.exceptions)
    from app.services import backends

    async def _db_exc(_: Request, exc: Exception):
        status, code, msg = DB_EXCEPTION_MAP[type(exc).__name__]
        if status >= 500:
            log.error("저장 실패: %s", type(exc).__name__)
        return error_json(status, code, msg)

    for name in DB_EXCEPTION_MAP:
        cls = getattr(backends.db_exceptions, name, None)
        if isinstance(cls, type) and issubclass(cls, Exception):
            app.add_exception_handler(cls, _db_exc)

    @app.exception_handler(Exception)
    async def _any(_: Request, exc: Exception):
        mapped = DB_EXCEPTION_MAP.get(type(exc).__name__)
        if mapped:
            status, code, msg = mapped
            if status >= 500:
                log.exception("저장 실패")
            return error_json(status, code, msg)
        log.exception("처리되지 않은 서버 오류")
        return error_json(500, "STORAGE_FAILURE", "서버 오류가 발생했습니다.")
