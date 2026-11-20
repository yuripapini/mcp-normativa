"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const G = require("../../web/games/core.js");

test("punteggio, moltiplicatore e vite", () => {
  const s = G.createScore();
  for (let i = 0; i < 5; i++) G.hit(s, 10);
  assert.equal(s.points, 50);
  assert.equal(s.mult, 2);
  G.hit(s, 10);
  assert.equal(s.points, 70);
  G.miss(s);
  assert.deepEqual([s.lives, s.mult, s.streak, s.over], [2, 1, 0, false]);
  G.miss(s);
  G.miss(s);
  assert.equal(s.over, true);
  G.hit(s, 10);
  assert.equal(s.points, 70, "a partita finita non si fanno punti");
  const m = G.createScore();
  for (let i = 0; i < 100; i++) G.hit(m, 1);
  assert.equal(m.mult, 5);
});

test("difficoltà cresce e ha un tetto", () => {
  assert.ok(G.difficulty(60).fallSpeed > G.difficulty(0).fallSpeed);
  assert.deepEqual(G.difficulty(120), G.difficulty(999));
  assert.ok(G.difficulty(999).spawnEvery > 0.3 && G.difficulty(999).passEvery > 0.5);
});

test("generatore con seme riproducibile", () => {
  const a = G.rng(42);
  const b = G.rng(42);
  for (let i = 0; i < 5; i++) assert.equal(a(), b());
});

test("gomitoli: presa, caduta, cetriolo", () => {
  const s = G.createScore();
  const yarn = { kind: "yarn", x: 100, y: G.CAT.y, r: 16, vy: 0 };
  assert.equal(G.catStep(100, yarn, 0), "caught");
  G.catOutcome(s, "yarn", "caught");
  assert.equal(s.points, 10);
  const lost = { kind: "yarn", x: 300, y: G.H + 40, r: 16, vy: 0 };
  assert.equal(G.catStep(60, lost, 0), "ground");
  G.catOutcome(s, "yarn", "ground");
  G.catOutcome(s, "cucumber", "caught");
  assert.equal(s.lives, 1);
  G.catOutcome(s, "cucumber", "ground");
  assert.equal(s.lives, 1);
  assert.equal(G.catMove(100, 300, 0.01), 109);
  assert.equal(G.catMove(10, 0, 1), G.CAT.w / 2);
});

function passante(state, id, x, y) {
  const p = { uid: state.nextId++, id, x, y: y || G.LANE_Y[0], vx: 100, stato: "cammina", until: 0 };
  state.passanti.push(p);
  return p;
}

test("blocco: irregolare fermato o perso, regolare fermato o passato", () => {
  const st = G.bloccoState();
  assert.equal(G.bloccoStop(st, passante(st, "auto-cintura", 50), 0), "fermato");
  assert.equal(st.score.points, 20);
  assert.equal(st.viste["auto-cintura"], 1);
  assert.equal(G.bloccoStop(st, passante(st, "auto-ok", 50), 0), "errore");
  assert.equal(st.score.lives, 2);
  passante(st, "auto-telefono", G.W - 1);
  passante(st, "signora-carrello", G.W - 1);
  const ev = G.bloccoStep(st, 0.1, 1).map((e) => e.tipo).sort();
  assert.deepEqual(ev, ["passato", "perso"]);
  assert.equal(st.score.lives, 1);
  assert.equal(st.score.points, 25);
});

test("blocco: adozione con coccole e tocchi ignorati intanto", () => {
  const st = G.bloccoState();
  const gatto = passante(st, "gatto", 50);
  assert.equal(G.bloccoStop(st, gatto, 10), "adottato");
  const ladro = passante(st, "auto-cintura", 100);
  assert.equal(G.bloccoStop(st, ladro, 10.5), "occupato");
  const x0 = ladro.x;
  G.bloccoStep(st, 0.5, 10.5);
  assert.ok(ladro.x > x0, "gli altri continuano a camminare");
  assert.equal(gatto.x, 50, "l'animale resta fermo durante le coccole");
  const ev = G.bloccoStep(st, 0.5, 11);
  assert.deepEqual(ev.map((e) => e.tipo), ["adottato"]);
  assert.deepEqual(st.squadra, { gatto: 1 });
  assert.equal(st.score.points, 30);
  assert.equal(G.bloccoStop(st, ladro, 11), "fermato");
});

test("blocco: animale lasciato passare senza effetti", () => {
  const st = G.bloccoState();
  passante(st, "papera", G.W - 1);
  assert.deepEqual(G.bloccoStep(st, 0.1, 0), []);
  assert.deepEqual([st.score.points, st.score.lives], [0, 3]);
});

