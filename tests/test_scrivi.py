"""Tipi di testo della scheda Scrivi."""

from __future__ import annotations

from typing import get_args

from app.llm import PROMPTS_DIR
from app.scrivi import (
    BOZZA_PREFIX,
    PROMEMORIA_VERBALE,
    TIPI,
    TipoScritto,
    build_request,
    clean_text,
    finalize,
    split_oggetto,
)


def test_literal_matches_tipi():
    assert set(get_args(TipoScritto)) == set(TIPI)


def test_split_oggetto_formats():
    assert split_oggetto("OGGETTO: Richiesta atti\n---\nGentili colleghi,\nsaluti.") == (
        "Richiesta atti",
        "Gentili colleghi,\nsaluti.",
    )
    assert split_oggetto("**Oggetto**: X\n----\nCorpo") == ("X", "Corpo")
    assert split_oggetto("OGGETTO:\n---\nSolo testo") == ("", "Solo testo")
    assert split_oggetto("Testo senza formato") == ("", "Testo senza formato")


def test_finalize_mail_has_no_prefix():
    assert finalize("mail_sollecito", "OGGETTO: S\n---\nCorpo") == ("S", "Corpo")


def test_finalize_bozza_and_verbale():
    _, testo = finalize("relazione_servizio", "OGGETTO:\n---\nRelazione.")
    assert testo == f"{BOZZA_PREFIX}\n\nRelazione."
    _, testo = finalize("verbale_violazione_cds", "Circolava...")
    assert testo.startswith(BOZZA_PREFIX) and testo.endswith(PROMEMORIA_VERBALE)


def test_build_request():
    req = build_request("mail_richiesta", "Comune di X", "chiedere copia")
    assert "Tipo di testo: Mail: richiesta a ufficio o ente" in req
    assert "Destinatario: Comune di X" in req and req.endswith("chiedere copia")
    assert "Destinatario" not in build_request("relazione_servizio", "Comune di X", "fatti")


def test_clean_text_keeps_newlines():
    assert clean_text(" a\x00b\nc\t ", 10) == "a b\nc"
    assert clean_text("x" * 50, 5) == "xxxxx"


def test_prompts_exist():
    assert "[DA COMPLETARE]" in (PROMPTS_DIR / "scrivi.md").read_text(encoding="utf-8")
    assert "comma" in (PROMPTS_DIR / "riassumi.md").read_text(encoding="utf-8")


def test_split_oggetto_tolerant():
    assert split_oggetto("OGGETTO: S\nCorpo senza separatore") == ("S", "Corpo senza separatore")
    assert split_oggetto("Ecco il testo:\nOGGETTO: S\n---\nCorpo") == ("S", "Corpo")
    assert split_oggetto("OGGETTO: S\n---\n") == ("S", "")
    assert split_oggetto("OGGETTO: S") == ("S", "")


def test_finalize_no_duplicate_bozza():
    _, testo = finalize("relazione_servizio", "OGGETTO: S\n---\nbozza - controllare\n\nTesto")
    assert testo.lower().count("bozza") == 1


def test_clean_text_normalizes_newlines():
    assert clean_text("a\r\nb\rc", 10) == "a\nb\nc"


PG = ["verbale_denuncia", "annotazione_pg", "verbale_sit", "verbale_perquisizione", "verbale_identificazione"]


def test_tipi_pg():
    for tipo in PG:
        t = TIPI[tipo]
        assert t.pg and t.bozza and t.verbale and not t.mail, tipo
        _, testo = finalize(tipo, "OGGETTO: X\n---\nCorpo")
        assert testo.startswith(BOZZA_PREFIX) and testo.endswith(PROMEMORIA_VERBALE)
    assert not any(TIPI[k].pg for k in TIPI if k not in PG)


def test_prompt_copre_tipi_pg():
    prompt = (PROMPTS_DIR / "scrivi.md").read_text(encoding="utf-8")
    for tipo in PG:
        assert TIPI[tipo].label in prompt, tipo
    assert "[DENUNCIANTE]" in prompt and "[INDAGATO]" in prompt
