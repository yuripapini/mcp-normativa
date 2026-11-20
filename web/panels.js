"use strict";
// Pannelli Strada, Indagini e Scrivi. Ricevono da app.js un contesto con le funzioni condivise.
// Testi dal server non sanificati (oggetto, testo): solo textContent. innerHTML solo per i campi html.

(function () {
  const $ = (id) => document.getElementById(id);

  function norm(s) {
    return String(s || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "");
  }

  function list(title, items) {
    const box = document.createElement("div");
    const h = document.createElement("h3");
    h.textContent = title;
    const ul = document.createElement("ul");
    (items || []).forEach((t) => {
      const li = document.createElement("li");
      li.textContent = t;
      ul.append(li);
    });
    box.append(h, ul);
    return box;
  }

  // Unisce le maschere di istruzioni e destinatario in un'unica mappa coerente:
  // stesso valore -> stesso segnaposto; segnaposto del destinatario rinumerati se già usati.
  function mergeMasks(main, extra) {
    const map = Object.assign({}, main.map);
    const tokenByValue = {};
    const next = {};
    Object.keys(map).forEach((token) => {
      const m = /^\[([A-Z]+)_(\d+)\]$/.exec(token);
      if (!m) return;
      tokenByValue[m[1] + ":" + map[token]] = token;
      next[m[1]] = Math.max(next[m[1]] || 0, Number(m[2]));
    });
    const rename = {};
    Object.keys(extra.map).forEach((token) => {
      const m = /^\[([A-Z]+)_(\d+)\]$/.exec(token);
      if (!m) return;
      const key = m[1] + ":" + extra.map[token];
      if (!tokenByValue[key]) {
        next[m[1]] = (next[m[1]] || 0) + 1;
        const fresh = "[" + m[1] + "_" + next[m[1]] + "]";
        tokenByValue[key] = fresh;
        map[fresh] = extra.map[token];
      }
      rename[token] = tokenByValue[key];
    });
    const masked = extra.masked.replace(/\[[A-Z]+_\d+\]/g, (t) => rename[t] || t);
    const counts = {};
    Object.keys(map).forEach((token) => {
      const m = /^\[([A-Z]+)_\d+\]$/.exec(token);
      if (m) counts[m[1]] = (counts[m[1]] || 0) + 1;
    });
    return { extraMasked: masked, map, counts };
  }

  // Sigla breve dell'atto per il badge delle schede Indagini.
  function sigla(lawId) {
    if (lawId === "d.p.r. 447/1988") return "c.p.p.";
    if (lawId === "r.d. 1398/1930") return "c.p.";
    return lawId;
  }

  // Pannello a schede generico (Strada, Indagini).
  // cfg = { schede, filter, list, detail, grouped, scriviDefault, mode }
  function initSchede(ctx, cfg) {
    const schede = Array.isArray(cfg.schede) ? cfg.schede : [];
    const filter = $(cfg.filter);
    const listEl = $(cfg.list);
    const detail = $(cfg.detail);

    function matches(s, q) {
      if (!q) return true;
      const extra = cfg.grouped ? [s.gruppo, s.law_id] : [];
      const hay = norm([s.titolo, s.articolo, "art " + s.articolo].concat(extra, s.sinonimi || []).join(" "));
      return norm(q)
        .split(/\s+/)
        .every((w) => hay.includes(w));
    }

    function item(s) {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.className = "strada-item";
      const t = document.createElement("span");
      t.className = "strada-title";
      t.textContent = s.titolo;
      const a = document.createElement("span");
      a.className = "badge neutral";
      a.textContent = "art. " + s.articolo + (cfg.grouped ? " " + sigla(s.law_id) : "");
      b.append(t, a);
      b.addEventListener("click", () => open(s));
      li.append(b);
      return li;
    }

    function renderList() {
      const q = filter.value.trim();
      listEl.replaceChildren();
      const found = schede.filter((s) => matches(s, q));
      if (cfg.grouped) {
        const gruppi = [];
        const byGruppo = {};
        found.forEach((s) => {
          if (!byGruppo[s.gruppo]) {
            byGruppo[s.gruppo] = [];
            gruppi.push(s.gruppo);
          }
          byGruppo[s.gruppo].push(s);
        });
        gruppi.forEach((g) => {
          const h = document.createElement("h3");
          h.className = "gruppo-title";
          h.textContent = g;
          const ul = document.createElement("ul");
          ul.className = "strada-list";
          byGruppo[g].forEach((s) => ul.append(item(s)));
          listEl.append(h, ul);
        });
        if (!found.length) {
          const p = document.createElement("p");
          p.className = "muted small-text";
          p.textContent = "Nessuna scheda: prova la scheda Domanda.";
          listEl.append(p);
        }
        return;
      }
      found.forEach((s) => listEl.append(item(s)));
      if (!found.length) {
        const li = document.createElement("li");
        li.className = "muted small-text";
        li.textContent = "Nessuna scheda: prova la scheda Domanda.";
        listEl.append(li);
      }
    }

    async function fetchArticle(s, path, label) {
      if (ctx.isBusy()) return;
      ctx.setBusy(true);
      const query = s.titolo + " - art. " + s.articolo + " " + s.law_id + (label ? " (" + label + ")" : "");
      ctx.renderLoading(query, label ? "Riassunto in corso…" : "Testo vigente da Normattiva…");
      ctx.scrollToResult();
      try {
        const data = await ctx.api(path, { law_id: s.law_id, article: s.articolo });
        const entry = ctx.makeEntry(cfg.mode, query, data.text, data.html);
        ctx.saveHistory(entry);
        ctx.renderEntry(entry, { fromHistory: false });
      } catch (err) {
        if (err.status !== 401) ctx.renderError(err.message);
      } finally {
        ctx.setBusy(false);
      }
    }

    function open(s) {
      detail.hidden = false;
      detail.replaceChildren();
      const h = document.createElement("h2");
      h.textContent = s.titolo;
      const ref = document.createElement("p");
      ref.className = "muted";
      // Indagini: sigla leggibile (c.p., c.p.p.) seguita dall'atto formale; Strada invariata.
      const sig = cfg.grouped ? sigla(s.law_id) : s.law_id;
      ref.textContent = "Art. " + s.articolo + " " + (sig !== s.law_id ? sig + " (" + s.law_id + ")" : s.law_id);
      const actions = document.createElement("div");
      actions.className = "scheda-actions";
      let note = null;
      if (s.fonte === "link") {
        const a = document.createElement("a");
        a.className = "btn primary small";
        a.href = s.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = "Apri su Normattiva";
        actions.append(a);
        note = document.createElement("p");
        note.className = "nota-link";
        note.textContent = "Testo del codice penale non disponibile tramite API: si apre il sito ufficiale.";
      } else {
        actions.append(
          // Senza IA.
          ctx.button("Testo vigente", "primary small", () => fetchArticle(s, "/api/articolo", "")),
          // Con IA: solo su clic esplicito.
          ctx.button("Riassumi", "ghost small", () => fetchArticle(s, "/api/riassumi", "riassunto")),
        );
      }
      if (cfg.scriviDefault) {
        actions.append(
          ctx.button("Prepara verbale", "ghost small", () =>
            ctx.openScrivi(
              cfg.scriviDefault,
              "Violazione dell'art. " + s.articolo + " del " + s.law_id + " (" + s.titolo + ").\nFatti: ",
            ),
          ),
        );
      } else if (s.scrivi) {
        actions.append(
          ctx.button("Prepara atto", "ghost small", () =>
            ctx.openScrivi(s.scrivi, "Riferimento: art. " + s.articolo + " " + sig + " (" + s.titolo + ").\nFatti: "),
          ),
        );
      }
      actions.querySelectorAll("button").forEach((b) => (b.disabled = ctx.isBusy()));
      detail.append(h, ref, list("Cosa controllare", s.controlli), list("Cosa annotare", s.annotare));
      if (note) detail.append(note);
      detail.append(actions);
      detail.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    filter.addEventListener("input", renderList);
    renderList();
  }

  function initScrivi(ctx) {
    const form = $("scrivi-form");
    const tipo = $("scrivi-tipo");
    const destWrap = $("scrivi-dest-wrap");
    const dest = $("scrivi-dest");
    const istr = $("scrivi-istruzioni");
    const info = $("scrivi-mask-info");
    const avviso = $("scrivi-pg-avviso");
    const guardBox = $("scrivi-guard");
    const hint = $("scrivi-hint");
    // Stato della pagina (solo tipi PG): segnaposto -> valore e valori segnalati come falsi allarmi.
    let guardMap = {};
    let guardIgnore = [];

    const isPg = () => tipo.selectedOptions[0] && tipo.selectedOptions[0].dataset.pg === "1";

    function resetGuard() {
      guardMap = {};
      guardIgnore = [];
      guardBox.hidden = true;
      guardBox.replaceChildren();
    }

    function syncTipo() {
      destWrap.hidden = !tipo.value.startsWith("mail_");
      avviso.hidden = !isPg();
      // Nei tipi PG l'invio viene bloccato, non mascherato in silenzio: il suggerimento non vale.
      if (hint) hint.hidden = isPg();
      // La mappa resta: il campo può contenere già i segnaposto. Si azzera solo svuotando il campo.
      guardBox.hidden = true;
      guardBox.replaceChildren();
    }

    function renderGuard(found) {
      guardBox.replaceChildren();
      if (!found.length) {
        guardBox.hidden = true;
        return;
      }
      guardBox.hidden = false;
      const h = document.createElement("h3");
      h.textContent = "Possibili dati personali: sostituiscili o segnala i falsi allarmi";
      h.tabIndex = -1;
      guardBox.append(h);
      // Il pulsante toccato viene ricreato: il focus va al titolo del riquadro o, se chiuso, a "Genera".
      const rescan = () => {
        renderGuard(window.LexGuard.scan(istr.value, { ignore: guardIgnore }));
        const target = guardBox.hidden ? $("scrivi-submit") : guardBox.querySelector("h3");
        if (target) target.focus({ preventScroll: true });
      };
      found.forEach((f) => {
        const row = document.createElement("div");
        row.className = "guard-row";
        const what = document.createElement("div");
        const label = window.LexGuard.LABELS[f.kind] || f.kind;
        what.append(document.createTextNode(label + ": "));
        const mk = document.createElement("mark");
        mk.textContent = f.value;
        what.append(mk);
        const actions = document.createElement("div");
        actions.className = "guard-actions";
        actions.append(
          ctx.button("Sostituisci", "primary small", () => {
            istr.value = window.LexGuard.replace(istr.value, f, guardMap).text;
            rescan();
          }),
          ctx.button("Non è un dato personale", "ghost small", () => {
            guardIgnore.push(f.value);
            rescan();
          }),
        );
        row.append(what, actions);
        guardBox.append(row);
      });
      const all = document.createElement("div");
      all.className = "guard-actions";
      all.append(
        ctx.button("Sostituisci tutti", "primary small", () => {
          // Ciclo protetto: si ferma se il testo non cambia e comunque dopo 200 giri.
          for (let i = 0; i < 200; i++) {
            const first = window.LexGuard.scan(istr.value, { ignore: guardIgnore })[0];
            if (!first) break;
            const next = window.LexGuard.replace(istr.value, first, guardMap).text;
            if (next === istr.value) break;
            istr.value = next;
          }
          rescan();
        }),
      );
      guardBox.append(all);
    }

    function copyButton(label, getText) {
      return ctx.button(label, "ghost small", async (ev) => {
        const target = ev.currentTarget;
        try {
          await navigator.clipboard.writeText(getText());
          target.textContent = "Copiato";
          setTimeout(() => (target.textContent = label), 1500);
        } catch (_) {
          target.textContent = "Non disponibile";
        }
      });
    }

    function block(title, text, html) {
      const box = document.createElement("div");
      box.className = "scritto-block";
      const head = document.createElement("div");
      head.className = "scritto-head";
      const h = document.createElement("h3");
      h.textContent = title;
      head.append(h, copyButton("Copia", () => text));
      const body = document.createElement("div");
      body.className = "answer";
      // html: già sanificato dal server (valori rimessi con escape); altrimenti solo testo.
      if (html !== undefined) body.innerHTML = html;
      else body.textContent = text;
      body.querySelectorAll("a").forEach((a) => {
        a.target = "_blank";
        a.rel = "noopener noreferrer";
      });
      box.append(head, body);
      return box;
    }

    function renderScritto(label, oggetto, testo, html) {
      const result = ctx.resultEl;
      result.hidden = false;
      result.replaceChildren();
      const head = document.createElement("div");
      head.className = "result-head";
      const k = document.createElement("span");
      k.className = "badge neutral";
      k.textContent = label;
      head.append(k);
      result.append(head);
      if (oggetto) result.append(block("Oggetto", oggetto));
      result.append(block("Testo", testo, html));
      const actions = document.createElement("div");
      actions.className = "result-actions";
      actions.append(copyButton("Copia tutto", () => (oggetto ? "Oggetto: " + oggetto + "\n\n" : "") + testo));
      result.append(actions);
    }

    async function submit() {
      if (ctx.isBusy()) return;
      const text = istr.value.trim();
      if (!text) {
        istr.focus();
        return;
      }
      const label = tipo.options[tipo.selectedIndex].text;
      const isMail = tipo.value.startsWith("mail_");
      let m;
      let merged;
      let map;
      if (isPg()) {
        // Tipi PG: blocco se ci sono possibili dati personali; i residui di LexMask (falsi allarmi
        // confermati dall'operatore) usano la stessa mappa, così la numerazione non collide.
        const prep = window.LexGuard.prepare(text, guardMap, guardIgnore);
        if (prep.found.length) {
          info.hidden = true;
          renderGuard(prep.found);
          guardBox.scrollIntoView({ block: "nearest" });
          return;
        }
        guardBox.hidden = true;
        m = { masked: prep.text };
        // Per il ripristino solo i segnaposto davvero inviati: un segnaposto inventato dal modello non
        // deve ricevere un valore rimasto in mappa da una richiesta precedente.
        map = {};
        Object.keys(guardMap).forEach((k) => {
          if (prep.text.includes(k)) map[k] = guardMap[k];
        });
        const n = Object.keys(map).length;
        info.hidden = !n;
        info.textContent = n ? "Sostituiti sul dispositivo: " + n : "";
      } else {
        m = window.LexMask.mask(text);
        const d = window.LexMask.mask(isMail ? dest.value.trim() : "");
        merged = mergeMasks(m, d);
        map = merged.map;
        const sum = window.LexMask.summary(merged.counts);
        info.hidden = !sum;
        info.textContent = sum;
      }
      ctx.setBusy(true);
      ctx.renderLoading(label, "Scrittura in corso (10-40 secondi)…");
      ctx.scrollToResult();
      try {
        const data = await ctx.api("/api/scrivi", {
          tipo: tipo.value,
          destinatario: merged ? merged.extraMasked : "",
          istruzioni: m.masked,
        });
        const oggetto = String(data.oggetto || "");
        const testo = String(data.testo || "");
        // Nello storico solo la versione mascherata.
        const masked = (oggetto ? "Oggetto: " + oggetto + "\n\n" : "") + testo;
        ctx.saveHistory(
          ctx.makeEntry("scrivi", label + ": " + m.masked, masked, data.html, oggetto ? { oggetto } : null),
        );
        renderScritto(
          label,
          window.LexMask.unmask(oggetto, map),
          window.LexMask.unmask(testo, map),
          window.LexMask.unmask(data.html, map, { escape: true }),
        );
      } catch (err) {
        if (err.status !== 401) ctx.renderError(err.message);
      } finally {
        ctx.setBusy(false);
      }
    }

    istr.addEventListener("input", () => {
      if (!istr.value) resetGuard();
    });
    tipo.addEventListener("change", syncTipo);
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      submit();
    });
    syncTipo();

    return {
      prefill(tipoValue, text) {
        tipo.value = tipoValue;
        syncTipo();
        resetGuard();
        istr.value = text;
        istr.focus();
        istr.setSelectionRange(text.length, text.length);
      },
    };
  }

  window.LexPanels = {
    init(ctx) {
      initSchede(ctx, {
        schede: window.LEXBOT_SCHEDE,
        filter: "strada-filter",
        list: "strada-list",
        detail: "strada-detail",
        grouped: false,
        scriviDefault: "verbale_violazione_cds",
        mode: "strada",
      });
      initSchede(ctx, {
        schede: window.LEXBOT_INDAGINI,
        filter: "indagini-filter",
        list: "indagini-list",
        detail: "indagini-detail",
        grouped: true,
        mode: "indagini",
      });
      return { scrivi: initScrivi(ctx) };
    },
  };
})();
