"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { scan, replace } = require("../../web/guard.js");
const { unmask } = require("../../web/mask.js");

const kinds = (t, o) => scan(t, o).map((f) => f.kind + ":" + f.value);

test("nomi propri da elenco, ordine inverso, titoli e maiuscolo", () => {
  assert.deepEqual(kinds("Ha denunciato Mario Rossi ieri"), ["PERSONA:Mario Rossi"]);
  assert.deepEqual(kinds("presente Rossi Mario, nato"), ["PERSONA:Rossi Mario"]);
  assert.deepEqual(kinds("la sig.ra Bianchi riferisce"), ["PERSONA:sig.ra Bianchi"]);
  assert.deepEqual(kinds("indagato ROSSI MARIO"), ["PERSONA:ROSSI MARIO"]);
  assert.deepEqual(kinds("Maria De Luca ha visto"), ["PERSONA:Maria De Luca"]);
});

test("nessun falso positivo su toponimi, sigle, norme e segnaposto", () => {
  assert.deepEqual(kinds("in via Giuseppe Verdi senza civico"), []);
  assert.deepEqual(kinds("BOZZA VERBALE DENUNCIA alla PROCURA REPUBBLICA"), []);
  assert.deepEqual(kinds("art. 186 comma 2 del d.lgs. 285/1992, il 30/04/1992"), []);
  assert.deepEqual(kinds("[DENUNCIANTE] riferisce che [INDAGATO] in [INDIRIZZO_1]"), []);
  assert.deepEqual(kinds("Il giorno 12/03/2024 alle ore 10:30"), []);
});

test("data di nascita e indirizzo con civico", () => {
  assert.deepEqual(kinds("nato a Roma il 12/03/1980"), ["NASCITA:12/03/1980"]);
  assert.deepEqual(kinds("nata il 3 maggio 1975"), ["NASCITA:3 maggio 1975"]);
  assert.deepEqual(kinds("residente in via Giuseppe Verdi 12"), ["INDIRIZZO:via Giuseppe Verdi 12"]);
  assert.deepEqual(kinds("piazza Duomo, n. 3/A"), ["INDIRIZZO:piazza Duomo, n. 3"]);
});

test("dati di mask.js bloccati", () => {
  const k = kinds("CF RSSMRA85T10A562S targa AB123CD tel 333 1234567 mail a.b@x.it");
  assert.deepEqual(k, ["CF:RSSMRA85T10A562S", "TARGA:AB123CD", "TEL:333 1234567", "EMAIL:a.b@x.it"]);
});

test("ignore e ordinamento", () => {
  assert.deepEqual(kinds("Mario Rossi e via Roma 1", { ignore: ["mario  rossi"] }), ["INDIRIZZO:via Roma 1"]);
  const f = scan("via Roma 1, poi Mario Rossi");
  assert.ok(f[0].start < f[1].start);
});

test("sostituzione di tutte le occorrenze e ripristino", () => {
  const map = {};
  let text = "Mario Rossi riferisce. Mario Rossi abita in via Roma 1.";
  for (;;) {
    const f = scan(text)[0];
    if (!f) break;
    text = replace(text, f, map).text;
  }
  assert.equal(text, "[PERSONA_1] riferisce. [PERSONA_1] abita in [INDIRIZZO_1].");
  assert.equal(unmask(text, map), "Mario Rossi riferisce. Mario Rossi abita in via Roma 1.");
});

// ---- Casi aggiuntivi dalla revisione (falsi positivi su testi di verbale, falsi negativi, convergenza)

test("revisione: nessun falso positivo su intestazioni, cariche, toponimi e usi comuni", () => {
  for (const t of [
    "Al Signor Procuratore della Repubblica presso il Tribunale di Roma",
    "Lo stesso dichiarava: Signor Giudice, non ero presente.",
    "VERBALE DI SOMMARIE INFORMAZIONI TESTIMONIALI",
    "VERBALE DI PERQUISIZIONE PERSONALE E SEQUESTRO",
    "STAZIONE CARABINIERI ROMA PRATI",
    "POLIZIA GIUDIZIARIA, PUBBLICO MINISTERO",
    "Tribunale di Santa Maria Capua Vetere",
    "Comando Stazione Carabinieri di San Marco Argentano",
    "a Porto San Giorgio, il giorno di Santo Stefano",
    "trasportato al Policlinico Umberto I, poi all'Aeroporto Leonardo da Vinci",
    "a Vittorio Veneto e a Martina Franca",
    "Domenica Maria è uscita. Oggi Andrea e Luca hanno",
    "la Casa Bianca e la Stella Polare",
    "in via precauzionale veniva sottoposto a 2 accertamenti",
    "per via delle 3 ferite riportate",
    "nel Corso Della notte 2 persone",
    "durante la lite è nata una discussione il 12/03/2024",
    "andrea riferiva che luca aveva visto tutto",
    "il dott. di turno e la sig.ra non era presente",
  ]) {
    assert.deepEqual(kinds(t), [], t);
  }
});

