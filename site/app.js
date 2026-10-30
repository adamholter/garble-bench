"use strict";
// GarbleBench site. Photos and headings shred into slipping strips as you scroll; body text decays
// with the same nested corruption the benchmark uses. Data stays clean.

const $ = (s, el = document) => el.querySelector(s);
const OUT = {
  right: { label: "answered right", c: "var(--o-right)" },
  checked: { label: "right, asked to confirm", c: "var(--o-checked)" },
  wrong: { label: "answered wrong", c: "var(--o-wrong)" },
  guessed: { label: "guessed, no answer", c: "var(--o-guessed)", light: true },
  lost: { label: "lost: asked to rephrase", c: "var(--o-lost)", light: true },
  error: { label: "no reply", c: "var(--o-error)", light: true },
};
const STACK = ["right", "checked", "wrong", "guessed", "lost", "error"];
const MODEL_C = { sol: "var(--sol)", terra: "var(--terra)", astra: "var(--astra)", luna: "var(--luna)", argon: "var(--argon)", flash: "var(--flash)", grok: "var(--grok)" };
const SHORT = { sol: "Sol", terra: "Terra", astra: "Astra", luna: "Luna", argon: "Argon", flash: "Flash", grok: "Grok" };
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---------- seeded corruption (port of build_dataset.py) ----------
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const ROWS = ["1234567890-=", "qwertyuiop[]", "asdfghjkl;'", "zxcvbnm,./"];
const POS = {};
ROWS.forEach((row, r) => [...row].forEach((c, i) => (POS[c] = [r, i])));
const STRAY = "abcdefghijklmnopqrstuvwxyz;',./[]\\`~-=0123456789";
const PUNCT = new Set("?,.'!;:");
function neighbor(c, R) {
  const lo = c.toLowerCase();
  if (!POS[lo]) return "etaoinshrdlu"[Math.floor(R() * 12)];
  const [r, i] = POS[lo], opts = [];
  for (let rr = r - 1; rr <= r + 1; rr++)
    for (let ii = i - 1; ii <= i + 1; ii++)
      if (rr >= 0 && rr < 4 && ii >= 0 && ii < ROWS[rr].length && !(rr === r && ii === i)) opts.push(ROWS[rr][ii]);
  const o = opts[Math.floor(R() * opts.length)];
  return c === c.toUpperCase() && c !== lo ? o.toUpperCase() : o;
}
function plan(text, seed) {
  const R = rng(seed);
  return [...text].map((c) => {
    const x = R();
    return { u: R(), uc: R(), op: x < 0.36 ? "typo" : x < 0.62 ? "drop" : x < 0.84 ? "stray" : "swap", nb: neighbor(c, R), st: STRAY[Math.floor(R() * STRAY.length)] };
  });
}
function corrupt(text, p, rate) {
  const t = [...text], out = [];
  for (let i = 0; i < t.length; i++) {
    let c = t[i];
    const d = p[i];
    if (c !== c.toLowerCase() && d.uc < Math.min(1, rate * 2)) c = c.toLowerCase();
    if (PUNCT.has(c)) { if (d.u >= Math.min(1, rate * 2.5)) out.push(c); continue; }
    if (d.u >= rate) { out.push(c); continue; }
    let op = d.op;
    if (c === " " && (op === "typo" || op === "swap")) op = "drop";
    if (op === "typo") out.push(d.nb);
    else if (op === "stray") out.push(c + d.st);
    else if (op === "swap" && i + 1 < t.length && !PUNCT.has(t[i + 1])) { out.push(t[i + 1] + c); i++; }
    else if (op === "swap") out.push(c);
  }
  return out.join("");
}
function hash(s) { let h = 2166136261; for (const c of String(s)) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0; }

// ---------- scroll state ----------
let held = false, G = 0;
const holdBtn = $("#hold");
holdBtn.onclick = () => {
  held = !held;
  holdBtn.setAttribute("aria-pressed", String(held));
  holdBtn.textContent = held ? "Release" : "Hold";
  tick(true);
};
const level = () => (held ? 0 : G);

