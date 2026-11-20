"""Astrazione LLM provider-agnostic e orchestrazione del ciclo tool-calling."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Protocol

import httpx
import structlog

from app.guardrails import NORMATTIVA_LINK_RE, ensure_disclaimer, ensure_verified_link
from app.mcp_client import ToolSession
from app.models import AnswerResult, ChatMessage, LLMResult, ToolCall, ToolSpec

log = structlog.get_logger("llm")

PROMPT_PATH = Path(__file__).parent / "prompts" / "system_prompt.md"

NO_RESULT_MESSAGE = (
    "Non sono riuscito a verificare una norma pertinente sulle fonti ufficiali. "
    "Ti consiglio di consultare direttamente https://www.normattiva.it/ "
    "o un professionista."
)


class LLMError(Exception):
    """Errore del provider LLM."""


class LLMProvider(Protocol):
    """Interfaccia minima di un provider LLM con tool calling."""

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        *,
        tool_choice: str = "auto",
    ) -> LLMResult:
        """Esegue un turno di chat."""
        ...


def load_system_prompt(path: Path = PROMPT_PATH) -> str:
    """Legge il prompt di sistema versionato."""
    return path.read_text(encoding="utf-8").strip()


class OpenAICompatibleProvider:
    """Provider per API /chat/completions compatibili OpenAI."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise LLMError("OPENAI_API_KEY non configurata")
        self.model = model
        self.url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @staticmethod
    def _serialize(msg: ChatMessage) -> dict[str, Any]:
        out: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_calls:
            out["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in msg.tool_calls
            ]
        if msg.tool_call_id:
            out["tool_call_id"] = msg.tool_call_id
        return out

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        *,
        tool_choice: str = "auto",
    ) -> LLMResult:
        """Chiama /chat/completions e normalizza la risposta."""
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [self._serialize(m) for m in messages],
            "temperature": 0.1,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description[:1000],
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]
            body["tool_choice"] = tool_choice
        try:
            resp = await self._client.post(self.url, json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise LLMError(f"Errore di rete verso il provider LLM: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise LLMError(f"Provider LLM HTTP {resp.status_code}")
        try:
            message = resp.json()["choices"][0]["message"]
        except (ValueError, KeyError, IndexError) as exc:
            raise LLMError("Risposta LLM non valida") from exc
        calls = []
        for tc in message.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=args))
        return LLMResult(content=message.get("content"), tool_calls=calls)


def build_provider(provider: str, model: str, api_key: str, base_url: str, timeout: float) -> LLMProvider:
    """Factory dei provider supportati (estendibile)."""
    if provider.lower() in {"openai", "openai-compatible"}:
        return OpenAICompatibleProvider(api_key, model, base_url=base_url, timeout=timeout)
    raise LLMError(f"LLM_PROVIDER non supportato: {provider}")


async def answer_question(
    question: str,
    provider: LLMProvider,
    session: ToolSession,
    *,
    system_prompt: str,
    max_rounds: int = 6,
    llm_timeout: float = 30.0,
) -> AnswerResult:
    """Ciclo agentico: l'LLM deve usare i tool MCP prima di rispondere.

    Al primo turno il tool calling è obbligatorio (tool_choice="required").
    """
    tools = await session.list_tools()
    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=question),
    ]
    used: list[str] = []
    verified: list[str] = []  # link Normattiva presenti nei risultati dei tool

    def _final(content: str | None, rounds: int) -> AnswerResult:
        text = (content or "").strip() or NO_RESULT_MESSAGE
        text = ensure_verified_link(text, verified)
        return AnswerResult(text=ensure_disclaimer(text), tools_used=used, rounds=rounds)

    for round_no in range(1, max_rounds + 1):
        choice = "required" if round_no == 1 else "auto"
        result = await asyncio.wait_for(
            provider.complete(messages, tools, tool_choice=choice), timeout=llm_timeout
        )
        if not result.tool_calls:
            return _final(result.content, round_no)
        messages.append(ChatMessage(role="assistant", content=result.content, tool_calls=result.tool_calls))
        for call in result.tool_calls:
            used.append(call.name)
            output = await session.call_tool(call.name, call.arguments)
            verified.extend(u for u in NORMATTIVA_LINK_RE.findall(output) if u not in verified)
            log.info("tool_executed", tool=call.name, round=round_no, result_chars=len(output))
            messages.append(ChatMessage(role="tool", content=output, tool_call_id=call.id))
    # Tool round esauriti: si chiede la risposta finale senza ulteriori tool.
    messages.append(
        ChatMessage(
            role="user",
            content="Fornisci ora la risposta finale usando solo i risultati già ottenuti.",
        )
    )
    final = await asyncio.wait_for(provider.complete(messages, []), timeout=llm_timeout)
    return _final(final.content, max_rounds + 1)
