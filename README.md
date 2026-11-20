# lexbot-telegram

Bot Telegram di **ricerca** sulla legislazione italiana. Trova norme e articoli, ne verifica lo stato
di vigenza e restituisce i link ufficiali Normattiva e Gazzetta Ufficiale.

> **Non è un servizio di consulenza legale.** Le risposte servono a individuare le fonti; ogni
> risposta si chiude con: _Informazione normativa di supporto, non parere legale._

Ogni risposta riporta:

- la norma precisa (atto, numero, anno, articolo);
- l'URL Normattiva (ELI o URN) e, quando serve, quello della Gazzetta Ufficiale;
- la data di consultazione;
- lo stato di vigenza (vigente, modificato, abrogato), oppure "non verificabile".

Il link Normattiva è garantito dal codice, non solo dal prompt. Un link nella risposta dell'LLM conta
solo se corrisponde a un URL restituito dai tool (ELI `https://www.normattiva.it/eli/id/...` o
risolutore URN `https://www.normattiva.it/uri-res/N2Ls?urn:nir:...`). Altrimenti il bot aggiunge la
sezione "Fonti verificate su Normattiva"; se nessuna norma è stata verificata, rimanda al portale.
Anche i messaggi di servizio (aiuto, errori, limiti) contengono il link. L'unica eccezione è il
rifiuto agli utenti non autorizzati, che non rivela nulla del servizio.

## Architettura

```
Utente Telegram
      |
      v  HTTPS webhook (header X-Telegram-Bot-Api-Secret-Token)
+-----------------------------+        Streamable HTTP (/mcp)        +-----------------------------+
| lexbot-telegram  (FastAPI)  | -----------------------------------> | lexbot-mcp  (FastMCP)       |
| - POST /telegram/webhook    |   Bearer MCP_AUTH_TOKEN (opzionale)  | - 5 tool normativi          |
| - GET  /healthz             |                                      | - GET /healthz              |
| - python-telegram-bot v22   |                                      +--------------+--------------+
| - allowlist, rate limit     |                                                     |
| - LLM con tool calling      | --> API OpenAI-compatible (gpt-4.1-mini)            v
+-----------------------------+                                       API Normattiva OpenData (IPZS)
                                                                      (opzionale: discovery Lexifina,
                                                                       sempre verificata su Normattiva)
```

Lo schema sopra è la modalità `http`, con due processi separati. Con `MCP_TRANSPORT=inprocess` i 5 tool
di `mcp_server` girano nello stesso processo del bot, tramite il trasporto in memoria di FastMCP, senza
rete e senza `MCP_AUTH_TOKEN`. È la modalità usata dal blueprint `render.yaml` sul piano Free.

