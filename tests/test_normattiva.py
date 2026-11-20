"""Test del client Normattiva: parsing identificativi, risposte ed errori HTTP."""

from __future__ import annotations

import httpx
import pytest

from mcp_server import normattiva as nt
from tests.conftest import URL_ADVANCED, URL_DETAIL, URL_SIMPLE, detail_payload, search_item, search_payload

# ------------------------------------------------------------ identificativi ---


def test_parse_internal_id():
    parsed = nt.parse_law_id("1990-08-18:090g0294")
    assert parsed.ref == nt.ActRef("1990-08-18", "090G0294")
    assert parsed.ref.law_id == "1990-08-18:090G0294"


def test_parse_eli_normattiva_and_gu():
    for url in (
        "https://www.normattiva.it/eli/id/1990/08/18/090G0294/CONSOLIDATED",
        "https://www.gazzettaufficiale.it/eli/id/1990/08/18/090G0294/sg",
    ):
        assert nt.parse_law_id(url).ref == nt.ActRef("1990-08-18", "090G0294")


def test_parse_carica_dettaglio_url():
    url = (
        "https://www.normattiva.it/atto/caricaDettaglioAtto?"
        "atto.dataPubblicazioneGazzetta=2003-07-29&atto.codiceRedazionale=003G0218"
    )
    assert nt.parse_law_id(url).ref == nt.ActRef("2003-07-29", "003G0218")


def test_parse_urn_with_article():
    parsed = nt.parse_law_id("urn:nir:stato:legge:1988-08-23;400~art13bis")
    assert parsed.citation is not None
    assert parsed.citation.type_key == "legge"
    assert parsed.citation.numero == "400"
    assert parsed.citation.data_emanazione == "1988-08-23"
    assert parsed.articolo == "13bis"
    assert parsed.citation.urn == "urn:nir:stato:legge:1988-08-23;400"


def test_parse_unsupported_urn_type():
    with pytest.raises(nt.InvalidLawId):
        nt.parse_law_id("urn:nir:stato:circolare:2020-01-01;1")


@pytest.mark.parametrize(
    ("text", "key", "numero", "anno", "data"),
    [
        ("d.lgs. 196/2003", "decreto legislativo", "196", "2003", None),
        ("D.Lgs. n. 81 del 2008", "decreto legislativo", "81", "2008", None),
        ("legge 23 agosto 1988, n. 400", "legge", "400", "1988", "1988-08-23"),
        ("dpr 445/2000", "decreto del presidente della repubblica", "445", "2000", None),
        ("R.D. 262/1942", "regio decreto", "262", "1942", None),
    ],
)
def test_parse_citation(text, key, numero, anno, data):
    cit = nt.parse_citation(text)
    assert cit is not None
    assert (cit.type_key, cit.numero, cit.anno, cit.data_emanazione) == (key, numero, anno, data)


def test_parse_citation_with_article_suffix():
    cit = nt.parse_citation("art. 13-bis della legge 400/1988")
    assert cit is not None and cit.articolo == "13-bis"


def test_parse_invalid_id():
    with pytest.raises(nt.InvalidLawId):
        nt.parse_law_id("una frase qualsiasi senza riferimenti")


@pytest.mark.parametrize(
    ("label", "expected"), [("13", (13, 1)), ("13-bis", (13, 2)), ("13 ter", (13, 3)), ("art. 2", (2, 1))]
)
def test_parse_article(label, expected):
    assert nt.parse_article(label) == expected
    assert nt.parse_article(nt.format_article(*expected)) == expected


def test_parse_article_invalid():
    with pytest.raises(nt.InvalidLawId):
        nt.parse_article("13-foo")
    with pytest.raises(nt.InvalidLawId):
        nt.parse_article("primo")


def test_official_urls():
    ref = nt.ActRef("1990-08-18", "090G0294")
    assert ref.normattiva_url == "https://www.normattiva.it/eli/id/1990/08/18/090G0294/CONSOLIDATED"
    assert ref.gazzetta_url == "https://www.gazzettaufficiale.it/eli/id/1990/08/18/090G0294/sg"
    assert nt.n2ls_url("urn:nir:stato:legge:1988-08-23;400", "13-bis") == (
        "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:1988-08-23;400~art13bis"
    )