test("hit test: vince il passante in primo piano, area ampliata", () => {
  const st = G.bloccoState();
  passante(st, "auto-ok", 100);
  const front = passante(st, "gatto", 110);
  assert.equal(G.hitTest(st, 130, G.LANE_Y[0]), front);
  assert.equal(G.hitTest(st, 100 - 10, G.LANE_Y[0]).id, "auto-ok");
  assert.equal(G.hitTest(st, 5, 5), null);
});

test("spawn: tutti i tipi sono validi", () => {
  const st = G.bloccoState();
  const r = G.rng(7);
  for (let i = 0; i < 200; i++) G.bloccoSpawn(st, r, i);
  const ids = new Set(st.passanti.map((p) => p.id));
  for (const id of ids) assert.ok(G.BY_ID[id]);
  assert.ok(ids.size >= 10);
});

test("testo di condivisione e WhatsApp", () => {
  assert.equal(G.shareText("gomitoli", 1240, null), "Ho fatto 1.240 punti a Gomitoli su LexBot, riesci a battermi?");
  assert.equal(
    G.shareText("blocco", 980, { gatto: 3, papera: 1 }),
    "Ho fatto 980 punti al Posto di blocco su LexBot e ho adottato 3 gatti e una papera, riesci a battermi?",
  );
  assert.equal(G.squadraFrase({ cane: 1, gatto: 2, papera: 2 }), " e ho adottato 2 gatti, un cane e 2 papere");
  assert.equal(G.whatsappUrl("a b", "https://x.it"), "https://wa.me/?text=a%20b%20https%3A%2F%2Fx.it");
  assert.equal(G.whatsappUrl("a b"), "https://wa.me/?text=a%20b");
});

test("articoli del riepilogo: 171-173 hanno una scheda Strada", () => {
  const src = fs.readFileSync(path.join(__dirname, "../../web/strada.js"), "utf8");
  const schede = JSON.parse(/\/\* SCHEDE-INIZIO \*\/([\s\S]*)\/\* SCHEDE-FINE \*\//.exec(src)[1]);
  const arts = new Set(schede.map((s) => s.articolo));
  for (const a of ["171", "172", "173"]) assert.ok(arts.has(a), a);
  for (const p of G.PASSANTI) assert.ok(p.cat !== "irregolare" || p.articolo || p.battuta, p.id);
});

test("blocco: a partita finita niente punti, viste o adozioni; i fermati escono dopo STOP_S", () => {
  const st = G.bloccoState();
  st.score.lives = 1;
  passante(st, "auto-cintura", G.W - 1);
  passante(st, "auto-ok", G.W - 1);
  G.bloccoStep(st, 0.1, 0);
  assert.deepEqual([st.score.points, st.score.lives, st.score.over], [0, 0, true]);
  assert.equal(G.bloccoStop(st, passante(st, "moto-casco", 50), 1), "occupato");
  assert.deepEqual(st.viste, {});

  const st2 = G.bloccoState();
  const f = passante(st2, "auto-cintura", 50);
  G.bloccoStop(st2, f, 0);
  G.bloccoStep(st2, 0.1, G.STOP_S / 2);
  assert.ok(st2.passanti.includes(f));
  G.bloccoStep(st2, 0.1, G.STOP_S);
  assert.ok(!st2.passanti.includes(f));
});

test("condivisione: singolare di punto", () => {
  assert.match(G.shareText("gomitoli", 1), /Ho fatto 1 punto a Gomitoli/);
});

// ---- Interfaccia dei giochi (Task 9): parti senza DOM di cat.js, blocco.js e pausa.js
const Cat = require("../../web/games/cat.js");
const Blocco = require("../../web/games/blocco.js");
const P = require("../../web/games/pausa.js");

function fakeStorage(init) {
  const m = new Map(Object.entries(init || {}));
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), m };
}

test("pausa: chiave, lettura e scrittura del record, anche senza storage", () => {
  assert.equal(P.recordKey("blocco"), "lexbot.record.blocco");
  const st = fakeStorage({ "lexbot.record.gomitoli": "120" });
  assert.equal(P.leggiRecord(st, "gomitoli"), 120);
  assert.equal(P.leggiRecord(st, "blocco"), 0);
  assert.equal(P.leggiRecord(fakeStorage({ "lexbot.record.blocco": "abc" }), "blocco"), 0);
  assert.equal(P.scriviRecord(st, "blocco", 50.4), true);
  assert.equal(st.m.get("lexbot.record.blocco"), "50");
  const rotto = { getItem() { throw new Error("SecurityError"); }, setItem() { throw new Error("QuotaExceeded"); } };
  assert.equal(P.leggiRecord(rotto, "blocco"), null);
  assert.equal(P.scriviRecord(rotto, "blocco", 10), false);
  assert.equal(P.leggiRecord(null, "blocco"), null);
});

