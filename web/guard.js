"use strict";
// Rilevamento di dati personali nel testo prima dell'invio al server (modelli di polizia giudiziaria).
// Modulo puro, UMD come mask.js: in Node module.exports, nel browser window.LexGuard.
// Niente lookbehind nelle regex (Safari < 16.4): il contesto precedente è un gruppo catturato.

(function (root) {
  const Mask =
    typeof module === "object" && module.exports && typeof require === "function"
      ? require("./mask.js")
      : root.LexMask;

  const LABELS = {
    PERSONA: "nome",
    NASCITA: "data di nascita",
    INDIRIZZO: "indirizzo",
    CF: "codice fiscale",
    TARGA: "targa",
    TEL: "telefono",
    EMAIL: "email",
    IBAN: "IBAN",
  };

  const lista = (s) => s.split(/\s+/).filter(Boolean);

  // Nomi propri frequenti in Italia (minuscolo, senza accenti). Esclusi i nomi che sono anche parole
  // comuni con l'iniziale maiuscola in toponimi o feste (Santo, Natale, Stella, Bianca, Vera...).
  const NOMI = new Set(
    lista(
      // maschili italiani
      "mario luigi giuseppe giovanni antonio francesco marco andrea luca paolo alessandro roberto stefano " +
        "angelo vincenzo salvatore pietro carlo massimo fabio davide simone matteo lorenzo riccardo giorgio " +
        "claudio daniele michele nicola nicolo niccolo enrico sergio bruno franco renato maurizio gianni " +
        "giancarlo gianluca emanuele federico fabrizio domenico antonino gaetano rocco vittorio umberto ugo " +
        "aldo alberto alfredo armando arturo augusto benedetto bernardo carmine cesare ciro cristian " +
        "cristiano damiano dario diego dino edoardo elia elio emilio ennio enzo ettore eugenio fausto felice " +
        "filippo flavio fulvio gabriele gennaro gerardo gianfranco gianmarco gianpaolo giampaolo giampiero " +
        "gino gioacchino giacomo giulio graziano guido ignazio igor ivan jacopo leonardo lino livio loris " +
        "luciano ludovico manuel mattia mauro michelangelo mirko nando nazario nello nino nunzio orazio " +
        "oreste oscar osvaldo pasquale patrizio piero pierluigi pierpaolo pierfrancesco raffaele raimondo " +
        "remo rinaldo rodolfo romeo ruggero samuele sandro saverio sebastiano silvano silvio tiziano " +
        "tommaso tonino tullio valentino valerio walter " +
        // femminili italiane
        "maria anna giulia francesca sara laura chiara elena martina alessia valentina federica silvia " +
        "paola roberta elisa simona monica daniela cristina barbara patrizia stefania giovanna angela " +
        "rosa teresa lucia carla carmela concetta filomena antonella raffaella serena veronica ilaria " +
        "alice giorgia beatrice emma sofia aurora ginevra camilla greta arianna benedetta claudia michela " +
        "manuela marina marta nadia nicoletta rita rossella sabrina sandra tiziana viviana vittoria " +
        "adriana agnese alessandra alida amalia anita annamaria antonietta assunta brigida caterina " +
        "cecilia cinzia clara clelia consuelo debora diana dora edith eleonora elisabetta emanuela erika " +
        "eva ester fabiana fabiola fiorella flavia franca gabriella gemma grazia ida ines irene isabella " +
        "lara lea liliana lisa loredana lorena luana luisa margherita mariangela mariagrazia mariarosa " +
        "mariella marisa mirella miriam morena nicole noemi olga ornella paolina pierina renata romina " +
        "rosalba rosaria rosetta sonia susanna tania tatiana teodora ursula vanessa wanda yvonne zaira " +
        // stranieri frequenti in Italia
        "mohamed mohammed mohammad muhammad ahmed ahmad ali omar youssef youness yassine ayoub mehdi adil " +
        "aziz hamid mourad karim hassan hussein ibrahim mustafa khaled said samir tarek nabil rachid abdel " +
        "abdul abdullah bilal hamza imran fatima aisha khadija amina samira leila yasmine salma mariam " +
        "hanane rachida zineb " +
        "ion ionut vasile gheorghe nicolae florin marian marius costel catalin dorin andrei adrian bogdan " +
        "alexandru mihai cosmin razvan stefan sorin ciprian ovidiu valentin " +
        "ana ioana mihaela nicoleta gabriela alina oana " +
        "ardit arben besnik erion klodian elton fatjon gentian ervin " +
        "ivana dragan milan goran zoran branko vladimir sergei oleg viktor dmitri aleksandr " +
        "olena oksana natalia svetlana tetiana irina galina " +
        "jose juan carlos miguel pedro luis jorge pablo jesus javier carmen rosario ahmet mehmet emir " +
        "kevin jonathan michael john david james robert thomas peter daniel christian jennifer jessica " +
        "kwame kofi emmanuel godwin blessing chinedu ousmane moussa mamadou abdoulaye ibrahima cheikh " +
        "modou babacar aliou gurpreet harpreet rajesh " +
        "agnieszka katarzyna piotr krzysztof tomasz marek pawel",
    ),
  );

  // Nomi che in minuscolo sono anche parole comuni ("rosa", "chiara", "massimo", "salma"...):
  // esclusi dalla regola dei nomi scritti in minuscolo.
  const AMBIGUI = new Set(
    lista(
      "rosa marina franco franca bruno chiara serena massimo vittoria assunta pasquale angelo angela sara " +
        "lara lisa gemma aurora diana fausto benedetto benedetta carmine rosario milan oscar blessing " +
        "salvatore felice salma dora ginevra margherita barbara guido nello cristiano armando lino remo " +
        "dino gino enzo nando nino augusto grazia sofia elio ugo ida eva lea ali said rita carmen emir ion ana",
    ),
  );

  const SIGLE = new Set(
    lista(
      "BOZZA OGGETTO VERBALE DENUNCIA QUERELA PROCURA REPUBBLICA TRIBUNALE DPR CDS ANAS INPS ASL COMUNE " +
        "STAZIONE COMANDO NUCLEO COMPAGNIA PG CNR SIT",
    ),
  );

  // Particelle dei cognomi (De Luca, D'Angelo, Ben Ali): uniscono le parole ma non contano nel limite.
  const PARTICELLE = new Set(
    lista("de di del della dello dei degli delle da dal dalla lo la li le d' van von der den ben bin el al abu"),
  );

  // Parole dopo le quali un nome indica un luogo (via Giuseppe Verdi, San Marco, Ospedale Santa Maria).
  const TOPONIMI = new Set(
    lista(
      "via viale piazza piazzale corso vicolo largo localita loc. contrada scuola istituto ospedale stadio " +
        "san santo santa sant' porto galleria policlinico aeroporto stazione tribunale chiesa parrocchia " +
        "clinica caserma ponte borgo lido monte villa frazione rione quartiere parco teatro museo",
    ),
  );

  // Luoghi noti che iniziano con un nome proprio ("Vittorio Veneto", "Martina Franca").
  const LUOGHI = new Set(["vittorio veneto", "martina franca", "diano marina", "marina di pisa", "andrea doria"]);

  const GIORNI = "lunedi martedi mercoledi giovedi venerdi sabato domenica";
  const MESI = "gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre";

  // Prime parole che non possono essere un cognome nell'ordine inverso ("Rossi Mario").
  const NON_COGNOMI = new Set(
    lista(
      GIORNI +
        " " +
        MESI.replace(/\|/g, " ") +
        " il lo la le gli un una uno ieri oggi domani poi quindi allora anche mentre dopo prima quando " +
        "successivamente inoltre infine ma che con per tra fra nel sul ecco cosi presso verso secondo " +
        "signor signora signorina",
    ),
  );

  // Cariche dopo un titolo ("Signor Procuratore"): non sono nomi di persona.
  const CARICHE = new Set(
    lista(
      "procuratore procuratrice giudice presidente sindaco prefetto questore comandante ministro pubblico " +
        "magistrato direttore direttrice dirigente responsabile ufficiale agente maresciallo brigadiere " +
        "appuntato carabiniere avvocato dottore dottoressa medico vicario capitano tenente colonnello " +
        "generale commissario ispettore sovrintendente assistente sostituto gip gup pm",
    ),
  );

  // Parole funzionali, verbi e nomi comuni che seguono spesso un nome scritto in minuscolo
  // ("mario riferiva", "luca non", "anna presso"): non sono cognomi.
  const STOP = new Set(
    lista(
      // preposizioni, articoli, pronomi, congiunzioni, avverbi
      "del della dello dei degli delle dal dalla dallo dai dagli dalle nel nella nello nei negli nelle " +
        "sul sulla sullo sui sugli sulle all alla allo agli alle col con per tra fra che chi cui non una " +
        "uno gli suo sua suoi sue loro mio mia miei mie tuo tua lui lei noi voi essi esse egli ella esso " +
        "essa anche ancora poi quindi allora mentre dopo prima quando dove come perche cosi gia sempre " +
        "mai solo soltanto molto poco tutto tutti tutta tutte questo questa questi queste quello quella " +
        "quelli quelle stesso stessa stessi stesse altro altra altri altre nessuno qualcuno ognuno " +
        "ciascuno senza sopra sotto dentro fuori verso presso contro oltre circa ieri oggi domani ora " +
        "ore giorno sera notte mattina pomeriggio insieme invece inoltre infine pure neanche nemmeno " +
        "neppure oppure ovvero ossia cioe appena subito spesso bene male piu meno tanto troppo assai qui " +
        "qua durante tramite mediante secondo lungo attraverso dietro davanti accanto vicino lontano " +
        "nonche affinche poiche siccome benche sebbene pertanto dunque comunque tuttavia pero infatti " +
        "eppure ecc etc " +
        // verbi frequenti nei racconti dei fatti
        "sono sei era eri erano ero sta sto stai stanno stava stavano stato stata stati state aveva " +
        "avevo avevano avere essere hanno viene vengono venne vado fatto detto dice disse dichiara " +
        "riferisce afferma aggiunge precisa conferma nega abita lavora racconta denuncia chiede vede " +
        "prende esce entra torna arriva parla guarda chiama porta vive risiede conosce frequenta colpisce " +
        "minaccia insulta picchia aggredisce ruba sottrae spinge urla grida scappa fugge rientra rimane " +
        "resta possiede guida conduce telefona scrive invia riceve mostra consegna ammette ricorda spiega " +
        "sostiene querela presenta segnala nota osserva sente vuole deve puo tiene mette lascia trova " +
        "cerca perde paga compra vende prova chiude apre rompe danneggia " +
        // nomi comuni di contesto
        "presente assente nato nata residente domiciliato domiciliata identificato identificata indagato " +
        "indagata denunciante querelante persona persone padre madre figlio figlia fratello sorella " +
        "marito moglie amico amica compagno compagna cugino cugina zio zia nonno nonna suocero suocera " +
        "cognato cognata collega vicina signor signora dottor anni anno mesi classe tel cell",
    ),
  );

  // Desinenze verbali (imperfetto, infinito, gerundio, participio, forme accentate).
  const FORME_VERBALI =
    /(?:are|ere|ire|ava|avo|avano|eva|evo|evano|iva|ivo|ivano|ando|endo|ato|ata|ati|ate|uto|uta|uti|ute|ito|ita|iti|ite|isce|iscono|[àèéìòù])$/;
  const COGNOMI_IN_FORMA_VERBALE = new Set(lista("esposito amato donato"));

  // Primo termine dopo "via" che indica un uso non toponomastico ("in via precauzionale").
  const VIA_AGGETTIVI = new Set(
    lista(
      "precauzionale cautelativa cautelare preliminare provvisoria provvisorio d'urgenza urgente breve " +
        "amministrativa telematica informale eccezionale ufficiosa ufficiale prioritaria subordinata " +
        "principale residuale sommaria generale esclusiva transitoria definitiva diretta indiretta " +
        "privata riservata alternativa",
    ),
  );

  const norm = (s) =>
    String(s)
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/’/g, "'")
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();

  const prevWord = (text, pos) => {
    const m = /([^\s]+)[ \t]*$/.exec(text.slice(Math.max(0, pos - 40), pos));
    return m ? norm(m[1]) : "";
  };
  const isToponimo = (text, pos) => TOPONIMI.has(prevWord(text, pos));
  const soloSpazi = (s) => /^[ \t]+$/.test(s);

  // (a) nomi da elenco con iniziale maiuscola, anche in ordine inverso, con particelle.
  function nomiMaiuscoli(text) {
    const out = [];
    const words = [];
    for (const m of text.matchAll(/\p{Lu}[\p{Ll}'’]+/gu)) {
      words.push({ w: m[0], n: norm(m[0]), start: m.index, end: m.index + m[0].length });
    }
    const adj = (a, b) => {
      if (!a || !b) return false;
      const gap = text.slice(a.end, b.start);
      return soloSpazi(gap) || (gap === "" && /['’]$/.test(a.w));
    };
    const part = (x) => Boolean(x) && PARTICELLE.has(x.n);
    const nome = (x) => Boolean(x) && NOMI.has(x.n);
    // Estende da words[i] fino a `max` parole contate (le particelle non contano); -1 se nessuna.
    const estendi = (i, max) => {
      let j = i;
      let cnt = 0;
      let last = -1;
      while (cnt < max && adj(words[j], words[j + 1])) {
        j++;
        if (part(words[j])) continue;
        cnt++;
        last = j;
      }
      return last;
    };
    for (let i = 0; i < words.length; i++) {
      const a = words[i];
      let last = -1;
      if (nome(a)) last = estendi(i, 2);
      if (last < 0) {
        // ordine inverso: [particelle] cognome + nome (+ secondo nome)
        let k = i;
        while (part(words[k]) && adj(words[k], words[k + 1])) k++;
        const sur = words[k];
        const nm = words[k + 1];
        const nn = words[k + 2];
        if (sur && !part(sur) && !NON_COGNOMI.has(sur.n) && !TOPONIMI.has(sur.n) && adj(sur, nm) && nome(nm)) {
          // se segue un'altra parola che non è un nome, il nome apre la sequenza successiva
          if (!adj(nm, nn)) last = k + 1;
          else if (nome(nn)) last = k + 2;
        }
      }
      if (last < 0) continue;
      // nomi composti scritti attaccati ("MariaGrazia"): il valore parte dall'inizio della parola
      let start = a.start;
      while (start > 0 && /\p{L}/u.test(text[start - 1])) start--;
      out.push({ kind: "PERSONA", start, end: words[last].end });
      i = last;
    }
    return out;
  }

  // (b) titolo + una o due parole maiuscole (non cariche come "Procuratore").
  function titoli(text) {
    const out = [];
    const titolo =
      /(^|[^\p{L}\p{N}_])(sig\.ra|sig\.na|sigg\.|sig\.|sigra|signora|signorina|signor|dott\.ssa|dott\.|dr\.|prof\.ssa|prof\.|avv\.|ing\.|geom\.|rag\.|arch\.|m\.llo|mar\.|brig\.|app\.|car\.|ten\.|cap\.|magg\.|col\.|lgt\.)(?=[ \t])/giu;
    const parola = /[ \t]+(\p{Lu}[\p{L}'’]+)/uy;
    const minuscola = /[ \t]+(\p{Ll}{3,})(?![\p{L}\p{N}_])/uy;
    for (const m of text.matchAll(titolo)) {
      const start = m.index + m[1].length;
      let pos = start + m[2].length;
      let end = pos;
      let n = 0;
      while (n < 2) {
        parola.lastIndex = pos;
        const p = parola.exec(text);
        if (!p) break;
        const w = norm(p[1]);
        if (CARICHE.has(w) || /^[IVXLCDM]+$/.test(p[1])) break;
        pos = parola.lastIndex;
        if (PARTICELLE.has(w)) continue;
        end = pos;
        n++;
      }
      // cognome in minuscolo dopo un titolo civile ("il sig. rossi")
      if (n === 0 && /^(?:sig|dott|dr|avv|prof)/i.test(m[2])) {
        minuscola.lastIndex = pos;
        const p = minuscola.exec(text);
        if (p && !STOP.has(norm(p[1])) && !CARICHE.has(norm(p[1])) && !FORME_VERBALI.test(p[1])) {
          end = minuscola.lastIndex;
          n = 1;
        }
      }
      if (n > 0) out.push({ kind: "PERSONA", start, end });
    }
    return out;
  }

  // (c) sequenze in maiuscolo ("ROSSI MARIO"): almeno una parola deve essere un nome dell'elenco.
  function maiuscolo(text) {
    const out = [];
    const toks = [];
    for (const m of text.matchAll(/(^|[^\p{L}\p{N}_])(\p{Lu}[\p{Lu}'’]*)(?![\p{L}\p{N}_])/gu)) {
      const start = m.index + m[1].length;
      toks.push({ w: m[2], n: norm(m[2]), start, end: start + m[2].length });
    }
    let seg = [];
    const chiudi = () => {
      const c = seg.filter((t) => !t.part);
      seg = [];
      if (c.length < 2) return;
      const idx = c.map((t, i) => (NOMI.has(t.n) ? i : -1)).filter((i) => i >= 0);
      if (!idx.length) return;
      let from = 0;
      let to = c.length - 1;
      if (c.length > 4) {
        // sequenza lunga (intestazione con un nome): solo il tratto attorno ai nomi
        from = Math.max(0, idx[0] - 1);
        to = Math.min(c.length - 1, idx[idx.length - 1] + 1);
      }
      const len = to - from + 1;
      if (len >= 2 && len <= 4) out.push({ kind: "PERSONA", start: c[from].start, end: c[to].end });
    };
    for (let i = 0; i < toks.length; i++) {
      const t = toks[i];
      const prev = toks[i - 1];
      if (prev && !soloSpazi(text.slice(prev.end, t.start))) chiudi();
      if (PARTICELLE.has(t.n)) {
        if (seg.length) seg.push({ ...t, part: true });
        continue;
      }
      if (t.w.replace(/['’]/g, "").length < 3 || SIGLE.has(t.w) || TOPONIMI.has(t.n)) {
        chiudi();
        continue;
      }
      seg.push(t);
    }
    chiudi();
    return out;
  }

  // Nomi scritti in minuscolo ("ho fermato mario rossi"): regola prudente, solo nomi non ambigui di
  // almeno 4 lettere seguiti da una parola minuscola che non sia funzionale, un verbo o un nome comune.
  function nomiMinuscoli(text) {
    const out = [];
    const toks = [];
    for (const m of text.matchAll(/[\p{L}\p{N}_'’]+/gu)) {
      toks.push({ w: m[0], n: norm(m[0]), start: m.index, end: m.index + m[0].length });
    }
    const sep = (a, b) => Boolean(a && b) && soloSpazi(text.slice(a.end, b.start));
    const minuscola = (t, min) => /^\p{Ll}+$/u.test(t.w) && t.w.length >= min;
    const cognomeOk = (t) =>
      minuscola(t, 3) && !STOP.has(t.n) && (!FORME_VERBALI.test(t.w) || COGNOMI_IN_FORMA_VERBALE.has(t.n));
    for (let i = 0; i < toks.length; i++) {
      const t = toks[i];
      // il primo può avere la maiuscola di inizio frase ("Mario rossi"), il seguito è minuscolo
      if (!/^\p{Lu}?\p{Ll}+$/u.test(t.w) || t.w.length < 4 || !NOMI.has(t.n) || AMBIGUI.has(t.n)) continue;
      let j = i + 1;
      let cnt = 0;
      let last = -1;
      while (cnt < 2 && sep(toks[j - 1], toks[j])) {
        const u = toks[j];
        if (PARTICELLE.has(u.n) && minuscola(u, 1)) {
          j++;
          continue;
        }
        if (!cognomeOk(u)) break;
        last = j;
        cnt++;
        j++;
      }
      if (last < 0) continue;
      out.push({ kind: "PERSONA", start: t.start, end: toks[last].end });
      i = last;
    }
    return out;
  }

  function persone(text) {
    return []
      .concat(nomiMaiuscoli(text), titoli(text), maiuscolo(text), nomiMinuscoli(text))
      .filter((f) => !isToponimo(text, f.start))
      .map((f) => ({ ...f, value: text.slice(f.start, f.end) }))
      .filter((f) => !LUOGHI.has(norm(f.value)));
  }

  function nascite(text) {
    const out = [];
    const data = new RegExp(String.raw`\b(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{1,2} (?:${MESI}) \d{4})\b`, "i");
    // "nato a", "nata il", "data di nascita", "n. a Roma": la data deve iniziare entro 40 caratteri
    const chiavi = [
      /\b(?:nat[oa]\b(?=[ \t,]+(?:a|ad|il|in|nel|nella|presso)\b)|nascita\b)/gi,
      /(^|[^\p{L}\p{N}_])n\.(?=[ \t]+a[ \t]+\p{Lu})/gu,
    ];
    for (const re of chiavi) {
      for (const m of text.matchAll(re)) {
        const from = m.index + m[0].length;
        const tail = text.slice(from, from + 60).split("\n")[0];
        const d = data.exec(tail);
        if (d && d.index <= 40) {
          out.push({ kind: "NASCITA", value: d[0], start: from + d.index, end: from + d.index + d[0].length });
        }
      }
    }
    return out;
  }

  function indirizzi(text) {
    const out = [];
    const W = String.raw`[^\s,\d\[\]]+`;
    const re = new RegExp(
      String.raw`\b(via|viale|piazza|piazzale|corso|vicolo|largo|località|loc\.|contrada)[ \t]+((?:\d{1,2}[ \t]+)?${W}(?:[ \t]+${W}){0,4}),?\s*(?:n\.\s*)?\d{1,4}(?:bis|ter|quater|[a-zA-Z])?\b`,
      "gi",
    );
    const maiuscola = (p) => /^\p{Lu}/u.test(p);
    for (const m of text.matchAll(re)) {
      const parole = m[2].split(/[ \t]+/).filter((p) => !/^\d+$/.test(p));
      const primaPiena = parole.find((p) => !PARTICELLE.has(norm(p)));
      // "per via delle 3 ferite", "in via precauzionale veniva sottoposto a 2 accertamenti"
      if (/^via$/i.test(m[1]) && prevWord(text, m.index) === "per") continue;
      if (VIA_AGGETTIVI.has(norm(parole[0]))) continue;
      if (!primaPiena) continue;
      if (parole.length > 3 && !parole.some(maiuscola)) continue;
      // "corso" e "largo" sono anche nomi comuni ("nel corso del 2023"): serve un nome proprio.
      if (/^(corso|largo)$/i.test(m[1]) && !maiuscola(primaPiena)) continue;
      out.push({ kind: "INDIRIZZO", value: m[0], start: m.index, end: m.index + m[0].length });
    }
    return out;
  }

  function scan(text, options) {
    const src = String(text || "");
    const ignore = new Set(((options && options.ignore) || []).map(norm));
    const all = [].concat(Mask.find(src), persone(src), nascite(src), indirizzi(src));
    // Esenti solo i segnaposto veri ([DENUNCIANTE], [DA COMPLETARE], [PERSONA_1]): maiuscole, cifre,
    // trattini bassi e spazi. "[DENUNCIANTE Mario Rossi]" o "[via Roma 12]" vengono controllati.
    const brackets = [];
    for (const m of src.matchAll(/\[[\p{Lu}\p{N}_ ]{1,40}\]/gu)) brackets.push([m.index, m.index + m[0].length]);
    const cand = all
      .filter((f) => !brackets.some(([a, b]) => f.start >= a && f.start < b))
      .sort((x, y) => x.start - y.start || y.end - x.end);
    const out = [];
    let lastEnd = 0;
    for (const f of cand) {
      if (f.start < lastEnd) continue;
      out.push({ kind: f.kind, value: f.value, start: f.start, end: f.end });
      lastEnd = f.end;
    }
    // ignore si applica dopo le sovrapposizioni: un falso allarme scartato non fa emergere i suoi
    // frammenti più corti ("Rossi Mario" ignorato non deve diventare "Mario tel").
    return out.filter((f) => !ignore.has(norm(f.value)));
  }

  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  function replace(text, finding, map) {
    const src = String(text);
    const key = norm(finding.value);
    let token = null;
    let n = 0;
    for (const t of Object.keys(map)) {
      const m = /^\[([A-Z]+)_(\d+)\]$/.exec(t);
      if (!m || m[1] !== finding.kind) continue;
      n = Math.max(n, Number(m[2]));
      if (norm(map[t]) === key) token = t;
    }
    // Numerazione oltre anche i segnaposto già scritti nel testo ("[PERSONA_1] ... Mario Rossi"):
    // altrimenti due persone diverse riceverebbero lo stesso segnaposto.
    for (const m of src.matchAll(/\[\s*([A-Za-z]+)[\s_]*(\d+)\s*\]/g)) {
      if (m[1].toUpperCase() === finding.kind) n = Math.max(n, Number(m[2]));
    }
    if (!token) {
      token = "[" + finding.kind + "_" + (n + 1) + "]";
      map[token] = finding.value;
    }
    const body = finding.value.trim().split(/\s+/).map(escapeRe).join("\\s+");
    const re = new RegExp("(^|[^\\p{L}\\p{N}_])" + body + "(?![\\p{L}\\p{N}_])", "giu");
    let out = src.replace(re, (w, pre) => pre + token);
    // Valore attaccato ad altre lettere o cifre ("3Mario Rossi"): se la regex non trova nulla si
    // sostituisce per posizione, così il ciclo "Sostituisci tutti" converge sempre.
    if (out === src && src.slice(finding.start, finding.end) === finding.value) {
      out = src.slice(0, finding.start) + token + src.slice(finding.end);
    }
    return { text: out, token };
  }

  // Prepara il testo da inviare per i tipi PG. Se scan trova qualcosa restituisce { found, text } senza
  // modificare nulla (l'invio va bloccato). Altrimenti i residui di LexMask.find (anche quelli segnalati
  // "Non è un dato personale") vengono sostituiti con la STESSA mappa, così la numerazione dei segnaposto
  // è condivisa e l'unmask con quella mappa ripristina tutto. La mappa viene aggiornata sul posto.
  function prepare(text, map, ignore) {
    let out = String(text || "");
    const found = scan(out, { ignore });
    if (found.length) return { found, text: out };
    for (let i = 0; i < 200; i++) {
      const f = Mask.find(out)[0];
      if (!f) break;
      const next = replace(out, f, map).text;
      if (next === out) break;
      out = next;
    }
    // Se il ciclo non ha esaurito i dati (oltre 200 valori), l'invio resta bloccato.
    const residui = Mask.find(out);
    if (residui.length) return { found: residui, text: String(text || "") };
    return { found: [], text: out };
  }

  const api = { scan, replace, prepare, LABELS, NOMI };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LexGuard = api;
})(typeof window !== "undefined" ? window : globalThis);