# ---------------------------------------------------------------- parsing ---


def test_act_from_search_item():
    act = nt.act_from_search_item(search_item())
    assert act.ref.law_id == "1990-08-18:090G0294"
    assert act.titolo == "Nuove norme in materia di procedimento amministrativo."
    assert act.data_emanazione == "1990-08-07"
    assert act.urn == "urn:nir:stato:legge:1990-08-07;241"


def test_parse_article_html_extracts_heading_text_and_links():
    markup = (
        '<div class="article-heading-akn">Art. 2 - Rubrica</div>'
        "<p>Primo comma &egrave; qui.</p>"
        '<p>Vedi <a href="/uri-res/N2Ls?urn:nir:stato:legge:1988-08-23;400~art17">art. 17 L. 400</a>.</p>'
    )
    parsed = nt.parse_article_html(markup)
    assert parsed.heading == "Art. 2 - Rubrica"
    assert "Primo comma è qui." in parsed.text
    assert parsed.links == [("art. 17 L. 400", "urn:nir:stato:legge:1988-08-23;400~art17")]


def test_parse_article_html_heading_of_inserted_article():
    markup = (
        '<h2 class="article-num-akn">Art. 13-bis</h2>'
        '<div class="article-pre-comma-text-akn"><div class="ins-akn">(( (Rubrica di prova). ))</div>'
        "<br> ((</div><p>1. Testo.</p>"
    )
    assert nt.parse_article_html(markup).heading == "(( (Rubrica di prova). ))"


def test_yyyymmdd_and_abrogation_marker():
    assert nt.yyyymmdd_to_iso("20090704") == "2009-07-04"
    assert nt.yyyymmdd_to_iso("99999999") is None
    assert nt.yyyymmdd_to_iso(None) is None
    assert nt.is_article_abrogated("((ARTICOLO ABROGATO DAL D.LGS. 10 AGOSTO 2018, N. 101))")
    assert not nt.is_article_abrogated("Testo vigente")


# ----------------------------------------------------------- chiamate HTTP ---


async def test_search_simple_ok(client, api):
    route = api.post(URL_SIMPLE).respond(200, json=search_payload(search_item()))
    payload = await client.search_simple("procedimento amministrativo", page_size=3)
    assert payload["listaAtti"][0]["codiceRedazionale"] == "090G0294"
    body = route.calls.last.request.read()
    assert b'"numeroElementiPerPagina":3' in body.replace(b" ", b"")
    assert route.calls.last.request.headers["Origin"] == "https://dati.normattiva.it"


async def test_search_without_lista_atti_is_error(client, api):
    api.post(URL_SIMPLE).respond(200, json={"altro": 1})
    with pytest.raises(nt.NormattivaError, match="listaAtti"):
        await client.search_simple("x")


async def test_retry_on_503_then_success(client, api):
    route = api.post(URL_SIMPLE).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=search_payload())]
    )
    payload = await client.search_simple("x")
    assert payload["listaAtti"] == []
    assert route.call_count == 2


async def test_generic_500_retried_until_exhausted(client, api):
    route = api.post(URL_SIMPLE).respond(500, json={"message": nt._GENERIC_500})
    with pytest.raises(nt.NormattivaError) as exc:
        await client.search_simple("x")
    assert exc.value.status == 500 and exc.value.retryable
    assert route.call_count == client.max_retries + 1


async def test_400_not_retried(client, api):
    route = api.post(URL_SIMPLE).respond(400, json={"message": "Richiesta non valida"})
    with pytest.raises(nt.NormattivaError) as exc:
        await client.search_simple("x")
    assert exc.value.status == 400 and not exc.value.retryable
    assert route.call_count == 1


async def test_network_error_retried(client, api):
    route = api.post(URL_SIMPLE).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(nt.NormattivaError, match="rete"):
        await client.search_simple("x")
    assert route.call_count == client.max_retries + 1