// ---------- decaying prose ----------
const decays = [];
function initDecay(el) {
  const nodes = [];
  const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = w.nextNode())) if (node.nodeValue.trim()) nodes.push({ node, orig: node.nodeValue, p: plan(node.nodeValue, hash(node.nodeValue)) });
  const d = { el, nodes, max: parseFloat(el.dataset.max || 0.2), rate: -1, hover: false };
  el.setAttribute("aria-label", nodes.map((x) => x.orig).join(""));
  el.addEventListener("mouseenter", () => { d.hover = true; applyDecay(d, 0); });
  el.addEventListener("mouseleave", () => { d.hover = false; applyDecay(d, decayTarget(d)); });
  decays.push(d);
}
function decayTarget(d) { return d.hover ? 0 : Math.round(d.max * Math.min(1, level() * 1.3) * 100) / 100; }
function applyDecay(d, rate) {
  if (rate === d.rate) return;
  d.rate = rate;
  for (const x of d.nodes) x.node.nodeValue = rate ? corrupt(x.orig, x.p, rate) : x.orig;
}

// ---------- the shredder ----------
// The original element stays in the layout (hidden once shredding starts); strips are copies of it,
// each clipped to one band and slid sideways by a seeded amount.
const shreds = [];
function initShred(el, kind) {
  let orig;
  if (kind === "img") orig = el.querySelector("img");
  else {
    orig = document.createElement("span");
    while (el.firstChild) orig.appendChild(el.firstChild);
    el.appendChild(orig);
    el.setAttribute("aria-label", orig.textContent);
  }
  orig.classList.add("orig");
  el.classList.add("shred");
  const layer = document.createElement("div");
  layer.className = "slices";
  layer.setAttribute("aria-hidden", "true");
  el.appendChild(layer);
  const s = { el, orig, layer, kind, slices: [], seed: hash(orig.textContent + (orig.src || "")), built: false, k: -1 };
  shreds.push(s);
  if (kind === "img" && !orig.complete) orig.addEventListener("load", () => { s.built = false; tick(true); }, { once: true });
}
function buildShred(s) {
  const h = s.kind === "img" ? s.orig.offsetHeight : s.el.offsetHeight;
  if (!h) return;
  s.layer.innerHTML = "";
  s.slices = [];
  const R = rng(s.seed);
  const n = s.kind === "img" ? Math.max(8, Math.round(h / 34)) : Math.max(3, Math.round(h / 22));
  // uneven bands, like a shredder catching the sheet at an angle
  const cuts = [0];
  for (let i = 1; i < n; i++) cuts.push((i + (R() - 0.5) * 0.7) / n);
  cuts.push(1);
  const top0 = s.kind === "img" ? s.orig.offsetTop : 0;
  for (let i = 0; i < n; i++) {
    const t = cuts[i] * h, b = cuts[i + 1] * h;
    const sl = document.createElement("div");
    sl.className = "slice";
    sl.style.top = top0 + t + "px";
    sl.style.height = b - t + 0.6 + "px";
    const copy = s.orig.cloneNode(true);
    copy.classList.remove("orig");
    copy.classList.add("copy");
    copy.removeAttribute("alt");
    copy.style.top = -t + "px";
    if (s.kind !== "img") { copy.style.display = "block"; copy.style.width = s.orig.offsetWidth + "px"; }
    sl.appendChild(copy);
    const bar = document.createElement("i");
    bar.className = "redbar";
    sl.appendChild(bar);
    s.layer.appendChild(sl);
    s.slices.push({ el: sl, bar, dir: R() * 2 - 1, gate: R(), bx: R(), bw: 0.08 + R() * 0.3 });
  }
  s.built = true;
  s.k = -1;
}
function applyShred(s, k) {
  if (!s.built) buildShred(s);
  if (!s.built) return;
  k = Math.round(k * 200) / 200;
  if (k === s.k) return;
  s.k = k;
  const on = k > 0.004;
  s.el.classList.toggle("on", on);
  s.layer.style.display = on ? "" : "none";
  if (!on) return;
  const w = s.el.offsetWidth;
  const amp = s.kind === "img" ? Math.min(90, w * 0.09) : Math.min(46, w * 0.05);
  for (const sl of s.slices) {
    // strips join in one by one as k rises
    const live = Math.max(0, (k - sl.gate * 0.55) / (1 - sl.gate * 0.55));
    sl.el.style.transform = live ? `translateX(${(sl.dir * amp * live).toFixed(1)}px)` : "";
    const showBar = k > 0.25 && sl.gate < (k - 0.25) * 0.9;
    sl.bar.style.display = showBar ? "" : "none";
    if (showBar) { sl.bar.style.left = sl.bx * 82 + "%"; sl.bar.style.width = sl.bw * Math.min(1, k * 1.4) * 100 + "%"; }
  }
}
function shredLevel(s) {
  // deeper on the page = more broken
  const docTop = s.el.getBoundingClientRect().top + scrollY;
  const depth = Math.min(1, docTop / Math.max(1, document.documentElement.scrollHeight - innerHeight));
  return Math.min(1, level() * (0.55 + depth * 0.9));
}

