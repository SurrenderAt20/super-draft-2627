"use strict";
// Prognose, Waivers and Mit hold: the projection pages inside Avanceret spillerdata.
// Everything here reads ADV (decrypted in adv.js); nothing is visible without the password.

const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500"];   // categorical slots, dark mode
const FORM = { GKP: { min: 1, max: 1 }, DEF: { min: 3, max: 5 }, MID: { min: 2, max: 5 }, FWD: { min: 1, max: 3 } };
const PROG = { picks: null, horizon: 6, pos: "ALL", owner: "all", fixMode: "att" };
const WAIV = { horizon: 3, pos: "ALL" };
const HOLD = { horizon: 3 };

// ---------------------------------------------------------------- data helpers

const projOf = (pid) => ADV.proj.by_player[pid] || [];
const sumH = (pid, h) => projOf(pid).slice(0, h).reduce((a, b) => a + b, 0);
const teamShort = (t) => ADV.teams[t]?.short ?? "?";
const playerById = (pid) => ADV.players.find((p) => p.id === pid);
const isAvailable = (p) => !p.status || p.status === "a" || p.status === "d";

function fixturesOf(p, n) {
  return (ADV.fixtures[p.team] || []).slice(0, n);
}

function fixChips(p, n, mode) {
  return `<span class="fx-chips">${fixturesOf(p, n).map((f) => {
    const good = mode === "def" || ["GKP", "DEF"].includes(p.pos) ? Math.exp(-f.ga) : f.gf;
    const scale = mode === "def" || ["GKP", "DEF"].includes(p.pos) ? [0.15, 0.45] : [0.9, 2.0];
    const t = Math.max(0, Math.min(1, (good - scale[0]) / (scale[1] - scale[0])));
    const eu = f.euro_h != null ? `, ${Math.round(f.euro_h / 24)} dage efter europæisk kamp` : "";
    return `<i class="fxc${f.euro_h != null ? " eu" : ""}" style="--t:${t.toFixed(2)}" title="Runde ${f.gw}: ${teamShort(f.opp)} ${f.home ? "hjemme" : "ude"}${eu}">${teamShort(f.opp)}${f.home ? "" : "<small>u</small>"}</i>`;
  }).join("")}</span>`;
}

function seasonSum(pid, key) {
  const i = ADV.cols.indexOf(key);
  return ADV.gws.reduce((a, gw) => a + (ADV.by_gw[gw]?.[pid]?.[i] ?? 0), 0);
}
function recentPts(pid, n) {
  const i = ADV.cols.indexOf("pt");
  return ADV.gws.slice(-n).reduce((a, gw) => a + (ADV.by_gw[gw]?.[pid]?.[i] ?? 0), 0);
}

// a short plain-language reason a player is worth a look
function reasonFor(p) {
  const d = ADV.proj.detail[p.id] || {};
  const bits = [];
  if (d.p60 >= 0.8) bits.push("fast starter");
  else if (d.p60 >= 0.5) bits.push("spiller det meste");
  else bits.push("usikre minutter");
  const mi = seasonSum(p.id, "mi");
  if (["MID", "FWD"].includes(p.pos) && mi) {
    const xgi90 = (seasonSum(p.id, "xgi") * 90) / mi;
    if (xgi90 >= 0.35) bits.push(`xGI ${num(xgi90, 2)} per 90`);
  }
  if (["GKP", "DEF"].includes(p.pos) && d.cs >= 0.33) bits.push(`${Math.round(d.cs * 100)}% chance for clean sheet næste runde`);
  if (["DEF", "MID"].includes(p.pos) && d.dc >= 0.4) bits.push(`når DefCon i ${Math.round(d.dc * 100)}% af kampene`);
  const fx = fixturesOf(p, 3);
  if (fx.length) {
    const att = fx.reduce((a, f) => a + f.gf, 0) / fx.length;
    const cs = fx.reduce((a, f) => a + Math.exp(-f.ga), 0) / fx.length;
    const easy = ["GKP", "DEF"].includes(p.pos) ? cs >= 0.32 : att >= 1.55;
    const hard = ["GKP", "DEF"].includes(p.pos) ? cs <= 0.2 : att <= 1.15;
    if (easy) bits.push("let program");
    if (hard) bits.push("svært program");
  }
  const pen = ADV.proj.pens?.[p.id];
  if (pen === 1) bits.push("første straffeskytte");
  if (p.status === "d") bits.push(`tvivlsom: ${p.news || "ukendt"}`);
  return bits.join(", ");
}

// best XI for one round: 1 GKP, at least 3 DEF, 2 MID, 1 FWD, 11 in all
function bestXI(squad, j) {
  const by = { GKP: [], DEF: [], MID: [], FWD: [] };
  squad.forEach((p) => by[p.pos]?.push({ p, v: projOf(p.id)[j] ?? 0 }));
  Object.values(by).forEach((l) => l.sort((a, b) => b.v - a.v));
  const xi = [];
  const count = { GKP: 0, DEF: 0, MID: 0, FWD: 0 };
  const take = (pos) => { const x = by[pos].shift(); if (x) { xi.push(x); count[pos] += 1; } };
  take("GKP");
  for (const pos of ["DEF", "MID", "FWD"]) for (let i = 0; i < FORM[pos].min; i++) take(pos);
  const rest = ["DEF", "MID", "FWD"].flatMap((pos) => by[pos].map((x) => ({ ...x, pos }))).sort((a, b) => b.v - a.v);
  for (const x of rest) {
    if (xi.length >= 11) break;
    if (count[x.pos] < FORM[x.pos].max) { xi.push(x); count[x.pos] += 1; }
  }
  return { xi, total: xi.reduce((a, x) => a + x.v, 0), count };
}
const xiOver = (squad, h) => Array.from({ length: h }, (_, j) => bestXI(squad, j).total).reduce((a, b) => a + b, 0);

