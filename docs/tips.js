"use strict";
// Betting: daily singles and accas for fun, a ladder challenge and Premier League goalscorers, with a
// track record. data/tips.enc.json is encrypted with the same password as the Advanced tab (it holds
// bookmaker prices); see scripts/tips.py.

let TIPS = null;
const TIPS_STATE = { done: "singles", ladderLog: "live" };

const KIND = {
  banker: ["Sikre singler", "De mest sandsynlige udfald i dagens kampe."],
  value: ["Bedste pris", "Hvor bet365's odds ligger tættest på den rigtige chance."],
  edge: ["Value", "bet365 giver mere end den rigtige chance tilsiger. Lyder som gratis penge, men se testen nedenfor: markedet har som regel ret, og bet365's høje odds er oftere en fejl i den anden retning."],
  goals: ["Mål", "Over/under 2,5 mål og begge hold scorer."],
  scorer: ["Målscorere", "Premier League. Chancen er FPL-modellens forventede mål for spilleren. Ingen bet365-odds i data, så tallet er fair odds: tag kun spillet, hvis bet365 giver mere."],
  safe: ["Sikker kombi", "Fire sandsynlige ben fra hver sin kamp."],
  long: ["Langskud-kombi", "Ben omkring 50%, samlet odds omkring 8 eller mere."],
};
const SINGLE_KINDS = ["banker", "value", "edge", "goals", "scorer"];
const pct = (x, d = 0) => `${num(x * 100, d)}%`;
const odds = (x) => (x ? num(x, 2) : "–");
const price = (l) => (l.price ? num(l.price, 2) : `<span class="muted" title="Fair odds: 1 / chance">fair ${num(1 / l.p, 2)}</span>`);
const roiTxt = (x) => (x == null ? "–" : `${x >= 0 ? "+" : "−"}${num(Math.abs(x) * 100, 1)}%`);
const units = (x) => `${x >= 0 ? "+" : "−"}${num(Math.abs(x), 1)}`;
const kr = (x) => `${num(x, 0)} kr.`;

function pick(l) {
  return { H: `${l.home} vinder`, D: "Uafgjort", A: `${l.away} vinder`, O: "Over 2,5 mål", U: "Under 2,5 mål",
    Y: "Begge hold scorer", N: "Ikke begge hold scorer", S: `${l.player} scorer` }[l.sel];
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
const shortDay = (iso) => new Intl.DateTimeFormat("da-DK", { day: "numeric", month: "short", year: "numeric" }).format(new Date(iso));

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
    const saved = store.get();
    if (saved) {
      try { TIPS = await advDecrypt(saved, "data/tips.enc.json"); } catch { /* ask for the password below */ }
    }
  }
  if (!TIPS) return renderTipsLock();
  renderTips();
}

function renderTipsLock(error) {
  app.innerHTML = `
    <h1>Betting</h1>
    <p class="lede">Dagens singler og kombi'er, stigen og målscorere, og hvordan det er gået. Samme kodeord som Avanceret.</p>
    <form class="panel lock" id="bt-lock" autocomplete="on">
      <svg class="lock-ic" width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="10" width="14" height="10" rx="2.5"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>
      <label for="bt-pw">Kodeord</label>
      <div class="lock-row">
        <input id="bt-pw" name="password" type="password" autocomplete="current-password" required>
        <button type="submit">Lås op</button>
      </div>
      <p class="lock-err" aria-live="polite">${error || ""}</p>
    </form>`;
  const form = app.querySelector("#bt-lock");
  const input = form.querySelector("input");
  input.focus({ preventScroll: true });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button");
    btn.disabled = true;
    btn.textContent = "Låser op…";
    try {
      TIPS = await advDecrypt(input.value, "data/tips.enc.json");
      store.set(input.value);
      renderTips();
      enhance(app);
    } catch (err) {
      console.error(err);
      renderTipsLock(err.message === "wrong-password" ? "Forkert kodeord. Prøv igen."
        : err.message.includes("404") ? "Der er ingen tips endnu." : "Data kunne ikke åbnes. Genindlæs siden.");
    }
  });
}