// ---------- small slips on data rows ----------
function slipRows() {
  const k = reduced ? 0 : level();
  document.querySelectorAll("#board tbody tr, .card, .multiples figure").forEach((row, j) => {
    const jr = (hash("r" + j) % 1000) / 1000 - 0.5;
    row.style.transform = k > 0.3 ? `translateX(${(jr * (k - 0.3) * 26).toFixed(1)}px)` : "";
  });
}

// ---------- readout: three rotor windows step as you scroll ----------
const ABC = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
function readout() {
  const k = level();
  const w = $("#windows").children;
  const steps = Math.floor(k * 26 * 26 * 3);
  [Math.floor(steps / 676) % 26, Math.floor(steps / 26) % 26, steps % 26].forEach((v, i) => {
    w[i].textContent = ABC[v];
    w[i].classList.toggle("hot", k > 0 && i === 2);
  });
  $("#ro-pct").textContent = Math.round(k * 100) + "%";
}

let lastG = -1;
function tick(force) {
  const max = document.documentElement.scrollHeight - innerHeight;
  G = max > 0 ? Math.min(1, Math.max(0, scrollY / max)) : 0;
  $(".top").classList.toggle("scrolled", scrollY > 10);
  if (!force && Math.abs(G - lastG) < 0.003) return;
  lastG = G;
  for (const d of decays) if (!d.hover) applyDecay(d, decayTarget(d));
  if (!reduced) {
    for (const s of shreds) applyShred(s, shredLevel(s));
    slipRows();
  }
  readout();
}
let raf = 0;
addEventListener("scroll", () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; tick(); }); }, { passive: true });
let rz = 0;
addEventListener("resize", () => {
  clearTimeout(rz);
  rz = setTimeout(() => { shreds.forEach((s) => (s.built = false)); tick(true); }, 150);
});

// ---------- tooltip ----------
const tip = $("#tip");
function moveTip(e) {
  tip.style.left = Math.min(innerWidth - tip.offsetWidth - 10, e.clientX + 14) + "px";
  tip.style.top = Math.max(8, e.clientY - tip.offsetHeight - 12) + "px";
}
function bindTips(root) {
  root.querySelectorAll("[data-tip]").forEach((el) => {
    el.addEventListener("mouseenter", (e) => { tip.innerHTML = el.dataset.tip; tip.style.opacity = 1; moveTip(e); });
    el.addEventListener("mousemove", moveTip);
    el.addEventListener("mouseleave", () => (tip.style.opacity = 0));
  });
}

