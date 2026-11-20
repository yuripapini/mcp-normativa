"""Client asincrono per l'API Normattiva OpenData e utility sugli identificativi.

Endpoint e campi verificati sulla specifica ufficiale "Normattiva - Specifiche API
Open Data" (riportata in https://github.com/adellorto/normattiva-mcp/tree/main/docs)
e con chiamate reali all'ambiente di esercizio il 2026-11-20:

- POST /bff-opendata/v1/api/v1/ricerca/semplice
- POST /bff-opendata/v1/api/v1/ricerca/avanzata
- POST /bff-opendata/v1/api/v1/atto/dettaglio-atto

URL pubblici verificati (HTTP 200):
- https://www.normattiva.it/eli/id/AAAA/MM/GG/<codiceRedazionale>/CONSOLIDATED
- https://www.normattiva.it/uri-res/N2Ls?<urn:nir:...>
- https://www.gazzettaufficiale.it/eli/id/AAAA/MM/GG/<codiceRedazionale>/sg

Nessun testo normativo viene salvato su disco: le risposte vivono solo in memoria.
"""

from __future__ import annotations

import asyncio
import html
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any, ClassVar
from urllib.parse import parse_qs, unquote, urlparse

import httpx

DEFAULT_API_URL = "https://api.normattiva.it/t/normattiva.api"
DEFAULT_PORTAL_URL = "https://dati.normattiva.it"
NORMATTIVA_SITE = "https://www.normattiva.it"
GAZZETTA_SITE = "https://www.gazzettaufficiale.it"

PATH_SEARCH_SIMPLE = "/bff-opendata/v1/api/v1/ricerca/semplice"
PATH_SEARCH_ADVANCED = "/bff-opendata/v1/api/v1/ricerca/avanzata"
# La specifica riporta "bff-mobile" nel titolo ma "bff-opendata" nell'esempio curl:
# in esercizio risponde "bff-opendata" (verificato).
PATH_ARTICLE_DETAIL = "/bff-opendata/v1/api/v1/atto/dettaglio-atto"

# Classe provvedimento (tipologica 1.2.4 della specifica).
CLASSE_SENZA_AGGIORNAMENTI = "1"
CLASSE_AGGIORNATO = "2"
CLASSE_ABROGATO = "3"

_GENERIC_500 = "Errore generico della chiamata, riprovare più tardi"
# 500 è ritentabile per specifica ("riprovare più tardi", par. 1.3.1-1.3.10).
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# Il WAF IPZS risponde 409 {"status": "KO", "supportId": ..., "message": "La pagina
# richiesta è stata bloccata dai sistemi di protezione..."} (osservato il 2026-11-20):
# non si ritenta per non peggiorare il blocco.
_WAF_STATUS = 409


def now_iso() -> str:
    """Timestamp UTC ISO 8601 al secondo, usato come data di consultazione."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


# ------------------------------------------------------------------ errori ---


class NormattivaError(Exception):
    """Errore generico verso Normattiva."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.retryable = retryable


class NormattivaNotFound(NormattivaError):
    """Atto o articolo non presente in banca dati."""


class InvalidLawId(ValueError):
    """Identificativo di atto non riconosciuto."""


# ------------------------------------------------------- tipi di atto/URN ---


@dataclass(frozen=True)
class ActType:
    """Tipo di atto: denominazione Normattiva e segmento URN NIR."""

    denominazione: str
    urn_type: str | None


ACT_TYPES: dict[str, ActType] = {
    "legge": ActType("LEGGE", "legge"),
    "legge costituzionale": ActType("LEGGE COSTITUZIONALE", "legge.costituzionale"),
    "decreto legislativo": ActType("DECRETO LEGISLATIVO", "decreto.legislativo"),
    "decreto legge": ActType("DECRETO-LEGGE", "decreto.legge"),
    "decreto del presidente della repubblica": ActType(
        "DECRETO DEL PRESIDENTE DELLA REPUBBLICA", "decreto.del.presidente.della.repubblica"
    ),
    "decreto del presidente del consiglio dei ministri": ActType(
        "DECRETO DEL PRESIDENTE DEL CONSIGLIO DEI MINISTRI",
        "decreto.del.presidente.del.consiglio.dei.ministri",
    ),
    "regio decreto": ActType("REGIO DECRETO", "regio.decreto"),
    "regio decreto legge": ActType("REGIO DECRETO-LEGGE", "regio.decreto.legge"),
    "costituzione": ActType("COSTITUZIONE", "costituzione"),
    # TODO(verifica URN): per i decreti ministeriali l'URN NIR include l'autorità
    # emanante; non lo costruiamo per non inventare identificativi.
    "decreto ministeriale": ActType("DECRETO MINISTERIALE", None),
    "decreto": ActType("DECRETO", None),
}

