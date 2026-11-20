"""Modelli condivisi tra LLM, client MCP e bot."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """Descrizione di un tool MCP esposto all'LLM."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})


class ToolCall(BaseModel):
    """Chiamata a tool richiesta dall'LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    """Messaggio in formato chat OpenAI-compatible."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


class LLMResult(BaseModel):
    """Risposta di un turno LLM."""

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class AnswerResult(BaseModel):
    """Risposta finale del backend con metadati tecnici (senza dati utente)."""

    text: str
    tools_used: list[str] = Field(default_factory=list)
    rounds: int = 0
