"""Test dei tool MCP con API Normattiva mockata (respx)."""

from __future__ import annotations

import json

import httpx
import pytest
from fastmcp import Client

from mcp_server import discovery as disc
from mcp_server import normattiva as nt
from mcp_server import server
from mcp_server.schemas import ArticleInput, LawIdInput, RelatedInput, SearchInput, VigenceInput
from tests.conftest import URL_ADVANCED, URL_DETAIL, URL_SIMPLE, detail_payload, search_item, search_payload


def advanced_responder(classe_attesa: str | None):
    """Ricerca avanzata: senza classe restituisce l'atto; con classe solo se coincide."""

    def responder(request: httpx.Request) -> httpx.Response:
        classe = json.loads(request.read()).get("classeProvvedimento")
        if classe is None or classe == classe_attesa:
            return httpx.Response(200, json=search_payload(search_item()))
        return httpx.Response(200, json=search_payload())

    return responder


# ------------------------------------------------------------------ search ---


async def test_search_by_citation(client, api):
    api.post(URL_ADVANCED).respond(200, json=search_payload(search_item()))
    api.post(URL_SIMPLE).respond(200, json=search_payload())
    out = await server.search_italian_law_impl(SearchInput(query="legge 241/1990", limit=1))
    assert len(out.risultati) == 1
    res = out.risultati[0]
    assert res.origine == "citazione"
    assert res.law_id == "1990-08-18:090G0294"
    assert res.url_normattiva.startswith("https://www.normattiva.it/eli/id/1990/08/18/090G0294")
    assert res.urn == "urn:nir:stato:legge:1990-08-07;241"
    assert out.fonte.data_consultazione


async def test_search_by_topic_then_text(client, api):
    api.post(URL_ADVANCED).respond(200, json=search_payload(search_item()))
    api.post(URL_SIMPLE).respond(
        200,
        json=search_payload(
            search_item(codice="024G00001", data_gu="2024-01-02", numero="1", anno="2024"),
        ),
    )
    out = await server.search_italian_law_impl(SearchInput(query="accesso agli atti", limit=5))
    origini = [r.origine for r in out.risultati]
    assert origini[0] == "indice_tematico"
    assert "ricerca_testuale" in origini
    assert any("pertinenza" in n for n in out.fonte.note)


async def test_search_no_results(client, api):
    api.post(URL_SIMPLE).respond(200, json=search_payload())
    out = await server.search_italian_law_impl(SearchInput(query="zzzz qwerty"))
    assert out.risultati == []
    assert any("Nessun atto" in n for n in out.fonte.note)


def test_match_topics_by_materia_and_synonym():
    assert any(t["id"] == "privacy" for t in server.match_topics("domanda generica", "privacy"))
    assert any(t["id"] == "privacy" for t in server.match_topics("cosa dice il codice privacy?", None))
    assert server.match_topics("ricetta della carbonara", None) == []


@pytest.mark.parametrize(
    ("query", "topic"),
    [
        ("mi hanno licenziato senza preavviso", "lavoro"),
        ("come richiedo l'accesso agli atti del comune?", "procedimento-amministrativo"),
        ("trattamento dei miei dati personali da parte di un'azienda", "privacy"),
    ],
)
def test_match_topics_inflected_forms(query, topic):
    assert topic in {t["id"] for t in server.match_topics(query, None)}


# ----------------------------------------------------------------- article ---


async def test_get_article_ok(client, api):
    api.post(URL_ADVANCED).respond(200, json=search_payload(search_item()))
    route = api.post(URL_DETAIL).respond(200, json=detail_payload())
    out = await server.get_law_article_impl(ArticleInput(law_id="legge 241/1990", article="3-bis"))
    assert out.trovato and out.stato_vigenza == "vigente"
    art = out.articoli[0]
    assert art.articolo == "3-bis"
    assert art.rubrica == "Art. 1 - Principi"
    assert art.vigenza_dal == "2005-03-08" and art.vigenza_al is None
    assert art.url_articolo == (
        "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:1990-08-07;241~art3bis"
    )
    body = json.loads(route.calls.last.request.read())
    assert (body["idArticolo"], body["sottoArticolo"]) == (3, 2)


async def test_get_article_abrogated(client, api):
    api.post(URL_ADVANCED).respond(200, json=search_payload(search_item()))
    api.post(URL_DETAIL).respond(200, json=detail_payload("<p>((ARTICOLO ABROGATO DALLA L. X))</p>"))
    out = await server.get_law_article_impl(ArticleInput(law_id="legge 241/1990", article="5"))
    assert out.stato_vigenza == "abrogato" and out.articoli[0].abrogato


