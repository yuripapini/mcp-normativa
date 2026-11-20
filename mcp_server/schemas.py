"""Schemi Pydantic di input/output dei tool MCP normativi."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

VigenceStatus = Literal["vigente", "abrogato", "modificato", "sconosciuto"]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SourceMetadata(BaseModel):
    """Metadati di provenienza allegati a ogni risposta."""

    fonte: str = "Normattiva OpenData (IPZS)"
    api_endpoint: str | None = None
    licenza: str = "CC BY 4.0 - contenuti normativi IPZS"
    data_consultazione: str = Field(description="Timestamp ISO 8601 UTC della chiamata")
    note: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- input ---


class SearchInput(BaseModel):
    """Input di search_italian_law."""

    query: str = Field(min_length=2, max_length=500)
    materia: str | None = Field(default=None, max_length=80)
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("query troppo corta")
        return v


class LawIdInput(BaseModel):
    """Input con un identificativo di atto (URN, ELI, URL Normattiva, id interno)."""

    law_id: str = Field(min_length=3, max_length=500)

    @field_validator("law_id")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class ArticleInput(LawIdInput):
    """Input di get_law_article."""

    article: str | None = Field(default=None, max_length=20)


class VigenceInput(LawIdInput):
    """Input di check_law_vigence."""

    as_of_date: str | None = None

    @field_validator("as_of_date")
    @classmethod
    def _valid_date(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not _DATE_RE.match(v):
            raise ValueError("as_of_date deve essere nel formato YYYY-MM-DD")
        date.fromisoformat(v)  # solleva ValueError se la data non esiste
        return v


class RelatedInput(LawIdInput):
    """Input di get_related_laws."""

    limit: int = Field(default=5, ge=1, le=20)


# --------------------------------------------------------------- output ---


class LawSearchResult(BaseModel):
    """Singolo atto trovato."""

    titolo: str
    tipo_atto: str | None = None
    numero: str | None = None
    anno: str | None = None
    descrizione: str | None = None
    law_id: str = Field(description="Id interno 'dataGU:codiceRedazionale' riusabile negli altri tool")
    urn: str | None = None
    eli: str | None = None
    url_normattiva: str
    data_gu: str | None = None
    origine: Literal["citazione", "indice_tematico", "discovery_verificata", "ricerca_testuale"] = (
        "ricerca_testuale"
    )
    articolo_suggerito: str | None = None
    data_ultima_consultazione: str


class SearchOutput(BaseModel):
    """Output di search_italian_law."""

    query: str
    totale_trovati: int
    risultati: list[LawSearchResult]
    fonte: SourceMetadata


class ArticleText(BaseModel):
    """Testo di un articolo."""

    articolo: str
    rubrica: str | None = None
    testo_essenziale: str
    troncato: bool = False
    vigenza_dal: str | None = None
    vigenza_al: str | None = None
    abrogato: bool = False
    url_articolo: str | None = None


class ArticleOutput(BaseModel):
    """Output di get_law_article."""

    trovato: bool
    titolo_atto: str | None = None
    descrizione_atto: str | None = None
    law_id: str | None = None
    articoli: list[ArticleText] = Field(default_factory=list)
    stato_vigenza: VigenceStatus = "sconosciuto"
    url_ufficiale: str | None = None
    messaggio: str | None = None
    fonte: SourceMetadata


class VigenceChange(BaseModel):
    """Modifica o abrogazione rilevata."""

    tipo: str
    descrizione: str
    data: str | None = None


class VigenceOutput(BaseModel):
    """Output di check_law_vigence."""

    law_id: str | None = None
    descrizione_atto: str | None = None
    stato: VigenceStatus
    stato_verificato: bool
    motivazione: str
    data_riferimento: str
    data_entrata_in_vigore: str | None = None
    modifiche: list[VigenceChange] = Field(default_factory=list)
    url_normattiva: str | None = None
    fonte: SourceMetadata


class RelatedLaw(BaseModel):
    """Atto collegato o citato."""

    riferimento: str
    urn: str
    tipo_relazione: str
    citato_in: str | None = None
    url: str


class RelatedOutput(BaseModel):
    """Output di get_related_laws."""

    law_id: str | None = None
    descrizione_atto: str | None = None
    collegate: list[RelatedLaw] = Field(default_factory=list)
    fonte: SourceMetadata


class OfficialSourceOutput(BaseModel):
    """Output di get_official_source."""

    law_id: str | None = None
    descrizione_atto: str | None = None
    url_normattiva: str | None = None
    url_gazzetta_ufficiale: str | None = None
    urn: str | None = None
    eli: str | None = None
    data_consultazione: str
    fonte: SourceMetadata
