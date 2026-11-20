"""Suggerimenti di /verifica quando manca il tipo di atto."""

from __future__ import annotations

import pytest

from app.law_suggest import CANDIDATE_TYPES, is_number_only, suggest_law_ids
from mcp_server.normattiva import parse_citation

EXPECTED = ["legge 285/1992", "d.lgs. 285/1992", "d.l. 285/1992", "d.p.r. 285/1992"]


@pytest.mark.parametrize(
    "text",
    ["285/1992", " 285 / 1992 ", "n. 285/1992", "285 del 1992", "N. 285 del 1992", "n.285 dell'anno 1992"],
)
def test_suggest_bare_number_year(text):
    assert suggest_law_ids(text) == EXPECTED


@pytest.mark.parametrize("text", ["d.lgs. 285/1992", "legge 241/1990", "285", "abc", "285/92", ""])
def test_no_suggestion(text):
    assert suggest_law_ids(text) is None


def test_number_only():
    assert is_number_only("285") and is_number_only("n. 285") and is_number_only(" N.285 ")
    assert not is_number_only("285/1992") and not is_number_only("legge 285")


@pytest.mark.parametrize("tipo", CANDIDATE_TYPES)
def test_candidates_are_parsable(tipo):
    cit = parse_citation(f"{tipo} 285/1992")
    assert cit is not None and cit.numero == "285" and cit.anno == "1992"
