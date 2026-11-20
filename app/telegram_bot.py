"""Handler Telegram (python-telegram-bot v22) e logica dei comandi.

La logica è in LexBot.handle_* (pure, testabili senza Telegram); gli handler
PTB si limitano a controlli di accesso, invio e gestione errori.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import structlog
from telegram import LinkPreviewOptions, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.config import Settings
from app.guardrails import (
    DISCLAIMER,
    RATE_LIMITED_MESSAGE,
    UNAUTHORIZED_MESSAGE,
    RateLimiter,
    ensure_normattiva_link,
    is_authorized,
    query_fingerprint,
    render_for_telegram,
    sanitize_query,
)
from app.law_suggest import is_number_only, parse_number_year, suggest_law_ids
from app.llm import (
    RETRYABLE_STATUS,
    LLMError,
    LLMProvider,
    answer_question,
    build_provider,
    load_system_prompt,
)
from app.mcp_client import MCPToolClient

log = structlog.get_logger("telegram")

START_TEXT = f"""**Benvenuto in LexBot**

Cerco e consulto la legislazione italiana sulle fonti ufficiali ([Normattiva](https://www.normattiva.it/) e [Gazzetta Ufficiale](https://www.gazzettaufficiale.it/)) e ti restituisco norme, articoli, stato di vigenza e link diretti.

**Attenzione**: non sono un avvocato e non fornisco pareri legali.

**Esempi di domande**
- Quale legge disciplina l'accesso agli atti amministrativi?
- Cosa prevede l'art. 13-bis della legge 400/1988?
- Il d.lgs. 196/2003 è ancora in vigore?
- /verifica urn:nir:stato:legge:1990-08-07;241

_{DISCLAIMER}_"""

HELP_TEXT = f"""**Comandi**
- /start - presentazione ed esempi
- /aiuto - questo elenco
- /fonti - fonti ufficiali utilizzate
- /verifica <URN | ELI | URL Normattiva | citazione> - identifica la norma, verifica la vigenza e fornisce il link ufficiale

**Domande libere**
Scrivi una domanda in italiano: cerco le norme pertinenti, ne leggo gli articoli e ne verifico la vigenza prima di risponderti.

**Formati accettati da /verifica**
- `urn:nir:stato:legge:1990-08-07;241`
- `https://www.normattiva.it/eli/id/1990/08/18/090G0294/CONSOLIDATED`
- `legge 241/1990`, `d.lgs. 196/2003`, `dpr 445/2000`

Limite: 10 richieste ogni 5 minuti. Fonte: [Normattiva](https://www.normattiva.it/).

_{DISCLAIMER}_"""

FONTI_TEXT = f"""**Fonti ufficiali**
- [Normattiva](https://www.normattiva.it/) - il portale della legge vigente (IPZS)
- [Normattiva OpenData](https://dati.normattiva.it/) - API ufficiale usata per ricerche e testi
- [Gazzetta Ufficiale](https://www.gazzettaufficiale.it/) - testo ufficiale e definitivo

I testi Normattiva sono riprodotti con licenza CC BY 4.0; il solo testo ufficiale e definitivo è quello pubblicato in Gazzetta Ufficiale.

_{DISCLAIMER}_"""

GENERIC_ERROR = "Si è verificato un problema temporaneo nel recupero delle fonti. Riprova tra poco."
LLM_BUSY_ERROR = (
    "Il servizio di intelligenza artificiale è momentaneamente sovraccarico. "
    "Riprova tra un minuto; nel frattempo /verifica funziona senza IA."
)
LLM_ERROR = (
    "Il servizio di intelligenza artificiale non ha risposto correttamente. "
    "Riprova tra poco; nel frattempo /verifica funziona senza IA."
)
TIMEOUT_ERROR = "La ricerca ha richiesto troppo tempo. Prova a riformulare la domanda in modo più specifico."

# Testo con cui il server MCP segnala un atto inesistente (mcp_server/server.py, _guard).
NOT_FOUND_MARKER = "Nessun riferimento verificabile"

VERIFICA_HELP = (
    "Riferimento non riconosciuto. Indica tipo, numero e anno dell'atto. "
    "Esempi: `d.lgs. 285/1992`, `legge 241/1990`, `dpr 445/2000`."
)


@dataclass
class VerificaResult:
    """Esito di /verifica: testo Markdown e, se ambiguo, citazioni da proporre."""

    text: str
    suggerimenti: list[str] = field(default_factory=list)


def llm_error_message(exc: LLMError) -> str:
    """Messaggio utente per un errore del provider LLM."""
    return LLM_BUSY_ERROR if exc.status_code in RETRYABLE_STATUS else LLM_ERROR


_STATUS_LABEL = {
    "vigente": "vigente",
    "modificato": "vigente con modifiche (testo consolidato)",
    "abrogato": "abrogato",
    "sconosciuto": "non verificabile",
}


class LexBot:
    """Logica del bot indipendente da Telegram."""

    def __init__(
        self,
        settings: Settings,
        *,
        mcp: MCPToolClient | None = None,
        provider_factory: Callable[[], LLMProvider] | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.settings = settings
        if mcp is not None:
            self.mcp = mcp
        elif settings.mcp_inprocess:
            self.mcp = MCPToolClient.inprocess(timeout=settings.request_timeout_seconds)
        else:
            self.mcp = MCPToolClient(
                settings.effective_mcp_server_url,
                timeout=settings.request_timeout_seconds,
                auth_token=settings.mcp_auth_token,
            )
        self._provider_factory = provider_factory or (
            lambda: build_provider(
                settings.llm_provider,
                settings.llm_model,
                settings.openai_api_key,
                settings.openai_base_url,
                settings.request_timeout_seconds,
            )
        )
        self._provider: LLMProvider | None = None
        self.rate_limiter = rate_limiter or RateLimiter(
            settings.rate_limit_max_requests, settings.rate_limit_window_seconds
        )
        self.system_prompt = load_system_prompt()

    @property
    def provider(self) -> LLMProvider:
        """Provider LLM creato al primo utilizzo."""
        if self._provider is None:
            self._provider = self._provider_factory()
        return self._provider

    def check_access(self, user_id: int | None, *, rate_limited: bool) -> str | None:
        """Ritorna un messaggio di rifiuto oppure None se la richiesta può procedere."""
        if not is_authorized(user_id, self.settings.allowed_user_ids):
            log.warning("unauthorized_user", user_id=user_id)
            return UNAUTHORIZED_MESSAGE
        assert user_id is not None
        if rate_limited and not self.rate_limiter.allow(user_id):
            log.info("rate_limited", user_id=user_id)
            return RATE_LIMITED_MESSAGE
        return None

    async def handle_question(self, user_id: int, text: str) -> str:
        """Risponde a una domanda libera tramite LLM + tool MCP."""
        query = sanitize_query(text, self.settings.max_query_chars)
        started = time.perf_counter()
        meta = {"user_id": user_id, **query_fingerprint(query)}
        if len(query) < 3:
            return "Scrivi una domanda un po' più dettagliata."
        try:
            async with asyncio.timeout(self.settings.request_timeout_seconds * 4):
                async with self.mcp.session() as session:
                    result = await answer_question(
                        query,
                        self.provider,
                        session,
                        system_prompt=self.system_prompt,
                        max_rounds=self.settings.llm_max_tool_rounds,
                        llm_timeout=self.settings.request_timeout_seconds,
                    )
        except TimeoutError:
            log.warning("question_timeout", **meta)
            return TIMEOUT_ERROR
        except LLMError as exc:
            log.error("llm_error", error=str(exc), status=exc.status_code, **meta)
            return llm_error_message(exc)
        except Exception as exc:  # errori MCP/rete: mai far fallire il webhook
            log.error("question_failed", error_type=type(exc).__name__, **meta)
            return GENERIC_ERROR
        log.info(
            "question_answered",
            tools=result.tools_used,
            rounds=result.rounds,
            answer_len=len(result.text),
            duration_ms=round((time.perf_counter() - started) * 1000),
            **meta,
        )
        return result.text

    async def handle_verifica(self, user_id: int, law_id: str) -> str:
        """/verifica per Telegram: solo testo."""
        return (await self.verifica(user_id, law_id)).text

    async def verifica(self, user_id: int, law_id: str) -> VerificaResult:
        """Identificazione, vigenza, data di consultazione e link ufficiali.

        Con "numero/anno" senza tipo prova i tipi più comuni: se ne trova uno procede,
        se ne trova più di uno restituisce i suggerimenti.
        """
        law_id = sanitize_query(law_id, 500)
        if not law_id:
            return VerificaResult(
                "Uso: /verifica <URN | ELI | URL Normattiva | citazione>\nEsempio: /verifica legge 241/1990"
            )
        if is_number_only(law_id):
            return VerificaResult(VERIFICA_HELP)
        candidates = suggest_law_ids(law_id)
        meta = {"user_id": user_id, **query_fingerprint(law_id)}
        prefix = ""
        factor = 4 if candidates else 2
        try:
            async with asyncio.timeout(self.settings.request_timeout_seconds * factor):
                async with self.mcp.session() as session:
                    if candidates:
                        found = []
                        for cand in candidates:
                            src = json.loads(await session.call_tool("get_official_source", {"law_id": cand}))
                            if "errore" not in src:
                                found.append((cand, src))
                            elif NOT_FOUND_MARKER not in src["errore"]:
                                # Errore di rete/timeout di Normattiva: non è "atto inesistente".
                                log.warning("verifica_candidate_error", candidate=cand, **meta)
                                return VerificaResult(
                                    TIMEOUT_ERROR if "non ha risposto" in src["errore"] else GENERIC_ERROR
                                )
                        log.info("verifica_candidates", found=len(found), **meta)
                        if not found:
                            numero, anno = parse_number_year(law_id) or ("", "")
                            return VerificaResult(
                                f"Nessun atto trovato con numero {numero}/{anno}. {VERIFICA_HELP}"
                            )
                        if len(found) > 1:
                            return VerificaResult(format_suggestions(found), [c for c, _ in found])
                        cand, source = found[0]
                        prefix = f"Interpretato come **{cand}**.\n\n"
                    else:
                        source = json.loads(
                            await session.call_tool("get_official_source", {"law_id": law_id})
                        )
                        if "errore" in source:
                            if "non riconosciuto" in source["errore"].lower():
                                return VerificaResult(VERIFICA_HELP)
                            return VerificaResult(
                                ensure_normattiva_link(
                                    f"Non è stato possibile identificare la norma: {source['errore']}"
                                )
                            )
                    vig = json.loads(
                        await session.call_tool("check_law_vigence", {"law_id": source["law_id"]})
                    )
        except TimeoutError:
            log.warning("verifica_timeout", **meta)
            return VerificaResult(TIMEOUT_ERROR)
        except Exception as exc:
            log.error("verifica_failed", error_type=type(exc).__name__, **meta)
            return VerificaResult(GENERIC_ERROR)
        log.info("verifica_done", **meta)
        return VerificaResult(prefix + format_verifica(source, vig))


def format_verifica(source: dict[str, Any], vig: dict[str, Any]) -> str:
    """Formatta l'esito di /verifica in Markdown semplice."""
    lines = [f"**{source.get('descrizione_atto') or 'Atto'}**", ""]
    if "errore" in vig:
        lines.append(f"**Stato di vigenza**: non verificabile ({vig['errore']})")
    else:
        stato = _STATUS_LABEL.get(vig.get("stato", "sconosciuto"), "non verificabile")
        if not vig.get("stato_verificato"):
            stato += " (non verificato)"
        lines.append(f"**Stato di vigenza**: {stato}")
        if vig.get("motivazione"):
            lines.append(f"- {vig['motivazione']}")
        if vig.get("data_entrata_in_vigore"):
            lines.append(f"- Entrata in vigore: {vig['data_entrata_in_vigore']}")
        for change in vig.get("modifiche") or []:
            lines.append(f"- {change.get('tipo')}: {change.get('descrizione')}")
        for note in (vig.get("fonte") or {}).get("note") or []:
            lines.append(f"- Nota: {note}")
    lines.append("")
    if source.get("urn"):
        lines.append(f"**URN**: `{source['urn']}`")
    if source.get("eli"):
        lines.append(f"**ELI**: `{source['eli']}`")
    if source.get("url_normattiva"):
        lines.append(f"**Normattiva**: [testo vigente]({source['url_normattiva']})")
    if source.get("url_gazzetta_ufficiale"):
        lines.append(f"**Gazzetta Ufficiale**: [pubblicazione]({source['url_gazzetta_ufficiale']})")
    lines.append(f"**Data di consultazione**: {source.get('data_consultazione', 'n.d.')}")
    lines.append("")
    lines.append(f"_{DISCLAIMER}_")
    return "\n".join(lines)


def format_suggestions(found: list[tuple[str, dict[str, Any]]]) -> str:
    """Elenco degli atti trovati per un "numero/anno" ambiguo."""
    lines = ["Indica il tipo di atto. Trovati:", ""]
    for cand, src in found:
        desc = src.get("descrizione_atto") or cand
        url = src.get("url_normattiva")
        lines.append(f"- **{cand}** - [{desc}]({url})" if url else f"- **{cand}** - {desc}")
    lines += ["", f"Ripeti la verifica con il tipo, ad esempio: `{found[0][0]}`."]
    return "\n".join(lines)


# ------------------------------------------------------------ adapter PTB ---


_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


async def send_long_message(update: Update, text: str) -> None:
    """Invia una risposta suddivisa in messaggi <= 4096 caratteri, HTML sicuro."""
    message = update.effective_message
    if message is None:
        return
    for html_part, plain_part in render_for_telegram(text):
        try:
            await message.reply_text(html_part, parse_mode=ParseMode.HTML, link_preview_options=_NO_PREVIEW)
        except BadRequest:
            # Formattazione rifiutata da Telegram: si ripiega sul testo semplice.
            await message.reply_text(plain_part, link_preview_options=_NO_PREVIEW)


async def reply(update: Update, text: str) -> None:
    """Invia una risposta garantendo almeno un link Normattiva.

    Unica eccezione: il rifiuto agli utenti non autorizzati, che non rivela nulla del servizio.
    """
    if text != UNAUTHORIZED_MESSAGE:
        text = ensure_normattiva_link(text)
    await send_long_message(update, text)


def _user_id(update: Update) -> int | None:
    return update.effective_user.id if update.effective_user else None


def build_application(settings: Settings, bot_logic: LexBot | None = None) -> Application:
    """Crea l'Application PTB senza Updater (solo webhook)."""
    lex = bot_logic or LexBot(settings)
    application = Application.builder().token(settings.telegram_bot_token).updater(None).build()
    application.bot_data["lex"] = lex

    async def _static(update: Update, text: str) -> None:
        denial = lex.check_access(_user_id(update), rate_limited=False)
        await reply(update, denial or text)

    async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await _static(update, START_TEXT)

    async def aiuto(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await _static(update, HELP_TEXT)

    async def fonti(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await _static(update, FONTI_TEXT)

    async def verifica(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        uid = _user_id(update)
        if denial := lex.check_access(uid, rate_limited=True):
            await reply(update, denial)
            return
        assert uid is not None
        await _typing(update)
        await reply(update, await lex.handle_verifica(uid, " ".join(context.args or [])))

    async def question(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        uid = _user_id(update)
        if denial := lex.check_access(uid, rate_limited=True):
            await reply(update, denial)
            return
        assert uid is not None and update.effective_message is not None
        await _typing(update)
        await reply(update, await lex.handle_question(uid, update.effective_message.text or ""))

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("telegram_handler_error", error_type=type(context.error).__name__)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler(["aiuto", "help"], aiuto))
    application.add_handler(CommandHandler("fonti", fonti))
    application.add_handler(CommandHandler("verifica", verifica))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, question))
    application.add_error_handler(on_error)
    return application


async def _typing(update: Update) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    with contextlib.suppress(TelegramError):
        await chat.send_action(ChatAction.TYPING)
