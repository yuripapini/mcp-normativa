"""Funzioni della web app: verifica con suggerimenti, articolo, riassunto, scrittura."""

from __future__ import annotations

import json
from typing import Any

from app.llm import LLMError
from app.models import LLMResult
from app.scrivi import BOZZA_PREFIX
from app.telegram_bot import GENERIC_ERROR, LLM_BUSY_ERROR, TIMEOUT_ERROR
from app.web_features import ARTICLE_NOT_FOUND, RIASSUNTO_NOTE, SCRITTO_EMPTY, WebFeatures
from tests.test_telegram_handler import FakeMCP, FakeProvider, FakeSession, make_bot

VIGENCE = {"stato": "vigente", "stato_verificato": True}


def source(desc: str, codice: str) -> dict[str, Any]:
    return {
        "law_id": f"1992-05-18:{codice}",
        "descrizione_atto": desc,
        "url_normattiva": f"https://www.normattiva.it/eli/id/1992/05/18/{codice}/CONSOLIDATED",
        "data_consultazione": "2026-11-20T10:00:00+00:00",
    }


class RoutedSession(FakeSession):
    """get_official_source risponde in base al law_id; gli altri tool da `results`."""

    def __init__(self, sources: dict[str, dict[str, Any]], results: dict[str, str] | None = None) -> None:
        super().__init__({"check_law_vigence": json.dumps(VIGENCE), **(results or {})})
        self.sources = sources
        self.not_found = "Atto non trovato. Nessun riferimento verificabile: non citare questa norma."

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls.append((name, arguments))
        if name == "get_official_source":
            src = self.sources.get(arguments["law_id"])
            if src:
                return json.dumps(src)
            return json.dumps({"errore": self.not_found})
        return self.results.get(name, "{}")


DLGS = source("DECRETO LEGISLATIVO 30 aprile 1992, n. 285", "092G0306")
LEGGE = source("LEGGE 1 giugno 1992, n. 285", "092G0999")


async def test_verifica_multiple_candidates_returns_suggestions():
    session = RoutedSession({"d.lgs. 285/1992": DLGS, "legge 285/1992": LEGGE})
    res = await make_bot(mcp=FakeMCP(session)).verifica(42, "285/1992")
    assert res.suggerimenti == ["legge 285/1992", "d.lgs. 285/1992"]
    assert res.text.startswith("Indica il tipo di atto")
    assert "DECRETO LEGISLATIVO 30 aprile 1992, n. 285" in res.text
    assert all(name == "get_official_source" for name, _ in session.calls)


async def test_verifica_single_candidate_goes_on():
    session = RoutedSession({"d.lgs. 285/1992": DLGS})
    res = await make_bot(mcp=FakeMCP(session)).verifica(42, "n. 285 del 1992")
    assert res.suggerimenti == []
    assert res.text.startswith("Interpretato come **d.lgs. 285/1992**")
    assert "**Stato di vigenza**: vigente" in res.text
    assert ("check_law_vigence", {"law_id": DLGS["law_id"]}) in session.calls


async def test_verifica_no_candidate_found():
    res = await make_bot(mcp=FakeMCP(RoutedSession({}))).verifica(42, "285/1992")
    assert res.text.startswith("Nessun atto trovato con numero 285/1992")
    assert res.suggerimenti == []


async def test_verifica_number_only_needs_no_call():
    session = RoutedSession({})
    res = await make_bot(mcp=FakeMCP(session)).verifica(42, "285")
    assert "Esempi" in res.text and session.calls == []


async def test_verifica_unrecognized_gives_help():
    session = FakeSession(
        {"get_official_source": json.dumps({"errore": "Identificativo non riconosciuto. Usa..."})}
    )
    res = await make_bot(mcp=FakeMCP(session)).verifica(42, "abc def")
    assert "Esempi" in res.text and "non riconosciuto" in res.text


async def test_verifica_candidate_timeout_is_not_reported_as_not_found():
    session = RoutedSession({"legge 285/1992": LEGGE})
    session.not_found = (
        "Normattiva non ha risposto entro il tempo massimo. Non è possibile verificare la norma ora."
    )
    res = await make_bot(mcp=FakeMCP(session)).verifica(42, "285/1992")
    assert res.text == TIMEOUT_ERROR and res.suggerimenti == []


async def test_verifica_candidate_other_error_is_generic():
    session = RoutedSession({})
    session.not_found = "Errore interno nell'elaborazione della risposta Normattiva."
    res = await make_bot(mcp=FakeMCP(session)).verifica(42, "285/1992")
    assert res.text == GENERIC_ERROR