function subnav(active) {
  const items = [["", "Spillerdata"], ["prognose", "Prognose"], ["waivers", "Waivers"], ["hold", "Mit hold"], ["noejagtighed", "Nøjagtighed"]];
  return `<nav class="subnav" aria-label="Avanceret">${items.map(([k, l]) => `<a href="#avanceret${k ? "/" + k : ""}"${k === active ? ' aria-current="page"' : ""}>${l}</a>`).join("")}</nav>`;
}

function horizonSelect(id, value) {
  return `<label>Periode<select id="${id}">${[[1, "Næste runde"], [3, "Næste 3 runder"], [6, "Næste 6 runder"]].map(([v, l]) => `<option value="${v}"${v === value ? " selected" : ""}>${l}</option>`).join("")}</select></label>`;
}

function modelNote() {
  const b = ADV.backtest;
  if (!b) return "";
  const r = b.rank, r0 = b.rank_base;
  const pc = (x) => `${Math.round(x * 100)}%`;
  const acc = r && r.pair_acc != null ? `<div class="acc">
      <div class="acc-big"><b>${pc(r.pair_acc)}</b><span>rigtige sammenligninger</span></div>
      <p>Når modellen siger, at spiller A scorer flere point end spiller B i de kommende runder, havde den ret i <b>${pc(r.pair_acc)}</b> af tilfældene (${r.players} spillere, runde ${r.from + 1}–${r.to} forudsagt kun ud fra runde 1–${r.from}). Et rent gæt giver 50%, og point i de seneste runder alene ${pc(r.pair_acc_form)}.</p>
      <ul class="acc-buckets">${r.buckets.map((b) => `<li><span>Forudsagt forskel ${b.hi ? `${num(b.lo, 1)}–${num(b.hi, 1)}` : `over ${num(b.lo, 1)}`} point per runde</span><b>${b.acc != null ? pc(b.acc) : "–"}</b></li>`).join("")}</ul>
      <p class="small muted">Jo større forskel modellen ser, jo mere kan du stole på den. Under et halvt point per runde er det næsten plat eller krone.</p>
    </div>` : "";
  const rank = r && r0 ? `${acc}<p>Sammenhængen mellem forudsagte og faktiske point var <b>${num(r.corr, 2)}</b>, og <b>${r.top30} af modellens top 30</b> var blandt de 30 bedste. Uden sidste sæson og straffeskytter var det ${num(r0.corr, 2)} og ${r0.top30} af 30.</p>` : "";
  return `<div class="panel model-note">
    <h3>Hvor godt rammer modellen?</h3>
    ${rank}
    ${b.odds_check ? `<p>Bookmakerodds bruges for de kommende kampe, hvor de findes (typisk de næste 1–2 runder). I ${b.odds_check.n} spillede kampe ramte odds holdenes xG bedre end modellens egen regression: i snit ${num(b.odds_check.rmse_odds, 2)} mål ved siden af per hold mod ${num(b.odds_check.rmse_model, 2)}. Derfor vægter odds ${Math.round(b.odds_check.w * 100)}%, hvor de findes. Kilder: The Odds API og football-data.co.uk.</p>` : ""}
    <p>Runde for runde, testet på runde ${b.gws[0]}–${b.gws[b.gws.length - 1]} hvor hver runde blev forudsagt kun ud fra runderne før: i snit <b>${num(b.mae, 2)} point</b> ved siden af per spiller. Et simpelt formsnit ramte ${num(b.mae_form, 2)} ved siden af.</p>
    <p class="small muted">Modellen bygger på xG, xA, minutter, modstandernes styrke, sidste sæson (2025/26, den første sæson med DefCon) og hvem der tager straffe. Point i én runde er meget tilfældige, så brug tallene til at sammenligne spillere over flere runder. Modellen ser minutter, ikke træningsnyheder: en spiller på vej tilbage fra skade er undervurderet, indtil han spiller igen. Faste startere mister ifølge sidste sæsons data næsten ingen minutter efter europæiske kampe, så det flag er til information.</p>
  </div>`;
}

// ---------------------------------------------------------------- Prognose