async def test_404_atto_non_trovato_is_not_found(client, api):
    api.post(URL_DETAIL).respond(404, json={"message": "Atto non trovato"})
    with pytest.raises(nt.NormattivaNotFound):
        await client.article_detail(nt.ActRef("1990-08-18", "090G0294"))


async def test_404_echo_message_is_not_found(client, api):
    api.post(URL_DETAIL).respond(404, json={"message": '{"idArticolo":999}'})
    with pytest.raises(nt.NormattivaNotFound):
        await client.article_detail(nt.ActRef("1990-08-18", "090G0294"), articolo=999)


async def test_404_gateway_is_endpoint_error(client, api):
    api.post(URL_DETAIL).respond(404, json={"code": "404", "description": "No matching resource found"})
    with pytest.raises(nt.NormattivaError) as exc:
        await client.article_detail(nt.ActRef("1990-08-18", "090G0294"))
    assert not isinstance(exc.value, nt.NormattivaNotFound)


async def test_detail_without_data_is_not_found(client, api):
    api.post(URL_DETAIL).respond(200, json={"data": None})
    with pytest.raises(nt.NormattivaNotFound):
        await client.article_detail(nt.ActRef("1942-04-04", "042U0262"))


async def test_article_detail_request_body(client, api):
    route = api.post(URL_DETAIL).respond(200, json=detail_payload())
    atto = await client.article_detail(
        nt.ActRef("1988-09-12", "088G0458"), articolo=13, sotto_articolo=2, data_vigenza="2020-01-01"
    )
    assert "articoloHtml" in atto
    import json

    body = json.loads(route.calls.last.request.read())
    assert body["idArticolo"] == 13 and body["sottoArticolo"] == 2
    assert body["dataVigenza"] == "2020-01-01"
    assert body["codiceRedazionale"] == "088G0458"


async def test_resolve_citation_filters_by_number_and_date(client, api):
    api.post(URL_ADVANCED).respond(
        200,
        json=search_payload(
            search_item(codice="090G0001", numero="2410"),
            search_item(codice="090G0002", emanazione="1990-01-01T00:00:00Z"),
            search_item(codice="090G0003"),
        ),
    )
    cit = nt.parse_citation("legge 7 agosto 1990, n. 241")
    act = await client.resolve_citation(cit)
    assert act.ref.codice_redazionale == "090G0003"


async def test_resolve_citation_not_found(client, api):
    api.post(URL_ADVANCED).respond(200, json=search_payload())
    with pytest.raises(nt.NormattivaNotFound):
        await client.resolve_citation(nt.parse_citation("legge 1/1900"))


async def test_classe_provvedimento(client, api):
    import json

    def responder(request: httpx.Request) -> httpx.Response:
        classe = json.loads(request.read()).get("classeProvvedimento")
        items = [search_item()] if classe == nt.CLASSE_AGGIORNATO else []
        return httpx.Response(200, json=search_payload(*items))

    api.post(URL_ADVANCED).mock(side_effect=responder)
    act = nt.act_from_search_item(search_item())
    classe, item = await client.classe_provvedimento(act)
    assert classe == nt.CLASSE_AGGIORNATO
    assert item is not None and item["codiceRedazionale"] == "090G0294"


def test_n2ls_url_codici_in_allegato():
    cp = "urn:nir:stato:regio.decreto:1930-10-19;1398"
    cc = "urn:nir:stato:regio.decreto:1942-03-16;262"
    base = "https://www.normattiva.it/uri-res/N2Ls?"
    assert nt.n2ls_url(cp, "612-bis") == base + cp + ":1~art612bis"
    assert nt.n2ls_url(cc, "2043") == base + cc + ":2~art2043"
    # senza articolo: URL dell'atto invariato
    assert nt.n2ls_url(cp) == base + cp
    # altri atti invariati
    cpp = "urn:nir:stato:decreto.del.presidente.della.repubblica:1988-09-22;447"
    assert nt.n2ls_url(cpp, "380") == base + cpp + "~art380"
