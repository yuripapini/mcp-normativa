"use strict";
// Pannelli Strada e Scrivi. Ricevono da app.js un contesto con le funzioni condivise.
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

  function initStrada(ctx) {
    const schede = Array.isArray(window.LEXBOT_SCHEDE) ? window.LEXBOT_SCHEDE : [];
    const filter = $("strada-filter");
    const listEl = $("strada-list");
    const detail = $("strada-detail");

    function matches(s, q) {
      if (!q) return true;
      const hay = norm([s.titolo, s.articolo, "art " + s.articolo].concat(s.sinonimi || []).join(" "));
      return norm(q)
        .split(/\s+/)
        .every((w) => hay.includes(w));
    }

    function renderList() {
      const q = filter.value.trim();
      listEl.replaceChildren();
      schede
        .filter((s) => matches(s, q))
        .forEach((s) => {
          const li = document.createElement("li");
          const b = document.createElement("button");
          b.type = "button";
          b.className = "strada-item";
          const t = document.createElement("span");
          t.className = "strada-title";
          t.textContent = s.titolo;
          const a = document.createElement("span");
          a.className = "badge neutral";
          a.textContent = "art. " + s.articolo;
          b.append(t, a);
          b.addEventListener("click", () => open(s));
          li.append(b);
          listEl.append(li);
        });
      if (!listEl.children.length) {
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
        const entry = ctx.makeEntry("strada", query, data.text, data.html);
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
      ref.textContent = "Art. " + s.articolo + " " + s.law_id;
      const actions = document.createElement("div");
      actions.className = "scheda-actions";
      actions.append(
        // Senza IA.
        ctx.button("Testo vigente", "primary small", () => fetchArticle(s, "/api/articolo", "")),
        // Con IA: solo su clic esplicito.
        ctx.button("Riassumi", "ghost small", () => fetchArticle(s, "/api/riassumi", "riassunto")),
        ctx.button("Prepara verbale", "ghost small", () =>
          ctx.openScrivi(
            "verbale_violazione_cds",
            "Violazione dell'art. " + s.articolo + " del " + s.law_id + " (" + s.titolo + ").\nFatti: ",
          ),
        ),
      );
      actions.querySelectorAll("button").forEach((b) => (b.disabled = ctx.isBusy()));
      detail.append(h, ref, list("Cosa controllare", s.controlli), list("Cosa annotare", s.annotare), actions);
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

    function syncTipo() {
      destWrap.hidden = !tipo.value.startsWith("mail_");
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
      const m = window.LexMask.mask(text);
      const d = window.LexMask.mask(isMail ? dest.value.trim() : "");
      const merged = mergeMasks(m, d);
      const map = merged.map;
      const sum = window.LexMask.summary(merged.counts);
      info.hidden = !sum;
      info.textContent = sum;
      ctx.setBusy(true);
      ctx.renderLoading(label, "Scrittura in corso (10-40 secondi)…");
      ctx.scrollToResult();
      try {
        const data = await ctx.api("/api/scrivi", {
          tipo: tipo.value,
          destinatario: merged.extraMasked,
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
        istr.value = text;
        istr.focus();
        istr.setSelectionRange(text.length, text.length);
      },
    };
  }

  window.LexPanels = {
    init(ctx) {
      initStrada(ctx);
      return { scrivi: initScrivi(ctx) };
    },
  };
})();