test("pausa: esito del record", () => {
  assert.deepEqual(P.esitoRecord(null, 500), { record: null, nuovo: false });
  assert.deepEqual(P.esitoRecord(0, 0), { record: 0, nuovo: false });
  assert.deepEqual(P.esitoRecord(0, 30), { record: 30, nuovo: true });
  assert.deepEqual(P.esitoRecord(100, 30), { record: 100, nuovo: false });
  assert.deepEqual(P.esitoRecord(100, 100), { record: 100, nuovo: false });
});

test("pausa: vite, squadra e infrazioni del riepilogo", () => {
  assert.equal(P.viteTesto(3), "●●●");
  assert.equal(P.viteTesto(1), "●○○");
  assert.equal(P.viteTesto(-1), "○○○");
  assert.equal(P.squadraTesto({}), "");
  assert.equal(P.squadraTesto({ gatto: 3, papera: 1 }), "Squadra adottata: 3 gatti e una papera");
  const righe = P.infrazioni({ "auto-fanale": 1, "gatto-ladro": 2, "moto-casco": 1, "auto-ok": 0 }, ["171", "172", "173"]);
  assert.deepEqual(righe.map((r) => r.id), ["moto-casco", "auto-fanale", "gatto-ladro"]);
  assert.deepEqual(righe[0], { id: "moto-casco", label: "Senza casco", volte: 1, articolo: "171", link: true, battuta: null });
  assert.equal(righe[1].link, false);
  assert.equal(righe[1].articolo, "152");
  assert.equal(righe[2].articolo, null);
  assert.equal(righe[2].volte, 2);
  assert.match(righe[2].battuta, /gomitoli/);
  assert.deepEqual(P.infrazioni({}, []), []);
});

test("pausa: misure del canvas con devicePixelRatio", () => {
  const a = P.layoutCanvas(358, 844, 3);
  assert.equal(a.cssH, Math.round((358 * G.H) / G.W));
  assert.ok(Math.abs(a.scale - 358 / G.W) < 1e-9);
  assert.equal(a.offX, 0);
  assert.deepEqual([a.bw, a.bh], [1074, a.cssH * 3]);
  const b = P.layoutCanvas(358, 500, 2); // finestra bassa: campo intero, centrato in orizzontale
  assert.equal(b.cssH, 350);
  assert.ok(G.H * b.scale <= b.cssH + 1e-9 && G.W * b.scale <= 358 + 1e-9);
  assert.ok(b.offX > 0);
});

test("gomitoli: il gatto segue il dito e prende i gomitoli", () => {
  assert.equal(Cat.id, "gomitoli");
  const g = Cat.create(G.rng(1));
  g.pointerDown(300, 400, 0);
  let now = 0;
  for (let i = 0; i < 20; i++) g.update(0.05, (now += 0.05));
  assert.ok(g.catX > G.W / 2);
  // pilota automatico: il gatto va sotto il gomitolo più basso
  for (let i = 0; i < 400 && !g.score.over; i++) {
    const y = g.objects.filter((o) => o.kind === "yarn").sort((a, b) => b.y - a.y)[0];
    if (y) g.pointerMove(y.x, 500);
    g.update(0.05, (now += 0.05));
  }
  assert.ok(g.presi > 5, "gomitoli presi: " + g.presi);
  assert.equal(g.score.points >= g.presi * 10, true);
  assert.deepEqual(g.summary().righe, ["Gomitoli presi: " + g.presi]);
});

test("gomitoli: senza muoversi la partita finisce e si ferma", () => {
  const g = Cat.create(G.rng(2));
  let now = 0;
  for (let i = 0; i < 2000 && !g.score.over; i++) g.update(0.05, (now += 0.05));
  assert.equal(g.score.over, true);
  const n = g.objects.length;
  g.update(0.05, now + 0.05);
  assert.equal(g.objects.length, n);
});

test("blocco: etichette, icone della squadra e righe dell'etichetta", () => {
  assert.equal(Blocco.labelVisibile(0), true);
  assert.equal(Blocco.labelVisibile(19.9), true);
  assert.equal(Blocco.labelVisibile(20), false);
  const lista = Array(13).fill("gatto");
  assert.deepEqual(Blocco.squadraIcone(lista), { icone: lista.slice(0, 10), extra: 3 });
  assert.deepEqual(Blocco.squadraIcone(["cane"]), { icone: ["cane"], extra: 0 });
  const misura = (s) => s.length * 8;
  assert.deepEqual(Blocco.righeEtichetta("Papera in moto senza casco", misura, 100), ["Papera in", "moto senza", "casco"]);
  assert.deepEqual(Blocco.righeEtichetta("Gatto", misura, 100), ["Gatto"]);
});

