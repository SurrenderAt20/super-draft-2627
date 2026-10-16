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

const TOUCH = matchMedia("(hover: none)").matches;
const sheet = document.getElementById("sheet");

function openSheet(html) {
  sheet.querySelector(".sheet-body").innerHTML = html;
  sheet.hidden = false;
  requestAnimationFrame(() => sheet.classList.add("open"));
  sheet.querySelector(".sheet-close").focus({ preventScroll: true });
}
function closeSheet() {
  sheet.classList.remove("open");
  setTimeout(() => (sheet.hidden = true), REDUCED ? 0 : 220);
}
sheet.addEventListener("click", (e) => { if (e.target === sheet || e.target.closest(".sheet-close")) closeSheet(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !sheet.hidden) closeSheet(); });

function bindTips(root) {
  root.querySelectorAll("[data-tip]").forEach((el) => {
    el.setAttribute("tabindex", "0");
    el.setAttribute("role", "button");
    el.classList.add("has-tip");
    if (TOUCH) {
      el.addEventListener("click", () => openSheet(el.dataset.tip));
    } else {
      el.addEventListener("mousemove", (e) => {
        tip.innerHTML = el.dataset.tip;
        tip.hidden = false;
        const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
        const y = e.clientY + 16 + tip.offsetHeight > window.innerHeight ? e.clientY - tip.offsetHeight - 12 : e.clientY + 16;
        tip.style.left = `${Math.max(8, x)}px`;
        tip.style.top = `${y}px`;
      });
      el.addEventListener("mouseleave", () => (tip.hidden = true));
    }
    el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openSheet(el.dataset.tip); } });
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

// numbers count up from 0 the first time they scroll into view
const COUNT_SEL = ".match .sc, td.pts, .rec .v, .award .v, .race .pts, details.lineup .s, .prize b";
function countUp(el) {
  const m = el.textContent.trim().match(/^([+−-]?)(\d+)(?:,(\d+))?([\s\S]*)$/);
  if (!m) return;
  const [, sign, int, frac = "", rest] = m;
  const target = Number(int + (frac ? "." + frac : ""));
  const dec = frac.length;
  const fmt = (v) => sign + (dec ? num(v, dec) : String(Math.round(v))) + rest;
  const dur = 900, start = performance.now();
  el.textContent = fmt(0);
  const step = (t) => {
    const p = Math.min(1, (t - start) / dur);
    el.textContent = fmt(target * (1 - Math.pow(1 - p, 3)));
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// elements rise into place as they scroll into view; grids stagger their children
const REVEAL_SEL = "main > h1, main > .lede, .hero-top, .sec-head, .matches > .panel, .recs > .panel, .awards > .panel, .timeline > li, .lineups > details, .trophy > .panel, .sec > .panel, .gw-pick, .legend";
const io = "IntersectionObserver" in window ? new IntersectionObserver((entries) => {
  entries.forEach((en) => {
    if (!en.isIntersecting) return;
    const el = en.target;
    io.unobserve(el);
    el.classList.add("in");
    el.querySelectorAll(COUNT_SEL).forEach(countUp);
  });
}, { rootMargin: "0px 0px -6% 0px", threshold: 0.06 }) : null;

// safety net: after any scroll, reveal whatever is on screen even if the observer missed a jump
let revealTick = 0;
document.addEventListener("scroll", () => {
  if (revealTick) return;
  revealTick = requestAnimationFrame(() => {
    revealTick = 0;
    document.querySelectorAll(".reveal:not(.in)").forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.top < innerHeight && r.bottom > 0) {
        el.classList.add("in");
        io?.unobserve(el);
        el.querySelectorAll(COUNT_SEL).forEach(countUp);
      }
    });
  });
}, { passive: true });

function enhance(root) {
  if (REDUCED || !io) return;
  const seen = new Map();
  root.querySelectorAll(REVEAL_SEL).forEach((el) => {
    const i = seen.get(el.parentElement) ?? 0;
    seen.set(el.parentElement, i + 1);
    el.style.setProperty("--d", `${Math.min(i, 8) * 55}ms`);
    el.classList.add("reveal");
    // anything already on screen shows at once; the rest waits for the scroll
    const r = el.getBoundingClientRect();
    if (r.top < innerHeight && r.bottom > 0) {
      requestAnimationFrame(() => el.classList.add("in"));
      setTimeout(() => el.classList.add("in"), 50);
      el.querySelectorAll(COUNT_SEL).forEach(countUp);
    } else io.observe(el);
  });
}