function projChart(pids) {
  const past = ADV.gws.slice(-6);
  const fut = ADV.proj.gws;
  const xs = [...past.map((g) => ({ gw: g, past: true })), ...fut.map((g) => ({ gw: g, past: false }))];
  const W = Math.max(320, Math.min(1060, app.clientWidth - 22));
  const narrow = W < 560;
  const L = 34, R = narrow ? 14 : 92, T = 14, B = 36, H = narrow ? 260 : 300;
  const xi = ADV.cols.indexOf("xpt"), pi = ADV.cols.indexOf("pt");
  const vals = pids.flatMap((pid) => [...past.flatMap((g) => [ADV.by_gw[g]?.[pid]?.[xi] ?? 0, ADV.by_gw[g]?.[pid]?.[pi] ?? 0]), ...projOf(pid)]);
  const max = Math.max(4, Math.ceil(Math.max(...vals) + 0.5));
  const step = (W - L - R) / (xs.length - 1 || 1);
  const x = (i) => L + i * step;
  const y = (v) => T + (1 - Math.max(0, v) / max) * (H - T - B);
  const ticks = [];
  for (let t = 0; t <= max; t += max > 10 ? 4 : 2) ticks.push(t);
  const split = x(past.length - 0.5);

  let svg = `<g class="grid">${ticks.map((t) => `<line x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/>`).join("")}</g>
    <g class="axis">${ticks.map((t) => `<text x="${L - 8}" y="${y(t) + 4}" text-anchor="end">${t}</text>`).join("")}
    ${xs.map((d, i) => `<text x="${x(i)}" y="${H - 14}" text-anchor="middle">${narrow && i % 2 ? "" : "R" + d.gw}</text>`).join("")}</g>
    <line class="now" x1="${split}" x2="${split}" y1="${T}" y2="${H - B}"/>
    <text class="now-l" x="${split + 6}" y="${T + 10}">Prognose</text><text class="now-l" x="${split - 6}" y="${T + 10}" text-anchor="end">Spillet</text>`;

  const ends = [];
  pids.forEach((pid, s) => {
    const c = SERIES[s];
    const pastXP = past.map((g, i) => [x(i), y(ADV.by_gw[g]?.[pid]?.[xi] ?? 0)]);
    const futXP = projOf(pid).map((v, i) => [x(past.length + i), y(v)]);
    const path = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
    svg += `<path d="${path(pastXP)}" fill="none" stroke="${c}" stroke-width="2" stroke-dasharray="4 4" opacity=".7"/>`;
    svg += `<path d="${path([pastXP[pastXP.length - 1], ...futXP])}" fill="none" stroke="${c}" stroke-width="2.5"/>`;
    past.forEach((g, i) => {
      const v = ADV.by_gw[g]?.[pid]?.[pi];
      if (v != null) svg += `<circle cx="${x(i)}" cy="${y(v)}" r="4" fill="${c}" opacity=".45"/>`;
    });
    futXP.forEach(([px, py]) => (svg += `<circle cx="${px}" cy="${py}" r="4" fill="${c}" stroke="var(--bg)" stroke-width="2"/>`));
    if (!narrow) ends.push({ y: futXP[futXP.length - 1][1], x: futXP[futXP.length - 1][0], name: playerById(pid).name, c });
  });

  // end-of-line names, nudged apart so they never overlap
  ends.sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) ends[i].y = Math.max(ends[i].y, ends[i - 1].y + 15);
  ends.forEach((e) => (svg += `<text x="${e.x + 10}" y="${e.y + 4}" font-size="12.5" font-weight="600" style="fill:var(--text)">${esc(e.name)}</text>`));

  // one hover/tap column per round
  xs.forEach((d, i) => {
    const lines = pids.map((pid, s) => {
      const p = playerById(pid);
      if (d.past) {
        const v = ADV.by_gw[d.gw]?.[pid];
        return `<span style="color:${SERIES[s]}">●</span> ${esc(p.name)}: ${v ? `${v[pi]} point, xP ${num(v[xi], 1)}` : "spillede ikke"}`;
      }
      const j = i - past.length;
      const f = (ADV.fixtures[p.team] || []).filter((f) => f.gw === d.gw).map((f) => `${teamShort(f.opp)} ${f.home ? "h" : "u"}`).join(", ") || "ingen kamp";
      return `<span style="color:${SERIES[s]}">●</span> ${esc(p.name)}: ${num(projOf(pid)[j] ?? 0, 1)} xP (${f})`;
    }).join("<br>");
    svg += `<rect class="col-hit" x="${x(i) - step / 2}" y="${T}" width="${step}" height="${H - T - B}" data-tip="${esc(`<b>Runde ${d.gw}${d.past ? "" : " (prognose)"}</b>${lines}`)}"/>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Point og forventede point per runde">${svg}</svg>`;
}

function renderPrognose() {
  if (!PROG.picks) {
    PROG.picks = ADV.players.filter((p) => p.owner === null && isAvailable(p))
      .sort((a, b) => sumH(b.id, 6) - sumH(a.id, 6)).slice(0, 3).map((p) => p.id);
  }
  const names = ADV.players.filter((p) => seasonSum(p.id, "mi") > 0).sort((a, b) => a.name.localeCompare(b.name, "da"));
  const fut = ADV.proj.gws;

  app.innerHTML = `
    ${advHead()}
    ${subnav("prognose")}
    <p class="lede">Forventede point for de næste ${fut.length} runder ud fra spillernes underliggende tal, minutter og modstandernes styrke.</p>

    <section class="sec">
      <div class="sec-head"><div><h2>Kurve</h2><p class="lede">Prikker er faktiske point, stiplet linje er xP i de spillede runder, fuld linje er prognosen. Op til fire spillere.</p></div></div>
      <div class="panel curve-pick">
        <div class="chips-picked" id="picked">${PROG.picks.map((pid, i) => `<button type="button" class="pchip" data-pid="${pid}" style="--c:${SERIES[i]}"><i></i>${esc(playerById(pid).name)}<span aria-hidden="true">×</span><span class="sr">Fjern</span></button>`).join("")}</div>
        <label class="add-player">Tilføj spiller<input id="add-pl" list="pl-list" placeholder="Skriv et navn" ${PROG.picks.length >= 4 ? "disabled" : ""}></label>
        <datalist id="pl-list">${names.map((p) => `<option value="${esc(p.name)} (${esc(p.club)})"></option>`).join("")}</datalist>
      </div>
      <div class="panel chart proj-chart">${PROG.picks.length ? projChart(PROG.picks) : '<p class="adv-empty">Vælg en spiller for at se kurven.</p>'}</div>
    </section>

    <section class="sec">
      <div class="sec-head"><div><h2>Højeste prognoser</h2><p class="lede">Forventede point per runde med modstander. Grønnere felt betyder flere forventede point.</p></div></div>
      <div class="panel adv-controls"><div class="adv-filters">
        <label>Ejer<select id="pg-owner"><option value="all">Alle spillere</option><option value="free">Kun ledige</option>${Object.entries(ADV.managers).sort((a, b) => a[1].localeCompare(b[1], "da")).map(([le, n]) => `<option value="${le}">${esc(n)}</option>`).join("")}</select></label>
        <div class="seg" id="pg-pos" role="group" aria-label="Position">${["ALL", "GKP", "DEF", "MID", "FWD"].map((p) => `<button type="button" data-pos="${p}">${p === "ALL" ? "Alle" : p}</button>`).join("")}</div>
      </div></div>
      <div class="panel adv-table"><div class="scroll matrix" id="pg-box"></div></div>
    </section>

    <section class="sec">
      <div class="sec-head"><div><h2>Kampprogram</h2><p class="lede">Hvert holds næste ${fut.length} kampe. Angreb: forventede mål for holdet. Forsvar: chancen for clean sheet. En lilla prik betyder europæisk kamp få dage før.</p></div>
        <div class="seg" id="fx-mode" role="group" aria-label="Visning"><button type="button" data-m="att">Angreb</button><button type="button" data-m="def">Forsvar</button></div></div>
      <div class="panel"><div class="scroll matrix" id="fx-box"></div></div>
    </section>

    <section class="sec">${modelNote()}</section>`;

  const $ = (s) => app.querySelector(s);
  $("#pg-owner").value = PROG.owner;
  $("#picked").querySelectorAll(".pchip").forEach((b) => b.addEventListener("click", () => {
    PROG.picks = PROG.picks.filter((x) => x !== Number(b.dataset.pid));
    renderPrognose(); bindTips(app);
  }));
  $("#add-pl").addEventListener("change", (e) => {
    const v = e.target.value;
    const p = names.find((p) => `${p.name} (${p.club})` === v);
    if (p && !PROG.picks.includes(p.id) && PROG.picks.length < 4) { PROG.picks.push(p.id); renderPrognose(); bindTips(app); }
  });
  $("#pg-owner").addEventListener("change", (e) => { PROG.owner = e.target.value; drawProjTable(); });
  $("#pg-pos").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { PROG.pos = b.dataset.pos; drawProjTable(); }));
  $("#fx-mode").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { PROG.fixMode = b.dataset.m; drawFixtures(); }));
  drawProjTable();
  drawFixtures();
  bindTips(app);
}

