"use strict";

// Categorical palette (10 distinct hues that work on light + dark).
const PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed",
                 "#0891b2", "#db2777", "#84cc16", "#92400e", "#64748b",
                 "#0d9488", "#9333ea"];

const state = {
  status: null, eventId: null, data: null,
  market: null, outcome: null, mode: "odds", hidden: new Set(),
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
}

function fmtTime(iso) {
  return new Date(iso).toLocaleString([], { weekday: "short", day: "2-digit", month: "short",
                                             hour: "2-digit", minute: "2-digit" });
}
function fmtUntil(iso) {
  const mins = Math.round((new Date(iso) - Date.now()) / 60000);
  if (mins <= 0) return "started";
  if (mins < 60) return `in ${mins}m`;
  const h = Math.floor(mins / 60);
  return h < 48 ? `in ${h}h ${mins % 60}m` : `in ${Math.floor(h / 24)}d ${h % 24}h`;
}

// ---------------------------------------------------------------- status
async function loadStatus() {
  const s = state.status = await api("/api/status");
  $("mode-pill").textContent = s.demo ? "DEMO" : "LIVE";
  $("mode-pill").className = "pill " + (s.demo ? "demo" : "live");
  $("demo-banner").classList.toggle("hidden", !s.demo);
  const stat = (v, l) => `<div class="stat"><b>${esc(v)}</b><span>${esc(l)}</span></div>`;
  $("credits").innerHTML =
    stat(s.remaining, "credits left") +
    stat(`${s.spent_today} / ${s.daily_allowance}`, "used today / today's share") +
    stat(s.cost_per_poll, "credits per poll") +
    stat(new Date(s.cycle_resets).toLocaleDateString(), "quota resets (est.)");

  const sel = $("sport-select");
  if (!sel.options.length) {
    sel.innerHTML = s.sports.map((k) => `<option value="${esc(k)}">${esc(k)}</option>`).join("");
  }
  $("btn-load-fixtures").disabled = s.demo;

  $("schedule").innerHTML = s.schedule.length ? s.schedule.map((g) => `
    <div class="sched">
      <div class="top"><b>${esc(g.sport_key)}</b>
        <button class="btn small" data-poll="${esc(g.sport_key)}" ${s.demo ? "disabled" : ""}>Poll now</button></div>
      <div class="dim">${g.tracked_events} match(es) · next kickoff ${g.minutes_to_next_kickoff} min ·
        every ${g.poll_every_minutes} min</div>
      <div class="dim">next poll ${fmtTime(g.next_poll)}</div>
      ${g.last_skip_reason ? `<div class="warn">skipped: ${esc(g.last_skip_reason)}</div>` : ""}
    </div>`).join("") : `<p class="hint">Nothing tracked yet.</p>`;
}

async function loadCalls() {
  const calls = await api("/api/calls?limit=40");
  $("call-log").innerHTML = calls.length ? calls.map((c) =>
    `<div class="${c.ok ? "" : "bad"}">${esc(c.at.slice(5, 16).replace("T", " "))} ${esc(c.endpoint)}
     ${esc(c.sport_key || "")} cost=${c.cost ?? "?"} left=${c.remaining ?? "?"} ${esc(c.note || "")}</div>`).join("")
    : "No API calls yet.";
}

// --------------------------------------------------------------- events
async function loadTracked() {
  const evs = await api("/api/events?tracked=true");
  $("tracked-list").innerHTML = evs.length ? evs.map((e) => `
    <li class="clickable ${e.id === state.eventId ? "active" : ""}" data-event="${esc(e.id)}">
      <div class="grow"><div>${esc(e.home_team)} v ${esc(e.away_team)}</div>
        <div class="meta">${esc(e.sport_title || e.sport_key)} · ${fmtUntil(e.commence_time)} · ${e.snapshots} polls</div></div>
      <button class="btn small" data-untrack="${esc(e.id)}" title="Stop tracking">✕</button>
    </li>`).join("") : `<li class="dim">None yet. Load fixtures below and tick some.</li>`;
}

