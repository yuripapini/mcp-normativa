"use strict";
// Scheda Pausa: selettore dei giochi, canvas, ciclo di gioco, pausa automatica, fine partita, record e condivisione.
(function (root) {
  const NODE = typeof module === "object" && module.exports;
  const G = NODE ? require("./core.js") : root.LexGames;

  // ---- Funzioni pure (testate in Node)

  function recordKey(gioco) {
    return "lexbot.record." + gioco;
  }

  // Record salvato: numero (0 se assente) oppure null se lo storage non è disponibile.
  function leggiRecord(storage, gioco) {
    try {
      if (!storage) return null;
      const n = parseInt(storage.getItem(recordKey(gioco)), 10);
      return Number.isFinite(n) && n > 0 ? n : 0;
    } catch (e) {
      return null;
    }
  }

  function scriviRecord(storage, gioco, points) {
    try {
      if (!storage) return false;
      storage.setItem(recordKey(gioco), String(Math.round(points)));
      return true;
    } catch (e) {
      return false;
    }
  }

  // Confronto col record precedente: senza storage (prev null) niente record.
  function esitoRecord(prev, points) {
    if (prev === null || prev === undefined) return { record: null, nuovo: false };
    const nuovo = points > prev && points > 0;
    return { record: nuovo ? points : prev, nuovo };
  }

  function viteTesto(lives, max) {
    const m = max || G.LIVES;
    const n = Math.max(0, Math.min(m, lives));
    return "●".repeat(n) + "○".repeat(m - n);
  }

  // Righe "Infrazioni fermate" dal conteggio `viste` del posto di blocco, nell'ordine dei PASSANTI.
  // link = true se esiste una scheda Strada con quell'articolo.
  function infrazioni(viste, articoliStrada) {
    const arts = new Set(articoliStrada || []);
    return G.PASSANTI.filter((p) => viste && viste[p.id] > 0).map((p) => ({
      id: p.id,
      label: p.label,
      volte: viste[p.id],
      articolo: p.articolo || null,
      link: !!(p.articolo && arts.has(p.articolo)),
      battuta: p.battuta || null,
    }));
  }

  function squadraTesto(squadra) {
    const frase = G.squadraFrase(squadra);
    return frase ? "Squadra adottata: " + frase.replace(" e ho adottato ", "") : "";
  }

  // Misure del canvas: altezza CSS min(70% della finestra, larghezza in proporzione), campo logico centrato.
  function layoutCanvas(cw, vh, dpr) {
    const cssH = Math.max(1, Math.round(Math.min(vh * 0.7, (cw * G.H) / G.W)));
    const scale = Math.min(cw / G.W, cssH / G.H);
    return {
      cssH,
      scale,
      offX: (cw - G.W * scale) / 2,
      offY: (cssH - G.H * scale) / 2,
      bw: Math.max(1, Math.round(cw * dpr)),
      bh: Math.max(1, Math.round(cssH * dpr)),
    };
  }

  // Condivisione: share nativo se c'è; WhatsApp se manca o fallisce (non se l'utente annulla).
  // Ritorna una Promise (risolta a "share" | "whatsapp" | "annullata") per i test.
  function condividiCon(nav, apri, text, url) {
    const wa = () => {
      apri(G.whatsappUrl(text, url));
      return "whatsapp";
    };
    if (!nav || typeof nav.share !== "function") return Promise.resolve(wa());
    let p;
    try {
      p = Promise.resolve(nav.share({ text, url }));
    } catch (err) {
      p = Promise.reject(err);
    }
    return p.then(
      () => "share",
      (err) => (err && err.name === "AbortError" ? "annullata" : wa()),
    );
  }

  const helpers = { condividiCon, recordKey, leggiRecord, scriviRecord, esitoRecord, viteTesto, infrazioni, squadraTesto, layoutCanvas };
  if (NODE) {
    module.exports = helpers;
    return;
  }

  // ---- Interfaccia nel browser

  let ui = null;
  let opts = {};
  let gioco = "gomitoli";
  let game = null;
  let stato = "intro"; // intro | play | paused | over
  let visibile = false;
  let raf = 0;
  let last = 0;
  let now = 0;
  let theme = null;
  let lay = null;
  let hudPrec = "";

  function storage() {
    try {
      return root.localStorage;
    } catch (e) {
      return null;
    }
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function button(cls, text, onClick) {
    const b = el("button", cls, text);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }

  function leggiTema() {
    const cs = getComputedStyle(document.documentElement);
    const v = (name, fallback) => cs.getPropertyValue(name).trim() || fallback;
    const dark = !!(root.matchMedia && root.matchMedia("(prefers-color-scheme: dark)").matches);
    theme = {
      dark,
      surface: v("--surface", "#ffffff"),
      surface2: v("--surface-2", "#eef0f4"),
      text: v("--text", "#111827"),
      muted: v("--muted", "#6b7280"),
      border: v("--border", "#e5e7eb"),
      accent: v("--accent", "#2563eb"),
      ok: v("--ok", "#047857"),
      warn: v("--warn", "#b45309"),
      bad: v("--bad", "#b91c1c"),
      font: v("--font", "system-ui, sans-serif"),
    };
  }

  function view() {
    return root.LexGameViews[gioco];
  }

  function nuovaPartita() {
    game = view().create(G.rng((Date.now() ^ Math.floor(Math.random() * 0x7fffffff)) >>> 0));
    now = 0;
    last = 0;
    hudPrec = "";
  }

  function ridimensiona() {
    if (!ui || !visibile) return;
    const cw = ui.canvas.clientWidth || ui.wrap.clientWidth;
    if (!cw) return;
    const vh = (root.visualViewport && root.visualViewport.height) || root.innerHeight;
    lay = layoutCanvas(cw, vh, root.devicePixelRatio || 1);
    ui.canvas.style.height = lay.cssH + "px";
    if (ui.canvas.width !== lay.bw) ui.canvas.width = lay.bw;
    if (ui.canvas.height !== lay.bh) ui.canvas.height = lay.bh;
    disegna();
  }

  function disegna() {
    if (!ui || !lay || !game || !theme) return;
    const ctx = ui.ctx;
    const dpr = lay.bw / (ui.canvas.clientWidth || lay.bw);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, ui.canvas.width, ui.canvas.height);
    ctx.setTransform(dpr * lay.scale, 0, 0, dpr * lay.scale, dpr * lay.offX, dpr * lay.offY);
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, G.W, G.H);
    ctx.clip();
    game.draw(ctx, theme, lay.scale);
    ctx.restore();
  }

  function aggiornaHud() {
    if (!game) return;
    const s = game.score;
    const chiave = s.points + "|" + s.mult + "|" + s.lives;
    if (chiave === hudPrec) return;
    hudPrec = chiave;
    ui.score.textContent = G.formatPoints(s.points);
    ui.mult.textContent = s.mult > 1 ? "x" + s.mult : "";
    ui.lives.textContent = viteTesto(s.lives);
    ui.lives.setAttribute("aria-label", "Vite: " + Math.max(0, s.lives));
    if (ui.squadra) {
      const testo = gioco === "blocco" && game.state ? squadraTesto(game.state.squadra) : "";
      ui.squadra.textContent = testo;
      ui.squadra.hidden = !testo;
    }
  }

  function mostraOverlay(nodi) {
    const ov = ui.overlay;
    while (ov.firstChild) ov.removeChild(ov.firstChild);
    for (const n of nodi) ov.appendChild(n);
    ov.scrollTop = 0;
  }

  function fermaCiclo() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  }

  function avviaCiclo() {
    fermaCiclo();
    last = 0;
    raf = requestAnimationFrame(frame);
  }

  function frame(ts) {
    raf = 0;
    if (stato !== "play" || !visibile) return;
    const dt = last ? Math.max(0, Math.min(0.05, (ts - last) / 1000)) : 0;
    last = ts;
    now += dt;
    game.update(dt, now);
    disegna();
    aggiornaHud();
    if (game.score.over) {
      finePartita();
      return;
    }
    raf = requestAnimationFrame(frame);
  }

  function intro() {
    fermaCiclo();
    stato = "intro";
    nuovaPartita();
    const v = view();
    const nodi = [el("h2", "", v.titolo), el("p", "", v.intro)];
    const rec = leggiRecord(storage(), gioco);
    if (rec) nodi.push(el("p", "game-record", "Record: " + G.formatPoints(rec)));
    nodi.push(button("btn primary", "Gioca", gioca));
    mostraOverlay(nodi);
    aggiornaHud();
    disegna();
  }

  function gioca() {
    if (stato === "over" || !game) nuovaPartita();
    stato = "play";
    mostraOverlay([]);
    aggiornaHud();
    avviaCiclo();
  }

  function pausa() {
    if (stato !== "play") return;
    fermaCiclo();
    stato = "paused";
    mostraOverlay([el("h2", "", "In pausa"), button("btn primary", "Riprendi", riprendi), button("btn ghost", "Ricomincia", intro)]);
  }

  function riprendi() {
    if (stato !== "paused") return;
    stato = "play";
    mostraOverlay([]);
    avviaCiclo();
  }

  function finePartita() {
    fermaCiclo();
    stato = "over";
    const points = game.score.points;
    const st = storage();
    const esito = esitoRecord(leggiRecord(st, gioco), points);
    if (esito.nuovo) scriviRecord(st, gioco, points);
    const sum = game.summary();
    const nodi = [el("h2", "", "Partita finita"), el("p", "game-punti", G.formatPoints(points) + (Math.round(points) === 1 ? " punto" : " punti"))];
    if (esito.nuovo) nodi.push(el("p", "game-nuovo", "Nuovo record!"));
    else if (esito.record) nodi.push(el("p", "game-record", "Record: " + G.formatPoints(esito.record)));
    // Pulsanti subito dopo punteggio e record: visibili senza scorrere il riepilogo.
    const azioni = el("div", "game-actions");
    azioni.appendChild(button("btn primary", "Rigioca", gioca));
    azioni.appendChild(button("btn ghost", "Condividi", () => condividi(points, sum.squadra)));
    nodi.push(azioni);
    for (const r of sum.righe || []) nodi.push(el("p", "", r));
    if (sum.viste) {
      const articoli = (root.LEXBOT_SCHEDE || []).map((s) => s.articolo);
      const righe = infrazioni(sum.viste, articoli);
      if (righe.length) {
        nodi.push(el("h3", "", "Infrazioni fermate"));
        const ul = el("ul", "game-infrazioni");
        for (const r of righe) {
          const li = el("li");
          li.appendChild(el("span", "", r.label + (r.volte > 1 ? " (" + r.volte + ")" : "")));
          if (r.articolo && r.link) {
            const art = r.articolo;
            li.appendChild(button("btn chip", "art. " + art + " C.d.S.", () => opts.openStrada && opts.openStrada(art)));
          } else if (r.articolo) {
            li.appendChild(el("span", "muted", "art. " + r.articolo + " C.d.S."));
          }
          if (r.battuta) li.appendChild(el("span", "muted", r.battuta));
          ul.appendChild(li);
        }
        nodi.push(ul);
      }
    }
    const sq = squadraTesto(sum.squadra);
    if (sq) nodi.push(el("p", "", sq));
    mostraOverlay(nodi);
  }

  function condividi(points, squadra) {
    const text = G.shareText(gioco, points, squadra);
    const url = location.origin + location.pathname;
    condividiCon(root.navigator, (u) => root.open(u, "_blank", "noopener"), text, url);
  }

  function scegliGioco(id) {
    if (!root.LexGameViews[id]) return;
    gioco = id;
    for (const b of ui.segs) {
      const on = b.dataset.gioco === id;
      b.classList.toggle("active", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    }
    intro();
  }

  function coordinate(ev) {
    const r = ui.canvas.getBoundingClientRect();
    return { x: (ev.clientX - r.left - lay.offX) / lay.scale, y: (ev.clientY - r.top - lay.offY) / lay.scale };
  }

  function onDown(ev) {
    if (stato !== "play" || !lay) return;
    ev.preventDefault();
    try {
      ui.canvas.setPointerCapture(ev.pointerId);
    } catch (e) {
      // cattura non disponibile: si prosegue senza
    }
    const c = coordinate(ev);
    game.pointerDown(c.x, c.y, now);
  }

  function onMove(ev) {
    if (stato !== "play" || !lay) return;
    const c = coordinate(ev);
    game.pointerMove(c.x, c.y);
  }

  function onUp() {
    if (game) game.pointerUp();
  }

  function init(o) {
    if (ui) return;
    opts = o || {};
    const panel = document.getElementById("pausa-panel");
    if (!panel) return;
    const canvas = document.getElementById("game-canvas");
    ui = {
      panel,
      canvas,
      ctx: canvas.getContext("2d"),
      wrap: canvas.parentElement,
      overlay: document.getElementById("game-overlay"),
      score: document.getElementById("game-score"),
      mult: document.getElementById("game-mult"),
      lives: document.getElementById("game-lives"),
      squadra: document.getElementById("game-squadra"),
      segs: Array.from(panel.querySelectorAll("[data-gioco]")),
    };
    ui.lives.setAttribute("role", "img");
    canvas.style.touchAction = "none";
    leggiTema();
    for (const b of ui.segs) b.addEventListener("click", () => scegliGioco(b.dataset.gioco));
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointercancel", onUp);
    root.addEventListener("resize", ridimensiona);
    if (root.visualViewport) root.visualViewport.addEventListener("resize", ridimensiona);
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) pausa();
    });
    if (root.matchMedia) {
      const mq = root.matchMedia("(prefers-color-scheme: dark)");
      const cambio = () => {
        leggiTema();
        disegna();
      };
      if (mq.addEventListener) mq.addEventListener("change", cambio);
      else if (mq.addListener) mq.addListener(cambio);
    }
    const attivo = ui.segs.find((b) => b.classList.contains("active"));
    if (attivo && root.LexGameViews[attivo.dataset.gioco]) gioco = attivo.dataset.gioco;
    intro();
  }

  function show() {
    if (!ui) return;
    visibile = true;
    leggiTema();
    ridimensiona();
  }

  function hide() {
    if (!ui) return;
    pausa();
    visibile = false;
    fermaCiclo();
  }

  root.LexPausa = { init, show, hide };
})(typeof window !== "undefined" ? window : globalThis);
