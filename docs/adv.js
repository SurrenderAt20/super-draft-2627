"use strict";
// Avanceret spillerdata: password-protected player stats for waivers and trades.
// data/adv.enc.json is AES-GCM encrypted; the key comes from the password via PBKDF2,
// so the data cannot be read without it, not even from the public repo.

let ADV = null;          // decrypted data
const ADV_STATE = { cat: "overblik", period: "season", per90: false, pos: "ALL", owner: "all", q: "", minMin: 90, sort: null, dir: -1, shown: 60 };

// ---------------------------------------------------------------- decryption

const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

async function advDecrypt(password) {
  const enc = await getJSON("data/adv.enc.json");
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt: b64(enc.salt), iterations: enc.iter },
    base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(enc.iv) }, key, b64(enc.data));
  const stream = new Blob([plain]).stream().pipeThrough(new DecompressionStream("gzip"));
  return JSON.parse(await new Response(stream).text());
}

const store = {
  get: () => { try { return sessionStorage.getItem("adv-pw"); } catch { return null; } },
  set: (v) => { try { sessionStorage.setItem("adv-pw", v); } catch { /* private mode: ask again next time */ } },
  clear: () => { try { sessionStorage.removeItem("adv-pw"); } catch { /* nothing stored */ } },
};

// ---------------------------------------------------------------- columns

// sum: summed over the period (and shown per 90 when that view is on); fixed: never per 90
const COLDEF = {
  mi: { label: "Min", tip: "Minutter spillet", fixed: true },
  st: { label: "Starter", tip: "Kampe startet", fixed: true },
  apps: { label: "Kampe", tip: "Runder med minutter", fixed: true },
  share: { label: "Min-andel", tip: "Andel af mulige minutter i perioden", fixed: true, pct: true },
  pt: { label: "Point", tip: "FPL-point" },
  g: { label: "Mål" }, a: { label: "Assist" },
  xg: { label: "xG", dec: 2, tip: "Forventede mål" }, xa: { label: "xA", dec: 2, tip: "Forventede assists" },
  xgi: { label: "xGI", dec: 2, tip: "Forventet målinvolvering (xG + xA)" },
  over: { label: "G+A−xGI", dec: 2, tip: "Mål og assists minus xGI. Plus: scorer over det forventede. Minus: uheldig eller ineffektiv.", signed: true },
  sh: { label: "Skud" }, sot: { label: "På mål", tip: "Skud på mål" },
  box: { label: "Felt-berøringer", tip: "Berøringer i modstanderens felt" },
  cc: { label: "Chancer skabt" },
  cs: { label: "CS", tip: "Clean sheets" }, gc: { label: "Mål imod" },
  xgc: { label: "xGC", dec: 2, tip: "Forventede mål imod" },
  dc: { label: "DefCon", tip: "Defensive bidrag (FPL)" },
  tkw: { label: "Tacklinger", tip: "Vundne tacklinger" }, int: { label: "Erobringer", tip: "Interceptions" },
  clr: { label: "Clearinger" }, aer: { label: "Luftdueller", tip: "Vundne luftdueller" },
  crs: { label: "Indlæg", tip: "Præcise indlæg" },
  sv: { label: "Redninger" }, gp: { label: "Mål forhindret", dec: 2, tip: "Mål forhindret ud fra skuddenes kvalitet (xGOT minus mål imod)", signed: true },
  bo: { label: "Bonus" },
};

// m: shown on phones; first column of each category is the default sort
const CATS = {
  overblik: { label: "Overblik", cols: ["pt", "mi", "st", "g", "a", "xgi", "dc", "cs"], m: ["pt", "mi"], pos: "ALL" },
  angreb: { label: "Angreb", cols: ["xgi", "mi", "g", "a", "xg", "xa", "over", "sh", "sot", "box", "cc"], m: ["xgi", "mi"], pos: "ALL" },
  forsvar: { label: "Forsvar", cols: ["dc", "mi", "cs", "gc", "xgc", "tkw", "int", "clr", "aer", "crs", "xgi"], m: ["dc", "mi"], pos: "DEF" },
  maal: { label: "Målmænd", cols: ["pt", "mi", "sv", "gp", "cs", "gc", "xgc", "bo"], m: ["sv", "mi"], pos: "GKP" },
  minutter: { label: "Minutter", cols: ["mi", "share", "st", "apps", "pt"], m: ["mi", "share"], pos: "ALL" },
};

// ---------------------------------------------------------------- aggregation

function periodGws() {
  const all = ADV.gws;
  if (ADV_STATE.period === "season") return all;
  if (ADV_STATE.period.startsWith("last")) return all.slice(-Number(ADV_STATE.period.slice(4)));
  return [Number(ADV_STATE.period)];
}