async function loadFixtures(fetchFresh) {
  const sport = $("sport-select").value;
  const list = $("fixture-list");
  try {
    const evs = fetchFresh
      ? await api(`/api/fixtures/${encodeURIComponent(sport)}`, { method: "POST" })
      : await api(`/api/events?sport_key=${encodeURIComponent(sport)}`);
    const upcoming = evs.filter((e) => new Date(e.commence_time) > Date.now());
    list.innerHTML = upcoming.length ? upcoming.map((e) => `
      <li><input type="checkbox" data-track="${esc(e.id)}" ${e.tracked ? "checked" : ""} aria-label="track" />
        <div class="grow"><div>${esc(e.home_team)} v ${esc(e.away_team)}</div>
        <div class="meta">${fmtTime(e.commence_time)}</div></div></li>`).join("")
      : `<li class="dim">${fetchFresh ? "No upcoming fixtures." : "Click Load fixtures."}</li>`;
  } catch (err) {
    list.innerHTML = `<li class="warn">${esc(err.message)}</li>`;
  }
  refreshAll();
}

// --------------------------------------------------------------- match view
async function openEvent(id) {
  if (state.eventId !== id) { state.hidden.clear(); state.outcome = null; state.market = null; }
  state.eventId = id;
  const q = state.market ? `?market=${encodeURIComponent(state.market)}` : "";
  const d = state.data = await api(`/api/events/${encodeURIComponent(id)}/series${q}`);
  state.market = d.market;
  if (!d.outcomes.includes(state.outcome)) state.outcome = d.outcomes[0] || null;

  $("empty").classList.add("hidden");
  $("match-view").classList.remove("hidden");
  $("match-title").textContent = `${d.event.home_team} v ${d.event.away_team}`;
  $("match-sub").textContent = `${d.event.sport_title || d.event.sport_key} · kickoff ${fmtTime(d.event.commence_time)} (${fmtUntil(d.event.commence_time)}) · ${d.polls.length} polls`;
  $("market-select").innerHTML = (d.markets.length ? d.markets : [d.market])
    .map((m) => `<option ${m === d.market ? "selected" : ""}>${esc(m)}</option>`).join("");
  $("outcome-tabs").innerHTML = d.outcomes.map((o) =>
    `<button data-outcome="${esc(o)}" class="${o === state.outcome ? "on" : ""}">${esc(o)}</button>`).join("");
  render();
  loadTracked();
}

function colorFor(key) {
  const keys = state.data.bookmakers.map((b) => b.key);
  return PALETTE[keys.indexOf(key) % PALETTE.length];
}

function render() {
  const d = state.data;
  if (!d) return;
  const per = d.series[state.outcome] || {};
  const val = (p) => (state.mode === "prob" ? 100 / p : p);
  const series = d.bookmakers.filter((b) => per[b.key]).map((b) => ({
    ...b, color: colorFor(b.key),
    pts: per[b.key].map(([t, p]) => [Date.parse(t), val(p)]),
  }));

  $("legend").innerHTML = series.map((s) => `
    <button data-bm="${esc(s.key)}" class="${state.hidden.has(s.key) ? "off" : ""}">
      <span class="sw ${s.exchange ? "dash" : ""}" style="border-color:${s.color}"></span>${esc(s.title)}</button>`).join("");

  drawChart(series.filter((s) => !state.hidden.has(s.key)), d.polls.map(Date.parse));
  renderTable();
}

