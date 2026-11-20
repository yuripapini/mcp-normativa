"""Suggerimenti per /verifica quando manca il tipo di atto (es. "285/1992")."""

from __future__ import annotations

import re

# Tipi provati, in ordine di frequenza d'uso.
CANDIDATE_TYPES = ("legge", "d.lgs.", "d.l.", "d.p.r.")

_BARE = re.compile(r"^(?:n\.?\s*)?(\d{1,5})\s*(?:/\s*|del\s+|dell'anno\s+)(\d{4})$", re.IGNORECASE)
_ONLY_NUMBER = re.compile(r"^(?:n\.?\s*)?\d{1,5}$", re.IGNORECASE)


def _compact(text: str) -> str:
    return " ".join(text.split())


def parse_number_year(text: str) -> tuple[str, str] | None:
    """(numero, anno) se il testo è "numero/anno" senza tipo di atto, altrimenti None."""
    m = _BARE.match(_compact(text))
    if not m:
        return None
    return m.group(1).lstrip("0") or "0", m.group(2)


def suggest_law_ids(text: str) -> list[str] | None:
    """Citazioni candidate per "numero/anno" senza tipo; None se il testo non è in quella forma."""
    parsed = parse_number_year(text)
    if not parsed:
        return None
    numero, anno = parsed
    return [f"{tipo} {numero}/{anno}" for tipo in CANDIDATE_TYPES]


def is_number_only(text: str) -> bool:
    """True se il testo è solo un numero (manca almeno l'anno)."""
    return bool(_ONLY_NUMBER.match(_compact(text)))
