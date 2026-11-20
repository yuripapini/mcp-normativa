"use strict";

// LexBot web: schede Domanda, Verifica, Strada e Scrivi (pannelli Strada/Scrivi in panels.js).
// Il testo di Domanda passa da LexMask prima dell'invio; i valori originali tornano solo nel browser.
// Codice di accesso e storico restano nel browser (localStorage); la pagina funziona anche senza.

(function () {
  const API = String(window.LEXBOT_API || "").replace(/\/+$/, "");
  const CODE_KEY = "lexbot.code";
  const HISTORY_KEY = "lexbot.history";
  const HISTORY_MAX = 50;
  const REQUEST_TIMEOUT_MS = 150000;

  const MODES = {
    ask: {
      path: "/api/ask",
      field: "question",
      button: "Chiedi",
      hint: "Risposta con IA e fonti Normattiva (10-30 secondi).",
      placeholder: "Es. Art. 186 d.lgs. 285/1992: sanzioni per guida in stato di ebbrezza",
      label: "Domanda",
      panel: "query",
    },
    verifica: {
      path: "/api/verifica",
      field: "law_id",
      button: "Verifica",
      hint: "Senza IA: stato di vigenza e link ufficiali in pochi secondi.",
      placeholder: "Es. d.lgs. 285/1992 oppure legge 241/1990",
      label: "Verifica",
      panel: "query",
    },
    strada: { panel: "strada", label: "Strada" },
    scrivi: { panel: "scrivi", label: "Scrivi" },
  };

  const $ = (id) => document.getElementById(id);
  const el = {
    login: $("login"),
    loginForm: $("login-form"),
    code: $("code"),
    loginError: $("login-error"),
    app: $("app"),
    logout: $("logout"),
    tabs: Array.from(document.querySelectorAll(".tab")),
    form: $("query-form"),
    query: $("query"),
    hint: $("mode-hint"),
    submit: $("submit"),
    result: $("result"),
    historyList: $("history-list"),
    historyEmpty: $("history-empty"),
    clearHistory: $("clear-history"),
    askMaskInfo: $("ask-mask-info"),
    stradaPanel: $("strada-panel"),
    scriviForm: $("scrivi-form"),
  };

  let mode = "ask";
  let busy = false;

  // ---------------------------------------------------------------- storage ---
  const storage = {
    get(key, fallback) {
      try {
        const raw = window.localStorage.getItem(key);
        return raw === null ? fallback : JSON.parse(raw);
      } catch (_) {
        return fallback;
      }
    },
    set(key, value) {
      try {
        window.localStorage.setItem(key, JSON.stringify(value));
      } catch (_) {
        /* storage non disponibile: si continua senza salvare */
      }
    },
    remove(key) {
      try {
        window.localStorage.removeItem(key);
      } catch (_) {
        /* ignorato */
      }
    },
  };

  let accessCode = storage.get(CODE_KEY, "");
  let history = storage.get(HISTORY_KEY, []);
  if (!Array.isArray(history)) history = [];

  // -------------------------------------------------------------------- API ---
  class ApiError extends Error {
    constructor(status, message) {
      super(message);
      this.status = status;
    }
  }

  async function call(path, body, code) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    let response;
    try {
      response = await fetch(API + path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Access-Code": code },
        body: JSON.stringify(body || {}),
        signal: controller.signal,
      });
    } catch (_) {
      throw new ApiError(0, "Servizio non raggiungibile. Controlla la connessione e riprova tra un minuto.");
    } finally {
      clearTimeout(timer);
    }
    let data = null;
    try {
      data = await response.json();
    } catch (_) {
      data = null;
    }
    if (!response.ok) {
      // 422 di FastAPI: detail è una lista di errori di validazione (es. testo oltre 4000 caratteri
      // dopo il mascheramento): messaggio generico invece della lista.
      const invalid = response.status === 422 || (data && Array.isArray(data.detail));
      const detail = invalid
        ? "Testo non valido o troppo lungo."
        : data && typeof data.detail === "string"
          ? data.detail
          : null;
      const fallback = {
        401: "Codice di accesso non valido.",
        403: "La web app non è attiva sul server.",
        429: "Hai raggiunto il limite di richieste. Riprova tra qualche minuto.",
      }[response.status];
      throw new ApiError(response.status, detail || fallback || "Errore del servizio (" + response.status + ").");
    }
    return data;
  }

  // ----------------------------------------------------------------- screen ---
  function showLogin(message) {
    el.app.hidden = true;
    el.login.hidden = false;
    el.loginError.hidden = !message;
    el.loginError.textContent = message || "";
    el.code.value = "";
    setTimeout(() => el.code.focus(), 50);
  }

  function showApp() {
    el.login.hidden = true;
    el.app.hidden = false;
    renderHistory();
  }

  function setMode(next) {
    mode = MODES[next] ? next : "ask";
    const cfg = MODES[mode];
    el.tabs.forEach((tab) => {
      const active = tab.dataset.mode === mode;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    el.form.hidden = cfg.panel !== "query";
    el.stradaPanel.hidden = cfg.panel !== "strada";
    el.scriviForm.hidden = cfg.panel !== "scrivi";
    el.askMaskInfo.hidden = true;
    if (cfg.panel === "query") {
      el.hint.textContent = cfg.hint;
      el.query.placeholder = cfg.placeholder;
      el.submit.textContent = cfg.button;
    }
  }

  // Una sola richiesta alla volta per tutte le schede (condiviso con panels.js tramite ctx).
  function setBusy(value) {
    busy = value;
    document.querySelectorAll("#strada-detail button, #scrivi-submit").forEach((b) => (b.disabled = value));
    el.submit.disabled = value;
    el.query.readOnly = value;
  }

  // ---------------------------------------------------------------- results ---
  function vigenceBadge(text) {
    const m = /stato(?: di vigenza)?\**\s*:\s*\**\s*([a-zàèéìòù ]+)/i.exec(text || "");
    if (!m) return null;
    const s = m[1].trim().toLowerCase();
    if (s.startsWith("abrogat")) return { cls: "bad", label: "Abrogato" };
    if (s.includes("modific")) return { cls: "warn", label: "Vigente con modifiche" };
    if (s.startsWith("vigente")) return { cls: "ok", label: "Vigente" };
    if (s.startsWith("non")) return { cls: "neutral", label: "Vigenza non verificata" };
    return null;
  }

  function formatDate(iso) {
    try {
      return new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" });
    } catch (_) {
      return iso;
    }
  }

  function button(label, cls, onClick) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn " + cls;
    b.textContent = label;
    b.addEventListener("click", onClick);
    return b;
  }

  function renderLoading(query, message) {
    el.result.hidden = false;
    el.result.replaceChildren();
    const box = document.createElement("div");
    box.className = "loading";
    const spinner = document.createElement("div");
    spinner.className = "spinner";
    const msg = document.createElement("span");
    msg.textContent = message;
    box.append(spinner, msg);
    const q = document.createElement("div");
    q.className = "result-query";
    q.textContent = query;
    el.result.append(q, box);
    return msg;
  }

  function renderEntry(entry, { fromHistory }) {
    el.result.hidden = false;
    el.result.replaceChildren();

    const head = document.createElement("div");
    head.className = "result-head";
    const q = document.createElement("div");
    q.className = "result-query";
    q.textContent = entry.query;
    head.append(q);
    const kind = document.createElement("span");
    kind.className = "badge neutral";
    kind.textContent = MODES[entry.mode] ? MODES[entry.mode].label : "Domanda";
    head.append(kind);
    const badge = vigenceBadge(entry.text);
    if (badge) {
      const b = document.createElement("span");
      b.className = "badge " + badge.cls;
      b.textContent = badge.label;
      head.append(b);
    }
    if (fromHistory) {
      const when = document.createElement("span");
      when.className = "badge neutral";
      when.textContent = "Salvata il " + formatDate(entry.at);
      head.append(when);
    }

    // Oggetto di una mail di Scrivi: testo non sanificato, solo textContent.
    let oggetto = null;
    if (entry.oggetto) {
      oggetto = document.createElement("p");
      oggetto.className = "result-oggetto";
      const label = document.createElement("b");
      label.textContent = "Oggetto: ";
      oggetto.append(label, document.createTextNode(String(entry.oggetto)));
    }

    const answer = document.createElement("div");
    answer.className = "answer";
    // HTML prodotto dal server: testo già escapato, solo tag b/i/code/a con link http/https.
    answer.innerHTML = entry.html;
    answer.querySelectorAll("a").forEach((a) => {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    });

    // Suggerimenti di /api/verifica: testo non sanificato, solo textContent (via button()).
    let chips = null;
    if (Array.isArray(entry.suggerimenti) && entry.suggerimenti.length) {
      chips = document.createElement("div");
      chips.className = "chips";
      entry.suggerimenti.forEach((s) =>
        chips.append(
          button(String(s), "chip", () => {
            setMode("verifica");
            el.query.value = String(s);
            submit();
          }),
        ),
      );
    }

    const actions = document.createElement("div");
    actions.className = "result-actions";
    actions.append(
      button("Copia", "ghost small", async (ev) => {
        const target = ev.currentTarget;
        try {
          await navigator.clipboard.writeText(entry.text);
          target.textContent = "Copiato";
          setTimeout(() => (target.textContent = "Copia"), 1500);
        } catch (_) {
          target.textContent = "Non disponibile";
        }
      }),
    );
    if (fromHistory && MODES[entry.mode] && MODES[entry.mode].panel === "query") {
      actions.append(
        button("Ripeti", "ghost small", () => {
          setMode(entry.mode);
          el.query.value = entry.query;
          submit();
        }),
      );
    }

    el.result.append(head);
    if (oggetto) el.result.append(oggetto);
    el.result.append(answer);
    if (chips) el.result.append(chips);
    el.result.append(actions);
  }

  function renderError(message) {
    el.result.hidden = false;
    el.result.replaceChildren();
    const p = document.createElement("p");
    p.className = "error";
    p.textContent = message;
    el.result.append(p);
  }

  // ---------------------------------------------------------------- history ---
  function saveHistory(entry) {
    history = [entry, ...history].slice(0, HISTORY_MAX);
    storage.set(HISTORY_KEY, history);
    renderHistory();
  }

  function renderHistory() {
    el.historyList.replaceChildren();
    el.clearHistory.hidden = history.length === 0;
    el.historyEmpty.hidden = history.length > 0;
    history.forEach((entry) => {
      const li = document.createElement("li");
      const item = document.createElement("button");
      item.type = "button";
      item.className = "history-item";
      const meta = document.createElement("span");
      meta.className = "history-meta";
      const kind = document.createElement("span");
      kind.textContent = MODES[entry.mode] ? MODES[entry.mode].label : "Domanda";
      const when = document.createElement("span");
      when.textContent = formatDate(entry.at);
      meta.append(kind, when);
      const text = document.createElement("span");
      text.className = "history-text";
      text.textContent = entry.query;
      item.append(meta, text);
      item.addEventListener("click", () => {
        renderEntry(entry, { fromHistory: true });
        el.result.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      li.append(item);
      el.historyList.append(li);
    });
  }

  // ---------------------------------------------------------------- actions ---
  function makeEntry(entryMode, query, text, html, extra) {
    return {
      id: Date.now().toString(36),
      mode: entryMode,
      query,
      text,
      html,
      at: new Date().toISOString(),
      ...(extra || {}),
    };
  }

  async function api(path, body) {
    try {
      return await call(path, body, accessCode);
    } catch (err) {
      if (err.status === 401) logout("Il codice di accesso non è più valido. Inseriscilo di nuovo.");
      throw err;
    }
  }

  function scrollToResult() {
    el.result.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function submit() {
    if (busy) return;
    const query = el.query.value.trim();
    if (!query) {
      el.query.focus();
      return;
    }
    const cfg = MODES[mode];
    if (!cfg || cfg.panel !== "query") return;
    const currentMode = mode;
    // Domanda: dati personali mascherati prima dell'invio. Verifica: solo riferimenti normativi, senza IA.
    const m = currentMode === "ask" ? window.LexMask.mask(query) : { masked: query, map: {}, counts: {} };
    const sum = window.LexMask.summary(m.counts);
    el.askMaskInfo.hidden = !sum;
    el.askMaskInfo.textContent = sum;
    setBusy(true);
    const msg = renderLoading(
      query,
      currentMode === "ask" ? "Ricerca su Normattiva in corso…" : "Verifica su Normattiva in corso…",
    );
    const slow = setTimeout(() => {
      msg.textContent = "Ancora un momento: sto consultando le fonti…";
    }, 20000);
    try {
      const data = await api(cfg.path, { [cfg.field]: m.masked });
      const extra = Array.isArray(data.suggerimenti) ? { suggerimenti: data.suggerimenti } : null;
      // Nello storico la versione mascherata; a video i valori originali (unmask solo nel browser).
      const entry = makeEntry(currentMode, m.masked, data.text, data.html, extra);
      saveHistory(entry);
      renderEntry(
        {
          ...entry,
          query: window.LexMask.unmask(entry.query, m.map),
          text: window.LexMask.unmask(entry.text, m.map),
          html: window.LexMask.unmask(entry.html, m.map, { escape: true }),
        },
        { fromHistory: false },
      );
      el.query.value = "";
    } catch (err) {
      if (err.status !== 401) renderError(err.message);
    } finally {
      clearTimeout(slow);
      setBusy(false);
    }
  }

  async function login(code) {
    const submitBtn = el.loginForm.querySelector("button");
    submitBtn.disabled = true;
    el.loginError.hidden = true;
    try {
      await call("/api/accesso", {}, code);
      accessCode = code;
      storage.set(CODE_KEY, code);
      showApp();
    } catch (err) {
      el.loginError.textContent = err.message;
      el.loginError.hidden = false;
    } finally {
      submitBtn.disabled = false;
    }
  }

  function logout(message) {
    accessCode = "";
    storage.remove(CODE_KEY);
    el.result.hidden = true;
    showLogin(message);
  }

  // ----------------------------------------------------------------- events ---
  el.loginForm.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const code = el.code.value.trim();
    if (code) login(code);
  });

  el.form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    submit();
  });

  el.query.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) {
      ev.preventDefault();
      submit();
    }
  });

  el.tabs.forEach((tab) => tab.addEventListener("click", () => setMode(tab.dataset.mode)));

  el.logout.addEventListener("click", () => logout(""));

  el.clearHistory.addEventListener("click", () => {
    history = [];
    storage.remove(HISTORY_KEY);
    renderHistory();
  });

  const panels = window.LexPanels.init({
    api,
    button,
    makeEntry,
    renderEntry,
    renderError,
    renderLoading,
    saveHistory,
    scrollToResult,
    resultEl: el.result,
    isBusy: () => busy,
    setBusy,
    openScrivi(tipoValue, text) {
      setMode("scrivi");
      panels.scrivi.prefill(tipoValue, text);
    },
  });

  setMode("ask");
  if (accessCode) showApp();
  else showLogin("");
})();
