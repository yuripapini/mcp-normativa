"""Server FastMCP che espone strumenti di ricerca sulla legislazione italiana.

Fonte primaria: API Normattiva OpenData. Avvio:

    python -m mcp_server.server --port 8001

Endpoint MCP (Streamable HTTP): /mcp  -  health check: /healthz
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog
import yaml
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp_server import normattiva as nt
from mcp_server.discovery import DEFAULT_LEXIFINA_URL, LexifinaDiscovery
from mcp_server.schemas import (
    ArticleInput,
    ArticleOutput,
    ArticleText,
    LawIdInput,
    LawSearchResult,
    OfficialSourceOutput,
    RelatedInput,
    RelatedLaw,
    RelatedOutput,
    SearchInput,
    SearchOutput,
    SourceMetadata,
    VigenceChange,
    VigenceInput,
    VigenceOutput,
    VigenceStatus,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_ARTICLE_CHARS = 3500
RELATED_SCAN_ARTICLES = 8

log = structlog.get_logger("mcp_server")


class MCPSettings(BaseSettings):
    """Configurazione del server MCP (variabili d'ambiente / .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    normattiva_base_url: str = Field(default=nt.DEFAULT_PORTAL_URL)
    # Opzionale: l'API risponde su un host diverso dal portale dati.normattiva.it.
    normattiva_api_url: str = Field(default=nt.DEFAULT_API_URL)
    normattiva_timeout: float = 10.0
    normattiva_max_retries: int = 2
    # Tempo massimo complessivo di un tool: inferiore al timeout di 30 s del bot,
    # così l'LLM riceve un errore leggibile invece di un timeout di trasporto.
    tool_timeout_seconds: float = 25.0
    # Opzionale: se valorizzato, /mcp richiede "Authorization: Bearer <token>".
    mcp_auth_token: str | None = None
    # Opzionale, default off: discovery su Lexifina, sempre verificata su Normattiva.
    lexifina_discovery_enabled: bool = False
    lexifina_api_url: str = DEFAULT_LEXIFINA_URL
    log_level: str = "INFO"


@lru_cache
def get_settings() -> MCPSettings:
    """Settings singleton."""
    return MCPSettings()


_client: nt.NormattivaClient | None = None


def get_client() -> nt.NormattivaClient:
    """Client Normattiva condiviso (sostituibile nei test)."""
    global _client
    if _client is None:
        s = get_settings()
        _client = nt.NormattivaClient(
            s.normattiva_api_url,
            s.normattiva_base_url,
            timeout=s.normattiva_timeout,
            max_retries=s.normattiva_max_retries,
        )
    return _client


def set_client(client: nt.NormattivaClient | None) -> None:
    """Imposta il client Normattiva (usato dai test)."""
    global _client
    _client = client


_discovery: LexifinaDiscovery | None = None


def get_discovery() -> LexifinaDiscovery | None:
    """Adapter di discovery, solo se abilitato da configurazione."""
    global _discovery
    s = get_settings()
    if not s.lexifina_discovery_enabled:
        return None
    if _discovery is None:
        _discovery = LexifinaDiscovery(s.lexifina_api_url)
    return _discovery


def set_discovery(discovery: LexifinaDiscovery | None) -> None:
    """Imposta l'adapter di discovery (usato dai test)."""
    global _discovery
    _discovery = discovery


# ------------------------------------------------------------ dati tematici ---


@lru_cache
def load_topics() -> list[dict[str, Any]]:
    """Carica l'indice tematico (solo alias e citazioni, nessun testo normativo)."""
    path = DATA_DIR / "topics.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("topics", []))


def _words(text: str) -> str:
    """Normalizza e sostituisce la punteggiatura con spazi ("privacy?" -> "privacy")."""
    return " ".join(re.sub(r"[^\w\s]", " ", nt._normalize(text)).split())


_STEM_LEN = 6


def _stems(text: str) -> list[str]:
    """Radici grezze delle parole: le prime 6 lettere (licenziato/licenziamento -> licenz)."""
    return [w[:_STEM_LEN] for w in _words(text).split()]


def _contains(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def match_topics(query: str, materia: str | None) -> list[dict[str, Any]]:
    """Trova i temi per materia esplicita o sinonimi presenti nella query.

    Il confronto avviene sulle radici delle parole, in sequenza, così che forme
    flesse diverse ("licenziato", "licenziamento") individuino lo stesso tema.
    """
    q = _stems(query)
    m = _stems(materia) if materia else None
    found = []
    for topic in load_topics():
        names = [topic.get("id", ""), topic.get("nome", ""), *topic.get("sinonimi", [])]
        stemmed = [_stems(n) for n in names if n]
        if (m and m in stemmed) or any(_contains(q, n) for n in stemmed):
            found.append(topic)
    return found


# ----------------------------------------------------------------- helpers ---


def _meta(endpoint: str | None = None, note: list[str] | None = None) -> SourceMetadata:
    return SourceMetadata(api_endpoint=endpoint, data_consultazione=nt.now_iso(), note=note or [])


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _to_result(act: nt.ActInfo, origine: str, articolo: str | None = None) -> LawSearchResult:
    return LawSearchResult(
        titolo=act.titolo or act.descrizione,
        tipo_atto=act.denominazione,
        numero=act.numero,
        anno=act.anno,
        descrizione=act.descrizione,
        law_id=act.ref.law_id,
        urn=act.urn,
        eli=act.ref.eli,
        url_normattiva=act.ref.normattiva_url,
        data_gu=act.ref.data_gu,
        origine=origine,  # type: ignore[arg-type]
        articolo_suggerito=articolo,
        data_ultima_consultazione=nt.now_iso(),
    )


async def _guard[T](tool: str, fn: Callable[[], Awaitable[T]], **log_fields: Any) -> T:
    """Esegue un tool convertendo ogni errore in ToolError leggibile dall'LLM.

    Gli input sono validati qui dentro (fn costruisce il modello Pydantic), così
    anche un parametro non valido produce un messaggio comprensibile.
    """
    started = time.perf_counter()
    status = "ok"
    try:
        async with asyncio.timeout(get_settings().tool_timeout_seconds):
            return await fn()
    except TimeoutError as exc:
        status = "timeout"
        raise ToolError(
            "Normattiva non ha risposto entro il tempo massimo. "
            "Non è possibile verificare la norma ora: non citarla come verificata."
        ) from exc
    except ValidationError as exc:
        status = "invalid_input"
        problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'input'}: {e['msg']}" for e in exc.errors())
        raise ToolError(f"Parametri non validi: {problems}") from exc
    except nt.InvalidLawId as exc:
        status = "invalid_input"
        raise ToolError(str(exc)) from exc
    except nt.NormattivaNotFound as exc:
        status = "not_found"
        raise ToolError(f"{exc}. Nessun riferimento verificabile: non citare questa norma.") from exc
    except nt.NormattivaError as exc:
        status = "upstream_error"
        raise ToolError(
            f"Normattiva non ha risposto correttamente ({exc}). "
            "Riprova più tardi; non è possibile verificare la norma ora."
        ) from exc
    except ToolError:
        status = "tool_error"
        raise
    except Exception as exc:  # risposta inattesa: mai propagare dettagli interni
        status = "internal_error"
        log.error("tool_internal_error", tool=tool, error_type=type(exc).__name__)
        raise ToolError(
            "Errore interno nell'elaborazione della risposta Normattiva. "
            "Non è possibile verificare la norma ora."
        ) from exc
    finally:
        log.info(
            "tool_call",
            tool=tool,
            status=status,
            duration_ms=round((time.perf_counter() - started) * 1000),
            **log_fields,
        )


# --------------------------------------------------------- implementazioni ---


async def search_italian_law_impl(inp: SearchInput) -> SearchOutput:
    """Cerca atti: citazione esplicita, poi indice tematico, poi ricerca testuale."""
    client = get_client()
    results: dict[str, LawSearchResult] = {}
    notes: list[str] = []
    totale = 0

    if cit := nt.parse_citation(inp.query):
        try:
            act = await client.resolve_citation(cit)
            results[act.ref.law_id] = _to_result(act, "citazione")
        except nt.NormattivaNotFound:
            notes.append("La citazione indicata non corrisponde ad alcun atto su Normattiva.")

    topics = match_topics(inp.query, inp.materia)
    citations = [
        c for t in topics for a in t.get("atti", []) if (c := nt.parse_citation(a.get("citazione", "")))
    ]
    if citations:
        resolved = await asyncio.gather(
            *(client.resolve_citation(c) for c in citations[: inp.limit]), return_exceptions=True
        )
        for item in resolved:
            if isinstance(item, nt.ActInfo):
                results.setdefault(item.ref.law_id, _to_result(item, "indice_tematico"))
            elif isinstance(item, nt.NormattivaError):
                notes.append("Un atto dell'indice tematico non è stato verificato su Normattiva.")

    discovery = get_discovery()
    if discovery is not None and len(results) < inp.limit:
        candidates = await discovery.candidates(inp.query, inp.limit)
        verified = await asyncio.gather(
            *(client.resolve_citation(c.citation) for c in candidates), return_exceptions=True
        )
        for cand, item in zip(candidates, verified, strict=True):
            if isinstance(item, nt.ActInfo):
                results.setdefault(
                    item.ref.law_id,
                    _to_result(item, "discovery_verificata", cand.citation.articolo),
                )
        if candidates:
            notes.append(
                "Alcuni candidati sono stati individuati tramite l'indice Lexifina e "
                "verificati su Normattiva; i candidati non verificati sono stati scartati."
            )

    if len(results) < inp.limit:
        payload = await client.search_simple(inp.query, page_size=inp.limit)
        totale = payload["numeroAttiTrovati"]
        for item in payload["listaAtti"]:  # già filtrati da _validate_search
            act = nt.act_from_search_item(item)
            results.setdefault(act.ref.law_id, _to_result(act, "ricerca_testuale"))
        if totale:
            notes.append(
                "I risultati della ricerca testuale Normattiva sono ordinati per data, "
                "non per pertinenza: verificare l'attinenza."
            )

    risultati = list(results.values())[: inp.limit]
    if not risultati:
        notes.append("Nessun atto trovato: non è possibile indicare norme verificate.")
    return SearchOutput(
        query=inp.query,
        totale_trovati=max(totale, len(risultati)),
        risultati=risultati,
        fonte=_meta(client.endpoint(nt.PATH_SEARCH_SIMPLE), notes),
    )


async def get_law_article_impl(inp: ArticleInput) -> ArticleOutput:
    """Recupera testo e vigenza di un articolo (default: art. 1)."""
    client = get_client()
    parsed = nt.parse_law_id(inp.law_id)
    article_label = inp.article or parsed.articolo or "1"
    num, sotto = nt.parse_article(article_label)
    act = await client.resolve(parsed)
    urn = act.urn
    url_art = nt.n2ls_url(urn, article_label) if urn else act.ref.normattiva_url
    notes = [] if inp.article or parsed.articolo else ["Articolo non indicato: restituito l'art. 1."]
    try:
        atto = await client.article_detail(act.ref, articolo=num, sotto_articolo=sotto)
    except nt.NormattivaNotFound:
        return ArticleOutput(
            trovato=False,
            titolo_atto=act.titolo,
            descrizione_atto=act.descrizione,
            law_id=act.ref.law_id,
            url_ufficiale=url_art,
            messaggio=(
                f"Il testo dell'art. {article_label} non è disponibile tramite API OpenData "
                "(può accadere per articoli inesistenti o per codici strutturati). "
                "Consultare il link ufficiale."
            ),
            fonte=_meta(client.endpoint(nt.PATH_ARTICLE_DETAIL), notes),
        )
    parsed_html = nt.parse_article_html(atto["articoloHtml"])
    text = parsed_html.text
    abrogato = nt.is_article_abrogated(text)
    article = ArticleText(
        articolo=nt.format_article(num, sotto),
        rubrica=parsed_html.heading,
        testo_essenziale=text[:MAX_ARTICLE_CHARS],
        troncato=len(text) > MAX_ARTICLE_CHARS,
        vigenza_dal=nt.yyyymmdd_to_iso(atto.get("articoloDataInizioVigenza")),
        vigenza_al=nt.yyyymmdd_to_iso(atto.get("articoloDataFineVigenza")),
        abrogato=abrogato,
        url_articolo=url_art,
    )
    notes.append(
        "Stato riferito all'articolo nella versione vigente alla data di consultazione; "
        "per lo stato dell'intero atto usare check_law_vigence."
    )
    return ArticleOutput(
        trovato=True,
        titolo_atto=act.titolo or parsed_html.heading,
        descrizione_atto=act.descrizione,
        law_id=act.ref.law_id,
        articoli=[article],
        stato_vigenza="abrogato" if abrogato else "vigente",
        url_ufficiale=act.ref.normattiva_url,
        fonte=_meta(client.endpoint(nt.PATH_ARTICLE_DETAIL), notes),
    )


_CLASSE_STATUS: dict[str, tuple[VigenceStatus, str]] = {
    nt.CLASSE_ABROGATO: ("abrogato", "Normattiva classifica l'atto come 'atto normativo - abrogato'."),
    nt.CLASSE_AGGIORNATO: (
        "modificato",
        "Normattiva classifica l'atto come 'atto normativo - aggiornato': "
        "vigente con modifiche successive (testo consolidato).",
    ),
    nt.CLASSE_SENZA_AGGIORNAMENTI: (
        "vigente",
        "Normattiva classifica l'atto come 'atto normativo - senza aggiornamenti'.",
    ),
}


async def check_law_vigence_impl(inp: VigenceInput) -> VigenceOutput:
    """Verifica lo stato di vigenza tramite la classe provvedimento Normattiva."""
    client = get_client()
    act = await client.resolve(nt.parse_law_id(inp.law_id))
    today = date.today().isoformat()
    ref_date = inp.as_of_date or today
    notes: list[str] = []
    classe, item = await client.classe_provvedimento(act)
    modifiche: list[VigenceChange] = []

    if classe is None:
        stato: VigenceStatus = "sconosciuto"
        verificato = False
        motivazione = "Classe provvedimento non determinabile tramite API: stato non verificabile."
    else:
        stato, motivazione = _CLASSE_STATUS[classe]
        verificato = True
        if item and item.get("dataUltimaModifica"):
            modifiche.append(
                VigenceChange(
                    tipo="aggiornamento",
                    descrizione=f"Atti modificanti (codici): {item.get('ultimiAttiModificanti') or 'n.d.'}",
                    data=str(item["dataUltimaModifica"]),
                )
            )
        if stato == "abrogato":
            modifiche.append(VigenceChange(tipo="abrogazione", descrizione=motivazione))

    entrata: str | None = None
    try:
        art1 = await client.article_detail(act.ref, data_vigenza=ref_date)
        inizio = nt.yyyymmdd_to_iso(art1.get("articoloDataInizioVigenza"))
        if classe == nt.CLASSE_SENZA_AGGIORNAMENTI:
            entrata = inizio
        elif inizio:
            notes.append(f"Art. 1 nella versione alla data {ref_date} in vigore dal {inizio}.")
    except nt.NormattivaNotFound:
        notes.append(f"Testo dell'art. 1 non disponibile alla data {ref_date}.")
        if inp.as_of_date:
            stato, verificato = "sconosciuto", False
            motivazione = f"Impossibile verificare il testo vigente al {ref_date}."

    if inp.as_of_date and inp.as_of_date != today and verificato:
        # TODO(verifica API): la classe provvedimento descrive lo stato attuale;
        # non è documentato un modo sincrono per ottenerla a una data passata.
        notes.append("La classe provvedimento si riferisce allo stato attuale, non alla data richiesta.")
        verificato = False
    if entrata is None:
        notes.append("Data di entrata in vigore dell'atto non determinabile con certezza via API.")

    return VigenceOutput(
        law_id=act.ref.law_id,
        descrizione_atto=act.descrizione,
        stato=stato,
        stato_verificato=verificato,
        motivazione=motivazione,
        data_riferimento=ref_date,
        data_entrata_in_vigore=entrata,
        modifiche=modifiche,
        url_normattiva=act.ref.normattiva_url,
        fonte=_meta(client.endpoint(nt.PATH_SEARCH_ADVANCED), notes),
    )


def _base_urn(urn: str) -> str:
    return urn.split("~", 1)[0]


async def get_related_laws_impl(inp: RelatedInput) -> RelatedOutput:
    """Estrae gli atti citati nei primi articoli (link URN nel testo ufficiale)."""
    client = get_client()
    act = await client.resolve(nt.parse_law_id(inp.law_id))
    self_urn = act.urn
    seen: dict[str, RelatedLaw] = {}
    for num in range(1, RELATED_SCAN_ARTICLES + 1):
        try:
            atto = await client.article_detail(act.ref, articolo=num)
        except nt.NormattivaNotFound:
            break
        for anchor, urn in nt.parse_article_html(atto["articoloHtml"]).links:
            base = _base_urn(urn)
            if base == self_urn or base in seen:
                continue
            seen[base] = RelatedLaw(
                riferimento=anchor or base,
                urn=base,
                tipo_relazione="citata nel testo",
                citato_in=f"art. {num}",
                url=nt.n2ls_url(urn),
            )
        if len(seen) >= inp.limit:
            break
    notes = [
        f"Relazioni ricavate dai link URN presenti nei primi {RELATED_SCAN_ARTICLES} articoli; "
        "non è un elenco esaustivo di modifiche o abrogazioni."
    ]
    return RelatedOutput(
        law_id=act.ref.law_id,
        descrizione_atto=act.descrizione,
        collegate=list(seen.values())[: inp.limit],
        fonte=_meta(client.endpoint(nt.PATH_ARTICLE_DETAIL), notes),
    )


async def get_official_source_impl(inp: LawIdInput) -> OfficialSourceOutput:
    """Restituisce gli URL ufficiali Normattiva e Gazzetta Ufficiale."""
    client = get_client()
    act = await client.resolve(nt.parse_law_id(inp.law_id))
    return OfficialSourceOutput(
        law_id=act.ref.law_id,
        descrizione_atto=act.descrizione,
        url_normattiva=act.ref.normattiva_url,
        url_gazzetta_ufficiale=act.ref.gazzetta_url,
        urn=act.urn,
        eli=act.ref.eli,
        data_consultazione=nt.now_iso(),
        fonte=_meta(None, ["URL costruiti dagli identificativi ELI/URN ufficiali."]),
    )


# ---------------------------------------------------------------- server ---

mcp = FastMCP(
    "lexbot-normattiva",
    instructions=(
        "Strumenti di ricerca sulla legislazione italiana basati su Normattiva OpenData. "
        "Usa search_italian_law per trovare gli atti, poi get_law_article e "
        "check_law_vigence usando il law_id restituito. Non citare norme non verificate."
    ),
)


@mcp.tool
async def search_italian_law(query: str, materia: str | None = None, limit: int = 5) -> SearchOutput:
    """Cerca atti normativi italiani su Normattiva.

    Accetta testo libero o citazioni ("d.lgs. 196/2003", "legge 23 agosto 1988, n. 400").
    Restituisce titolo, tipo, numero, anno, URN/ELI, URL Normattiva e law_id da
    riutilizzare negli altri strumenti.
    """
    return await _guard(
        "search_italian_law",
        lambda: search_italian_law_impl(SearchInput(query=query, materia=materia, limit=limit)),
        q_hash=_hash(query),
    )


@mcp.tool
async def get_law_article(law_id: str, article: str | int | None = None) -> ArticleOutput:
    """Recupera il testo vigente di un articolo (es. "13", "13-bis") di un atto.

    law_id: id restituito da search_italian_law, URN NIR, URL ELI Normattiva o citazione.
    article: numero dell'articolo, come stringa ("13-bis") o intero (13).
    """
    # I modelli spesso passano il numero come intero: lo accettiamo invece di
    # rifiutare la chiamata e costringere l'LLM a riprovare.
    art = None if article is None else str(article)
    return await _guard(
        "get_law_article",
        lambda: get_law_article_impl(ArticleInput(law_id=law_id, article=art)),
        law_id=law_id[:120],
    )


@mcp.tool
async def check_law_vigence(law_id: str, as_of_date: str | None = None) -> VigenceOutput:
    """Verifica se un atto è vigente, modificato o abrogato secondo Normattiva.

    as_of_date opzionale nel formato YYYY-MM-DD.
    """
    return await _guard(
        "check_law_vigence",
        lambda: check_law_vigence_impl(VigenceInput(law_id=law_id, as_of_date=as_of_date)),
        law_id=law_id[:120],
    )


@mcp.tool
async def get_related_laws(law_id: str, limit: int = 5) -> RelatedOutput:
    """Elenca gli atti citati nel testo dell'atto indicato, con link Normattiva."""
    return await _guard(
        "get_related_laws",
        lambda: get_related_laws_impl(RelatedInput(law_id=law_id, limit=limit)),
        law_id=law_id[:120],
    )


@mcp.tool
async def get_official_source(law_id: str) -> OfficialSourceOutput:
    """Restituisce URL Normattiva, URL Gazzetta Ufficiale, URN ed ELI di un atto."""
    return await _guard(
        "get_official_source",
        lambda: get_official_source_impl(LawIdInput(law_id=law_id)),
        law_id=law_id[:120],
    )


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> Response:
    """Health check per Render."""
    return JSONResponse({"status": "ok"})


class BearerAuthMiddleware:
    """Middleware ASGI: richiede un token bearer su tutte le rotte tranne /healthz."""

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope.get("path") != "/healthz":
            headers = dict(scope.get("headers") or [])
            import hmac

            if not hmac.compare_digest(headers.get(b"authorization", b""), self.expected):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def configure_logging(level: str) -> None:
    """Log strutturati JSON su stdout."""
    logging.basicConfig(level=level.upper(), format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
    )


def create_app() -> Any:
    """App ASGI del server MCP (Streamable HTTP su /mcp)."""
    settings = get_settings()
    app = mcp.http_app(path="/mcp")
    if settings.mcp_auth_token:
        return BearerAuthMiddleware(app, settings.mcp_auth_token)
    return app


def main() -> None:
    """Entry point CLI."""
    import uvicorn

    parser = argparse.ArgumentParser(description="Server MCP Normattiva")
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "8001")))
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    log.info("mcp_server_start", host=args.host, port=args.port, auth=bool(settings.mcp_auth_token))
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
