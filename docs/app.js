"use strict";

const app = document.getElementById("app");
const tip = document.getElementById("tip");
let D = null;               // current.json
const gwCache = {};         // gameweek snapshots

// ---------------------------------------------------------------- formatting

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (n, d = 1) => Number(n).toLocaleString("da-DK", { minimumFractionDigits: d, maximumFractionDigits: d });
const signed = (n, d = 1) => (n > 0 ? "+" : n < 0 ? "−" : "±") + num(Math.abs(n), d);
const mgr = (le) => D.managers[le]?.manager ?? "?";
const team = (le) => D.managers[le]?.team ?? "";
const who = (le) => `<span class="who"><b>${esc(mgr(le))}</b><span>${esc(team(le))}</span></span>`;
const names = (list) => list.map(mgr).map(esc).join(" og ");
const RES = { W: "V", D: "U", L: "T" };
const form = (seq) => `<span class="form">${seq.map((r) => `<i class="${r}" title="${{ W: "Vundet", D: "Uafgjort", L: "Tabt" }[r]}">${RES[r]}</i>`).join("")}</span>`;
const when = (iso) => new Intl.DateTimeFormat("da-DK", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Copenhagen" }).format(new Date(iso));
const dateOnly = (iso) => new Intl.DateTimeFormat("da-DK", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Copenhagen" }).format(new Date(iso));

async function getJSON(path) {
  const r = await fetch(path, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${path} svarede ${r.status}`);
  return r.json();
}
async function loadGw(gw) {
  if (!gwCache[gw]) gwCache[gw] = await getJSON(`data/gameweeks/gw${String(gw).padStart(2, "0")}.json`);
  return gwCache[gw];
}

// ---------------------------------------------------------------- tooltip

function bindTips(root) {
  root.querySelectorAll("[data-tip]").forEach((el) => {
    const show = (e) => {
      tip.innerHTML = el.dataset.tip;
      tip.hidden = false;
      const pt = e.touches ? e.touches[0] : e;
      const x = Math.min(pt.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
      const y = pt.clientY + 16 + tip.offsetHeight > window.innerHeight ? pt.clientY - tip.offsetHeight - 12 : pt.clientY + 16;
      tip.style.left = `${Math.max(8, x)}px`;
      tip.style.top = `${y}px`;
    };
    el.addEventListener("mousemove", show);
    el.addEventListener("mouseleave", () => (tip.hidden = true));
    el.addEventListener("touchstart", show, { passive: true });
  });
}
document.addEventListener("scroll", () => (tip.hidden = true), { passive: true });

// ---------------------------------------------------------------- shared pieces

function scoreboard({ title, note, matches, intro, pending }) {
  const rows = matches.map((m, i) => {
    const aw = m.pa > m.pb ? "won" : m.pa < m.pb ? "lost" : "";
    const bw = m.pb > m.pa ? "won" : m.pb < m.pa ? "lost" : "";
    const score = pending
      ? `<div class="fx-score pending">mod</div>`
      : `<div class="fx-score" aria-label="${m.pa} mod ${m.pb}"><span class="${aw}" style="--i:${i * 2}">${m.pa}</span><span class="dash">–</span><span class="${bw}" style="--i:${i * 2 + 1}">${m.pb}</span></div>`;
    return `<li class="fx">
      <div class="fx-side"><span class="fx-name">${esc(mgr(m.a))}</span><span class="fx-team">${esc(team(m.a))}</span></div>
      ${score}
      <div class="fx-side"><span class="fx-name">${esc(mgr(m.b))}</span><span class="fx-team">${esc(team(m.b))}</span></div>
    </li>`;
  }).join("");
  return `<section class="board${intro ? " intro" : ""}">
    <div class="board-head"><h1 class="board-title">${title}</h1><p class="board-note">${note}</p></div>
    <ol class="fixtures">${rows}</ol>
  </section>`;
}

function inTrophyNow() {
  const live = D.blocks.find((b) => b.status === "live" || b.status === "locked");
  return live && live.rule !== "all" ? new Set(live.group) : new Set();
}

// ---------------------------------------------------------------- view: stilling

let tableMode = "h2h";

async function viewStilling() {
  const latest = D.latest_gw;
  let hero = "";
  if (D.live && D.live.matches.length) {
    hero = scoreboard({ title: `Runde ${D.live.gw}`, note: `Runden er i gang. Stillingen ${dateOnly(D.updated)}.`, matches: D.live.matches, intro: true });
  } else if (latest) {
    const snap = await loadGw(latest);
    const next = D.next_round && D.game.next_deadline ? `Runde ${D.next_round.gw} lukker <strong>${when(D.game.next_deadline)}</strong>.` : "";
    hero = scoreboard({ title: `Runde ${latest}`, note: `Færdigspillet. ${next}`, matches: snap.matches, intro: true });
  }

  const nextRound = D.next_round && D.next_round.matches.length && !D.live
    ? `<section class="sec"><div class="sec-head"><h2>Næste runde</h2><p class="lede">Runde ${D.next_round.gw}${D.game.next_deadline ? `, deadline ${when(D.game.next_deadline)}` : ""}.</p></div>
       <div class="scroll"><table><tbody>${D.next_round.matches.map((m) => `<tr><td class="l">${who(m.a)}</td><td class="muted" style="text-align:center">mod</td><td class="l">${who(m.b)}</td></tr>`).join("")}</tbody></table></div></section>`
    : "";

  app.innerHTML = `${hero}
    <section class="sec">
      <div class="sec-head">
        <h2>Tabel</h2>
        <div class="switch" role="group" aria-label="Vælg tabel">
          <button data-mode="h2h">Head-to-head</button>
          <button data-mode="points">Samlede point</button>
          <button data-mode="form">Form</button>
        </div>
      </div>
      <p class="lede" id="table-lede"></p>
      <div class="scroll" style="margin-top:12px" id="table-box"></div>
      <div class="legend" id="table-legend"></div>
    </section>
    ${nextRound}`;

  const draw = () => {
    app.querySelectorAll(".switch button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.mode === tableMode));
    const box = app.querySelector("#table-box");
    const lede = app.querySelector("#table-lede");
    const legend = app.querySelector("#table-legend");
    const trophy = inTrophyNow();
    if (tableMode === "h2h") {
      lede.textContent = "Den officielle stilling. Ved lige point afgør flest scorede point.";
      const half = Math.floor(D.standings.length / 2);
      box.innerHTML = `<table><thead><tr><th>#</th><th class="l">Hold</th><th>K</th><th>V</th><th>U</th><th>T</th><th>Scoret</th><th>Imod</th><th class="l">Form</th><th>Point</th></tr></thead><tbody>
        ${D.standings.map((s, i) => {
          const mv = s.last_rank && s.last_rank !== s.rank ? (s.last_rank > s.rank ? `<span class="delta-up" title="Op fra ${s.last_rank}.">▲</span>` : `<span class="delta-down" title="Ned fra ${s.last_rank}.">▼</span>`) : "";
          return `<tr class="${i === half ? "cut" : ""}"><td class="rank">${s.rank} ${mv}</td><td class="l">${who(s.le)}</td><td>${s.w + s.d + s.l}</td><td>${s.w}</td><td>${s.d}</td><td>${s.l}</td><td>${s.pf}</td><td>${s.pa}</td><td class="l">${form(s.form)}</td><td class="strong">${s.pts}${trophy.has(s.le) ? '<span class="mark" title="Med i bundpokalen"></span>' : ""}</td></tr>`;
        }).join("")}</tbody></table>`;
      legend.innerHTML = `<span><i class="mark" style="margin:0"></i> med i den nuværende bundpokal</span><span>Den stiplede linje deler tabellen i top og bund.</span>`;
    } else if (tableMode === "points") {
      lede.textContent = "Hvis vi spillede klassisk FPL: alle scorede point lagt sammen, uden kampe.";
      const rankOf = Object.fromEntries(D.standings.map((s) => [s.le, s.rank]));
      box.innerHTML = `<table><thead><tr><th>#</th><th class="l">Hold</th><th>Snit</th><th>Bedst</th><th>Værst</th><th>Plads i H2H</th><th>Point</th></tr></thead><tbody>
        ${D.points_table.map((p, i) => {
          const diff = rankOf[p.le] - (i + 1);
          const d = diff > 0 ? `<span class="delta-down">${rankOf[p.le]}.</span>` : diff < 0 ? `<span class="delta-up">${rankOf[p.le]}.</span>` : `${rankOf[p.le]}.`;
          return `<tr><td class="rank">${i + 1}</td><td class="l">${who(p.le)}</td><td>${num(p.avg)}</td><td>${p.best}</td><td>${p.worst}</td><td>${d}</td><td class="strong">${p.total}</td></tr>`;
        }).join("")}</tbody></table>`;
      legend.innerHTML = `<span><span class="delta-down">Rød</span> plads i H2H: holdet ligger lavere, end pointene fortjener.</span><span><span class="delta-up">Grøn</span>: højere.</span>`;
    } else {
      const gws = D.gameweeks.slice(-4).map((g) => g.gw);
      lede.textContent = `Point i de seneste ${gws.length} runder (runde ${gws[0]}–${gws[gws.length - 1]}).`;
      const rows = [...D.points_table].sort((a, b) => b.recent - a.recent);
      box.innerHTML = `<table><thead><tr><th>#</th><th class="l">Hold</th>${gws.map((g) => `<th>R${g}</th>`).join("")}<th class="l">Resultater</th><th>Point</th></tr></thead><tbody>
        ${rows.map((p, i) => {
          const last = p.by_gw.slice(-gws.length);
          const st = D.standings.find((s) => s.le === p.le);
          return `<tr><td class="rank">${i + 1}</td><td class="l">${who(p.le)}</td>${last.map((v) => `<td>${v}</td>`).join("")}<td class="l">${form(st.form.slice(-gws.length))}</td><td class="strong">${p.recent}</td></tr>`;
        }).join("")}</tbody></table>`;
      legend.innerHTML = "";
    }
  };
  app.querySelectorAll(".switch button").forEach((b) => b.addEventListener("click", () => { tableMode = b.dataset.mode; draw(); }));
  draw();
}

// ---------------------------------------------------------------- view: bundpokal

function viewBundpokal() {
  const prize = D.league.prize_kr;
  const current = D.blocks.find((b) => b.status === "live") || D.blocks.find((b) => b.status === "locked")
    || [...D.blocks].reverse().find((b) => b.status === "finished");
  const gwLabel = (b) => `Runde ${b.from}–${b.to}`;

  let race = "";
  if (current) {
    const max = Math.max(1, ...current.standings.map((r) => r.total));
    const lead = current.standings[0];
    const played = current.played.length;
    const total = current.to - current.from + 1;
    const status = current.status === "locked"
      ? `Gruppen er låst efter runde ${current.after_gw}. Blokken starter i runde ${current.from}.`
      : current.status === "live" ? `${played} af ${total} runder spillet.` : `Færdigspillet. ${names(current.winners)} vinder ${prize} kr.`;
    race = `<div>
      <h2>${gwLabel(current)}</h2>
      <p class="lede">${status}</p>
      <ol class="race" style="margin-top:14px">${current.standings.map((r, i) => {
        const gap = i === 0 ? "" : ` (${lead.total - r.total} efter)`;
        const rank = current.group_ranks?.[r.le];
        const tipTxt = `<b>${esc(mgr(r.le))}</b><br>${Object.entries(r.by_gw).map(([g, v]) => `Runde ${g}: ${v}`).join("<br>") || "Ingen runder spillet endnu"}${rank ? `<br>${rank}. plads ved låsning` : ""}`;
        return `<li data-tip="${esc(tipTxt)}"><span class="pos">${i + 1}</span>${who(r.le)}<span class="pts" aria-label="${r.total} point${gap}">${r.total}</span><span class="bar"><i style="width:${(r.total / max) * 100}%"></i></span></li>`;
      }).join("")}</ol>
    </div>`;
  }

  const history = D.blocks.map((b) => {
    let st, cls = "";
    if (b.status === "finished") {
      st = `<b>${names(b.winners)}</b> vandt med ${b.standings[0].total} point${b.final ? "" : " (foreløbigt)"}`;
      cls = "won";
    } else if (b.status === "live") { st = `I gang. ${names([b.standings[0].le])} fører.`; cls = "live"; }
    else if (b.status === "locked") st = `Gruppe låst: ${names(b.group)}`;
    else st = b.after_gw ? `Gruppen låses efter runde ${b.after_gw}` : "";
    const grp = b.rule === "all" ? "Alle deltog" : b.group ? names(b.group) : "Ikke låst endnu";
    return `<li class="${cls}"><span class="gws">${b.from}–${b.to}</span><span>${st || grp}</span><span class="status">${b.rule === "all" ? "Alle deltog" : b.status === "finished" || b.status === "live" ? grp : ""}</span></li>`;
  }).join("");

  app.innerHTML = `
    <h1>Bundpokalen</h1>
    <p class="lede">Hver blok har sin egen konkurrence for bundholdene. Den, der scorer flest point i blokken, vinder ${prize} kr.</p>
    <div class="trophy">
      ${race}
      <aside class="rules">
        <h3>Sådan virker det</h3>
        <ol>
          <li>Sæsonen er delt i seks blokke.</li>
          <li>Når en blok starter, låses de fem nederste hold i tabellen som gruppen.</li>
          <li>Kun scorede point tæller. H2H-resultater er ligegyldige.</li>
          <li>Rykker du op i løbet af blokken, er du stadig med.</li>
          <li>Ved lige point deles præmien.</li>
        </ol>
        <p class="small muted" style="margin:10px 0 0">Runde 1–6 var åben for alle.</p>
      </aside>
    </div>
    <section class="sec"><div class="sec-head"><h2>Alle blokke</h2></div><ol class="blocks">${history}</ol></section>`;
  bindTips(app);
}

// ---------------------------------------------------------------- view: held og uheld

function luckChart(rows) {
  // draw at the real container width so text stays at true size on phones
  const W = Math.max(320, Math.min(1000, app.clientWidth - 18));
  const narrow = W < 520;
  const rowH = 34, top = 28, left = narrow ? 96 : 150, right = narrow ? 52 : 70;
  const H = top + rows.length * rowH + 8;
  const max = Math.ceil(Math.max(...rows.flatMap((r) => [r.pts, r.xpts])) / 3) * 3 + 3;
  const x = (v) => left + (v / max) * (W - left - right);
  const ticks = [];
  for (let t = 0; t <= max; t += narrow ? 6 : 3) ticks.push(t);
  const grid = ticks.map((t) => `<line x1="${x(t)}" x2="${x(t)}" y1="${top - 6}" y2="${H - 8}"/>`).join("");
  const axis = ticks.map((t) => `<text x="${x(t)}" y="${top - 12}" text-anchor="middle">${t}</text>`).join("");
  const body = rows.map((r, i) => {
    const y = top + i * rowH + rowH / 2;
    const lucky = r.luck >= 0;
    const t = `<b>${esc(mgr(r.le))}</b><br>Forventet: ${num(r.xpts)} point<br>Faktisk: ${r.pts} point<br>${lucky ? "Heldig" : "Uheldig"} med ${num(Math.abs(r.luck))} point<br>Mod alle: ${r.w}-${r.d}-${r.l}`;
    return `<g class="row" data-tip="${esc(t)}">
      <rect class="hit" x="0" y="${y - rowH / 2}" width="${W}" height="${rowH}"/>
      <text x="${left - 14}" y="${y + 5}" text-anchor="end" font-size="15" font-weight="600">${esc(mgr(r.le))}</text>
      <line class="${lucky ? "lk-pos" : "lk-neg"}" x1="${x(r.xpts)}" x2="${x(r.pts)}" y1="${y}" y2="${y}" stroke-width="4" stroke-linecap="round"/>
      <circle class="dot-x" cx="${x(r.xpts)}" cy="${y}" r="6"/>
      <circle class="dot-a" cx="${x(r.pts)}" cy="${y}" r="6.5"/>
      <text x="${W - right + 14}" y="${y + 5}" font-size="14" font-weight="600" style="fill:${lucky ? "var(--turf)" : "var(--red)"}">${signed(r.luck)}</text>
    </g>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Forventede og faktiske point per hold"><g class="grid">${grid}</g><g class="axis">${axis}</g>${body}</svg>`;
}

function divergeBg(v, span) {
  if (!v) return "";
  const a = Math.min(1, Math.abs(v) / span) * 0.85 + 0.1;
  return v > 0 ? `background: rgba(30,107,69,${a * 0.45})` : `background: rgba(191,49,41,${a * 0.38})`;
}

async function viewHeld() {
  const rows = [...D.luck].sort((a, b) => b.luck - a.luck);
  const ids = D.standings.map((s) => s.le);
  const swap = D.schedule_swap;
  let span = 1;
  ids.forEach((a) => ids.forEach((b) => (span = Math.max(span, Math.abs(swap[a][b] - swap[a][a])))));

  const snaps = await Promise.all(D.gameweeks.map((g) => loadGw(g.gw)));
  const byXp = [...D.luck].sort((a, b) => b.xpts - a.xpts);

  app.innerHTML = `
    <h1>Held og uheld</h1>
    <p class="lede">I H2H afgør modstanderen meget. Her spiller hvert hold hver runde mod alle ni andre. Slår du 6 af 9 i en runde, er den 2 forventede point værd. Forskellen mellem forventet og faktisk er held.</p>

    <section class="sec">
      <div class="sec-head"><h2>Forventet mod faktisk</h2></div>
      <div class="chart">${luckChart(rows)}</div>
      <div class="legend"><span><i class="key-x"></i> forventede point</span><span><i class="key-a"></i> faktiske point</span><span><i class="key-pos"></i> heldig</span><span><i class="key-neg"></i> uheldig</span></div>
    </section>

    <section class="sec">
      <div class="sec-head"><h2>Tabellen uden held</h2><p class="lede">Sorteret efter forventede point.</p></div>
      <div class="scroll"><table><thead><tr><th>#</th><th class="l">Hold</th><th>Mod alle (V-U-T)</th><th>Vundet</th><th>Forventet</th><th>Faktisk</th><th>Held</th><th>Plads nu</th></tr></thead><tbody>
      ${byXp.map((r, i) => {
        const games = r.w + r.d + r.l;
        const st = D.standings.find((s) => s.le === r.le);
        return `<tr><td class="rank">${i + 1}</td><td class="l">${who(r.le)}</td><td>${r.w}-${r.d}-${r.l}</td><td>${games ? Math.round((r.w + r.d / 2) / games * 100) : 0}%</td><td class="strong">${num(r.xpts)}</td><td>${r.pts}</td><td class="${r.luck >= 0 ? "delta-up" : "delta-down"}">${signed(r.luck)}</td><td>${st.rank}.</td></tr>`;
      }).join("")}</tbody></table></div>
    </section>

    <section class="sec">
      <div class="sec-head"><h2>Forventede point per runde</h2><p class="lede">Hvor mange H2H-point runden var værd, målt mod hele feltet. 3,0 betyder, at du slog alle.</p></div>
      <div class="scroll"><table><thead><tr><th class="l">Hold</th>${snaps.map((s) => `<th>R${s.gw}</th>`).join("")}<th>I alt</th></tr></thead><tbody>
      ${byXp.map((r) => `<tr><td class="l">${who(r.le)}</td>${snaps.map((s) => {
        const ap = s.all_play[r.le];
        const m = s.matches.find((m) => m.a === r.le || m.b === r.le);
        const mine = m.a === r.le ? m.pa : m.pb, theirs = m.a === r.le ? m.pb : m.pa;
        const got = mine > theirs ? 3 : mine === theirs ? 1 : 0;
        const t = `<b>${esc(mgr(r.le))}, runde ${s.gw}</b><br>${mine} point slog ${ap.w} af 9<br>Forventet ${num(ap.xpts, 2)}, fik ${got}`;
        return `<td class="cell" style="${divergeBg(got - ap.xpts, 2)}" data-tip="${esc(t)}">${num(ap.xpts)}</td>`;
      }).join("")}<td class="strong">${num(r.xpts)}</td></tr>`).join("")}</tbody></table></div>
      <div class="legend"><span>Grøn: fik flere point end forventet den runde. Rød: færre.</span></div>
    </section>

    <section class="sec">
      <div class="sec-head"><h2>Byt kampprogram</h2><p class="lede">Hvor mange point havde du haft med en andens modstandere? Læs rækken: holdets egne scorer mod programmet i kolonnen. Den indrammede celle er virkeligheden.</p></div>
      <div class="scroll"><table><thead><tr><th class="l">Hold</th>${ids.map((b) => `<th class="rot">${esc(mgr(b))}</th>`).join("")}</tr></thead><tbody>
      ${ids.map((a) => `<tr><td class="l">${who(a)}</td>${ids.map((b) => {
        const v = swap[a][b], d = v - swap[a][a];
        const t = `<b>${esc(mgr(a))}</b> med ${esc(mgr(b))}s program<br>${v} point (${d === 0 ? "samme som nu" : `${d > 0 ? "+" : "−"}${Math.abs(d)} i forhold til nu`})`;
        return `<td class="cell${a === b ? " diag" : ""}" style="${a === b ? "" : divergeBg(d, span)}" data-tip="${esc(t)}">${v}</td>`;
      }).join("")}</tr>`).join("")}</tbody></table></div>
      <div class="legend"><span>Grøn: bedre end dit eget program. Rød: værre.</span></div>
    </section>`;
  bindTips(app);
}

// ---------------------------------------------------------------- view: runder

const AWARDS = [
  ["top_score", "Rundens højeste score"],
  ["low_score", "Træskeen"],
  ["biggest_win", "Største sejr"],
  ["luckiest_win", "Heldigste sejr", "Vandt med færrest point"],
  ["unluckiest_loss", "Mest uheldige nederlag", "Tabte med flest point"],
  ["bench_shame", "Bænkens skam", "Flest point på bænken"],
  ["waiver_hero", "Waiver-helten", "Flest point fra spillere hentet efter draften"],
  ["best_player", "Rundens spiller"],
];
const ACQ = { draft: "Draft", waiver: "Waiver", free: "Fri", other: "Byttet" };

function awardHtml(a) {
  return AWARDS.filter(([k]) => a[k]).map(([k, label, hint]) => {
    const x = a[k];
    let body;
    if (k === "biggest_win") {
      body = x.matches.map((m) => {
        const [w, l] = m.pa > m.pb ? [m.a, m.b] : [m.b, m.a];
        return `<span class="n">${esc(mgr(w))}</span> slog ${esc(mgr(l))} ${Math.max(m.pa, m.pb)}–${Math.min(m.pa, m.pb)}`;
      }).join("<br>");
      body = `<span class="v">${x.value}</span>${body}`;
    } else if (k === "best_player") {
      body = `<span class="v">${x.pts}</span><span class="n">${esc(x.name)}</span> <span class="muted">(${esc(x.club)}) hos ${esc(mgr(x.le))}</span>`;
    } else {
      body = `<span class="v">${x.value}</span><span class="n">${names(x.le)}</span>`;
    }
    return `<div class="award"${hint ? ` title="${hint}"` : ""}><dt>${label}</dt><dd>${body}</dd></div>`;
  }).join("");
}

async function viewRunder(gwArg) {
  const list = D.gameweeks.map((g) => g.gw);
  if (!list.length) { app.innerHTML = `<h1>Runder</h1><p class="lede">Ingen runder er færdigspillet endnu.</p>`; return; }
  const gw = list.includes(Number(gwArg)) ? Number(gwArg) : list[list.length - 1];
  const s = await loadGw(gw);
  const picker = D.gameweeks.map((g) => `<a href="#runder/${g.gw}" ${g.gw === gw ? 'aria-current="page"' : ""} class="${g.final ? "" : "open"}" title="${g.final ? "Endeligt" : "Kan stadig blive rettet"}">${g.gw}</a>`).join("");
  const order = Object.entries(s.teams).sort((a, b) => b[1].score - a[1].score);
  const status = s.final ? "Resultaterne er endelige." : `Kan stadig blive rettet frem til ${dateOnly(s.final_at)}.`;

  app.innerHTML = `
    <h1>Runder</h1>
    <nav class="gw-pick" aria-label="Vælg runde">${picker}</nav>
    ${scoreboard({ title: `Runde ${gw}`, note: status, matches: s.matches })}
    <section class="sec"><div class="sec-head"><h2>Rundens priser</h2></div><dl class="awards">${awardHtml(s.awards)}</dl></section>
    <section class="sec">
      <div class="sec-head"><h2>Holdene</h2><p class="lede">Startelleveren efter automatiske udskiftninger. Tryk for at se spillerne.</p></div>
      <div class="lineups">${order.map(([le, t]) => {
        const ap = s.all_play[le];
        return `<details class="lineup"><summary>${who(Number(le))}<span class="s">${t.score}</span></summary>
          <table><tbody>
          ${t.xi.map((p) => `<tr><td class="l">${esc(p.name)} <span class="muted small">${esc(p.pos)}, ${esc(p.club)}</span></td><td><span class="acq ${p.acq}">${ACQ[p.acq]}</span></td><td class="strong">${p.pts}</td></tr>`).join("")}
          <tr class="sep benchrow"><td class="l" colspan="2">Bænken</td><td>${t.bench_pts}</td></tr>
          ${t.bench.map((p) => `<tr class="benchrow"><td class="l">${esc(p.name)} <span class="small">${esc(p.pos)}, ${esc(p.club)}</span></td><td><span class="acq ${p.acq}">${ACQ[p.acq]}</span></td><td>${p.pts}</td></tr>`).join("")}
          <tr class="sep"><td class="l muted" colspan="3">Mod alle: ${ap.w}-${ap.d}-${ap.l}, ${num(ap.xpts, 2)} forventede point</td></tr>
          </tbody></table></details>`;
      }).join("")}</div>
    </section>
    <section class="sec">
      <div class="sec-head"><h2>Tabellen efter runde ${gw}</h2></div>
      <div class="scroll"><table><thead><tr><th>#</th><th class="l">Hold</th><th>V</th><th>U</th><th>T</th><th>Scoret</th><th>Point</th></tr></thead><tbody>
      ${s.table_after.map((r, i) => `<tr class="${i === Math.floor(s.table_after.length / 2) ? "cut" : ""}"><td class="rank">${r.rank}</td><td class="l">${who(r.le)}</td><td>${r.w}</td><td>${r.d}</td><td>${r.l}</td><td>${r.pf}</td><td class="strong">${r.pts}</td></tr>`).join("")}
      </tbody></table></div>
    </section>`;
}

// ---------------------------------------------------------------- view: rekorder

function viewRekorder() {
  const R = D.records;
  const rec = (v, t, d) => `<div class="rec"><span class="v">${v}</span><span class="t">${t}</span><span class="d">${d}</span></div>`;
  const m = (x) => { const [w, l] = x.pa > x.pb ? [x.a, x.b] : [x.b, x.a]; return `${esc(mgr(w))} mod ${esc(mgr(l))}, ${Math.max(x.pa, x.pb)}–${Math.min(x.pa, x.pb)} i runde ${x.event}`; };
  const recs = [
    R.high_score && rec(R.high_score.value, "Højeste score", `${esc(mgr(R.high_score.le))} i runde ${R.high_score.gw}`),
    R.low_score && rec(R.low_score.value, "Laveste score", `${esc(mgr(R.low_score.le))} i runde ${R.low_score.gw}`),
    R.biggest_win && rec(R.biggest_win.value, "Største sejr", m(R.biggest_win)),
    R.luckiest_win && rec(R.luckiest_win.value, "Heldigste sejr", m(R.luckiest_win)),
    R.unluckiest_loss && rec(R.unluckiest_loss.value, "Mest uheldige nederlag", m(R.unluckiest_loss)),
    R.bench_shame && rec(R.bench_shame.value, "Flest point på bænken", `${esc(mgr(R.bench_shame.le))} i runde ${R.bench_shame.gw}`),
  ].filter(Boolean).join("");

  const ids = D.standings.map((s) => s.le);
  const H = (k) => ids.map((le) => D.honours[le]?.[k] ?? 0);
  const honourKeys = [["top_score", "Højeste"], ["low_score", "Træske"], ["luckiest_win", "Heldig sejr"], ["unluckiest_loss", "Uheldigt nederlag"], ["bench_shame", "Bænkeskam"], ["waiver_hero", "Waiver-helt"]];
  const honourRows = ids.map((le) => ({ le, v: honourKeys.map(([k]) => D.honours[le]?.[k] ?? 0), s: D.streaks[le] }));
  const streak = (s) => s.current.n ? `${s.current.n} ${{ W: "sejre", D: "uafgjorte", L: "nederlag" }[s.current.kind]}` : "–";

  const maxBench = Math.max(1, ...D.bench.map((b) => b.total));
  const maxWaiver = Math.max(1, ...D.waivers.map((w) => w.pts));

  const h2h = D.h2h;
  app.innerHTML = `
    <h1>Rekorder</h1>
    <section class="sec"><div class="sec-head"><h2>Sæsonens rekorder</h2></div><div class="recs">${recs}</div></section>

    <section class="sec">
      <div class="sec-head"><h2>Prisoversigt</h2><p class="lede">Hvor mange gange hver har fået rundens priser. Ved delt pris tæller den for begge.</p></div>
      <div class="scroll"><table><thead><tr><th class="l">Hold</th>${honourKeys.map(([, l]) => `<th>${l}</th>`).join("")}<th>Stime nu</th><th>Længste sejrsstime</th></tr></thead><tbody>
      ${honourRows.map((r) => `<tr><td class="l">${who(r.le)}</td>${r.v.map((v) => `<td>${v || '<span class="muted">0</span>'}</td>`).join("")}<td>${streak(r.s)}</td><td>${r.s.best_win}</td></tr>`).join("")}
      </tbody></table></div>
    </section>

    <div class="cols2">
      <section class="sec">
        <div class="sec-head"><h2>Bænkens skam</h2><p class="lede">Point, der blev på bænken hele sæsonen.</p></div>
        <div class="scroll"><table><thead><tr><th class="l">Hold</th><th>Værste runde</th><th>I alt</th></tr></thead><tbody>
        ${D.bench.map((b) => `<tr><td class="l">${who(b.le)}</td><td>${b.worst} <span class="muted small">(R${b.worst_gw})</span></td><td class="strong">${b.total}</td></tr>`).join("")}
        </tbody></table></div>
      </section>
      <section class="sec">
        <div class="sec-head"><h2>Waiver-kongen</h2><p class="lede">Point fra spillere i startelleveren, som ikke blev draftet af holdet.</p></div>
        <div class="scroll"><table><thead><tr><th class="l">Hold</th><th>Claims</th><th>Frie</th><th>Andel</th><th>Point</th></tr></thead><tbody>
        ${D.waivers.map((w) => `<tr><td class="l">${who(w.le)}</td><td title="${w.claims_won} vundet, ${w.claims_lost} tabt">${w.claims_won}/${w.claims_won + w.claims_lost}</td><td>${w.free_agents}</td><td>${Math.round(w.share * 100)}%</td><td class="strong">${w.pts}</td></tr>`).join("")}
        </tbody></table></div>
        <p class="small muted">Claims: vundne af forsøgte. Frie: hentet som fri spiller uden claim.</p>
      </section>
    </div>

    <section class="sec">
      <div class="sec-head"><h2>Sæsonens bedste fund</h2><p class="lede">Spillere hentet på waivers eller som fri spiller, efter point i startelleveren for det hold, der hentede dem.</p></div>
      <div class="scroll"><table><thead><tr><th>#</th><th class="l">Spiller</th><th class="l">Hentet af</th><th class="l">Hvordan</th><th>Kampe i XI</th><th>Point</th></tr></thead><tbody>
      ${D.best_pickups.map((p, i) => `<tr><td class="rank">${i + 1}</td><td class="l"><b>${esc(p.name)}</b> <span class="muted small">${esc(p.pos)}, ${esc(p.club)}</span></td><td class="l">${esc(mgr(p.le))}</td><td class="l"><span class="acq ${p.acq}">${ACQ[p.acq]}</span></td><td>${p.starts}</td><td class="strong">${p.pts}</td></tr>`).join("")}
      </tbody></table></div>
    </section>

    <section class="sec">
      <div class="sec-head"><h2>Indbyrdes opgør</h2><p class="lede">Rækkens resultater mod kolonnen (V-U-T).</p></div>
      <div class="scroll"><table><thead><tr><th class="l">Hold</th>${ids.map((b) => `<th class="rot">${esc(mgr(b))}</th>`).join("")}</tr></thead><tbody>
      ${ids.map((a) => `<tr><td class="l">${who(a)}</td>${ids.map((b) => {
        if (a === b) return `<td class="cell muted">·</td>`;
        const r = h2h[a][b];
        if (!(r.w + r.d + r.l)) return `<td class="cell muted"></td>`;
        const net = r.w - r.l;
        const t = `<b>${esc(mgr(a))} mod ${esc(mgr(b))}</b><br>${r.w} sejre, ${r.d} uafgjort, ${r.l} nederlag<br>Point: ${r.pf}–${r.pa}`;
        return `<td class="cell" style="${divergeBg(net, 2)}" data-tip="${esc(t)}">${r.w}-${r.d}-${r.l}</td>`;
      }).join("")}</tr>`).join("")}</tbody></table></div>
    </section>`;
  bindTips(app);
}

// ---------------------------------------------------------------- router

const VIEWS = { stilling: viewStilling, bundpokal: viewBundpokal, held: viewHeld, runder: viewRunder, rekorder: viewRekorder };

async function route() {
  const [name, arg] = (location.hash.slice(1) || "stilling").split("/");
  const view = VIEWS[name] ? name : "stilling";
  document.querySelectorAll(".tabs a").forEach((a) => (a.dataset.view === view ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  tip.hidden = true;
  try {
    await VIEWS[view](arg);
  } catch (e) {
    app.innerHTML = `<p class="error">Siden kunne ikke vises: ${esc(e.message)}. Prøv at genindlæse.</p>`;
    console.error(e);
  }
  if (route.ran) { window.scrollTo(0, 0); app.focus({ preventScroll: true }); }
  route.ran = true;
}

(async function init() {
  try {
    D = await getJSON("data/current.json");
  } catch (e) {
    app.innerHTML = `<p class="error">Ligadata kunne ikke hentes (${esc(e.message)}). Prøv at genindlæse siden.</p>`;
    return;
  }
  document.getElementById("updated").textContent = `Senest opdateret ${dateOnly(D.updated)}.`;
  window.addEventListener("hashchange", route);
  route();
})();