function drawProjTable() {
  const fut = ADV.proj.gws;
  app.querySelectorAll("#pg-pos button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.pos === PROG.pos));
  const rows = ADV.players
    .filter((p) => (PROG.pos === "ALL" || p.pos === PROG.pos) && (PROG.owner === "all" || (PROG.owner === "free" ? !p.owner : String(p.owner) === PROG.owner)))
    .sort((a, b) => sumH(b.id, fut.length) - sumH(a.id, fut.length)).slice(0, 40);
  const max = Math.max(1, ...rows.flatMap((p) => projOf(p.id)));
  app.querySelector("#pg-box").innerHTML = `<table class="advt"><thead><tr><th class="l">Spiller</th>${fut.map((g) => `<th>R${g}</th>`).join("")}<th>I alt</th></tr></thead><tbody>
    ${rows.map((p) => `<tr data-pid="${p.id}"><td class="l"><span class="pl"><b>${esc(p.name)}${statusDot(p)}</b><span>${esc(p.pos)}, ${esc(p.club)}, ${ownerHtml(p)}</span></span></td>
      ${fut.map((g, j) => {
        const v = projOf(p.id)[j] ?? 0;
        const f = (ADV.fixtures[p.team] || []).filter((f) => f.gw === g);
        const opp = f.map((f) => `${teamShort(f.opp)}${f.home ? "" : " u"}`).join("+") || "–";
        return `<td class="cell heat" style="--t:${(v / max).toFixed(2)}"><b>${num(v, 1)}</b><small>${opp}</small></td>`;
      }).join("")}
      <td class="pts">${num(sumH(p.id, fut.length), 1)}</td></tr>`).join("")}</tbody></table>`;
  app.querySelectorAll("#pg-box tbody tr").forEach((tr) => tr.addEventListener("click", (e) => {
    if (e.target.closest(".st-dot")) return;
    const pid = Number(tr.dataset.pid);
    if (!PROG.picks.includes(pid)) {
      PROG.picks = [...PROG.picks.slice(-3), pid];
      renderPrognose(); bindTips(app);
      app.querySelector(".proj-chart")?.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "center" });
    }
  }));
  enhanceMatrices(app);
  bindTips(app.querySelector("#pg-box"));
}