async def test_get_article_not_available(client, api):
    api.post(URL_DETAIL).mock(
        side_effect=[
            httpx.Response(200, json=detail_payload()),  # resolve (art. 1)
            httpx.Response(404, json={"message": "eco"}),  # articolo richiesto
        ]
    )
    out = await server.get_law_article_impl(ArticleInput(law_id="1990-08-18:090G0294", article="999"))
    assert not out.trovato
    assert out.messaggio and "999" in out.messaggio
    assert out.url_ufficiale


async def test_get_article_default_is_art_1(client, api):
    api.post(URL_DETAIL).respond(200, json=detail_payload())
    out = await server.get_law_article_impl(ArticleInput(law_id="1990-08-18:090G0294"))
    assert out.articoli[0].articolo == "1"
    assert any("art. 1" in n for n in out.fonte.note)


# ----------------------------------------------------------------- vigenza ---


@pytest.mark.parametrize(
    ("classe", "stato"),
    [(nt.CLASSE_ABROGATO, "abrogato"), (nt.CLASSE_AGGIORNATO, "modificato"), ("1", "vigente")],
)
async def test_check_vigence(client, api, classe, stato):
    api.post(URL_ADVANCED).mock(side_effect=advanced_responder(classe))
    api.post(URL_DETAIL).respond(200, json=detail_payload())
    out = await server.check_law_vigence_impl(VigenceInput(law_id="legge 241/1990"))
    assert out.stato == stato and out.stato_verificato
    assert out.url_normattiva
    if stato == "vigente":
        assert out.data_entrata_in_vigore == "2005-03-08"
    if stato == "abrogato":
        assert any(m.tipo == "abrogazione" for m in out.modifiche)


async def test_check_vigence_unknown_class(client, api):
    api.post(URL_ADVANCED).mock(side_effect=advanced_responder("nessuna"))
    api.post(URL_DETAIL).respond(200, json=detail_payload())
    out = await server.check_law_vigence_impl(VigenceInput(law_id="legge 241/1990"))
    assert out.stato == "sconosciuto" and not out.stato_verificato


async def test_check_vigence_past_date_not_verified(client, api):
    api.post(URL_ADVANCED).mock(side_effect=advanced_responder(nt.CLASSE_AGGIORNATO))
    api.post(URL_DETAIL).respond(200, json=detail_payload())
    out = await server.check_law_vigence_impl(VigenceInput(law_id="legge 241/1990", as_of_date="2001-01-01"))
    assert out.stato == "modificato" and not out.stato_verificato
    assert out.data_riferimento == "2001-01-01"


def test_vigence_input_rejects_bad_date():
    with pytest.raises(ValueError):
        VigenceInput(law_id="legge 241/1990", as_of_date="2001-31-12")


# ------------------------------------------------------- related / source ---


async def test_related_laws(client, api):
    html = (
        '<p><a href="/uri-res/N2Ls?urn:nir:stato:legge:1988-08-23;400~art17">L. 400/1988</a>'
        '<a href="/uri-res/N2Ls?urn:nir:stato:legge:1990-08-07;241~art2">rinvio interno</a></p>'
    )
    api.post(URL_ADVANCED).respond(200, json=search_payload(search_item()))
    api.post(URL_DETAIL).mock(
        side_effect=[
            httpx.Response(200, json=detail_payload(html)),
            httpx.Response(404, json={"message": "x"}),
        ]
    )
    out = await server.get_related_laws_impl(RelatedInput(law_id="legge 241/1990"))
    assert [r.urn for r in out.collegate] == ["urn:nir:stato:legge:1988-08-23;400"]
    assert out.collegate[0].citato_in == "art. 1"


async def test_official_source(client, api):
    api.post(URL_DETAIL).respond(200, json=detail_payload())
    out = await server.get_official_source_impl(
        LawIdInput(law_id="https://www.normattiva.it/eli/id/1990/08/18/090G0294/CONSOLIDATED")
    )
    assert out.url_gazzetta_ufficiale == "https://www.gazzettaufficiale.it/eli/id/1990/08/18/090G0294/sg"
    assert out.urn == "urn:nir:stato:legge:1990-08-07;241"
    assert out.eli == "eli/id/1990/08/18/090G0294/CONSOLIDATED"


# ------------------------------------------------------ server FastMCP ---


