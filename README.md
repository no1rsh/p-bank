# BankDesk AI

가상 은행 고객 문의를 자동 분류하고 상담팀에 배정하는 교육용 프로젝트입니다. 직원이 검토하는 기능도 지원합니다. (가천대 P-실무프로젝트)

> ⚠️ 실제 은행 서비스가 아닙니다. 실제 비밀번호, 계좌번호, 주민등록번호는 입력하지 마세요.

기준 문서: `BankDesk AI 5인 공통 개발 기준서 v2.2` / 계약 `bankdesk_contract_v1` (팀 승인 대기)

## 현재 상태 (2026-11-12, 1번 작성)

| 모듈 | 담당 | 상태 |
|---|---|---|
| API 서버 (`app/main.py`, `app/api/`, `app/schemas/`, `app/services/`) | 1번 | 뼈대 완성, Mock 기준 테스트 16개 통과 |
| ML 예측 (`ml/`, `models/`) | 2번 | 2번 PC에서 확인됨. 저장소에는 아직 없음 |
| 라우팅 (`app/routing/`, `config/`) | 3번 | 아직 없음 → 1번 Mock 사용 중 |
| 웹 화면 (`web/`) | 4번 | 아직 없음 |
| DB (`app/db/`) | 5번 | 아직 없음 → 1번 메모리 Mock 사용 중 (재시작하면 데이터 사라짐) |

서버는 실제 모듈이 저장소에 들어오면 **자동으로 실제 모듈을 사용합니다**. 어떤 모듈이 연결됐는지는 `GET /api/health`에서 확인할 수 있습니다.

## 설치·실행

모든 명령은 프로젝트 루트에서 실행합니다.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   /  Mac·Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- API 문서(Swagger): http://127.0.0.1:8000/docs
- 상태 확인: http://127.0.0.1:8000/api/health
- OpenAPI 명세 파일: `docs/openapi.json` (4번 Mock 개발용)

## 테스트

```bash
pytest -q tests/api
```

## API 요약 (§8)

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/tickets` | 문의 접수 → 201 (모델 장애여도 201 REVIEW, DB 장애는 500) |
| GET | `/api/tickets` | 목록 (`work_status`, `routing_decision`, `assigned_team_code`, `review_pending`, `limit`, `offset`) |
| GET | `/api/tickets/{id}` | 상세 + `events` |
| PATCH | `/api/tickets/{id}/assignment` | 직원 수동 배정 `{assigned_team_code, reason}` |
| PATCH | `/api/tickets/{id}/status` | 상태 변경 `{work_status, reason}` (NEW→IN_PROGRESS→RESOLVED) |
| GET | `/api/teams` | 활성 팀 목록 `{items, total}` |

오류 형식: `{"error": {"code": "...", "message": "...", "details": ...}}`

## 데이터 출처

- 한국어 BANKING77 번역본: `neuralfoundry-coder/banking77-ko` (revision `9ac51f1f...`). 원본은 PolyAI BANKING77 (CC BY 4.0)입니다. 번역·정제·변형 사실은 2번이 정리합니다.
