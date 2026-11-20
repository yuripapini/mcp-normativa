"""Coerenza tra le option di #scrivi-tipo in web/index.html e i tipi di app/scrivi.py."""

from __future__ import annotations

import re
from pathlib import Path

from app.scrivi import TIPI

HTML = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")


def _options() -> list[tuple[str, str]]:
    select = re.search(r'<select id="scrivi-tipo">(.*?)</select>', HTML, re.S)
    assert select
    return re.findall(r"<option value=\"([^\"]+)\"([^>]*)>", select.group(1))


def test_option_pg_coincidono_con_tipi_pg():
    pg = {v for v, attrs in _options() if 'data-pg="1"' in attrs}
    assert pg == {k for k, t in TIPI.items() if t.pg}


def test_ogni_option_esiste_in_tipi():
    valori = [v for v, _ in _options()]
    assert valori
    assert set(valori) <= set(TIPI)


def test_elementi_usati_da_initscrivi_presenti():
    # panels.js nasconde il suggerimento sul mascheramento per i tipi PG e mostra avviso e blocco.
    for el_id in ("scrivi-hint", "scrivi-pg-avviso", "scrivi-guard"):
        assert f'id="{el_id}"' in HTML