function aggregate(pid, gws) {
  const C = ADV.cols;
  const sums = Object.fromEntries(C.map((c) => [c, 0]));
  let apps = 0;
  for (const gw of gws) {
    const v = ADV.by_gw[gw]?.[pid];
    if (!v) continue;
    apps += 1;
    C.forEach((c, i) => (sums[c] += v[i]));
  }
  sums.apps = apps;
  sums.share = gws.length ? sums.mi / (90 * gws.length) : 0;
  sums.over = sums.g + sums.a - sums.xgi;
  return sums;
}

function value(row, key) {
  const d = COLDEF[key];
  const v = row.s[key];
  if (ADV_STATE.per90 && !d.fixed) return row.s.mi ? (v * 90) / row.s.mi : 0;
  return v;
}

function fmt(key, v) {
  const d = COLDEF[key];
  if (d.pct) return `${Math.round(v * 100)}%`;
  const dec = ADV_STATE.per90 && !d.fixed ? 2 : d.dec || 0;
  const txt = num(Math.abs(v), dec);
  if (d.signed) return v > 0.004 ? `+${txt}` : v < -0.004 ? `−${txt}` : num(0, dec);
  return v < 0 ? `−${txt}` : txt;
}

// ---------------------------------------------------------------- view

async function viewAvanceret() {
  if (!ADV) {
    const saved = store.get();
    if (saved) {
      try { ADV = await advDecrypt(saved); } catch { store.clear(); }
    }
  }
  if (!ADV) return renderLock();
  renderData();
}

function renderLock(error) {
  app.innerHTML = `
    <h1>Avanceret spillerdata</h1>
    <p class="lede">Minutter, underliggende tal og roller for alle spillere, for hele sæsonen eller runde for runde. Til waivers og byttehandler.</p>
    <form class="panel lock" id="lock-form" autocomplete="on">
      <svg class="lock-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="10" width="14" height="10" rx="2.5"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>
      <label for="adv-pw">Kodeord</label>
      <div class="lock-row">
        <input id="adv-pw" name="password" type="password" autocomplete="current-password" required>
        <button type="submit">Lås op</button>
      </div>
      <p class="lock-err" id="lock-err" aria-live="polite">${error || ""}</p>
      <p class="small muted">Data er krypteret og kan ikke læses uden kodeordet, heller ikke på GitHub.</p>
    </form>`;
  const form = app.querySelector("#lock-form");
  const input = form.querySelector("input");
  input.focus({ preventScroll: true });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button");
    btn.disabled = true;
    btn.textContent = "Låser op…";
    try {
      ADV = await advDecrypt(input.value);
      store.set(input.value);
      renderData();
      enhance(app);
    } catch {
      renderLock("Forkert kodeord. Prøv igen.");
    }
  });
}

