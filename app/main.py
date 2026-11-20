"""App FastAPI: webhook Telegram, API della web app e health check.

Avvio: uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
"""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update
from telegram.error import TelegramError

from app.config import Settings, configure_logging, get_settings
from app.guardrails import RateLimiter
from app.web_api import build_web_router

if TYPE_CHECKING:
    from app.telegram_bot import LexBot

log = structlog.get_logger("main")

UpdateProcessor = Callable[[dict[str, Any]], Awaitable[None]]


def verify_secret(received: str | None, expected: str) -> bool:
    """Confronto a tempo costante del secret token del webhook."""
    if not expected or not received:
        return False
    return hmac.compare_digest(received.encode(), expected.encode())


def create_app(
    settings: Settings | None = None,
    processor: UpdateProcessor | None = None,
    web_bot: LexBot | None = None,
) -> FastAPI:
    """Costruisce l'app. `processor` e `web_bot` permettono di iniettare dipendenze nei test."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    tasks: set[asyncio.Task[None]] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        application = None
        if processor is not None:
            app.state.processor = processor
        elif settings.telegram_bot_token:
            from app.telegram_bot import build_application

            application = build_application(settings)
            await application.initialize()
            await application.start()

            async def _process(data: dict[str, Any]) -> None:
                await application.process_update(Update.de_json(data, application.bot))

            app.state.processor = _process
            mcp_client = application.bot_data["lex"].mcp
            log.info("mcp_transport", transport=getattr(mcp_client, "transport", "custom"))
            if not settings.is_test:
                await _set_webhook(application, settings)
        else:
            log.warning("telegram_disabled", reason="TELEGRAM_BOT_TOKEN mancante")
            app.state.processor = None
        _setup_web(app, settings, application, web_bot)
        try:
            yield
        finally:
            for task in list(tasks):
                task.cancel()
            if application is not None:
                await application.stop()
                await application.shutdown()

    app = FastAPI(title="lexbot-telegram", docs_url=None, redoc_url=None, lifespan=lifespan)
    if settings.web_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.web_origin],
            allow_methods=["POST"],
            allow_headers=["Content-Type", "X-Access-Code"],
            max_age=600,
        )
    app.include_router(build_web_router(settings))

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Health check per Render."""
        return {"status": "ok"}

    @app.post("/telegram/webhook")
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, bool]:
        """Riceve gli update Telegram; risponde subito e li elabora in background."""
        if not verify_secret(x_telegram_bot_api_secret_token, settings.webhook_secret_token):
            raise HTTPException(status_code=403, detail="forbidden")
        try:
            data = await request.json()
        except ValueError:
            log.warning("webhook_invalid_json")
            return {"ok": True}  # 200: evita retry infiniti di Telegram
        proc: UpdateProcessor | None = getattr(request.app.state, "processor", None)
        if proc is None or not isinstance(data, dict):
            return {"ok": True}

        async def _run() -> None:
            try:
                await proc(data)
            except Exception as exc:
                log.error("update_processing_failed", error_type=type(exc).__name__)

        task = asyncio.create_task(_run())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"ok": True}

    return app


def _setup_web(app: FastAPI, settings: Settings, application: Any, web_bot: LexBot | None) -> None:
    """Prepara LexBot e rate limiter per la web app; stessa istanza del bot Telegram se presente."""
    app.state.web_bot = None
    app.state.web_limiter = None
    app.state.web_features = None
    if not settings.web_enabled:
        return
    if web_bot is None and application is not None:
        web_bot = application.bot_data["lex"]
    if web_bot is None:
        from app.telegram_bot import LexBot

        web_bot = LexBot(settings)
    app.state.web_bot = web_bot
    from app.web_features import WebFeatures

    app.state.web_features = WebFeatures(web_bot)
    app.state.web_limiter = RateLimiter(settings.rate_limit_max_requests, settings.rate_limit_window_seconds)
    log.info("web_enabled", origin=settings.web_origin or None)


async def _set_webhook(application: Any, settings: Settings) -> None:
    """Registra il webhook; un errore non impedisce l'avvio del servizio."""
    if not settings.base_url or not settings.webhook_secret_token:
        log.warning(
            "webhook_not_configured",
            reason="PUBLIC_BASE_URL/RENDER_EXTERNAL_URL o TELEGRAM_WEBHOOK_SECRET mancanti",
        )
        return
    try:
        await application.bot.set_webhook(
            url=settings.webhook_url,
            secret_token=settings.webhook_secret_token,
            allowed_updates=["message"],
        )
        log.info("webhook_set", url=settings.webhook_url)
    except TelegramError as exc:
        log.error("webhook_set_failed", error_type=type(exc).__name__)


app = create_app()


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host="0.0.0.0", port=s.port, log_level=s.log_level.lower())
