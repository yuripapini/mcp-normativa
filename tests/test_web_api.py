"""Test delle API della web app (/api/ask, /api/verifica)."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import LLMResult
from app.main import create_app
from app.telegram_bot import LexBot
from tests.test_telegram_handler import FakeMCP, FakeProvider, FakeSession, tool_round

CODE = "codice-di-prova"
ORIGIN = "https://lexbot-web.onrender.com"

SOURCE = {
    "law_id": "1990-08-18:090G0294",
    "descrizione_atto": "LEGGE 7 agosto 1990, n. 241",
    "url_normattiva": "https://www.normattiva.it/eli/id/1990/08/18/090G0294/CONSOLIDATED",
    "urn": "urn:nir:stato:legge:1990-08-07;241",
    "data_consultazione": "2026-11-20T10:00:00+00:00",
}
VIGENCE = {"stato": "vigente", "stato_verificato": True}


def make_client(
    *,
    code: str = CODE,
    origin: str = ORIGIN,
    rate_limit: int = 10,
    provider: FakeProvider | None = None,
    session: FakeSession | None = None,
) -> TestClient:
    settings = Settings(
        runtime_env="test",
        web_access_code=code,
        web_allowed_origin=origin,
        rate_limit_max_requests=rate_limit,
    )
    bot = LexBot(
        settings,
        mcp=FakeMCP(session),
        provider_factory=lambda: provider or FakeProvider([LLMResult(content="Risposta.")]),
    )
    return TestClient(create_app(settings, processor=_noop, web_bot=bot))


async def _noop(_: dict[str, Any]) -> None:
    return None


def _headers(code: str | None = CODE) -> dict[str, str]:
    return {"X-Access-Code": code} if code is not None else {}


def test_web_disabled_without_code():
    with make_client(code="") as tc:
        r = tc.post("/api/ask", json={"question": "Art. 186 codice della strada"}, headers=_headers())
    assert r.status_code == 403


def test_missing_or_wrong_code_is_401():
    with make_client() as tc:
        assert tc.post("/api/ask", json={"question": "domanda"}, headers=_headers(None)).status_code == 401
        assert tc.post("/api/ask", json={"question": "domanda"}, headers=_headers("no")).status_code == 401
        assert tc.post("/api/verifica", json={"law_id": "legge 241/1990"}).status_code == 401


def test_accesso_checks_code_only():
    with make_client() as tc:
        assert tc.post("/api/accesso", headers=_headers()).json() == {"ok": True}
        assert tc.post("/api/accesso", headers=_headers("sbagliato")).status_code == 401


def test_ask_returns_text_and_safe_html():
    provider = FakeProvider([tool_round(), LLMResult(content="**Art. 1** <script>x</script>")])
    with make_client(provider=provider) as tc:
        r = tc.post("/api/ask", json={"question": "Art. 1 legge 241/1990"}, headers=_headers())
    assert r.status_code == 200
    body = r.json()
    assert "Art. 1" in body["text"]
    assert "normattiva.it" in body["text"]
    assert "<b>Art. 1</b>" in body["html"]
    assert "<script>" not in body["html"]


def test_verifica_returns_formatted_answer():
    session = FakeSession(
        {"get_official_source": json.dumps(SOURCE), "check_law_vigence": json.dumps(VIGENCE)}
    )
    with make_client(session=session) as tc:
        r = tc.post("/api/verifica", json={"law_id": "legge 241/1990"}, headers=_headers())
    assert r.status_code == 200
    body = r.json()
    assert "LEGGE 7 agosto 1990, n. 241" in body["text"]
    assert '<a href="https://www.normattiva.it/eli/id/1990/08/18/090G0294/CONSOLIDATED">' in body["html"]


def test_invalid_body_is_422():
    with make_client() as tc:
        assert tc.post("/api/ask", json={}, headers=_headers()).status_code == 422
        assert tc.post("/api/verifica", json={"law_id": "  "}, headers=_headers()).status_code == 422


def test_rate_limit_is_429():
    provider = FakeProvider([LLMResult(content="Uno."), LLMResult(content="Due.")])
    with make_client(rate_limit=1, provider=provider) as tc:
        assert tc.post("/api/ask", json={"question": "prima domanda"}, headers=_headers()).status_code == 200
        r = tc.post("/api/ask", json={"question": "seconda domanda"}, headers=_headers())
    assert r.status_code == 429
    assert "limite" in r.json()["detail"]


def _preflight(tc: TestClient, origin: str):
    return tc.options(
        "/api/ask",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-access-code",
        },
    )


def test_cors_only_for_allowed_origin():
    with make_client() as tc:
        ok = _preflight(tc, ORIGIN)
        bad = _preflight(tc, "https://altro-sito.example")
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-origin" not in bad.headers