function renderTable() {
  const rows = state.data.summary.filter((r) => r.outcome === state.outcome)
    .sort((a, b) => a.change_pct - b.change_pct);
  $("move-table").querySelector("tbody").innerHTML = rows.map((r) => {
    const cls = r.change_pct < 0 ? "up" : r.change_pct > 0 ? "down" : "";
    const word = r.change_pct < 0 ? "shortened" : r.change_pct > 0 ? "drifted" : "flat";
    return `<tr><td><span class="sw ${r.exchange ? "dash" : ""}" style="border-color:${colorFor(r.bookmaker)}"></span>${esc(r.title)}</td>
      <td class="dim">${r.exchange ? "exchange" : "bookmaker"}</td>
      <td class="num">${r.open.toFixed(2)}</td><td class="num">${r.latest.toFixed(2)}</td>
      <td class="num ${cls}" title="${word}">${r.change_pct > 0 ? "+" : ""}${r.change_pct.toFixed(1)}% ${word}</td>
      <td class="num">${r.implied_open.toFixed(1)} → ${r.implied_latest.toFixed(1)}</td></tr>`;
  }).join("") || `<tr><td colspan="6" class="dim">No prices for this outcome yet.</td></tr>`;
}

// --------------------------------------------------------------- SVG chart
function niceTicks(min, max, count) {
  const span = max - min || 1;
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) || 10 * mag;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

function drawChart(series, polls) {
  const svg = $("chart");
  const W = svg.clientWidth || 800, H = svg.clientHeight || 380;
  const m = { l: 52, r: 16, t: 12, b: 34 };
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const all = series.flatMap((s) => s.pts);
  if (!all.length) {
    svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle">No data yet - wait for the first poll.</text>`;
    return;
  }
  let x0 = Math.min(...all.map((p) => p[0])), x1 = Math.max(...polls, ...all.map((p) => p[0]));
  if (x1 === x0) { x0 -= 1800e3; x1 += 1800e3; }
  let y0 = Math.min(...all.map((p) => p[1])), y1 = Math.max(...all.map((p) => p[1]));
  const pad = (y1 - y0 || y1 * 0.05 || 1) * 0.08;
  y0 -= pad; y1 += pad;
  const X = (t) => m.l + (t - x0) / (x1 - x0) * (W - m.l - m.r);
  const Y = (v) => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);
  const dec = state.mode === "prob" ? 1 : 2;

  let g = "";
  for (const v of niceTicks(y0, y1, 6)) {
    g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)"/>`;
    g += `<text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end">${v.toFixed(dec)}${state.mode === "prob" ? "%" : ""}</text>`;
  }
  const nx = Math.max(1, Math.min(6, Math.floor((W - m.l - m.r) / 150)));
  for (let i = 0; i <= nx; i++) {
    const t = x0 + (x1 - x0) * i / nx;
    const d = new Date(t);
    const lbl = d.toLocaleDateString([], { day: "2-digit", month: "short" }) + " " +
                d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
    g += `<text x="${X(t)}" y="${H - 10}" text-anchor="${i === 0 ? "start" : i === nx ? "end" : "middle"}">${lbl}</text>`;
  }
  // Kickoff marker if inside range
  const ko = Date.parse(state.data.event.commence_time);
  if (ko >= x0 && ko <= x1) {
    g += `<line x1="${X(ko)}" x2="${X(ko)}" y1="${m.t}" y2="${H - m.b}" stroke="var(--dim)" stroke-dasharray="2 3"/>`;
  }

  for (const s of series) {
    let d = `M${X(s.pts[0][0])},${Y(s.pts[0][1])}`;
    for (let i = 1; i < s.pts.length; i++) d += `H${X(s.pts[i][0])}V${Y(s.pts[i][1])}`;
    d += `H${X(x1)}`; // carry last price to the latest poll
    g += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.exchange ? 2.25 : 1.75}"
          ${s.exchange ? 'stroke-dasharray="6 4"' : ""} stroke-linejoin="round"/>`;
  }
  g += `<line id="hover-line" y1="${m.t}" y2="${H - m.b}" stroke="var(--dim)" visibility="hidden"/>`;
  g += `<rect id="hover-zone" x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent"/>`;
  svg.innerHTML = g;

  const times = [...new Set([...polls, ...all.map((p) => p[0])])].sort((a, b) => a - b);
  const zone = svg.querySelector("#hover-zone"), line = svg.querySelector("#hover-line"), tip = $("tooltip");
  zone.addEventListener("mousemove", (ev) => {
    const r = svg.getBoundingClientRect();
    const px = (ev.clientX - r.left) * (W / r.width);
    const t = x0 + (px - m.l) / (W - m.l - m.r) * (x1 - x0);
    const near = times.reduce((a, b) => (Math.abs(b - t) < Math.abs(a - t) ? b : a));
    line.setAttribute("x1", X(near)); line.setAttribute("x2", X(near)); line.setAttribute("visibility", "visible");
    const rows = series.map((s) => {
      const last = s.pts.filter((p) => p[0] <= near).pop();
      return last ? { s, v: last[1] } : null;
    }).filter(Boolean).sort((a, b) => b.v - a.v);
    tip.innerHTML = `<div class="t">${esc(fmtTime(near))}</div>` + rows.map(({ s, v }) =>
      `<div class="r"><span><span class="sw ${s.exchange ? "dash" : ""}" style="border-color:${s.color}"></span>${esc(s.title)}</span>
       <b>${v.toFixed(dec)}${state.mode === "prob" ? "%" : ""}</b></div>`).join("");
    tip.classList.remove("hidden");
    const left = (X(near) / W) * r.width;
    tip.style.left = `${Math.min(Math.max(0, left + 12), r.width - tip.offsetWidth)}px`;
    tip.style.top = "8px";
  });
  zone.addEventListener("mouseleave", () => { tip.classList.add("hidden"); line.setAttribute("visibility", "hidden"); });
}

