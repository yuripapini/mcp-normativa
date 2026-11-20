"""Robustezza: errori HTTP documentati, timeout, risposte malformate, link Normattiva, config Render."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from app import guardrails as g
from app.config import DEFAULT_MCP_SERVER_URL, Settings
from app.llm import answer_question
from app.main import create_app
from app.models import LLMResult, ToolCall, ToolSpec
from app.telegram_bot import HELP_TEXT, START_TEXT, reply
from mcp_server import normattiva as nt
from mcp_server import server
from mcp_server.schemas import SearchInput
from tests.conftest import (
    ERR_ATTO_NON_TROVATO,
    ERR_GATEWAY_404,
    ERR_GENERIC_500,
    ERR_WAF_409,
    URL_ADVANCED,
    URL_DETAIL,
    URL_SIMPLE,
    detail_payload,
    err_spring,
    search_item,
    search_payload,
)

REF = nt.ActRef("1990-08-18", "090G0294")

# ------------------------------------------------------------- errori HTTP ---


async def test_spring_404_is_not_found(client, api):
    api.post(URL_DETAIL).respond(
        404, json=err_spring(404, "Not Found", "/bff-mobile/api/v1/atto/dettaglio-atto/")
    )
    with pytest.raises(nt.NormattivaNotFound):
        await client.article_detail(REF)


async def test_documented_404_bodies(client, api):
    route = api.post(URL_DETAIL)
    route.respond(404, json=ERR_ATTO_NON_TROVATO)
    with pytest.raises(nt.NormattivaNotFound):
        await client.article_detail(REF)
    route.respond(404, json=ERR_GATEWAY_404)
    with pytest.raises(nt.NormattivaError, match="gateway") as exc:
        await client.article_detail(REF)
    assert not isinstance(exc.value, nt.NormattivaNotFound)


@pytest.mark.parametrize("body", [ERR_GENERIC_500, err_spring(500, "Errore interno del server")])
async def test_500_bodies_are_retried(client, api, body):
    route = api.post(URL_SIMPLE).mock(
        side_effect=[httpx.Response(500, json=body), httpx.Response(200, json=search_payload())]
    )
    assert (await client.search_simple("x"))["listaAtti"] == []
    assert route.call_count == 2


@pytest.mark.parametrize(
    ("status", "body", "text"),
    [
        (400, err_spring(400, "Bad Request"), "Bad Request"),
        (422, err_spring(422, " Richiesta non processabile"), "Richiesta non processabile"),
    ],
)
async def test_client_errors_not_retried_and_readable(client, api, status, body, text):
    route = api.post(URL_SIMPLE).respond(status, json=body)
    with pytest.raises(nt.NormattivaError, match=text) as exc:
        await client.search_simple("x")
    assert exc.value.status == status and not exc.value.retryable
    assert route.call_count == 1


async def test_waf_block_not_retried(client, api):
    route = api.post(URL_SIMPLE).respond(409, json=ERR_WAF_409)
    with pytest.raises(nt.NormattivaError, match="protezione"):
        await client.search_simple("x")
    assert route.call_count == 1


async def test_429_retried(client, api):
    route = api.post(URL_SIMPLE).mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json=search_payload())]
    )
    await client.search_simple("x")
    assert route.call_count == 2


# ---------------------------------------------------------------- timeout ---


async def test_http_timeout_retried_then_error(client, api):
    route = api.post(URL_SIMPLE).mock(side_effect=httpx.ReadTimeout("lento"))
    with pytest.raises(nt.NormattivaError, match="ReadTimeout"):
        await client.search_simple("x")
    assert route.call_count == client.max_retries + 1


async def test_tool_overall_timeout_becomes_tool_error(client, monkeypatch):
    monkeypatch.setattr(server.get_settings(), "tool_timeout_seconds", 0.05)

    async def slow() -> None:
        await asyncio.sleep(1)

    with pytest.raises(server.ToolError, match="tempo massimo"):
        await server._guard("test", slow)


# ------------------------------------------------------- risposte malformate ---


@pytest.mark.parametrize("content", [b"", b"<html>errore</html>", b"[1, 2]"])
async def test_200_not_json_is_retried_then_error(client, api, content):
    route = api.post(URL_SIMPLE).respond(200, content=content)
    with pytest.raises(nt.NormattivaError, match="vuota o non in formato JSON"):
        await client.search_simple("x")
    assert route.call_count == client.max_retries + 1


async def test_search_drops_malformed_items(client, api):
    payload = search_payload(
        search_item(),
        "stringa",
        None,
        {"dataGU": "18-08-1990", "codiceRedazionale": "090G0294"},
        {"dataGU": "1990-08-18", "codiceRedazionale": "<script>"},
    )
    payload["numeroAttiTrovati"] = "5"
    api.post(URL_SIMPLE).respond(200, json=payload)
    out = await client.search_simple("x")
    assert len(out["listaAtti"]) == 1 and out["numeroAttiTrovati"] == 5


async def test_search_missing_list_with_zero_results(client, api):
    api.post(URL_SIMPLE).respond(200, json={"numeroAttiTrovati": 0, "listaAtti": None})
    assert (await client.search_simple("x"))["listaAtti"] == []


async def test_detail_success_false_is_not_found(client, api):
    api.post(URL_DETAIL).respond(200, json={"success": False, "code": "1", "message": "boh", "data": None})
    with pytest.raises(nt.NormattivaNotFound):
        await client.article_detail(REF)


def test_act_from_detail_tolerates_bad_types():
    atto = detail_payload()["data"]["atto"] | {
        "annoProvvedimento": "x",
        "numeroProvvedimento": None,
        "sottoTitolo": 123,
        "tipoProvvedimentoDescrizione": ["LEGGE"],
    }
    act = nt.act_from_detail(REF, atto)
    assert act.data_emanazione is None and act.numero is None and act.denominazione is None
    assert act.titolo == ""


async def test_unexpected_exception_becomes_generic_tool_error(client, api):
    async def boom() -> None:
        raise KeyError("campo_interno")

    with pytest.raises(server.ToolError) as exc:
        await server._guard("test", boom)
    assert "campo_interno" not in str(exc.value)


# ------------------------------------------------------- assenza risultati ---


async def test_search_tool_no_results_message(client, api):
    api.post(URL_SIMPLE).respond(200, json=search_payload())
    out = await server.search_italian_law_impl(SearchInput(query="parola inesistente xyz"))
    assert out.risultati == [] and out.totale_trovati == 0


async def test_vigence_citation_not_found_is_tool_error(client, api):
    api.post(URL_ADVANCED).respond(200, json=search_payload())
    async with Client(server.mcp) as c:
        result = await c.call_tool("check_law_vigence", {"law_id": "legge 9999/1990"}, raise_on_error=False)
    assert result.is_error and "non citare" in result.content[0].text


# ----------------------------------------------- URN/ELI non riconosciuti ---


@pytest.mark.parametrize(
    "law_id",
    [
        "urn:nir:stato:circolare:2020-01-01;1",  # tipo URN non supportato
        "urn:nir:regione.lombardia:legge:2020-01-01;1",  # URN regionale
        "https://www.normattiva.it/eli/id/1990/xx/18/090G0294",  # ELI malformato
        "https://example.com/legge/241",  # URL estraneo
        "cosa dice la legge",  # testo senza riferimenti
    ],
)
async def test_unrecognized_ids_give_readable_error(client, law_id):
    async with Client(server.mcp) as c:
        result = await c.call_tool("get_official_source", {"law_id": law_id}, raise_on_error=False)
    assert result.is_error
    text = result.content[0].text
    assert "non riconosciuto" in text.lower() or "non supportato" in text.lower()


async def test_invalid_tool_params_give_readable_error(client):
    async with Client(server.mcp) as c:
        result = await c.call_tool(
            "check_law_vigence",
            {"law_id": "legge 241/1990", "as_of_date": "2020-13-45"},
            raise_on_error=False,
        )
    assert result.is_error and "as_of_date" in result.content[0].text


async def test_unknown_eli_code_is_not_found(client, api):
    api.post(URL_DETAIL).respond(404, json=ERR_ATTO_NON_TROVATO)
    async with Client(server.mcp) as c:
        result = await c.call_tool(
            "get_official_source",
            {"law_id": "https://www.normattiva.it/eli/id/1990/08/18/099X9999/CONSOLIDATED"},
            raise_on_error=False,
        )
    assert result.is_error and "non trovato" in result.content[0].text


# --------------------------------------------------------- link Normattiva ---

ELI = "https://www.normattiva.it/eli/id/1990/08/18/090G0294/CONSOLIDATED"
N2LS = "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:1990-08-07;241~art3"


def test_ensure_verified_link_keeps_text_with_verified_link():
    text = f"Vedi [L. 241/1990]({ELI})."
    assert g.ensure_verified_link(text, [ELI]) == text


def test_ensure_verified_link_appends_when_missing_or_unverified():
    out = g.ensure_verified_link("Risposta senza link.", [N2LS, ELI])
    assert "Fonti verificate su Normattiva" in out and N2LS in out and ELI in out
    invented = "Vedi https://www.normattiva.it/eli/id/2099/01/01/099X0001/CONSOLIDATED"
    assert "Fonti verificate" in g.ensure_verified_link(invented, [ELI])


def test_ensure_verified_link_same_act_other_article_counts():
    text = "Vedi https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:1990-08-07;241~art5"
    assert g.ensure_verified_link(text, [N2LS]) == text


def test_ensure_normattiva_link_before_disclaimer():
    out = g.ensure_normattiva_link(g.ensure_disclaimer("Nessun risultato."))
    assert g.NORMATTIVA_HOME in out
    assert out.rstrip().endswith(f"_{g.DISCLAIMER}_")


class _Session:
    def __init__(self, output: str) -> None:
        self.output = output

    async def list_tools(self) -> list[ToolSpec]:
        return [ToolSpec(name="search_italian_law")]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        return self.output


class _Provider:
    def __init__(self, final: str) -> None:
        self.script = [
            LLMResult(tool_calls=[ToolCall(id="1", name="search_italian_law", arguments={"query": "q"})]),
            LLMResult(content=final),
        ]

    async def complete(self, messages, tools, *, tool_choice="auto"):
        return self.script.pop(0)


async def test_answer_without_link_gets_verified_sources():
    session = _Session(f'{{"risultati": [{{"url_normattiva": "{ELI}"}}]}}')
    res = await answer_question("q", _Provider("La norma è la legge 241/1990."), session, system_prompt="s")
    assert ELI in res.text and res.text.rstrip().endswith(f"_{g.DISCLAIMER}_")


async def test_answer_with_no_verified_results_links_portal():
    res = await answer_question(
        "q", _Provider("Non ho trovato norme."), _Session('{"risultati": []}'), system_prompt="s"
    )
    assert g.NORMATTIVA_HOME in res.text


class _Msg:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def reply_text(self, text, parse_mode=None, link_preview_options=None):
        self.texts.append(text)


class _Upd:
    def __init__(self) -> None:
        self.effective_message = _Msg()


@pytest.mark.parametrize(
    "text", [START_TEXT, HELP_TEXT, g.RATE_LIMITED_MESSAGE, "Scrivi una domanda un po' più dettagliata."]
)
async def test_every_reply_has_normattiva_link(text):
    upd = _Upd()
    await reply(upd, text)  # type: ignore[arg-type]
    assert "normattiva.it" in " ".join(upd.effective_message.texts)


async def test_unauthorized_reply_reveals_nothing():
    upd = _Upd()
    await reply(upd, g.UNAUTHORIZED_MESSAGE)  # type: ignore[arg-type]
    assert upd.effective_message.texts == [g.UNAUTHORIZED_MESSAGE]


# ------------------------------------------------------------ config Render ---


def test_render_generated_secret_is_normalized():
    raw = "B0jrphAPOY7pg92AN0c9MN4yecczLMdwnx4OkA1KFUk="  # formato di generateValue
    s = Settings(telegram_webhook_secret=raw)
    assert s.webhook_secret_token == hashlib.sha256(raw.encode()).hexdigest()
    assert Settings(telegram_webhook_secret="gia_valido-123").webhook_secret_token == "gia_valido-123"


def test_webhook_accepts_normalized_render_secret():
    raw = "B0jrphAPOY7pg92AN0c9MN4yecczLMdwnx4OkA1KFUk="
    seen: list[dict] = []

    async def proc(data: dict) -> None:
        seen.append(data)

    settings = Settings(telegram_webhook_secret=raw, runtime_env="test")
    with TestClient(create_app(settings, processor=proc)) as tc:
        ok = tc.post(
            "/telegram/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": settings.webhook_secret_token},
        )
        ko = tc.post(
            "/telegram/webhook", json={"update_id": 2}, headers={"X-Telegram-Bot-Api-Secret-Token": raw}
        )
    assert ok.status_code == 200 and ko.status_code == 403
    assert seen == [{"update_id": 1}]


def test_public_url_falls_back_to_render_external_url():
    s = Settings(render_external_url="https://lexbot-telegram.onrender.com/")
    assert s.webhook_url == "https://lexbot-telegram.onrender.com/telegram/webhook"
    s = Settings(public_base_url="https://bot.example.it", render_external_url="https://x.onrender.com")
    assert s.webhook_url == "https://bot.example.it/telegram/webhook"


def test_mcp_url_resolution():
    assert Settings().effective_mcp_server_url == DEFAULT_MCP_SERVER_URL
    assert (
        Settings(mcp_server_hostport="lexbot-mcp:10000").effective_mcp_server_url
        == "http://lexbot-mcp:10000/mcp"
    )
    s = Settings(mcp_server_url="https://m.example/mcp", mcp_server_hostport="lexbot-mcp:10000")
    assert s.effective_mcp_server_url == "https://m.example/mcp"


def test_render_blueprint_is_consistent():
    import yaml

    from mcp_server.server import MCPSettings

    blueprint = yaml.safe_load(Path("render.yaml").read_text(encoding="utf-8"))
    services = {s["name"]: s for s in blueprint["services"]}
    bot_keys = {e["key"] for e in services["lexbot-telegram"]["envVars"]}
    mcp_keys = {e["key"] for e in services["lexbot-mcp"]["envVars"]}
    # Ogni variabile del blueprint è letta dal codice (nessun refuso nei nomi).
    known_bot = {k.upper() for k in Settings.model_fields} | {"PYTHON_VERSION"}
    known_mcp = {k.upper() for k in MCPSettings.model_fields} | {"PYTHON_VERSION"}
    assert bot_keys <= known_bot, bot_keys - known_bot
    assert mcp_keys <= known_mcp, mcp_keys - known_mcp
    # I segreti indispensabili sono presenti (generati, collegati o da dashboard).
    assert {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_SECRET",
        "OPENAI_API_KEY",
        "ALLOWED_TELEGRAM_USER_IDS",
    } <= bot_keys
    assert {"MCP_AUTH_TOKEN", "MCP_SERVER_HOSTPORT"} <= bot_keys
    for svc in services.values():
        assert "$PORT" in svc["startCommand"] and svc["healthCheckPath"] == "/healthz"
