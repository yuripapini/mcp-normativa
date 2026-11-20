"""Schede Indagini (web/indagini.js): struttura, divieto di pene/termini e (live) articoli su Normattiva."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.scrivi import TIPI
from mcp_server import server
from mcp_server.normattiva import n2ls_url, parse_law_id
from mcp_server.schemas import ArticleInput

SRC = Path(__file__).resolve().parents[1] / "web" / "indagini.js"
BASE = {"id", "gruppo", "titolo", "sinonimi", "law_id", "articolo", "fonte", "controlli", "annotare"}
OPTIONAL = {"scrivi", "url"}
CP_URN = "urn:nir:stato:regio.decreto:1930-10-19;1398"
VIETATI = re.compile(r"\d+\s*(?:anni|anno|mesi|mese|giorni|giorno|ore)\b|euro|€|reclusione da|multa da", re.I)


def load() -> list[dict[str, Any]]:
    m = re.search(r"/\* INDAGINI-INIZIO \*/(.*)/\* INDAGINI-FINE \*/", SRC.read_text(encoding="utf-8"), re.S)
    assert m, "marcatori INDAGINI-INIZIO/INDAGINI-FINE mancanti"
    return json.loads(m.group(1))


def test_struttura():
    schede = load()
    assert len(schede) >= 30
    ids = [s["id"] for s in schede]
    assert len(ids) == len(set(ids))
    for s in schede:
        assert BASE <= set(s) <= BASE | OPTIONAL, s["id"]
        assert re.fullmatch(r"\d+(?:-[a-z]+)?", s["articolo"]), s["id"]
        parse_law_id(s["law_id"])
        assert s["fonte"] in {"api", "link"}, s["id"]
        assert s["controlli"] and s["annotare"] and s["gruppo"], s["id"]
        if "scrivi" in s:
            assert TIPI[s["scrivi"]].pg, s["id"]
        if s["fonte"] == "link":
            assert s["law_id"] == "r.d. 1398/1930", s["id"]
            assert s["url"] == n2ls_url(CP_URN, s["articolo"]), s["id"]
        else:
            assert "url" not in s, s["id"]


def test_nessuna_pena_o_termine():
    for s in load():
        for line in s["controlli"] + s["annotare"]:
            assert not VIETATI.search(line), (s["id"], line)


@pytest.mark.live
async def test_articoli_api_su_normattiva():
    for s in load():
        if s["fonte"] != "api":
            continue
        out = await server.get_law_article_impl(ArticleInput(law_id=s["law_id"], article=s["articolo"]))
        assert out.trovato, (s["id"], out.messaggio)