function renderTips() {
  const L = TIPS.live, H = TIPS.history;
  const cards = TIPS.cards;
  const latest = cards[cards.length - 1];
  const enoughLive = L.singles.n >= 30;
  const acc = enoughLive ? L.singles : H.singles;
  const legsAcc = L.legs >= 30 ? { hit: L.leg_hit, exp: L.leg_expected, n: L.legs, live: true } : { hit: H.leg_hit, exp: H.leg_expected, n: H.legs };

  app.innerHTML = `
    <div class="adv-head"><h1>Betting</h1><button class="ghost" id="bt-relock" type="button">Lås igen</button></div>
    <p class="lede">For sjov. Chancerne er Betfair Exchanges priser uden margin, den skarpeste vurdering vi har; vores egen målmodel slog den ikke. Odds er bet365's. Ingen tips har en fordel: bet365's margin gør, at en single i snit taber omkring 3–5%, og en kombi omkring 11–13%. Tryk på et spil for begrundelsen.</p>

    <div class="recs" style="margin-top:20px">
      ${panel(`<span class="v">${pct(legsAcc.hit)}</span><span class="t">Modellens træfsikkerhed</span><span class="d">${legsAcc.live ? `${legsAcc.n} afgjorte udfald` : `Historisk test, ${legsAcc.n.toLocaleString("da-DK")} udfald`}. Chancerne lovede ${pct(legsAcc.exp)}: når de siger 70%, sker det ca. 70% af gangene.</span>`, "rec")}
      ${panel(`<span class="v">${pct(acc.hit)}</span><span class="t">Singler ramt</span><span class="d">${enoughLive ? `${acc.won} af ${acc.n} afgjorte` : `Historisk test, ${acc.n.toLocaleString("da-DK")} tips`}. Lovet ${pct(acc.expected)}.</span>`, "rec")}
      ${panel(`<span class="v">${L.accas.n ? `${L.accas.won}/${L.accas.n}` : pct(H.accas.hit)}</span><span class="t">Kombi'er vundet</span><span class="d">${L.accas.n ? `Lovet ${pct(L.accas.expected)} i snit.` : `Historisk test: ${H.accas.won} af ${H.accas.n}, lovet ${pct(H.accas.expected)}.`}</span>`, "rec")}
      ${panel(`<span class="v">${L.singles.staked + L.accas.staked ? units(L.singles.profit + L.accas.profit) : "0"}</span><span class="t">Enheder siden start</span><span class="d">1 enhed per tip. Historisk: singler ${roiTxt(H.singles.roi)}, kombi'er ${roiTxt(H.accas.roi)} per enhed.</span>`, "rec")}
    </div>

    ${ladderHtml()}

    <section class="sec">
      <div class="sec-head"><div><h2>${latest ? `Kupon ${day(latest.published || latest.id)}` : "Ingen kupon endnu"}</h2>
        <p class="lede">${latest ? `Kampe de næste 24 timer, offentliggjort ${dateOnly(latest.published)}. Odds hentet ${latest.odds_as_of ? dateOnly(latest.odds_as_of) : "ukendt"}; bet365 kan have flyttet dem siden. Kuponen ændres aldrig, når den er lagt ud.` : "Første kupon kommer kl. 11 eller 15."}</p></div></div>
      ${latest ? cardHtml(latest) : ""}
    </section>

    ${scorerListHtml()}

    <section class="sec">
      <div class="sec-head"><div><h2>Afgjorte tips</h2><p class="lede">Alle tips, når kampene er spillet.</p></div>
        <div class="seg" id="bt-done" role="group" aria-label="Type"><button type="button" data-done="singles">Singler</button><button type="button" data-done="accas">Kombi'er</button></div></div>
      <div id="bt-done-box"></div>
    </section>

    <section class="sec">
      <div class="sec-head"><div><h2>Nøjagtighed</h2><p class="lede">Rammer tipsene så tit, som chancerne siger? Historisk test: de samme regler kørt på hver kampdag ${H.first.slice(0, 4)}–${H.last.slice(0, 4)} i ${H.matches.toLocaleString("da-DK")} kampe med priserne fra før kampene.</p></div></div>
      ${accuracyHtml(L, H)}
    </section>
    <p class="small muted" style="margin-top:20px">Opdateret ${dateOnly(TIPS.updated)}. Kun til underholdning. Spil ansvarligt; hjælp på stopspillet.dk.</p>`;

  app.querySelector("#bt-relock").addEventListener("click", () => { TIPS = null; ADV = null; store.clear(); renderTipsLock(); });
  app.querySelectorAll("#bt-done button").forEach((b) => b.addEventListener("click", () => { TIPS_STATE.done = b.dataset.done; drawDone(); }));
  app.querySelectorAll("#bt-lad-log button").forEach((b) => b.addEventListener("click", () => { TIPS_STATE.ladderLog = b.dataset.log; drawLadderLog(); }));
  drawDone();
  drawLadderLog();
  bindTips(app);
}

function legRow(l, extra = "") {
  return `<tr><td class="l"><span data-tip="${esc(reasons(l))}"><b>${esc(pick(l))}</b></span><span class="bt-sub">${esc(l.home)} – ${esc(l.away)} · ${esc(league(l))} · ${kickoff(l)}</span></td>
    ${extra}<td class="pts">${price(l)}</td><td>${pct(l.p)}${l.conf ? `<span class="bt-sub">ramte ${pct(l.conf.obs)}</span>` : ""}</td><td class="opt">${l.ev == null ? "–" : roiTxt(l.ev)}</td><td>${l.score ? `<span class="muted">${esc(l.score)}</span> ` : ""}${status(l)}</td></tr>`;
}
const LEG_HEAD = `<thead><tr><th class="l">Spil</th><th>Odds</th><th>Chance</th><th class="opt">Forventet</th><th>Status</th></tr></thead>`;

function cardHtml(c) {
  const singles = SINGLE_KINDS.map((k) => {
    const ls = c.singles.filter((l) => l.kind === k);
    if (!ls.length) return "";
    return `<div class="panel bt-block"><h3>${KIND[k][0]}</h3><p class="small muted">${KIND[k][1]}</p>
      <div class="scroll"><table class="advt">${LEG_HEAD}<tbody>${ls.map((l) => legRow(l)).join("")}</tbody></table></div></div>`;
  }).join("");
  const accas = c.accas.map((a) => `<div class="panel bt-block"><h3>${KIND[a.kind][0]} ${status(a)}</h3>
      <p class="small muted">${KIND[a.kind][1]} Samlet odds <b class="strong">${odds(a.price)}</b>, chance ${pct(a.p, 1)}, forventet ${roiTxt(a.ev)}.</p>
      <div class="scroll"><table class="advt">${LEG_HEAD}<tbody>${a.legs.map((l) => legRow(l)).join("")}</tbody></table></div></div>`).join("");
  return `<div class="bt-card">${singles}${accas}</div>`;
}

// ---------------------------------------------------------------- ladder

function ladderHtml() {
  const lad = TIPS.ladder || { runs: [] };
  const run = lad.runs[lad.runs.length - 1];
  const H = TIPS.history.ladder, R = TIPS.rules;
  const today = run ? run.bets.filter((b) => b.day === run.bets[run.bets.length - 1].day) : [];
  const head = `<thead><tr><th class="l">Spil</th><th>Indsats</th><th>Odds</th><th>Udbetaling</th><th>Chance</th><th>Status</th></tr></thead>`;
  const row = (b) => `<tr><td class="l"><span data-tip="${esc(reasons(b))}"><b>${b.of > 1 ? `${b.order}. ` : ""}${esc(pick(b))}</b></span><span class="bt-sub">${esc(b.home)} – ${esc(b.away)} · ${esc(league(b))} · ${kickoff(b)}</span></td>
    <td>${b.stake == null ? "–" : kr(b.stake)}${b.if_won ? `<span class="bt-sub">hvis forrige går hjem</span>` : ""}</td><td class="pts">${odds(b.price)}</td><td>${b.payout == null ? "–" : kr(b.payout)}</td>
    <td>${pct(b.p)}</td><td>${b.score ? `<span class="muted">${esc(b.score)}</span> ` : ""}${status(b)}</td></tr>`;
  const state = !run ? "Stigen starter ved første kørsel med et spil i intervallet."
    : run.status === "broken" ? `Forsøg ${run.id} røg efter ${run.steps} trin. Næste spil starter forfra med ${kr(R.ladder_start)}`
    : `Forsøg ${run.id}: ${run.steps} trin klaret, ${kr(run.stake)} i spil nu.`;
  return `<section class="sec">
    <div class="sec-head"><div><h2>Stigen</h2><p class="lede">Start med ${kr(R.ladder_start)}, sæt hele udbetalingen på næste spil til bet365-odds ${num(R.ladder_odds[0], 2)}–${num(R.ladder_odds[1], 2)}, og start forfra med ${kr(R.ladder_start)} efter et tab. Ét spil om dagen; lørdag og søndag en kæde, hvor hvert spil starter efter det forrige er slut og kun spilles, hvis det forrige gik hjem. Kun ligaer med resultater samme dag.</p></div></div>
    <div class="recs">
      ${panel(`<span class="v">${run && run.status === "alive" ? run.steps : 0}</span><span class="t">Trin i det nuværende forsøg</span><span class="d">${state}</span>`, "rec")}
      ${panel(`<span class="v">${H.best ? H.best.steps : 0}</span><span class="t">Længste stige i testen</span><span class="d">${H.best ? `${shortDay(H.best.start)}–${shortDay(H.best.end)}, op til ${kr(H.best.peak)}.` : ""} Et forsøg holdt i snit ${num(H.avg_steps || 0, 1)} trin (${H.runs} forsøg, ${H.bets} spil, ramte ${pct(H.hit)} mod lovet ${pct(H.expected)}).</span>`, "rec")}
    </div>
    ${today.length ? `<div class="panel bt-block" style="margin-top:12px"><h3>${today.length > 1 ? `Dagens kæde, ${today.length} spil` : "Dagens spil"}</h3>
      <p class="small muted">Odds hentet ${today[0].odds_as_of ? dateOnly(today[0].odds_as_of) : "ukendt"}. Ligger bet365 uden for ${num(R.ladder_odds[0], 2)}–${num(R.ladder_odds[1], 2)}, når du spiller, er det ikke stigens spil.</p>
      <div class="scroll"><table class="advt">${head}<tbody>${today.map(row).join("")}</tbody></table></div></div>` : ""}
    <div class="panel bt-block" style="margin-top:12px">
      <div class="sec-head" style="margin-bottom:6px"><h3 style="margin:0">Forsøg</h3>
        <div class="seg" id="bt-lad-log" role="group" aria-label="Log"><button type="button" data-log="live">Live</button><button type="button" data-log="hist">Historisk test</button></div></div>
      <div id="bt-lad-log-box"></div>
    </div>
  </section>`;
}

function drawLadderLog() {
  const box = app.querySelector("#bt-lad-log-box");
  if (!box) return;
  app.querySelectorAll("#bt-lad-log button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.log === TIPS_STATE.ladderLog));
  const log = TIPS_STATE.ladderLog === "live" ? (TIPS.ladder_live?.log || []) : (TIPS.history.ladder.log || []);
  if (!log.length) { box.innerHTML = `<p class="muted small">Ingen forsøg endnu.</p>`; return; }
  const max = Math.max(...log.map((r) => r.steps), 1);
  box.innerHTML = `<div class="scroll"><table class="advt"><thead><tr><th>#</th><th class="l">Periode</th><th class="l">Nåede</th><th>Højest</th><th class="l">Røg på</th></tr></thead><tbody>
    ${[...log].reverse().map((r) => `<tr><td class="muted">${r.id}</td><td class="l">${shortDay(r.start)}${r.end !== r.start ? `–${shortDay(r.end)}` : ""}</td>
      <td class="l"><span class="bt-steps"><i style="width:${(r.steps / max) * 100}%"></i></span> <b>${r.steps}</b> trin</td><td>${kr(r.peak)}</td>
      <td class="l">${r.status === "alive" ? `<span class="bt-res open">Lever</span>` : r.broke ? `${esc(pick(r.broke))}<span class="bt-sub">${esc(r.broke.home)} – ${esc(r.broke.away)} ${esc(r.broke.score || "")}, odds ${odds(r.broke.price)}</span>` : "–"}</td></tr>`).join("")}
  </tbody></table></div>`;
  bindTips(box);
}

// ---------------------------------------------------------------- goalscorers

function scorerListHtml() {
  const S = TIPS.scorers;
  if (!S) return "";
  return `<section class="sec">
    <div class="sec-head"><div><h2>Målscorere, runde ${S.gw}</h2><p class="lede">Premier Leagues ${S.players.length} mest sandsynlige målscorere ifølge FPL-modellen (midtbane og angreb; forsvarsspillere overvurderes). Fair odds er 1 / chance: bet365 skal give mere, før spillet er pengene værd. Tryk for begrundelsen.</p></div></div>
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
    const all = cards.flatMap((c) => c.singles.map((l) => ({ ...l, card: c.id })));
    const col = (res, title) => {
      const ls = all.filter((l) => l.res === res);
      return `<div class="panel bt-bracket ${res}"><h3>${title} <span class="muted">${ls.length}</span></h3>
        ${ls.length ? `<ul class="bt-list">${ls.map((l) => `<li><span><b data-tip="${esc(reasons(l))}">${esc(pick(l))}</b><span class="bt-sub">${esc(l.home)} – ${esc(l.away)} ${esc(l.score || "")} · ${KIND[l.kind][0]} · ${l.date}</span></span>
          <span class="bt-num">${price(l)}<small>${l.price ? units(l.res === "won" ? l.price - 1 : -1) : `chance ${pct(l.p)}`}</small></span></li>`).join("")}</ul>` : `<p class="muted small">Ingen endnu.</p>`}</div>`;
    };
    box.innerHTML = `<div class="cols2">${col("won", "Vundet")}${col("lost", "Tabt")}</div>`;
  } else {
    const all = cards.flatMap((c) => c.accas.map((a) => ({ ...a, card: c.id })));
    const col = (res, title) => {
      const as = all.filter((a) => a.res === res);
      return `<div class="panel bt-bracket ${res}"><h3>${title} <span class="muted">${as.length}</span></h3>
        ${as.length ? `<ul class="bt-list">${as.map((a) => {
          const missed = a.legs.filter((l) => l.res === "lost");
          return `<li><span><b>${KIND[a.kind][0]}, ${a.card}</b><span class="bt-sub">${a.legs_hit} af ${a.legs.length} ben ramt${missed.length ? `. Galt: ${missed.map((l) => `${esc(pick(l))} (${esc(l.home)} – ${esc(l.away)} ${esc(l.score || "")})`).join(", ")}` : ""}</span></span>
            <span class="bt-num">${odds(a.price)}<small>${units(a.res === "won" ? a.paid - 1 : -1)}</small></span></li>`;
        }).join("")}</ul>` : `<p class="muted small">Ingen endnu.</p>`}</div>`;
    };
    box.innerHTML = `<div class="cols2">${col("won", "Vundet")}${col("lost", "Tabt")}</div>`;
  }
  bindTips(box);
}