function drawFixtures() {
  const fut = ADV.proj.gws;
  const def = PROG.fixMode === "def";
  app.querySelectorAll("#fx-mode button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.m === PROG.fixMode));
  const score = (f) => (def ? Math.exp(-f.ga) : f.gf);
  const teams = Object.keys(ADV.fixtures).map(Number)
    .map((t) => ({ t, fx: ADV.fixtures[t], s: ADV.fixtures[t].reduce((a, f) => a + score(f), 0) / Math.max(1, ADV.fixtures[t].length) }))
    .sort((a, b) => b.s - a.s);
  const [lo, hi] = def ? [0.12, 0.45] : [0.8, 2.1];
  app.querySelector("#fx-box").innerHTML = `<table class="fxt"><thead><tr><th class="l">Hold</th>${fut.map((g) => `<th>R${g}</th>`).join("")}</tr></thead><tbody>
    ${teams.map(({ t, fx }) => `<tr><td class="l"><b>${esc(ADV.teams[t]?.name ?? "")}</b></td>${fut.map((g) => {
      const fs = fx.filter((f) => f.gw === g);
      if (!fs.length) return `<td class="cell blank">–</td>`;
      return `<td class="cell">${fs.map((f) => {
        const v = score(f);
        const k = Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
        const label = def ? `${Math.round(v * 100)}%` : num(v, 1);
        return `<span class="fxcell${f.euro_h != null ? " eu" : ""}" style="--t:${k.toFixed(2)}" data-tip="${esc(`<b>${esc(ADV.teams[t]?.name)} – ${esc(ADV.teams[f.opp]?.name)}</b>Runde ${g}, ${f.home ? "hjemme" : "ude"}<br>Forventede mål: ${num(f.gf, 2)} for, ${num(f.ga, 2)} imod<br>Chance for clean sheet: ${Math.round(Math.exp(-f.ga) * 100)}%${f.odds ? "<br>Ud fra bookmakerodds" : ""}${f.euro_h != null ? `<br>Europæisk kamp ${Math.round(f.euro_h / 24)} dage før` : ""}`)}">${teamShort(f.opp)}${f.home ? "" : " u"}<small>${label}</small></span>`;
      }).join("")}</td>`;
    }).join("")}</tr>`).join("")}</tbody></table>`;
  enhanceMatrices(app);
  bindTips(app.querySelector("#fx-box"));
}

// ---------------------------------------------------------------- Waivers

function waiverStatus() {
  const g = ADV.game || {};
  if (g.waivers_processed) return `<span class="badge"><span class="dot"></span>Waivers er afgjort. Ledige spillere kan hentes direkte nu, først til mølle.</span>`;
  if (g.next_waivers) return `<span class="badge"><span class="dot" style="background:var(--gold);box-shadow:0 0 0 3px rgba(251,191,36,.2)"></span>Waiver-ønsker lukker ${dateOnly(g.next_waivers)}</span>`;
  return "";
}

function renderWaivers() {
  app.innerHTML = `
    ${advHead()}
    ${subnav("waivers")}
    <p class="lede">De bedste ledige spillere lige nu, rangeret efter forventede point. Kun spillere uden ejer, som ikke er meldt ude.</p>
    <div style="margin-top:14px">${waiverStatus()}</div>
    <div class="panel adv-controls"><div class="adv-filters">
      ${horizonSelect("wv-h", WAIV.horizon)}
      <div class="seg" id="wv-pos" role="group" aria-label="Position">${["ALL", "GKP", "DEF", "MID", "FWD"].map((p) => `<button type="button" data-pos="${p}">${p === "ALL" ? "Alle" : p}</button>`).join("")}</div>
    </div></div>
    <div class="wv-list" id="wv-list"></div>
    <section class="sec">${modelNote()}</section>`;
  app.querySelector("#wv-h").addEventListener("change", (e) => { WAIV.horizon = Number(e.target.value); drawWaivers(); });
  app.querySelectorAll("#wv-pos button").forEach((b) => b.addEventListener("click", () => { WAIV.pos = b.dataset.pos; drawWaivers(); }));
  drawWaivers();
}

function drawWaivers() {
  const h = WAIV.horizon;
  app.querySelectorAll("#wv-pos button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.pos === WAIV.pos));
  const rows = ADV.players.filter((p) => !p.owner && isAvailable(p) && (WAIV.pos === "ALL" || p.pos === WAIV.pos))
    .sort((a, b) => sumH(b.id, h) - sumH(a.id, h)).slice(0, 20);
  app.querySelector("#wv-list").innerHTML = rows.map((p, i) => {
    const d = ADV.proj.detail[p.id] || {};
    const mi = seasonSum(p.id, "mi");
    return `<article class="panel spot wv" data-pid="${p.id}">
      <div class="wv-rank">${i + 1}</div>
      <div class="wv-main">
        <div class="wv-name"><b>${esc(p.name)}</b>${statusDot(p)}<span class="muted small">${esc(p.pos)}, ${esc(p.club)}</span></div>
        <p class="wv-why">${esc(reasonFor(p))}</p>
        <div class="wv-meta">${fixChips(p, Math.max(3, h))}
          <span class="muted small">60+ min: ${Math.round((d.p60 ?? 0) * 100)}%</span>
          <span class="muted small">Point seneste 3: ${recentPts(p.id, 3)}</span>
          <span class="muted small">Sæson: ${seasonSum(p.id, "pt")} point, ${num(seasonSum(p.id, "xpt"), 1)} xP, ${mi} min</span>
        </div>
      </div>
      <div class="wv-xp"><span class="v">${num(sumH(p.id, h), 1)}</span><span class="muted small">xP ${h === 1 ? "næste runde" : `næste ${h}`}</span></div>
    </article>`;
  }).join("") || `<p class="adv-empty">Ingen ledige spillere i den position.</p>`;
  app.querySelectorAll(".wv").forEach((el) => el.addEventListener("click", (e) => {
    if (e.target.closest(".st-dot")) return;
    playerSheet(Number(el.dataset.pid));
  }));
  bindTips(app.querySelector("#wv-list"));
}

// ---------------------------------------------------------------- Nøjagtighed

function renderAccuracy() {
  const S = ADV.scorecard;
  const pc = (x) => `${Math.round(x * 1000) / 10}`.replace(".", ",") + "%";
  const pp = (x) => `${x >= 0 ? "+" : "−"}${num(Math.abs(x) * 100, 1)} pp`;
  if (!S) {
    app.innerHTML = `${advHead()}${subnav("noejagtighed")}<p class="lede">Rapporten kræver mindst fire spillede runder.</p>`;
    return;
  }
  const r = S.ranking, sr = S.single_round, cs = S.clean_sheets, F = D.forecast?.calibration;
  const rounds = S.rounds;
  const verdict = (d) => d.lo > 0 ? `<span class="delta-up">Sikkert bedre</span>` : d.hi < 0 ? `<span class="delta-down">Sikkert dårligere</span>` : `<span class="muted">Ikke sikkert endnu</span>`;
  const calRows = (bins) => bins.map((b) => `<tr><td class="l">${Math.round(b.lo * 100)}–${Math.round(b.hi * 100)}%</td><td>${pc(b.pred)}</td><td class="strong">${pc(b.obs)}</td><td class="muted">${b.n}</td>
      <td class="l"><span class="calbar"><i class="p" style="left:${b.pred * 100}%"></i><i class="o" style="left:${b.obs * 100}%"></i></span></td></tr>`).join("");

  app.innerHTML = `
    ${advHead()}
    ${subnav("noejagtighed")}
    <p class="lede">Kan modellen noget? Hver test forudsiger en runde kun ud fra runderne før og sammenligner med, hvad der skete. Alle modeller testes på præcis de samme spillere og runder (runde ${rounds[0]}–${rounds[rounds.length - 1]}). Skadesstatus er den, FPL viste efter runden før.</p>

    <div class="recs" style="margin-top:24px">
      ${r ? panel(`<span class="v">${pc(r.new.acc)}</span><span class="t">Rigtige sammenligninger</span><span class="d">Når modellen siger, at spiller A får flere point end B i runde ${r.from + 1}–${r.to}. 90%-interval: ${pc(r.new.lo)}–${pc(r.new.hi)}. Et gæt giver 50%.</span>`, "rec") : ""}
      ${r ? panel(`<span class="v">${pp(r.new_vs_form.diff)}</span><span class="t">Bedre end formsnit</span><span class="d">90%-interval ${pp(r.new_vs_form.lo)} til ${pp(r.new_vs_form.hi)}. ${r.new_vs_form.lo > 0 ? "Forskellen er statistisk sikker." : "Ikke sikker endnu."}</span>`, "rec") : ""}
      ${F ? panel(`<span class="v">${F.fav_won} af ${F.fav_n}</span><span class="t">H2H-favoritten vandt</span><span class="d">${pc(F.fav_won / F.fav_n)} af ligaens kampe i testen.</span>`, "rec") : ""}
    </div>

    <section class="sec">
      <div class="sec-head"><div><h2>Modellerne side om side</h2><p class="lede">Formsnit er point i de seneste fire runder. Gammel er modellen før arbejdet med minutter, 2024/25 og dødbolde. Ny er den nuværende.</p></div></div>
      <div class="panel"><div class="scroll"><table class="advt"><thead><tr><th class="l">Mål</th><th>Formsnit</th><th>Gammel</th><th>Ny</th><th class="l">Ny mod gammel</th></tr></thead><tbody>
        ${r ? `<tr><td class="l"><b>Rigtige sammenligninger</b><br><span class="small muted">højere er bedre</span></td><td>${pc(r.form.acc)}</td><td>${pc(r.old.acc)}</td><td class="pts">${pc(r.new.acc)}</td><td class="l">${pp(r.new_vs_old.diff)}, ${verdict(r.new_vs_old)}</td></tr>` : ""}
        <tr><td class="l"><b>Pointfejl per spiller per runde</b><br><span class="small muted">lavere er bedre</span></td><td>${num(sr.form.pts_mae, 2)}</td><td>${num(sr.old.pts_mae, 2)}</td><td class="pts">${num(sr.new.pts_mae, 2)}</td><td class="l muted">Samme ${sr.new.n} spiller-runder</td></tr>
        <tr><td class="l"><b>Chance for 60+ minutter (Brier)</b><br><span class="small muted">lavere er bedre</span></td><td>–</td><td>${num(sr.old.brier60, 3)}</td><td class="pts">${num(sr.new.brier60, 3)}</td><td class="l muted">Kvaliteten af sandsynlighederne</td></tr>
        <tr><td class="l"><b>Minutfejl</b><br><span class="small muted">lavere er bedre</span></td><td>–</td><td>${num(sr.old.min_mae, 1)}</td><td class="pts">${num(sr.new.min_mae, 1)}</td><td class="l muted">Straffer forsigtige gæt som 70 minutter</td></tr>
        <tr><td class="l"><b>Skævhed i point</b><br><span class="small muted">0 er bedst</span></td><td>${signed(sr.form.pts_bias, 2)}</td><td>${signed(sr.old.pts_bias, 2)}</td><td class="pts">${signed(sr.new.pts_bias, 2)}</td><td class="l muted">Minus: rammer for lavt</td></tr>
      </tbody></table></div></div>
    </section>

    <section class="sec">
      <div class="sec-head"><div><h2>Holder sandsynlighederne?</h2><p class="lede">Når modellen giver en bestemt chance for 60+ minutter, hvor ofte skete det så? Perfekt kalibreret ligger de to prikker oven i hinanden.</p></div></div>
      <div class="panel"><div class="scroll"><table class="advt"><thead><tr><th class="l">Modellens chance</th><th>Forudsagt</th><th>Skete</th><th>Antal</th><th class="l"><span class="key-dot p"></span>forudsagt <span class="key-dot o"></span>skete</th></tr></thead><tbody>${calRows(sr.new.calibration60)}</tbody></table></div></div>
    </section>

    ${cs ? `<section class="sec">
      <div class="sec-head"><div><h2>Clean sheets</h2><p class="lede">Brier ${num(cs.brier, 3)} mod ${num(cs.brier_flat, 3)} for blot at gætte gennemsnittet (${pc(cs.rate)}) for alle, på ${cs.n} holdkampe. Forskellen er lille: med så få kampe kan modellen endnu ikke skelne meget mellem holdenes clean sheet-chancer.</p></div></div>
      <div class="panel"><div class="scroll"><table class="advt"><thead><tr><th class="l">Modellens chance</th><th>Forudsagt</th><th>Skete</th><th>Antal</th><th class="l"></th></tr></thead><tbody>${calRows(cs.calibration)}</tbody></table></div></div>
    </section>` : ""}

    <section class="sec"><div class="panel model-note"><h3>Sådan læser du det</h3>
      <p>Et 90%-interval er lavet ved at trække spillerne tilfældigt om 300 gange. Ligger hele intervallet over 0, er forbedringen ikke bare held. Med kun ${rounds.length + 2} spillede runder er intervallerne brede, og de bliver smallere hen over sæsonen. Rapporten opdateres automatisk.</p>
      <p class="small muted">Parametrene i minutmodellen er valgt på de samme runder, de testes på (et lille gitter af værdier), så forbedringen af minutterne kan være lidt for optimistisk.</p></div></section>`;
  bindTips(app);
}

// ---------------------------------------------------------------- Mit hold

function storedTeam() { try { return localStorage.getItem("adv-team"); } catch { return null; } }
function storeTeam(v) { try { localStorage.setItem("adv-team", v); } catch { /* not remembered */ } }

function resolveTeam(input) {
  const v = String(input || "").trim();
  if (!v) return null;
  if (ADV.managers[v]) return Number(v);                       // league entry id
  const hit = Object.entries(ADV.entry_ids || {}).find(([, id]) => String(id) === v);   // entry id from the FPL url
  return hit ? Number(hit[0]) : null;
}

function renderHold() {
  const saved = resolveTeam(storedTeam());
  const opts = Object.entries(ADV.managers).sort((a, b) => a[1].localeCompare(b[1], "da"));
  app.innerHTML = `
    ${advHead()}
    ${subnav("hold")}
    <p class="lede">Vælg dit hold, eller skriv dit hold-ID (tallet i adressen på draft.premierleague.com/entry/…). Så får du forslag til din egen trup.</p>
    <div class="panel adv-controls"><div class="adv-filters">
      <label>Hold<select id="hd-team"><option value="">Vælg hold</option>${opts.map(([le, n]) => `<option value="${le}"${Number(le) === saved ? " selected" : ""}>${esc(n)}, ${esc(ADV.teams_of?.[le] ?? "")}</option>`).join("")}</select></label>
      <label>Eller hold-ID<input id="hd-id" inputmode="numeric" placeholder="fx 263366"></label>
      ${horizonSelect("hd-h", HOLD.horizon)}
    </div><p class="lock-err" id="hd-err" aria-live="polite"></p></div>
    <div id="hd-body"></div>`;
  const pick = (le) => { storeTeam(String(le)); app.querySelector("#hd-team").value = String(le); drawHold(le); };
  app.querySelector("#hd-team").addEventListener("change", (e) => e.target.value && pick(Number(e.target.value)));
  app.querySelector("#hd-id").addEventListener("change", (e) => {
    const le = resolveTeam(e.target.value);
    app.querySelector("#hd-err").textContent = le ? "" : "Det hold-ID findes ikke i ligaen.";
    if (le) pick(le);
  });
  app.querySelector("#hd-h").addEventListener("change", (e) => { HOLD.horizon = Number(e.target.value); const le = resolveTeam(storedTeam()); if (le) drawHold(le); });
  if (saved) drawHold(saved);
}

function bucket(gainPerRound) {
  if (gainPerRound >= 0.6) return ["clear", "Klar opgradering"];
  if (gainPerRound >= 0.25) return ["marginal", "Marginal"];
  return ["watch", "Hold øje"];
}

function drawHold(le) {
  const h = Math.min(HOLD.horizon, ADV.proj.gws.length);
  const squad = ADV.players.filter((p) => p.owner === le);
  const body = app.querySelector("#hd-body");
  if (!squad.length) { body.innerHTML = `<p class="adv-empty">Fandt ingen spillere på holdet.</p>`; return; }
  const base = xiOver(squad, h);
  const next = bestXI(squad, 0);
  const inXI = new Set(next.xi.map((x) => x.p.id));
  const order = { GKP: 0, DEF: 1, MID: 2, FWD: 3 };

  // free-agent swaps measured on the best XI over the horizon, not raw points:
  // swapping a bench player you never start changes little
  const free = ADV.players.filter((p) => !p.owner && isAvailable(p));
  const topFree = {};
  for (const pos of Object.keys(FORM)) topFree[pos] = free.filter((p) => p.pos === pos).sort((a, b) => sumH(b.id, h) - sumH(a.id, h)).slice(0, 25);
  const swaps = squad.map((out) => {
    const adds = topFree[out.pos].map((inn) => ({ inn, gain: xiOver(squad.map((p) => (p === out ? inn : p)), h) - base }))
      .filter((x) => x.gain > 0.05).sort((a, b) => b.gain - a.gain).slice(0, 3);
    return { out, adds };
  }).filter((s) => s.adds.length).sort((a, b) => b.adds[0].gain - a.adds[0].gain).slice(0, 6);

  // 1-for-1 trades: my XI gain and the other team's XI change
  const trades = [];
  const others = Object.keys(ADV.managers).map(Number).filter((x) => x !== le);
  for (const o of others) {
    const theirs = ADV.players.filter((p) => p.owner === o);
    const theirBase = xiOver(theirs, h);
    for (const give of squad) {
      for (const get of theirs.filter((p) => p.pos === give.pos && isAvailable(p))) {
        const mine = xiOver(squad.map((p) => (p === give ? get : p)), h) - base;
        if (mine < 0.25 * h) continue;   // less than a quarter point per round is noise
        const them = xiOver(theirs.map((p) => (p === get ? give : p)), h) - theirBase;
        trades.push({ o, give, get, mine, them });
      }
    }
  }
  // realistic first: both gain, then a fair price for them, then hard sells; within each, biggest gain for you
  const tier = (t) => (t.them >= 0 ? 0 : t.them > -t.mine / 2 ? 1 : 2);
  trades.sort((a, b) => tier(a) - tier(b) || b.mine - a.mine);
  const bestTrades = trades.slice(0, 8);

  const xpCell = (p) => `<td>${num(projOf(p.id)[0] ?? 0, 1)}</td><td class="pts">${num(sumH(p.id, h), 1)}</td>`;
  const formation = `${next.count.DEF}-${next.count.MID}-${next.count.FWD}`;
  const bench = squad.filter((p) => !inXI.has(p.id)).sort((a, b) => (projOf(b.id)[0] ?? 0) - (projOf(a.id)[0] ?? 0));

  body.innerHTML = `
    <section class="sec">
      <div class="sec-head"><div><h2>Bedste startopstilling, runde ${ADV.proj.gws[0]}</h2><p class="lede">${formation}, i alt ${num(next.total, 1)} forventede point. Bænken i rækkefølge: ${bench.map((p) => esc(p.name)).join(", ")}.</p></div></div>
      <div class="pitch-xi panel">${["GKP", "DEF", "MID", "FWD"].map((pos) => `<div class="xi-row">${next.xi.filter((x) => x.p.pos === pos).sort((a, b) => b.v - a.v).map((x) => `<button type="button" class="xi-p" data-pid="${x.p.id}"><b>${esc(x.p.name)}</b><span>${num(x.v, 1)} xP</span><small>${fixturesOf(x.p, 1).map((f) => `${teamShort(f.opp)}${f.home ? "" : " u"}`).join("+") || "ingen kamp"}</small></button>`).join("")}</div>`).join("")}</div>
    </section>

    <section class="sec">
      <div class="sec-head"><div><h2>Drop og hent</h2><p class="lede">Gevinsten er ændringen i din bedste startopstillings forventede point over ${h === 1 ? "næste runde" : `de næste ${h} runder`}. Tre alternativer per spiller, så du kan stille flere waiver-ønsker op til samme drop. Sæt det mest eftertragtede ønske øverst: et vundet ønske sender dig bagerst i waiver-køen.${ADV.backtest?.rank?.buckets ? ` Klar opgradering betyder mindst 0,6 point per runde. I testen havde modellen ret i ${Math.round(ADV.backtest.rank.buckets[2].acc * 100)}% af sammenligningerne ved forskelle over 1 point per runde.` : ""}</p></div></div>
      ${swaps.length ? `<div class="swaps">${swaps.map((s) => {
        const [cls, label] = bucket(s.adds[0].gain / h);
        return `<div class="panel swap ${cls}">
          <div class="swap-head"><span class="bucket ${cls}">${label}</span><span class="muted small">Drop</span><b>${esc(s.out.name)}</b><span class="muted small">${esc(s.out.pos)}, ${esc(s.out.club)}, ${num(sumH(s.out.id, h), 1)} xP</span></div>
          <ol>${s.adds.map((a) => `<li data-pid="${a.inn.id}"><span class="gain">+${num(a.gain, 1)}</span><span><b>${esc(a.inn.name)}</b>${statusDot(a.inn)} <span class="muted small">${esc(a.inn.club)}, ${num(sumH(a.inn.id, h), 1)} xP</span><br><span class="small muted">${esc(reasonFor(a.inn))}</span></span>${fixChips(a.inn, Math.max(3, h))}</li>`).join("")}</ol>
        </div>`;
      }).join("")}</div>` : `<p class="adv-empty">Ingen ledige spillere ville forbedre din startopstilling lige nu.</p>`}
    </section>

    <section class="sec">
      <div class="sec-head"><div><h2>Byttehandler</h2><p class="lede">Én mod én med andre managere. Din gevinst og deres ændring er målt på hver sin bedste startopstilling, så en handel kan være god for begge, hvis den passer til deres trup.</p></div></div>
      ${bestTrades.length ? `<div class="panel"><div class="scroll"><table class="advt"><thead><tr><th class="l">Du giver</th><th class="l">Du får</th><th class="l">Fra</th><th>Din gevinst</th><th>Deres ændring</th><th class="l">Vurdering</th></tr></thead><tbody>
        ${bestTrades.map((t) => `<tr><td class="l"><b>${esc(t.give.name)}</b> <span class="muted small">${esc(t.give.pos)}</span></td><td class="l"><b>${esc(t.get.name)}</b>${statusDot(t.get)} <span class="muted small">${esc(t.get.club)}</span></td><td class="l">${esc(ADV.managers[t.o])}</td><td class="delta-up">+${num(t.mine, 1)}</td><td class="${t.them >= 0 ? "delta-up" : "delta-down"}">${t.them >= 0 ? "+" : "−"}${num(Math.abs(t.them), 1)}</td><td class="l">${["Begge vinder", "Rimelig", "Svær at sælge"][tier(t)]}</td></tr>`).join("")}
      </tbody></table></div></div>` : `<p class="adv-empty">Ingen oplagte byttehandler lige nu.</p>`}
    </section>

    <section class="sec">
      <div class="sec-head"><div><h2>Din trup</h2><p class="lede">Forventede point næste runde og over perioden.</p></div></div>
      <div class="panel"><div class="scroll"><table class="advt"><thead><tr><th class="l">Spiller</th><th class="l">Program</th><th>60+ min</th><th>Næste</th><th>Periode</th></tr></thead><tbody>
        ${[...squad].sort((a, b) => order[a.pos] - order[b.pos] || sumH(b.id, h) - sumH(a.id, h)).map((p) => {
          const d = ADV.proj.detail[p.id] || {};
          return `<tr data-pid="${p.id}"><td class="l"><span class="pl"><b>${esc(p.name)}${statusDot(p)}${inXI.has(p.id) ? '<span class="tag xi">XI</span>' : ""}</b><span>${esc(p.pos)}, ${esc(p.club)}</span></span></td><td class="l">${fixChips(p, Math.max(3, h))}</td><td>${Math.round((d.p60 ?? 0) * 100)}%</td>${xpCell(p)}</tr>`;
        }).join("")}
      </tbody></table></div></div>
    </section>
    <section class="sec">${modelNote()}</section>`;

  body.querySelectorAll("tr[data-pid], .xi-p, .swap li[data-pid]").forEach((el) => el.addEventListener("click", (e) => {
    if (e.target.closest(".st-dot")) return;
    playerSheet(Number(el.dataset.pid));
  }));
  bindTips(body);
}