// ---------- helpers ----------
const pct = (v) => (v == null ? "·" : Math.round(v * 100) + "%");
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
// replies come back as markdown; render bold, italics and inline code, nothing else
const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>").replace(/`([^`\n]+)`/g, "<code>$1</code>");
function chips(el, opts, val, onPick) {
  el.innerHTML = opts.map(([v, label]) => `<button type="button" data-v="${esc(v)}" aria-pressed="${v === val}">${esc(label)}</button>`).join("");
  el.onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    el.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    onPick(b.dataset.v);
  };
}
function spreadLabels(items, gap, lo, hi) {
  items.sort((a, b) => a.y - b.y);
  for (let i = 1; i < items.length; i++) if (items[i].y - items[i - 1].y < gap) items[i].y = items[i - 1].y + gap;
  const over = items.length ? items[items.length - 1].y - hi : 0;
  if (over > 0) items.forEach((it) => (it.y -= over));
  items.forEach((it) => (it.y = Math.max(lo, it.y)));
  return items;
}
function diffMark(orig, garbled) {
  // characters kept from the original stay plain, everything else is marked
  const a = [...orig], b = [...garbled], n = a.length, m = b.length;
  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  let i = 0, j = 0, out = "";
  while (j < m) {
    if (i < n && a[i] === b[j]) { out += esc(b[j]); i++; j++; }
    else if (i < n && dp[i + 1][j] >= dp[i][j + 1]) i++;
    else { out += `<span class="x">${esc(b[j])}</span>`; j++; }
  }
  return out;
}
function axes(W, H, m, xs, ys, xfmt, yfmt) {
  let s = `<g class="axis">`;
  for (const y of ys.ticks) s += `<line x1="${m.l}" x2="${W - m.r}" y1="${ys.f(y)}" y2="${ys.f(y)}" ${y === ys.ticks[0] ? 'class="base"' : 'stroke-dasharray="2 4"'}/><text x="${m.l - 8}" y="${ys.f(y) + 4}" text-anchor="end">${yfmt(y)}</text>`;
  for (const x of xs.ticks) s += `<text x="${xs.f(x)}" y="${H - m.b + 20}" text-anchor="middle">${xfmt(x)}</text>`;
  return s + "</g>";
}

// ---------- data + render ----------
let DATA = null;
const S = { boardModel: "all", boardEffort: "all", sort: "tolerance", dir: -1, curveEffort: null, phaseEffort: null, q: "capital", level: 6, specEffort: "all" };
const complete = () => DATA.configs.filter((c) => c.complete);
const effortsWith = (list) => DATA.efforts.filter((e) => list.some((c) => c.effort === e));

function renderStats() {
  const done = complete();
  const graded = DATA.configs.reduce((a, c) => a + c.graded, 0);
  $("#stats").innerHTML = [
    [new Set(done.map((c) => c.model)).size, "Models"],
    [done.length, "Model × effort runs"],
    [DATA.questions.length * DATA.rates.length, "Garbled prompts"],
    [graded.toLocaleString(), "Graded replies"],
  ].map(([v, l]) => `<div><dt>${v}</dt><dd>${l}</dd></div>`).join("");
}

function renderStrip() {
  const q = DATA.questions.find((x) => x.id === "capital") || DATA.questions[0];
  $("#strip-q").textContent = q.question;
  $("#strip").innerHTML = q.prompts.map((p, i) => `<div><b>${Math.round(DATA.rates[i] * 100)}%</b>${diffMark(q.question, p) || "&nbsp;"}</div>`).join("");
}

function phaseStrip(c) {
  return `<div class="phase-strip">${c.phases.map((ph, i) => {
    const tot = Object.values(ph).reduce((a, b) => a + b, 0) || 1;
    const title = `${Math.round(DATA.rates[i] * 100)}% corrupted<br>` + STACK.filter((k) => ph[k]).map((k) => `${ph[k]} ${OUT[k].label}`).join("<br>");
    return `<span data-tip="${esc(title)}">${STACK.filter((k) => ph[k]).map((k) => `<i style="height:${(ph[k] / tot) * 100}%;background:${OUT[k].c}"></i>`).join("")}</span>`;
  }).join("")}</div>`;
}