# Abbreviazioni d'uso comune (dopo normalizzazione: minuscolo, punti -> spazi).
_TYPE_ALIASES: dict[str, str] = {
    "l": "legge",
    "legge": "legge",
    "l cost": "legge costituzionale",
    "legge costituzionale": "legge costituzionale",
    "d lgs": "decreto legislativo",
    "dlgs": "decreto legislativo",
    "d leg": "decreto legislativo",
    "d lg": "decreto legislativo",
    "decreto legislativo": "decreto legislativo",
    "d l": "decreto legge",
    "dl": "decreto legge",
    "decreto legge": "decreto legge",
    "d p r": "decreto del presidente della repubblica",
    "dpr": "decreto del presidente della repubblica",
    "decreto del presidente della repubblica": "decreto del presidente della repubblica",
    "d p c m": "decreto del presidente del consiglio dei ministri",
    "dpcm": "decreto del presidente del consiglio dei ministri",
    "r d": "regio decreto",
    "rd": "regio decreto",
    "regio decreto": "regio decreto",
    "r d l": "regio decreto legge",
    "regio decreto legge": "regio decreto legge",
    "d m": "decreto ministeriale",
    "dm": "decreto ministeriale",
    "decreto ministeriale": "decreto ministeriale",
}

_URN_TO_KEY = {t.urn_type: k for k, t in ACT_TYPES.items() if t.urn_type}
_DENOM_TO_KEY = {t.denominazione: k for k, t in ACT_TYPES.items()}

_MESI = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]  # fmt: skip

# Suffissi latini degli articoli -> valore di sottoArticolo (1 = articolo base).
_SUFFISSI = [
    "bis", "ter", "quater", "quinquies", "sexies", "septies", "octies",
    "novies", "decies", "undecies", "duodecies", "terdecies", "quaterdecies",
    "quinquiesdecies", "sexiesdecies", "septiesdecies", "duodevicies", "undevicies",
    "vicies",
]  # fmt: skip


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[.\-–’']", " ", text)
    return " ".join(text.split())


def act_type_from_denominazione(denominazione: str | None) -> ActType | None:
    """Ritorna il tipo di atto a partire dalla denominazione Normattiva."""
    if not denominazione:
        return None
    key = _DENOM_TO_KEY.get(denominazione.strip().upper())
    return ACT_TYPES.get(key) if key else None


# ------------------------------------------------------------ identificativi ---


@dataclass(frozen=True)
class ActRef:
    """Chiave primaria Normattiva di un atto: data GU + codice redazionale."""

    data_gu: str
    codice_redazionale: str

    @property
    def law_id(self) -> str:
        """Id interno stabile 'AAAA-MM-GG:CODICE'."""
        return f"{self.data_gu}:{self.codice_redazionale}"

    @property
    def eli(self) -> str:
        """Identificativo ELI della versione consolidata."""
        return f"eli/id/{self.data_gu.replace('-', '/')}/{self.codice_redazionale}/CONSOLIDATED"

    @property
    def normattiva_url(self) -> str:
        """URL ufficiale Normattiva (ELI, verificato)."""
        return f"{NORMATTIVA_SITE}/{self.eli}"

    @property
    def gazzetta_url(self) -> str:
        """URL ufficiale Gazzetta Ufficiale (ELI serie generale, verificato)."""
        return f"{GAZZETTA_SITE}/eli/id/{self.data_gu.replace('-', '/')}/{self.codice_redazionale}/sg"


@dataclass(frozen=True)
class Citation:
    """Citazione testuale di un atto (tipo, numero, anno ed eventuale data)."""

    type_key: str
    anno: str
    numero: str | None = None
    data_emanazione: str | None = None
    articolo: str | None = None

    @property
    def act_type(self) -> ActType:
        """Tipo di atto risolto."""
        return ACT_TYPES[self.type_key]

    @property
    def urn(self) -> str | None:
        """URN NIR, solo se ricostruibile senza ambiguità."""
        if not self.act_type.urn_type or not self.data_emanazione:
            return None
        base = f"urn:nir:stato:{self.act_type.urn_type}:{self.data_emanazione}"
        return f"{base};{self.numero}" if self.numero else base


@dataclass(frozen=True)
class ParsedLawId:
    """Risultato del parsing di un identificativo fornito dall'utente o dall'LLM."""

    ref: ActRef | None = None
    citation: Citation | None = None
    articolo: str | None = None


_ID_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}):([A-Za-z0-9]{5,12})$")
_ELI_RE = re.compile(r"eli/id/(\d{4})/(\d{2})/(\d{2})/([A-Za-z0-9]{5,12})", re.IGNORECASE)
_URN_RE = re.compile(
    r"urn:nir:stato:([a-z.]+):(\d{4}-\d{2}-\d{2})(?:;([0-9]+))?(?:~art([0-9]+[a-z]*))?",
    re.IGNORECASE,
)
_TYPE_PATTERN = "|".join(sorted((re.escape(a) for a in _TYPE_ALIASES), key=len, reverse=True))
_CIT_WITH_DATE = re.compile(
    rf"\b(?P<tipo>{_TYPE_PATTERN})\s+(?P<g>\d{{1,2}})\s+(?P<m>{'|'.join(_MESI)})\s+"
    rf"(?P<a>\d{{4}})\s*,?\s*(?:n\s*)?(?P<n>\d+)\b"
)
_CIT_SHORT = re.compile(
    rf"\b(?P<tipo>{_TYPE_PATTERN})\s+(?:n\s*)?(?P<n>\d+)\s*(?:/|del|dell anno|,)\s*(?P<a>\d{{4}})\b"
)
_ART_RE = re.compile(r"\bart(?:icolo|t)?\s*(\d+)\s*[- ]?\s*([a-z]+)?\b")


