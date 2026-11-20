"""Adapter opzionale di *discovery* basato sull'API pubblica Lexifina Global law.

Lexifina (https://github.com/lexifina/italy-law, CC BY 4.0) indicizza i testi
Normattiva per articolo con ricerca full-text. Qui è usato SOLO per individuare
candidati (tipo, anno, numero, articolo): ogni candidato viene poi risolto e
verificato sull'API Normattiva OpenData, che resta l'unica fonte citata.

Disattivato di default (LEXIFINA_DISCOVERY_ENABLED=false) perché invia la query
dell'utente a un servizio di terze parti.

Endpoint verificato il 2026-11-20:
GET https://global-law.lexifina.com/v1/search_law?query=...&jurisdiction=italy
-> data.provisions: lista di percorsi tipo
   "italy/national/acts/normativa/legge/1990/108/art-002.md"
TODO(verifica API): lo schema non è documentato come stabile; in caso di
cambiamento l'adapter degrada a lista vuota senza bloccare la ricerca.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from mcp_server.normattiva import Citation

DEFAULT_LEXIFINA_URL = "https://global-law.lexifina.com/v1/search_law"

# Cartelle Lexifina -> chiavi ACT_TYPES di normattiva.py
_FOLDER_TO_TYPE = {
    "legge": "legge",
    "legge-costituzionale": "legge costituzionale",
    "decreto-legislativo": "decreto legislativo",
    "decreto-legge": "decreto legge",
    "dpr": "decreto del presidente della repubblica",
    "dpcm": "decreto del presidente del consiglio dei ministri",
    "regio-decreto": "regio decreto",
    "regio-decreto-legge": "regio decreto legge",
}

_PATH_RE = re.compile(
    r"^italy/national/acts/normativa/(?P<tipo>[a-z-]+)/(?P<anno>\d{4})/(?P<num>\d+)"
    r"(?:/art-(?P<art>\d+)(?:-(?P<suf>[a-z]+))?\.md)?"
)


@dataclass(frozen=True)
class Candidate:
    """Candidato non verificato proveniente dalla discovery."""

    citation: Citation
    path: str


def parse_provision_path(path: str) -> Candidate | None:
    """Converte un percorso Lexifina in una citazione (None se non statale/sconosciuto)."""
    m = _PATH_RE.match(path)
    if not m:
        return None
    type_key = _FOLDER_TO_TYPE.get(m.group("tipo"))
    if not type_key:
        return None
    art = None
    if m.group("art"):
        art = str(int(m.group("art")))
        if m.group("suf"):
            art = f"{art}-{m.group('suf')}"
    return Candidate(Citation(type_key, m.group("anno"), str(int(m.group("num"))), None, art), path)


class LexifinaDiscovery:
    """Client minimale per la discovery Lexifina."""

    def __init__(
        self,
        url: str = DEFAULT_LEXIFINA_URL,
        *,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = url
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def candidates(self, query: str, limit: int = 5) -> list[Candidate]:
        """Restituisce fino a `limit` atti candidati distinti. Mai solleva eccezioni."""
        try:
            resp = await self._client.get(self.url, params={"query": query, "jurisdiction": "italy"})
            resp.raise_for_status()
            provisions = resp.json().get("data", {}).get("provisions", [])
        except (httpx.HTTPError, ValueError, AttributeError):
            return []
        seen: dict[tuple[str, str, str | None], Candidate] = {}
        for path in provisions if isinstance(provisions, list) else []:
            cand = parse_provision_path(str(path))
            if cand is None:
                continue
            key = (cand.citation.type_key, cand.citation.anno, cand.citation.numero)
            seen.setdefault(key, cand)
            if len(seen) >= limit:
                break
        return list(seen.values())