function renderBoard() {
  const all = complete();
  const list = all.filter((c) => (S.boardModel === "all" || c.model === S.boardModel) && (S.boardEffort === "all" || c.effort === S.boardEffort));
  const keyf = { tolerance: (c) => c.tolerance, breaks: (c) => c.breaks, secs: (c) => c.secs, tokens: (c) => c.tokens, model: (c) => c.name, effort: (c) => DATA.efforts.indexOf(c.effort) }[S.sort];
  list.sort((a, b) => { const x = keyf(a), y = keyf(b); return (x < y ? -1 : x > y ? 1 : 0) * S.dir || b.tolerance - a.tolerance; });
  const top = Math.max(...all.map((c) => c.tolerance), 1);
  const th = (k, label, cls = "") => `<th data-k="${k}" class="${cls}" ${S.sort === k ? `aria-sort="${S.dir < 0 ? "descending" : "ascending"}"` : ""}>${label}</th>`;
  $("#board").innerHTML = `<thead><tr><th>#</th>${th("model", "Model")}${th("effort", "Effort")}${th("tolerance", "Tolerance")}${th("breaks", "Breaks at", "r")}<th>Phases, 0 → 100%</th>${th("secs", "Avg s", "r")}${th("tokens", "Out tok", "r")}</tr></thead><tbody>` +
    (list.length ? list.map((c, i) => `<tr><td class="rank">${String(i + 1).padStart(2, "0")}</td><td class="model"><i style="background:${MODEL_C[c.model]}"></i>${esc(c.name)}</td><td class="effort">${c.effort}</td>` +
      `<td class="tol">${c.tolerance.toFixed(1)}<span class="bar"><i style="width:${(c.tolerance / top) * 100}%"></i></span></td>` +
      `<td class="dim r">${pct(c.breaks)}</td><td>${phaseStrip(c)}</td><td class="dim r">${c.secs}</td><td class="dim r">${c.tokens}</td></tr>`).join("")
      : `<tr><td colspan="8" class="empty">No finished runs match.</td></tr>`) + "</tbody>";
  $("#board thead").onclick = (e) => {
    const k = e.target.closest("th")?.dataset.k;
    if (!k) return;
    S.dir = S.sort === k ? -S.dir : k === "model" || k === "effort" ? 1 : -1;
    S.sort = k;
    renderBoard();
  };
  bindTips($("#board"));
  slipRows();
  const pend = DATA.configs.filter((c) => !c.complete);
  $("#pending").innerHTML = pend.length
    ? `<div>Still running (${pend.length}). Each appears once every prompt is answered and graded:</div>` +
      pend.map((c) => `<span style="display:inline-block;margin-right:18px">${esc(c.name)} ${c.effort}<span class="pb"><i style="width:${(c.graded / c.total) * 100}%"></i></span>${c.graded}/${c.total}</span>`).join("")
    : "";
}

function renderBoardFilter() {
  $("#board-filter").innerHTML = '<div class="chips" id="bf-m"></div><div class="chips" id="bf-e"></div>';
  const models = Object.keys(SHORT).filter((m) => DATA.configs.some((c) => c.model === m));
  chips($("#bf-m"), [["all", "All models"], ...models.map((m) => [m, SHORT[m]])], S.boardModel, (v) => { S.boardModel = v; renderBoard(); });
  chips($("#bf-e"), [["all", "All efforts"], ...DATA.efforts.map((e) => [e, e])], S.boardEffort, (v) => { S.boardEffort = v; renderBoard(); });
  $("#legend").innerHTML = STACK.map((k) => `<span style="--c:${OUT[k].c}">${OUT[k].label}</span>`).join("");
}

