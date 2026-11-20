"""Scheda Scrivi: tipi di testo, richiesta per l'LLM e post-elaborazione della risposta."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

TipoScritto = Literal[
    "mail_richiesta",
    "mail_trasmissione",
    "mail_sollecito",
    "mail_risposta_cittadino",
    "mail_generica",
    "relazione_servizio",
    "descrizione_fatto",
    "verbale_violazione_cds",
    "verbale_accertamento",
]


@dataclass(frozen=True)
class Tipo:
    """Caratteristiche di un tipo di testo."""

    label: str
    mail: bool = False
    bozza: bool = False
    verbale: bool = False


TIPI: dict[str, Tipo] = {
    "mail_richiesta": Tipo("Mail: richiesta a ufficio o ente", mail=True),
    "mail_trasmissione": Tipo("Mail: trasmissione di atti o documenti", mail=True),
    "mail_sollecito": Tipo("Mail: sollecito", mail=True),
    "mail_risposta_cittadino": Tipo("Mail: risposta a un cittadino", mail=True),
    "mail_generica": Tipo("Mail: comunicazione generica", mail=True),
    "relazione_servizio": Tipo("Relazione di servizio", bozza=True),
    "descrizione_fatto": Tipo("Descrizione del fatto", bozza=True),
    "verbale_violazione_cds": Tipo(
        "Verbale: descrizione della violazione (Codice della strada)", bozza=True, verbale=True
    ),
    "verbale_accertamento": Tipo("Verbale di accertamento o constatazione", bozza=True, verbale=True),
}

BOZZA_PREFIX = "BOZZA - da verificare prima dell'uso."
PROMEMORIA_VERBALE = "Controllare dati, orari e norme sul modulo ufficiale prima della firma."

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_FORMAT = re.compile(
    r"^[ \t]*\**oggetto\**[ \t]*:[ \t]*\**(?P<oggetto>[^\n]*?)\**[ \t]*$"
    r"(?:\s*\n[ \t]*-{3,}[ \t]*$)?(?P<testo>.*)",
    re.IGNORECASE | re.DOTALL | re.MULTILINE,
)


def clean_text(text: str, max_chars: int) -> str:
    """Rimuove i caratteri di controllo (tranne a capo e tab) e tronca."""
    return _CONTROL.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()[:max_chars].strip()


def build_request(tipo: str, destinatario: str, istruzioni: str) -> str:
    """Messaggio utente per l'LLM."""
    t = TIPI[tipo]
    parts = [f"Tipo di testo: {t.label}"]
    if t.mail and destinatario:
        parts.append(f"Destinatario: {destinatario}")
    parts.append("Istruzioni dell'operatore:\n" + istruzioni)
    return "\n".join(parts)


def split_oggetto(text: str) -> tuple[str, str]:
    """Separa "OGGETTO: ...\\n---\\n<testo>"; senza formato tutto va nel testo."""
    text = text.strip()
    m = _FORMAT.search(text)
    if not m:
        return "", text
    return m.group("oggetto").strip(), m.group("testo").strip()


def finalize(tipo: str, raw: str) -> tuple[str, str]:
    """Oggetto e testo definitivi: avviso BOZZA e promemoria per relazioni e verbali."""
    t = TIPI[tipo]
    oggetto, testo = split_oggetto(raw)
    if t.bozza and not testo.lstrip().upper().startswith("BOZZA"):
        testo = f"{BOZZA_PREFIX}\n\n{testo}"
    if t.verbale:
        testo = f"{testo}\n\n{PROMEMORIA_VERBALE}"
    return oggetto, testo
