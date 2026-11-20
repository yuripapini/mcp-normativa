"""Indice tematico: struttura, nuovi temi penali e (con -m live) citazioni risolte su Normattiva."""

from __future__ import annotations

import pytest

from mcp_server import server
from mcp_server.normattiva import parse_citation

NUOVI = {
    "diritto-penale",
    "procedura-penale",
    "illeciti-amministrativi",
    "pubblica-sicurezza",
    "stupefacenti",
    "immigrazione",
    "armi",
    "codice-rosso",
}


def test_struttura():
    topics = server.load_topics()
    ids = [t["id"] for t in topics]
    assert len(ids) == len(set(ids))
    assert set(ids) >= NUOVI
    for t in topics:
        assert t["nome"] and t["sinonimi"] and t["atti"], t["id"]
        for a in t["atti"]:
            assert parse_citation(a["citazione"]) is not None, (t["id"], a["citazione"])


@pytest.mark.parametrize(
    ("query", "topic"),
    [
        ("come si fa un arresto in flagranza", "procedura-penale"),
        ("perquisizione domiciliare", "procedura-penale"),
        ("furto in abitazione", "diritto-penale"),
        ("contestazione di una sanzione amministrativa", "illeciti-amministrativi"),
        ("licenza tulps per un bar", "pubblica-sicurezza"),
        ("detenzione di stupefacenti per uso personale", "stupefacenti"),
        ("permesso di soggiorno scaduto", "immigrazione"),
        ("porto di un coltello in auto", "armi"),
        ("violenza domestica e codice rosso", "codice-rosso"),
        ("furti e rapine in zona", "diritto-penale"),
        ("denuncia per minaccia", "diritto-penale"),
        ("merce ricettata", "diritto-penale"),
        ("atti persecutori", "codice-rosso"),
        ("detenzione di hashish", "stupefacenti"),
        ("segnalazione prefetto", "stupefacenti"),
    ],
)
def test_sinonimi(query, topic):
    assert topic in {t["id"] for t in server.match_topics(query, None)}


@pytest.mark.parametrize(
    ("query", "topic"),
    [
        ("uso personale del telefono di servizio", "stupefacenti"),
        ("fermo amministrativo del veicolo", "procedura-penale"),
        ("ricetta della carbonara", "diritto-penale"),
    ],
)
def test_sinonimi_senza_falsi_positivi(query, topic):
    assert topic not in {t["id"] for t in server.match_topics(query, None)}


@pytest.mark.live
async def test_citazioni_risolte():
    client = server.get_client()
    for t in server.load_topics():
        if t["id"] not in NUOVI:
            continue
        for a in t["atti"]:
            act = await client.resolve_citation(parse_citation(a["citazione"]))
            assert act.ref.codice_redazionale, (t["id"], a["citazione"])
