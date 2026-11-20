"""Guardrail: allowlist, rate limit, fingerprint delle query, disclaimer, formattazione."""

from __future__ import annotations

import hashlib
import html
import re
import time
from collections import defaultdict, deque
from collections.abc import Callable

DISCLAIMER = "Informazione normativa di supporto, non parere legale."
TELEGRAM_MAX_CHARS = 4096
# Margine per l'espansione dovuta a escaping HTML e tag.
_RAW_CHUNK_CHARS = 3500

NORMATTIVA_HOME = "https://www.normattiva.it/"
# Link Normattiva verificabili: ELI e risolutore URN (formati verificati HTTP 200).
NORMATTIVA_LINK_RE = re.compile(r"https://www\.normattiva\.it/(?:eli/id/|uri-res/N2Ls\?)[^\s\"'<>)\]\\]+")

UNAUTHORIZED_MESSAGE = "Servizio non disponibile."
RATE_LIMITED_MESSAGE = "Hai raggiunto il limite di richieste. Riprova tra qualche minuto."


def is_authorized(user_id: int | None, allowed: frozenset[int]) -> bool:
    """True solo se l'utente è nell'allowlist (allowlist vuota = nessuno)."""
    return user_id is not None and user_id in allowed


class RateLimiter:
    """Finestra scorrevole in memoria: max `max_requests` ogni `window` secondi per utente."""

    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: float = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def allow(self, user_id: int) -> bool:
        """Registra una richiesta e ritorna False se il limite è superato."""
        now = self._clock()
        hits = self._hits[user_id]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True


def query_fingerprint(text: str) -> dict[str, object]:
    """Metadati loggabili di una query: hash troncato e lunghezza, mai il testo."""
    return {"q_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], "q_len": len(text)}


def sanitize_query(text: str, max_chars: int) -> str:
    """Rimuove caratteri di controllo e tronca la query."""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text)
    return " ".join(text.split())[:max_chars]


def ensure_disclaimer(text: str) -> str:
    """Garantisce che il disclaimer obbligatorio chiuda la risposta."""
    text = text.rstrip()
    if DISCLAIMER.lower() in text[-300:].lower():
        return text
    return f"{text}\n\n_{DISCLAIMER}_"


def _same_act(a: str, b: str) -> bool:
    return a == b or a.split("~", 1)[0] == b.split("~", 1)[0]


def ensure_verified_link(text: str, verified: list[str], *, max_links: int = 3) -> str:
    """Garantisce almeno un link Normattiva proveniente dai risultati dei tool.

    Un link nel testo conta solo se corrisponde (stesso atto) a un URL restituito
    dai tool; altrimenti si aggiunge la sezione "Fonti verificate". Senza URL
    verificati si rimanda alla ricerca diretta su Normattiva.
    """
    text = text.rstrip()
    in_text = NORMATTIVA_LINK_RE.findall(text)
    if any(_same_act(t, v) for t in in_text for v in verified):
        return text
    if verified:
        lines = [f"- [{url}]({url})" for url in dict.fromkeys(verified)][:max_links]
        return text + "\n\n**Fonti verificate su Normattiva**\n" + "\n".join(lines)
    return ensure_normattiva_link(text)


def ensure_normattiva_link(text: str) -> str:
    """Aggiunge il link al portale Normattiva se il testo non ne contiene; prima del disclaimer."""
    if "normattiva.it" in text:
        return text
    line = f"Fonte ufficiale: [Normattiva]({NORMATTIVA_HOME})"
    body = text.rstrip()
    tail = f"_{DISCLAIMER}_"
    if body.endswith(tail):
        return f"{body[: -len(tail)].rstrip()}\n\n{line}\n\n{tail}"
    return f"{body}\n\n{line}"


# ------------------------------------------------------------ formattazione ---


def split_message(text: str, limit: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """Divide il testo in parti <= limit, preferendo paragrafi, righe e spazi."""
    if limit <= 0:
        raise ValueError("limit deve essere positivo")
    chunks: list[str] = []
    rest = text.strip()
    while len(rest) > limit:
        window = rest[:limit]
        cut = max(window.rfind("\n\n"), -1)
        if cut < limit // 3:
            cut = window.rfind("\n")
        if cut < limit // 3:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        chunks.append(rest)
    return chunks


_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC = re.compile(r"(?<![\w*])_(?!\s)(.+?)(?<!\s)_(?![\w*])")
_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)


def markdown_to_telegram_html(text: str) -> str:
    """Converte un sottoinsieme sicuro di Markdown in HTML Telegram.

    Tutto il testo viene prima escapato: l'unico HTML prodotto sono i tag
    generati qui (b, i, code, a), sempre bilanciati.
    """
    links: list[tuple[str, str]] = []

    def _stash_link(m: re.Match[str]) -> str:
        links.append((m.group(1), m.group(2)))
        return f"\x00{len(links) - 1}\x00"

    text = _LINK.sub(_stash_link, text)
    out = html.escape(text, quote=False)
    out = _HEADING.sub(r"<b>\1</b>", out)
    out = _CODE.sub(r"<code>\1</code>", out)
    out = _BOLD.sub(r"<b>\1</b>", out)
    out = _ITALIC.sub(r"<i>\1</i>", out)

    def _restore(m: re.Match[str]) -> str:
        label, url = links[int(m.group(1))]
        return f'<a href="{html.escape(url, quote=True)}">{html.escape(label, quote=False)}</a>'

    return re.sub(r"\x00(\d+)\x00", _restore, out)


def render_for_telegram(text: str) -> list[tuple[str, str]]:
    """Restituisce [(html, testo_semplice_fallback)] con html <= 4096 caratteri."""
    parts: list[tuple[str, str]] = []
    for raw in split_message(text, _RAW_CHUNK_CHARS):
        rendered = markdown_to_telegram_html(raw)
        if len(rendered) <= TELEGRAM_MAX_CHARS:
            parts.append((rendered, raw))
        else:  # caso raro: troppo escaping, si ripiega su testo semplice escapato
            for piece in split_message(raw, TELEGRAM_MAX_CHARS // 2):
                parts.append((html.escape(piece, quote=False), piece))
    return parts
