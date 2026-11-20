"use strict";
// Logica pura dei giochi della scheda Pausa: punteggio, vite, difficoltà, oggetti, decisioni, condivisione.
(function (root) {
  const W = 360;
  const H = 560;
  const LIVES = 3;
  const MAX_MULT = 5;

  // Generatore pseudocasuale con seme (mulberry32): partite riproducibili nei test.
  function rng(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function createScore() {
    return { points: 0, streak: 0, mult: 1, lives: LIVES, over: false };
  }

  // Azione corretta: punti base x moltiplicatore; ogni 5 corrette di fila il moltiplicatore sale (max x5).
  function hit(score, base) {
    if (score.over) return score;
    score.points += base * score.mult;
    score.streak += 1;
    score.mult = Math.min(MAX_MULT, 1 + Math.floor(score.streak / 5));
    return score;
  }

  // Errore: una vita in meno, serie azzerata.
  function miss(score) {
    if (score.over) return score;
    score.lives -= 1;
    score.streak = 0;
    score.mult = 1;
    score.over = score.lives <= 0;
    return score;
  }

  // Difficoltà crescente nel tempo con tetto a 120 s.
  function difficulty(t) {
    const k = Math.min(Math.max(t, 0), 120) / 120;
    return {
      fallSpeed: 140 + 260 * k, // gatto: px/s
      spawnEvery: 1.1 - 0.65 * k, // gatto: s fra un oggetto e l'altro
      cucumberChance: 0.12 + 0.23 * k,
      walkSpeed: 60 + 110 * k, // blocco: px/s
      passEvery: 2.2 - 1.3 * k, // blocco: s fra un passante e l'altro
    };
  }

  // ---- Gomitoli
  const CAT = { w: 72, h: 48, y: H - 64, maxSpeed: 900 };

  function catSpawn(rand, t) {
    const d = difficulty(t);
    const kind = rand() < d.cucumberChance ? "cucumber" : "yarn";
    return { kind, x: 24 + rand() * (W - 48), y: -20, r: kind === "yarn" ? 16 : 14, vy: d.fallSpeed * (0.9 + rand() * 0.2) };
  }

  // Il gatto insegue la x del dito con velocità massima.
  function catMove(catX, targetX, dt) {
    const max = CAT.maxSpeed * dt;
    const dx = Math.max(-max, Math.min(max, targetX - catX));
    return Math.max(CAT.w / 2, Math.min(W - CAT.w / 2, catX + dx));
  }

  function catCaught(catX, obj) {
    return Math.abs(obj.x - catX) <= CAT.w / 2 + obj.r * 0.6 && obj.y + obj.r >= CAT.y - CAT.h / 2 && obj.y - obj.r <= CAT.y + CAT.h / 2;
  }

  // Avanza un oggetto: "caught" | "ground" | null.
  function catStep(catX, obj, dt) {
    obj.y += obj.vy * dt;
    if (catCaught(catX, obj)) return "caught";
    if (obj.y - obj.r > H) return "ground";
    return null;
  }

  // Esito sul punteggio: gomitolo preso +10, gomitolo a terra -1 vita, cetriolo preso -1 vita, cetriolo a terra niente.
  function catOutcome(score, kind, event) {
    if (kind === "yarn" && event === "caught") hit(score, 10);
    else if (kind === "yarn" && event === "ground") miss(score);
    else if (kind === "cucumber" && event === "caught") miss(score);
    return score;
  }

  // ---- Posto di blocco
  // cat: "irregolare" | "regolare" | "animale"
  const PASSANTI = [
    { id: "auto-cintura", cat: "irregolare", label: "Senza cintura", articolo: "172" },
    { id: "auto-telefono", cat: "irregolare", label: "Telefono alla guida", articolo: "173" },
    { id: "moto-casco", cat: "irregolare", label: "Senza casco", articolo: "171" },
    { id: "papera-moto", cat: "irregolare", label: "Papera in moto senza casco", articolo: "171" },
    { id: "auto-fanale", cat: "irregolare", label: "Fanale spento", articolo: "152" },
    { id: "gatto-ladro", cat: "irregolare", label: "Gatto con i gomitoli rubati", battuta: "Refurtiva recuperata: 12 gomitoli." },
    { id: "cane-volante", cat: "irregolare", label: "Cane al volante", battuta: "Patente? Solo quella del guinzaglio." },
    { id: "auto-ok", cat: "regolare", label: "Auto in regola" },
    { id: "moto-ok", cat: "regolare", label: "Moto con casco" },
    { id: "pedone-strisce", cat: "regolare", label: "Pedone sulle strisce" },
    { id: "signora-carrello", cat: "regolare", label: "Signora con il carrello" },
    { id: "monopattino-ok", cat: "regolare", label: "Monopattino in regola" },
    { id: "gatto", cat: "animale", label: "Gatto", specie: "gatto" },
    { id: "cane", cat: "animale", label: "Cane", specie: "cane" },
    { id: "papera", cat: "animale", label: "Papera", specie: "papera" },
  ];
  const BY_ID = Object.fromEntries(PASSANTI.map((p) => [p.id, p]));
  const PASS_W = 64;
  const PASS_H = 56;
  const LANE_Y = [H * 0.38, H * 0.58]; // due corsie
  const CUDDLE_S = 1;
  const STOP_S = 0.6; // durata dell'animazione di un passante fermato

  function bloccoState() {
    return { score: createScore(), passanti: [], squadra: {}, viste: {}, busyUntil: 0, nextId: 1 };
  }

  // Pesi: irregolari 45%, regolari 35%, animali 20%.
  function bloccoSpawn(state, rand, t) {
    const r = rand();
    const pool = PASSANTI.filter((p) => p.cat === (r < 0.45 ? "irregolare" : r < 0.8 ? "regolare" : "animale"));
    const tipo = pool[Math.floor(rand() * pool.length)];
    const d = difficulty(t);
    const p = { uid: state.nextId++, id: tipo.id, x: -PASS_W, y: LANE_Y[Math.floor(rand() * LANE_Y.length)], vx: d.walkSpeed * (0.85 + rand() * 0.3), stato: "cammina", until: 0 };
    state.passanti.push(p);
    return p;
  }

  // Passante sotto il dito: area ampliata di 12 px; vince quello disegnato per ultimo (primo piano).
  function hitTest(state, x, y) {
    for (let i = state.passanti.length - 1; i >= 0; i--) {
      const p = state.passanti[i];
      if (p.stato !== "cammina") continue;
      if (x >= p.x - 12 && x <= p.x + PASS_W + 12 && y >= p.y - PASS_H / 2 - 12 && y <= p.y + PASS_H / 2 + 12) return p;
    }
    return null;
  }

  // Tocco su un passante: "fermato" | "errore" | "adottato" | "occupato".
  function bloccoStop(state, p, now) {
    if (state.score.over || now < state.busyUntil) return "occupato";
    const tipo = BY_ID[p.id];
    if (tipo.cat === "irregolare") {
      hit(state.score, 20);
      p.stato = "fermato";
      p.until = now + STOP_S;
      state.viste[p.id] = (state.viste[p.id] || 0) + 1;
      return "fermato";
    }
    if (tipo.cat === "regolare") {
      miss(state.score);
      p.stato = "fermato";
      p.until = now + STOP_S;
      return "errore";
    }
    p.stato = "coccole";
    p.until = now + CUDDLE_S;
    state.busyUntil = now + CUDDLE_S;
    return "adottato";
  }

  // Avanza il tempo: muove i passanti, chiude le coccole, gestisce le uscite. Ritorna gli eventi.
  function bloccoStep(state, dt, now) {
    const eventi = [];
    for (const p of state.passanti) {
      const tipo = BY_ID[p.id];
      if (p.stato === "coccole") {
        if (now >= p.until) {
          p.stato = "adottato";
          if (!state.score.over) state.squadra[tipo.specie] = (state.squadra[tipo.specie] || 0) + 1;
          hit(state.score, 30);
          eventi.push({ tipo: "adottato", p });
        }
        continue;
      }
      if (p.stato !== "cammina") continue;
      p.x += p.vx * dt;
      if (p.x > W) {
        p.stato = "uscito";
        if (tipo.cat === "irregolare") {
          miss(state.score);
          eventi.push({ tipo: "perso", p });
        } else if (tipo.cat === "regolare") {
          if (!state.score.over) state.score.points += 5;
          eventi.push({ tipo: "passato", p });
        }
      }
    }
    // Rimuove chi è uscito o adottato; i fermati restano STOP_S secondi per l'animazione.
    state.passanti = state.passanti.filter((p) => p.stato === "cammina" || p.stato === "coccole" || (p.stato === "fermato" && now < p.until));
    return eventi;
  }

  // ---- Condivisione
  const SPECIE = { gatto: ["gatto", "gatti"], cane: ["cane", "cani"], papera: ["papera", "papere"] };
  const ARTICOLO_UNO = { gatto: "un", cane: "un", papera: "una" };

  function squadraFrase(squadra) {
    const parti = Object.keys(SPECIE)
      .filter((k) => squadra && squadra[k] > 0)
      .map((k) => (squadra[k] === 1 ? ARTICOLO_UNO[k] + " " + SPECIE[k][0] : squadra[k] + " " + SPECIE[k][1]));
    if (!parti.length) return "";
    const elenco = parti.length === 1 ? parti[0] : parti.slice(0, -1).join(", ") + " e " + parti[parti.length - 1];
    return " e ho adottato " + elenco;
  }

  function formatPoints(n) {
    return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  }

  const GIOCHI = { gomitoli: "Gomitoli", blocco: "Posto di blocco" };

  function shareText(gioco, points, squadra) {
    const nome = GIOCHI[gioco] || gioco;
    const prep = gioco === "blocco" ? "al" : "a";
    return "Ho fatto " + formatPoints(points) + (Math.round(points) === 1 ? " punto " : " punti ") + prep + " " + nome + " su LexBot" + squadraFrase(squadra) + ", riesci a battermi?";
  }

  function whatsappUrl(text, url) {
    return "https://wa.me/?text=" + encodeURIComponent(url ? text + " " + url : text);
  }

  const api = {
    W, H, LIVES, CAT, PASSANTI, BY_ID, PASS_W, PASS_H, LANE_Y, CUDDLE_S, STOP_S, GIOCHI,
    rng, createScore, hit, miss, difficulty,
    catSpawn, catMove, catCaught, catStep, catOutcome,
    bloccoState, bloccoSpawn, hitTest, bloccoStop, bloccoStep,
    squadraFrase, formatPoints, shareText, whatsappUrl,
  };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LexGames = api;
})(typeof window !== "undefined" ? window : globalThis);
