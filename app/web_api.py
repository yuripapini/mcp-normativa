"""API della web app (Static Site): domanda libera, verifica, testo/riassunto di un articolo, scrittura testi.

Riusano la logica di LexBot. Accesso con codice condiviso (header X-Access-Code,
variabile WEB_ACCESS_CODE); rate limit per IP del client.
"""

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING, Annotated

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints

from app.guardrails import (
    RATE_LIMITED_MESSAGE,
    RateLimiter,
    ensure_normattiva_link,
    markdown_to_telegram_html,
)
from app.scrivi import TipoScritto, clean_text

if TYPE_CHECKING:
    from app.config import Settings
    from app.telegram_bot import LexBot
    from app.web_features import WebFeatures

log = structlog.get_logger("web_api")

# Id fittizio passato a LexBot per distinguere nei log il canale web da Telegram.
WEB_USER_ID = -1

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
LawId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Article = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
Destinatario = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


class AskBody(BaseModel):
    """Corpo di POST /api/ask."""

    question: Question


class VerificaBody(BaseModel):
    """Corpo di POST /api/verifica."""

    law_id: LawId


class ArticoloBody(BaseModel):
    """Corpo di POST /api/articolo e /api/riassumi."""

    law_id: LawId
    article: Article


class ScriviBody(BaseModel):
    """Corpo di POST /api/scrivi."""

    tipo: TipoScritto
    destinatario: Destinatario = ""
    istruzioni: Question


class WebAnswer(BaseModel):
    """Risposta: testo Markdown e HTML sicuro (solo tag b/i/code/a, link http/https)."""

    text: str
    html: str


class VerificaAnswer(WebAnswer):
    """Risposta di /api/verifica: con numero/anno ambiguo, le citazioni da proporre."""

    suggerimenti: list[str] = Field(default_factory=list)


class ScriviAnswer(BaseModel):
    """Risposta di /api/scrivi: oggetto (solo mail) e testo; HTML sicuro del testo."""

    oggetto: str
    testo: str
    html: str


def check_code(received: str | None, expected: str) -> bool:
    """Confronto a tempo costante del codice di accesso."""
    if not expected or not received:
        return False
    return hmac.compare_digest(received.strip().encode(), expected.strip().encode())


def client_key(request: Request) -> str:
    """IP del client (uvicorn con --proxy-headers lo ricava da X-Forwarded-For)."""
    return request.client.host if request.client else "sconosciuto"


def to_answer(text: str) -> WebAnswer:
    """Aggiunge il link Normattiva se manca e prepara l'HTML per il browser."""
    text = ensure_normattiva_link(text)
    return WebAnswer(text=text, html=markdown_to_telegram_html(text))


def build_web_router(settings: Settings) -> APIRouter:
    """Router /api: l'istanza LexBot e il limiter sono in app.state (impostati nel lifespan)."""
    router = APIRouter(prefix="/api")

    def _authorize(request: Request, code: str | None) -> LexBot:
        bot: LexBot | None = getattr(request.app.state, "web_bot", None)
        limiter: RateLimiter | None = getattr(request.app.state, "web_limiter", None)
        if not settings.web_enabled or bot is None or limiter is None:
            raise HTTPException(status_code=403, detail="Web app non attiva.")
        # Il limite vale anche per i codici errati: rallenta i tentativi a caso.
        if not limiter.allow(client_key(request)):
            log.info("web_rate_limited")
            raise HTTPException(status_code=429, detail=RATE_LIMITED_MESSAGE)
        if not check_code(code, settings.web_access_code):
            log.warning("web_unauthorized")
            raise HTTPException(status_code=401, detail="Codice di accesso non valido.")
        return bot

    @router.post("/accesso")
    async def accesso(request: Request, x_access_code: str | None = Header(default=None)) -> dict[str, bool]:
        """Verifica solo il codice (schermata di accesso della pagina)."""
        _authorize(request, x_access_code)
        return {"ok": True}

    @router.post("/ask")
    async def ask(
        body: AskBody, request: Request, x_access_code: str | None = Header(default=None)
    ) -> WebAnswer:
        bot = _authorize(request, x_access_code)
        return to_answer(await bot.handle_question(WEB_USER_ID, body.question))

    def _features(request: Request, code: str | None) -> WebFeatures:
        _authorize(request, code)
        return request.app.state.web_features

    @router.post("/verifica")
    async def verifica(
        body: VerificaBody, request: Request, x_access_code: str | None = Header(default=None)
    ) -> VerificaAnswer:
        bot = _authorize(request, x_access_code)
        res = await bot.verifica(WEB_USER_ID, body.law_id)
        ans = to_answer(res.text)
        return VerificaAnswer(text=ans.text, html=ans.html, suggerimenti=res.suggerimenti)

    @router.post("/articolo")
    async def articolo(
        body: ArticoloBody, request: Request, x_access_code: str | None = Header(default=None)
    ) -> WebAnswer:
        features = _features(request, x_access_code)
        return to_answer(await features.articolo(body.law_id, body.article))

    @router.post("/riassumi")
    async def riassumi(
        body: ArticoloBody, request: Request, x_access_code: str | None = Header(default=None)
    ) -> WebAnswer:
        features = _features(request, x_access_code)
        return to_answer(await features.riassumi(body.law_id, body.article))

    @router.post("/scrivi")
    async def scrivi(
        body: ScriviBody, request: Request, x_access_code: str | None = Header(default=None)
    ) -> ScriviAnswer:
        features = _features(request, x_access_code)
        istruzioni = clean_text(body.istruzioni, 4000)
        if not istruzioni:
            raise HTTPException(status_code=422, detail="Istruzioni mancanti.")
        destinatario = " ".join(clean_text(body.destinatario, 300).split())
        res = await features.scrivi(body.tipo, destinatario, istruzioni)
        return ScriviAnswer(oggetto=res.oggetto, testo=res.testo, html=markdown_to_telegram_html(res.testo))

    return router