// short column headers spelled out for the sheet
const FULL_HEAD = { K: "Kampe", V: "Vundet", U: "Uafgjort", T: "Tabt", Scoret: "Point scoret", Imod: "Point imod" };
const fullHead = (h) => FULL_HEAD[h] || h.replace(/^R(\d+)$/, "Runde $1");

// phones: tables show their key columns; tapping a row opens every column in the sheet
const NARROW = matchMedia("(max-width: 720px)");
function enhanceTables(root) {
  root.querySelectorAll("table[data-keep]").forEach((t) => {
    const heads = [...t.tHead.rows[0].cells];
    const n = heads.length;
    const keep = new Set(t.dataset.keep.split(",").map((x) => (Number(x) + n) % n));
    t.querySelectorAll("tr").forEach((tr) => [...tr.cells].forEach((c, i) => c.classList.toggle("opt", !keep.has(i))));
    t.classList.add("rtable");
    t.tBodies[0].querySelectorAll("tr").forEach((tr) => {
      tr.addEventListener("click", () => {
        if (!(TOUCH || NARROW.matches)) return;
        const title = tr.querySelector(".who b, td.l b")?.textContent ?? "";
        // skip the rank and the name cell (the name is already the sheet's title)
        const rows = [...tr.cells].map((c, i) => [heads[i].textContent.trim(), c])
          .filter(([h, c]) => h && h !== "#" && !c.querySelector(".who") && c.querySelector("b")?.textContent !== title);
        openSheet(`<b>${esc(title)}</b><dl class="kv">${rows.map(([h, c]) => {
          const wide = c.classList.contains("never") ? ' class="wide"' : "";
          return `<dt${wide}>${esc(fullHead(h))}</dt><dd${wide}>${c.innerHTML}</dd>`;
        }).join("")}</dl>`);
      });
    });
  });
}

// wide grids scroll sideways: names stay put and the edge fades while there is more to see
function enhanceMatrices(root) {
  root.querySelectorAll(".scroll.matrix").forEach((sc) => {
    const upd = () => sc.classList.toggle("more", sc.scrollLeft + sc.clientWidth < sc.scrollWidth - 4);
    sc.addEventListener("scroll", upd, { passive: true });
    upd();
  });
}

// section chips: jump straight to any part of the page, with the current one highlighted
let chipObserver = null;
function buildChips(root) {
  chipObserver?.disconnect();
  const secs = [...root.querySelectorAll("section.sec")].filter((sec) => sec.dataset.chip || sec.querySelector(":scope > .sec-head h2"));
  if (secs.length < 2) return;
  const slug = (t) => t.toLowerCase().replace(/[æ]/g, "ae").replace(/[ø]/g, "oe").replace(/[å]/g, "aa").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const items = secs.map((sec) => {
    const label = sec.dataset.chip || sec.querySelector(":scope > .sec-head h2").textContent.trim();
    sec.id = sec.id || `s-${slug(label)}`;
    return { sec, label };
  });
  const nav = document.createElement("nav");
  nav.className = "chips";
  nav.setAttribute("aria-label", "Sektioner på siden");
  nav.innerHTML = `<span class="chips-title">På siden</span><div class="chips-inner">${items.map((it) => `<button type="button" data-target="${it.sec.id}">${esc(it.label)}</button>`).join("")}</div>`;
  let anchor = root.querySelector(":scope > h1");
  while (anchor?.nextElementSibling?.matches(".lede, .gw-pick")) anchor = anchor.nextElementSibling;
  if (anchor && !items[0].sec.classList.contains("hero")) anchor.after(nav); else root.prepend(nav);
  const btns = [...nav.querySelectorAll("button")];
  const inner = nav.querySelector(".chips-inner");
  const setActive = (id) => btns.forEach((b) => {
    const on = b.dataset.target === id;
    b.classList.toggle("on", on);
    // keep the active chip in view in the sideways row (never scrolls the page itself)
    if (on && inner.scrollWidth > inner.clientWidth) inner.scrollTo({ left: b.offsetLeft - 24, behavior: REDUCED ? "auto" : "smooth" });
  });
  btns.forEach((b) => b.addEventListener("click", () => {
    document.getElementById(b.dataset.target).scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });
    setActive(b.dataset.target);
  }));
  const visible = new Map();
  chipObserver = new IntersectionObserver((entries) => {
    entries.forEach((e) => visible.set(e.target.id, e.isIntersecting ? e.intersectionRect.height : 0));
    const best = [...visible.entries()].sort((a, b) => b[1] - a[1])[0];
    if (best && best[1] > 0) setActive(best[0]);
  }, { rootMargin: "-30% 0px -45% 0px", threshold: [0, 0.25, 0.5, 1] });
  items.forEach((it) => chipObserver.observe(it.sec));
  setActive(items[0].sec.id);

  // phones and tablets: a small button by each heading jumps to the next section
  const jump = (target, label, up) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "jump";
    b.setAttribute("aria-label", up ? "Til toppen" : `Næste: ${label}`);
    b.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${up ? "M6 15l6-6 6 6" : "M6 9l6 6 6-6"}"/></svg>${up ? "Til toppen" : "Næste"}`;
    b.addEventListener("click", () => (up ? window.scrollTo({ top: 0, behavior: REDUCED ? "auto" : "smooth" })
      : target.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" })));
    return b;
  };
  const pageH1 = root.querySelector(":scope > h1");
  if (pageH1 && !items[0].sec.classList.contains("hero")) pageH1.append(jump(items[0].sec, items[0].label));
  items.forEach((it, i) => {
    const h = it.sec.querySelector(":scope > .sec-head h2") || it.sec.querySelector("h1");
    if (!h) return;
    const next = items[i + 1];
    h.append(next ? jump(next.sec, next.label) : jump(null, "", true));
  });
}

