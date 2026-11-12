"""1번 소유: FastAPI 시작점.

실행 (프로젝트 루트에서):
    uvicorn app.main:app --reload
문서: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import teams, tickets
from app.api.errors import register_error_handlers
from app.services import backends

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bankdesk")

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info("BankDesk 백엔드 연결 상태: %s", backends.USING)
    backends.repository.initialize_db()
    yield


app = FastAPI(
    title="BankDesk AI API",
    version="0.1.0",
    description="bankdesk_contract_v1 / 기준서 v2.2 (팀 승인 대기). 가상 은행 데모 — 실제 개인정보 입력 금지.",
    lifespan=lifespan,
)

# 4번 프론트 개발용 (로컬 개발 포트). 배포 범위는 Must 제외.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5500", "http://127.0.0.1:5500", "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)

register_error_handlers(app)
app.include_router(tickets.router)
app.include_router(teams.router)


@app.get("/api/health", tags=["meta"])
def health():
    """어떤 모듈이 실제/Mock으로 연결됐는지 확인 (통합 점검용)."""
    return {"status": "ok", "backends": backends.USING}


# 4번 web/ 폴더가 생기면 같은 서버에서 화면을 제공 (/ → web/index.html)
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
