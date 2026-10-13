"use strict";

const app = document.getElementById("app");
const tip = document.getElementById("tip");
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
let D = null;               // current.json
const gwCache = {};         // gameweek snapshots
let countdownTimer = null;

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
const rank = (n) => (n <= 3 ? `<span class="rk r${n}">${n}</span>` : `<span class="rk">${n}</span>`);
const when = (iso) => new Intl.DateTimeFormat("da-DK", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Copenhagen" }).format(new Date(iso));
const dateOnly = (iso) => new Intl.DateTimeFormat("da-DK", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Copenhagen" }).format(new Date(iso));
const panel = (inner, cls = "") => `<div class="panel spot ${cls}">${inner}</div>`;

async function getJSON(path) {
  const r = await fetch(path, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${path} svarede ${r.status}`);
  return r.json();
}
async function loadGw(gw) {
  if (!gwCache[gw]) gwCache[gw] = await getJSON(`data/gameweeks/gw${String(gw).padStart(2, "0")}.json`);
  return gwCache[gw];
}

// ---------------------------------------------------------------- interaction helpers

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

// spotlight: cards light up where the pointer is
document.addEventListener("pointermove", (e) => {
  const card = e.target.closest?.(".spot");
  if (!card) return;
  const r = card.getBoundingClientRect();
  card.style.setProperty("--mx", `${e.clientX - r.left}px`);
  card.style.setProperty("--my", `${e.clientY - r.top}px`);
});

// sliding pill under the active item of a nav or switch
function moveThumb(container, active) {
  const thumb = container.querySelector(".pill-thumb");
  if (!thumb || !active) return;
  thumb.style.width = `${active.offsetWidth}px`;
  thumb.style.transform = `translateX(${active.offsetLeft}px)`;
}

// count numbers up from 0 once
function tick(root) {
  if (REDUCED || !root) return;
  root.querySelectorAll("[data-count]").forEach((el, i) => {
    const target = Number(el.dataset.count);
    const start = performance.now() + i * 40;
    const dur = 900;
    el.textContent = "0";
    const step = (t) => {
      const p = Math.min(1, Math.max(0, (t - start) / dur));
      el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

function startCountdown(iso) {
  clearInterval(countdownTimer);
  const el = app.querySelector("#cd");
  if (!el || !iso) return;
  const end = new Date(iso).getTime();
  const draw = () => {
    let s = Math.max(0, Math.floor((end - Date.now()) / 1000));
    const d = Math.floor(s / 86400); s -= d * 86400;
    const h = Math.floor(s / 3600); s -= h * 3600;
    const m = Math.floor(s / 60); s -= m * 60;
    el.innerHTML = [[d, "dage"], [h, "timer"], [m, "min"], [s, "sek"]].map(([v, l]) => `<span>${String(v).padStart(2, "0")}<small>${l}</small></span>`).join("");
  };
  draw();
  countdownTimer = setInterval(draw, 1000);
}

// ---------------------------------------------------------------- shared pieces

function matchCards(matches, { pending = false, style = "" } = {}) {
  const line = (le, mine, theirs, cls) => `<div class="line ${cls}">
      <span class="side"><span class="nm">${esc(mgr(le))}</span><span class="tm">${esc(team(le))}</span></span>
      ${pending ? "" : `<span class="sc" data-count="${mine}">${mine}</span>`}
    </div>`;
  return `<div class="matches" style="${style}">${matches.map((m, i) => {
    const ca = pending ? "" : m.pa > m.pb ? "w" : m.pa < m.pb ? "l" : "d";
    const cb = pending ? "" : m.pb > m.pa ? "w" : m.pb < m.pa ? "l" : "d";
    const label = pending ? `${mgr(m.a)} mod ${mgr(m.b)}` : `${mgr(m.a)} ${m.pa}, ${mgr(m.b)} ${m.pb}`;
    return `<div class="panel spot match${pending ? " pending" : ""}" style="--i:${i}" aria-label="${esc(label)}">
      ${line(m.a, m.pa, m.pb, ca)}${line(m.b, m.pb, m.pa, cb)}
    </div>`;
  }).join("")}</div>`;
}

function inTrophyNow() {
  const b = D.blocks.find((x) => x.status === "live" || x.status === "locked");
  return b && b.rule !== "all" ? new Set(b.group) : new Set();
}

function divergeBg(v, span) {
  if (!v) return "";
  const a = Math.min(1, Math.abs(v) / span) * 0.85 + 0.15;
  return v > 0 ? `background: rgba(52,211,153,${(a * 0.32).toFixed(3)})` : `background: rgba(251,113,133,${(a * 0.28).toFixed(3)})`;
}

const dotStyle = (c, glow) => `style="background:${c};box-shadow:0 0 0 3px ${glow}"`;

// ---------------------------------------------------------------- view: stilling

let tableMode = "h2h";

async function viewStilling() {
  const latest = D.latest_gw;
  let hero = "";
  if (D.live && D.live.matches.length) {
    hero = `<section class="hero intro">
      <div class="hero-top"><div><span class="badge live"><span class="dot"></span>Live</span><h1>Runde ${D.live.gw}</h1></div>
      <p class="muted small">Stillingen ${dateOnly(D.updated)}</p></div>
      ${matchCards(D.live.matches)}</section>`;
  } else if (latest) {
    const snap = await loadGw(latest);
    const dl = D.next_round && D.game.next_deadline && new Date(D.game.next_deadline) > new Date();
    hero = `<section class="hero intro">
      <div class="hero-top">
        <div><span class="badge"><span class="dot"></span>Færdigspillet</span><h1>Runde ${latest}</h1></div>
        ${dl ? `<div class="countdown"><div class="lbl">Runde ${D.next_round.gw} lukker om</div><div class="t" id="cd"></div><div class="when">${when(D.game.next_deadline)}</div></div>` : ""}
      </div>
      ${matchCards(snap.matches)}</section>`;
  }

  const nextRound = D.next_round && D.next_round.matches.length && !D.live
    ? `<section class="sec"><div class="sec-head"><div><h2>Næste runde</h2><p class="lede">Kampene i runde ${D.next_round.gw}.</p></div></div>${matchCards(D.next_round.matches, { pending: true })}</section>`
    : "";

  app.innerHTML = `${hero}
    <section class="sec">
      <div class="sec-head">
        <div><h2>Tabel</h2><p class="lede" id="table-lede"></p></div>
        <div class="switch" role="group" aria-label="Vælg tabel">
          <span class="pill-thumb" aria-hidden="true"></span>
          <button data-mode="h2h">Head-to-head</button>
          <button data-mode="points">Samlede point</button>
          <button data-mode="form">Form</button>
        </div>
      </div>
      <div class="panel"><div class="scroll" id="table-box"></div></div>
      <div class="legend" id="table-legend"></div>
    </section>
    ${nextRound}`;

  const sw = app.querySelector(".switch");
  const draw = () => {
    sw.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.mode === tableMode));
    moveThumb(sw, sw.querySelector(`[data-mode="${tableMode}"]`));
    const box = app.querySelector("#table-box");
    const lede = app.querySelector("#table-lede");
    const legend = app.querySelector("#table-legend");
    const trophy = inTrophyNow();
    if (tableMode === "h2h") {
      lede.textContent = "Den officielle stilling. Ved lige point afgør flest scorede point.";
      const half = Math.floor(D.standings.length / 2);
      box.innerHTML = `<table><thead><tr><th>#</th><th class="l">Hold</th><th>K</th><th>V</th><th>U</th><th>T</th><th>Scoret</th><th>Imod</th><th class="l">Form</th><th>Point</th></tr></thead><tbody>
        ${D.standings.map((s, i) => {
          const mv = s.last_rank && s.last_rank !== s.rank ? (s.last_rank > s.rank ? `<span class="mv delta-up" title="Op fra ${s.last_rank}.">▲</span>` : `<span class="mv delta-down" title="Ned fra ${s.last_rank}.">▼</span>`) : "";
          return `<tr class="${i === half ? "cut" : ""}"><td class="rank">${rank(s.rank)}${mv}</td><td class="l"><span style="display:inline-flex;align-items:center">${who(s.le)}${trophy.has(s.le) ? '<span class="tag">Bundpokal</span>' : ""}</span></td><td>${s.w + s.d + s.l}</td><td>${s.w}</td><td>${s.d}</td><td>${s.l}</td><td>${s.pf}</td><td class="muted">${s.pa}</td><td class="l">${form(s.form)}</td><td class="pts">${s.pts}</td></tr>`;
        }).join("")}</tbody></table>`;
      legend.innerHTML = trophy.size ? `<span><span class="tag" style="margin:0">Bundpokal</span> låst i den nuværende bundpokal</span><span>Den lilla linje deler tabellen i top og bund.</span>` : "";
    } else if (tableMode === "points") {
      lede.textContent = "Hvis vi spillede klassisk FPL: alle scorede point lagt sammen, uden kampe.";
      const rankOf = Object.fromEntries(D.standings.map((s) => [s.le, s.rank]));
      box.innerHTML = `<table><thead><tr><th>#</th><th class="l">Hold</th><th>Snit</th><th>Bedst</th><th>Værst</th><th>Plads i H2H</th><th>Point</th></tr></thead><tbody>
        ${D.points_table.map((p, i) => {
          const diff = rankOf[p.le] - (i + 1);
          const d = diff > 0 ? `<span class="delta-down">${rankOf[p.le]}.</span>` : diff < 0 ? `<span class="delta-up">${rankOf[p.le]}.</span>` : `<span class="muted">${rankOf[p.le]}.</span>`;
          return `<tr><td class="rank">${rank(i + 1)}</td><td class="l">${who(p.le)}</td><td>${num(p.avg)}</td><td>${p.best}</td><td class="muted">${p.worst}</td><td>${d}</td><td class="pts">${p.total}</td></tr>`;
        }).join("")}</tbody></table>`;
      legend.innerHTML = `<span><span class="delta-down">Rød plads:</span> holdet ligger lavere i H2H, end pointene fortjener.</span><span><span class="delta-up">Grøn:</span> højere.</span>`;
    } else {
      const gws = D.gameweeks.slice(-4).map((g) => g.gw);
      lede.textContent = `Point i de seneste ${gws.length} runder (runde ${gws[0]}–${gws[gws.length - 1]}).`;
      const rows = [...D.points_table].sort((a, b) => b.recent - a.recent);
      box.innerHTML = `<table><thead><tr><th>#</th><th class="l">Hold</th>${gws.map((g) => `<th>R${g}</th>`).join("")}<th class="l">Resultater</th><th>Point</th></tr></thead><tbody>
        ${rows.map((p, i) => {
          const last = p.by_gw.slice(-gws.length);
          const st = D.standings.find((s) => s.le === p.le);
          return `<tr><td class="rank">${rank(i + 1)}</td><td class="l">${who(p.le)}</td>${last.map((v) => `<td>${v}</td>`).join("")}<td class="l">${form(st.form.slice(-gws.length))}</td><td class="pts">${p.recent}</td></tr>`;
        }).join("")}</tbody></table>`;
      legend.innerHTML = "";
    }
  };
  sw.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { tableMode = b.dataset.mode; draw(); }));
  draw();
  requestAnimationFrame(() => moveThumb(sw, sw.querySelector(`[data-mode="${tableMode}"]`)));
  tick(app.querySelector(".hero"));
  startCountdown(D.game.next_deadline);
}

// ---------------------------------------------------------------- view: bundpokal

function viewBundpokal() {
  const prize = D.league.prize_kr;
  const current = D.blocks.find((b) => b.status === "live") || D.blocks.find((b) => b.status === "locked")
    || [...D.blocks].reverse().find((b) => b.status === "finished");

  let race = "";
  if (current) {
    const max = Math.max(1, ...current.standings.map((r) => r.total));
    const lead = current.standings[0];
    const total = current.to - current.from + 1;
    const status = current.status === "locked"
      ? `Gruppen blev låst efter runde ${current.after_gw}. Blokken starter i runde ${current.from}.`
      : current.status === "live" ? `${current.played.length} af ${total} runder spillet.` : `Færdigspillet. ${names(current.winners)} vinder.`;
    const badge = current.status === "live" ? `<span class="badge live"><span class="dot"></span>I gang</span>`
      : current.status === "locked" ? `<span class="badge"><span class="dot" ${dotStyle("var(--violet)", "rgba(167,139,250,.2)")}></span>Gruppen er låst</span>`
      : `<span class="badge"><span class="dot" ${dotStyle("var(--gold)", "rgba(251,191,36,.2)")}></span>Afgjort</span>`;
    race = `<div class="panel spot beam race-card">
      ${badge}
      <h2 style="margin-top:14px">Runde ${current.from}–${current.to}</h2>
      <p class="lede">${status}</p>
      <ol class="race">${current.standings.map((r, i) => {
        const gap = i === 0 ? "" : ` (${lead.total - r.total} efter)`;
        const rk = current.group_ranks?.[r.le];
        const tipTxt = `<b>${esc(mgr(r.le))}</b><br>${Object.entries(r.by_gw).map(([g, v]) => `Runde ${g}: ${v}`).join("<br>") || "Ingen runder spillet endnu"}${rk ? `<br>${rk}. plads ved låsning` : ""}`;
        return `<li data-tip="${esc(tipTxt)}"><span class="pos">${i + 1}</span>${who(r.le)}<span class="pts" aria-label="${r.total} point${gap}">${r.total}</span><span class="bar"><i style="width:${Math.max(2, (r.total / max) * 100)}%"></i></span></li>`;
      }).join("")}</ol>
    </div>`;
  }

  const history = D.blocks.map((b) => {
    let res, sub, cls = b.status;
    if (b.status === "finished") {
      cls = "won";
      res = `🏆 ${names(b.winners)}`;
      sub = `${b.standings[0].total} point${b.final ? "" : ", foreløbigt"}.${b.rule === "all" ? " Alle deltog." : ""}`;
    } else if (b.status === "live") {
      res = `${names([b.standings[0].le])} fører`;
      sub = `${b.played.length} af ${b.to - b.from + 1} runder spillet`;
    } else if (b.status === "locked") {
      res = "Gruppen er låst";
      sub = names(b.group);
    } else {
      res = "Ikke startet";
      sub = `Gruppen låses efter runde ${b.after_gw}`;
    }
    return `<li class="panel spot ${cls}"><div class="gws">Runde ${b.from}–${b.to}</div><div class="res">${res}</div><div class="sub">${sub}</div></li>`;
  }).join("");

  app.innerHTML = `
    <h1>Bundpokalen</h1>
    <p class="lede">Hver blok har sin egen konkurrence for bundholdene. Den, der scorer flest point i blokken, vinder.</p>
    <div class="trophy">
      ${race}
      <div class="panel spot rules">
        <h3>Sådan virker det</h3>
        <div class="prize"><b>${prize} kr.</b> per blok</div>
        <ol>
          <li>Sæsonen er delt i seks blokke.</li>
          <li>Når en blok starter, låses de fem nederste hold i tabellen som gruppen.</li>
          <li>Kun scorede point tæller. H2H-resultater er ligegyldige.</li>
          <li>Rykker du op i løbet af blokken, er du stadig med.</li>
          <li>Ved lige point deles præmien.</li>
        </ol>
        <p class="small muted" style="margin:16px 0 0">Runde 1–6 var åben for alle.</p>
      </div>
    </div>
    <section class="sec"><div class="sec-head"><h2>Alle blokke</h2></div><ol class="timeline">${history}</ol></section>`;
  bindTips(app);
}

// ---------------------------------------------------------------- view: held og uheld

function luckChart(rows) {
  // draw at the real container width so text stays at true size on phones
  const W = Math.max(320, Math.min(1080, app.clientWidth - 22));
  const narrow = W < 520;
  const rowH = 36, top = 30, left = narrow ? 96 : 150, right = narrow ? 52 : 74;
  const H = top + rows.length * rowH + 8;
  const max = Math.ceil(Math.max(...rows.flatMap((r) => [r.pts, r.xpts])) / 3) * 3 + 3;
  const x = (v) => left + (v / max) * (W - left - right);
  const ticks = [];
  for (let t = 0; t <= max; t += narrow ? 6 : 3) ticks.push(t);
  const grid = ticks.map((t) => `<line x1="${x(t)}" x2="${x(t)}" y1="${top - 6}" y2="${H - 8}"/>`).join("");
  const axis = ticks.map((t) => `<text x="${x(t)}" y="${top - 13}" text-anchor="middle">${t}</text>`).join("");
  const body = rows.map((r, i) => {
    const y = top + i * rowH + rowH / 2;
    const lucky = r.luck >= 0;
    const t = `<b>${esc(mgr(r.le))}</b><br>Forventet: ${num(r.xpts)} point<br>Faktisk: ${r.pts} point<br>${lucky ? "Heldig" : "Uheldig"} med ${num(Math.abs(r.luck))} point<br>Mod alle: ${r.w}-${r.d}-${r.l}`;
    return `<g class="row" data-tip="${esc(t)}">
      <rect class="hit" x="0" y="${y - rowH / 2}" width="${W}" height="${rowH}" rx="8"/>
      <text x="${left - 14}" y="${y + 5}" text-anchor="end" font-size="14.5" font-weight="600">${esc(mgr(r.le))}</text>
      <line class="${lucky ? "lk-pos" : "lk-neg"}" x1="${x(r.xpts)}" x2="${x(r.pts)}" y1="${y}" y2="${y}" stroke-width="4" stroke-linecap="round"/>
      <circle class="dot-x" cx="${x(r.xpts)}" cy="${y}" r="6"/>
      <circle class="dot-a" cx="${x(r.pts)}" cy="${y}" r="6.5"/>
      <text x="${W - right + 14}" y="${y + 5}" font-size="14" font-weight="700" style="fill:${lucky ? "var(--emerald)" : "var(--rose)"}">${signed(r.luck)}</text>
    </g>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Forventede og faktiske point per hold"><g class="grid">${grid}</g><g class="axis">${axis}</g>${body}</svg>`;
}

async function viewHeld() {
  const rows = [...D.luck].sort((a, b) => b.luck - a.luck);
  const ids = D.standings.map((s) => s.le);
  const swap = D.schedule_swap;
  let span = 1;
  ids.forEach((a) => ids.forEach((b) => (span = Math.max(span, Math.abs(swap[a][b] - swap[a][a])))));
  const snaps = await Promise.all(D.gameweeks.map((g) => loadGw(g.gw)));
  const byXp = [...D.luck].sort((a, b) => b.xpts - a.xpts);
  const luckiest = rows[0], unluckiest = rows[rows.length - 1];
  const solid = (c) => `style="background:none;-webkit-text-fill-color:${c};color:${c}"`;

  app.innerHTML = `
    <h1>Held og uheld</h1>
    <p class="lede">I H2H betyder modstanderen meget. Her spiller hvert hold hver runde mod alle ni andre. Slår du 6 af 9 i en runde, er den 2 forventede point værd. Forskellen mellem forventet og faktisk er held.</p>

    <div class="recs" style="margin-top:28px">
      ${panel(`<span class="v" ${solid("var(--emerald)")}>${signed(luckiest.luck)}</span><span class="t">Heldigst: ${esc(mgr(luckiest.le))}</span><span class="d">${luckiest.pts} point mod ${num(luckiest.xpts)} forventede</span>`, "rec")}
      ${panel(`<span class="v" ${solid("var(--rose)")}>${signed(unluckiest.luck)}</span><span class="t">Mest uheldig: ${esc(mgr(unluckiest.le))}</span><span class="d">${unluckiest.pts} point mod ${num(unluckiest.xpts)} forventede</span>`, "rec")}
    </div>

    <section class="sec">
      <div class="sec-head"><h2>Forventet mod faktisk</h2></div>
      <div class="panel chart">${luckChart(rows)}</div>
      <div class="legend"><span><i class="key-x"></i> forventede point</span><span><i class="key-a"></i> faktiske point</span><span><i class="key-pos"></i> heldig</span><span><i class="key-neg"></i> uheldig</span></div>
    </section>

    <section class="sec">
      <div class="sec-head"><div><h2>Tabellen uden held</h2><p class="lede">Sorteret efter forventede point.</p></div></div>
      <div class="panel"><div class="scroll"><table><thead><tr><th>#</th><th class="l">Hold</th><th>Mod alle (V-U-T)</th><th>Vundet</th><th>Forventet</th><th>Faktisk</th><th>Held</th><th>Plads nu</th></tr></thead><tbody>
      ${byXp.map((r, i) => {
        const games = r.w + r.d + r.l;
        const st = D.standings.find((s) => s.le === r.le);
        return `<tr><td class="rank">${rank(i + 1)}</td><td class="l">${who(r.le)}</td><td>${r.w}-${r.d}-${r.l}</td><td>${games ? Math.round((r.w + r.d / 2) / games * 100) : 0}%</td><td class="pts">${num(r.xpts)}</td><td>${r.pts}</td><td class="${r.luck >= 0 ? "delta-up" : "delta-down"}">${signed(r.luck)}</td><td class="muted">${st.rank}.</td></tr>`;
      }).join("")}</tbody></table></div></div>
    </section>

    <section class="sec">
      <div class="sec-head"><div><h2>Forventede point per runde</h2><p class="lede">Hvor mange H2H-point runden var værd, målt mod hele feltet. 3,0 betyder, at du slog alle.</p></div></div>
      <div class="panel"><div class="scroll"><table><thead><tr><th class="l">Hold</th>${snaps.map((s) => `<th style="text-align:center">R${s.gw}</th>`).join("")}<th>I alt</th></tr></thead><tbody>
      ${byXp.map((r) => `<tr><td class="l">${who(r.le)}</td>${snaps.map((s) => {
        const ap = s.all_play[r.le];
        const m = s.matches.find((m) => m.a === r.le || m.b === r.le);
        const mine = m.a === r.le ? m.pa : m.pb, theirs = m.a === r.le ? m.pb : m.pa;
        const got = mine > theirs ? 3 : mine === theirs ? 1 : 0;
        const t = `<b>${esc(mgr(r.le))}, runde ${s.gw}</b><br>${mine} point slog ${ap.w} af 9<br>Forventet ${num(ap.xpts, 2)}, fik ${got}`;
        return `<td class="cell" style="${divergeBg(got - ap.xpts, 2)}" data-tip="${esc(t)}">${num(ap.xpts)}</td>`;
      }).join("")}<td class="pts">${num(r.xpts)}</td></tr>`).join("")}</tbody></table></div></div>
      <div class="legend"><span>Grøn: fik flere point end forventet den runde. Rød: færre.</span></div>
    </section>

    <section class="sec">
      <div class="sec-head"><div><h2>Byt kampprogram</h2><p class="lede">Hvor mange point havde du haft med en andens modstandere? Rækken er holdets egne scorer mod programmet i kolonnen. Den indrammede celle er virkeligheden.</p></div></div>
      <div class="panel"><div class="scroll"><table><thead><tr><th class="l">Hold</th>${ids.map((b) => `<th class="rot">${esc(mgr(b))}</th>`).join("")}</tr></thead><tbody>
      ${ids.map((a) => `<tr><td class="l">${who(a)}</td>${ids.map((b) => {
        const v = swap[a][b], d = v - swap[a][a];
        const t = `<b>${esc(mgr(a))}</b> med ${esc(mgr(b))}s program<br>${v} point (${d === 0 ? "samme som nu" : `${d > 0 ? "+" : "−"}${Math.abs(d)} i forhold til nu`})`;
        return `<td class="cell${a === b ? " diag" : ""}" style="${a === b ? "" : divergeBg(d, span)}" data-tip="${esc(t)}">${v}</td>`;
      }).join("")}</tr>`).join("")}</tbody></table></div></div>
      <div class="legend"><span>Grøn: bedre end dit eget program. Rød: værre.</span></div>
    </section>`;
  bindTips(app);
}

// ---------------------------------------------------------------- view: runder

const AWARDS = [
  ["top_score", "Rundens højeste score", "gold"],
  ["low_score", "Træskeen", "rose"],
  ["biggest_win", "Største sejr", "emerald"],
  ["luckiest_win", "Heldigste sejr", "", "Vandt med færrest point"],
  ["unluckiest_loss", "Mest uheldige nederlag", "", "Tabte med flest point"],
  ["bench_shame", "Bænkens skam", "", "Flest point på bænken"],
  ["waiver_hero", "Waiver-helten", "", "Flest point fra spillere hentet efter draften"],
  ["best_player", "Rundens spiller", "gold"],
];
const ACQ = { draft: "Draft", waiver: "Waiver", free: "Fri", other: "Byttet" };

function awardHtml(a) {
  return AWARDS.filter(([k]) => a[k]).map(([k, label, tone, hint]) => {
    const x = a[k];
    let body;
    if (k === "biggest_win") {
      body = `<span class="v">${x.value}</span>` + x.matches.map((m) => {
        const [w, l] = m.pa > m.pb ? [m.a, m.b] : [m.b, m.a];
        return `<span class="n">${esc(mgr(w))}</span> <span class="muted">slog ${esc(mgr(l))} ${Math.max(m.pa, m.pb)}–${Math.min(m.pa, m.pb)}</span>`;
      }).join("<br>");
    } else if (k === "best_player") {
      body = `<span class="v">${x.pts}</span><span class="n">${esc(x.name)}</span> <span class="muted">(${esc(x.club)}) hos ${esc(mgr(x.le))}</span>`;
    } else {
      body = `<span class="v">${x.value}</span><span class="n">${names(x.le)}</span>`;
    }
    return `<div class="panel spot award ${tone}"${hint ? ` title="${hint}"` : ""}><dt>${label}</dt><dd>${body}</dd></div>`;
  }).join("");
}

async function viewRunder(gwArg) {
  const list = D.gameweeks.map((g) => g.gw);
  if (!list.length) { app.innerHTML = `<h1>Runder</h1><p class="lede">Ingen runder er færdigspillet endnu.</p>`; return; }
  const gw = list.includes(Number(gwArg)) ? Number(gwArg) : list[list.length - 1];
  const s = await loadGw(gw);
  const picker = D.gameweeks.map((g) => `<a href="#runder/${g.gw}" ${g.gw === gw ? 'aria-current="page"' : ""} class="${g.final ? "" : "open"}" title="${g.final ? "Endeligt" : "Kan stadig blive rettet"}">${g.gw}</a>`).join("");
  const order = Object.entries(s.teams).sort((a, b) => b[1].score - a[1].score);
  const status = s.final ? `<span class="badge"><span class="dot"></span>Endeligt resultat</span>` : `<span class="badge"><span class="dot" ${dotStyle("var(--gold)", "rgba(251,191,36,.2)")}></span>Kan rettes frem til ${dateOnly(s.final_at)}</span>`;

  app.innerHTML = `
    <h1>Runder</h1>
    <nav class="gw-pick" aria-label="Vælg runde">${picker}</nav>
    <section class="sec" style="margin-top:32px">
      <div class="sec-head"><h2>Runde ${gw}</h2>${status}</div>
      ${matchCards(s.matches, { style: "margin-top:0" })}
    </section>
    <section class="sec"><div class="sec-head"><h2>Rundens priser</h2></div><dl class="awards">${awardHtml(s.awards)}</dl></section>
    <section class="sec">
      <div class="sec-head"><div><h2>Holdene</h2><p class="lede">Startelleveren efter automatiske udskiftninger. Tryk for at se spillerne.</p></div></div>
      <div class="lineups">${order.map(([le, t]) => {
        const ap = s.all_play[le];
        return `<details class="panel lineup"><summary>${who(Number(le))}<span class="s">${t.score}</span></summary>
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
      <div class="panel"><div class="scroll"><table><thead><tr><th>#</th><th class="l">Hold</th><th>V</th><th>U</th><th>T</th><th>Scoret</th><th>Point</th></tr></thead><tbody>
      ${s.table_after.map((r, i) => `<tr class="${i === Math.floor(s.table_after.length / 2) ? "cut" : ""}"><td class="rank">${rank(r.rank)}</td><td class="l">${who(r.le)}</td><td>${r.w}</td><td>${r.d}</td><td>${r.l}</td><td>${r.pf}</td><td class="pts">${r.pts}</td></tr>`).join("")}
      </tbody></table></div></div>
    </section>`;
  tick(app.querySelector(".matches"));
}

// ---------------------------------------------------------------- view: rekorder

function viewRekorder() {
  const R = D.records;
  const rec = (v, t, d) => panel(`<span class="v">${v}</span><span class="t">${t}</span><span class="d">${d}</span>`, "rec");
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
  const honourKeys = [["top_score", "Højeste"], ["low_score", "Træske"], ["luckiest_win", "Heldig sejr"], ["unluckiest_loss", "Uheldigt nederlag"], ["bench_shame", "Bænkeskam"], ["waiver_hero", "Waiver-helt"]];
  const honourRows = ids.map((le) => ({ le, v: honourKeys.map(([k]) => D.honours[le]?.[k] ?? 0), s: D.streaks[le] }));
  const streak = (s) => s.current.n ? `${s.current.n} ${{ W: "sejre", D: "uafgjorte", L: "nederlag" }[s.current.kind]}` : "–";
  const h2h = D.h2h;

  app.innerHTML = `
    <h1>Rekorder</h1>
    <section class="sec" style="margin-top:28px"><div class="recs">${recs}</div></section>

    <section class="sec">
      <div class="sec-head"><div><h2>Prisoversigt</h2><p class="lede">Hvor mange gange hver har fået rundens priser. Ved delt pris tæller den for begge.</p></div></div>
      <div class="panel"><div class="scroll"><table><thead><tr><th class="l">Hold</th>${honourKeys.map(([, l]) => `<th>${l}</th>`).join("")}<th>Stime nu</th><th>Længste sejrsstime</th></tr></thead><tbody>
      ${honourRows.map((r) => `<tr><td class="l">${who(r.le)}</td>${r.v.map((v) => `<td>${v ? `<b>${v}</b>` : '<span style="color:var(--dim)">0</span>'}</td>`).join("")}<td>${streak(r.s)}</td><td>${r.s.best_win}</td></tr>`).join("")}
      </tbody></table></div></div>
    </section>

    <div class="cols2">
      <section class="sec">
        <div class="sec-head"><div><h2>Bænkens skam</h2><p class="lede">Point, der blev på bænken hele sæsonen.</p></div></div>
        <div class="panel"><div class="scroll"><table><thead><tr><th class="l">Hold</th><th>Værste runde</th><th>I alt</th></tr></thead><tbody>
        ${D.bench.map((b) => `<tr><td class="l">${who(b.le)}</td><td>${b.worst} <span class="muted small">(R${b.worst_gw})</span></td><td class="pts">${b.total}</td></tr>`).join("")}
        </tbody></table></div></div>
      </section>
      <section class="sec">
        <div class="sec-head"><div><h2>Waiver-kongen</h2><p class="lede">Point fra spillere i startelleveren, som ikke blev draftet af holdet.</p></div></div>
        <div class="panel"><div class="scroll"><table><thead><tr><th class="l">Hold</th><th>Claims</th><th>Frie</th><th>Andel</th><th>Point</th></tr></thead><tbody>
        ${D.waivers.map((w) => `<tr><td class="l">${who(w.le)}</td><td title="${w.claims_won} vundet, ${w.claims_lost} tabt">${w.claims_won}/${w.claims_won + w.claims_lost}</td><td>${w.free_agents}</td><td>${Math.round(w.share * 100)}%</td><td class="pts">${w.pts}</td></tr>`).join("")}
        </tbody></table></div></div>
        <p class="small muted">Claims: vundne af forsøgte. Frie: hentet som fri spiller uden claim.</p>
      </section>
    </div>

    <section class="sec">
      <div class="sec-head"><div><h2>Sæsonens bedste fund</h2><p class="lede">Spillere hentet på waivers eller som fri spiller, efter point i startelleveren for det hold, der hentede dem.</p></div></div>
      <div class="panel"><div class="scroll"><table><thead><tr><th>#</th><th class="l">Spiller</th><th class="l">Hentet af</th><th class="l">Hvordan</th><th>Kampe i XI</th><th>Point</th></tr></thead><tbody>
      ${D.best_pickups.map((p, i) => `<tr><td class="rank">${rank(i + 1)}</td><td class="l"><b>${esc(p.name)}</b> <span class="muted small">${esc(p.pos)}, ${esc(p.club)}</span></td><td class="l">${esc(mgr(p.le))}</td><td class="l"><span class="acq ${p.acq}">${ACQ[p.acq]}</span></td><td>${p.starts}</td><td class="pts">${p.pts}</td></tr>`).join("")}
      </tbody></table></div></div>
    </section>

    <section class="sec">
      <div class="sec-head"><div><h2>Indbyrdes opgør</h2><p class="lede">Rækkens resultater mod kolonnen (V-U-T).</p></div></div>
      <div class="panel"><div class="scroll"><table><thead><tr><th class="l">Hold</th>${ids.map((b) => `<th class="rot">${esc(mgr(b))}</th>`).join("")}</tr></thead><tbody>
      ${ids.map((a) => `<tr><td class="l">${who(a)}</td>${ids.map((b) => {
        if (a === b) return `<td class="cell" style="color:var(--dim)">·</td>`;
        const r = h2h[a][b];
        if (!(r.w + r.d + r.l)) return `<td class="cell"></td>`;
        const t = `<b>${esc(mgr(a))} mod ${esc(mgr(b))}</b><br>${r.w} sejre, ${r.d} uafgjort, ${r.l} nederlag<br>Point: ${r.pf}–${r.pa}`;
        return `<td class="cell" style="${divergeBg(r.w - r.l, 2)}" data-tip="${esc(t)}">${r.w}-${r.d}-${r.l}</td>`;
      }).join("")}</tr>`).join("")}</tbody></table></div></div>
    </section>`;
  bindTips(app);
}

// ---------------------------------------------------------------- router

const VIEWS = { stilling: viewStilling, bundpokal: viewBundpokal, held: viewHeld, runder: viewRunder, rekorder: viewRekorder };
const nav = document.querySelector(".tabs");

async function route() {
  const [name, arg] = (location.hash.slice(1) || "stilling").split("/");
  const view = VIEWS[name] ? name : "stilling";
  let active = null;
  nav.querySelectorAll("a").forEach((a) => {
    if (a.dataset.view === view) { a.setAttribute("aria-current", "page"); active = a; } else a.removeAttribute("aria-current");
  });
  moveThumb(nav, active);
  tip.hidden = true;
  clearInterval(countdownTimer);
  try {
    await VIEWS[view](arg);
  } catch (e) {
    app.innerHTML = `<p class="error">Siden kunne ikke vises: ${esc(e.message)}. Prøv at genindlæse.</p>`;
    console.error(e);
  }
  if (route.ran) { window.scrollTo(0, 0); app.focus({ preventScroll: true }); }
  route.ran = true;
}

window.addEventListener("resize", () => moveThumb(nav, nav.querySelector('[aria-current="page"]')));

(async function init() {
  try {
    D = await getJSON("data/current.json");
  } catch (e) {
    app.innerHTML = `<p class="error">Ligadata kunne ikke hentes (${esc(e.message)}). Prøv at genindlæse siden.</p>`;
    return;
  }
  document.getElementById("updated").textContent = `Senest opdateret ${dateOnly(D.updated)}.`;
  document.getElementById("stamp").textContent = `Opdateret ${dateOnly(D.updated)}`;
  window.addEventListener("hashchange", route);
  if (document.fonts) await document.fonts.ready;
  route();
})();