async def test_mcp_lists_five_tools():
    async with Client(server.mcp) as c:
        names = {t.name for t in await c.list_tools()}
    assert names == {
        "search_italian_law",
        "get_law_article",
        "check_law_vigence",
        "get_related_laws",
        "get_official_source",
    }


async def test_mcp_invalid_id_returns_readable_error(client):
    async with Client(server.mcp) as c:
        result = await c.call_tool("get_official_source", {"law_id": "boh boh"}, raise_on_error=False)
    assert result.is_error
    assert "Identificativo non riconosciuto" in result.content[0].text


async def test_mcp_upstream_error_is_tool_error(client, api):
    api.post(URL_DETAIL).respond(400, json={"message": "Richiesta non valida"})
    async with Client(server.mcp) as c:
        result = await c.call_tool(
            "get_official_source", {"law_id": "1990-08-18:090G0294"}, raise_on_error=False
        )
    assert result.is_error
    assert "Normattiva non ha risposto correttamente" in result.content[0].text


async def test_mcp_article_accepts_integer(client, api):
    """I modelli gratuiti passano spesso article come numero (25 invece di "25")."""
    route = api.post(URL_DETAIL).respond(200, json=detail_payload())
    async with Client(server.mcp) as c:
        result = await c.call_tool("get_law_article", {"law_id": "1990-08-18:090G0294", "article": 25})
    assert not result.is_error
    assert result.structured_content["articoli"][0]["articolo"] == "25"
    body = json.loads(route.calls.last.request.read())
    assert body["idArticolo"] == 25


async def test_mcp_structured_output(client, api):
    api.post(URL_DETAIL).respond(200, json=detail_payload())
    async with Client(server.mcp) as c:
        result = await c.call_tool("get_official_source", {"law_id": "1990-08-18:090G0294"})
    assert result.structured_content["law_id"] == "1990-08-18:090G0294"


async def test_bearer_middleware():
    from starlette.testclient import TestClient

    app = server.BearerAuthMiddleware(server.mcp.http_app(path="/mcp"), "segreto")
    with TestClient(app) as tc:
        assert tc.get("/healthz").status_code == 200
        assert tc.post("/mcp", json={}).status_code == 401
        assert tc.post("/mcp", json={}, headers={"Authorization": "Bearer altro"}).status_code == 401


# --------------------------------------------------------------- discovery ---


def test_parse_provision_path():
    cand = disc.parse_provision_path("italy/national/acts/normativa/legge/1990/241/art-022-bis.md")
    assert cand is not None
    assert (cand.citation.type_key, cand.citation.anno, cand.citation.numero) == ("legge", "1990", "241")
    assert cand.citation.articolo == "22-bis"
    assert disc.parse_provision_path("italy/regional/foo/1/2") is None
    assert disc.parse_provision_path("italy/national/acts/normativa/circolare/2020/1") is None


async def test_discovery_candidates_dedup_and_errors(api):
    route = api.get(disc.DEFAULT_LEXIFINA_URL).respond(
        200,
        json={
            "data": {
                "provisions": [
                    "italy/national/acts/normativa/legge/1990/241/art-001.md",
                    "italy/national/acts/normativa/legge/1990/241/art-002.md",
                    "italy/national/acts/normativa/decreto-legislativo/2003/196/art-013.md",
                ]
            }
        },
    )
    d = disc.LexifinaDiscovery()
    cands = await d.candidates("privacy", limit=5)
    assert [(c.citation.type_key, c.citation.numero) for c in cands] == [
        ("legge", "241"),
        ("decreto legislativo", "196"),
    ]
    assert route.calls.last.request.url.params["jurisdiction"] == "italy"
    route.respond(500)
    assert await d.candidates("privacy") == []


async def test_search_with_discovery_verifies_on_normattiva(client, api):
    class FakeDiscovery:
        async def candidates(self, query, limit):
            return [disc.Candidate(nt.Citation("legge", "1990", "241", None, "22"), "p")]

    server.set_discovery(FakeDiscovery())  # type: ignore[arg-type]
    server.get_settings().lexifina_discovery_enabled = True
    try:
        api.post(URL_ADVANCED).respond(200, json=search_payload(search_item()))
        api.post(URL_SIMPLE).respond(200, json=search_payload())
        out = await server.search_italian_law_impl(SearchInput(query="diritto di accesso civico", limit=3))
    finally:
        server.get_settings().lexifina_discovery_enabled = False
    res = [r for r in out.risultati if r.origine == "discovery_verificata"]
    assert res and res[0].articolo_suggerito == "22"