| Componente | Percorso | Ruolo |
|---|---|---|
| Bot | `app/main.py` | FastAPI: webhook, health check, elaborazione degli update in background |
| Bot | `app/telegram_bot.py` | Comandi `/start`, `/aiuto`, `/fonti`, `/verifica` e domande libere |
| Bot | `app/llm.py` | Provider OpenAI-compatible e ciclo tool calling (al primo turno l'uso dei tool è obbligatorio) |
| Bot | `app/guardrails.py` | Allowlist, rate limit, disclaimer, suddivisione dei messaggi oltre 4096 caratteri, HTML sicuro |
| Bot | `app/mcp_client.py` | Client FastMCP con timeout e risultati troncati a 12.000 caratteri |
| Bot | `app/prompts/system_prompt.md` | Prompt di sistema versionato |
| MCP | `mcp_server/server.py` | Server FastMCP con i 5 tool |
| MCP | `mcp_server/normattiva.py` | Client dell'API Normattiva (retry/backoff) e parsing di URN, ELI e citazioni |
| MCP | `mcp_server/discovery.py` | Adapter Lexifina opzionale (disattivato di default) |
| Dati | `data/*.yaml` | Indice tematico (solo citazioni), fonti, query di prova. Nessun testo di legge |

### Tool MCP

| Tool | Cosa fa |
|---|---|
| `search_italian_law(query, materia?, limit?)` | Cerca prima per citazione esplicita ("d.lgs. 196/2003"), poi nell'indice tematico, poi in Lexifina (se attivo), infine con la ricerca testuale Normattiva |
| `get_law_article(law_id, article?)` | Testo essenziale, rubrica e date di vigenza di un articolo ("13", "13-bis") |
| `check_law_vigence(law_id, as_of_date?)` | Stato vigente, modificato o abrogato, ricavato dalla *classe provvedimento* Normattiva |
| `get_related_laws(law_id, limit?)` | Atti citati nel testo (link URN presenti nei primi articoli) |
| `get_official_source(law_id)` | URL Normattiva e Gazzetta Ufficiale, URN ed ELI |

`law_id` accetta: l'id interno `AAAA-MM-GG:CODICE` (restituito dalla ricerca), un URN
(`urn:nir:stato:legge:1990-08-07;241~art3`), un URL ELI Normattiva o GU, un URL `caricaDettaglioAtto`
oppure una citazione testuale (`legge 23 agosto 1988, n. 400`, `dpr 445/2000`).

## Prerequisiti

- Python 3.12 (consigliato [uv](https://docs.astral.sh/uv/))
- Un bot Telegram creato con [@BotFather](https://t.me/BotFather)
- Una chiave API OpenAI, o di un provider compatibile con `/chat/completions`
- Per provare il webhook in locale, un tunnel HTTPS (es. `cloudflared`)

## Configurazione

Copia `.env.example` in `.env` e valorizza le variabili:

| Variabile | Descrizione |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token di BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | Stringa casuale (es. `openssl rand -hex 32`). Se contiene caratteri non ammessi da Telegram (solo `A-Za-z0-9_-`), il bot usa il suo SHA-256 esadecimale |
| `PUBLIC_BASE_URL` | URL pubblico HTTPS del bot. Su Render si può omettere: si usa `RENDER_EXTERNAL_URL` |
| `ALLOWED_TELEGRAM_USER_IDS` | User ID ammessi, separati da virgola. **Se è vuota, nessuno è autorizzato** |
| `LLM_PROVIDER` / `LLM_MODEL` / `OPENAI_API_KEY` | `openai`, `gpt-4.1-mini`, chiave API |
| `MCP_TRANSPORT` | `http` (default): server MCP separato raggiunto via URL. `inprocess`: tool eseguiti nel processo del bot, un solo servizio |
| `MCP_SERVER_URL` | Solo con `MCP_TRANSPORT=http`. Es. `http://localhost:8001/mcp`. Se è vuota si usa `MCP_SERVER_HOSTPORT`, poi il default locale |
| `NORMATTIVA_BASE_URL` | `https://dati.normattiva.it`, usato come `Origin` verso l'API |
| `LOG_LEVEL` / `RUNTIME_ENV` / `PORT` | `INFO`, `development` / `production` / `test`, `8000` |

Variabili opzionali, con default nel codice:

| Variabile | Servizio | Default / uso |
|---|---|---|
| `MCP_AUTH_TOKEN` | entrambi | vuota = nessuna autenticazione; se valorizzata deve coincidere sui due servizi |
| `MCP_SERVER_HOSTPORT` | bot | `host:porta` privati del server MCP (impostata dal blueprint Render) |
| `RENDER_EXTERNAL_URL` | bot | impostata da Render; usata se manca `PUBLIC_BASE_URL` |
| `OPENAI_BASE_URL` | bot | `https://api.openai.com/v1` |
| `NORMATTIVA_API_URL` | MCP | `https://api.normattiva.it/t/normattiva.api` (ambiente di esercizio) |
| `NORMATTIVA_TIMEOUT` / `NORMATTIVA_MAX_RETRIES` | MCP | `10` s per chiamata / `2` tentativi aggiuntivi |
| `TOOL_TIMEOUT_SECONDS` | MCP | `25`: tempo massimo di un tool, sotto i 30 s del bot |
| `LEXIFINA_DISCOVERY_ENABLED` | MCP | `false` |
| `MCP_HOST` / `MCP_PORT` | MCP | `0.0.0.0` / `8001` |

Il server MCP legge la porta da `--port` o `MCP_PORT`, mai da `PORT`. Così i due processi possono
condividere lo stesso `.env` in locale. Con `MCP_TRANSPORT=inprocess` le variabili "MCP" della tabella
valgono per il servizio del bot.

### Configurazione Telegram

1. Su @BotFather: `/newbot`, poi copia il token in `TELEGRAM_BOT_TOKEN`.
2. Facoltativo: `/setcommands` con

   ```
   start - Presentazione ed esempi
   aiuto - Comandi disponibili
   fonti - Fonti ufficiali utilizzate
   verifica - Verifica vigenza e link ufficiali di una norma
   ```

3. Per conoscere il tuo user ID, scrivi a [@userinfobot](https://t.me/userinfobot) e mettilo in `ALLOWED_TELEGRAM_USER_IDS`.
4. Il webhook viene registrato **in automatico all'avvio** (`setWebhook` con `secret_token`, solo
   update `message`) se l'URL pubblico (`PUBLIC_BASE_URL` o `RENDER_EXTERNAL_URL`) e
   `TELEGRAM_WEBHOOK_SECRET` sono valorizzati e
   `RUNTIME_ENV` non è `test`. In produzione il polling non viene mai usato.

## Avvio locale

```bash
cd lexbot-telegram
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
cp .env.example .env    # poi modifica i valori

# Terminale 1 - server MCP
.venv/bin/python -m mcp_server.server --port 8001

# Terminale 2 - tunnel HTTPS (annota l'URL https://....trycloudflare.com)
cloudflared tunnel --url http://localhost:8000

# Terminale 3 - bot (PUBLIC_BASE_URL = URL del tunnel)
.venv/bin/uvicorn app.main:app --port 8000

# Verifiche
curl http://localhost:8001/healthz     # {"status":"ok"}
curl http://localhost:8000/healthz     # {"status":"ok"}
curl -X POST http://localhost:8000/telegram/webhook -d '{}'   # 403: secret mancante
```

In alternativa, senza il terminale 1: avvia il bot con `MCP_TRANSPORT=inprocess`, che esegue i tool nel
proprio processo. All'avvio il log `mcp_transport` indica la modalità attiva.

Con Docker (un'unica immagine per entrambi i servizi, utente non-root):

```bash
docker build -t lexbot .
docker run --rm --env-file .env -p 8001:8001 lexbot python -m mcp_server.server --port 8001
docker run --rm --env-file .env -p 8000:8000 lexbot
```

## Test

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -q
```

I test non fanno chiamate di rete: `respx` intercetta Normattiva, Lexifina e il provider LLM, mentre il
server MCP viene provato in memoria con `fastmcp.Client`. Coprono:

- webhook (secret mancante o errato -> 403);
- `/healthz`, allowlist e rate limiter;
- parsing di URN, ELI e citazioni, identificativi non riconosciuti;
- risposte simulate con la struttura reale (tutti i campi della specifica IPZS) ed errori nei formati
  documentati: 404 del gateway e applicativo, formato `timestamp/status/error/path`, 400, 422, 429,
  500, 503 e 409 del WAF;
- timeout HTTP e del singolo tool, risposte malformate (corpo vuoto, HTML, elementi non validi), assenza
  di risultati;
- i 5 tool, anche tramite `fastmcp.Client`;
- presenza del link Normattiva in ogni risposta e coerenza del blueprint Render con il codice;
- suddivisione dei messaggi ed escaping HTML;
- ciclo LLM e comando `/verifica`.

La CI GitHub (`.github/workflows/ci.yml`) esegue ruff e pytest a ogni push su `main` e a ogni pull request.
Le domande in `data/test_queries.yaml` servono per i test manuali end-to-end.

## Deploy su Render

Ci sono due blueprint. **Non servono modifiche al codice** con nessuno dei due:

| File | Piano | Servizi | Costo |
|---|---|---|---|
| `render.yaml` (default) | `free` | 1: `lexbot-telegram` con i tool in-process (`MCP_TRANSPORT=inprocess`) | gratuito |
| `render-starter.yaml` | `starter` | 2: `lexbot-telegram` e `lexbot-mcp` sulla rete privata | 2 istanze a pagamento |

Il piano Free richiede un solo servizio perché i servizi Free non possono *ricevere* traffico dalla rete
privata di Render. Altri limiti del piano Free:

- il servizio si spegne dopo 15 minuti senza richieste. Il primo messaggio successivo attende circa un
  minuto, poi le risposte tornano normali. Telegram ritenta la consegna degli update, quindi i messaggi
  non vanno persi;
- ci sono 750 ore gratuite al mese per workspace: un solo servizio sempre acceso ne usa circa 720;
- Render può riavviare il servizio in qualsiasi momento. Il bot non conserva stato, salvo il rate limiter
  in memoria.

Valori impostati in automatico:

| Variabile | Come viene impostata |
|---|---|
| `TELEGRAM_WEBHOOK_SECRET` | `generateValue: true` (base64), normalizzata dal bot nel formato ammesso da Telegram |
| URL pubblico del bot | `RENDER_EXTERNAL_URL`, impostata da Render |
| `MCP_AUTH_TOKEN` (solo `render-starter.yaml`) | generata sul servizio MCP e copiata nel bot con `fromService.envVarKey` |
| `MCP_SERVER_HOSTPORT` (solo `render-starter.yaml`) | `fromService.property: hostport`: il bot chiama `http://<hostport>/mcp` sulla rete privata |

Passaggi:

1. Pubblica la repo su GitHub o GitLab.
2. **Render Dashboard -> New -> Blueprint**, seleziona la repo e conferma `render.yaml`. Per la versione
   a pagamento indica `render-starter.yaml` come Blueprint Path.
3. Alla richiesta dei valori `sync: false` del servizio `lexbot-telegram`, inserisci:
   - `TELEGRAM_BOT_TOKEN`: token di BotFather;
   - `ALLOWED_TELEGRAM_USER_IDS`: i tuoi user ID, separati da virgola;
   - `OPENAI_API_KEY`: chiave del provider LLM.
4. **Apply**. Render crea i servizi, esegue `pip install -r requirements.txt` e controlla `GET /healthz`.
   All'avvio il bot registra da solo il webhook su `<RENDER_EXTERNAL_URL>/telegram/webhook`.
5. Verifica:
   - `curl https://<nome-servizio-bot>.onrender.com/healthz` restituisce `{"status":"ok"}`;
   - nei log del bot ci sono gli eventi `mcp_transport` (`inprocess` sul piano Free) e `webhook_set`;
   - su Telegram, `/start` al bot.

Note:

- Il rate limiter è in memoria, quindi il bot gira con `numInstances: 1`.
- Per ruotare il secret del webhook, rigenera `TELEGRAM_WEBHOOK_SECRET` in dashboard e riavvia: il
  webhook viene registrato di nuovo all'avvio.

## Allineamento con l'API Normattiva OpenData

Riferimento: "Normattiva - Specifiche API Open Data" (IPZS, rev. 08 del 30/10/2025), verificata anche con
chiamate all'ambiente di esercizio il 2026-11-20.

| Aspetto | Specifica | Implementazione |
|---|---|---|
| Base URL | esercizio `https://api.normattiva.it/t/normattiva.api` | identico (`NORMATTIVA_API_URL`) |
| Autenticazione | nessuna in esercizio (mutua TLS solo in collaudo) | nessuna; header `Origin` del portale come negli esempi |
| Ricerca | `POST .../bff-opendata/v1/api/v1/ricerca/semplice` e `/avanzata` (par. 1.3.1-1.3.2) | identico; filtri `denominazioneAtto`, `annoProvvedimento`, `numeroProvvedimento`, `classeProvvedimento` |
| Dettaglio | par. 1.3.7: suffisso `bff-mobile`, esempio `bff-opendata` | `bff-opendata` (l'unico che risponde in esercizio) |
| Date | il testo dice `YYYY-DD-MM`, l'esempio usa `YYYY-MM-DD` | `YYYY-MM-DD` (verificato) |
| Classe provvedimento | 1 senza aggiornamenti, 2 aggiornato, 3 abrogato (par. 1.2.4) | vigente, modificato, abrogato |
| Errori | 400/404/422/500 nei formati par. 1.3.1, 1.3.7, 1.3.10 | tutti riconosciuti; 404 applicativo = "non trovato", 404 del gateway = errore di configurazione |
| Limiti | nessun rate limit documentato; 7000 atti solo per `ricerca/aggiornati` (codice 1502) | pagine di 5-20 risultati; il 409 del WAF IPZS non viene ritentato |
| Campi non documentati | `dataUltimaModifica`, `ultimiAttiModificanti` presenti nelle risposte reali | letti come opzionali |

Gestione degli errori:

- **Ritentati con backoff esponenziale** (al massimo 2 volte): 429, 500, 502, 503, 504, errori di rete o
  timeout, risposta 200 vuota o non JSON.
- **Non ritentati**: 400, 422, 409 del WAF, 404.
- **Timeout per tool** di 25 s.
- **Risposte malformate**: gli elementi di `listaAtti` senza `dataGU`/`codiceRedazionale` validi vengono
  scartati e i campi numerici sono convertiti in modo tollerante.
- **Identificativi non riconosciuti** (URN regionali o di tipi non supportati, ELI malformati, URL
  estranei): errore leggibile con i formati accettati.
- **Errori interni**: non espongono mai dettagli all'LLM.

## Esempio di conversazione

```
Utente: Cosa prevede l'art. 13-bis della legge 400/1988?

LexBot: Sintesi: l'art. 13-bis della legge 23 agosto 1988, n. 400 riguarda la chiarezza
dei testi normativi: le norme che modificano o abrogano altre norme devono indicarle
espressamente, e i rinvii devono indicare il testo o la materia richiamati.

Norme rilevanti
- LEGGE 23 agosto 1988, n. 400 - stato: vigente con modifiche
  - Art. 13-bis (Chiarezza dei testi normativi): 1. Il Governo, nell'ambito delle proprie
    competenze, provvede a che ... [testo essenziale]
    https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:1988-08-23;400~art13bis

Versione consultata: vigente alla data di consultazione 2026-11-20.

Informazione normativa di supporto, non parere legale.

Utente: /verifica d.lgs. 196/2003

LexBot: DECRETO LEGISLATIVO 30 giugno 2003, n. 196
Stato di vigenza: vigente con modifiche (testo consolidato)
URN: urn:nir:stato:decreto.legislativo:2003-06-30;196
Normattiva: testo vigente  ·  Gazzetta Ufficiale: pubblicazione
Data di consultazione: 2026-11-20T10:15:02+00:00
```

Il testo è indicativo: la formulazione esatta dipende dal modello e dai dati restituiti in quel momento.

## Limiti legali e sicurezza

- **Il solo testo ufficiale e definitivo è quello pubblicato in Gazzetta Ufficiale.** Il testo
  Normattiva è un testo consolidato a fini informativi.
- Il bot non dà pareri. Per casi personali, contenziosi o strategie indica solo le norme e rimanda a
  un professionista abilitato.
- Lo stato di vigenza deriva dalla *classe provvedimento* Normattiva (abrogato, aggiornato, senza
  aggiornamenti) e descrive lo stato **attuale**. Per una data passata (`as_of_date`) lo stato viene
  segnato come non verificato.
- La ricerca testuale Normattiva ordina per data, non per pertinenza. Per questo hanno priorità le
  citazioni e l'indice tematico, e l'LLM deve scartare i risultati non attinenti.
- Alcuni codici con struttura particolare (es. art. 2043 del codice civile, R.D. 262/1942) non sono
  raggiungibili con l'API sincrona. Il tool restituisce `trovato: false` con il link ufficiale N2Ls.
- Anti-abuso:
  - allowlist obbligatoria;
  - 10 richieste ogni 5 minuti per utente;
  - timeout di 30 s per ogni chiamata a LLM e MCP;
  - query sanificate e troncate a 2000 caratteri.
- Privacy:
  - i log (JSON su stdout) contengono solo `user_id`, hash troncato e lunghezza della query, mai il testo;
  - il logger `httpx` è a WARNING per non esporre il token del bot contenuto negli URL.
- Sicurezza del webhook:
  - il secret token viene confrontato a tempo costante;
  - il bot risponde subito 200 ed elabora l'update in background;
  - le risposte sono convertite in HTML Telegram con escaping completo e link solo `http(s)`.
- La repo non contiene testi di legge: solo indici, alias, configurazione, test e prompt.
- La discovery Lexifina è **disattivata di default** perché invierebbe la query a un servizio di terzi.
  Quando è attiva, ogni candidato viene verificato su Normattiva prima di essere mostrato.

## Roadmap

- Rate limit condiviso (Redis) per più istanze; cache delle risoluzioni di citazioni.
- Supporto `idGruppo` per i codici strutturati (codice civile, codice penale).
- Vigenza storica affidabile tramite le versioni multivigenti.
- Ricerca semantica offline su un corpus come [italia-corpus](https://github.com/ahmeabd/italia-corpus)
  (RAG), sempre con verifica finale su Normattiva.
- Più provider LLM (Anthropic, modelli locali) dietro l'interfaccia `LLMProvider`.

## Crediti e riferimenti

- [Normattiva OpenData](https://dati.normattiva.it/) ([Il progetto](https://dati.normattiva.it/Il-progetto)):
  API ufficiale dell'Istituto Poligrafico e Zecca dello Stato, fonte primaria del bot.
- [adellorto/normattiva-mcp](https://github.com/adellorto/normattiva-mcp): riferimento per la specifica
  delle API OpenData e per un server MCP su Normattiva.
- [capazme/mcp-legal-it](https://github.com/capazme/mcp-legal-it): riferimento per la struttura dei tool
  legali italiani via MCP.
- [lexifina/italy-law](https://github.com/lexifina/italy-law): indice per articolo dei testi Normattiva
  (CC BY 4.0), usato solo come discovery opzionale.
- [ahmeabd/italia-corpus](https://github.com/ahmeabd/italia-corpus): corpus normativo italiano, citato
  in roadmap per una futura ricerca semantica offline.

Le repository di riferimento sono state consultate in sola lettura.

### Licenze

- Codice: MIT (vedi `pyproject.toml`).
- I contenuti normativi Normattiva sono rilasciati dall'IPZS con licenza
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.it). Il bot attribuisce la fonte in ogni
  risposta. Il solo testo ufficiale e definitivo è quello pubblicato nella Gazzetta Ufficiale della
  Repubblica Italiana.
