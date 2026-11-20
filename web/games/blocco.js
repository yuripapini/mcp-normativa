"use strict";
// Gioco "Posto di blocco": si toccano i passanti irregolari, si lasciano passare i regolari, si adottano gli animali.
(function (root) {
  const NODE = typeof module === "object" && module.exports;
  const G = NODE ? require("./core.js") : root.LexGames;
  const C = NODE ? require("./cat.js") : root.LexGameViews.gomitoli;
  const { rrect, label, drawFx, drawFlash, drawCat, drawYarn } = C;
  const W = G.W;
  const H = G.H;
  const PW = G.PASS_W;
  const PH = G.PASS_H;
  const ROAD_TOP = G.LANE_Y[0] - 50;
  const ROAD_BOTTOM = G.LANE_Y[1] + 50;
  const MID = (G.LANE_Y[0] + G.LANE_Y[1]) / 2;
  const LABEL_S = 20; // etichette di aiuto solo nei primi 20 secondi
  const SQUADRA_MAX = 10;
  const ETICHETTA_W = 100;
  const PALETTA = { x: W - 40, y: 62, r: 24 };
  const RED = "#d92d20";
  const SKIN = "#f2c49b";
  const HAIR = "#4a3426";
  const DARK = "#1f2937";
  const GLASS = "#d6ecff";
  const HELMET = "#facc15";
  const DOG = "#a86b32";
  const DOG_DARK = "#6e4420";
  const DUCK = "#fcd34d";
  const BEAK = "#f97316";
  const CAR_COLORS = ["accent", "#0d9488", "#7c3aed", "#ea580c"];

  // Le etichette di aiuto restano solo all'inizio della partita.
  function labelVisibile(t) {
    return t < LABEL_S;
  }

  // Etichetta di aiuto spezzata a parole su righe larghe al massimo maxW (misura passata dal chiamante).
  function righeEtichetta(testo, misura, maxW) {
    const righe = [];
    for (const parola of testo.split(" ")) {
      const ultima = righe[righe.length - 1];
      if (ultima !== undefined && misura(ultima + " " + parola) <= maxW) righe[righe.length - 1] = ultima + " " + parola;
      else righe.push(parola);
    }
    return righe;
  }

  // Icone della squadra in fondo al campo: al massimo `max` icone, poi un contatore "+N".
  function squadraIcone(lista, max) {
    const m = max || SQUADRA_MAX;
    return { icone: lista.slice(0, m), extra: Math.max(0, lista.length - m) };
  }

  // ---- figure
  function wheel(ctx, x, y, r) {
    ctx.fillStyle = DARK;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#6b7280";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.fillStyle = "#9ca3af";
    ctx.beginPath();
    ctx.arc(x, y, r * 0.38, 0, Math.PI * 2);
    ctx.fill();
  }

  function stroke(ctx, color, width, pts) {
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(pts[0], pts[1]);
    for (let i = 2; i < pts.length; i += 2) ctx.lineTo(pts[i], pts[i + 1]);
    ctx.stroke();
  }

  function circle(ctx, color, x, y, r) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  function head(ctx, x, y, r, casco) {
    circle(ctx, SKIN, x, y, r);
    circle(ctx, DARK, x + r * 0.45, y - r * 0.1, r * 0.16);
    if (casco) {
      ctx.fillStyle = HELMET;
      ctx.beginPath();
      ctx.arc(x, y - 1, r + 2.5, Math.PI * 0.95, Math.PI * 2.05);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = DARK;
      rrect(ctx, x - r - 2.5, y - 1.5, r * 2 + 5, 3, 1.5);
      ctx.fill();
    } else {
      ctx.fillStyle = HAIR;
      ctx.beginPath();
      ctx.arc(x - 1, y - 1, r + 0.5, Math.PI * 1.0, Math.PI * 1.85);
      ctx.closePath();
      ctx.fill();
    }
  }

  function dogHead(ctx, x, y, r) {
    circle(ctx, DOG, x, y, r);
    ctx.fillStyle = DOG_DARK;
    ctx.beginPath();
    ctx.ellipse(x - r * 0.75, y + r * 0.15, r * 0.38, r * 0.8, 0.25, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#e9c79f";
    ctx.beginPath();
    ctx.ellipse(x + r * 0.7, y + r * 0.3, r * 0.55, r * 0.4, 0, 0, Math.PI * 2);
    ctx.fill();
    circle(ctx, DARK, x + r * 1.15, y + r * 0.15, r * 0.2);
    circle(ctx, DARK, x + r * 0.2, y - r * 0.3, r * 0.15);
  }

  function carColor(theme, uid) {
    const c = CAR_COLORS[uid % CAR_COLORS.length];
    return theme[c] || c;
  }

  // Auto vista di lato verso destra. variante: "ok" | "cintura" | "telefono" | "fanale" | "cane".
  function drawAuto(ctx, x, y, color, variante) {
    const faro = variante !== "fanale";
    if (faro) {
      ctx.fillStyle = "rgba(254,240,138,0.6)";
      ctx.beginPath();
      ctx.moveTo(x + 62, y + 2);
      ctx.lineTo(x + 92, y - 10);
      ctx.lineTo(x + 92, y + 16);
      ctx.closePath();
      ctx.fill();
    }
    ctx.fillStyle = color;
    rrect(ctx, x + 11, y - 36, 42, 34, 11);
    ctx.fill();
    rrect(ctx, x, y - 6, 64, 24, 9);
    ctx.fill();
    // finestrino con conducente
    ctx.save();
    rrect(ctx, x + 15, y - 32, 34, 28, 7);
    ctx.fillStyle = GLASS;
    ctx.fill();
    ctx.clip();
    if (variante === "cane") {
      ctx.fillStyle = DOG;
      rrect(ctx, x + 18, y - 14, 18, 14, 5);
      ctx.fill();
      dogHead(ctx, x + 29, y - 20, 7);
      ctx.strokeStyle = DARK;
      ctx.lineWidth = 2.6;
      ctx.beginPath();
      ctx.ellipse(x + 43, y - 12, 2.5, 7, 0, 0, Math.PI * 2);
      ctx.stroke();
      circle(ctx, DOG, x + 41, y - 10, 2.8);
    } else {
      ctx.fillStyle = "#f8fafc";
      rrect(ctx, x + 19, y - 18, 24, 18, 7);
      ctx.fill();
      ctx.strokeStyle = "#94a3b8";
      ctx.lineWidth = 1;
      ctx.stroke();
      head(ctx, x + 31, y - 24, 6.5, false);
      if (variante !== "cintura") stroke(ctx, DARK, 4.5, [x + 21, y - 17, x + 40, y - 4]);
    }
    ctx.restore();
    if (variante === "telefono") {
      circle(ctx, SKIN, x + 40, y - 18, 3.2);
      ctx.fillStyle = DARK;
      rrect(ctx, x + 38, y - 32, 8, 13, 2);
      ctx.fill();
      ctx.fillStyle = "#7dd3fc";
      rrect(ctx, x + 39.3, y - 30.5, 5.4, 9, 1);
      ctx.fill();
      ctx.strokeStyle = HELMET;
      ctx.lineWidth = 2;
      ctx.lineCap = "round";
      for (const r of [5, 9]) {
        ctx.beginPath();
        ctx.arc(x + 42, y - 26, r + 4, -Math.PI * 0.45, Math.PI * 0.05);
        ctx.stroke();
      }
    }
    // fari: anteriore giallo (grigio se spento), posteriore rosso
    ctx.fillStyle = faro ? "#fde047" : "#6b7280";
    ctx.beginPath();
    ctx.ellipse(x + 61, y + 1, 3.5, 5, 0, 0, Math.PI * 2);
    ctx.fill();
    if (!faro) {
      ctx.strokeStyle = DARK;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
    ctx.fillStyle = "#ef4444";
    rrect(ctx, x, y - 4, 4, 8, 2);
    ctx.fill();
    ctx.fillStyle = "rgba(255,255,255,0.25)";
    rrect(ctx, x + 20, y + 2, 26, 3, 1.5);
    ctx.fill();
    wheel(ctx, x + 15, y + 18, 8.5);
    wheel(ctx, x + 49, y + 18, 8.5);
  }

  // Moto vista di lato. pilota: "casco" | "senza" | "papera".
  function drawMoto(ctx, x, y, color, pilota) {
    wheel(ctx, x + 12, y + 17, 10);
    wheel(ctx, x + 52, y + 17, 10);
    stroke(ctx, "#9ca3af", 3.5, [x + 52, y + 17, x + 46, y - 8]);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x + 10, y + 8);
    ctx.lineTo(x + 50, y + 8);
    ctx.lineTo(x + 46, y - 4);
    ctx.lineTo(x + 30, y - 6);
    ctx.lineTo(x + 18, y - 2);
    ctx.closePath();
    ctx.fill();
    stroke(ctx, DARK, 3, [x + 46, y - 8, x + 41, y - 12]);
    if (pilota === "papera") {
      ctx.fillStyle = DUCK;
      ctx.beginPath();
      ctx.ellipse(x + 28, y - 13, 11, 10, -0.3, 0, Math.PI * 2);
      ctx.fill();
      stroke(ctx, DUCK, 4, [x + 33, y - 15, x + 41, y - 12]);
      circle(ctx, DUCK, x + 35, y - 28, 8.5);
      ctx.fillStyle = BEAK;
      ctx.beginPath();
      ctx.ellipse(x + 44, y - 26, 6, 3, 0, 0, Math.PI * 2);
      ctx.fill();
      circle(ctx, DARK, x + 37, y - 30, 1.6);
      stroke(ctx, DUCK, 2.5, [x + 33, y - 36, x + 30, y - 40]);
    } else {
      stroke(ctx, "#7c3aed", 7, [x + 27, y - 6, x + 33, y - 20]);
      stroke(ctx, "#7c3aed", 4, [x + 33, y - 17, x + 41, y - 12]);
      stroke(ctx, "#334155", 5, [x + 28, y - 4, x + 37, y + 2, x + 36, y + 8]);
      head(ctx, x + 35, y - 29, 7, pilota === "casco");
      if (pilota !== "casco") {
        for (const dy of [-34, -28]) stroke(ctx, "rgba(148,163,184,0.9)", 2, [x + 18, y + dy, x + 25, y + dy]);
      }
    }
  }

  function drawMonopattino(ctx, x, y, phase) {
    ctx.fillStyle = DARK;
    rrect(ctx, x + 8, y + 13, 42, 5, 2.5);
    ctx.fill();
    wheel(ctx, x + 12, y + 21, 5);
    wheel(ctx, x + 49, y + 21, 5);
    stroke(ctx, "#64748b", 3.5, [x + 49, y + 16, x + 45, y - 22]);
    stroke(ctx, DARK, 3.5, [x + 41, y - 22, x + 49, y - 22]);
    const s = Math.sin(phase) * 1.5;
    stroke(ctx, "#334155", 5, [x + 24, y + 12, x + 27, y - 4, x + 32, y + 12]);
    stroke(ctx, "#0d9488", 8, [x + 28, y - 4, x + 30, y - 19]);
    stroke(ctx, "#0d9488", 4, [x + 31, y - 15, x + 44, y - 20 + s]);
    head(ctx, x + 31, y - 28, 6.5, true);
  }

  function drawPedone(ctx, x, y, phase) {
    // strisce pedonali sotto i piedi
    ctx.fillStyle = "rgba(255,255,255,0.85)";
    for (let i = 0; i < 5; i++) ctx.fillRect(x + 8 + i * 10, y + 20, 6, 8);
    const a = Math.sin(phase) * 7;
    const cx = x + 32;
    stroke(ctx, "#334155", 5, [cx, y + 2, cx + a, y + 20]);
    stroke(ctx, "#334155", 5, [cx, y + 2, cx - a, y + 20]);
    stroke(ctx, "#2563eb", 9, [cx, y - 16, cx, y + 2]);
    stroke(ctx, "#2563eb", 4, [cx, y - 13, cx - a * 0.8, y - 1]);
    stroke(ctx, "#2563eb", 4, [cx, y - 13, cx + a * 0.8, y - 1]);
    head(ctx, cx + 1, y - 25, 7, false);
  }

  function drawSignora(ctx, x, y, phase) {
    const a = Math.sin(phase) * 4;
    const cx = x + 20;
    // carrello davanti
    ctx.strokeStyle = "#94a3b8";
    ctx.lineWidth = 2.5;
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(x + 36, y - 10);
    ctx.lineTo(x + 64, y - 10);
    ctx.lineTo(x + 60, y + 10);
    ctx.lineTo(x + 40, y + 10);
    ctx.closePath();
    ctx.stroke();
    circle(ctx, "#4ade80", x + 45, y - 13, 5);
    circle(ctx, BEAK, x + 54, y - 12, 4.5);
    ctx.fillStyle = "#f8fafc";
    rrect(ctx, x + 57, y - 20, 5, 10, 1.5);
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (const gx of [44, 50, 56]) {
      ctx.moveTo(x + gx, y - 10);
      ctx.lineTo(x + gx - 1, y + 10);
    }
    ctx.moveTo(x + 37, y);
    ctx.lineTo(x + 62, y);
    ctx.stroke();
    stroke(ctx, "#94a3b8", 2.5, [x + 40, y + 10, x + 42, y + 18, x + 60, y + 18]);
    wheel(ctx, x + 44, y + 21, 3.5);
    wheel(ctx, x + 58, y + 21, 3.5);
    stroke(ctx, "#94a3b8", 2.5, [x + 30, y - 13, x + 36, y - 10]);
    // signora
    stroke(ctx, "#334155", 4, [cx - 2, y + 6, cx - 2 - a, y + 21]);
    stroke(ctx, "#334155", 4, [cx + 3, y + 6, cx + 3 + a, y + 21]);
    ctx.fillStyle = "#db2777";
    ctx.beginPath();
    ctx.moveTo(cx - 5, y - 18);
    ctx.lineTo(cx + 6, y - 18);
    ctx.lineTo(cx + 12, y + 8);
    ctx.lineTo(cx - 11, y + 8);
    ctx.closePath();
    ctx.fill();
    stroke(ctx, "#db2777", 4, [cx + 3, y - 14, cx + 11, y - 13]);
    circle(ctx, SKIN, cx + 11, y - 13, 2.6);
    circle(ctx, "#cbd5e1", cx - 6, y - 31, 4.5);
    circle(ctx, SKIN, cx + 1, y - 26, 7);
    ctx.fillStyle = "#cbd5e1";
    ctx.beginPath();
    ctx.arc(cx, y - 27, 7.5, Math.PI * 0.95, Math.PI * 1.9);
    ctx.closePath();
    ctx.fill();
    circle(ctx, DARK, cx + 4, y - 26, 1.1);
  }

  function drawCane(ctx, x, y, phase) {
    const a = Math.sin(phase) * 4;
    stroke(ctx, DOG, 4, [x + 10, y - 2, x + 2, y - 14]);
    for (const [lx, d] of [[x + 16, a], [x + 24, -a], [x + 40, -a], [x + 48, a]]) stroke(ctx, DOG_DARK, 5, [lx, y + 6, lx + d, y + 22]);
    ctx.fillStyle = DOG;
    ctx.beginPath();
    ctx.ellipse(x + 30, y + 2, 22, 12, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#e9c79f";
    ctx.beginPath();
    ctx.ellipse(x + 30, y + 7, 13, 5, 0, 0, Math.PI * 2);
    ctx.fill();
    dogHead(ctx, x + 50, y - 12, 11);
    ctx.fillStyle = "#f472b6";
    ctx.beginPath();
    ctx.ellipse(x + 58, y - 4, 2.5, 4, 0.2, 0, Math.PI * 2);
    ctx.fill();
  }

  function drawPapera(ctx, x, y, phase) {
    const a = Math.sin(phase) * 5;
    stroke(ctx, BEAK, 3, [x + 28, y + 14, x + 28 + a, y + 23]);
    stroke(ctx, BEAK, 3, [x + 36, y + 14, x + 36 - a, y + 23]);
    ctx.fillStyle = DUCK;
    ctx.beginPath();
    ctx.moveTo(x + 6, y - 6);
    ctx.lineTo(x + 18, y + 2);
    ctx.lineTo(x + 14, y + 8);
    ctx.closePath();
    ctx.fill();
    ctx.beginPath();
    ctx.ellipse(x + 30, y + 4, 19, 13, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#f59e0b";
    ctx.beginPath();
    ctx.ellipse(x + 27, y + 2, 10, 6, -0.25, 0, Math.PI * 2);
    ctx.fill();
    circle(ctx, DUCK, x + 46, y - 14, 10);
    ctx.fillStyle = BEAK;
    ctx.beginPath();
    ctx.ellipse(x + 57, y - 11, 7, 3.4, 0, 0, Math.PI * 2);
    ctx.fill();
    circle(ctx, DARK, x + 49, y - 17, 1.8);
  }

  function drawGattoPassante(ctx, x, y, theme, phase, ladro) {
    const bob = -Math.abs(Math.sin(phase)) * 4;
    if (ladro) {
      // sacco sulla schiena con i gomitoli rubati
      ctx.fillStyle = "#a16207";
      ctx.beginPath();
      ctx.ellipse(x + 10, y - 2 + bob, 14, 15, -0.2, 0, Math.PI * 2);
      ctx.fill();
      drawYarn(ctx, x + 5, y - 17 + bob, 5.5, theme.bad, 0.3);
      drawYarn(ctx, x + 15, y - 19 + bob, 5.5, theme.accent, 1.2);
      stroke(ctx, "#713f12", 2.5, [x + 4, y - 11 + bob, x + 18, y - 13 + bob]);
    }
    drawCat(ctx, x + 36, y + 4, 0.78, theme.warn, { bob, mask: ladro });
  }

  function drawPassante(ctx, theme, p, phase) {
    const x = p.x;
    const y = p.y;
    const col = carColor(theme, p.uid);
    switch (p.id) {
      case "auto-cintura": return drawAuto(ctx, x, y, col, "cintura");
      case "auto-telefono": return drawAuto(ctx, x, y, col, "telefono");
      case "auto-fanale": return drawAuto(ctx, x, y, col, "fanale");
      case "auto-ok": return drawAuto(ctx, x, y, col, "ok");
      case "cane-volante": return drawAuto(ctx, x, y, col, "cane");
      case "moto-casco": return drawMoto(ctx, x, y, col, "senza");
      case "moto-ok": return drawMoto(ctx, x, y, col, "casco");
      case "papera-moto": return drawMoto(ctx, x, y, col, "papera");
      case "monopattino-ok": return drawMonopattino(ctx, x, y, phase);
      case "pedone-strisce": return drawPedone(ctx, x, y, phase);
      case "signora-carrello": return drawSignora(ctx, x, y, phase);
      case "gatto": return drawGattoPassante(ctx, x, y, theme, phase, false);
      case "gatto-ladro": return drawGattoPassante(ctx, x, y, theme, phase, true);
      case "cane": return drawCane(ctx, x, y, phase);
      case "papera": return drawPapera(ctx, x, y, phase);
      default: return null;
    }
  }

  // Piccola icona di un animale della squadra.
  function drawIcona(ctx, theme, specie, x, y) {
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(0.5, 0.5);
    if (specie === "gatto") drawCat(ctx, 0, 0, 1, theme.warn);
    else if (specie === "cane") drawCane(ctx, -32, 4, 0);
    else drawPapera(ctx, -32, 6, 0);
    ctx.restore();
  }

  function heart(ctx, x, y, s, color) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x, y + s * 0.35);
    ctx.bezierCurveTo(x - s, y - s * 0.4, x - s * 0.45, y - s, x, y - s * 0.45);
    ctx.bezierCurveTo(x + s * 0.45, y - s, x + s, y - s * 0.4, x, y + s * 0.35);
    ctx.fill();
  }

  function drawPaletta(ctx, theme, occupato) {
    const { x, y, r } = PALETTA;
    ctx.fillStyle = "rgba(0,0,0,0.15)";
    ctx.beginPath();
    ctx.ellipse(x, y + r + 66, 12, 4, 0, 0, Math.PI * 2);
    ctx.fill();
    stroke(ctx, "#9ca3af", 7, [x, y + r - 2, x, y + r + 64]);
    circle(ctx, occupato ? "#9ca3af" : RED, x, y, r);
    circle(ctx, occupato ? "#e5e7eb" : "#ffffff", x, y, r - 7);
    if (occupato) label(ctx, "occupato", x - 32, y + r + 16, theme.muted, theme, 15);
  }

  function drawScena(ctx, theme) {
    // marciapiede in alto con alberi
    ctx.fillStyle = theme.surface2;
    ctx.fillRect(0, 0, W, H);
    for (const tx of [34, 112, 190]) {
      stroke(ctx, "#8b5e34", 6, [tx, 120, tx, 140]);
      circle(ctx, theme.dark ? "#2f7a4a" : "#5fb878", tx, 104, 22);
      circle(ctx, theme.dark ? "#3a8f58" : "#7cc993", tx - 7, 97, 9);
    }
    ctx.fillStyle = theme.border;
    ctx.fillRect(0, ROAD_TOP - 14, W, 14);
    ctx.fillRect(0, ROAD_BOTTOM, W, 14);
    // strada
    ctx.fillStyle = theme.dark ? "#2d323c" : "#5b6472";
    ctx.fillRect(0, ROAD_TOP, W, ROAD_BOTTOM - ROAD_TOP);
    ctx.fillStyle = "rgba(255,255,255,0.8)";
    ctx.fillRect(0, ROAD_TOP + 6, W, 3);
    ctx.fillRect(0, ROAD_BOTTOM - 9, W, 3);
    for (let i = 0; i < 9; i++) ctx.fillRect(i * 44 + 6, MID - 2, 24, 4);
    // strisce pedonali
    ctx.fillStyle = theme.dark ? "rgba(255,255,255,0.22)" : "rgba(255,255,255,0.35)";
    for (let yy = ROAD_TOP + 16; yy < ROAD_BOTTOM - 20; yy += 18) ctx.fillRect(214, yy, 44, 10);
  }

  function create(rand) {
    const state = G.bloccoState();
    const score = state.score;
    const game = { score, state, adottati: [], fermati: 0, update, draw, pointerDown, pointerMove, pointerUp, summary };
    let t = 0;
    let now = 0;
    let nextSpawn = 0.3;
    let flashUntil = -1;
    let fx = [];

    function addFx(text, x, y, color) {
      fx.push({ text, x: Math.max(70, Math.min(W - 70, x)), y, color, t0: now, size: 18 });
    }

    function update(dt, nowArg) {
      now = nowArg;
      fx = fx.filter((f) => now - f.t0 <= C.FX_S);
      if (score.over) return;
      t += dt;
      nextSpawn -= dt;
      if (nextSpawn <= 0) {
        G.bloccoSpawn(state, rand, t);
        nextSpawn += G.difficulty(t).passEvery;
      }
      // Un'adozione conta solo se il core l'ha registrata nella squadra (non a partita finita).
      const nuovi = Object.assign({}, state.squadra);
      const eventi = G.bloccoStep(state, dt, now);
      for (const k of Object.keys(state.squadra)) nuovi[k] = state.squadra[k] - (nuovi[k] || 0);
      for (const e of eventi) {
        const tipo = G.BY_ID[e.p.id];
        if (e.tipo === "adottato" && nuovi[tipo.specie] > 0) {
          nuovi[tipo.specie] -= 1;
          game.adottati.push(tipo.specie);
          addFx("Adottato!", e.p.x + PW / 2, e.p.y - PH / 2 - 10, "ok");
        } else if (e.tipo === "perso") {
          flashUntil = now + C.FLASH_S;
          addFx("Perso!", W - 60, e.p.y - 10, "bad");
        }
      }
    }

    function drawStato(ctx, theme, p) {
      const cx = p.x + PW / 2;
      if (p.stato === "coccole") {
        const k = 1 - Math.max(0, p.until - now) / G.CUDDLE_S;
        for (let i = 0; i < 3; i++) {
          const kk = (k + i / 3) % 1;
          ctx.globalAlpha = 1 - kk;
          heart(ctx, cx - 16 + i * 16, p.y - PH / 2 - 4 - kk * 26, 9, "#ec4899");
        }
        ctx.globalAlpha = 1;
      } else if (p.stato === "fermato") {
        const giusto = G.BY_ID[p.id].cat === "irregolare";
        const k = Math.max(0, p.until - now) / G.STOP_S;
        const r = 16 + (1 - k) * 4;
        ctx.globalAlpha = Math.min(1, k * 2.5);
        circle(ctx, giusto ? theme.ok : theme.bad, cx, p.y - 6, r);
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 4.5;
        ctx.lineCap = "round";
        ctx.beginPath();
        if (giusto) {
          ctx.moveTo(cx - 8, p.y - 6);
          ctx.lineTo(cx - 2, p.y);
          ctx.lineTo(cx + 9, p.y - 13);
        } else {
          ctx.moveTo(cx - 7, p.y - 13);
          ctx.lineTo(cx + 7, p.y + 1);
          ctx.moveTo(cx + 7, p.y - 13);
          ctx.lineTo(cx - 7, p.y + 1);
        }
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
    }

    function drawEtichetta(ctx, theme, p, occupate) {
      ctx.font = "700 15px " + theme.font;
      const righe = righeEtichetta(G.BY_ID[p.id].label, (s) => ctx.measureText(s).width, ETICHETTA_W);
      const w = Math.max(...righe.map((r) => ctx.measureText(r).width)) + 14;
      const h = righe.length * 18 + 4;
      const cx = Math.max(w / 2 + 2, Math.min(W - w / 2 - 2, p.x + PW / 2));
      const y = p.y + PH / 2 + 2;
      const box = { x0: cx - w / 2 - 3, x1: cx + w / 2 + 3, y0: y, y1: y + h };
      if (occupate.some((b) => b.x0 < box.x1 && box.x0 < b.x1 && b.y0 < box.y1 && box.y0 < b.y1)) return;
      occupate.push(box);
      ctx.globalAlpha = 0.92;
      ctx.fillStyle = theme.surface;
      rrect(ctx, cx - w / 2, y, w, h, 9);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.fillStyle = theme.text;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      righe.forEach((r, i) => ctx.fillText(r, cx, y + 11 + i * 18 + 0.5));
    }

    function drawSquadra(ctx, theme) {
      const y0 = ROAD_BOTTOM + 44;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.font = "700 15px " + theme.font;
      ctx.fillStyle = theme.muted;
      if (!game.adottati.length) {
        ctx.fillText("Tocca gli animali per adottarli", 16, y0);
        return;
      }
      ctx.fillText("Squadra", 16, y0);
      const { icone, extra } = squadraIcone(game.adottati);
      icone.forEach((s, i) => drawIcona(ctx, theme, s, 30 + i * 31, y0 + 50));
      if (extra) label(ctx, "+" + extra, W - 24, y0 + 50, theme.text, theme, 17);
    }

    function draw(ctx, theme) {
      drawScena(ctx, theme);
      drawPaletta(ctx, theme, now < state.busyUntil);
      const etichette = labelVisibile(t);
      for (const p of state.passanti) {
        const coccole = p.stato === "coccole";
        const phase = coccole ? now * 14 : p.x / 7;
        if (p.stato === "fermato") ctx.globalAlpha = 0.45 + 0.55 * Math.max(0, p.until - now) / G.STOP_S;
        ctx.save();
        if (coccole) ctx.translate(0, -Math.abs(Math.sin(now * 10)) * 5);
        drawPassante(ctx, theme, p, phase);
        ctx.restore();
        ctx.globalAlpha = 1;
        drawStato(ctx, theme, p);
      }
      if (etichette) {
        const occupate = [];
        const vivi = state.passanti.filter((p) => p.stato === "cammina").sort((a, b) => b.x - a.x);
        for (const p of vivi) drawEtichetta(ctx, theme, p, occupate);
      }
      drawSquadra(ctx, theme);
      drawFx(ctx, theme, fx, now);
      if (!score.over) drawFlash(ctx, theme, flashUntil, now);
    }

    function pointerDown(x, y, nowArg) {
      if (score.over) return null;
      const n = nowArg === undefined ? now : nowArg;
      const p = G.hitTest(state, x, y);
      if (!p) return null;
      const prima = score.points;
      const esito = G.bloccoStop(state, p, n);
      const cx = p.x + PW / 2;
      const ty = p.y - PH / 2 - 12;
      if (esito === "fermato") {
        game.fermati += 1;
        addFx("+" + G.formatPoints(score.points - prima) + " fermato!", cx, ty, "ok");
      } else if (esito === "errore") {
        flashUntil = n + C.FLASH_S;
        addFx("Errore: era in regola", cx, ty, "bad");
      } else if (esito === "occupato") {
        addFx("occupato", cx, ty, "muted");
      }
      return esito;
    }
    function pointerMove() {}
    function pointerUp() {}

    function summary() {
      return { righe: ["Irregolari fermati: " + game.fermati], squadra: state.squadra, viste: state.viste };
    }

    return game;
  }

  const view = {
    id: "blocco",
    titolo: "Posto di blocco",
    intro: "Tocca chi è irregolare prima che esca dallo schermo e lascia passare chi è in regola. Gli animali toccati vengono adottati: bonus, ma la paletta resta occupata per un secondo.",
    create,
    labelVisibile,
    righeEtichetta,
    squadraIcone,
    LABEL_S,
    SQUADRA_MAX,
  };
  if (NODE) module.exports = view;
  else {
    root.LexGameViews = root.LexGameViews || {};
    root.LexGameViews.blocco = view;
  }
})(typeof window !== "undefined" ? window : globalThis);
