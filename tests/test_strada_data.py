"""Validità delle schede Strada (web/strada.js) e, con -m live, esistenza degli articoli su Normattiva."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from mcp_server import server
from mcp_server.normattiva import parse_law_id
from mcp_server.schemas import ArticleInput

STRADA_JS = Path(__file__).resolve().parents[1] / "web" / "strada.js"
REQUIRED = {"id", "titolo", "sinonimi", "law_id", "articolo", "controlli", "annotare"}
NUMERIC_SANCTION = re.compile(r"\d[\d.,]*\s*(?:euro|€)|\d+\s*punt|\bpunti\s*\d", re.IGNORECASE)


def load_schede() -> list[dict[str, Any]]:
    src = STRADA_JS.read_text(encoding="utf-8")
    m = re.search(r"/\* SCHEDE-INIZIO \*/(.*)/\* SCHEDE-FINE \*/", src, re.DOTALL)
    assert m, "marcatori SCHEDE-INIZIO/SCHEDE-FINE mancanti"
    return json.loads(m.group(1))


def test_schede_structure():
    schede = load_schede()
    assert len(schede) >= 15
    ids = [s["id"] for s in schede]
    assert len(ids) == len(set(ids))
    for s in schede:
        assert set(s) == REQUIRED, s["id"]
        assert re.fullmatch(r"\d+(?:-[a-z]+)?", s["articolo"]), s["id"]
        parse_law_id(s["law_id"])
        assert s["controlli"] and s["annotare"] and isinstance(s["sinonimi"], list)


def test_schede_have_no_amounts_or_points():
    for s in load_schede():
        for line in s["controlli"] + s["annotare"]:
            assert not NUMERIC_SANCTION.search(line), (s["id"], line)


@pytest.mark.live
async def test_articoli_esistono_su_normattiva():
    for s in load_schede():
        out = await server.get_law_article_impl(ArticleInput(law_id=s["law_id"], article=s["articolo"]))
        assert out.trovato, (s["id"], out.messaggio)
