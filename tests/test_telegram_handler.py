"""Test del bot: webhook FastAPI, guardrail, orchestrazione LLM e comandi."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app import guardrails as g
from app.config import Settings
from app.llm import NO_RESULT_MESSAGE, LLMError, OpenAICompatibleProvider, answer_question
from app.main import create_app, verify_secret
from app.models import LLMResult, ToolCall, ToolSpec
from app.telegram_bot import (
    GENERIC_ERROR,
    LLM_BUSY_ERROR,
    LLM_ERROR,
    LexBot,
    format_verifica,
    send_long_message,
)

# ------------------------------------------------------------------ webhook ---


def make_client(secret: str = "s3cret_-OK") -> tuple[TestClient, list[dict[str, Any]]]:
    received: list[dict[str, Any]] = []

    async def processor(data: dict[str, Any]) -> None:
        received.append(data)

    app = create_app(Settings(telegram_webhook_secret=secret, runtime_env="test"), processor=processor)
    return TestClient(app), received


def test_healthz():
    tc, _ = make_client()
    with tc:
        r = tc.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"X-Telegram-Bot-Api-Secret-Token": "sbagliato"}])
def test_webhook_rejects_wrong_or_missing_secret(headers):
    tc, received = make_client()
    with tc:
        r = tc.post("/telegram/webhook", json={"update_id": 1}, headers=headers)
    assert r.status_code == 403
    assert received == []


def test_webhook_accepts_and_processes():
    tc, received = make_client()
    with tc:
        r = tc.post(
            "/telegram/webhook",
            json={"update_id": 7},
            headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret_-OK"},
        )
        assert r.status_code == 200 and r.json() == {"ok": True}
    assert received == [{"update_id": 7}]


def test_webhook_invalid_json_returns_200():
    tc, received = make_client()
    with tc:
        r = tc.post(
            "/telegram/webhook",
            content=b"non json",
            headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret_-OK", "Content-Type": "application/json"},
        )
    assert r.status_code == 200 and received == []


def test_webhook_disabled_when_secret_not_configured():
    tc, _ = make_client(secret="")
    with tc:
        r = tc.post("/telegram/webhook", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": ""})
    assert r.status_code == 403


def test_verify_secret():
    assert verify_secret("abc", "abc")
    assert not verify_secret("abc", "abd")
    assert not verify_secret(None, "abc")
    assert not verify_secret("abc", "")


# ------------------------------------------------------- allowlist e limiti ---


def test_allowlist_parsing_and_check():
    s = Settings(allowed_telegram_user_ids=" 123, 456;abc,-789 ")
    assert s.allowed_user_ids == frozenset({123, 456, -789})
    assert g.is_authorized(123, s.allowed_user_ids)
    assert not g.is_authorized(999, s.allowed_user_ids)
    assert not g.is_authorized(None, s.allowed_user_ids)
    assert not g.is_authorized(123, Settings().allowed_user_ids)  # allowlist vuota = nessuno


def test_rate_limiter_sliding_window():
    now = [0.0]
    rl = g.RateLimiter(max_requests=10, window_seconds=300, clock=lambda: now[0])
    assert all(rl.allow(1) for _ in range(10))
    assert not rl.allow(1)
    assert rl.allow(2)  # utenti indipendenti
    now[0] = 299.0
    assert not rl.allow(1)
    now[0] = 300.0
    assert rl.allow(1)


def test_query_fingerprint_never_contains_text():
    fp = g.query_fingerprint("dati sensibili dell'utente")
    assert set(fp) == {"q_hash", "q_len"}
    assert "sensibili" not in json.dumps(fp)


def test_sanitize_query():
    assert g.sanitize_query("ciao\x00\x07  mondo\n\n", 100) == "ciao mondo"
    assert len(g.sanitize_query("a" * 5000, 2000)) == 2000


# ------------------------------------------------------------ formattazione ---


def test_ensure_disclaimer_idempotent():
    once = g.ensure_disclaimer("Risposta.")
    assert g.DISCLAIMER in once
    assert g.ensure_disclaimer(once) == once


def test_split_message_respects_limit_and_content():
    text = "\n\n".join(f"Paragrafo {i} " + "parola " * 80 for i in range(40))
    parts = g.split_message(text, 4096)
    assert len(parts) > 1
    assert all(len(p) <= 4096 for p in parts)
    assert " ".join(parts).split() == text.split()


def test_split_message_without_spaces():
    parts = g.split_message("x" * 10000, 4096)
    assert [len(p) for p in parts] == [4096, 4096, 1808]


def test_markdown_to_html_escapes_and_formats():
    out = g.markdown_to_telegram_html(
        "**Art. 1** <script>alert(1)</script> & _nota_ `cod` [Normattiva](https://www.normattiva.it/a?b=1&c=2)"
    )
    assert "<script>" not in out
    assert "&lt;script&gt;" in out and "&amp;" in out
    assert "<b>Art. 1</b>" in out and "<i>nota</i>" in out and "<code>cod</code>" in out
    assert '<a href="https://www.normattiva.it/a?b=1&amp;c=2">Normattiva</a>' in out


def test_markdown_rejects_non_http_links():
    out = g.markdown_to_telegram_html("[clic](javascript:alert(1))")
    assert "<a " not in out


def test_markdown_underscores_in_identifiers_untouched():
    out = g.markdown_to_telegram_html("variabile snake_case_name e URN urn:nir:stato:legge")
    assert "<i>" not in out


def test_render_for_telegram_all_parts_within_limit():
    text = ("**titolo** <&> " * 50 + "\n\n") * 60
    parts = g.render_for_telegram(text)
    assert len(parts) > 1
    assert all(len(html) <= g.TELEGRAM_MAX_CHARS for html, _ in parts)
    assert all(len(plain) <= g.TELEGRAM_MAX_CHARS for _, plain in parts)


# -------------------------------------------------------------------- LLM ---


class FakeSession:
    def __init__(self, results: dict[str, str] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.results = results or {}

    async def list_tools(self) -> list[ToolSpec]:
        return [ToolSpec(name="search_italian_law", description="cerca")]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls.append((name, arguments))
        return self.results.get(name, '{"risultati": []}')


class FakeProvider:
    def __init__(self, script: list[LLMResult]) -> None:
        self.script = script
        self.choices: list[str] = []
        self.tool_counts: list[int] = []

    async def complete(self, messages, tools, *, tool_choice="auto"):
        self.choices.append(tool_choice)
        self.tool_counts.append(len(tools))
        return self.script.pop(0)


def tool_round(name: str = "search_italian_law") -> LLMResult:
    return LLMResult(tool_calls=[ToolCall(id="c1", name=name, arguments={"query": "x"})])


async def test_answer_question_uses_tools_then_answers():
    provider = FakeProvider([tool_round(), LLMResult(content="Risposta con fonte.")])
    session = FakeSession()
    result = await answer_question("domanda", provider, session, system_prompt="sys")
    assert provider.choices == ["required", "auto"]
    assert session.calls == [("search_italian_law", {"query": "x"})]
    assert result.tools_used == ["search_italian_law"] and result.rounds == 2
    assert result.text.startswith("Risposta con fonte.") and g.DISCLAIMER in result.text


async def test_answer_question_round_limit_forces_final_without_tools():
    provider = FakeProvider([tool_round(), tool_round(), LLMResult(content="Finale.")])
    result = await answer_question("d", provider, FakeSession(), system_prompt="s", max_rounds=2)
    assert provider.tool_counts == [1, 1, 0]
    assert result.rounds == 3 and result.text.startswith("Finale.")


async def test_answer_question_empty_answer_fallback():
    provider = FakeProvider([LLMResult(content="  ")])
    result = await answer_question("d", provider, FakeSession(), system_prompt="s")
    assert result.text.startswith(NO_RESULT_MESSAGE)


async def test_openai_provider_parses_tool_calls(api):
    route = api.post("https://llm.test/v1/chat/completions").respond(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "t1",
                                "type": "function",
                                "function": {"name": "get_law_article", "arguments": '{"law_id": "x"}'},
                            }
                        ],
                    }
                }
            ]
        },
    )
    p = OpenAICompatibleProvider("k", "gpt-4.1-mini", base_url="https://llm.test/v1")
    res = await p.complete([], [ToolSpec(name="get_law_article")], tool_choice="required")
    assert res.tool_calls[0].name == "get_law_article" and res.tool_calls[0].arguments == {"law_id": "x"}
    body = json.loads(route.calls.last.request.read())
    assert body["tool_choice"] == "required" and body["model"] == "gpt-4.1-mini"
    assert route.calls.last.request.headers["Authorization"] == "Bearer k"


async def test_openai_provider_errors(api):
    route = api.post("https://llm.test/v1/chat/completions")
    p = OpenAICompatibleProvider("k", "m", base_url="https://llm.test/v1")
    route.respond(500)
    with pytest.raises(LLMError):
        await p.complete([], [])
    route.respond(200, json={"choices": []})
    with pytest.raises(LLMError):
        await p.complete([], [])
    route.mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(LLMError):
        await p.complete([], [])


OPENROUTER_429 = {
    "error": {
        "message": "Provider returned error",
        "code": 429,
        "metadata": {
            "raw": "google/gemma-4-31b-it:free is temporarily rate-limited upstream. Please retry shortly.",
            "provider_name": "Google AI Studio",
        },
    }
}


async def test_openai_provider_retries_429_then_succeeds(api):
    route = api.post("https://llm.test/v1/chat/completions")
    route.side_effect = [
        httpx.Response(429, json=OPENROUTER_429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}),
    ]
    p = OpenAICompatibleProvider("k", "m", base_url="https://llm.test/v1", retry_base=0)
    res = await p.complete([], [])
    assert res.content == "ok" and route.call_count == 2


async def test_openai_provider_429_exhausted_has_status_and_detail(api):
    route = api.post("https://llm.test/v1/chat/completions")
    route.respond(429, json=OPENROUTER_429)
    p = OpenAICompatibleProvider("k", "m", base_url="https://llm.test/v1", retry_base=0, max_retries=2)
    with pytest.raises(LLMError) as info:
        await p.complete([], [])
    assert route.call_count == 3
    assert info.value.status_code == 429
    assert "Google AI Studio" in str(info.value) and "rate-limited upstream" in str(info.value)


async def test_openai_provider_does_not_retry_4xx(api):
    route = api.post("https://llm.test/v1/chat/completions")
    route.respond(401, json={"error": {"message": "No auth credentials found", "code": 401}})
    p = OpenAICompatibleProvider("k", "m", base_url="https://llm.test/v1", retry_base=0)
    with pytest.raises(LLMError) as info:
        await p.complete([], [])
    assert route.call_count == 1
    assert info.value.status_code == 401 and "No auth credentials found" in str(info.value)


async def test_openai_provider_error_in_200_body(api):
    api.post("https://llm.test/v1/chat/completions").respond(
        200, json={"error": {"message": "upstream failure", "code": 502}}
    )
    p = OpenAICompatibleProvider("k", "m", base_url="https://llm.test/v1", retry_base=0, max_retries=0)
    with pytest.raises(LLMError) as info:
        await p.complete([], [])
    assert "upstream failure" in str(info.value)


def test_openai_provider_requires_key():
    with pytest.raises(LLMError):
        OpenAICompatibleProvider("", "m")


# ------------------------------------------------------------- logica bot ---


class FakeMCP:
    def __init__(self, session: FakeSession | None = None, exc: Exception | None = None) -> None:
        self._session = session or FakeSession()
        self._exc = exc

    @asynccontextmanager
    async def session(self):
        if self._exc:
            raise self._exc
        yield self._session


def make_bot(**kwargs: Any) -> LexBot:
    settings = Settings(allowed_telegram_user_ids="42", runtime_env="test")
    return LexBot(settings, **kwargs)


def test_check_access():
    bot = make_bot(rate_limiter=g.RateLimiter(max_requests=1, window_seconds=300))
    assert bot.check_access(7, rate_limited=True) == g.UNAUTHORIZED_MESSAGE
    assert bot.check_access(42, rate_limited=True) is None
    assert bot.check_access(42, rate_limited=True) == g.RATE_LIMITED_MESSAGE
    assert bot.check_access(42, rate_limited=False) is None  # comandi statici non consumano quota


async def test_handle_question_ok():
    provider = FakeProvider([tool_round(), LLMResult(content="Ok.")])
    bot = make_bot(mcp=FakeMCP(), provider_factory=lambda: provider)
    assert (await bot.handle_question(42, "Quale legge regola la privacy?")).startswith("Ok.")


async def test_handle_question_too_short():
    bot = make_bot(mcp=FakeMCP(), provider_factory=lambda: FakeProvider([]))
    assert "dettagliata" in await bot.handle_question(42, "a")


async def test_handle_question_mcp_down_is_generic_error():
    bot = make_bot(mcp=FakeMCP(exc=httpx.ConnectError("down")), provider_factory=lambda: FakeProvider([]))
    assert await bot.handle_question(42, "domanda valida") == GENERIC_ERROR


class FailingProvider:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def complete(self, messages, tools, *, tool_choice="auto"):
        raise self.exc


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (LLMError("Provider LLM HTTP 429", status_code=429), LLM_BUSY_ERROR),
        (LLMError("Provider LLM HTTP 503", status_code=503), LLM_BUSY_ERROR),
        (LLMError("Provider LLM HTTP 401", status_code=401), LLM_ERROR),
        (LLMError("Risposta LLM non valida"), LLM_ERROR),
    ],
)
async def test_handle_question_llm_errors_have_specific_message(exc, expected):
    bot = make_bot(mcp=FakeMCP(), provider_factory=lambda: FailingProvider(exc))
    assert await bot.handle_question(42, "domanda valida") == expected
    assert expected != GENERIC_ERROR


async def test_handle_verifica_ok():
    session = FakeSession(
        {
            "get_official_source": json.dumps(
                {
                    "law_id": "1990-08-18:090G0294",
                    "descrizione_atto": "LEGGE 7 agosto 1990, n. 241",
                    "url_normattiva": "https://www.normattiva.it/eli/id/1990/08/18/090G0294/CONSOLIDATED",
                    "url_gazzetta_ufficiale": "https://www.gazzettaufficiale.it/eli/id/1990/08/18/090G0294/sg",
                    "urn": "urn:nir:stato:legge:1990-08-07;241",
                    "data_consultazione": "2026-11-20T10:00:00+00:00",
                }
            ),
            "check_law_vigence": json.dumps(
                {"stato": "modificato", "stato_verificato": True, "motivazione": "aggiornato"}
            ),
        }
    )
    bot = make_bot(mcp=FakeMCP(session), provider_factory=lambda: FakeProvider([]))
    out = await bot.handle_verifica(42, "legge 241/1990")
    assert [c[0] for c in session.calls] == ["get_official_source", "check_law_vigence"]
    assert session.calls[1][1] == {"law_id": "1990-08-18:090G0294"}
    assert "vigente con modifiche" in out
    assert "2026-11-20T10:00:00+00:00" in out
    assert g.DISCLAIMER in out


async def test_handle_verifica_unknown_id_and_usage():
    session = FakeSession({"get_official_source": json.dumps({"errore": "Identificativo non riconosciuto"})})
    bot = make_bot(mcp=FakeMCP(session), provider_factory=lambda: FakeProvider([]))
    assert "non riconosciuto" in await bot.handle_verifica(42, "boh")
    assert (await bot.handle_verifica(42, "  ")).startswith("Uso: /verifica")


def test_format_verifica_unverifiable():
    out = format_verifica({"descrizione_atto": "Atto X"}, {"errore": "Normattiva non risponde"})
    assert "non verificabile" in out and "n.d." in out
    out = format_verifica({}, {"stato": "vigente", "stato_verificato": False})
    assert "vigente (non verificato)" in out


# ------------------------------------------------------------- invio PTB ---


class FakeMessage:
    def __init__(self, fail_html: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail_html = fail_html

    async def reply_text(self, text, parse_mode=None, link_preview_options=None):
        from telegram.error import BadRequest

        if parse_mode and self.fail_html:
            raise BadRequest("Can't parse entities")
        self.sent.append({"text": text, "parse_mode": parse_mode, "preview": link_preview_options})


class FakeUpdate:
    def __init__(self, message: FakeMessage) -> None:
        self.effective_message = message


async def test_send_long_message_splits_and_disables_preview():
    msg = FakeMessage()
    await send_long_message(FakeUpdate(msg), "parola " * 2000)  # type: ignore[arg-type]
    assert len(msg.sent) >= 3
    assert all(len(s["text"]) <= 4096 and s["parse_mode"] == "HTML" for s in msg.sent)
    assert all(s["preview"].is_disabled for s in msg.sent)


async def test_send_long_message_falls_back_to_plain_text():
    msg = FakeMessage(fail_html=True)
    await send_long_message(FakeUpdate(msg), "**ciao**")  # type: ignore[arg-type]
    assert msg.sent == [{"text": "**ciao**", "parse_mode": None, "preview": msg.sent[0]["preview"]}]


def test_build_application_registers_handlers():
    from app.telegram_bot import build_application

    settings = Settings(telegram_bot_token="123456:TEST-token", runtime_env="test")
    application = build_application(settings, make_bot(mcp=FakeMCP()))
    commands = {
        c for handlers in application.handlers.values() for h in handlers for c in getattr(h, "commands", [])
    }
    assert {"start", "aiuto", "help", "fonti", "verifica"} <= commands


async def test_answer_question_optional_tools_and_raw_text():
    provider = FakeProvider([LLMResult(content="OGGETTO: x\n---\nTesto.")])
    result = await answer_question(
        "scrivi", provider, FakeSession(), system_prompt="s", require_tools=False, postprocess=False
    )
    assert provider.choices == ["auto"]
    assert result.text == "OGGETTO: x\n---\nTesto."
    assert g.DISCLAIMER not in result.text


async def test_answer_question_raw_empty_stays_empty():
    provider = FakeProvider([LLMResult(content="  ")])
    result = await answer_question(
        "scrivi", provider, FakeSession(), system_prompt="s", require_tools=False, postprocess=False
    )
    assert result.text == ""