function renderCurve() {
  const list = complete(), effs = effortsWith(list), el = $("#curve");
  if (!effs.length) { el.innerHTML = `<div class="empty">Waiting on the first finished run.</div>`; return; }
  if (!effs.includes(S.curveEffort)) S.curveEffort = effs.includes("high") ? "high" : effs[0];
  chips($("#curve-effort"), effs.map((e) => [e, e]), S.curveEffort, (v) => { S.curveEffort = v; renderCurve(); });
  const W = 1000, H = 420, m = { l: 48, r: 120, t: 12, b: 38 };
  const X = (r) => m.l + r * (W - m.l - m.r), Y = (a) => m.t + (1 - a) * (H - m.t - m.b);
  let s = axes(W, H, m, { ticks: [0, 0.2, 0.4, 0.6, 0.8, 1], f: X }, { ticks: [0, 0.25, 0.5, 0.75, 1], f: Y }, (x) => `${Math.round(x * 100)}%`, (y) => `${y * 100}%`);
  s += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(0.5)}" y2="${Y(0.5)}" stroke="var(--red)" stroke-dasharray="5 5" opacity=".7"/><text x="${W - m.r - 4}" y="${Y(0.5) - 7}" text-anchor="end" style="font:11.5px var(--mono);fill:var(--red)">half right</text>`;
  const rows = list.filter((c) => c.effort === S.curveEffort);
  for (const c of rows) {
    const pts = c.acc.map((a, i) => [X(DATA.rates[i]), Y(a)]);
    s += `<g class="series"><path d="M${pts.map((p) => p.join(",")).join("L")}" stroke="${MODEL_C[c.model]}"/>` +
      pts.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="4.5" fill="${MODEL_C[c.model]}" data-tip="${esc(`${c.name} ${c.effort}<br>${Math.round(DATA.rates[i] * 100)}% corrupted: ${pct(c.acc[i])} right`)}"/>`).join("") +
      `<line x1="${X(c.breaks)}" x2="${X(c.breaks)}" y1="${Y(0.5) - 7}" y2="${Y(0.5) + 7}" stroke="${MODEL_C[c.model]}" stroke-width="2.5"/></g>`;
  }
  // a ranked key down the right margin: where each line breaks
  s += `<text x="${W - m.r + 16}" y="${m.t + 4}" style="font:10.5px var(--mono);fill:var(--ink-3)">BREAKS AT</text>`;
  [...rows].sort((a, b) => b.breaks - a.breaks).forEach((c, i) => {
    s += `<g class="series"><text x="${W - m.r + 16}" y="${m.t + 26 + i * 20}" fill="${MODEL_C[c.model]}">${SHORT[c.model]} ${pct(c.breaks)}</text></g>`;
  });
  s += `<text x="${(W - m.r + m.l) / 2}" y="${H - 2}" text-anchor="middle" style="font:11.5px var(--mono);fill:var(--ink-3)">share of characters corrupted</text>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Accuracy by corruption rate">${s}</svg>`;
  bindTips(el);
}