async def test_verifica_other_error_gives_normattiva_link():
    session = FakeSession({"get_official_source": json.dumps({"errore": "Normattiva non raggiungibile"})})
    res = await make_bot(mcp=FakeMCP(session)).verifica(42, "legge 241/1990")
    assert res.text.startswith("Non è stato possibile identificare la norma: Normattiva non raggiungibile")
    assert "normattiva.it" in res.text


ARTICLE = {
    "trovato": True,
    "descrizione_atto": "DECRETO LEGISLATIVO 30 aprile 1992, n. 285",
    "law_id": "1992-05-18:092G0306",
    "articoli": [
        {
            "articolo": "172",
            "rubrica": "Uso delle cinture di sicurezza",
            "testo_essenziale": "1. Il conducente ... 10. Chiunque non fa uso ...",
            "troncato": False,
            "vigenza_dal": "2024-12-14",
            "abrogato": False,
            "url_articolo": "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:decreto.legislativo:1992-04-30;285~art172",
        }
    ],
    "url_ufficiale": "https://www.normattiva.it/eli/id/1992/05/18/092G0306/CONSOLIDATED",
    "fonte": {"data_consultazione": "2026-11-20T10:00:00+00:00"},
}


class RaisingProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages, tools, *, tool_choice="auto"):
        self.calls += 1
        raise LLMError("busy", status_code=429)


def features(session=None, provider=None, **kwargs) -> WebFeatures:
    bot = make_bot(
        mcp=FakeMCP(session or FakeSession({"get_law_article": json.dumps(ARTICLE)})),
        provider_factory=lambda: provider or FakeProvider([LLMResult(content="ok")]),
    )
    return WebFeatures(bot, **kwargs)


async def test_articolo_formats_text_without_llm():
    text = await features().articolo("d.lgs. 285/1992", "172")
    assert text.startswith("**DECRETO LEGISLATIVO 30 aprile 1992, n. 285 - art. 172**")
    assert "**Stato di vigenza**: vigente (articolo)" in text
    assert "10. Chiunque non fa uso" in text
    assert "N2Ls?urn:nir:stato:decreto.legislativo:1992-04-30;285~art172" in text


async def test_articolo_not_found_and_error():
    missing = {
        "trovato": False,
        "messaggio": "Il testo dell'art. 999 non è disponibile",
        "url_ufficiale": "https://www.normattiva.it/x",
    }
    text = await features(FakeSession({"get_law_article": json.dumps(missing)})).articolo(
        "d.lgs. 285/1992", "999"
    )
    assert text.startswith("Il testo dell'art. 999") and "https://www.normattiva.it/x" in text
    err = await features(FakeSession({"get_law_article": json.dumps({"errore": "x"})})).articolo("boh", "1")
    assert err.startswith(ARTICLE_NOT_FOUND)


async def test_riassumi_calls_llm_without_tools():
    provider = FakeProvider([LLMResult(content="- **Sanzione pecuniaria**: ... (c. 10)")])
    text = await features(provider=provider).riassumi("d.lgs. 285/1992", "172")
    assert provider.tool_counts == [0]
    assert "(c. 10)" in text and RIASSUNTO_NOTE in text and "art172" in text


async def test_riassumi_llm_error_message():
    text = await features(provider=RaisingProvider()).riassumi("d.lgs. 285/1992", "172")
    assert text == LLM_BUSY_ERROR


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_riassumi_cache_hit_and_ttl():
    clock = Clock()
    provider = FakeProvider([LLMResult(content="primo"), LLMResult(content="secondo")])
    feat = features(provider=provider, clock=clock)
    first = await feat.riassumi("d.lgs. 285/1992", "172")
    again = await feat.riassumi("  D.Lgs.  285/1992 ", " 172 ")
    assert again == first and provider.tool_counts == [0]
    clock.now += 24 * 3600
    await feat.riassumi("d.lgs. 285/1992", "172")
    assert provider.tool_counts == [0]  # ancora entro il TTL
    clock.now += 1
    text = await feat.riassumi("d.lgs. 285/1992", "172")
    assert provider.tool_counts == [0, 0] and "secondo" in text


async def test_riassumi_errors_not_cached():
    provider = RaisingProvider()
    feat = features(provider=provider)
    assert await feat.riassumi("d.lgs. 285/1992", "172") == LLM_BUSY_ERROR
    assert await feat.riassumi("d.lgs. 285/1992", "172") == LLM_BUSY_ERROR
    assert provider.calls == 2
    missing = {"trovato": False, "messaggio": "non disponibile"}
    session = FakeSession({"get_law_article": json.dumps(missing)})
    feat = features(session)
    await feat.riassumi("x", "1")
    await feat.riassumi("x", "1")
    assert [c[0] for c in session.calls] == ["get_law_article"] * 2


