"use strict";
// Mascheramento dei dati personali nel browser prima dell'invio al server.
// La mappa segnaposto -> valore resta in memoria nella pagina: non viene inviata né salvata.

(function (root) {
  const digits = (s) => s.replace(/\D/g, "").length;

  // Ogni regola ha il gruppo 1 = prefisso di contesto (non mascherato, reinserito) e il gruppo 2 = valore.
  // Niente lookbehind (non supportato da Safari < 16.4): il contesto è un gruppo catturato.
  const CC = String.raw`(?:(?:\+|00)39[\s.-]?)?`;
  const END = String.raw`(?![\w/:])`;
  const PRE = String.raw`(^|[^\w+/])`;

  const isDate = (m) =>
    /^(0[1-9]|[12]\d|3[01])[\s.-](0[1-9]|1[0-2])[\s.-](?:19|20)?\d{2}$/.test(m);
  const phoneOk = (m) => {
    if (isDate(m)) return false;
    const n = digits(m.replace(/^(\+|00)39/, ""));
    return n >= 8 && n <= 11;
  };

  // Ordine importante: prima i formati più lunghi e specifici.
  const RULES = [
    {
      kind: "EMAIL",
      re: /()\b([A-Z0-9._%+-]{1,64}@[A-Z0-9-]{1,63}(?:\.[A-Z0-9-]{1,63}){0,10}\.[A-Z]{2,24})\b/gi,
    },
    { kind: "IBAN", re: /()\b(IT\s?\d{2}\s?[A-Z](?:\s?[0-9A-Z]){22})\b/gi },
    {
      kind: "CF",
      re: /()\b([A-Z]{6}[0-9LMNPQRSTUV]{2}[A-EHLMPRST][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z])\b/gi,
    },
    // Targhe: senza spazi in qualunque maiuscolo/minuscolo; con spazi solo in maiuscolo
    // (evita "il 186 bi", "da 12345" e simili).
    { kind: "TARGA", re: /()\b([A-Za-z]{2}\d{3}[A-Za-z]{2})\b/g },
    { kind: "TARGA", re: /()\b([A-Z]{2} \d{3} [A-Z]{2})\b/g },
    { kind: "TARGA", re: /()\b([A-Za-z]{2}\d{5})\b/g },
    { kind: "TARGA", re: /()\b([A-Z]{2} \d{5})\b/g },
    // Fisso con barra dopo il prefisso ("06/12345678"); almeno 6 cifre dopo la barra: le date no.
    { kind: "TEL", re: new RegExp(PRE + "(" + CC + String.raw`0\d{1,3}\/\d{6,8})` + END, "g") },
    // Fisso con prefisso tra parentesi: "(06) 12345678".
    { kind: "TEL", re: new RegExp(PRE + "(" + CC + String.raw`\(0\d{1,3}\)[\s.-]?\d{6,8})` + END, "g") },
    {
      kind: "TEL",
      re: new RegExp(
        PRE + "(" + CC + String.raw`(?:3\d{2}|0\d{1,3})(?:[\s.-]?\d{2,4}){1,3})` + END,
        "g",
      ),
      valid: phoneOk,
    },
  ];

  const LABELS = {
    TARGA: ["targa", "targhe"],
    CF: ["codice fiscale", "codici fiscali"],
    IBAN: ["IBAN", "IBAN"],
    EMAIL: ["email", "email"],
    TEL: ["telefono", "telefoni"],
  };

  function mask(text) {
    const map = {};
    const byValue = {};
    const counts = {};
    let out = String(text || "");
    for (const rule of RULES) {
      out = out.replace(rule.re, (whole, pre, match) => {
        if (rule.valid && !rule.valid(match)) return whole;
        const key = rule.kind + ":" + match.replace(/[\s.-]+/g, "").toUpperCase();
        if (!byValue[key]) {
          counts[rule.kind] = (counts[rule.kind] || 0) + 1;
          const token = "[" + rule.kind + "_" + counts[rule.kind] + "]";
          byValue[key] = token;
          map[token] = match;
        }
        return pre + byValue[key];
      });
    }
    return { masked: out, map, counts };
  }

  // Individua i dati senza sostituirli: [{ kind, value, start, end }] ordinati per start.
  // Usa le stesse RULES di mask(); start/end escludono il prefisso di contesto (gruppo 1).
  // Sovrapposizioni: vince la regola più in alto nell'elenco (come in mask()).
  function find(text) {
    const src = String(text || "");
    const found = [];
    for (const rule of RULES) {
      for (const m of src.matchAll(rule.re)) {
        const value = m[2];
        if (rule.valid && !rule.valid(value)) continue;
        const start = m.index + m[1].length;
        const end = start + value.length;
        if (found.some((f) => start < f.end && end > f.start)) continue;
        found.push({ kind: rule.kind, value, start, end });
      }
    }
    return found.sort((a, b) => a.start - b.start);
  }

  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // Tollerante ai segnaposto alterati dall'LLM: "[targa_1]", "[ TARGA_1 ]", "[TARGA 1]", "\[TARGA\_1\]".
  const TOKEN_RE = /\\?\[\s*([A-Za-z]+)[\s\\]*_?[\s\\]*(\d+)\s*\\?\]/g;

  function unmask(text, map, options) {
    const escape = Boolean(options && options.escape);
    const m = map || {};
    return String(text || "").replace(TOKEN_RE, (whole, kind, n) => {
      const key = "[" + kind.toUpperCase() + "_" + n + "]";
      if (!Object.prototype.hasOwnProperty.call(m, key)) return whole;
      return escape ? escapeHtml(m[key]) : m[key];
    });
  }

  function summary(counts) {
    const parts = Object.keys(LABELS)
      .filter((k) => counts && counts[k])
      .map((k) => counts[k] + " " + LABELS[k][counts[k] === 1 ? 0 : 1]);
    return parts.length ? "Mascherati: " + parts.join(", ") : "";
  }

  const api = { mask, unmask, summary, find };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LexMask = api;
})(typeof window !== "undefined" ? window : globalThis);
