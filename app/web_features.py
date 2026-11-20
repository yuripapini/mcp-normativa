"""Funzioni della web app oltre Domanda/Verifica: testo di un articolo, riassunto, scrittura testi.

Riusano client MCP e provider LLM di LexBot. Nei log mai testo dell'utente né output dell'LLM.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from app.llm import PROMPTS_DIR, LLMError, answer_question, load_system_prompt
from app.models import ChatMessage
from app.scrivi import build_request, finalize
from app.telegram_bot import GENERIC_ERROR, TIMEOUT_ERROR, LexBot, llm_error_message

log = structlog.get_logger("web_features")

ARTICLE_NOT_FOUND = "Articolo non trovato su Normattiva."
RIASSUNTO_NOTE = "Riassunto automatico: verificare sul testo ufficiale."
RIASSUNTO_EMPTY = "Il riassunto non è disponibile: consulta il testo vigente."
SCRITTO_EMPTY = "Il servizio di intelligenza artificiale non ha prodotto alcun testo. Riprova tra poco."

RIASSUNTI_TTL_SECONDS = 24 * 3600
RIASSUNTI_MAX_ENTRIES = 200


@dataclass
class Scritto:
    """Testo prodotto da Scrivi."""

    oggetto: str
    testo: str


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def first_article(data: dict[str, Any]) -> dict[str, Any] | None:
    """Primo articolo dell'output di get_law_article, se trovato."""
    arts = data.get("articoli")
    if not data.get("trovato") or not isinstance(arts, list) or not arts:
        return None
    first = arts[0]
    return first if isinstance(first, dict) and "articolo" in first else None


def _consultazione(data: dict[str, Any]) -> str:
    return (data.get("fonte") or {}).get("data_consultazione") or "n.d."


def _article_url(data: dict[str, Any], art: dict[str, Any]) -> str | None:
    return art.get("url_articolo") or data.get("url_ufficiale")


def format_articolo(data: dict[str, Any]) -> str:
    """Testo vigente di un articolo in Markdown semplice."""
    if "errore" in data:
        return f"{ARTICLE_NOT_FOUND} ({data['errore']})"
    art = first_article(data)
    if art is None:
        msg = data.get("messaggio") or ARTICLE_NOT_FOUND
        link = data.get("url_ufficiale")
        return msg + (f"\n\n**Normattiva**: [testo ufficiale]({link})" if link else "")
    head = f"**{data.get('descrizione_atto') or 'Atto'} - art. {art['articolo']}**"
    if art.get("rubrica"):
        head += f"\n{art['rubrica']}"
    stato = "abrogato" if art.get("abrogato") else "vigente"
    lines = [head, "", f"**Stato di vigenza**: {stato} (articolo)"]
    if art.get("vigenza_dal"):
        lines.append(f"- In vigore dal: {art['vigenza_dal']}")
    lines += ["", (art.get("testo_essenziale") or "").strip()]
    if art.get("troncato"):
        lines += ["", "_Testo troncato: leggi il resto su Normattiva._"]
    lines.append("")
    url = _article_url(data, art)
    if url:
        lines.append(f"**Normattiva**: [testo dell'articolo]({url})")
    lines.append(f"**Data di consultazione**: {_consultazione(data)}")
    return "\n".join(lines)


def riassumi_input(data: dict[str, Any], art: dict[str, Any]) -> str:
    """Messaggio utente per il riassunto: solo il testo dell'articolo."""
    head = f"Atto: {data.get('descrizione_atto') or ''}\nArticolo {art['articolo']}"
    if art.get("rubrica"):
        head += f" - {art['rubrica']}"
    tail = "\n\n[Testo troncato]" if art.get("troncato") else ""
    return f"{head}\n\nTesto vigente:\n{art.get('testo_essenziale') or ''}{tail}"


def format_riassunto(body: str, data: dict[str, Any], art: dict[str, Any]) -> str:
    """Riassunto con fonte, data di consultazione e avvertenza."""
    lines = [f"**Riassunto - {data.get('descrizione_atto') or 'Atto'} art. {art['articolo']}**", "", body, ""]
    url = _article_url(data, art)
    if url:
        lines.append(f"**Normattiva**: [testo dell'articolo]({url})")
    lines += [f"**Data di consultazione**: {_consultazione(data)}", "", f"_{RIASSUNTO_NOTE}_"]
    return "\n".join(lines)