test("revisione: paragrafo di denuncia anonimizzato", () => {
  const t =
    "In data 12 marzo 2024 alle ore 18.30 circa [DENUNCIANTE], nato a [LUOGO] il [DATA_NASCITA], si " +
    "presentava presso il Comando Stazione Carabinieri di Roma Prati e riferiva che in data 10 marzo 2024, " +
    "mentre si trovava in via [VIA], veniva avvicinato da [INDAGATO] il quale gli intimava di consegnare il " +
    "portafoglio. I fatti sono riconducibili all'art. 628 c.p.; si procedeva ai sensi dell'art. 352 c.p.p. " +
    "a perquisizione personale con esito positivo e al sequestro ai sensi dell'art. 354 c.p.p. La " +
    "comunicazione veniva trasmessa alla Procura della Repubblica presso il Tribunale di Roma, pm di turno " +
    "dott.ssa [PM], nel corso della notte. Proc. pen. n. 1234/2024 RGNR, sentenza n. 56/2023 sez. II.";
  assert.deepEqual(kinds(t), []);
});

test("revisione: nomi con particelle, accenti, minuscolo, titoli e gradi", () => {
  assert.deepEqual(kinds("De Luca Maria riferisce"), ["PERSONA:De Luca Maria"]);
  assert.deepEqual(kinds("Giovanni Paolo De Luca"), ["PERSONA:Giovanni Paolo De Luca"]);
  assert.deepEqual(kinds("D'Angelo Mario e D'AMICO LUCA"), ["PERSONA:D'Angelo Mario", "PERSONA:D'AMICO LUCA"]);
  assert.deepEqual(kinds("NICOLÒ ROSSI veniva identificato"), ["PERSONA:NICOLÒ ROSSI"]);
  assert.deepEqual(kinds("BIANCHI MARIA ROSA ANNA"), ["PERSONA:BIANCHI MARIA ROSA ANNA"]);
  assert.deepEqual(kinds("POPESCU IONUT"), ["PERSONA:POPESCU IONUT"]);
  assert.deepEqual(kinds("ho fermato mario rossi davanti al bar"), ["PERSONA:mario rossi"]);
  assert.deepEqual(kinds("giuseppe de luca"), ["PERSONA:giuseppe de luca"]);
  assert.deepEqual(kinds("il sig. rossi riferiva"), ["PERSONA:sig. rossi"]);
  assert.deepEqual(kinds("il Mar. Rossi e l'App. Bianchi"), ["PERSONA:Mar. Rossi", "PERSONA:App. Bianchi"]);
  assert.deepEqual(kinds("al prof. Verdi e all'ing. Neri"), ["PERSONA:prof. Verdi", "PERSONA:ing. Neri"]);
});

test("revisione: data di nascita e indirizzi", () => {
  assert.deepEqual(kinds("nato a Casablanca (Marocco) il giorno 01/01/1990"), ["NASCITA:01/01/1990"]);
  assert.deepEqual(kinds("data di nascita: 12/03/1980"), ["NASCITA:12/03/1980"]);
  assert.deepEqual(kinds("n. a Roma il 12/03/1980"), ["NASCITA:12/03/1980"]);
  assert.deepEqual(kinds("residente in via Roma 12bis"), ["INDIRIZZO:via Roma 12bis"]);
  assert.deepEqual(kinds("residente in via 4 Novembre 12"), ["INDIRIZZO:via 4 Novembre 12"]);
});

test("revisione: 'Sostituisci tutti' converge anche con valori attaccati ad altri caratteri", () => {
  for (const src of ["MariaGrazia Bianchi riferiva", "3Mario Rossi riferiva", "x_Mario Rossi e Mario Rossi"]) {
    const map = {};
    let text = src;
    let giri = 0;
    for (;;) {
      const f = scan(text)[0];
      if (!f) break;
      assert.ok(++giri < 10, "nessuna convergenza: " + src);
      text = replace(text, f, map).text;
    }
    assert.match(text, /\[PERSONA_1\]/);
    assert.equal(unmask(text, map).replace(/\s+/g, " "), src);
  }
});

