const API = "/api";
let currentDrilldownId = null;
let charts = [];

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function fmtPct(v) {
  return v === null || v === undefined ? "—" : `${v.toFixed(2)}%`;
}
function fmtPp(v) {
  return v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}pp`;
}
function fmtNum(v, d = 2) {
  return v === null || v === undefined ? "—" : Number(v).toFixed(d);
}
function toUnixSeconds(iso) {
  return Math.floor(new Date(iso).getTime() / 1000);
}
function toSeriesData(rows, valueField, timeField = "captured_at") {
  const out = [];
  let lastTime = null;
  for (const r of rows) {
    const v = r[valueField];
    if (v === null || v === undefined) continue;
    const t = toUnixSeconds(r[timeField]);
    if (t === lastTime) {
      out[out.length - 1].value = v; // last-write-wins for same-second dupes
      continue;
    }
    out.push({ time: t, value: v });
    lastTime = t;
  }
  return out;
}

async function api(path, options) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : null;
}

// ---------------------------------------------------------------------------
// Summary table
// ---------------------------------------------------------------------------

async function loadSummary() {
  const rows = await api("/matches/summary");
  const body = document.getElementById("summary-body");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="11" class="dim">No matches being monitored yet — use Discovery to add the Megajackpot fixtures.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map((r) => {
      const ah = r.ah_detail || {};
      const x2 = r.x2_detail || {};
      const lim = r.limit_detail || {};
      const tier = r.tier || "insufficient_data";
      const kickoff = new Date(r.start_time);
      return `
      <tr data-id="${r.id}">
        <td>${kickoff.toLocaleString()}</td>
        <td>${r.home_team} vs ${r.away_team}</td>
        <td class="dim">${r.league_name || ""}</td>
        <td><span class="tier-badge tier-${tier}">${tier.replace("_", " ")}</span></td>
        <td>${r.sharp_side || "—"}</td>
        <td>${fmtNum(r.total_score, 1)}</td>
        <td>${fmtPp(x2.home_pp !== undefined ? (Math.abs(x2.home_pp) >= Math.abs(x2.away_pp) ? x2.home_pp : x2.away_pp) : null)}</td>
        <td>${fmtPct(lim.moneyline_limit_drop_pct)}</td>
        <td>${ah.opening !== undefined && ah.opening !== null ? `${fmtNum(ah.opening)} → ${fmtNum(ah.current)}` : "—"}</td>
        <td>${ah.magnitude !== undefined ? fmtNum(ah.shift, 2) : "—"}</td>
        <td>${fmtPct(lim.spread_limit_drop_pct)}</td>
      </tr>`;
    })
    .join("");

  body.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", () => openDrilldown(Number(tr.dataset.id)));
  });
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

async function loadSettingsPanel() {
  const s = await api("/settings");
  document.getElementById("settings-current").textContent =
    `Current: arcadia=${s.arcadia_api_key || "(unset)"}  telegram_token=${s.telegram_bot_token || "(unset)"}  chat_id=${s.telegram_chat_id || "(unset)"}`;
}

document.getElementById("btn-settings").onclick = () => {
  document.getElementById("modal-settings").classList.remove("hidden");
  loadSettingsPanel();
};
document.getElementById("btn-settings-close").onclick = () =>
  document.getElementById("modal-settings").classList.add("hidden");

document.getElementById("btn-settings-save").onclick = async () => {
  const body = {};
  const key = document.getElementById("in-arcadia-key").value.trim();
  const tok = document.getElementById("in-tg-token").value.trim();
  const chat = document.getElementById("in-tg-chat").value.trim();
  if (key) body.arcadia_api_key = key;
  if (tok) body.telegram_bot_token = tok;
  if (chat) body.telegram_chat_id = chat;
  await api("/settings", { method: "POST", body: JSON.stringify(body) });
  document.getElementById("modal-settings").classList.add("hidden");
};

// ---------------------------------------------------------------------------
// Discovery
// ---------------------------------------------------------------------------

let discoveredMatches = [];

document.getElementById("btn-discovery").onclick = () =>
  document.getElementById("modal-discovery").classList.remove("hidden");
document.getElementById("btn-discovery-close").onclick = () =>
  document.getElementById("modal-discovery").classList.add("hidden");

document.getElementById("btn-fetch-leagues").onclick = async () => {
  const raw = document.getElementById("in-league-ids").value;
  const ids = raw.split(",").map((s) => s.trim()).filter(Boolean);
  discoveredMatches = [];
  const container = document.getElementById("discovery-results");
  container.innerHTML = "Fetching…";
  try {
    for (const leagueId of ids) {
      const matches = await api(`/leagues/${leagueId}/matchups`);
      for (const m of matches) {
        discoveredMatches.push({
          pinnacle_matchup_id: m.matchup_id ?? m.id,
          home_team: m.home_team ?? m.home,
          away_team: m.away_team ?? m.away,
          start_time: m.startTime ?? m.start_time,
          league_id: Number(leagueId),
          league_name: m.league ?? m.league_name ?? "",
        });
      }
    }
    container.innerHTML = discoveredMatches
      .map(
        (m, i) => `
        <label>
          <input type="checkbox" data-idx="${i}" checked />
          ${new Date(m.start_time).toLocaleString()} — ${m.home_team} vs ${m.away_team}
          <span class="dim">(${m.league_name})</span>
        </label>`
      )
      .join("");
  } catch (e) {
    container.innerHTML = `<div class="dim">Fetch failed: ${e.message}</div>`;
  }
};

document.getElementById("btn-add-selected").onclick = async () => {
  const checked = Array.from(document.querySelectorAll("#discovery-results input:checked")).map(
    (el) => discoveredMatches[Number(el.dataset.idx)]
  );
  if (!checked.length) return;
  const mjp_round_label = document.getElementById("in-round-label").value.trim() || null;
  await api("/monitored-matches", {
    method: "POST",
    body: JSON.stringify({ matches: checked, mjp_round_label }),
  });
  document.getElementById("modal-discovery").classList.add("hidden");
  loadSummary();
};

// ---------------------------------------------------------------------------
// Drill-down
// ---------------------------------------------------------------------------

function destroyCharts() {
  charts.forEach((c) => c.remove());
  charts = [];
}

function makeChart(elId) {
  const el = document.getElementById(elId);
  el.innerHTML = "";
  const chart = LightweightCharts.createChart(el, {
    width: el.clientWidth,
    height: el.clientHeight,
    layout: { background: { color: "#10140f" }, textColor: "#c9f0c0", fontFamily: "monospace" },
    grid: { vertLines: { color: "#263123" }, horzLines: { color: "#263123" } },
    rightPriceScale: { borderColor: "#263123" },
    leftPriceScale: { visible: false, borderColor: "#263123" },
    timeScale: { borderColor: "#263123", timeVisible: true },
  });
  charts.push(chart);
  return chart;
}

function lineOn(chart, data, color, opts = {}) {
  const series = chart.addLineSeries({ color, lineWidth: 2, ...opts });
  series.setData(data);
  return series;
}

function renderCards(detail) {
  const s = detail.latest_score;
  const sig = detail.latest_signals || {};
  const cardsEl = document.getElementById("dd-cards");
  if (!s) {
    cardsEl.innerHTML = `<div class="card"><h4>Status</h4><div class="value">Insufficient data</div></div>`;
    return;
  }
  const ah = sig.ah_line_shift?.detail_json || {};
  const x2 = sig.x2_displacement?.detail_json || {};
  const lim = sig.limit_movement?.detail_json || {};

  cardsEl.innerHTML = `
    <div class="card">
      <h4>Tier</h4>
      <div class="value"><span class="tier-badge tier-${s.tier}">${s.tier.replace("_", " ")}</span></div>
      <div class="sub">total score ${fmtNum(s.total_score, 2)} (AH ${fmtNum(s.ah_score)} × 1.4 + 1X2 ${fmtNum(s.x2_score)} + limit ${fmtNum(s.limit_bonus)} + convergence ${fmtNum(s.convergence_bonus)})</div>
    </div>
    <div class="card">
      <h4>Sharp side</h4>
      <div class="value">${s.sharp_side || "—"}</div>
      <div class="sub">${s.contested ? "Contested: early vs late-window direction disagree" : ""}</div>
    </div>
    <div class="card">
      <h4>AH line shift</h4>
      <div class="value">${ah.opening !== undefined ? `${fmtNum(ah.opening)} → ${fmtNum(ah.current)}` : "—"}</div>
      <div class="sub">shift ${fmtNum(ah.shift)} / direction ${ah.direction || "—"}</div>
    </div>
    <div class="card">
      <h4>1X2 displacement</h4>
      <div class="value">${fmtPp(x2.home_pp)} H / ${fmtPp(x2.draw_pp)} D / ${fmtPp(x2.away_pp)} A</div>
      <div class="sub">from true opening line</div>
    </div>
    <div class="card">
      <h4>Limit movement</h4>
      <div class="value">${fmtPct(lim.moneyline_limit_drop_pct)} 1X2 / ${fmtPct(lim.spread_limit_drop_pct)} AH</div>
      <div class="sub">% drop vs opening market limit</div>
    </div>
  `;
}

function renderRawTable(rows) {
  const body = document.getElementById("raw-table-body");
  body.innerHTML = rows
    .map(
      (r) => `
      <tr>
        <td>${new Date(r.captured_at).toLocaleString()}</td>
        <td>${r.market_type}</td>
        <td>${r.period}</td>
        <td>${r.is_alternate ? "alt" : "main"}</td>
        <td>${r.status || ""}</td>
        <td>${fmtNum(r.home_price)}</td>
        <td>${fmtNum(r.draw_price)}</td>
        <td>${fmtNum(r.away_price)}</td>
        <td>${fmtNum(r.home_points)}</td>
        <td>${fmtNum(r.limit_amount, 0)}</td>
        <td>${r.fair_home_prob != null ? fmtPct(r.fair_home_prob * 100) : "—"}</td>
        <td>${r.fair_draw_prob != null ? fmtPct(r.fair_draw_prob * 100) : "—"}</td>
        <td>${r.fair_away_prob != null ? fmtPct(r.fair_away_prob * 100) : "—"}</td>
      </tr>`
    )
    .join("");
}

function renderCharts(detail) {
  destroyCharts();
  const ml = detail.series.moneyline_main;
  const sp = detail.series.spread_main;
  const tot = detail.series.total_main;

  const c1 = makeChart("chart-1x2-prob");
  lineOn(c1, toSeriesData(ml, "fair_home_prob").map((d) => ({ ...d, value: d.value * 100 })), "#39ff88");
  lineOn(c1, toSeriesData(ml, "fair_draw_prob").map((d) => ({ ...d, value: d.value * 100 })), "#ffd60a");
  lineOn(c1, toSeriesData(ml, "fair_away_prob").map((d) => ({ ...d, value: d.value * 100 })), "#ff9500");

  const c2 = makeChart("chart-1x2-odds");
  lineOn(c2, toSeriesData(ml, "home_price"), "#39ff88");
  lineOn(c2, toSeriesData(ml, "draw_price"), "#ffd60a");
  lineOn(c2, toSeriesData(ml, "away_price"), "#ff9500");

  const c3 = makeChart("chart-1x2-limit");
  lineOn(c3, toSeriesData(ml, "limit_amount"), "#39ff88");

  const c4 = makeChart("chart-ah-line");
  lineOn(c4, toSeriesData(sp, "home_points"), "#bf5af2");

  const c5 = makeChart("chart-ah-prob");
  lineOn(c5, toSeriesData(sp, "fair_home_prob").map((d) => ({ ...d, value: d.value * 100 })), "#39ff88");
  lineOn(c5, toSeriesData(sp, "fair_away_prob").map((d) => ({ ...d, value: d.value * 100 })), "#ff9500");

  const c6 = makeChart("chart-ah-limit");
  lineOn(c6, toSeriesData(sp, "limit_amount"), "#bf5af2");

  const c7 = makeChart("chart-total");
  lineOn(c7, toSeriesData(tot, "home_points"), "#bf5af2", { priceScaleId: "left" });
  c7.priceScale("left").applyOptions({ visible: true });
  lineOn(c7, toSeriesData(tot, "home_price"), "#39ff88");
  lineOn(c7, toSeriesData(tot, "away_price"), "#ff9500");

  const c8 = makeChart("chart-score");
  lineOn(c8, toSeriesData(detail.score_history, "total_score", "computed_at"), "#39ff88");
}

async function openDrilldown(matchupId) {
  currentDrilldownId = matchupId;
  const detail = await api(`/matches/${matchupId}/detail`);
  document.getElementById("dd-title").textContent = `${detail.matchup.home_team} vs ${detail.matchup.away_team}`;
  renderCards(detail);
  renderRawTable(detail.raw_snapshots);
  document.getElementById("drilldown").classList.remove("hidden");
  // charts need the container to be visible/sized before createChart
  requestAnimationFrame(() => renderCharts(detail));
}

document.getElementById("dd-close").onclick = () => {
  currentDrilldownId = null;
  destroyCharts();
  document.getElementById("drilldown").classList.add("hidden");
};
document.getElementById("dd-force-poll").onclick = async () => {
  if (currentDrilldownId) await api(`/poll/force/${currentDrilldownId}`, { method: "POST" });
};
document.getElementById("dd-unmonitor").onclick = async () => {
  if (!currentDrilldownId) return;
  await api(`/matches/${currentDrilldownId}?is_monitored=false`, { method: "PATCH" });
  document.getElementById("dd-close").click();
  loadSummary();
};

// ---------------------------------------------------------------------------
// Force poll all / websocket
// ---------------------------------------------------------------------------

document.getElementById("btn-force-all").onclick = async () => {
  const rows = await api("/matches/summary");
  await Promise.all(rows.map((r) => api(`/poll/force/${r.id}`, { method: "POST" })));
};

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}${API}/ws`);
  const status = document.getElementById("ws-status");
  ws.onopen = () => {
    status.textContent = "live";
    status.className = "pill pill-ok";
  };
  ws.onclose = () => {
    status.textContent = "reconnecting…";
    status.className = "pill pill-err";
    setTimeout(connectWs, 3000);
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "match_update" || msg.type === "error") {
      loadSummary();
      if (currentDrilldownId === msg.matchup_id) openDrilldown(msg.matchup_id);
    }
  };
}

loadSummary();
connectWs();
setInterval(loadSummary, 30000);