function renderPhases() {
  const list = complete(), effs = effortsWith(list), el = $("#phase-charts");
  if (!effs.length) { el.innerHTML = `<div class="empty">Waiting on the first finished run.</div>`; return; }
  if (!effs.includes(S.phaseEffort)) S.phaseEffort = effs.includes("high") ? "high" : effs[0];
  chips($("#phase-effort"), effs.map((e) => [e, e]), S.phaseEffort, (v) => { S.phaseEffort = v; renderPhases(); });
  const W = 420, H = 220, m = { l: 36, r: 6, t: 6, b: 28 };
  const X = (r) => m.l + r * (W - m.l - m.r), Y = (a) => m.t + (1 - a) * (H - m.t - m.b);
  el.innerHTML = list.filter((c) => c.effort === S.phaseEffort).map((c) => {
    const tots = c.phases.map((ph) => Object.values(ph).reduce((a, b) => a + b, 0) || 1);
    let base = c.phases.map(() => 0), s = "";
    for (const k of STACK) {
      const top = c.phases.map((ph, i) => base[i] + (ph[k] || 0) / tots[i]);
      if (top.some((v, i) => v > base[i])) {
        const up = top.map((v, i) => `${X(DATA.rates[i])},${Y(v)}`), dn = base.map((v, i) => `${X(DATA.rates[i])},${Y(v)}`).reverse();
        s += `<path d="M${up.join("L")}L${dn.join("L")}Z" fill="${OUT[k].c}" data-tip="${esc(OUT[k].label)}"/>`;
      }
      base = top;
    }
    s += axes(W, H, m, { ticks: [0, 0.5, 1], f: X }, { ticks: [0, 0.5, 1], f: Y }, (x) => `${x * 100}%`, (y) => `${y * 100}%`);
    return `<figure><figcaption>${esc(c.name)}<small>${c.effort} · ${c.tolerance.toFixed(1)}</small></figcaption><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(c.name)} behaviour by corruption rate">${s}</svg></figure>`;
  }).join("") || `<div class="empty">No finished runs at this effort yet.</div>`;
  bindTips(el);
  slipRows();
}

function renderEffort() {
  const list = complete(), effs = effortsWith(list), el = $("#effort-chart");
  if (!effs.length) { el.innerHTML = `<div class="empty">Waiting on the first finished run.</div>`; return; }
  const W = 1000, H = 360, m = { l: 48, r: 100, t: 12, b: 34 };
  const vals = list.map((c) => c.tolerance);
  const lo = Math.max(0, Math.floor((Math.min(...vals) - 3) / 5) * 5), hi = Math.min(100, Math.ceil((Math.max(...vals) + 2) / 5) * 5);
  const X = (i) => m.l + 20 + (effs.length === 1 ? 0.5 : i / (effs.length - 1)) * (W - m.l - m.r - 40);
  const Y = (v) => m.t + (1 - (v - lo) / (hi - lo || 1)) * (H - m.t - m.b);
  const ticks = [];
  for (let v = lo; v <= hi + 0.01; v += (hi - lo) / 4) ticks.push(Math.round(v));
  let s = axes(W, H, m, { ticks: effs.map((_, i) => i), f: X }, { ticks, f: Y }, (i) => effs[i], (v) => v);
  const labels = [];
  for (const mo of Object.keys(SHORT)) {
    const pts = effs.map((e, i) => { const c = list.find((c) => c.model === mo && c.effort === e); return c ? [X(i), Y(c.tolerance), c] : null; }).filter(Boolean);
    if (!pts.length) continue;
    s += `<g class="series"><path d="M${pts.map((p) => p[0] + "," + p[1]).join("L")}" stroke="${MODEL_C[mo]}"/>` +
      pts.map((p) => `<circle cx="${p[0]}" cy="${p[1]}" r="5" fill="${MODEL_C[mo]}" data-tip="${esc(`${p[2].name} ${p[2].effort}<br>tolerance ${p[2].tolerance.toFixed(1)} · breaks at ${pct(p[2].breaks)}<br>${p[2].secs}s · ${p[2].tokens} output tokens avg`)}"/>`).join("") + "</g>";
    const last = pts[pts.length - 1];
    labels.push({ y: last[1], x: last[0], mo });
  }
  for (const l of spreadLabels(labels, 17, m.t, H - m.b)) s += `<g class="series"><text x="${l.x + 12}" y="${l.y + 4}" fill="${MODEL_C[l.mo]}">${SHORT[l.mo]}</text></g>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Tolerance by reasoning effort">${s}</svg>`;
  bindTips(el);
}