test("prepare: blocca se scan trova dati, senza modificare il testo", () => {
  const src = "Mario Rossi nato il 12/03/1980";
  const r = require("../../web/guard.js").prepare(src, {}, []);
  assert.equal(r.text, src);
  assert.equal(r.found.length, 2);
});

test("prepare: telefono ignorato e telefono sostituito condividono la numerazione", () => {
  const { prepare } = require("../../web/guard.js");
  const src = "Chiamare 333 1234567 oppure 06/12345678 per il fatto";
  const map = {};
  const t1 = scan(src)[0];
  assert.equal(t1.kind, "TEL");
  const dopo = replace(src, t1, map).text;
  assert.match(dopo, /\[TEL_1\]/);
  // il secondo telefono e' segnalato "Non e' un dato personale"
  const r = prepare(dopo, map, ["06/12345678"]);
  assert.deepEqual(r.found, []);
  assert.match(r.text, /\[TEL_1\].*\[TEL_2\]/);
  assert.ok(!/\d{6}/.test(r.text));
  assert.equal(unmask(r.text, map), src);
});

test("revisione T5: segnaposto già scritti nel testo non vengono riusati per un'altra persona", () => {
  const map = {};
  let text = "[PERSONA_1] riferisce che Mario Rossi lo ha colpito";
  const f = scan(text)[0];
  text = replace(text, f, map).text;
  assert.equal(text, "[PERSONA_1] riferisce che [PERSONA_2] lo ha colpito");
  assert.equal(unmask(text, map), "[PERSONA_1] riferisce che Mario Rossi lo ha colpito");
  // anche per i dati di mask.js e con segnaposto scritti in forma alterata
  const { prepare } = require("../../web/guard.js");
  const m2 = {};
  const r = prepare("Chiamato da [tel 1]: 333 1234567", m2, ["333 1234567"]);
  assert.equal(r.text, "Chiamato da [tel 1]: [TEL_2]");
  assert.deepEqual(m2, { "[TEL_2]": "333 1234567" });
});

test("revisione T5: mappa conservata con segnaposto nel campo (cambio tipo) e nuova persona", () => {
  // simula initScrivi: la mappa non si azzera al cambio tipo, il testo contiene già [PERSONA_1]
  const map = {};
  let text = "Mario Rossi riferisce";
  text = replace(text, scan(text)[0], map).text;
  text += " che Luca Bianchi lo ha colpito";
  text = replace(text, scan(text)[0], map).text;
  assert.equal(text, "[PERSONA_1] riferisce che [PERSONA_2] lo ha colpito");
  assert.equal(unmask(text, map), "Mario Rossi riferisce che Luca Bianchi lo ha colpito");
  // anche con mappa azzerata (prefill) la numerazione riparte dopo i segnaposto presenti
  const vuota = {};
  const t2 = replace("[PERSONA_1] e Luca Bianchi", scan("[PERSONA_1] e Luca Bianchi")[0], vuota).text;
  assert.equal(t2, "[PERSONA_1] e [PERSONA_2]");
});

test("revisione T5: solo i segnaposto veri sono esenti, non il testo libero fra quadre", () => {
  assert.deepEqual(kinds("[DENUNCIANTE Mario Rossi] residente [via Roma 12]"), [
    "PERSONA:Mario Rossi",
    "INDIRIZZO:via Roma 12",
  ]);
  assert.deepEqual(kinds("nato il [12/03/1980]"), ["NASCITA:12/03/1980"]);
  assert.deepEqual(kinds("[DA COMPLETARE] [NOME VIA] [PERSONA_1] [INDIRIZZO_2]"), []);
});

test("revisione T5: un falso allarme ignorato non fa emergere i suoi frammenti", () => {
  assert.deepEqual(kinds("Rossi Mario tel 333 1234567", { ignore: ["Rossi Mario"] }), ["TEL:333 1234567"]);
  assert.deepEqual(kinds("ho visto mario tel 333 1234567"), ["TEL:333 1234567"]);
});

test("revisione T5: prepare resta bloccato se restano dati di mask.js oltre il limite dei giri", () => {
  const { prepare } = require("../../web/guard.js");
  const tel = [];
  for (let i = 0; i < 230; i++) tel.push("33" + String(10000000 + i * 37).padStart(8, "0"));
  const src = tel.join(" ");
  const r = prepare(src, {}, tel);
  assert.ok(r.found.length > 0);
  assert.equal(r.text, src);
});