async def test_riassumi_cache_max_entries_evicts_oldest():
    clock = Clock()
    provider = FakeProvider([LLMResult(content=f"r{i}") for i in range(300)])
    feat = features(provider=provider, clock=clock)
    for i in range(201):
        clock.now += 1
        await feat.riassumi("d.lgs. 285/1992", str(i))
    assert len(feat._riassunti) == 200
    assert ("d.lgs. 285/1992", "0") not in feat._riassunti


async def test_scrivi_mail_and_verbale():
    provider = FakeProvider([LLMResult(content="OGGETTO: Richiesta atti\n---\nGentili colleghi, [TARGA_1].")])
    res = await features(provider=provider).scrivi("mail_richiesta", "Comune", "chiedere atti per [TARGA_1]")
    assert provider.choices == ["auto"]
    assert (res.oggetto, res.testo) == ("Richiesta atti", "Gentili colleghi, [TARGA_1].")
    provider = FakeProvider([LLMResult(content="OGGETTO:\n---\nCircolava ...")])
    res = await features(provider=provider).scrivi("verbale_violazione_cds", "", "cinture")
    assert res.oggetto == "" and res.testo.startswith(BOZZA_PREFIX)


async def test_scrivi_empty_llm_output_gives_clear_message():
    provider = FakeProvider([LLMResult(content="   ")])
    res = await features(provider=provider).scrivi("verbale_violazione_cds", "", "cinture")
    assert (res.oggetto, res.testo) == ("", SCRITTO_EMPTY)
    assert BOZZA_PREFIX not in res.testo


async def test_riassumi_cache_key_normalizes_article_and_shares_canonical_law():
    art = {**ARTICLE["articoli"][0], "articolo": "126bis"}
    session = FakeSession({"get_law_article": json.dumps({**ARTICLE, "articoli": [art]})})
    provider = FakeProvider([LLMResult(content="uno"), LLMResult(content="due")])
    feat = features(session, provider)
    first = await feat.riassumi("d.lgs. 285/1992", "126-bis")
    assert await feat.riassumi("d.lgs. 285/1992", "126 bis") == first  # stessa chiave, niente fetch
    assert len(session.calls) == 1
    # altro nome dell'atto: fetch MCP, ma stesso law_id restituito -> riassunto condiviso
    assert await feat.riassumi("decreto legislativo 285/1992", "126bis") == first
    assert len(session.calls) == 2 and provider.tool_counts == [0]


async def test_articolo_and_riassumi_robust_to_malformed_mcp_json():
    for payload in (
        "[1, 2]",
        '"x"',
        "null",
        json.dumps({"trovato": True, "articoli": [{}]}),
        json.dumps({"trovato": True, "articoli": "x"}),
    ):
        feat = features(FakeSession({"get_law_article": payload}))
        a = await feat.articolo("x", "1")
        r = await feat.riassumi("x", "1")
        assert a.startswith((ARTICLE_NOT_FOUND, GENERIC_ERROR))
        assert r.startswith((ARTICLE_NOT_FOUND, GENERIC_ERROR))


async def test_riassumi_timeout_and_mcp_error_not_cached():
    class SlowProvider:
        calls = 0

        async def complete(self, messages, tools, *, tool_choice="auto"):
            SlowProvider.calls += 1
            raise TimeoutError

    feat = features(provider=SlowProvider())
    assert await feat.riassumi("x", "1") == TIMEOUT_ERROR
    assert await feat.riassumi("x", "1") == TIMEOUT_ERROR
    assert SlowProvider.calls == 2
    session = FakeSession({"get_law_article": json.dumps({"errore": "boom"})})
    feat = features(session)
    assert (await feat.riassumi("x", "1")).startswith(ARTICLE_NOT_FOUND)
    await feat.riassumi("x", "1")
    assert len(session.calls) == 2 and not feat._riassunti


async def test_cache_eviction_prefers_expired_entries():
    from app.web_features import RIASSUNTI_MAX_ENTRIES, RIASSUNTI_TTL_SECONDS

    clock = Clock()
    feat = features(clock=clock)
    feat._cache_put(("a", "1"), "old")  # la più vecchia, ma verrà rimossa per ultima
    clock.now += 10
    feat._cache_put(("b", "1"), "mid")
    for i in range(RIASSUNTI_MAX_ENTRIES - 2):
        feat._cache_put(("c", str(i)), "x")
    clock.now += RIASSUNTI_TTL_SECONDS - 5  # ("a","1") scaduta, le altre no
    feat._cache_put(("z", "z"), "new")
    assert ("a", "1") not in feat._riassunti and ("b", "1") in feat._riassunti
    assert len(feat._riassunti) == RIASSUNTI_MAX_ENTRIES