def _article_from_text(norm: str) -> str | None:
    m = _ART_RE.search(norm)
    if not m:
        return None
    suffix = m.group(2) if m.group(2) in _SUFFISSI else None
    return f"{m.group(1)}-{suffix}" if suffix else m.group(1)


def parse_citation(text: str) -> Citation | None:
    """Estrae una citazione normativa da testo libero ("d.lgs. 196/2003", ...)."""
    norm = _normalize(text)
    m = _CIT_WITH_DATE.search(norm)
    if m:
        key = _TYPE_ALIASES[m.group("tipo")]
        mese = _MESI.index(m.group("m")) + 1
        data = f"{m.group('a')}-{mese:02d}-{int(m.group('g')):02d}"
        return Citation(key, m.group("a"), m.group("n"), data, _article_from_text(norm))
    m = _CIT_SHORT.search(norm)
    if m:
        key = _TYPE_ALIASES[m.group("tipo")]
        return Citation(key, m.group("a"), m.group("n"), None, _article_from_text(norm))
    return None


def parse_law_id(value: str) -> ParsedLawId:
    """Interpreta id interno, URL/ELI Normattiva o GU, URN NIR o citazione testuale.

    Solleva InvalidLawId se l'input non è riconducibile a un atto.
    """
    raw = unquote(value.strip())
    if m := _ID_RE.match(raw):
        return ParsedLawId(ref=ActRef(m.group(1), m.group(2).upper()))
    if m := _ELI_RE.search(raw):
        return ParsedLawId(ref=ActRef(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", m.group(4).upper()))
    if raw.startswith("http"):
        qs = parse_qs(urlparse(raw).query)
        gu = qs.get("atto.dataPubblicazioneGazzetta", [None])[0]
        cod = qs.get("atto.codiceRedazionale", [None])[0]
        if gu and cod and re.match(r"^\d{4}-\d{2}-\d{2}$", gu):
            return ParsedLawId(ref=ActRef(gu, cod.upper()))
    if m := _URN_RE.search(raw):
        key = _URN_TO_KEY.get(m.group(1).lower())
        if key is None:
            raise InvalidLawId(f"Tipo di atto URN non supportato: {m.group(1)}")
        data = m.group(2)
        art = m.group(4)
        return ParsedLawId(
            citation=Citation(key, data[:4], m.group(3), data, art),
            articolo=art,
        )
    if cit := parse_citation(raw):
        return ParsedLawId(citation=cit, articolo=cit.articolo)
    raise InvalidLawId(
        "Identificativo non riconosciuto. Usa un URN (urn:nir:...), un URL ELI "
        "Normattiva, l'id 'AAAA-MM-GG:CODICE' oppure una citazione tipo 'legge 400/1988'."
    )


def parse_article(article: str) -> tuple[int, int]:
    """Converte "13", "13-bis", "13 ter" in (idArticolo, sottoArticolo)."""
    m = re.match(r"^\s*(?:art\.?\s*)?(\d+)\s*[- ]?\s*([a-z]*)\s*$", article.lower())
    if not m:
        raise InvalidLawId(f"Numero di articolo non valido: {article!r}")
    num = int(m.group(1))
    suffix = m.group(2)
    if not suffix:
        return num, 1
    if suffix not in _SUFFISSI:
        raise InvalidLawId(f"Suffisso di articolo non riconosciuto: {suffix!r}")
    return num, _SUFFISSI.index(suffix) + 2


def format_article(num: int, sotto: int) -> str:
    """Inverso di parse_article."""
    return str(num) if sotto <= 1 else f"{num}-{_SUFFISSI[sotto - 2]}"


# Codici approvati come allegato del decreto: il risolutore apre l'articolo solo con il
# suffisso dell'allegato nell'URN (verificato su www.normattiva.it il 2026-11-20).
ALLEGATO_CODICI: dict[str, str] = {
    "urn:nir:stato:regio.decreto:1930-10-19;1398": ":1",  # codice penale
    "urn:nir:stato:regio.decreto:1942-03-16;262": ":2",  # codice civile
}


def n2ls_url(urn: str, articolo: str | None = None) -> str:
    """URL risolutore Normattiva per URN (verificato), con eventuale articolo."""
    if not articolo:
        return f"{NORMATTIVA_SITE}/uri-res/N2Ls?{urn}"
    allegato = ALLEGATO_CODICI.get(urn, "")
    return f"{NORMATTIVA_SITE}/uri-res/N2Ls?{urn}{allegato}~art{articolo.replace('-', '')}"


# --------------------------------------------------------------- metadati ---


@dataclass
class ActInfo:
    """Metadati di un atto normalizzati dalle risposte API."""

    ref: ActRef
    descrizione: str
    titolo: str
    denominazione: str | None = None
    numero: str | None = None
    anno: str | None = None
    data_emanazione: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def urn(self) -> str | None:
        """URN NIR ricostruito da tipo, data di emanazione e numero."""
        t = act_type_from_denominazione(self.denominazione)
        if not t or not t.urn_type or not self.data_emanazione:
            return None
        base = f"urn:nir:stato:{t.urn_type}:{self.data_emanazione}"
        if t.urn_type == "costituzione" or not self.numero:
            return base
        return f"{base};{self.numero}"


def _clean_title(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    value = re.sub(r"\(\s*\d{2,3}[A-Z]\d{4,5}\s*\)", "", value)  # codice redazionale nel titolo
    return " ".join(value.split()).strip()


def act_from_search_item(item: dict[str, Any]) -> ActInfo:
    """Converte un elemento di listaAtti in ActInfo."""
    emanazione = item.get("dataEmanazione")
    data_em = emanazione[:10] if isinstance(emanazione, str) and len(emanazione) >= 10 else None
    denominazione = item.get("denominazioneAtto")
    titolo = item.get("titoloAtto")
    return ActInfo(
        ref=ActRef(str(item["dataGU"]), str(item["codiceRedazionale"]).upper()),
        descrizione=str(item.get("descrizioneAtto") or "").strip(),
        titolo=_clean_title(titolo if isinstance(titolo, str) else None),
        denominazione=denominazione if isinstance(denominazione, str) else None,
        numero=str(item.get("numeroProvvedimento") or item.get("numeroAtto") or "") or None,
        anno=str(item.get("annoProvvedimento") or "") or None,
        data_emanazione=data_em,
        # Campi presenti nelle risposte reali ma non elencati nella specifica: opzionali.
        extra={
            "dataUltimaModifica": item.get("dataUltimaModifica"),
            "ultimiAttiModificanti": item.get("ultimiAttiModificanti"),
        },
    )


def act_from_detail(ref: ActRef, atto: dict[str, Any]) -> ActInfo:
    """Converte il blocco data.atto di dettaglio-atto in ActInfo."""
    anno, mese, giorno = (
        atto.get("annoProvvedimento"),
        atto.get("meseProvvedimento"),
        atto.get("giornoProvvedimento"),
    )
    anno, mese, giorno = _to_int(anno), _to_int(mese), _to_int(giorno)
    data_em = None
    if anno and mese and giorno:
        data_em = f"{anno:04d}-{mese:02d}-{giorno:02d}"
    numero = _to_int(atto.get("numeroProvvedimento"))
    denominazione = atto.get("tipoProvvedimentoDescrizione")
    return ActInfo(
        ref=ref,
        descrizione=str(atto.get("titolo") or "").strip(),
        titolo=_clean_title(atto.get("sottoTitolo") if isinstance(atto.get("sottoTitolo"), str) else None),
        denominazione=denominazione if isinstance(denominazione, str) else None,
        numero=str(numero) if numero else None,
        anno=str(anno) if anno else None,
        data_emanazione=data_em,
    )


def yyyymmdd_to_iso(value: Any) -> str | None:
    """'20090704' -> '2009-07-04'; '99999999' o valori non validi -> None."""
    if not isinstance(value, str) or not re.match(r"^\d{8}$", value) or value == "99999999":
        return None
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


# ------------------------------------------------------------- HTML -> testo ---


_HEADING_CLASSES = frozenset({"article-heading-akn", "article-pre-comma-text-akn"})


class _TextExtractor(HTMLParser):
    _BLOCK: ClassVar[frozenset[str]] = frozenset({"div", "p", "br", "h1", "h2", "h3", "h4", "li", "tr"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._anchor: list[str] = []
        self.heading: str | None = None
        self._in_heading = False
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag in self._BLOCK:
            self.parts.append("\n")
        if tag == "a":
            self._href = a.get("href") or None
            self._anchor = []
        # Rubrica: "article-heading-akn" di norma; negli articoli inseriti da novelle
        # (es. art. 13-bis L. 400/1988) è in "article-pre-comma-text-akn" (verificato).
        classes = (a.get("class") or "").split()
        if tag == "div" and self.heading is None and _HEADING_CLASSES & set(classes):
            self._in_heading = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            m = _URN_RE.search(unquote(self._href))
            if m:
                self.links.append((" ".join("".join(self._anchor).split()), m.group(0)))
            self._href = None
        if tag == "div" and self._in_heading:
            self._in_heading = False
            self.heading = " ".join("".join(self._heading_parts).split()) or None
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)
        if self._href:
            self._anchor.append(data)
        if self._in_heading:
            self._heading_parts.append(data)


@dataclass
class ParsedArticle:
    """Testo estratto da articoloHtml."""

    text: str
    heading: str | None
    links: list[tuple[str, str]]


def parse_article_html(markup: str) -> ParsedArticle:
    """Estrae testo semplice, rubrica e link URN dall'HTML dell'articolo."""
    parser = _TextExtractor()
    parser.feed(html.unescape(markup) if "&" in markup and "<" not in markup else markup)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    text = "\n".join(line for line in lines if line)
    return ParsedArticle(text=text, heading=parser.heading, links=parser.links)


def is_article_abrogated(text: str) -> bool:
    """Euristica: marcatore canonico di articolo interamente abrogato."""
    return bool(re.search(r"\(\(\s*ARTICOLO ABROGATO", text[:400], re.IGNORECASE))


# ------------------------------------------------------------------ client ---


class NormattivaClient:
    """Client httpx asincrono con retry e backoff esponenziale."""

    def __init__(
        self,
        api_url: str = DEFAULT_API_URL,
        portal_url: str = DEFAULT_PORTAL_URL,
        *,
        timeout: float = 15.0,
        max_retries: int = 2,
        backoff_base: float = 0.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        # L'API OpenData si aspetta l'Origin del portale dati.normattiva.it.
        self._headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "it-IT,it;q=0.9",
            "Content-Type": "application/json",
            "Origin": portal_url.rstrip("/"),
            "User-Agent": "lexbot-telegram/0.1 (+https://github.com/)",
        }

    async def aclose(self) -> None:
        """Chiude il client HTTP se posseduto."""
        if self._owns_client:
            await self._client.aclose()

    def endpoint(self, path: str) -> str:
        """URL completo di un endpoint."""
        return self.api_url + path

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = self.endpoint(path)
        last: NormattivaError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._client.post(url, json=body, headers=self._headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = NormattivaError(
                    f"Errore di rete verso Normattiva: {type(exc).__name__}", retryable=True
                )
            else:
                result = self._handle_response(resp)
                if not isinstance(result, NormattivaError):
                    return result
                if not result.retryable:
                    raise result
                last = result
            if attempt < self.max_retries:
                await asyncio.sleep(self.backoff_base * (2**attempt))
        assert last is not None
        raise last

    @staticmethod
    def _handle_response(resp: httpx.Response) -> dict[str, Any] | NormattivaError:
        """Classifica la risposta secondo i formati della specifica (par. 1.3.10).

        Formati di errore gestiti:
        - gateway: {"code": "404", "type": "Status report", "description": "No matching resource..."}
        - applicativo: {"message": "Atto non trovato", "code": null} | {"message": ..., "code": "500"}
        - Spring: {"timestamp": ..., "status": 4xx/5xx, "error": "...", "path": "/bff-..."}
        - WAF IPZS: HTTP 409 {"status": "KO", "message": "... bloccata dai sistemi di protezione ..."}
        """
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        body = payload if isinstance(payload, dict) else {}
        message = body.get("message") if isinstance(body.get("message"), str) else None
        error = body.get("error") if isinstance(body.get("error"), str) else None
        code = str(body["code"]) if body.get("code") is not None else None
        status = resp.status_code

        if status == 200:
            if not isinstance(payload, dict):
                # Corpo vuoto o non JSON con 200: osservato come errore transitorio.
                return NormattivaError(
                    "Risposta Normattiva vuota o non in formato JSON", status=200, retryable=True
                )
            if payload.get("success") is False:
                return NormattivaNotFound(
                    f"Normattiva ha risposto senza esito: {message or 'nessun dettaglio'}", status=200
                )
            return payload
        if status == 404:
            is_gateway = code == "404" or "description" in body
            is_spring = "path" in body and "status" in body
            if is_gateway and not is_spring:
                return NormattivaError(
                    "Endpoint Normattiva non trovato (404 del gateway): verificare NORMATTIVA_API_URL",
                    status=404,
                    code=code,
                )
            return NormattivaNotFound("Atto o articolo non trovato su Normattiva", status=404, code=code)
        if status == _WAF_STATUS and str(body.get("status", "")).upper() == "KO":
            return NormattivaError(
                "Richiesta bloccata dai sistemi di protezione di Normattiva", status=status, code=code
            )
        detail = (message or error or resp.reason_phrase or "errore").strip()
        return NormattivaError(
            f"Normattiva HTTP {status}: {detail}",
            status=status,
            code=code,
            retryable=status in _RETRYABLE_STATUS,
        )

    async def search_simple(self, text: str, *, page_size: int = 10, page: int = 1) -> dict[str, Any]:
        """Ricerca semplice (par. 1.3.1): parole nel titolo e/o testo."""
        body = {
            "testoRicerca": text,
            "orderType": "recente",
            "paginazione": {"paginaCorrente": page, "numeroElementiPerPagina": page_size},
        }
        return self._validate_search(await self._post(PATH_SEARCH_SIMPLE, body))

    async def search_advanced(self, *, page_size: int = 10, **filters: Any) -> dict[str, Any]:
        """Ricerca avanzata (par. 1.3.2). I filtri usano i nomi della specifica."""
        body: dict[str, Any] = {k: v for k, v in filters.items() if v not in (None, "")}
        body.setdefault("orderType", "recente")
        body["paginazione"] = {"paginaCorrente": 1, "numeroElementiPerPagina": page_size}
        return self._validate_search(await self._post(PATH_SEARCH_ADVANCED, body))

    @staticmethod
    def _validate_search(payload: dict[str, Any]) -> dict[str, Any]:
        """Verifica la struttura e scarta gli elementi non conformi di listaAtti."""
        lista = payload.get("listaAtti")
        if lista is None and payload.get("numeroAttiTrovati") in (0, "0"):
            lista = []  # nessun risultato: alcune risposte omettono la lista
        if not isinstance(lista, list):
            raise NormattivaError("Risposta di ricerca Normattiva inattesa (manca listaAtti)")
        payload["listaAtti"] = [i for i in lista if _has_key(i)]
        payload["numeroAttiTrovati"] = _to_int(payload.get("numeroAttiTrovati")) or 0
        return payload

    async def article_detail(
        self,
        ref: ActRef,
        *,
        articolo: int = 1,
        sotto_articolo: int = 1,
        data_vigenza: str | None = None,
        id_gruppo: int = 0,
    ) -> dict[str, Any]:
        """Dettaglio di un articolo (par. 1.3.7). Ritorna il blocco data.atto.

        TODO(verifica API): alcuni codici (es. codice civile) richiedono un
        idGruppo diverso da 0 non scopribile via API sincrona; in quel caso
        l'API risponde senza 'data' e solleviamo NormattivaNotFound.
        """
        body: dict[str, Any] = {
            "dataGU": ref.data_gu,
            "codiceRedazionale": ref.codice_redazionale,
            "idArticolo": articolo,
            "sottoArticolo": sotto_articolo,
            "sottoArticolo1": 0,
            "versione": 0,
            "idGruppo": id_gruppo,
            "progressivo": 0,
        }
        if data_vigenza:
            body["dataVigenza"] = data_vigenza
        payload = await self._post(PATH_ARTICLE_DETAIL, body)
        data = payload.get("data")
        atto = data.get("atto") if isinstance(data, dict) else None
        if not isinstance(atto, dict) or not isinstance(atto.get("articoloHtml"), str):
            raise NormattivaNotFound(
                f"Articolo {format_article(articolo, sotto_articolo)} non disponibile via API"
            )
        return atto

    # ----------------------------------------------------- risoluzione atti ---

    async def resolve_citation(self, cit: Citation) -> ActInfo:
        """Risolve una citazione (tipo/anno/numero) in un atto tramite ricerca avanzata."""
        filters: dict[str, Any] = {
            "denominazioneAtto": cit.act_type.denominazione,
            "annoProvvedimento": cit.anno,
            "numeroProvvedimento": cit.numero,
        }
        payload = await self.search_advanced(page_size=20, **filters)
        items = [act_from_search_item(i) for i in payload["listaAtti"] if _has_key(i)]
        if cit.numero:
            items = [a for a in items if a.numero == cit.numero]
        if cit.data_emanazione:
            exact = [a for a in items if a.data_emanazione == cit.data_emanazione]
            items = exact or items
        if not items:
            raise NormattivaNotFound("Nessun atto corrispondente alla citazione su Normattiva")
        return items[0]

    async def resolve(self, parsed: ParsedLawId) -> ActInfo:
        """Ritorna i metadati dell'atto indicato da un ParsedLawId."""
        if parsed.citation is not None:
            return await self.resolve_citation(parsed.citation)
        assert parsed.ref is not None
        atto = await self.article_detail(parsed.ref)
        return act_from_detail(parsed.ref, atto)

    async def classe_provvedimento(self, act: ActInfo) -> tuple[str | None, dict[str, Any] | None]:
        """Determina la classe provvedimento (1/2/3) filtrando la ricerca avanzata.

        La ricerca non restituisce la classe nei risultati: la deduciamo
        verificando in quale filtro classeProvvedimento compare l'atto.
        Ritorna (classe, elemento listaAtti) oppure (None, None).
        """
        if not act.denominazione or not act.anno:
            return None, None
        for classe in (CLASSE_ABROGATO, CLASSE_AGGIORNATO, CLASSE_SENZA_AGGIORNAMENTI):
            payload = await self.search_advanced(
                page_size=20,
                denominazioneAtto=act.denominazione,
                annoProvvedimento=act.anno,
                numeroProvvedimento=act.numero,
                classeProvvedimento=classe,
            )
            for item in payload["listaAtti"]:
                if str(item["codiceRedazionale"]).upper() == act.ref.codice_redazionale:
                    return classe, item
        return None, None


_DATE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CODICE = re.compile(r"^[A-Za-z0-9]{5,12}$")


def _has_key(item: Any) -> bool:
    """True se l'elemento ha una chiave primaria valida (dataGU + codiceRedazionale)."""
    return (
        isinstance(item, dict)
        and isinstance(item.get("dataGU"), str)
        and bool(_DATE_ISO.match(item["dataGU"]))
        and bool(_CODICE.match(str(item.get("codiceRedazionale") or "")))
    )


def _to_int(value: Any) -> int | None:
    """Conversione tollerante di campi numerici (int o stringa) restituiti dall'API."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
