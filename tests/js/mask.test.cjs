"use strict";
// Esecuzione: node --test tests/js/*.test.cjs
const test = require("node:test");
const assert = require("node:assert/strict");
const { mask, unmask, summary } = require("../../web/mask.js");

test("targhe auto e moto, anche minuscole", () => {
  const r = mask("Fermato AB123CD, poi ab123cd e AB 123 CD; moto XY12345.");
  assert.equal(r.masked, "Fermato [TARGA_1], poi [TARGA_1] e [TARGA_1]; moto [TARGA_2].");
  assert.equal(r.counts.TARGA, 2);
});

test("codice fiscale, IBAN, email, telefoni", () => {
  const r = mask("CF RSSMRA85T10A562S iban IT60 X054 2811 1010 0000 0123 456 mail a.b@x.it tel +39 333 1234567 o 06 12345678");
  assert.equal(r.masked, "CF [CF_1] iban [IBAN_1] mail [EMAIL_1] tel [TEL_1] o [TEL_2]");
});

test("nessun falso positivo su norme, date e orari", () => {
  const t = "art. 186 comma 2 del d.lgs. 285/1992, il 30/04/1992 alle 10:30, comma 2 bis, il 186 bi";
  assert.equal(mask(t).masked, t);
});

test("telefono con barra e stesso valore in formati diversi", () => {
  const r = mask("tel 06/12345678, 03/04/2020, 285/1992, 333 123 4567 e 3331234567");
  assert.equal(r.masked, "tel [TEL_1], 03/04/2020, 285/1992, [TEL_2] e [TEL_2]");
});

test("round trip e escape HTML", () => {
  const original = "Targa AB123CD, CF RSSMRA85T10A562S, mail a.b@x.it";
  const r = mask(original);
  assert.equal(unmask(r.masked, r.map), original);
  const v = mask("x AB123CD");
  assert.equal(unmask("<b>[TARGA_1]</b>", v.map, { escape: true }), "<b>AB123CD</b>");
  assert.equal(unmask("[TARGA_1]", { "[TARGA_1]": "<i>" }, { escape: true }), "&lt;i&gt;");
});

test("riepilogo", () => {
  assert.equal(summary({ TARGA: 2, CF: 1 }), "Mascherati: 2 targhe, 1 codice fiscale");
  assert.equal(summary({}), "");
});

test("targhe moto: niente falsi positivi con spazio minuscolo", () => {
  for (const t of ["il 10000 euro", "da 12345", "km 12345", "AS 12345 no"]) {
    if (t.startsWith("AS")) continue;
    assert.equal(mask(t).masked, t);
  }
  assert.equal(mask("km12345").masked, "[TARGA_1]"); // lato sicuro
  assert.equal(mask("moto AS 12345").masked, "moto [TARGA_1]");
});

test("date non sono telefoni", () => {
  for (const t of ["dal 01.01.2024", "il 05.06.2023", "03-04-2020", "del 01 02 2024"]) {
    assert.equal(mask(t).masked, t);
  }
});

test("telefoni: prefissi e separatori", () => {
  const cases = [
    ["0039 333 1234567", "[TEL_1]"],
    ["0039 06 12345678", "[TEL_1]"],
    ["tel.3331234567", "tel.[TEL_1]"],
    ["cell:3331234567", "cell:[TEL_1]"],
    ["+39-333-1234567 ok", "[TEL_1] ok"],
    ["+39 06/12345678", "[TEL_1]"],
    ["(06) 12345678", "[TEL_1]"],
    ["Tel (06) 12345678.", "Tel [TEL_1]."],
  ];
  for (const [i, o] of cases) assert.equal(mask(i).masked, o, i);
});

test("unmask tollera segnaposto alterati", () => {
  const map = { "[TARGA_1]": "AB123CD" };
  for (const t of ["[targa_1]", "[ TARGA_1 ]", "[TARGA 1]", "\\[TARGA\\_1\\]"]) {
    assert.equal(unmask(t, map), "AB123CD", t);
  }
  assert.equal(unmask("[TARGA_2] [FOO_1]", map), "[TARGA_2] [FOO_1]");
});

test("email: nessun backtracking quadratico", () => {
  const inputs = ["a".repeat(100000), "a.".repeat(50000), "a@" + "a.".repeat(50000), "a@a".repeat(30000)];
  for (const s of inputs) {
    const t0 = Date.now();
    mask(s);
    assert.ok(Date.now() - t0 < 500, "troppo lento");
  }
});

test("sorgente senza lookbehind", () => {
  const src = require("node:fs").readFileSync(require("node:path").join(__dirname, "../../web/mask.js"), "utf8");
  assert.ok(!src.includes("(?<"));
});