function renderData() {
  const gws = ADV.gws;
  const latest = gws[gws.length - 1];
  const periods = [["season", "Hele sæsonen"], ...[3, 5].filter((n) => gws.length > n).map((n) => [`last${n}`, `Seneste ${n} runder`]),
    ...[...gws].reverse().map((g) => [String(g), `Runde ${g}`])];
  const managers = Object.entries(ADV.managers).sort((a, b) => a[1].localeCompare(b[1], "da"));

  app.innerHTML = `
    <div class="adv-head">
      <h1>Avanceret spillerdata</h1>
      <button class="ghost" id="adv-lock" type="button">Lås igen</button>
    </div>
    <p class="lede">Data til og med runde ${latest}. Tryk på en spiller for tallene runde for runde.</p>

    <div class="panel adv-controls">
      <div class="switch" id="adv-cat" role="group" aria-label="Kategori">
        <span class="pill-thumb" aria-hidden="true"></span>
        ${Object.entries(CATS).map(([k, c]) => `<button type="button" data-cat="${k}">${c.label}</button>`).join("")}
      </div>
      <div class="adv-filters">
        <label>Periode
          <select id="adv-period">${periods.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></label>
        <label>Ejer
          <select id="adv-owner"><option value="all">Alle spillere</option><option value="free">Kun ledige</option>${managers.map(([le, n]) => `<option value="${le}">${esc(n)}</option>`).join("")}</select></label>
        <label>Min. minutter
          <input id="adv-min" type="number" min="0" step="30" inputmode="numeric"></label>
        <label class="grow">Søg
          <input id="adv-q" type="search" placeholder="Spiller eller klub"></label>
      </div>
      <div class="adv-filters">
        <div class="seg" id="adv-pos" role="group" aria-label="Position">
          ${["ALL", "GKP", "DEF", "MID", "FWD"].map((p) => `<button type="button" data-pos="${p}">${p === "ALL" ? "Alle" : p}</button>`).join("")}
        </div>
        <div class="seg" id="adv-mode" role="group" aria-label="Visning">
          <button type="button" data-per90="0">Total</button><button type="button" data-per90="1">Per 90</button>
        </div>
        <span class="adv-count muted small" id="adv-count"></span>
      </div>
    </div>

    <div class="panel adv-table"><div class="scroll" id="adv-box"></div></div>
    <div class="adv-more"><button class="ghost" id="adv-more" type="button" hidden>Vis flere</button></div>
    <div class="legend"><span><span class="free">Ledig</span> kan hentes nu</span><span><i class="st-dot d"></i> tvivlsom</span><span><i class="st-dot i"></i> skadet, syg eller udelukket</span></div>`;

  const $ = (s) => app.querySelector(s);
  $("#adv-period").value = ADV_STATE.period;
  $("#adv-owner").value = ADV_STATE.owner;
  $("#adv-min").value = ADV_STATE.minMin;
  $("#adv-q").value = ADV_STATE.q;

  $("#adv-lock").addEventListener("click", () => { ADV = null; store.clear(); renderLock(); });
  $("#adv-cat").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    ADV_STATE.cat = b.dataset.cat;
    ADV_STATE.pos = CATS[b.dataset.cat].pos;
    ADV_STATE.sort = null;
    ADV_STATE.shown = 60;
    drawAdv();
  }));
  $("#adv-pos").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { ADV_STATE.pos = b.dataset.pos; ADV_STATE.shown = 60; drawAdv(); }));
  $("#adv-mode").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    ADV_STATE.per90 = b.dataset.per90 === "1";
    // per 90 over a few minutes misleads: ask for at least three full games' worth over several rounds
    if (ADV_STATE.per90 && !ADV_STATE.period.match(/^\d+$/) && ADV_STATE.minMin < 270) {
      ADV_STATE.minMin = 270;
      $("#adv-min").value = 270;
    }
    drawAdv();
  }));
  $("#adv-period").addEventListener("change", (e) => {
    ADV_STATE.period = e.target.value;
    // a single round needs a lower bar than a whole season
    ADV_STATE.minMin = e.target.value.match(/^\d+$/) ? 1 : 90;
    $("#adv-min").value = ADV_STATE.minMin;
    drawAdv();
  });
  $("#adv-owner").addEventListener("change", (e) => { ADV_STATE.owner = e.target.value; ADV_STATE.shown = 60; drawAdv(); });
  $("#adv-min").addEventListener("input", (e) => { ADV_STATE.minMin = Number(e.target.value) || 0; drawAdv(); });
  $("#adv-q").addEventListener("input", (e) => { ADV_STATE.q = e.target.value; ADV_STATE.shown = 60; drawAdv(); });
  $("#adv-more").addEventListener("click", () => { ADV_STATE.shown += 60; drawAdv(); });
  drawAdv();
  requestAnimationFrame(() => moveThumb($("#adv-cat"), $(`#adv-cat [data-cat="${ADV_STATE.cat}"]`)));
}

function ownerHtml(p) {
  return p.owner ? esc(ADV.managers[p.owner] ?? "?") : '<span class="free">Ledig</span>';
}

function statusDot(p) {
  if (!p.status || p.status === "a") return "";
  const cls = p.status === "d" ? "d" : "i";
  const chance = p.chance != null ? ` (${p.chance}% chance for at spille)` : "";
  return `<i class="st-dot ${cls}" data-tip="${esc(`<b>${esc(p.name)}</b>${esc(p.news || "Ikke tilgængelig")}${chance}`)}" aria-label="${esc(p.news || "Ikke tilgængelig")}"></i>`;
}

