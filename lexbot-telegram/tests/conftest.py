"""Fixture comuni: nessuna chiamata di rete reale (respx intercetta httpx)."""

from __future__ import annotations

import os
from typing import Any

os.environ.setdefault("RUNTIME_ENV", "test")

import pytest
import respx

from mcp_server import normattiva as nt
from mcp_server import server

API = nt.DEFAULT_API_URL
URL_SIMPLE = API + nt.PATH_SEARCH_SIMPLE
URL_ADVANCED = API + nt.PATH_SEARCH_ADVANCED
URL_DETAIL = API + nt.PATH_ARTICLE_DETAIL


def search_item(
    *,
    data_gu: str = "1990-08-18",
    codice: str = "090G0294",
    denominazione: str = "LEGGE",
    numero: str = "241",
    anno: str = "1990",
    emanazione: str = "1990-08-07T00:00:00Z",
    descrizione: str = "LEGGE 7 agosto 1990, n. 241",
    titolo: str = "[Nuove norme in materia di procedimento amministrativo. (090G0294)]",
    **extra: Any,
) -> dict[str, Any]:
    """Elemento di listaAtti con tutti i campi della specifica (par. 1.3.1/1.3.2)
    più quelli osservati nelle risposte reali (dataUltimaModifica, ultimiAttiModificanti).
    """
    giorno, mese = emanazione[8:10], emanazione[5:7]
    return {
        "numeroAtto": numero,
        "numeroAttoAlfanumerico": numero,
        "dataGU": data_gu,
        "numeroGU": "192",
        "codiceRedazionale": codice,
        "titoloAtto": titolo,
        "giornoProvvedimento": giorno.lstrip("0"),
        "meseProvvedimento": mese.lstrip("0"),
        "meseProvvedimentoIta": "agosto",
        "meseProvvedimentoEng": "August",
        "annoProvvedimento": anno,
        "numeroProvvedimento": numero,
        "denominazioneAtto": denominazione,
        "numeroSupplemento": "0",
        "tipoSupplemento": "NO",
        "suffissoArticoloSelezionato": 1,
        "subArt1ArticoloSelezionato": 0,
        "hlTitoli": None,
        "hlArticoli": None,
        "annoDataGU": data_gu[:4],
        "dataGUStr": f"{data_gu[8:10]}-{data_gu[5:7]}-{data_gu[:4]}",
        "tipoSupplementoIt": "",
        "tipoSupplementoEn": "",
        "dataEmanazione": emanazione,
        "descrizioneAtto": descrizione,
        "dataUltimaModifica": None,
        "ultimiAttiModificanti": None,
        **extra,
    }


def search_payload(*items: dict[str, Any]) -> dict[str, Any]:
    """Risposta di ricerca semplice/avanzata con la struttura reale (facetMap, paginazione)."""
    return {
        "listaAtti": list(items),
        "facetMap": {
            "anno_provvedimento": [],
            "codice_tipo_provvedimento": [],
            "descrizione_emettitore": [{"codice": "---", "valore": len(items), "descrizione": "STATO"}],
        },
        "numeroPagine": 1 if items else 0,
        "numeroAttiTrovati": len(items),
        "paginaCorrente": 1,
        "numeroElementiPerPagina": 0,
        "numeroFileRicerca": 0,
        "message": None,
    }


def detail_payload(
    html: str = '<div class="article-heading-akn">Art. 1 - Principi</div><p>Testo di prova.</p>',
    *,
    inizio: str = "20050308",
    fine: str = "99999999",
) -> dict[str, Any]:
    """Risposta di dettaglio-atto con la struttura del par. 1.3.7 (HTML di prova, non normativo)."""
    return {
        "code": None,
        "message": None,
        "success": True,
        "data": {
            "message": None,
            "atto": {
                "titolo": "LEGGE 7 agosto 1990, n. 241",
                "sottoTitolo": "Nuove norme in materia di procedimento amministrativo.\r\n",
                "dataPubblicazioneGazzetta": None,
                "articoloHtml": f'<div class="bodyTesto">{html}</div>',
                "tipoProvvedimentoDescrizione": "LEGGE",
                "tipoProvvedimentoCodice": "PLE",
                "annoProvvedimento": 1990,
                "meseProvvedimento": 8,
                "giornoProvvedimento": 7,
                "numeroProvvedimento": 241,
                "tipoSupplementoCode": "NO",
                "numeroSupplemento": 0,
                "annoGU": 1990,
                "meseGU": 8,
                "giornoGU": 18,
                "numeroGU": 192,
                "dataPubblicazioneInGazzetta": None,
                "articoloDataInizioVigenza": inizio,
                "articoloDataFineVigenza": fine,
                "testoInVigore": None,
            },
        },
    }


# Corpi di errore come da specifica (par. 1.3.1, 1.3.7, 1.3.10) e osservati in esercizio.
ERR_GATEWAY_404 = {
    "code": "404",
    "type": "Status report",
    "message": "Runtime Error",
    "description": "No matching resource found for given API Request",
}
ERR_ATTO_NON_TROVATO = {"message": "Atto non trovato", "code": None}
ERR_GENERIC_500 = {"message": "Errore generico della chiamata, riprovare più tardi", "code": "500"}


def err_spring(status: int, error: str, path: str = "/bff-opendata/api/v1/ricerca/semplice") -> dict:
    """Errore in formato par. 1.3.10: timestamp, status, error, path."""
    return {"timestamp": "2026-11-20T10:22:15.379+00:00", "status": status, "error": error, "path": path}


ERR_WAF_409 = {
    "status": "KO",
    "supportId": "5699325231325119944",
    "message": "La pagina richiesta è stata bloccata dai sistemi di protezione del Poligrafico "
    "e Zecca dello Stato Italiano",
}


@pytest.fixture
def api():
    """Router respx: ogni chiamata non mockata fallisce."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


@pytest.fixture
async def client(api):
    """Client Normattiva senza attese di backoff, iniettato nel server MCP."""
    c = nt.NormattivaClient(backoff_base=0)
    server.set_client(c)
    server.set_discovery(None)
    yield c
    server.set_client(None)
    server.set_discovery(None)
    await c.aclose()
