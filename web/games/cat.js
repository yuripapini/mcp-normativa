"use strict";
// Gioco "Gomitoli": il gatto raccoglie i gomitoli che cadono ed evita i cetrioli. Disegno su canvas e input.
(function (root) {
  const NODE = typeof module === "object" && module.exports;
  const G = NODE ? require("./core.js") : root.LexGames;
  const W = G.W;
  const H = G.H;
  const FLOOR_Y = G.CAT.y + G.CAT.h / 2 + 4;
  const FX_S = 0.6; // durata delle scritte che salgono
  const FLASH_S = 0.2; // lampo rosso del bordo alla perdita di una vita
  const CUCUMBER = "#3f8f3a";
  const CUCUMBER_DARK = "#2d6a2a";

  // Rettangolo arrotondato senza ctx.roundRect (assente nei Safari meno recenti).
  function rrect(ctx, x, y, w, h, r) {
    const k = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + k, y);
    ctx.arcTo(x + w, y, x + w, y + h, k);
    ctx.arcTo(x + w, y + h, x, y + h, k);
    ctx.arcTo(x, y + h, x, y, k);
    ctx.arcTo(x, y, x + w, y, k);
    ctx.closePath();
  }

  // Gatto originale visto di fronte, seduto. (x, y) = centro del corpo; s = scala (1 = 72 x 48 circa).
  // opts: { mood: "felice" | "spaventato", mask: true (mascherina da ladro), bob: spostamento verticale }
  function drawCat(ctx, x, y, s, color, opts) {
    const o = opts || {};
    ctx.save();
    ctx.translate(x, y + (o.bob || 0));
    ctx.scale(s, s);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    // ombra
    ctx.fillStyle = "rgba(0,0,0,0.16)";
    ctx.beginPath();
    ctx.ellipse(0, 24, 30, 5, 0, 0, Math.PI * 2);
    ctx.fill();
    // coda curva
    ctx.strokeStyle = color;
    ctx.lineWidth = 8;
    ctx.beginPath();
    ctx.moveTo(18, 16);
    ctx.bezierCurveTo(40, 18, 44, -4, 34, -14);
    ctx.stroke();
    // corpo
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.ellipse(0, 8, 25, 17, 0, 0, Math.PI * 2);
    ctx.fill();
    // pancia chiara
    ctx.fillStyle = "rgba(255,255,255,0.35)";
    ctx.beginPath();
    ctx.ellipse(0, 12, 12, 10, 0, 0, Math.PI * 2);
    ctx.fill();
    // zampe
    ctx.fillStyle = color;
    for (const dx of [-10, 10]) {
      ctx.beginPath();
      ctx.ellipse(dx, 23, 7, 4.5, 0, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.fillStyle = "rgba(255,255,255,0.45)";
    for (const dx of [-10, 10]) {
      ctx.beginPath();
      ctx.ellipse(dx, 24, 4, 2, 0, 0, Math.PI * 2);
      ctx.fill();
    }
    // orecchie
    ctx.fillStyle = color;
    for (const sx of [-1, 1]) {
      ctx.beginPath();
      ctx.moveTo(sx * 6, -26);
      ctx.lineTo(sx * 17, -38);
      ctx.lineTo(sx * 18, -18);
      ctx.closePath();
      ctx.fill();
    }
    ctx.fillStyle = "#f4a7b4";
    for (const sx of [-1, 1]) {
      ctx.beginPath();
      ctx.moveTo(sx * 9, -25);
      ctx.lineTo(sx * 15.5, -33);
      ctx.lineTo(sx * 16, -22);
      ctx.closePath();
      ctx.fill();
    }
    // testa
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(0, -14, 17, 0, Math.PI * 2);
    ctx.fill();
    // strisce sulla fronte
    ctx.strokeStyle = "rgba(0,0,0,0.18)";
    ctx.lineWidth = 2.5;
    for (const dx of [-5, 0, 5]) {
      ctx.beginPath();
      ctx.moveTo(dx, -30);
      ctx.lineTo(dx, -25);
      ctx.stroke();
    }
    // mascherina da ladro
    if (o.mask) {
      ctx.fillStyle = "#111827";
      rrect(ctx, -16, -21, 32, 10, 5);
      ctx.fill();
    }
    // occhi
    if (o.mood === "spaventato") {
      ctx.fillStyle = "#ffffff";
      for (const dx of [-7, 7]) {
        ctx.beginPath();
        ctx.arc(dx, -16, 5, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.fillStyle = "#111827";
      for (const dx of [-7, 7]) {
        ctx.beginPath();
        ctx.arc(dx, -16, 2, 0, Math.PI * 2);
        ctx.fill();
      }
    } else if (o.mood === "felice") {
      ctx.strokeStyle = "#111827";
      ctx.lineWidth = 2.2;
      for (const dx of [-7, 7]) {
        ctx.beginPath();
        ctx.arc(dx, -14, 3.5, Math.PI * 1.15, Math.PI * 1.85);
        ctx.stroke();
      }
    } else {
      ctx.fillStyle = o.mask ? "#ffffff" : "#111827";
      for (const dx of [-7, 7]) {
        ctx.beginPath();
        ctx.ellipse(dx, -16, 2.6, 3.6, 0, 0, Math.PI * 2);
        ctx.fill();
      }
      if (!o.mask) {
        ctx.fillStyle = "#ffffff";
        for (const dx of [-6, 8]) {
          ctx.beginPath();
          ctx.arc(dx, -17.5, 1, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
    // naso, bocca, baffi
    ctx.fillStyle = "#e86a86";
    ctx.beginPath();
    ctx.moveTo(-3, -9.5);
    ctx.lineTo(3, -9.5);
    ctx.lineTo(0, -6.5);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = "#111827";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    if (o.mood === "spaventato") {
      ctx.arc(0, -2.5, 2.6, 0, Math.PI * 2);
    } else {
      ctx.moveTo(0, -6.5);
      ctx.quadraticCurveTo(-1.5, -3.5, -4, -4.5);
      ctx.moveTo(0, -6.5);
      ctx.quadraticCurveTo(1.5, -3.5, 4, -4.5);
    }
    ctx.stroke();
    ctx.strokeStyle = "rgba(17,24,39,0.55)";
    ctx.lineWidth = 1.1;
    for (const sx of [-1, 1]) {
      for (const dy of [-1.5, 2]) {
        ctx.beginPath();
        ctx.moveTo(sx * 7, -7 + dy * 0.4);
        ctx.lineTo(sx * 21, -8 + dy * 2);
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  function drawYarn(ctx, x, y, r, color, spin) {
    ctx.save();
    ctx.translate(x, y);
    // filo che segue il gomitolo
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(r * 0.6, -r * 0.7);
    ctx.bezierCurveTo(r * 1.6, -r * 1.6, r * 0.2, -r * 2.2, r * 1.1, -r * 3);
    ctx.stroke();
    ctx.rotate(spin);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.save();
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.clip();
    ctx.strokeStyle = "rgba(255,255,255,0.55)";
    ctx.lineWidth = 2;
    for (const [cx, cy, rr] of [[-r * 0.9, -r * 0.3, r * 1.1], [r * 0.8, r * 0.5, r * 0.95], [0, r * 1.2, r * 0.9]]) {
      ctx.beginPath();
      ctx.arc(cx, cy, rr, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
    ctx.restore();
  }

  function drawCucumber(ctx, x, y, r, angle) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(angle);
    ctx.fillStyle = CUCUMBER;
    ctx.strokeStyle = CUCUMBER_DARK;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.ellipse(0, 0, r * 1.7, r * 0.78, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "rgba(255,255,255,0.22)";
    ctx.beginPath();
    ctx.ellipse(-r * 0.2, -r * 0.3, r * 1.1, r * 0.22, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#c9e7b5";
    for (const [dx, dy] of [[-12, 3], [-5, -4], [2, 4], [9, -3], [15, 2], [-15, -2]]) {
      ctx.beginPath();
      ctx.arc(dx * r / 14, dy * r / 14, 1.4, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.fillStyle = CUCUMBER_DARK;
    rrect(ctx, r * 1.6, -2, 5, 4, 2);
    ctx.fill();
    ctx.restore();
  }

  // Scritta con bordo del colore di sfondo, leggibile su qualunque disegno.
  function label(ctx, text, x, y, color, theme, size) {
    ctx.font = "800 " + (size || 18) + "px " + theme.font;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.lineJoin = "round";
    ctx.lineWidth = 5;
    ctx.strokeStyle = theme.surface;
    ctx.strokeText(text, x, y);
    ctx.fillStyle = color;
    ctx.fillText(text, x, y);
  }

  function drawFx(ctx, theme, fx, now) {
    for (const f of fx) {
      const age = now - f.t0;
      if (age < 0 || age > FX_S) continue;
      ctx.globalAlpha = 1 - age / FX_S;
      label(ctx, f.text, f.x, f.y - 40 * age, theme[f.color] || f.color, theme, f.size);
    }
    ctx.globalAlpha = 1;
  }

  function drawFlash(ctx, theme, until, now) {
    if (now >= until) return;
    ctx.globalAlpha = (until - now) / FLASH_S;
    ctx.strokeStyle = theme.bad;
    ctx.lineWidth = 10;
    ctx.strokeRect(5, 5, W - 10, H - 10);
    ctx.globalAlpha = 1;
  }

  function create(rand) {
    const score = G.createScore();
    const game = {
      score,
      objects: [],
      catX: W / 2,
      presi: 0,
      update,
      draw,
      pointerDown,
      pointerMove,
      pointerUp,
      summary,
    };
    let targetX = W / 2;
    let t = 0;
    let now = 0;
    let nextSpawn = 0.5;
    let flashUntil = -1;
    let scaredUntil = -1;
    let happyUntil = -1;
    let fx = [];

    function addFx(text, x, y, color) {
      fx.push({ text, x: Math.max(40, Math.min(W - 40, x)), y, color, t0: now });
    }

    function update(dt, nowArg) {
      now = nowArg;
      fx = fx.filter((f) => now - f.t0 <= FX_S);
      if (score.over) return;
      t += dt;
      game.catX = G.catMove(game.catX, targetX, dt);
      nextSpawn -= dt;
      if (nextSpawn <= 0) {
        game.objects.push(G.catSpawn(rand, t));
        nextSpawn += G.difficulty(t).spawnEvery;
      }
      const restano = [];
      for (const o of game.objects) {
        o.spin = (o.spin || 0) + dt * (o.kind === "yarn" ? 3 : 1.6);
        const ev = score.over ? null : G.catStep(game.catX, o, dt);
        if (!ev) {
          restano.push(o);
          continue;
        }
        const prima = score.points;
        const vite = score.lives;
        G.catOutcome(score, o.kind, ev);
        if (score.points > prima) {
          game.presi += 1;
          happyUntil = now + 0.35;
          addFx("+" + G.formatPoints(score.points - prima), o.x, G.CAT.y - 44, "ok");
        }
        if (score.lives < vite) {
          flashUntil = now + FLASH_S;
          if (o.kind === "cucumber") {
            scaredUntil = now + 0.5;
            addFx("Cetriolo!", game.catX, G.CAT.y - 50, "bad");
          } else {
            addFx("Perso!", o.x, FLOOR_Y - 14, "bad");
          }
        }
      }
      game.objects = restano;
    }

    function draw(ctx, theme) {
      // stanza: parete, battiscopa e pavimento
      ctx.fillStyle = theme.surface2;
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = theme.dark ? "rgba(255,255,255,0.03)" : "rgba(17,24,39,0.035)";
      for (let i = 0; i < 6; i++) ctx.fillRect(i * 64 + 16, 0, 28, FLOOR_Y);
      // finestra con la luna
      ctx.fillStyle = theme.surface;
      rrect(ctx, 30, 40, 86, 70, 10);
      ctx.fill();
      ctx.strokeStyle = theme.border;
      ctx.lineWidth = 4;
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(73, 40);
      ctx.lineTo(73, 110);
      ctx.moveTo(30, 75);
      ctx.lineTo(116, 75);
      ctx.stroke();
      ctx.fillStyle = theme.warn;
      ctx.globalAlpha = 0.5;
      ctx.beginPath();
      ctx.arc(96, 58, 9, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      // pavimento
      ctx.fillStyle = theme.border;
      ctx.fillRect(0, FLOOR_Y, W, H - FLOOR_Y);
      ctx.fillStyle = theme.dark ? "rgba(255,255,255,0.06)" : "rgba(17,24,39,0.06)";
      for (let i = 0; i < 9; i++) ctx.fillRect(i * 44 + 8, FLOOR_Y + 14, 26, 3);
      ctx.fillStyle = theme.muted;
      ctx.fillRect(0, FLOOR_Y - 3, W, 3);

      for (const o of game.objects) {
        if (o.kind === "yarn") drawYarn(ctx, o.x, o.y, o.r, theme.bad, o.spin || 0);
        else drawCucumber(ctx, o.x, o.y, o.r, (o.spin || 0) * 0.6 + 0.4);
      }
      const mood = now < scaredUntil ? "spaventato" : now < happyUntil ? "felice" : "";
      const bob = mood === "spaventato" ? -6 : 0;
      drawCat(ctx, game.catX, G.CAT.y + 2, 1, theme.warn, { mood, bob });
      drawFx(ctx, theme, fx, now);
      if (!score.over) drawFlash(ctx, theme, flashUntil, now);
    }

    function pointerDown(x) {
      targetX = x;
    }
    function pointerMove(x) {
      targetX = x;
    }
    function pointerUp() {}

    function summary() {
      return { righe: ["Gomitoli presi: " + game.presi] };
    }

    return game;
  }

  const view = {
    id: "gomitoli",
    titolo: "Gomitoli",
    intro: "Trascina il dito per spostare il gatto: prendi i gomitoli ed evita i cetrioli. Ogni gomitolo che tocca terra costa una vita.",
    create,
    drawCat,
    rrect,
    label,
    drawFx,
    drawFlash,
    drawYarn,
    FX_S,
    FLASH_S,
  };
  if (NODE) module.exports = view;
  else {
    root.LexGameViews = root.LexGameViews || {};
    root.LexGameViews.gomitoli = view;
    root.LexGameViews.drawCat = drawCat;
  }
})(typeof window !== "undefined" ? window : globalThis);