function drawAdv() {
  const st = ADV_STATE;
  const cat = CATS[st.cat];
  const sortKey = st.sort || cat.cols[0];
  const gws = periodGws();
  const q = st.q.trim().toLowerCase();

  app.querySelectorAll("#adv-cat button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.cat === st.cat));
  moveThumb(app.querySelector("#adv-cat"), app.querySelector(`#adv-cat [data-cat="${st.cat}"]`));
  app.querySelectorAll("#adv-pos button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.pos === st.pos));
  app.querySelectorAll("#adv-mode button").forEach((b) => b.setAttribute("aria-pressed", (b.dataset.per90 === "1") === st.per90));

  const rows = ADV.players
    .filter((p) => (st.pos === "ALL" || p.pos === st.pos)
      && (st.owner === "all" || (st.owner === "free" ? !p.owner : String(p.owner) === st.owner))
      && (!q || p.name.toLowerCase().includes(q) || p.full.toLowerCase().includes(q) || p.club.toLowerCase() === q))
    .map((p) => ({ p, s: aggregate(p.id, gws) }))
    .filter((r) => r.s.mi >= st.minMin);
  rows.sort((a, b) => st.dir * (value(a, sortKey) - value(b, sortKey)) || b.s.mi - a.s.mi);

  const show = rows.slice(0, st.shown);
  const visibleOnPhone = new Set([...cat.m, sortKey]);
  const cls = (k) => (visibleOnPhone.has(k) ? "" : " opt");
  const head = cat.cols.map((k) => {
    const d = COLDEF[k];
    const on = k === sortKey;
    const label = st.per90 && !d.fixed ? `${d.label}/90` : d.label;
    return `<th class="sortable${on ? " on" : ""}${cls(k)}" aria-sort="${on ? (st.dir < 0 ? "descending" : "ascending") : "none"}"><button type="button" data-sort="${k}"${d.tip ? ` title="${esc(d.tip)}"` : ""}>${label}${on ? (st.dir < 0 ? " ▾" : " ▴") : ""}</button></th>`;
  }).join("");

  app.querySelector("#adv-box").innerHTML = rows.length ? `<table class="advt"><thead><tr><th>#</th><th class="l">Spiller</th><th class="l opt">Ejer</th>${head}</tr></thead><tbody>
    ${show.map((r, i) => `<tr data-pid="${r.p.id}">
      <td class="rank">${i + 1}</td>
      <td class="l"><span class="pl"><b>${esc(r.p.name)}${statusDot(r.p)}</b><span>${esc(r.p.pos)}, ${esc(r.p.club)}<span class="ph-owner">, ${ownerHtml(r.p)}</span></span></span></td>
      <td class="l opt">${ownerHtml(r.p)}</td>
      ${cat.cols.map((k) => `<td class="${k === sortKey ? "sorted" : ""}${cls(k)}">${fmt(k, value(r, k))}</td>`).join("")}
    </tr>`).join("")}</tbody></table>`
    : `<p class="adv-empty">Ingen spillere matcher. Sænk min. minutter eller ryd søgningen.</p>`;

  app.querySelector("#adv-count").textContent = `${rows.length} spillere`;
  const more = app.querySelector("#adv-more");
  more.hidden = rows.length <= st.shown;

  app.querySelectorAll("#adv-box th button").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.sort;
    if (k === sortKey) st.dir = -st.dir; else { st.sort = k; st.dir = -1; }
    drawAdv();
  }));
  app.querySelectorAll("#adv-box tbody tr").forEach((tr) => tr.addEventListener("click", (e) => {
    if (e.target.closest(".st-dot")) return;
    playerSheet(Number(tr.dataset.pid));
  }));
  bindTips(app.querySelector("#adv-box"));
}

// every round for one player, in the current category's columns
function playerSheet(pid) {
  const p = ADV.players.find((x) => x.id === pid);
  const cols = CATS[ADV_STATE.cat].cols.filter((k) => !["share", "apps"].includes(k));
  const C = ADV.cols;
  const cell = (k, s) => fmtPlain(k, s[k]);
  const rows = ADV.gws.map((gw) => {
    const v = ADV.by_gw[gw]?.[pid];
    if (!v) return `<tr class="dnp"><td class="l">R${gw}</td>${cols.map((k) => `<td>${k === "mi" ? "0" : "–"}</td>`).join("")}</tr>`;
    const s = Object.fromEntries(C.map((c, i) => [c, v[i]]));
    s.over = s.g + s.a - s.xgi;
    return `<tr><td class="l">R${gw}</td>${cols.map((k) => `<td>${cell(k, s)}</td>`).join("")}</tr>`;
  }).join("");
  const tot = aggregate(pid, ADV.gws);
  const news = p.status && p.status !== "a" ? `<p class="sheet-news">${esc(p.news || "Ikke tilgængelig")}${p.chance != null ? ` (${p.chance}% chance for at spille)` : ""}</p>` : "";
  openSheet(`<b>${esc(p.full || p.name)}</b>
    <span class="sheet-sub">${esc(p.pos)}, ${esc(p.club)}. Ejer: ${ownerHtml(p)}</span>${news}
    <div class="scroll sheet-table"><table><thead><tr><th class="l">Runde</th>${cols.map((k) => `<th>${COLDEF[k].label}</th>`).join("")}</tr></thead>
    <tbody>${rows}<tr class="sep"><td class="l"><b>I alt</b></td>${cols.map((k) => `<td><b>${fmtPlain(k, tot[k])}</b></td>`).join("")}</tr></tbody></table></div>`);
}

function fmtPlain(k, v) {
  const d = COLDEF[k];
  const txt = num(Math.abs(v), d.dec || 0);
  if (d.signed) return v > 0.004 ? `+${txt}` : v < -0.004 ? `−${txt}` : num(0, d.dec || 0);
  return v < 0 ? `−${txt}` : txt;
}

VIEWS.avanceret = viewAvanceret;