// ---------------------------------------------------------------- accuracy

// scorers have no price history: their test is the 2025/26 replay, top 3 per round (scripts/scorer_check.py)
function scorerRow(L) {
  const T = TIPS.scorer_test, l = L.kinds.scorer;
  if (!T) return "";
  const live = l && l.n ? `${pct(l.hit)} <span class="muted">/ ${pct(l.expected)} · ${l.n}</span>` : `<span class="muted">${l && l.pending ? `${l.pending} afventer` : "–"}</span>`;
  return `<tr><td class="l">${KIND.scorer[0]}</td><td>${live}</td><td class="strong">${pct(T.top3.hit, 1)}</td><td>${pct(T.top3.expected, 1)}</td><td class="muted">${T.top3.n}</td>
    <td class="muted">–</td><td class="muted">–</td></tr>`;
}

function accuracyHtml(L, H) {
  const row = (k) => {
    const l = L.kinds[k], h = H.kinds[k];
    if (!h) return "";
    const live = l && l.n ? `${pct(l.hit)} <span class="muted">/ ${pct(l.expected)} · ${l.n}</span>` : `<span class="muted">${l && l.pending ? `${l.pending} afventer` : "–"}</span>`;
    return `<tr><td class="l">${KIND[k][0]}</td><td>${live}</td><td class="strong">${pct(h.hit, 1)}</td><td>${pct(h.expected, 1)}</td><td class="muted">${h.n.toLocaleString("da-DK")}</td>
      <td class="${h.roi >= 0 ? "delta-up" : "delta-down"}">${roiTxt(h.roi)}</td><td class="muted">${roiTxt(h.exp_roi)}</td></tr>`;
  };
  const cal = (S) => S.cal.map((b) => `<tr><td class="l">${Math.round(b.lo * 100)}–${Math.round(b.hi * 100)}%</td><td>${pct(b.pred, 1)}</td><td class="strong">${pct(b.obs, 1)}</td><td class="muted">${b.n.toLocaleString("da-DK")}</td>
      <td class="l"><span class="calbar"><i class="p" style="left:${b.pred * 100}%"></i><i class="o" style="left:${b.obs * 100}%"></i></span></td></tr>`).join("");
  const miss = H.acca_missed;
  const nA = H.accas.n;
  const T = TIPS.scorer_test, E = H.kinds.edge;
  return `
    <div class="panel"><div class="scroll"><table class="advt">
      <thead><tr><th class="l">Type</th><th>Live: ramt / lovet · antal</th><th>Historisk ramt</th><th>Lovet</th><th>Tips</th><th>Afkast</th><th>Forventet</th></tr></thead>
      <tbody>${["banker", "value", "edge", "goals", "safe", "long"].map(row).join("")}${scorerRow(L)}</tbody></table></div></div>
    <p class="small muted" style="margin-top:10px">Afkast er per enhed ved bet365's odds. "Forventet" er det, chancerne siger, man taber i snit. Forskellen er held.${E && E.n ? ` Value-spillene lovede ${roiTxt(E.exp_roi)}, men gav ${roiTxt(E.roi)} og ramte ${pct(E.hit, 1)} mod lovet ${pct(E.expected, 1)}: når bet365 ligger over den rigtige chance, er det oftest bet365, der har ret.` : ""} Langskud-kombi'erne har historisk ramt oftere end lovet, men det er få gevinster, og det kan være tilfældigt.${T ? ` Målscorere er testet på runde ${T.rounds[0]}–${T.rounds[1]} af 2025/26 (modellens tre bedste bud per runde, ${T.top3.n} tips: få, så usikkert). På alle ${T.n.toLocaleString("da-DK")} midtbane- og angrebsspillere holder chancerne: ${T.cal.filter((b) => b.lo >= 0.1).map((b) => `sagt ${pct(b.pred)}, scorede ${pct(b.obs)}`).join("; ")}.` : ""}</p>

    <div class="cols2" style="margin-top:16px">
      <div class="panel"><h3 style="margin:0 0 4px">Holder chancerne?</h3><p class="small muted">Alle ben historisk, grupperet efter chance. Det er her, "sikkerheden" på hvert tip kommer fra. <span class="key-dot p"></span>lovet <span class="key-dot o"></span>ramt.</p>
        <div class="scroll"><table class="advt"><thead><tr><th class="l">Chance</th><th>Lovet</th><th>Ramt</th><th>Ben</th><th class="l"></th></tr></thead><tbody>${cal(H)}</tbody></table></div>
        ${L.cal.length ? `<p class="small muted" style="margin-top:10px">Live indtil nu: ${L.legs} ben, ramt ${pct(L.leg_hit)} mod lovet ${pct(L.leg_expected)}.</p>` : ""}</div>
      <div class="panel"><h3 style="margin:0 0 4px">Tæt på</h3><p class="small muted">Kombi'er historisk, efter hvor mange ben der gik galt.</p>
        <dl class="kv">${Object.keys(miss).sort().map((k) => `<dt>${k === "0" ? "Vundet" : k === "1" ? "Galt på ét ben" : `Galt på ${k} ben`}</dt><dd>${miss[k]} <span class="muted">(${pct(miss[k] / nA)})</span></dd>`).join("")}</dl>
        ${L.accas.n ? `<p class="small muted" style="margin-top:10px">Live: ${Object.entries(L.acca_missed).map(([k, v]) => `${k === "0" ? "vundet" : `galt på ${k}`}: ${v}`).join(", ")}.</p>` : ""}</div>
    </div>`;
}

VIEWS.betting = viewBetting;