// --------------------------------------------------------------- wiring
document.addEventListener("click", async (ev) => {
  const el = ev.target.closest("button, li, input");
  if (!el) return;
  try {
    if (el.dataset.untrack) {
      ev.stopPropagation();
      await api(`/api/events/${encodeURIComponent(el.dataset.untrack)}/track`, { method: "POST", body: JSON.stringify({ tracked: false }) });
      return refreshAll();
    }
    if (el.dataset.event) return openEvent(el.dataset.event);
    if (el.dataset.track !== undefined) {
      await api(`/api/events/${encodeURIComponent(el.dataset.track)}/track`, { method: "POST", body: JSON.stringify({ tracked: el.checked }) });
      return refreshAll();
    }
    if (el.dataset.poll) {
      const cost = state.status.cost_per_poll;
      if (!confirm(`Poll ${el.dataset.poll} now? This costs about ${cost} credit(s).`)) return;
      el.disabled = true;
      const r = await api(`/api/poll/${encodeURIComponent(el.dataset.poll)}`, { method: "POST" });
      if (!r.polled) alert(`Not polled: ${r.reason}`);
      await refreshAll();
      if (state.eventId) openEvent(state.eventId);
      return;
    }
    if (el.dataset.outcome) { state.outcome = el.dataset.outcome; document.querySelectorAll("#outcome-tabs button").forEach((b) => b.classList.toggle("on", b === el)); return render(); }
    if (el.dataset.mode) { state.mode = el.dataset.mode; document.querySelectorAll("#mode-seg button").forEach((b) => b.classList.toggle("on", b === el)); return render(); }
    if (el.dataset.bm) { state.hidden.has(el.dataset.bm) ? state.hidden.delete(el.dataset.bm) : state.hidden.add(el.dataset.bm); return render(); }
    if (el.id === "btn-load-fixtures") return loadFixtures(true);
  } catch (err) {
    alert(err.message);
  }
});
$("market-select").addEventListener("change", (e) => { state.market = e.target.value; openEvent(state.eventId); });
$("sport-select").addEventListener("change", () => loadFixtures(false));
window.addEventListener("resize", () => render());

async function refreshAll() {
  await Promise.all([loadStatus(), loadTracked(), loadCalls()]).catch((e) => console.error(e));
}

(async () => {
  await refreshAll();
  loadFixtures(false);
  // Refresh the page data every minute (this reads our own server, it costs no credits).
  setInterval(async () => { await refreshAll(); if (state.eventId) openEvent(state.eventId); }, 60000);
})();
