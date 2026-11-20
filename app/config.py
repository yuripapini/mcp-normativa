"""Configurazione applicativa da variabili d'ambiente (pydantic-settings)."""

from __future__ import annotations

import hashlib
import logging
import re
from functools import lru_cache

import structlog
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MCP_SERVER_URL = "http://localhost:8001/mcp"
_TELEGRAM_SECRET_RE = re.compile(r"[A-Za-z0-9_-]{1,256}")


class Settings(BaseSettings):
    """Variabili d'ambiente del bot. Nessun segreto ha un valore di default."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    public_base_url: str = ""
    # Stringa "123,456": parsata in allowed_user_ids. Vuota = nessun utente autorizzato.
    allowed_telegram_user_ids: str = ""

    llm_provider: str = "openai"
    llm_model: str = "gpt-4.1-mini"
    openai_api_key: str = ""
    # Opzionale: endpoint OpenAI-compatible alternativo.
    openai_base_url: str = "https://api.openai.com/v1"

    # "http" (default): server MCP separato raggiunto via URL.
    # "inprocess": tool MCP eseguiti nel processo del bot (un solo servizio, es. Render Free).
    mcp_transport: str = "http"
    # Vuota: si usa MCP_SERVER_HOSTPORT (rete privata Render) oppure il default locale.
    mcp_server_url: str = ""
    # Impostata dal blueprint Render (fromService.property=hostport), es. "lexbot-mcp:10000".
    mcp_server_hostport: str = ""
    # Opzionale: token bearer condiviso con il server MCP.
    mcp_auth_token: str | None = None
    normattiva_base_url: str = "https://dati.normattiva.it"

    # Impostata automaticamente da Render sui web service (es. https://app.onrender.com).
    render_external_url: str = ""

    log_level: str = "INFO"
    runtime_env: str = "development"
    port: int = 8000

    # Limiti (non presenti in .env.example: valori di specifica).
    request_timeout_seconds: float = 30.0
    rate_limit_max_requests: int = 10
    rate_limit_window_seconds: int = 300
    max_query_chars: int = Field(default=2000, ge=50)
    llm_max_tool_rounds: int = Field(default=6, ge=1, le=12)

    @property
    def allowed_user_ids(self) -> frozenset[int]:
        """Allowlist parsata; valori non numerici vengono ignorati."""
        ids = set()
        for part in self.allowed_telegram_user_ids.replace(";", ",").split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                ids.add(int(part))
        return frozenset(ids)

    @property
    def base_url(self) -> str:
        """URL pubblico del bot: PUBLIC_BASE_URL, altrimenti RENDER_EXTERNAL_URL."""
        return (self.public_base_url or self.render_external_url).strip().rstrip("/")

    @property
    def webhook_url(self) -> str:
        """URL pubblico del webhook Telegram."""
        return f"{self.base_url}/telegram/webhook"

    @property
    def webhook_secret_token(self) -> str:
        """Secret da registrare su Telegram e da verificare nell'header.

        Telegram accetta solo 1-256 caratteri A-Za-z0-9_-. Un valore diverso (es. il
        base64 prodotto da Render con generateValue) viene derivato in modo
        deterministico con SHA-256 esadecimale.
        """
        secret = self.telegram_webhook_secret.strip()
        if not secret or _TELEGRAM_SECRET_RE.fullmatch(secret):
            return secret
        return hashlib.sha256(secret.encode()).hexdigest()

    @property
    def effective_mcp_server_url(self) -> str:
        """URL del server MCP: esplicito, poi hostport privato Render, poi locale."""
        if self.mcp_server_url.strip():
            return self.mcp_server_url.strip()
        if self.mcp_server_hostport.strip():
            return f"http://{self.mcp_server_hostport.strip()}/mcp"
        return DEFAULT_MCP_SERVER_URL

    @property
    def mcp_inprocess(self) -> bool:
        """True quando MCP_TRANSPORT=inprocess."""
        return self.mcp_transport.strip().lower() == "inprocess"

    @property
    def is_test(self) -> bool:
        """True quando RUNTIME_ENV=test."""
        return self.runtime_env.lower() == "test"


@lru_cache
def get_settings() -> Settings:
    """Settings singleton."""
    return Settings()


def configure_logging(level: str) -> None:
    """Log JSON strutturati. Non loggare mai il testo delle query utente."""
    logging.basicConfig(level=level.upper(), format="%(message)s")
    # httpx logga gli URL completi: includerebbero il token del bot Telegram.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
    )