test("blocco: tocchi, adozioni e riepilogo", () => {
  const g = Blocco.create(G.rng(3));
  assert.equal(Blocco.id, "blocco");
  const st = g.state;
  const metti = (id, x) => {
    const p = { uid: st.nextId++, id, x, y: G.LANE_Y[0], vx: 0, stato: "cammina", until: 0 };
    st.passanti.push(p);
    return p;
  };
  st.passanti = [];
  metti("auto-cintura", 100);
  assert.equal(g.pointerDown(132, G.LANE_Y[0], 1), "fermato");
  assert.equal(g.fermati, 1);
  assert.equal(g.pointerDown(5, 20, 1), null);
  metti("gatto", 200);
  assert.equal(g.pointerDown(232, G.LANE_Y[0], 2), "adottato");
  metti("cane", 10);
  assert.equal(g.pointerDown(42, G.LANE_Y[0], 2.5), "occupato");
  g.update(0.01, 2 + G.CUDDLE_S);
  assert.deepEqual(g.adottati, ["gatto"]);
  const s = g.summary();
  assert.deepEqual(s.squadra, { gatto: 1 });
  assert.deepEqual(s.viste, { "auto-cintura": 1 });
  assert.deepEqual(s.righe, ["Irregolari fermati: 1"]);
});

test("blocco: partita lasciata andare finisce, a partita finita niente tocchi", () => {
  const g = Blocco.create(G.rng(4));
  let now = 0;
  for (let i = 0; i < 6000 && !g.score.over; i++) g.update(0.05, (now += 0.05));
  assert.equal(g.score.over, true);
  assert.equal(g.pointerDown(100, G.LANE_Y[0], now), null);
  assert.deepEqual(g.adottati, []);
});

test("pausa: condivisione nativa, annullata, fallita o assente", async () => {
  const aperti = [];
  const apri = (u) => aperti.push(u);
  const err = (name) => Object.assign(new Error(name), { name });
  let dati = null;
  assert.equal(await P.condividiCon({ share: (d) => ((dati = d), Promise.resolve()) }, apri, "T", "U"), "share");
  assert.deepEqual(dati, { text: "T", url: "U" });
  assert.equal(await P.condividiCon({ share: () => Promise.reject(err("AbortError")) }, apri, "T", "U"), "annullata");
  assert.equal(aperti.length, 0);
  assert.equal(await P.condividiCon({ share: () => Promise.reject(err("NotAllowedError")) }, apri, "T", "U"), "whatsapp");
  assert.equal(await P.condividiCon({ share() { throw err("TypeError"); } }, apri, "T", "U"), "whatsapp");
  assert.equal(await P.condividiCon({}, apri, "T", "U"), "whatsapp");
  assert.equal(await P.condividiCon(null, apri, "T", "U"), "whatsapp");
  assert.equal(aperti.length, 4);
  assert.equal(aperti[0], G.whatsappUrl("T", "U"));
});

// Contesto canvas finto: registra le chiamate e rifiuta coordinate non finite.
function fakeCtx() {
  const ctx = { ops: 0, globalAlpha: 1 };
  return new Proxy(ctx, {
    get(t, k) {
      if (k in t) return t[k];
      if (k === "measureText") return (s) => ({ width: String(s).length * 8 });
      return (...args) => {
        t.ops += 1;
        for (const a of args) if (typeof a === "number" && !Number.isFinite(a)) throw new Error("valore non finito in " + String(k));
      };
    },
    set(t, k, v) {
      t[k] = v;
      return true;
    },
  });
}

function fakeTheme(dark) {
  return { dark, surface: "#fff", surface2: "#eee", text: "#111", muted: "#666", border: "#ddd", accent: "#2563eb", ok: "#070", warn: "#b45309", bad: "#b91c1c", font: "sans-serif" };
}

test("disegno: tutti i passanti in ogni stato e il gatto, tema chiaro e scuro", () => {
  for (const dark of [false, true]) {
    const theme = fakeTheme(dark);
    const g = Blocco.create(G.rng(9));
    g.update(0.01, 0.01);
    g.state.passanti = [];
    let uid = 1;
    for (const p of G.PASSANTI) {
      for (const stato of ["cammina", "fermato", "coccole"]) {
        g.state.passanti.push({ uid: uid++, id: p.id, x: 100, y: G.LANE_Y[uid % 2], vx: 50, stato, until: 1 });
      }
    }
    g.adottati = Array.from({ length: 12 }, (_, i) => ["gatto", "cane", "papera"][i % 3]);
    const ctx = fakeCtx();
    g.draw(ctx, theme, 1);
    assert.ok(ctx.ops > 1000);
    const c = Cat.create(G.rng(1));
    let now = 0;
    for (let i = 0; i < 300; i++) c.update(0.016, (now += 0.016));
    const ctx2 = fakeCtx();
    c.draw(ctx2, theme, 1);
    assert.ok(ctx2.ops > 50);
  }
});