class WebFeatures:
    """Articolo, riassunto e scrittura testi per la web app."""

    def __init__(self, bot: LexBot, clock: Callable[[], float] = time.monotonic) -> None:
        self.bot = bot
        self._clock = clock
        self._riassunti: dict[tuple[str, str], tuple[float, str]] = {}
        self.prompt_riassumi = load_system_prompt(PROMPTS_DIR / "riassumi.md")
        self.prompt_scrivi = load_system_prompt(PROMPTS_DIR / "scrivi.md")

    @property
    def _timeout(self) -> float:
        return float(self.bot.settings.request_timeout_seconds)

    @staticmethod
    def _cache_key(law_id: str, article: str) -> tuple[str, str]:
        return re.sub(r"\s+", " ", law_id.strip().lower()), re.sub(r"[\s\-]+", "", article.lower())

    def _cache_get(self, key: tuple[str, str]) -> str | None:
        entry = self._riassunti.get(key)
        if entry is None:
            return None
        stored_at, text = entry
        if self._clock() - stored_at > RIASSUNTI_TTL_SECONDS:
            del self._riassunti[key]
            return None
        return text

    def _cache_put(self, key: tuple[str, str], text: str) -> None:
        now = self._clock()
        if key not in self._riassunti and len(self._riassunti) >= RIASSUNTI_MAX_ENTRIES:
            expired = [k for k, (t, _) in self._riassunti.items() if now - t > RIASSUNTI_TTL_SECONDS]
            # senza voci scadute si elimina la più vecchia (il dict conserva l'ordine di inserimento)
            for k in expired or [next(iter(self._riassunti))]:
                del self._riassunti[k]
        self._riassunti.pop(key, None)
        self._riassunti[key] = (now, text)

    async def _fetch_article(self, law_id: str, article: str) -> dict[str, Any]:
        async with self.bot.mcp.session() as session:
            raw = await session.call_tool("get_law_article", {"law_id": law_id, "article": article})
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("risposta MCP non valida")
        return data

    async def articolo(self, law_id: str, article: str) -> str:
        """Testo vigente di un articolo, senza LLM."""
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self._timeout * 2):
                data = await self._fetch_article(law_id, article)
        except TimeoutError:
            log.warning("articolo_timeout")
            return TIMEOUT_ERROR
        except Exception as exc:
            log.error("articolo_failed", error_type=type(exc).__name__)
            return GENERIC_ERROR
        log.info("articolo_done", trovato=bool(first_article(data)), duration_ms=_ms(started))
        return format_articolo(data)

    async def riassumi(self, law_id: str, article: str) -> str:
        """Riassunto IA (senza tool) di sanzioni, punti e accessorie dal testo vigente."""
        started = time.perf_counter()
        key = self._cache_key(law_id, article)
        cached = self._cache_get(key)
        if cached is not None:
            log.info("riassumi_cache_hit")
            return cached
        try:
            async with asyncio.timeout(self._timeout * 3):
                data = await self._fetch_article(law_id, article)
                art = first_article(data)
                if art is None:
                    return format_articolo(data)
                canonical = self._cache_key(str(data.get("law_id") or law_id), str(art["articolo"]))
                cached = self._cache_get(canonical)
                if cached is not None:
                    log.info("riassumi_cache_hit")
                    self._cache_put(key, cached)
                    return cached
                messages = [
                    ChatMessage(role="system", content=self.prompt_riassumi),
                    ChatMessage(role="user", content=riassumi_input(data, art)),
                ]
                result = await asyncio.wait_for(
                    self.bot.provider.complete(messages, []), timeout=self._timeout
                )
        except TimeoutError:
            log.warning("riassumi_timeout")
            return TIMEOUT_ERROR
        except LLMError as exc:
            log.error("llm_error", error=str(exc), status=exc.status_code, feature="riassumi")
            return llm_error_message(exc)
        except Exception as exc:
            log.error("riassumi_failed", error_type=type(exc).__name__)
            return GENERIC_ERROR
        body = (result.content or "").strip()
        log.info("riassumi_done", chars=len(body), duration_ms=_ms(started))
        text = format_riassunto(body or RIASSUNTO_EMPTY, data, art)
        if body:  # in cache solo i riassunti riusciti
            self._cache_put(canonical, text)
            self._cache_put(key, text)
        return text

    async def scrivi(self, tipo: str, destinatario: str, istruzioni: str) -> Scritto:
        """Bozza di un testo d'ufficio; le norme eventualmente citate passano dai tool MCP."""
        started = time.perf_counter()
        settings = self.bot.settings
        request = build_request(tipo, destinatario, istruzioni)
        try:
            async with asyncio.timeout(self._timeout * 4):
                async with self.bot.mcp.session() as session:
                    result = await answer_question(
                        request,
                        self.bot.provider,
                        session,
                        system_prompt=self.prompt_scrivi,
                        max_rounds=settings.llm_max_tool_rounds,
                        llm_timeout=self._timeout,
                        require_tools=False,
                        postprocess=False,
                    )
        except TimeoutError:
            log.warning("scrivi_timeout", tipo=tipo)
            return Scritto("", TIMEOUT_ERROR)
        except LLMError as exc:
            log.error("llm_error", error=str(exc), status=exc.status_code, feature="scrivi")
            return Scritto("", llm_error_message(exc))
        except Exception as exc:
            log.error("scrivi_failed", error_type=type(exc).__name__, tipo=tipo)
            return Scritto("", GENERIC_ERROR)
        if not result.text.strip():
            log.warning("scrivi_empty", tipo=tipo, duration_ms=_ms(started))
            return Scritto("", SCRITTO_EMPTY)
        oggetto, testo = finalize(tipo, result.text)
        log.info(
            "scrivi_done",
            tipo=tipo,
            tools=result.tools_used,
            rounds=result.rounds,
            chars=len(testo),
            duration_ms=_ms(started),
        )
        return Scritto(oggetto, testo)