// ---------- proofs: rotor control ----------
function setLevel(v) {
  S.level = Math.max(0, Math.min(DATA.rates.length - 1, v));
  renderSpecBody();
}
function renderSpec() {
  chips($("#spec-q"), DATA.questions.map((q) => [q.id, q.question.length > 34 ? q.question.slice(0, 32) + "…" : q.question]), S.q, (v) => { S.q = v; renderSpecBody(); });
  chips($("#spec-effort"), [["all", "All efforts"], ...effortsWith(DATA.configs).map((e) => [e, e])], S.specEffort, (v) => { S.specEffort = v; renderSpecBody(); });
  const rot = $("#rotor");
  rot.innerHTML = DATA.rates.map((r) => `<span>${Math.round(r * 100)}</span>`).join("");
  const pick = (e) => {
    const r = rot.getBoundingClientRect();
    setLevel(Math.floor(((e.clientX - r.left) / r.width) * DATA.rates.length));
  };
  rot.onpointerdown = (e) => { rot.setPointerCapture(e.pointerId); pick(e); rot.onpointermove = pick; };
  rot.onpointerup = () => (rot.onpointermove = null);
  rot.onkeydown = (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowUp") { setLevel(S.level + 1); e.preventDefault(); }
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") { setLevel(S.level - 1); e.preventDefault(); }
  };
  $("#rot-up").onclick = () => setLevel(S.level + 1);
  $("#rot-down").onclick = () => setLevel(S.level - 1);
  renderSpecBody();
}
function renderSpecBody() {
  const q = DATA.questions.find((x) => x.id === S.q);
  const iid = `${q.id}-L${String(S.level).padStart(2, "0")}`;
  const rot = $("#rotor");
  [...rot.children].forEach((c, i) => c.classList.toggle("on", i === S.level));
  rot.setAttribute("aria-valuenow", S.level);
  rot.setAttribute("aria-valuetext", Math.round(DATA.rates[S.level] * 100) + "% corrupted");
  $("#spec-rate").textContent = Math.round(DATA.rates[S.level] * 100) + "%";
  $("#spec-prompt").innerHTML = diffMark(q.question, q.prompts[S.level]) || "&nbsp;";
  $("#spec-orig").innerHTML = `Original: "${esc(q.question)}" · accepted answer: <b>${esc(q.answer)}</b>`;
  const cfgs = DATA.configs.filter((c) => (S.specEffort === "all" || c.effort === S.specEffort) && c.results[iid]);
  $("#cards").innerHTML = cfgs.length ? cfgs.map((c) => {
    const r = c.results[iid], o = OUT[r.o];
    return `<article class="card"><h4><span><i style="background:${MODEL_C[c.model]}"></i>${esc(c.name)}</span><small>${c.effort}</small></h4>` +
      `<span class="tag ${o.light ? "light" : ""}" style="--c:${o.c}">${o.label}</span><p>${md(r.r || "(no reply)")}</p>` +
      `<div class="meta">${r.s ?? "·"}s · ${r.t} tok${r.n ? ` · judge: ${esc(r.n)}` : ""}</div></article>`;
  }).join("") : `<div class="empty">No graded replies for this one yet.</div>`;
  slipRows();
}

function renderAll() {
  renderStats();
  renderStrip();
  renderBoardFilter();
  renderBoard();
  renderCurve();
  renderPhases();
  renderEffort();
  renderSpec();
}

async function load() {
  try {
    DATA = await (await fetch("data.json?" + Date.now())).json();
  } catch (e) {
    $("#stats").textContent = "Could not load data.json";
    return;
  }
  renderAll();
  shreds.forEach((s) => (s.built = false));
  tick(true);
  if (!DATA.configs.length || DATA.configs.some((c) => !c.complete)) setTimeout(load, 60000);
}

document.querySelectorAll(".decay").forEach(initDecay);
document.querySelectorAll("h1.shred-text, h2.shred-text").forEach((el) => initShred(el, "text"));
document.querySelectorAll(".hero-fig, .materials figure").forEach((el) => initShred(el, "img"));
tick(true);
load();