// one line telling phone users that numbers and rows open details
function addTapHint(root) {
  if (!TOUCH) return;
  if (!root.querySelector("[data-tip], table[data-keep]")) return;
  const p = document.createElement("p");
  p.className = "tap-hint";
  p.textContent = "Tryk på tal, navne og rækker for flere detaljer.";
  const chips = root.querySelector(".chips");
  (chips || root.firstElementChild).after(p);
}

// the top bar's height decides where sticky chips and section jumps stop
function measureTop() {
  const h = document.querySelector(".topbar").offsetHeight;
  document.documentElement.style.setProperty("--top", `${h}px`);
}
window.addEventListener("resize", measureTop);

// the next gameweek's deadlines, with a countdown to whichever comes next
function milestones() {
  const g = D.game;
  return [
    g.next_trades && { at: g.next_trades, label: "Byttehandler lukker", note: `Et bytte med en anden manager skal være godkendt inden da for at tælle i runde ${g.next}.` },
    g.next_waivers && { at: g.next_waivers, label: "Waiver-ønsker lukker", note: "Sidste chance for at ønske ledige spillere. Ønskerne afgøres efter waiver-rækkefølgen." },
    g.next_waivers && { at: null, label: "Ledige spillere frigives", note: g.waivers_processed ? "Waivers er afgjort. Nu gælder først til mølle." : "Når waivers er afgjort, gælder først til mølle.", done: !!g.waivers_processed },
    g.next_deadline && { at: g.next_deadline, label: "Holdet låses", note: "Startopstilling og sidste skift skal være på plads." },
    g.next_kickoff && { at: g.next_kickoff, label: "Første kamp", note: `Runde ${g.next} går i gang.` },
  ].filter(Boolean);
}
const short = (iso) => new Intl.DateTimeFormat("da-DK", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Copenhagen" }).format(new Date(iso));

function deadlinesHtml() {
  return `<div class="deadlines panel">
    <div class="dl-head"><h3>Inden runde ${D.game.next}</h3><span class="lbl" id="cd-label"></span><div class="t" id="cd"></div></div>
    <ol class="steps" id="steps"></ol>
  </div>`;
}

function startCountdown() {
  clearInterval(countdownTimer);
  const el = app.querySelector("#cd");
  if (!el) return;
  const steps = app.querySelector("#steps");
  const label = app.querySelector("#cd-label");
  let lastSteps = "";
  const draw = () => {
    const now = Date.now();
    const ms = milestones();
    // a step without a time (free agents) counts as done once the step before it has passed and the API says so
    const isDone = (m) => (m.at ? new Date(m.at).getTime() <= now : m.done);
    const next = ms.find((m) => m.at && !isDone(m));
    const html = ms.map((m) => `<li class="${isDone(m) ? "done" : m === next ? "next" : ""}">
        <span class="mk" aria-hidden="true"></span>
        <span class="st"><b>${m.label}</b><span>${m.note}</span></span>
        <span class="tm">${m.at ? short(m.at) : ""}</span>
      </li>`).join("");
    if (html !== lastSteps) { steps.innerHTML = html; lastSteps = html; }
    if (!next) { label.textContent = `Runde ${D.game.next} er i gang`; el.innerHTML = ""; return; }
    label.textContent = `${next.label} om`;
    let s = Math.max(0, Math.floor((new Date(next.at).getTime() - now) / 1000));
    const d = Math.floor(s / 86400); s -= d * 86400;
    const h = Math.floor(s / 3600); s -= h * 3600;
    const mi = Math.floor(s / 60); s -= mi * 60;
    el.innerHTML = [[d, "dage"], [h, "timer"], [mi, "min"], [s, "sek"]].map(([v, l]) => `<span>${String(v).padStart(2, "0")}<small>${l}</small></span>`).join("");
  };
  draw();
  countdownTimer = setInterval(draw, 1000);
}

// ---------------------------------------------------------------- shared pieces

function matchCards(matches, { pending = false, style = "" } = {}) {
  const line = (le, mine, theirs, cls) => `<div class="line ${cls}">
      <span class="side"><span class="nm">${esc(mgr(le))}</span><span class="tm">${esc(team(le))}</span></span>
      ${pending ? "" : `<span class="sc">${mine}</span>`}
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

// ---------------------------------------------------------------- forecasts (public)

const pc = (x) => `${Math.round(x * 100)}%`;

function calibText(F) {
  const c = F.calibration;
  return c && c.fav_n ? `I testen på runde ${c.rounds[0]}–${c.rounds[c.rounds.length - 1]}, hvor hver runde blev forudsagt kun ud fra runderne før, vandt favoritten ${c.fav_won} af ${c.fav_n} kampe (${pc(c.fav_won / c.fav_n)}).` : "";
}

function oddsCards(F) {
  return `<div class="odds-list">${F.next_round.map((m) => {
    const tip = `<b>${esc(mgr(m.a))} mod ${esc(mgr(m.b))}</b>Forventet score ${num(m.ea, 1)} mod ${num(m.eb, 1)}, ud fra hvert holds bedste startopstilling i modellen.<br>Simuleret ${F.sims.toLocaleString("da-DK")} gange med den spredning, holdscorerne faktisk har haft (±${num(F.calibration.sd, 0)} point).<br>${calibText(F)}`;
    return `<div class="panel spot odds" data-tip="${esc(tip)}">
      <div class="o-side"><b>${esc(mgr(m.a))}</b><span>${esc(team(m.a))}</span><span class="o-exp">${num(m.ea, 0)} forventet</span></div>
      <div class="o-mid">
        <div class="o-pcts"><b class="${m.pa >= m.pb ? "fav" : ""}">${pc(m.pa)}</b><span>Uafgjort ${pc(m.pd)}</span><b class="${m.pb > m.pa ? "fav" : ""}">${pc(m.pb)}</b></div>
        <div class="o-bar" aria-hidden="true"><i class="a" style="width:${m.pa * 100}%"></i><i class="d" style="width:${m.pd * 100}%"></i><i class="b" style="width:${m.pb * 100}%"></i></div>
      </div>
      <div class="o-side r"><b>${esc(mgr(m.b))}</b><span>${esc(team(m.b))}</span><span class="o-exp">${num(m.eb, 0)} forventet</span></div>
    </div>`;
  }).join("")}</div>`;
}

function seasonForecast(F) {
  const n = F.season.length;
  const rows = F.season;
  const special = F.special_rounds?.length
    ? `<p class="small" style="margin-top:12px">${F.special_rounds.map((r) => `Runde ${r.gw}: ${r.double.length ? `dobbeltkamp for ${r.double.join(", ")}` : ""}${r.double.length && r.blank.length ? "; " : ""}${r.blank.length ? `ingen kamp for ${r.blank.join(", ")}` : ""}`).join(". ")}.</p>` : "";
  return `<section class="sec">
    <div class="sec-head"><div><h2>Sæsonprognose</h2><p class="lede">Resten af sæsonen simuleret ${F.sims.toLocaleString("da-DK")} gange ud fra holdenes forventede point og H2H-programmet.</p></div></div>
    <div class="panel"><div class="scroll"><table data-keep="0,1,4,6"><thead><tr><th>#</th><th class="l">Hold</th><th>Forv. placering</th><th>Forv. point</th><th>Vinder ligaen</th><th>Top 3</th><th>Sidst</th></tr></thead><tbody>
      ${rows.map((r, i) => `<tr><td class="rank">${rank(i + 1)}</td><td class="l">${who(r.le)}</td><td>${num(r.exp_rank, 1)}</td><td>${num(r.exp_pts, 0)}</td><td class="pts">${pc(r.p_first)}</td><td>${pc(r.p_top3)}</td><td class="${r.p_last >= 0.15 ? "delta-down" : ""}">${pc(r.p_last)}</td></tr>`).join("")}
    </tbody></table></div></div>
    <h3 style="margin-top:28px">Chance for hver placering</h3>
    <div class="panel" style="margin-top:12px"><div class="scroll matrix"><table class="posgrid"><thead><tr><th class="l">Hold</th>${Array.from({ length: n }, (_, i) => `<th>${i + 1}.</th>`).join("")}</tr></thead><tbody>
      ${rows.map((r) => `<tr><td class="l">${who(r.le)}</td>${r.dist.map((p, i) => `<td class="cell" style="background:rgba(167,139,250,${(Math.min(1, p / 0.4) * 0.55).toFixed(3)})" data-tip="${esc(`<b>${esc(mgr(r.le))}</b>${i + 1}. plads: ${pc(p)}`)}">${p >= 0.005 ? pc(p) : ""}</td>`).join("")}</tr>`).join("")}
    </tbody></table></div></div>
    ${special}
    <p class="small muted" style="margin-top:12px;max-width:72ch">${calibText(F)} Hvert hold stilles op med sin bedste startopstilling ifølge modellen. For de nærmeste kampe bruges bookmakerodds (The Odds API og football-data.co.uk) til holdenes forventede mål. Holdene antages at beholde deres trupper, men waivers og byttehandler ændrer dem, så hver simulation giver hvert hold en varig afvigelse på ±${num(F.drift_sd, 0)} point per runde. Den afvigelse er en antagelse, ikke målt.</p>
  </section>`;
}

// ---------------------------------------------------------------- view: stilling

let tableMode = "h2h";

async function viewStilling() {
  const latest = D.latest_gw;
  let hero = "";
  if (D.live && D.live.matches.length) {
    hero = `<section class="hero sec" id="runde" data-chip="Runde ${D.live.gw}">
      <div class="hero-top"><div><span class="badge live"><span class="dot"></span>Live</span><h1>Runde ${D.live.gw}</h1></div>
      <p class="muted small">Stillingen ${dateOnly(D.updated)}</p></div>
      ${matchCards(D.live.matches)}</section>`;
  } else if (latest) {
    const snap = await loadGw(latest);
    const dl = D.next_round && D.game.next_deadline;
    const A = snap.awards;
    const sum = [
      A.top_score && `${names(A.top_score.le)} scorede mest med ${A.top_score.value} point.`,
      A.biggest_win && (() => { const m = A.biggest_win.matches[0]; const [w, l] = m.pa > m.pb ? [m.a, m.b] : [m.b, m.a]; return `Største sejr: ${esc(mgr(w))} over ${esc(mgr(l))} med ${A.biggest_win.value}.`; })(),
      A.low_score && `${names(A.low_score.le)} fik træskeen med ${A.low_score.value}.`,
    ].filter(Boolean).join(" ");
    hero = `<section class="hero sec" id="runde" data-chip="Runde ${latest}">
      <div class="hero-top${dl ? " has-dl" : ""}">
        <div class="hero-title"><span class="badge"><span class="dot"></span>Færdigspillet</span><h1>Runde ${latest}</h1><p class="hero-sum">${sum}</p><a class="link" href="#runder/${latest}">Se hele runden</a></div>
        ${dl ? deadlinesHtml() : ""}
      </div>
      ${matchCards(snap.matches)}</section>`;
  }

  const F = D.forecast;
  const odds = F && F.next_round?.length && F.next_gw === D.next_round?.gw;
  const nextRound = D.next_round && D.next_round.matches.length && !D.live
    ? `<section class="sec"><div class="sec-head"><div><h2>Næste runde</h2><p class="lede">${odds
        ? `Kampene i runde ${D.next_round.gw} med vinderchancer. Tryk på en kamp for at se, hvordan chancen er regnet.`
        : `Kampene i runde ${D.next_round.gw}.`}</p></div></div>
      ${odds ? oddsCards(F) : matchCards(D.next_round.matches, { pending: true })}</section>`
    : "";
  const seasonSec = F?.season?.length ? seasonForecast(F) : "";

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
    ${nextRound}
    ${seasonSec}`;

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
      box.innerHTML = `<table data-keep="0,1,6,9"><thead><tr><th>#</th><th class="l">Hold</th><th>K</th><th>V</th><th>U</th><th>T</th><th>Scoret</th><th>Imod</th><th class="l">Form</th><th>Point</th></tr></thead><tbody>
        ${D.standings.map((s, i) => {
          const mv = s.last_rank && s.last_rank !== s.rank ? (s.last_rank > s.rank ? `<span class="mv delta-up" title="Op fra ${s.last_rank}.">▲</span>` : `<span class="mv delta-down" title="Ned fra ${s.last_rank}.">▼</span>`) : "";
          return `<tr class="${i === half ? "cut" : ""}"><td class="rank">${rank(s.rank)}${mv}</td><td class="l"><span style="display:inline-flex;align-items:center">${who(s.le)}${trophy.has(s.le) ? '<span class="tag">Bundpokal</span>' : ""}</span></td><td>${s.w + s.d + s.l}</td><td>${s.w}</td><td>${s.d}</td><td>${s.l}</td><td>${s.pf}</td><td class="muted">${s.pa}</td><td class="l">${form(s.form)}</td><td class="pts">${s.pts}</td></tr>`;
        }).join("")}</tbody></table>`;
      legend.innerHTML = trophy.size ? `<span><span class="tag" style="margin:0">Bundpokal</span> låst i den nuværende bundpokal</span><span>Den lilla linje deler tabellen i top og bund.</span>` : "";
    } else if (tableMode === "points") {
      lede.textContent = "Hvis vi spillede klassisk FPL: alle scorede point lagt sammen, uden kampe.";
      const rankOf = Object.fromEntries(D.standings.map((s) => [s.le, s.rank]));
      box.innerHTML = `<table data-keep="0,1,2,6"><thead><tr><th>#</th><th class="l">Hold</th><th>Snit</th><th>Bedst</th><th>Værst</th><th>Plads i H2H</th><th>Point</th></tr></thead><tbody>
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
      box.innerHTML = `<table data-keep="0,1,-1"><thead><tr><th>#</th><th class="l">Hold</th>${gws.map((g) => `<th>R${g}</th>`).join("")}<th class="l">Resultater</th><th>Point</th></tr></thead><tbody>
        ${rows.map((p, i) => {
          const last = p.by_gw.slice(-gws.length);
          const st = D.standings.find((s) => s.le === p.le);
          return `<tr><td class="rank">${rank(i + 1)}</td><td class="l">${who(p.le)}</td>${last.map((v) => `<td>${v}</td>`).join("")}<td class="l">${form(st.form.slice(-gws.length))}</td><td class="pts">${p.recent}</td></tr>`;
        }).join("")}</tbody></table>`;
      legend.innerHTML = "";
    }
  };
  sw.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    tableMode = b.dataset.mode;
    draw();
    enhanceTables(app.querySelector("#table-box"));
    if (!REDUCED) app.querySelectorAll("#table-box td.pts").forEach(countUp);
  }));
  draw();
  requestAnimationFrame(() => moveThumb(sw, sw.querySelector(`[data-mode="${tableMode}"]`)));
  startCountdown();
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
        const pw = D.forecast?.trophy?.block === current.id ? D.forecast.trophy.p_win[r.le] : null;
        return `<li data-tip="${esc(tipTxt + (pw != null ? `<br>Chance for at vinde blokken: ${pc(pw)}` : ""))}"><span class="pos">${i + 1}</span>${who(r.le)}<span class="pts" aria-label="${r.total} point${gap}">${r.total}</span><span class="bar"><i style="width:${Math.max(2, (r.total / max) * 100)}%"></i></span>${pw != null ? `<span class="p-win">${pc(pw)} chance for at vinde</span>` : ""}</li>`;
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
      <div class="panel"><div class="scroll"><table data-keep="0,1,4,6"><thead><tr><th>#</th><th class="l">Hold</th><th>Mod alle (V-U-T)</th><th>Vundet</th><th>Forventet</th><th>Faktisk</th><th>Held</th><th>Plads nu</th></tr></thead><tbody>
      ${byXp.map((r, i) => {
        const games = r.w + r.d + r.l;
        const st = D.standings.find((s) => s.le === r.le);
        return `<tr><td class="rank">${rank(i + 1)}</td><td class="l">${who(r.le)}</td><td>${r.w}-${r.d}-${r.l}</td><td>${games ? Math.round((r.w + r.d / 2) / games * 100) : 0}%</td><td class="pts">${num(r.xpts)}</td><td>${r.pts}</td><td class="${r.luck >= 0 ? "delta-up" : "delta-down"}">${signed(r.luck)}</td><td class="muted">${st.rank}.</td></tr>`;
      }).join("")}</tbody></table></div></div>
    </section>

    <section class="sec">
      <div class="sec-head"><div><h2>Forventede point per runde</h2><p class="lede">Hvor mange H2H-point runden var værd, målt mod hele feltet. 3,0 betyder, at du slog alle.</p></div></div>
      <div class="panel"><div class="scroll matrix"><table><thead><tr><th class="l">Hold</th>${snaps.map((s) => `<th style="text-align:center">R${s.gw}</th>`).join("")}<th>I alt</th></tr></thead><tbody>
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
      <div class="panel"><div class="scroll matrix"><table><thead><tr><th class="l">Hold</th>${ids.map((b) => `<th class="rot">${esc(mgr(b))}</th>`).join("")}</tr></thead><tbody>
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
    return `<div class="panel spot award ${tone}"><dt>${label}${hint ? `<small>${hint}</small>` : ""}</dt><dd>${body}</dd></div>`;
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
      <div class="panel"><div class="scroll"><table data-keep="0,1,5,6"><thead><tr><th>#</th><th class="l">Hold</th><th>V</th><th>U</th><th>T</th><th>Scoret</th><th>Point</th></tr></thead><tbody>
      ${s.table_after.map((r, i) => `<tr class="${i === Math.floor(s.table_after.length / 2) ? "cut" : ""}"><td class="rank">${rank(r.rank)}</td><td class="l">${who(r.le)}</td><td>${r.w}</td><td>${r.d}</td><td>${r.l}</td><td>${r.pf}</td><td class="pts">${r.pts}</td></tr>`).join("")}
      </tbody></table></div></div>
    </section>`;
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
    D.most_moved?.[0] && rec(D.most_moved[0].moves, "Mest handlede spiller", `${esc(D.most_moved[0].name)} er hentet eller droppet ${D.most_moved[0].moves} gange`),
  ].filter(Boolean).join("");

  // most moved players: every pickup and drop, and the chain of managers who had them
  const step = (h) => h.type === "draft" ? `Draftet af ${esc(mgr(h.le))}`
    : h.type === "in" ? `Før runde ${h.gw}: hentet af ${esc(mgr(h.le))} ${h.kind === "waiver" ? "på waivers" : "som fri spiller"}`
    : `Før runde ${h.gw}: droppet af ${esc(mgr(h.le))}`;
  const chev = '<svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>';
  const chain = (r) => {
    const hands = r.history.filter((h) => h.type !== "out").map((h) => `<span>${esc(mgr(h.le))}</span>`);
    if (!r.owner) hands.push('<span class="free">Ledig</span>');
    return `<span class="chain">${hands.join(chev)}</span>`;
  };
  const moved = D.most_moved || [];

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
      <div class="panel"><div class="scroll matrix"><table><thead><tr><th class="l">Hold</th>${honourKeys.map(([, l]) => `<th>${l}</th>`).join("")}<th>Stime nu</th><th>Længste sejrsstime</th></tr></thead><tbody>
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
        <div class="panel"><div class="scroll"><table data-keep="0,1,4"><thead><tr><th class="l">Hold</th><th>Claims</th><th>Frie</th><th>Andel</th><th>Point</th></tr></thead><tbody>
        ${D.waivers.map((w) => `<tr><td class="l">${who(w.le)}</td><td data-tip="${w.claims_won} claims vundet, ${w.claims_lost} tabt">${w.claims_won}/${w.claims_won + w.claims_lost}</td><td>${w.free_agents}</td><td>${Math.round(w.share * 100)}%</td><td class="pts">${w.pts}</td></tr>`).join("")}
        </tbody></table></div></div>
        <p class="small muted">Claims: vundne af forsøgte. Frie: hentet som fri spiller uden claim.</p>
      </section>
    </div>

    <section class="sec">
      <div class="sec-head"><div><h2>Sæsonens bedste fund</h2><p class="lede">Spillere hentet på waivers eller som fri spiller, efter point i startelleveren for det hold, der hentede dem.</p></div></div>
      <div class="panel"><div class="scroll"><table data-keep="0,1,2,5"><thead><tr><th>#</th><th class="l">Spiller</th><th class="l">Hentet af</th><th class="l">Hvordan</th><th>Kampe i XI</th><th>Point</th></tr></thead><tbody>
      ${D.best_pickups.map((p, i) => `<tr><td class="rank">${rank(i + 1)}</td><td class="l"><b>${esc(p.name)}</b> <span class="muted small">${esc(p.pos)}, ${esc(p.club)}</span></td><td class="l">${esc(mgr(p.le))}</td><td class="l"><span class="acq ${p.acq}">${ACQ[p.acq]}</span></td><td>${p.starts}</td><td class="pts">${p.pts}</td></tr>`).join("")}
      </tbody></table></div></div>
    </section>

    ${moved.length ? `<section class="sec">
      <div class="sec-head"><div><h2>Mest handlede spillere</h2><p class="lede">Spillere, der er blevet hentet og droppet flest gange. En handel er én gang hentet eller én gang droppet.</p></div></div>
      <div class="panel"><div class="scroll"><table data-keep="0,1,2,6"><thead><tr><th>#</th><th class="l">Spiller</th><th>Handler</th><th>Hentet</th><th>Droppet</th><th>Managere</th><th class="l">Ejer nu</th><th class="l">Har været hos</th><th>Sæsonpoint</th><th class="never">Forløb</th></tr></thead><tbody>
      ${moved.map((r, i) => `<tr data-tip="${esc(`<b>${esc(r.name)}</b>${r.history.map(step).join("<br>")}`)}"><td class="rank">${rank(i + 1)}</td><td class="l"><b>${esc(r.name)}</b> <span class="muted small">${esc(r.pos)}, ${esc(r.club)}</span></td><td class="pts">${r.moves}</td><td>${r.ins}</td><td>${r.outs}</td><td>${r.managers}</td><td class="l">${r.owner ? esc(mgr(r.owner)) : '<span class="free">Ledig</span>'}</td><td class="l">${chain(r)}</td><td class="muted">${r.pts}</td><td class="never l">${r.history.map(step).join("<br>")}</td></tr>`).join("")}
      </tbody></table></div></div>
      <div class="legend hover-only"><span>Hold musen over en spiller for hele forløbet.</span></div>
    </section>` : ""}

    <section class="sec">
      <div class="sec-head"><div><h2>Indbyrdes opgør</h2><p class="lede">Rækkens resultater mod kolonnen (V-U-T).</p></div></div>
      <div class="panel"><div class="scroll matrix"><table><thead><tr><th class="l">Hold</th>${ids.map((b) => `<th class="rot">${esc(mgr(b))}</th>`).join("")}</tr></thead><tbody>
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
  if (!sheet.hidden) closeSheet();
  clearInterval(countdownTimer);
  try {
    await VIEWS[view](arg);
  } catch (e) {
    app.innerHTML = `<p class="error">Siden kunne ikke vises: ${esc(e.message)}. Prøv at genindlæse.</p>`;
    console.error(e);
  }
  if (route.ran) { window.scrollTo(0, 0); app.focus({ preventScroll: true }); }
  measureTop();
  enhanceTables(app);
  enhanceMatrices(app);
  buildChips(app);
  addTapHint(app);
  enhance(app);
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
