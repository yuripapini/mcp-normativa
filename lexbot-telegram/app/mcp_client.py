"""Client verso il server MCP normativo (Streamable HTTP, FastMCP)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastmcp import Client

from app.models import ToolSpec

MAX_TOOL_RESULT_CHARS = 12000


class ToolSession(Protocol):
    """Sessione MCP minima usata dall'orchestratore LLM."""

    async def list_tools(self) -> list[ToolSpec]:
        """Elenca i tool disponibili."""
        ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Esegue un tool e ritorna il risultato serializzato."""
        ...


class _FastMCPSession:
    def __init__(self, client: Client, timeout: float) -> None:
        self._client = client
        self._timeout = timeout

    async def list_tools(self) -> list[ToolSpec]:
        tools = await self._client.list_tools()
        return [
            ToolSpec(name=t.name, description=t.description or "", input_schema=dict(t.input_schema))
            for t in tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self._client.call_tool(name, arguments, timeout=self._timeout, raise_on_error=False)
        if result.is_error:
            text = " ".join(getattr(c, "text", "") for c in result.content).strip()
            return json.dumps({"errore": text or "errore del tool"}, ensure_ascii=False)
        if result.structured_content is not None:
            payload = json.dumps(result.structured_content, ensure_ascii=False)
        else:
            payload = " ".join(getattr(c, "text", "") for c in result.content)
        if len(payload) > MAX_TOOL_RESULT_CHARS:
            payload = payload[:MAX_TOOL_RESULT_CHARS] + ' ..."[risultato troncato]"'
        return payload


class MCPToolClient:
    """Factory di sessioni MCP con timeout e autenticazione opzionale."""

    def __init__(self, url: str, *, timeout: float = 30.0, auth_token: str | None = None) -> None:
        self.url = url
        self.timeout = timeout
        self.auth_token = auth_token

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ToolSession]:
        """Apre una sessione MCP per la durata di una richiesta utente."""
        client = Client(self.url, timeout=self.timeout, auth=self.auth_token or None)
        async with client:
            yield _FastMCPSession(client, self.timeout)
