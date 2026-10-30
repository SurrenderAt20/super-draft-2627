"use strict";
// Betting: singles, accas, same-match combinations, a ladder challenge and Premier League goalscorers,
// with a live track record, from data/tips.json (scripts/tips.py).

let TIPS = null;
const TIPS_STATE = { done: "singles" };

const KIND = {
  banker: ["Sikre singler", "De mest sandsynlige spil til mindst odds 1,10, på tværs af markeder: vinder, dobbeltchance, mål, hold scorer."],
  value: ["Bedste pris", "Hvor bet365's odds ligger tættest på den rigtige chance."],
  edge: ["Value", "bet365 giver mere end den rigtige chance tilsiger. Lyder som gratis penge, men i testen havde bet365 oftest ret: markedet flytter sig den anden vej."],
  goals: ["Mål", "Over/under, begge hold scorer, hold scorer, hold scorer 2+."],
  sgm: ["Kampkombi", "To ting i samme kamp, fx vinder og over 1,5 mål. Chancen regnes samlet, fordi de hænger sammen."],
  scorer: ["Målscorere", "Premier League. Chancen er FPL-modellens forventede mål for spilleren. Tallet er fair odds: tag kun spillet, hvis bet365 giver mere."],
  safe: ["Sikker kombi", "Fire sandsynlige ben fra hver sin kamp, blandede markeder."],
  mix: ["Mix-kombi", "Ben omkring 55–78% fra forskellige markeder, samlet odds omkring 4."],
  long: ["Langskud-kombi", "Ben omkring 40–65%, samlet odds 8 eller mere."],
  watch: ["Hold øje", "Kampe med en historie: nyheder, fravær, tabel, form mod marked, målfest, markedsbevægelser."],
};
const STORY = { skade: "Skade", udelukket: "Udelukket", comeback: "Comeback", træner: "Træner", krise: "Krise", fravær: "Fravær",
  tabel: "Tabel", form: "Form", mål: "Mål", marked: "Marked" };
const SINGLE_KINDS = ["banker", "goals", "sgm", "value", "edge", "scorer"];
const pct = (x, d = 0) => `${num(x * 100, d)}%`;
const odds = (x) => (x ? num(x, 2) : "–");
const price = (l) => (!l.price ? `<span class="muted" title="Fair odds: 1 / chance">fair ${num(1 / l.p, 2)}</span>`
  : l.est ? `<span title="Skønnet bet365-pris: tjek den">≈${num(l.price, 2)}</span>` : num(l.price, 2));
const roiTxt = (x) => (x == null ? "–" : `${x >= 0 ? "+" : "−"}${num(Math.abs(x) * 100, 1)}%`);
const units = (x) => `${x >= 0 ? "+" : "−"}${num(Math.abs(x), 1)}`;
const kr = (x) => `${num(x, 0)} kr.`;

