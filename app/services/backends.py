"""1번 소유: 2·3·5번 모듈을 찾아 연결하는 곳.

실제 모듈이 저장소에 있으면 그것을 쓰고, 없으면 Mock으로 대체한다.
- 2번: ml.predictor (predict, load_model)
- 3번: app.routing.engine (build_routing_context, decide)
- 5번: app.db.repository (+ app.db.exceptions)

환경변수 BANKDESK_FORCE_MOCK=1 이면 3번·5번은 무조건 Mock을 사용한다(테스트용).
"""
from __future__ import annotations

import importlib
import logging
import os
from types import ModuleType
from typing import Any

from app.services import mock_backends

log = logging.getLogger("bankdesk.backends")


def _try_import(name: str) -> ModuleType | None:
    try:
        return importlib.import_module(name)
    except ImportError as e:
        log.warning("모듈 %s 를 찾지 못해 Mock/장애 경로를 사용합니다: %s", name, e)
        return None


_force_mock = os.getenv("BANKDESK_FORCE_MOCK") == "1"

routing: Any = (None if _force_mock else _try_import("app.routing.engine")) or mock_backends
repository: Any = (None if _force_mock else _try_import("app.db.repository")) or mock_backends
db_exceptions: Any = (None if _force_mock else _try_import("app.db.exceptions")) or mock_backends
predictor: Any = _try_import("ml.predictor")  # 없으면 None → MODEL_UNAVAILABLE

USING = {
    "routing": "mock" if routing is mock_backends else "real",
    "repository": "mock" if repository is mock_backends else "real",
    "predictor": "missing" if predictor is None else "real",
}