function part(mkt, sel, l) {
  const h = l.home, a = l.away;
  const m = {
    "1x2": { H: `${h} vinder`, D: "Uafgjort", A: `${a} vinder` },
    dc: { "1X": `${h} eller uafgjort`, X2: `${a} eller uafgjort`, 12: "Ingen uafgjort" },
    btts: { Y: "Begge hold scorer", N: "Ikke begge hold scorer" },
    ts: { H: `${h} scorer`, A: `${a} scorer` },
    t2: { H: `${h} scorer 2+`, A: `${a} scorer 2+` },
  };
  if (mkt === "ou") return `${sel[0] === "O" ? "Over" : "Under"} ${sel.slice(1).replace(".", ",")} mål`;
  return m[mkt]?.[sel] ?? sel;
}
function pick(l) {
  if (l.mkt === "manual") return l.text;
  if (l.mkt === "scorer") return `${l.player} scorer`;
  if (l.mkt === "sgm") return l.sel.split("+").map((s) => { const [m, x] = s.split(":"); return part(m, x, l); }).join(" + ");
  return part(l.mkt, l.sel, l);
}
function league(l) {
  return { E0: "Premier League", E1: "Championship", E2: "League One", E3: "League Two", EC: "National League",
    SC0: "Skotsk Premiership", SC1: "Skotsk Championship", SC2: "Skotsk League One", SC3: "Skotsk League Two",
    D1: "Bundesliga", D2: "2. Bundesliga", SP1: "La Liga", SP2: "La Liga 2", I1: "Serie A", I2: "Serie B",
    F1: "Ligue 1", F2: "Ligue 2", N1: "Eredivisie", B1: "Jupiler Pro League", P1: "Primeira Liga", T1: "Süper Lig",
    G1: "Super League (GR)" }[l.div] || l.div;
}
const kickoff = (l) => (l.ko ? new Intl.DateTimeFormat("da-DK", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Copenhagen" }).format(new Date(l.ko)) : l.date);
const day = (iso) => new Intl.DateTimeFormat("da-DK", { weekday: "long", day: "numeric", month: "long", timeZone: "Europe/Copenhagen" }).format(new Date(iso));
const clock = (iso) => new Intl.DateTimeFormat("da-DK", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Copenhagen" }).format(new Date(iso));
const shortDay = (iso) => new Intl.DateTimeFormat("da-DK", { day: "numeric", month: "short" }).format(new Date(iso));

function status(x) {
  if (x.res === "won") return `<span class="bt-res won">Vundet</span>`;
  if (x.res === "lost") return `<span class="bt-res lost">Tabt</span>`;
  if (x.res === "void") return `<span class="bt-res">Annulleret</span>`;
  if (x.res === "skipped") return `<span class="bt-res">Ikke spillet</span>`;
  return `<span class="bt-res open">Afventer</span>`;
}

// confidence: the tip's chance, and how often tips with that chance hit in the historical test
function confText(l) {
  if (!l.conf) return "";
  return `Tips med ${Math.round(l.conf.lo * 100)}–${Math.round(l.conf.hi * 100)}% chance ramte ${pct(l.conf.obs, 1)} i testen (${l.conf.n.toLocaleString("da-DK")} tips).`;
}
function reasons(l) {
  const items = (l.why || []).map((w) => `<li>${esc(w)}</li>`).join("");
  const c = confText(l);
  return `<b>${esc(pick(l))}</b><br>Chance ${pct(l.p)}${c ? `. ${c}` : ""}${items ? `<ul class="bt-why">${items}</ul>` : ""}`;
}

// ---------------------------------------------------------------- view

async function viewBetting() {
  if (!TIPS) {
    try {
      TIPS = await getJSON("data/tips.json");
    } catch (e) {
      app.innerHTML = `<h1>Betting</h1><p class="lede">${e.message.includes("404") ? "Der er ingen tips endnu. Første kupon kommer kl. 11 eller 15." : `Tips kunne ikke hentes (${esc(e.message)}). Prøv at genindlæse.`}</p>`;
      return;
    }
  }
  renderTips();
}

function renderTips() {
  const L = TIPS.live;
  const cards = TIPS.cards;
  const lastDay = cards.length ? cards[cards.length - 1].day : null;
  const todays = cards.filter((c) => c.day === lastDay).reverse();
  const pending = cards.reduce((n, c) => n + c.singles.filter((l) => !l.res).length + c.accas.filter((a) => !a.res).length, 0);
  const none = `<span class="v">–</span>`;

  app.innerHTML = `
    <h1>Betting</h1>
    <p class="lede">For sjov. Chancerne er Betfair Exchanges priser uden margin, den skarpeste vurdering vi har, eller de forventede mål, de priser giver. Odds er bet365's; med ≈ er de skønnet og skal tjekkes. Ingen tips har en fordel: bet365's margin gør, at en single i snit taber omkring 3–5%, og en kombi mere. Tryk på et spil for begrundelsen. Kupon kl. 11, opdatering kl. 15.</p>

    <div class="recs" style="margin-top:20px">
      ${panel(`${L.legs ? `<span class="v">${pct(L.leg_hit)}</span>` : none}<span class="t">Modellens træfsikkerhed</span><span class="d">${L.legs ? `${L.legs} afgjorte udfald siden ${shortDay(TIPS.started)}. Chancerne lovede ${pct(L.leg_expected)}.` : `Ingen afgjort endnu (${pending} afventer). I den historiske test holdt chancerne: sagt ${pct(TIPS.history.leg_expected)}, ramt ${pct(TIPS.history.leg_hit)}.`}</span>`, "rec")}
      ${panel(`${L.singles.n ? `<span class="v">${L.singles.won}/${L.singles.n}</span>` : none}<span class="t">Singler vundet</span><span class="d">${L.singles.n ? `Lovet ${pct(L.singles.expected)} i snit, ramt ${pct(L.singles.hit)}.` : "Ingen afgjort endnu."}</span>`, "rec")}
      ${panel(`${L.accas.n ? `<span class="v">${L.accas.won}/${L.accas.n}</span>` : none}<span class="t">Kombi'er vundet</span><span class="d">${L.accas.n ? `Lovet ${pct(L.accas.expected)} i snit.` : "Ingen afgjort endnu."}</span>`, "rec")}
      ${panel(`<span class="v">${L.singles.staked + L.accas.staked ? units(L.singles.profit + L.accas.profit) : "0"}</span><span class="t">Enheder siden ${shortDay(TIPS.started)}</span><span class="d">1 enhed per tip med odds.${L.singles.n ? ` Forventet: ${roiTxt(L.singles.exp_roi)} per single.` : ""}</span>`, "rec")}
    </div>

    ${moneyHtml()}

    ${ladderHtml()}

    ${todays.map((c) => `<section class="sec">
      <div class="sec-head"><div><h2>${c.extra ? `Ekstra kupon kl. ${clock(c.published)}` : c.slot === 15 ? "Opdatering kl. 15" : "Kupon kl. 11"}, ${day(c.published)}</h2>
        <p class="lede">Kampe de næste 24 timer${c.slot !== 11 ? ", uden spil og kampe der allerede er givet i dag" : ""}. Offentliggjort ${dateOnly(c.published)}, odds hentet ${c.odds_as_of ? dateOnly(c.odds_as_of) : "ukendt"}; bet365 kan have flyttet dem. Ændres aldrig, når den er lagt ud.</p></div></div>
      ${cardHtml(c)}
    </section>`).join("") || `<section class="sec"><h2>Ingen kupon endnu</h2><p class="lede">Første kupon kommer kl. 11 eller 15.</p></section>`}

    ${scorerListHtml()}

    <section class="sec">
      <div class="sec-head"><div><h2>Afgjorte tips</h2><p class="lede">Alle tips siden ${shortDay(TIPS.started)}, når kampene er spillet.</p></div>
        <div class="seg" id="bt-done" role="group" aria-label="Type"><button type="button" data-done="singles">Singler</button><button type="button" data-done="accas">Kombi'er</button></div></div>
      <div id="bt-done-box"></div>
    </section>

    <section class="sec">
      <div class="sec-head"><div><h2>Nøjagtighed</h2><p class="lede">Rammer tipsene så tit, som chancerne siger? Live er tips siden ${shortDay(TIPS.started)}. Baggrund: de samme regler kørt på hver kampdag ${TIPS.history.first.slice(0, 4)}–${TIPS.history.last.slice(0, 4)} med priserne fra før kampene; den giver sikkerheden på hvert tip.</p></div></div>
      ${accuracyHtml(L, TIPS.history)}
    </section>
    <p class="small muted" style="margin-top:20px">Opdateret ${dateOnly(TIPS.updated)}. Kun til underholdning. Spil ansvarligt; hjælp på stopspillet.dk.</p>`;

  app.querySelectorAll("#bt-done button").forEach((b) => b.addEventListener("click", () => { TIPS_STATE.done = b.dataset.done; drawDone(); }));
  app.querySelectorAll(".bt-act").forEach((b) => b.addEventListener("click", () => ladderAct(b.dataset.act, b.dataset.step)));
  drawDone();
  bindTips(app);
}

// ---------------------------------------------------------------- ladder changes
// The site is static: a change runs the tips workflow on GitHub with the choice as its inputs, which
// updates the ladder and commits it. That needs a GitHub token kept in this browser only.

const REPO = "SurrenderAt20/super-draft-2627";
const ghKey = {
  get: () => { try { return localStorage.getItem("bt-gh-token"); } catch { return null; } },
  set: (v) => { try { localStorage.setItem("bt-gh-token", v); } catch { /* storage blocked: asked again next time */ } },
  clear: () => { try { localStorage.removeItem("bt-gh-token"); } catch { /* nothing stored */ } },
};

function findBet(ref) {
  const [rid, d, order] = ref.split(":");
  const run = TIPS.ladder.runs.find((r) => String(r.id) === rid);
  return run && run.bets.find((b) => b.day === d && String(b.order) === order);
}

function ladderAct(act, ref) {
  if (!ghKey.get()) return keySheet(() => ladderAct(act, ref));
  const b = findBet(ref);
  if (act === "replace") return dispatch({ action: "replace", step: ref }, "Leder efter en ny bet til trinnet.");
  if (act === "won" || act === "lost") return dispatch({ action: "result", step: ref, res: act }, `Markerer dit spil som ${act === "won" ? "vundet" : "tabt"}.`);
  if (act === "manual") ownBetSheet(ref, b);
}

function keySheet(then) {
  openSheet(`<h3 class="sheet-h">Nøgle til at ændre stigen</h3>
    <p class="small">Ændringer gemmes ved at køre tips-jobbet på GitHub, så siden skal have en GitHub-nøgle. Den gemmes kun i denne browser.</p>
    <ol class="small bt-steps-list">
      <li>Åbn <a class="link" href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener">GitHub: ny fine-grained token</a>.</li>
      <li>Repository access: <b>Only select repositories</b> → super-draft-2627.</li>
      <li>Permissions → Repository → <b>Actions: Read and write</b>. Intet andet.</li>
      <li>Generate token, kopiér den og sæt den ind her.</li>
    </ol>
    <form id="bt-key"><input type="password" autocomplete="off" placeholder="github_pat_…" required style="width:100%">
      <button type="submit" style="margin-top:10px">Gem nøgle</button></form>`);
  sheet.querySelector("#bt-key").addEventListener("submit", (e) => {
    e.preventDefault();
    ghKey.set(e.target.querySelector("input").value.trim());
    closeSheet();
    then();
  });
}

function ownBetSheet(ref, b) {
  const fx = (TIPS.fixtures || []).filter((m) => new Date(m.ko) > new Date());
  const groups = {};
  fx.forEach((m) => (groups[league(m)] = groups[league(m)] || []).push(m));
  const markets = [["1x2", "H"], ["1x2", "D"], ["1x2", "A"], ["dc", "1X"], ["dc", "X2"], ["dc", "12"], ["ou", "O1.5"], ["ou", "U1.5"],
    ["ou", "O2.5"], ["ou", "U2.5"], ["ou", "O3.5"], ["ou", "U3.5"], ["btts", "Y"], ["btts", "N"], ["ts", "H"], ["ts", "A"], ["t2", "H"], ["t2", "A"]];
  const R = TIPS.rules;
  openSheet(`<h3 class="sheet-h">Byt trin ${b.order} med dit eget spil</h3>
    <form id="bt-own" class="bt-form">
      <label>Kamp<select name="match"><option value="">Vælg kamp…</option>
        ${Object.entries(groups).map(([lg, ms]) => `<optgroup label="${esc(lg)}">${ms.map((m) => `<option value="${esc(m.id)}">${esc(m.home)} – ${esc(m.away)} · ${kickoff(m)}</option>`).join("")}</optgroup>`).join("")}
        <option value="other">Andet spil, skriv selv</option></select></label>
      <label class="bt-mkt">Spil<select name="mkt"></select></label>
      <label class="bt-text" hidden>Spil (fritekst)<input name="text" maxlength="120" placeholder="fx Brøndby vinder"></label>
      <label>Odds<input name="odds" inputmode="decimal" placeholder="1,15" required></label>
      <p class="small" id="bt-pay">Indsats ${kr(b.stake ?? R.ladder_start)}.</p>
      <p class="small muted">Chancen vises som –, fordi spillet er dit valg. Fritekst-spil afgør du selv med Vundet/Tabt.</p>
      <button type="submit">Gem</button>
    </form>`);
  const f = sheet.querySelector("#bt-own");
  const fillMarkets = () => {
    const m = fx.find((x) => x.id === f.match.value);
    f.querySelector(".bt-text").hidden = f.match.value !== "other";
    f.querySelector(".bt-mkt").hidden = !m;
    f.mkt.innerHTML = m ? markets.map(([k, s]) => `<option value="${k}:${s}">${esc(part(k, s, m))}</option>`).join("") : "";
  };
  const pay = () => {
    const o = parseFloat(f.odds.value.replace(",", "."));
    const stake = b.stake ?? R.ladder_start;
    sheet.querySelector("#bt-pay").innerHTML = o > 1 ? `Indsats ${kr(stake)} × ${num(o, 2)} = <b>${kr(stake * o)}</b>${o < R.ladder_odds[0] || o > R.ladder_odds[1] ? ` · uden for stigens ${num(R.ladder_odds[0], 2)}–${num(R.ladder_odds[1], 2)}; det er dit valg` : ""}` : `Indsats ${kr(stake)}.`;
  };
  f.match.addEventListener("change", fillMarkets);
  f.odds.addEventListener("input", pay);
  fillMarkets();
  f.addEventListener("submit", (e) => {
    e.preventDefault();
    const o = parseFloat(f.odds.value.replace(",", "."));
    if (!(o > 1)) return;
    const inputs = { action: "manual", step: ref, odds: String(o) };
    if (f.match.value === "other") {
      if (!f.text.value.trim()) return;
      inputs.text = f.text.value.trim();
    } else if (f.match.value) {
      const [mkt, sel] = f.mkt.value.split(":");
      Object.assign(inputs, { match: f.match.value, mkt, sel });
    } else return;
    closeSheet();
    dispatch(inputs, "Gemmer dit spil i stigen.");
  });
}

async function dispatch(inputs, what) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/tips.yml/dispatches`, {
    method: "POST",
    headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${ghKey.get()}`, "X-GitHub-Api-Version": "2022-11-28" },
    body: JSON.stringify({ ref: "main", inputs }),
  }).catch(() => null);
  if (!r || r.status !== 204) {
    if (r && (r.status === 401 || r.status === 403 || r.status === 404)) ghKey.clear();
    openSheet(`<h3 class="sheet-h">Det gik ikke</h3><p class="small">${r && (r.status === 401 || r.status === 403 || r.status === 404)
      ? "GitHub afviste nøglen (udløbet, eller mangler Actions: Read and write på super-draft-2627). Prøv igen med en ny nøgle."
      : "GitHub svarede ikke. Prøv igen om lidt."}</p>`);
    return;
  }
  openSheet(`<h3 class="sheet-h">Sendt</h3><p class="small">${what} Det tager typisk 1–3 minutter (længere hvis ligaopdateringen kører); siden opdaterer sig selv.</p>`);
  const before = TIPS.updated;
  for (let i = 0; i < 30; i++) {
    await new Promise((res) => setTimeout(res, 20000));
    try {
      const fresh = await getJSON("data/tips.json");
      if (fresh.updated !== before) {
        TIPS = fresh;
        if (location.hash.startsWith("#betting")) { renderTips(); enhance(app); }
        return;
      }
    } catch { /* keep waiting */ }
  }
}

// ---------------------------------------------------------------- 100 kr. on everything

const STAKE = 100;
const MONEY_KINDS = ["watch", "banker", "goals", "sgm", "value", "edge", "safe", "mix", "long"];
const krSigned = (x) => `${x > 0 ? "+" : x < 0 ? "−" : "±"}${num(Math.abs(x), 0)} kr.`;
const moneyCls = (x) => (x > 0 ? "delta-up" : x < 0 ? "delta-down" : "muted");

// one section's result at 100 kr. per settled bet, from the live track record
function sectionMoney(k) {
  const s = TIPS.live.kinds[k];
  if (!s || !s.staked) return null;
  return { n: s.staked, won: s.won, staked: s.staked * STAKE, result: s.profit * STAKE, est: s.est || 0, pending: s.pending || 0 };
}

function sectionLine(k) {
  const m = sectionMoney(k);
  if (!m) return "";
  return `<p class="small bt-sofar">Hidtil: ${m.n} afgjorte, ${m.won} vundet · 100 kr. på hver: <b class="${moneyCls(m.result)}">${krSigned(m.result)}</b> af ${kr(m.staked)}${m.est ? ` · ${m.est} med skønnede odds` : ""}</p>`;
}

function moneyHtml() {
  const rows = MONEY_KINDS.map((k) => [k, sectionMoney(k)]).filter(([, m]) => m);
  const tot = rows.reduce((t, [, m]) => ({ n: t.n + m.n, won: t.won + m.won, staked: t.staked + m.staked, result: t.result + m.result, est: t.est + m.est, pending: t.pending + m.pending }),
    { n: 0, won: 0, staked: 0, result: 0, est: 0, pending: 0 });
  const LL = TIPS.ladder_live, runs = TIPS.ladder.runs;
  const alive = runs.length && runs[runs.length - 1].status === "alive" ? runs[runs.length - 1].stake : 0;
  const ladderResult = alive - LL.spent;
  const sc = TIPS.live.kinds.scorer;
  return `<section class="sec">
    <div class="sec-head"><div><h2>Hvis du havde spillet 100 kr. på alt</h2><p class="lede">100 kr. på hvert afgjort forslag siden ${shortDay(TIPS.started)}, til de odds der stod ved forslaget. Kombi'er tæller som ét spil. Resultater ved skønnede odds (≈) er også et skøn.</p></div></div>
    <div class="recs">
      ${panel(`<span class="v ${moneyCls(tot.result)}">${krSigned(tot.result)}</span><span class="t">I alt</span><span class="d">${tot.n} spil, ${tot.won} vundet, ${kr(tot.staked)} indsat (${roiTxt(tot.staked ? tot.result / tot.staked : null)}).${tot.pending ? ` ${tot.pending} afventer.` : ""}</span>`, "rec")}
      ${panel(`<span class="v ${moneyCls(ladderResult)}">${krSigned(ladderResult)}</span><span class="t">Stigen</span><span class="d">${kr(LL.spent)} sat ind over ${LL.runs} forsøg${alive ? `, ${kr(alive)} står på stigen nu` : ""}. Tæller ikke med i "I alt".</span>`, "rec")}
    </div>
    <div class="panel" style="margin-top:12px"><div class="scroll"><table class="advt">
      <thead><tr><th class="l">Afsnit</th><th>Spil</th><th>Vundet</th><th>Indsat</th><th>Resultat</th><th>Afkast</th></tr></thead>
      <tbody>${rows.map(([k, m]) => `<tr><td class="l">${KIND[k][0]}${m.est ? ` <span class="muted small">(${m.est} ≈)</span>` : ""}</td><td>${m.n}</td><td>${m.won}</td><td>${kr(m.staked)}</td>
        <td class="strong ${moneyCls(m.result)}">${krSigned(m.result)}</td><td class="${moneyCls(m.result)}">${roiTxt(m.result / m.staked)}</td></tr>`).join("")}
      <tr class="sep"><td class="l"><b>I alt</b></td><td>${tot.n}</td><td>${tot.won}</td><td>${kr(tot.staked)}</td><td class="strong ${moneyCls(tot.result)}">${krSigned(tot.result)}</td><td class="${moneyCls(tot.result)}">${roiTxt(tot.staked ? tot.result / tot.staked : null)}</td></tr>
      </tbody></table></div></div>
    <p class="small muted" style="margin-top:8px">${sc && sc.n ? `Målscorere er ikke med: data har ikke deres odds (${sc.won} af ${sc.n} gik hjem). ` : ""}Efter få uger er resultatet mest held; se "Nøjagtighed" for, om chancerne holder.</p>
  </section>`;
}

function legRow(l) {
  return `<tr><td class="l"><span data-tip="${esc(reasons(l))}"><b>${esc(pick(l))}</b></span><span class="bt-sub">${esc(l.home)} – ${esc(l.away)} · ${esc(league(l))} · ${kickoff(l)}</span></td>
    <td class="pts">${price(l)}</td><td>${pct(l.p)}${l.conf ? `<span class="bt-sub">ramte ${pct(l.conf.obs)}</span>` : ""}</td><td class="opt">${l.ev == null ? "–" : roiTxt(l.ev)}</td><td>${l.score ? `<span class="muted">${esc(l.score)}</span> ` : ""}${status(l)}</td></tr>`;
}
const LEG_HEAD = `<thead><tr><th class="l">Spil</th><th>Odds</th><th>Chance</th><th class="opt">Forventet</th><th>Status</th></tr></thead>`;

function watchHtml(c) {
  if (!c.watch || !c.watch.length) return "";
  return `<div class="panel bt-block"><h3>Kampe at holde øje med</h3>
    ${sectionLine("watch")}<p class="small muted">Kampe med en historie, mest interessante først. Nyheder er baggrund: markedet når som regel at regne dem ind, så forslaget følger de målbare tegn (form mod marked, mål, markedsbevægelser, fravær) og ellers kampens mest sandsynlige spil til mindst odds 1,30. Logges som de andre tips, så vi kan se, om historierne giver noget.</p>
    <div class="bt-watch">${c.watch.map((w) => `<div class="bt-watch-item">
      <div class="bt-watch-head"><b>${esc(w.home)} – ${esc(w.away)}</b><span class="bt-sub">${esc(league(w))} · ${kickoff(w)}</span></div>
      <ul class="bt-stories">${w.stories.map((s) => `<li><span class="tag" style="margin-left:0">${STORY[s.type] || esc(s.type)}</span> ${s.link
        ? `<a class="link" href="${esc(s.link)}" target="_blank" rel="noopener">${esc(s.text)}</a>` : esc(s.text)}</li>`).join("")}</ul>
      <div class="bt-watch-bet"><span>Forslag: <b data-tip="${esc(reasons(w.leg))}">${esc(pick(w.leg))}</b> ${price(w.leg)} · chance ${pct(w.leg.p)}${w.leg.conf ? ` (ramte ${pct(w.leg.conf.obs)})` : ""}</span>
        <span>${w.leg.score ? `<span class="muted">${esc(w.leg.score)}</span> ` : ""}${status(w.leg)}</span></div>
    </div>`).join("")}</div></div>`;
}

function cardHtml(c) {
  const singles = SINGLE_KINDS.map((k) => {
    const ls = c.singles.filter((l) => l.kind === k);
    if (!ls.length) return "";
    return `<div class="panel bt-block"><h3>${KIND[k][0]}</h3><p class="small muted">${KIND[k][1]}</p>${sectionLine(k)}
      <div class="scroll"><table class="advt">${LEG_HEAD}<tbody>${ls.map(legRow).join("")}</tbody></table></div></div>`;
  }).join("");
  const accas = c.accas.map((a) => `<div class="panel bt-block">
      <div class="bt-acca-head"><div><h3>${KIND[a.kind][0]} ${status(a)}</h3><p class="small muted">${KIND[a.kind][1]}</p>${sectionLine(a.kind)}</div>
        <div class="bt-odds"><b>${a.est ? "≈" : ""}${odds(a.price)}</b><span>samlet odds</span><small>100 kr. giver ${kr(100 * a.price)} · chance ${pct(a.p, 1)}</small></div></div>
      <div class="scroll"><table class="advt">${LEG_HEAD}<tbody>${a.legs.map(legRow).join("")}</tbody></table></div></div>`).join("");
  return `<div class="bt-card">${watchHtml(c)}${singles}${accas}</div>`;
}

// ---------------------------------------------------------------- ladder

function ladderHtml() {
  const lad = TIPS.ladder || { runs: [] };
  const run = lad.runs[lad.runs.length - 1];
  const H = TIPS.history.ladder, R = TIPS.rules, LL = TIPS.ladder_live;
  const today = run ? run.bets.filter((b) => b.day === run.bets[run.bets.length - 1].day) : [];
  const head = `<thead><tr><th class="l">Trin</th><th>Indsats</th><th>Odds</th><th>Udbetaling</th><th>Chance</th><th>Status</th><th></th></tr></thead>`;
  const legLine = (l) => l.mkt === "manual" ? `<div><b>${esc(l.text)}</b><span class="bt-sub">Dit eget spil${l.res ? "" : " · afgøres her på siden"}</span></div>`
    : `<div><span data-tip="${esc(reasons(l))}"><b>${esc(pick(l))}</b></span> <span class="muted">${price(l)}</span><span class="bt-sub">${esc(l.home)} – ${esc(l.away)} · ${esc(league(l))} · ${kickoff(l)}${l.score ? ` · ${esc(l.score)}` : ""}</span></div>`;
  const row = (b) => {
    const ref = `${run.id}:${b.day}:${b.order}`;
    const started = b.legs.some((l) => l.ko && new Date(l.ko) <= new Date());
    const open = !b.res && run.status === "alive";
    const own = b.legs.some((l) => l.mkt === "manual");
    const buttons = !open ? "" : own ? `<button class="ghost bt-act" data-act="won" data-step="${ref}">Vundet</button><button class="ghost bt-act" data-act="lost" data-step="${ref}">Tabt</button>`
      : started ? "" : `<button class="ghost bt-act" data-act="replace" data-step="${ref}">Find ny bet</button><button class="ghost bt-act" data-act="manual" data-step="${ref}">Byt selv</button>`;
    const was = (b.replaced || []).map((r) => r.legs.map((l) => (l.mkt === "manual" ? l.text : `${part(l.mkt, l.sel, l)} (${l.home} – ${l.away})`)).join(" + ")).join("; ");
    return `<tr><td class="l">${b.of > 1 ? `<b>${b.order}.</b> ` : ""}${b.legs.length > 1 ? `<span class="tag" style="margin-left:0">Double</span>` : ""}${b.manual ? `<span class="tag" style="margin-left:0">Dit valg</span>` : ""}
      ${b.legs.map(legLine).join("")}${was ? `<span class="bt-sub">Erstattede: ${esc(was)}</span>` : ""}${b.note ? `<span class="bt-sub">${esc(b.note)}</span>` : ""}</td>
    <td>${b.stake == null ? "–" : kr(b.stake)}${b.if_won ? `<span class="bt-sub">hvis forrige går hjem</span>` : ""}</td><td class="pts">${b.est ? "≈" : ""}${odds(b.price)}</td><td>${b.payout == null ? "–" : kr(b.payout)}</td>
    <td>${b.p == null ? "–" : pct(b.p)}</td><td>${status(b)}</td><td class="bt-acts">${buttons}</td></tr>`;
  };
  const state = !run ? "Stigen starter ved første kørsel med et spil i intervallet."
    : run.status === "broken" ? `Forsøg ${run.id} røg efter ${run.steps} trin. Næste trin starter forfra med ${kr(R.ladder_start)}`
    : `Forsøg ${run.id}: ${run.steps} trin klaret, ${kr(run.stake)} i spil nu.`;
  const log = LL.log || [];
  const max = Math.max(...log.map((r) => r.steps), 1);
  return `<section class="sec">
    <div class="sec-head"><div><h2>Stigen</h2><p class="lede">Start med ${kr(R.ladder_start)}, sæt hele udbetalingen på næste trin, og start forfra med ${kr(R.ladder_start)} efter et tab. Et trin er en single eller en double med samlede bet365-odds ${num(R.ladder_odds[0], 2)}–${num(R.ladder_odds[1], 2)}, det der giver mest tilbage i snit. Ét trin om dagen; lørdag og søndag en kæde, hvor hvert trin starter efter det forrige er slut og kun spilles, hvis det forrige gik hjem. Kun ligaer med resultater samme dag.</p></div></div>
    <div class="recs">
      ${panel(`<span class="v">${run && run.status === "alive" ? run.steps : 0}</span><span class="t">Trin i det nuværende forsøg</span><span class="d">${state}</span>`, "rec")}
      ${panel(`<span class="v">${LL.best ? LL.best.steps : 0}</span><span class="t">Længste stige siden ${shortDay(TIPS.started)}</span><span class="d">${LL.runs} forsøg. Baggrund: i testen holdt et forsøg i snit ${num(H.avg_steps || 0, 1)} trin, og det længste ${H.best ? H.best.steps : 0} trin op til ${kr(H.best ? H.best.peak : 0)}.</span>`, "rec")}
    </div>
    ${today.length ? `<div class="panel bt-block" style="margin-top:12px"><h3>${today.length > 1 ? `Dagens kæde, ${today.length} trin` : "Dagens trin"}</h3>
      <p class="small muted">Odds hentet ${today[0].legs[0].odds_as_of ? dateOnly(today[0].legs[0].odds_as_of) : "ukendt"}; ≈ er skønnet. Ligger bet365 uden for ${num(R.ladder_odds[0], 2)}–${num(R.ladder_odds[1], 2)}, når du spiller, er det ikke stigens spil.</p>
      <div class="scroll"><table class="advt">${head}<tbody>${today.map(row).join("")}</tbody></table></div></div>` : ""}
    <div class="panel bt-block" style="margin-top:12px"><h3>Forsøg</h3><p class="small muted">Hvor langt hvert forsøg nåede, og hvad der fældede det.</p>
      ${log.length ? `<div class="scroll"><table class="advt"><thead><tr><th>#</th><th class="l">Periode</th><th class="l">Nåede</th><th>Højest</th><th class="l">Røg på</th></tr></thead><tbody>
      ${[...log].reverse().map((r) => `<tr><td class="muted">${r.id}</td><td class="l">${shortDay(r.start)}${r.end !== r.start ? `–${shortDay(r.end)}` : ""}</td>
        <td class="l"><span class="bt-steps"><i style="width:${(r.steps / max) * 100}%"></i></span> <b>${r.steps}</b> trin</td><td>${kr(r.peak)}</td>
        <td class="l">${r.status === "alive" ? `<span class="bt-res open">Lever</span>` : r.broke ? r.broke.legs.filter((l) => l.res === "lost").map((l) => `${esc(pick(l))}<span class="bt-sub">${esc(l.home)} – ${esc(l.away)} ${esc(l.score || "")}</span>`).join("") : "–"}</td></tr>`).join("")}
      </tbody></table></div>` : `<p class="muted small">Ingen forsøg endnu.</p>`}
    </div>
  </section>`;
}

// ---------------------------------------------------------------- goalscorers

function scorerListHtml() {
  const S = TIPS.scorers;
  if (!S) return "";
  return `<section class="sec">
    <div class="sec-head"><div><h2>Målscorere, runde ${S.gw}</h2><p class="lede">Premier Leagues ${S.players.length} mest sandsynlige målscorere i kampene, der mangler (midtbane og angreb; forsvarsspillere overvurderes). Fair odds er 1 / chance: bet365 skal give mere, før spillet er pengene værd. Tryk for begrundelsen.</p></div></div>
    <div class="panel"><div class="scroll"><table class="advt"><thead><tr><th class="l">Spiller</th><th>Chance</th><th>Fair odds</th><th class="opt">xG</th><th class="opt">Minutter</th></tr></thead><tbody>
      ${S.players.map((p) => `<tr><td class="l"><span data-tip="${esc(reasons(p))}"><b>${esc(p.player)}</b>${p.pen ? `<span class="tag">Straffe</span>` : ""}</span><span class="bt-sub">${esc(p.home)} – ${esc(p.away)} · ${kickoff(p)}</span></td>
        <td class="strong">${pct(p.p)}</td><td class="pts">${num(1 / p.p, 2)}</td><td class="opt">${num(p.xg_player, 2)}</td><td class="opt">${p.emin ?? "–"}</td></tr>`).join("")}
    </tbody></table></div></div>
  </section>`;
}

// ---------------------------------------------------------------- settled

function drawDone() {
  const box = app.querySelector("#bt-done-box");
  app.querySelectorAll("#bt-done button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.done === TIPS_STATE.done));
  const cards = [...TIPS.cards].reverse();
  if (TIPS_STATE.done === "singles") {
    const all = cards.flatMap((c) => [...c.singles, ...(c.watch || []).map((w) => w.leg)]);
    const col = (res, title) => {
      const ls = all.filter((l) => l.res === res);
      return `<div class="panel bt-bracket ${res}"><h3>${title} <span class="muted">${ls.length}</span></h3>
        ${ls.length ? `<ul class="bt-list">${ls.map((l) => `<li><span><b data-tip="${esc(reasons(l))}">${esc(pick(l))}</b><span class="bt-sub">${esc(l.home)} – ${esc(l.away)} ${esc(l.score || "")} · ${KIND[l.kind][0]} · ${shortDay(l.date)}</span></span>
          <span class="bt-num">${price(l)}<small>${l.price ? units(l.res === "won" ? l.price - 1 : -1) : `chance ${pct(l.p)}`}</small></span></li>`).join("")}</ul>` : `<p class="muted small">Ingen endnu.</p>`}</div>`;
    };
    box.innerHTML = `<div class="cols2">${col("won", "Vundet")}${col("lost", "Tabt")}</div>`;
  } else {
    const all = cards.flatMap((c) => c.accas.map((a) => ({ ...a, day: c.day })));
    const col = (res, title) => {
      const as = all.filter((a) => a.res === res);
      return `<div class="panel bt-bracket ${res}"><h3>${title} <span class="muted">${as.length}</span></h3>
        ${as.length ? `<ul class="bt-list">${as.map((a) => {
          const missed = a.legs.filter((l) => l.res === "lost");
          return `<li><span><b>${KIND[a.kind][0]}, ${shortDay(a.day)}</b><span class="bt-sub">${a.legs_hit} af ${a.legs.length} ben ramt${missed.length ? `. Galt: ${missed.map((l) => `${esc(pick(l))} (${esc(l.home)} – ${esc(l.away)} ${esc(l.score || "")})`).join(", ")}` : ""}</span></span>
            <span class="bt-num">${a.est ? "≈" : ""}${odds(a.price)}<small>${units(a.res === "won" ? a.paid - 1 : -1)}</small></span></li>`;
        }).join("")}</ul>` : `<p class="muted small">Ingen endnu.</p>`}</div>`;
    };
    box.innerHTML = `<div class="cols2">${col("won", "Vundet")}${col("lost", "Tabt")}</div>`;
  }
  bindTips(box);
}

// ---------------------------------------------------------------- accuracy

function accuracyHtml(L, H) {
  const live = (l) => (l && l.n ? `${pct(l.hit)} <span class="muted">/ ${pct(l.expected)} · ${l.n}</span>` : `<span class="muted">${l && l.pending ? `${l.pending} afventer` : "–"}</span>`);
  const row = (k) => {
    const l = L.kinds[k], h = H.kinds[k];
    if (k === "scorer") {
      const T = TIPS.scorer_test;
      return T ? `<tr><td class="l">${KIND[k][0]}</td><td>${live(l)}</td><td class="muted">${pct(T.top3.hit, 1)} / ${pct(T.top3.expected, 1)} · ${T.top3.n}</td><td class="muted">–</td></tr>` : "";
    }
    if (k === "watch") return `<tr><td class="l">${KIND[k][0]}</td><td>${live(l)}</td><td class="muted">ny, ingen test</td><td class="muted">–</td></tr>`;
    if (!h || !h.n) return "";
    return `<tr><td class="l">${KIND[k][0]}</td><td>${live(l)}</td><td class="muted">${pct(h.hit, 1)} / ${pct(h.expected, 1)} · ${h.n.toLocaleString("da-DK")}</td>
      <td class="muted">${roiTxt(h.roi)} <span class="small">(forventet ${roiTxt(h.exp_roi)})</span></td></tr>`;
  };
  const cal = (S) => S.cal.map((b) => `<tr><td class="l">${Math.round(b.lo * 100)}–${Math.round(b.hi * 100)}%</td><td>${pct(b.pred, 1)}</td><td class="strong">${pct(b.obs, 1)}</td><td class="muted">${b.n.toLocaleString("da-DK")}</td>
      <td class="l"><span class="calbar"><i class="p" style="left:${b.pred * 100}%"></i><i class="o" style="left:${b.obs * 100}%"></i></span></td></tr>`).join("");
  const E = H.kinds.edge;
  return `
    <div class="panel"><div class="scroll"><table class="advt">
      <thead><tr><th class="l">Type</th><th>Live: ramt / lovet · antal</th><th>Baggrund: ramt / lovet · antal</th><th>Baggrund: afkast</th></tr></thead>
      <tbody>${["watch", "banker", "goals", "sgm", "value", "edge", "safe", "mix", "long", "scorer"].map(row).join("")}</tbody></table></div></div>
    <p class="small muted" style="margin-top:10px">Afkast er per enhed ved bet365's odds; for skønnede odds er det et skøn. "Forventet" er det, chancerne siger, man taber i snit; forskellen er held.${E && E.n ? ` Value-spillene lovede ${roiTxt(E.exp_roi)}, men gav ${roiTxt(E.roi)}: når bet365 ligger over den rigtige chance, er det oftest bet365, der har ret.` : ""}${TIPS.scorer_test ? ` Målscorere er testet på runde ${TIPS.scorer_test.rounds[0]}–${TIPS.scorer_test.rounds[1]} af 2025/26 (modellens tre bedste bud per runde).` : ""}</p>
    <div class="cols2" style="margin-top:16px">
      <div class="panel"><h3 style="margin:0 0 4px">Holder chancerne? Live</h3><p class="small muted">Alle afgjorte ben siden ${shortDay(TIPS.started)}, grupperet efter chance. <span class="key-dot p"></span>lovet <span class="key-dot o"></span>ramt.</p>
        ${L.cal.length ? `<div class="scroll"><table class="advt"><thead><tr><th class="l">Chance</th><th>Lovet</th><th>Ramt</th><th>Ben</th><th class="l"></th></tr></thead><tbody>${cal(L)}</tbody></table></div>` : `<p class="muted small">Ingen afgjorte endnu.</p>`}</div>
      <div class="panel"><h3 style="margin:0 0 4px">Baggrund: testen</h3><p class="small muted">Det er her, sikkerheden på hvert tip kommer fra.</p>
        <div class="scroll"><table class="advt"><thead><tr><th class="l">Chance</th><th>Lovet</th><th>Ramt</th><th>Ben</th><th class="l"></th></tr></thead><tbody>${cal(H)}</tbody></table></div></div>
    </div>`;
}

VIEWS.betting = viewBetting;
