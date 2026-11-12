const API = "/api";
let currentDrilldownId = null;
let currentRound = null; // null = "live" (is_monitored=true), else a round_label
let charts = [];

// ---------------------------------------------------------------------------
// Rounds
// ---------------------------------------------------------------------------

async function loadRounds(preferredLabel) {
  const rounds = await api("/rounds");
  const select = document.getElementById("round-select");
  const previous = preferredLabel !== undefined ? preferredLabel : select.value;

  select.innerHTML = rounds
    .map((r) => {
      const range = r.earliest_kickoff
        ? new Date(r.earliest_kickoff).toLocaleDateString()
        : "";
      return `<option value="${r.round_label}">${r.round_label} — ${r.match_count} matches (${range})${r.is_active ? " ● live" : ""}</option>`;
    })
    .join("");

  let target = previous;
  if (!target || !rounds.some((r) => r.round_label === target)) {
    const active = rounds.find((r) => r.is_active);
    target = active ? active.round_label : rounds[0] ? rounds[0].round_label : null;
  }
  if (target) select.value = target;
  currentRound = target;
  updateRoundStatus(rounds);
}

function updateRoundStatus(rounds) {
  const status = document.getElementById("round-status");
  const r = rounds.find((x) => x.round_label === currentRound);
  if (!r) {
    status.textContent = "";
    return;
  }
  status.textContent = r.is_active ? "● live — actively polling" : "○ archived — no longer polled";
  status.className = r.is_active ? "pill pill-ok" : "pill pill-dim";
}

document.getElementById("round-select").onchange = async (e) => {
  currentRound = e.target.value;
  const rounds = await api("/rounds");
  updateRoundStatus(rounds);
  loadSummary();
};

document.getElementById("btn-rename-round").onclick = async () => {
  if (!currentRound) {
    alert("Select a round first.");
    return;
  }
  // Renaming (unlabeled) only relabels the matches sitting in it right
  // now - any match removed from a round afterwards still lands back in
  // a fresh (unlabeled) bucket, so pre-filling with that literal text
  // would be misleading rather than helpful.
  const promptDefault = currentRound === "(unlabeled)" ? "" : currentRound;
  const newName = prompt("New name for this round:", promptDefault);
  if (!newName || !newName.trim() || newName.trim() === currentRound) return;
  await api("/rounds/rename", {
    method: "PATCH",
    body: JSON.stringify({ old_label: currentRound, new_label: newName.trim() }),
  });
  await loadRounds(newName.trim());
  loadSummary();
  loadScorecard();
};

// ---------------------------------------------------------------------------
// Download (one CSV per round, or everything, for backtesting elsewhere)
// ---------------------------------------------------------------------------

async function loadDownloadRounds() {
  const rounds = await api("/rounds");
  const select = document.getElementById("download-round-select");
  select.innerHTML =
    `<option value="">All rounds (one big file)</option>` +
    rounds.map((r) => `<option value="${r.round_label}">${r.round_label} — ${r.match_count} matches</option>`).join("");
  updateDownloadHref();
}

function updateDownloadHref() {
  const select = document.getElementById("download-round-select");
  const link = document.getElementById("btn-download-data");
  const roundLabel = select.value;
  link.href = roundLabel
    ? `/api/export/match-snapshots.csv?round_label=${encodeURIComponent(roundLabel)}`
    : "/api/export/match-snapshots.csv";
}

document.getElementById("download-round-select").onchange = updateDownloadHref;

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
function renderHistoryDropdown(transitions) {
  const entries = (transitions || []).filter((t) => t.label);
  if (entries.length === 0) return "";
  const rows = entries
    .map((t) => {
      const when = new Date(t.at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
      const side = t.side ? ` (${t.side})` : "";
      const pp = t.change_pp != null ? `, ${fmtPp(t.change_pp)}` : "";
      return `<li>${when} — ${t.label}${side}${pp}</li>`;
    })
    .join("");
  return `<details class="history-dropdown"><summary>History (${entries.length})</summary><ol>${rows}</ol></details>`;
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

// ---------------------------------------------------------------------------
// Betslip cutoff markers - rounds span Saturday and Sunday, so each match's
// own "latest" reading keeps moving at a different pace. These mark what a
// match's series actually read 10 minutes before the round's two real
// decision points (earliest kickoff overall = Saturday betslip lock-in;
// earliest Sunday kickoff = the separate Sunday-only jackpot's lock-in),
// so post-match review compares what was actually known at those moments,
// not each match's own end-of-history point.
// ---------------------------------------------------------------------------
const CUTOFF_COLOR = { saturday: "#ffffff", sunday: "#5ac8fa" };
const CUTOFF_LABEL = { saturday: "Sat", sunday: "Sun" };

function valueAtOrBefore(rows, cutoffIso, field, timeField = "captured_at") {
  if (!cutoffIso) return null;
  const cutoffMs = new Date(cutoffIso).getTime();
  let best = null;
  for (const r of rows) {
    if (r[field] === null || r[field] === undefined) continue;
    const t = new Date(r[timeField]).getTime();
    if (t <= cutoffMs && (!best || t > new Date(best[timeField]).getTime())) best = r;
  }
  return best ? best[field] : null;
}

function cutoffMarkers(rows, field, cutoffs, valueFmt, timeField = "captured_at") {
  if (!cutoffs) return [];
  const markers = [];
  for (const key of ["saturday", "sunday"]) {
    const iso = cutoffs[key];
    if (!iso) continue;
    const val = valueAtOrBefore(rows, iso, field, timeField);
    if (val === null) continue;
    markers.push({
      time: toUnixSeconds(iso),
      position: "aboveBar",
      color: CUTOFF_COLOR[key],
      shape: "circle",
      text: `${CUTOFF_LABEL[key]} ${valueFmt ? valueFmt(val) : val}`,
    });
  }
  markers.sort((a, b) => a.time - b.time);
  return markers;
}

function renderCutoffNote(cutoffs) {
  const el = document.getElementById("cutoff-note");
  if (!el) return;
  if (!cutoffs || (!cutoffs.saturday && !cutoffs.sunday)) {
    el.innerHTML = "";
    return;
  }
  const fmt = (iso) => (iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : null);
  const parts = [];
  if (cutoffs.saturday) parts.push(`<span class="swatch"><span class="dot" style="background:${CUTOFF_COLOR.saturday}"></span>Sat betslip cutoff — ${fmt(cutoffs.saturday)}</span>`);
  if (cutoffs.sunday) parts.push(`<span class="swatch"><span class="dot" style="background:${CUTOFF_COLOR.sunday}"></span>Sun betslip cutoff — ${fmt(cutoffs.sunday)}</span>`);
  el.innerHTML = parts.join("");
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

function formatCountdown(startIso) {
  const diffMs = new Date(startIso).getTime() - Date.now();
  if (diffMs <= 0) return { text: "Kicked off", cls: "countdown-live" };
  const totalSec = Math.floor(diffMs / 1000);
  const days = Math.floor(totalSec / 86400);
  const hours = Math.floor((totalSec % 86400) / 3600);
  const mins = Math.floor((totalSec % 3600) / 60);
  const secs = totalSec % 60;
  let text;
  if (days > 0) text = `${days}d ${hours}h ${mins}m`;
  else if (hours > 0) text = `${hours}h ${mins}m`;
  else if (mins > 0) text = `${mins}m ${secs}s`;
  else text = `${secs}s`;
  const cls = totalSec <= 7200 ? "countdown-urgent" : "";
  return { text, cls };
}

function tickCountdowns() {
  document.querySelectorAll(".countdown[data-start]").forEach((el) => {
    const { text, cls } = formatCountdown(el.dataset.start);
    el.textContent = text;
    el.className = `countdown ${cls}`;
  });
}

// The summary table is refreshed by a 30s timer and after every poll. Rebuilding
// it each time made the whole table flash and wiped any scores being typed, so:
// nothing is touched when the data is unchanged, changed rows are patched cell
// by cell, and score inputs that are focused or hold unsaved edits are left alone.
let lastSummarySig = null;
let summaryTimer = null;

const STEAM_COLOR = "#ff2fa0";
const SIDE_LABEL = { home: "Home", draw: "Draw", away: "Away" };

// Sides that have had a steam move, biggest first (server-ranked), as chips.
function steamChips(moves) {
  if (!moves || !moves.length) return `<span class="dim">—</span>`;
  return moves
    .map(
      (m) =>
        `<span class="steam-chip" title="Biggest steam move on ${SIDE_LABEL[m.side]}${m.count > 1 ? ` (${m.count} steam moves)` : ""}"><span class="steam-dot"></span>${SIDE_LABEL[m.side]} <strong>+${m.magnitude_pp.toFixed(2)}pp</strong></span>`
    )
    .join("");
}

function summaryCells(r) {
  const ah = r.ah_detail || {};
  const x2 = r.x2_detail || {};
  return [
    new Date(r.start_time).toLocaleString(),
    null, // countdown cell is updated by tickCountdowns()
    `${escapeHtml(r.home_team)} vs ${escapeHtml(r.away_team)}`,
    escapeHtml(r.league_name || ""),
    steamChips(r.steam_moves),
    fmtPp(x2.home_pp !== undefined ? (Math.abs(x2.home_pp) >= Math.abs(x2.away_pp) ? x2.home_pp : x2.away_pp) : null),
    ah.opening !== undefined && ah.opening !== null ? `${fmtNum(ah.opening)} → ${fmtNum(ah.current)}` : "—",
    ah.magnitude !== undefined ? fmtNum(ah.shift, 2) : "—",
  ];
}

function scoreValue(v) {
  return v !== null && v !== undefined ? String(v) : "";
}

function buildSummaryRow(r) {
  const cells = summaryCells(r);
  const tds = cells
    .map((html, i) =>
      i === 1
        ? `<td class="countdown" data-start="${r.start_time}">—</td>`
        : `<td${i === 3 ? ' class="dim"' : ""}>${html}</td>`
    )
    .join("");
  return `<tr data-id="${r.id}">${tds}
    <td class="result-cell">
      <input type="number" class="result-input" data-side="home" value="${scoreValue(r.home_score)}" placeholder="H" min="0">
      <span class="dim">-</span>
      <input type="number" class="result-input" data-side="away" value="${scoreValue(r.away_score)}" placeholder="A" min="0">
      <button type="button" class="btn btn-ghost result-save" title="Save result">✓</button>
    </td>
  </tr>`;
}

function patchSummaryRow(tr, r) {
  summaryCells(r).forEach((html, i) => {
    const td = tr.children[i];
    if (i === 1) {
      if (td.dataset.start !== r.start_time) td.dataset.start = r.start_time;
    } else if (td.dataset.h !== html) {
      td.innerHTML = html;
      td.dataset.h = html;
    }
  });
  [["home", r.home_score], ["away", r.away_score]].forEach(([side, v]) => {
    const input = tr.querySelector(`.result-input[data-side="${side}"]`);
    if (input.dataset.dirty === "1" || document.activeElement === input) return;
    const value = scoreValue(v);
    if (input.value !== value) input.value = value;
  });
}

function renderSummary(rows) {
  const body = document.getElementById("summary-body");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="9" class="dim">No matches in this round yet — use Discovery to add the Megajackpot fixtures.</td></tr>`;
    return;
  }
  const existing = Array.from(body.querySelectorAll("tr[data-id]"));
  const sameRows = existing.length === rows.length && existing.every((tr, i) => Number(tr.dataset.id) === rows[i].id);
  if (sameRows) {
    rows.forEach((r, i) => patchSummaryRow(existing[i], r));
    return;
  }
  // Row set changed (new round, match added/removed): rebuild, carrying over unsaved scores.
  const unsaved = {};
  existing.forEach((tr) => {
    const inputs = tr.querySelectorAll('.result-input[data-dirty="1"]');
    if (inputs.length) {
      unsaved[tr.dataset.id] = {};
      inputs.forEach((inp) => (unsaved[tr.dataset.id][inp.dataset.side] = inp.value));
    }
  });
  body.innerHTML = rows.map(buildSummaryRow).join("");
  rows.forEach((r, i) => {
    const tr = body.children[i];
    summaryCells(r).forEach((html, c) => {
      if (c !== 1) tr.children[c].dataset.h = html;
    });
  });
  Object.entries(unsaved).forEach(([id, sides]) => {
    const tr = body.querySelector(`tr[data-id="${id}"]`);
    if (!tr) return;
    Object.entries(sides).forEach(([side, value]) => {
      const inp = tr.querySelector(`.result-input[data-side="${side}"]`);
      inp.value = value;
      inp.dataset.dirty = "1";
    });
  });
}

// ---------------------------------------------------------------------------
// Signal scorecard: how often the engine, the steam signal and both together were right
// ---------------------------------------------------------------------------

let scorecardData = null;
let lastResultSig = null;
let scMissLabel = null;
let scHtml = { cells: null, table: null };

function scPct(right, n) {
  return n ? `${Math.round((100 * right) / n)}%` : "-";
}

function scFrac(right, n) {
  return n ? `${right} / ${n} <span class="sc-pct">${scPct(right, n)}</span>` : `<span class="dim">no matches</span>`;
}

function renderScorecard() {
  const cells = document.getElementById("sc-cells");
  const noteEl = document.getElementById("sc-note");
  const roundEl = document.getElementById("sc-round");
  if (!scorecardData) {
    cells.innerHTML = `<div class="sc-empty dim">Scorecard unavailable.</div>`;
    return;
  }
  const r = scorecardData.rounds.find((x) => x.round_label === currentRound);
  if (!r && currentRound && scMissLabel !== currentRound) {
    scMissLabel = currentRound; // round renamed/created since the last fetch: refresh once
    loadScorecard();
  }
  roundEl.textContent = r ? `${currentRound} — ${r.settled} of ${r.matches} results in` : "";
  let cellsHtml;
  if (!r || r.settled === 0) {
    cellsHtml = `<div class="sc-empty dim">No results entered for this round yet. Enter the final scores in the table below and the tally appears here.</div>`;
    noteEl.textContent = "";
  } else {
    const e = r.engine, st = r.steam, c = r.converged;
    cellsHtml = `
      <div class="sc-cell sc-engine">
        <h4>Engine (favourite)</h4>
        <div class="sc-value">${scFrac(e.right, e.picks)}</div>
        <div class="sc-sub">${e.no_pick} pick'em with no favourite not counted</div>
      </div>
      <div class="sc-cell sc-steam">
        <h4>Steam (any steaming side)</h4>
        <div class="sc-value">${scFrac(st.right, st.flagged)}</div>
        <div class="sc-sub">${st.avg_sides != null ? `covers ${st.avg_sides} of 3 sides on average, so blind picks of that many sides would get about ${st.chance_right} right` : ""}${st.no_steam ? ` · ${st.no_steam} with no steam` : ""}</div>
      </div>
      <div class="sc-cell sc-conv">
        <h4>Steam + engine</h4>
        <div class="sc-value">${scFrac(c.right, c.count)}</div>
        <div class="sc-sub">engine's favourite also had steam</div>
      </div>`;
    noteEl.textContent =
      "Engine and Steam + engine are right when the favourite won (a draw is a miss). Steam is right when the side that won was any of the steaming sides; move size is not used, so it covers several sides at once and is an easier test than a single pick.";
  }
  const row = (label, x, cls) =>
    `<tr class="${cls || ""}"><td>${escapeHtml(label)}</td>` +
    `<td>${x.settled}${x.matches != null ? ` / ${x.matches}` : ""}</td>` +
    `<td>${x.engine.picks ? `${x.engine.right} / ${x.engine.picks} (${scPct(x.engine.right, x.engine.picks)})` : "-"}</td>` +
    `<td>${x.steam.flagged ? `${x.steam.right} / ${x.steam.flagged} (${scPct(x.steam.right, x.steam.flagged)})` : "-"}</td>` +
    `<td>${x.converged.count ? `${x.converged.right} / ${x.converged.count} (${scPct(x.converged.right, x.converged.count)})` : "-"}</td></tr>`;
  if (scHtml.cells !== cellsHtml) {
    cells.innerHTML = cellsHtml;
    scHtml.cells = cellsHtml;
  }
  const tableHtml =
    scorecardData.rounds.map((x) => row(x.round_label, x, x.round_label === currentRound ? "sc-current" : "")).join("") +
    row("All rounds", { ...scorecardData.total, matches: null }, "sc-total");
  if (scHtml.table !== tableHtml) {
    document.getElementById("sc-body").innerHTML = tableHtml;
    scHtml.table = tableHtml;
  }
}

async function loadScorecard() {
  try {
    const data = await api("/matches/scorecard");
    scorecardData = data && Array.isArray(data.rounds) && data.total ? data : null;
  } catch (err) {
    scorecardData = null;
    return;
  }
  renderScorecard();
}

async function loadSummary(force = false) {
  const qs = currentRound ? `?round_label=${encodeURIComponent(currentRound)}` : "";
  const rows = await api(`/matches/summary${qs}`);
  const sig = `${currentRound}|${JSON.stringify(rows)}`;
  const resultSig = rows.map((r) => `${r.id}:${r.home_score}:${r.away_score}`).join(",");
  if (resultSig !== lastResultSig) {
    lastResultSig = resultSig;
    loadScorecard(); // only when a score or the match set changed, not on every price update
  } else {
    renderScorecard();
  }
  if (!force && sig === lastSummarySig) return;
  lastSummarySig = sig;
  renderSummary(rows);
  tickCountdowns();
}

// Poll results arrive in bursts (one per match); fold them into one refresh.
function scheduleSummaryRefresh() {
  if (summaryTimer) return;
  summaryTimer = setTimeout(() => {
    summaryTimer = null;
    loadSummary().catch(() => {});
  }, 1000);
}

// One set of listeners on the table body (rows are patched, not recreated).
(function bindSummaryTable() {
  const body = document.getElementById("summary-body");
  body.addEventListener("input", (e) => {
    if (e.target.matches(".result-input")) e.target.dataset.dirty = "1";
  });
  body.addEventListener("click", async (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (!tr) return;
    const btn = e.target.closest(".result-save");
    if (btn) {
      const homeInput = tr.querySelector('.result-input[data-side="home"]');
      const awayInput = tr.querySelector('.result-input[data-side="away"]');
      const home_score = homeInput.value === "" ? null : Number(homeInput.value);
      const away_score = awayInput.value === "" ? null : Number(awayInput.value);
      btn.disabled = true;
      try {
        await api(`/matches/${tr.dataset.id}/result`, { method: "PATCH", body: JSON.stringify({ home_score, away_score }) });
        delete homeInput.dataset.dirty;
        delete awayInput.dataset.dirty;
        await loadSummary();
      } finally {
        btn.disabled = false;
      }
      return;
    }
    if (e.target.closest(".result-cell")) return;
    openDrilldown(Number(tr.dataset.id));
  });
})();

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
// Storage: database size and deleting old rounds
// ---------------------------------------------------------------------------

function escapeHtml(v) {
  return String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtBytes(n) {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(n / 1e3))} KB`;
}

let lastStorageSig = null;

function renderStorageUsage(u) {
  const sig = JSON.stringify(u);
  if (sig === lastStorageSig) return;
  lastStorageSig = sig;
  const banner = document.getElementById("storage-banner");
  banner.className = `pill storage-pill storage-${u.level}`;
  banner.textContent = `DB ${fmtBytes(u.used_bytes)} / ${fmtBytes(u.limit_bytes)}`;
  banner.title = `${fmtBytes(u.free_bytes)} free of the ${fmtBytes(u.limit_bytes)} free-tier limit - click for details`;
  const alertEl = document.getElementById("storage-alert");
  const pct = u.used_pct.toFixed(1);
  const messages = {
    warning: `Database is ${pct}% full (${fmtBytes(u.free_bytes)} left of the free tier). Delete old rounds you have downloaded before it fills up.`,
    critical: `Database is ${pct}% full (${fmtBytes(u.free_bytes)} left). Collection pauses automatically at ${(u.pause_bytes / u.limit_bytes * 100).toFixed(0)}% to avoid the read-only lock - free space now.`,
    paused: `DATA COLLECTION IS PAUSED - database is ${pct}% full. Delete downloaded rounds, then "Reclaim disk space" in Storage. It resumes by itself once there is room.`,
  };
  if (messages[u.level]) {
    alertEl.className = `storage-alert storage-${u.level}`;
    alertEl.textContent = messages[u.level];
  } else {
    alertEl.className = "storage-alert hidden";
    alertEl.textContent = "";
  }
}

async function refreshStorageBanner() {
  try {
    renderStorageUsage(await api("/storage/status"));
  } catch (e) {
    /* banner just keeps its last state */
  }
}
document.getElementById("storage-banner").onclick = () => document.getElementById("btn-storage").click();

function askYesNo(title, text, yesLabel = "Yes") {
  return new Promise((resolve) => {
    const modal = document.getElementById("modal-confirm");
    const yes = document.getElementById("confirm-yes");
    const no = document.getElementById("confirm-no");
    document.getElementById("confirm-title").textContent = title;
    document.getElementById("confirm-text").textContent = text;
    yes.textContent = yesLabel;
    const done = (answer) => {
      modal.classList.add("hidden");
      yes.onclick = no.onclick = null;
      resolve(answer);
    };
    yes.onclick = () => done(true);
    no.onclick = () => done(false);
    modal.classList.remove("hidden");
  });
}

let storageRounds = [];
let pendingPoll = null;

async function loadStorage() {
  const msg = document.getElementById("storage-message");
  const data = await api("/storage");
  storageRounds = data.rounds;
  const u = data.usage;
  renderStorageUsage(u);
  const fill = document.getElementById("storage-bar-fill");
  fill.style.width = `${Math.min(100, u.used_pct)}%`;
  fill.className = `storage-bar-fill storage-${u.level}`;
  const top = data.tables.slice(0, 3).map((t) => `${t.name} ${fmtBytes(t.bytes)}`).join(" · ");
  document.getElementById("storage-summary").textContent =
    `Used ${fmtBytes(u.used_bytes)} of ${fmtBytes(u.limit_bytes)} (${u.used_pct.toFixed(1)}%) · ${fmtBytes(u.free_bytes)} free · ` +
    `${fmtBytes(u.usable_bytes)} before collection pauses at ${(u.pause_bytes / u.limit_bytes * 100).toFixed(0)}% (${top})`;
  const h = data.headroom;
  const bits = [];
  if (h.rounds_left != null) bits.push(`room for about ${h.rounds_left} more round${h.rounds_left === 1 ? "" : "s"} at the average size (${fmtBytes(h.avg_round_bytes)})`);
  if (h.days_left != null) bits.push(`at the last 24 hours' collection rate (~${fmtBytes(h.bytes_per_day)}/day) it pauses in about ${h.days_left} day${h.days_left === 1 ? "" : "s"}`);
  document.getElementById("storage-headroom").textContent = bits.length ? bits.join(" · ") : "";
  document.getElementById("storage-table-body").innerHTML = data.rounds
    .map((r, i) => {
      const csv = `/api/export/match-snapshots.csv?round_label=${encodeURIComponent(r.round_label)}`;
      let dl = `<span class="never-downloaded">never</span>`;
      if (r.downloaded_at) {
        const when = new Date(r.downloaded_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
        const grown = r.downloaded_snapshots != null ? r.snapshot_count - r.downloaded_snapshots : 0;
        dl = `${when}${grown > 0 ? ` <span class="never-downloaded" title="Snapshots collected after that download">(+${grown.toLocaleString()} since)</span>` : ""}`;
      }
      const del = r.is_active
        ? `<span class="dim" title="Stop tracking this round first (Start New Round)">live - cannot delete</span>`
        : `<button class="btn btn-danger" data-delete-round="${i}">Delete</button>`;
      return `<tr>
        <td>${escapeHtml(r.round_label)}</td>
        <td>${r.match_count}</td>
        <td>${r.snapshot_count.toLocaleString()}</td>
        <td>${fmtBytes(r.est_bytes)}</td>
        <td>${dl}</td>
        <td><a class="btn btn-ghost" data-csv href="${csv}" download>CSV</a> ${del}</td>
      </tr>`;
    })
    .join("");
  const pending = data.pending_delete_matches || 0;
  document.getElementById("btn-reclaim").disabled = pending > 0;
  if (pending > 0) {
    msg.textContent = `Removing ${pending} deleted match${pending === 1 ? "" : "es"} in the background...`;
    if (!pendingPoll) pendingPoll = setTimeout(pollPending, 2000);
  } else {
    msg.textContent = "";
  }
  return data;
}

async function pollPending() {
  pendingPoll = null;
  try {
    const data = await loadStorage();
    if (data && !data.pending_delete_matches) {
      document.getElementById("storage-message").textContent =
        "Deleted data cleared. Run \"Reclaim disk space\" to lower the size meter.";
    }
  } catch (e) {
    /* modal may be closed or the server restarting; stop polling */
  }
}

document.getElementById("btn-storage").onclick = () => {
  document.getElementById("modal-storage").classList.remove("hidden");
  loadStorage().catch((e) => (document.getElementById("storage-message").textContent = `Could not load storage: ${e.message}`));
};
document.getElementById("btn-storage-close").onclick = () =>
  document.getElementById("modal-storage").classList.add("hidden");

document.getElementById("storage-table-body").onclick = async (ev) => {
  if (ev.target.closest("[data-csv]")) {
    // the server records the download when it serves the file; refresh the "Downloaded" column afterwards
    setTimeout(() => loadStorage().catch(() => {}), 2500);
    return;
  }
  const btn = ev.target.closest("[data-delete-round]");
  if (!btn) return;
  const r = storageRounds[Number(btn.dataset.deleteRound)];
  const msg = document.getElementById("storage-message");
  const sure = await askYesNo(
    "Are you sure you want to delete this round?",
    `${r.round_label}\n${r.match_count} matches, ${r.snapshot_count.toLocaleString()} snapshots (~${fmtBytes(r.est_bytes)}). This cannot be undone.`,
    "Yes, delete"
  );
  if (!sure) return;
  const neverDownloaded = !r.downloaded_at;
  if (neverDownloaded) {
    const ok = await askYesNo(
      "This round has never been downloaded",
      `If you delete "${r.round_label}", this data is gone for good - there is no copy anywhere else.\n\nIs it really okay to delete it without a download?`,
      "Yes, delete anyway"
    );
    if (!ok) {
      msg.textContent = "Not deleted - download the CSV first if you want to keep this round.";
      return;
    }
  }
  btn.disabled = true;
  try {
    const out = await api(
      `/rounds?round_label=${encodeURIComponent(r.round_label)}` + (neverDownloaded ? "&allow_undownloaded=true" : ""),
      { method: "DELETE" }
    );
    const data = await loadStorage();
    if (!data.pending_delete_matches) {
      msg.textContent = `Deleted ${out.deleted_matches} matches. Run "Reclaim disk space" to lower the size meter.`;
    }
    await loadRounds();
    await loadSummary();
    loadScorecard();
    await loadDownloadRounds();
  } catch (e) {
    btn.disabled = false;
    msg.textContent = `Delete failed: ${e.message}`;
  }
};

document.getElementById("btn-reclaim").onclick = async () => {
  const msg = document.getElementById("storage-message");
  const go = await askYesNo(
    "Reclaim disk space?",
    "This briefly locks the data tables while they are rewritten (live polling pauses until it finishes) and can take a minute on a large database.",
    "Yes, reclaim"
  );
  if (!go) return;
  const btn = document.getElementById("btn-reclaim");
  btn.disabled = true;
  msg.textContent = "Reclaiming...";
  try {
    const out = await api("/storage/reclaim", { method: "POST" });
    await loadStorage();
    let text = `Database size ${fmtBytes(out.before_bytes)} -> ${fmtBytes(out.after_bytes)}.`;
    if (out.skipped && out.skipped.length) {
      text += " Not rewritten (a compact copy needs free space the database does not have): " +
        out.skipped.map((t) => `${t.table} needs ~${fmtBytes(t.needs_bytes)}, ${fmtBytes(t.free_bytes)} available`).join("; ") +
        ". Delete more downloaded rounds first.";
    }
    msg.textContent = text;
  } catch (e) {
    msg.textContent = `Reclaim failed: ${e.message}`;
  } finally {
    btn.disabled = false;
  }
};

// ---------------------------------------------------------------------------
// Discovery
// ---------------------------------------------------------------------------

let discoveredMatches = [];

document.getElementById("btn-discovery").onclick = () => {
  document.getElementById("modal-discovery").classList.remove("hidden");
  loadSavedLeagues();
};
document.getElementById("btn-discovery-close").onclick = () =>
  document.getElementById("modal-discovery").classList.add("hidden");

async function loadSavedLeagues(checkIds) {
  const leagues = await api("/saved-leagues");
  const list = document.getElementById("saved-leagues-list");
  if (!leagues.length) {
    list.innerHTML = `<div class="league-row dim">No leagues saved yet - use "+ Add league" below.</div>`;
    return;
  }
  const toCheck = new Set(checkIds || []);
  list.innerHTML = leagues
    .map(
      (l) => `
      <div class="league-row">
        <label>
          <input type="checkbox" value="${l.league_id}" ${toCheck.has(l.league_id) ? "checked" : ""} />
          ${l.league_name} <span class="dim">#${l.league_id}</span>
        </label>
        <button class="league-remove" data-id="${l.league_id}" title="Remove from saved list">✕</button>
      </div>`
    )
    .join("");

  list.querySelectorAll(".league-remove").forEach((btn) => {
    btn.onclick = async () => {
      await api(`/saved-leagues/${btn.dataset.id}`, { method: "DELETE" });
      loadSavedLeagues();
    };
  });
}

document.getElementById("btn-toggle-add-league").onclick = () => {
  document.getElementById("add-league-form").classList.toggle("hidden");
};

document.getElementById("btn-save-league").onclick = async () => {
  const idInput = document.getElementById("in-new-league-id");
  const nameInput = document.getElementById("in-new-league-name");
  const league_id = Number(idInput.value.trim());
  const league_name = nameInput.value.trim();
  if (!league_id || !league_name) {
    alert("Both a numeric league ID and a name are required.");
    return;
  }
  await api("/saved-leagues", { method: "POST", body: JSON.stringify({ league_id, league_name }) });
  idInput.value = "";
  nameInput.value = "";
  document.getElementById("add-league-form").classList.add("hidden");
  await loadSavedLeagues([league_id]);
};

document.getElementById("btn-fetch-leagues").onclick = async () => {
  const ids = Array.from(document.querySelectorAll("#saved-leagues-list input[type=checkbox]:checked")).map(
    (el) => el.value
  );
  if (!ids.length) {
    document.getElementById("discovery-results").innerHTML = `<div class="dim">Tick at least one league above first.</div>`;
    return;
  }
  discoveredMatches = [];
  const container = document.getElementById("discovery-results");
  container.innerHTML = "Fetching…";
  try {
    for (const leagueId of ids) {
      const matches = await api(`/leagues/${leagueId}/matchups`);
      // The Arcadia /matchups list mixes real fixtures with their "special"
      // sub-markets (Draw No Bet, team props, etc.) - every special repeats
      // the same `parent` object holding the actual match. Resolve through
      // `.parent` (falling back to the entry itself when there's no parent,
      // i.e. this entry already IS the main fixture) and dedupe by that
      // resolved id, since many specials otherwise repeat the same match.
      const seen = new Map();
      for (const m of matches) {
        const main = m.parent || m;
        const participants = main.participants || [];
        const home = participants.find((p) => p.alignment === "home");
        const away = participants.find((p) => p.alignment === "away");
        if (!home || !away || seen.has(main.id)) continue;
        seen.set(main.id, {
          pinnacle_matchup_id: main.id,
          home_team: home.name,
          away_team: away.name,
          start_time: main.startTime,
          league_id: m.league?.id ?? Number(leagueId),
          league_name: m.league?.name ?? "",
        });
      }
      discoveredMatches.push(...seen.values());
    }
    container.innerHTML = discoveredMatches
      .map(
        (m, i) => `
        <label>
          <input type="checkbox" data-idx="${i}" />
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
  await loadRounds(mjp_round_label || "(unlabeled)");
  loadSummary();
};

// ---------------------------------------------------------------------------
// Drill-down
// ---------------------------------------------------------------------------

function destroyCharts() {
  charts.forEach((c) => c.remove());
  charts = [];
  destroyMarginCharts();
}

function makeChart(elId, store = charts) {
  const el = document.getElementById(elId);
  el.innerHTML = "";
  const chart = LightweightCharts.createChart(el, {
    width: el.clientWidth,
    height: el.clientHeight,
    layout: { background: { color: "#070e1b" }, textColor: "#a9c4e8", fontFamily: "monospace" },
    grid: { vertLines: { color: "#12223a" }, horzLines: { color: "#12223a" } },
    rightPriceScale: { borderColor: "#1c3354" },
    leftPriceScale: { visible: false, borderColor: "#1c3354" },
    timeScale: { borderColor: "#1c3354", timeVisible: true },
  });
  store.push(chart);
  return chart;
}

function lineOn(chart, data, color, opts = {}) {
  const series = chart.addLineSeries({ color, lineWidth: 2, ...opts });
  series.setData(data);
  return series;
}

function setLegend(elId, entries) {
  // entries: [{ color, label }, ...] - lightweight-charts has no built-in
  // legend, so this just renders colored dots next to labels above the
  // chart, in the same order/colors the series were plotted in.
  const el = document.getElementById(elId);
  if (!el) return;
  el.innerHTML = entries
    .map((e) => `<span class="swatch"><span class="dot" style="background:${e.color}"></span>${e.label}</span>`)
    .join("");
}

function renderCards(detail) {
  const sig = detail.latest_signals || {};
  const cardsEl = document.getElementById("dd-cards");
  const ah = sig.ah_line_shift?.detail_json || {};
  const x2 = sig.x2_displacement?.detail_json || {};
  const fav = sig.favorite_strength?.detail_json || {};
  const favTeamName = fav.favorite === "home" ? detail.matchup.home_team
    : fav.favorite === "away" ? detail.matchup.away_team : null;
  const x2HistoryDropdown = renderHistoryDropdown(detail.x2_transitions);
  const fmtWhen = (iso) => new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  const teamFor = { home: detail.matchup.home_team, draw: "Draw", away: detail.matchup.away_team };
  const steam = detail.steam_moves || [];
  const steamRows = steam.length
    ? `<ol class="steam-list">${steam
        .map(
          (m) =>
            `<li><span class="steam-dot"></span><strong>${escapeHtml(teamFor[m.side])}</strong> <span class="steam-mag">+${m.magnitude_pp.toFixed(2)}pp</span><span class="sub"> ${fmtWhen(m.from)} → ${fmtWhen(m.to)}${m.count > 1 ? ` · ${m.count} steam moves` : ""}</span></li>`
        )
        .join("")}</ol>`
    : `<div class="value dim">No steam move yet</div><div class="sub">A steam move is a fast swing of 0.8pp or more on a 1X2 line, seen in the 1X2 chart below.</div>`;

  cardsEl.innerHTML = `
    <div class="card card-wide card-steam">
      <h4>Steam moves <span class="pill-experimental">ranked by size</span></h4>
      ${steamRows}
    </div>
    <div class="card card-experimental">
      <h4>Favorite <span class="pill-experimental">${fav.lead_change ? "hard rule: flipped" : "early read"}</span></h4>
      <div class="value">${favTeamName ? `${favTeamName} (${fav.favorite})` : "Pick'em — no favorite"}</div>
      <div class="sub">${fav.opening_line != null ? `opening AH line ${fmtNum(fav.opening_line)}` : "—"}${fav.favorite_prob != null ? ` · ${fmtPct(fav.favorite_prob)} win prob (1X2, at ${fav.lead_change ? "current" : "open"})` : ""}</div>
      ${fav.lead_change && fav.lead_change_gap_pp != null
        ? `<div class="sub">⚠ 1X2 lead changed from ${fav.opening_favorite || "pick'em"} by ${fav.lead_change_gap_pp.toFixed(2)}pp - overriding the opening line per the hard rule in RESEARCH_FINDINGS.md section 10</div>`
        : `<div class="sub">Backtested on 115 real matches: right 68.1% of non-draw matches, improving with a bigger line - see RESEARCH_FINDINGS.md</div>`}
      ${fav.confidence && fav.confidence !== "none" && fav.confirming_move_pp != null
        ? `<div class="sub">✓ confidence: <strong>${fav.confidence}</strong> - a ${fav.confirming_move_pp.toFixed(2)}pp 1X2 swing confirmed this favorite (backtested 73-80% right at this size, section 12)</div>`
        : `<div class="sub">confidence: none - no sizeable confirming 1X2 swing seen yet</div>`}
    </div>
    <div class="card">
      <h4>AH line shift</h4>
      <div class="value">${ah.opening !== undefined ? `${fmtNum(ah.opening)} → ${fmtNum(ah.current)}` : "—"}</div>
      <div class="sub">shift ${fmtNum(ah.shift)} / direction ${ah.direction || "—"}</div>
      ${ah.prob_fallback_used
        ? `<div class="sub">ℹ line hasn't moved, but the price at that line has: ${ah.prob_fallback?.direction
            ? `${fmtPp(ah.prob_fallback.magnitude)} toward ${ah.prob_fallback.direction} — this is what's driving the score`
            : "not enough movement there either"}</div>`
        : ""}
    </div>
    <div class="card">
      <h4>1X2 displacement</h4>
      <div class="value">${fmtPp(x2.home_pp)} H / ${fmtPp(x2.draw_pp)} D / ${fmtPp(x2.away_pp)} A</div>
      <div class="sub">from true opening line</div>
      ${x2.swung_back ? `<div class="sub">⚠ swung back: peaked at ${fmtPp(x2.peak_pp)} ${x2.peak_side} earlier, since retraced — not scored, shown for context only</div>` : ""}
      ${x2HistoryDropdown}
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
        <td class="dim">${r.market_key || ""}</td>
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

const MARGIN_MARKETS = {
  moneyline_main: {
    hasLine: false,
    picks: [
      { price: "home_price", fair: "fair_home_prob", color: "#39ff88", label: (h) => `${h} (Home)` },
      { price: "draw_price", fair: "fair_draw_prob", color: "#ffd60a", label: () => "Draw" },
      { price: "away_price", fair: "fair_away_prob", color: "#ff9500", label: (h, a) => `${a} (Away)` },
    ],
  },
  spread_main: {
    hasLine: true,
    picks: [
      { price: "home_price", fair: "fair_home_prob", color: "#39ff88", label: (h) => `${h} (Home)` },
      { price: "away_price", fair: "fair_away_prob", color: "#ff9500", label: (h, a) => `${a} (Away)` },
    ],
  },
  total_main: {
    hasLine: true,
    picks: [
      { price: "home_price", fair: "fair_home_prob", color: "#39ff88", label: () => "Over" },
      { price: "away_price", fair: "fair_away_prob", color: "#ff9500", label: () => "Under" },
    ],
  },
};

let marginDetail = null;
let marginCharts = [];

// One row per usable snapshot: total margin (sum of 1/price - 1) and, per pick,
// its margin (price-implied minus de-vigged fair probability, in pp) and its
// share of the total.
function computeMarginRows(series, market) {
  const cfg = MARGIN_MARKETS[market];
  const rows = [];
  for (const s of series || []) {
    if (s.status === "suspended") continue;
    if (cfg.picks.some((p) => s[p.price] == null || s[p.fair] == null)) continue;
    const prices = cfg.picks.map((p) => Number(s[p.price]));
    const fairs = cfg.picks.map((p) => Number(s[p.fair]));
    if (prices.some((v) => !(v > 1)) || fairs.some((v) => !Number.isFinite(v))) continue;
    const imp = prices.map((v) => 1 / v);
    const total = imp.reduce((a, b) => a + b, 0) - 1;
    const row = { captured_at: s.captured_at, total: total * 100 };
    imp.forEach((v, i) => {
      row[`pp_${i}`] = (v - fairs[i]) * 100;
      row[`share_${i}`] = total > 1e-9 ? ((v - fairs[i]) / total) * 100 : null;
    });
    rows.push(row);
  }
  return rows;
}

function destroyMarginCharts() {
  marginCharts.forEach((c) => c.remove());
  marginCharts = [];
}

function renderMarginCharts() {
  if (!marginDetail || typeof LightweightCharts === "undefined") return;
  destroyMarginCharts();
  const market = document.getElementById("margin-market").value;
  const cfg = MARGIN_MARKETS[market];
  const rows = computeMarginRows((marginDetail.series || {})[market], market);
  const summary = document.getElementById("margin-summary");
  const home = marginDetail.matchup.home_team;
  const away = marginDetail.matchup.away_team;
  const cutoffs = marginDetail.betslip_cutoffs;
  const ppFmt = (v) => `${Number(v).toFixed(2)}pp`;
  const sharePctFmt = (v) => `${Number(v).toFixed(1)}%`;

  if (rows.length === 0) {
    summary.textContent = "No usable snapshots for this market yet.";
  } else {
    const first = rows[0];
    const last = rows[rows.length - 1];
    const sh = (r, i) => (r[`share_${i}`] == null ? "—" : `${r[`share_${i}`].toFixed(1)}%`);
    summary.textContent =
      `Total margin ${first.total.toFixed(2)}% at open → ${last.total.toFixed(2)}% latest · ` +
      cfg.picks.map((p, i) => `${p.label(home, away)} share ${sh(first, i)} → ${sh(last, i)}`).join(" · ");
  }

  const c1 = makeChart("chart-margin-pp", marginCharts);
  const sTotal = lineOn(c1, toSeriesData(rows, "total"), COLOR_LINE);
  cfg.picks.forEach((p, i) => lineOn(c1, toSeriesData(rows, `pp_${i}`), p.color));
  sTotal.setMarkers(cutoffMarkers(rows, "total", cutoffs, (v) => `${Number(v).toFixed(2)}%`));
  setLegend("legend-margin-pp", [
    { color: COLOR_LINE, label: "Total margin (%)" },
    ...cfg.picks.map((p) => ({ color: p.color, label: `${p.label(home, away)} margin (pp)` })),
  ]);

  const c2 = makeChart("chart-margin-share", marginCharts);
  let firstShare = null;
  cfg.picks.forEach((p, i) => {
    const s = lineOn(c2, toSeriesData(rows, `share_${i}`), p.color);
    if (i === 0) firstShare = s;
  });
  if (firstShare) firstShare.setMarkers(cutoffMarkers(rows, "share_0", cutoffs, sharePctFmt));
  setLegend("legend-margin-share", cfg.picks.map((p) => ({ color: p.color, label: p.label(home, away) })));
}

document.getElementById("margin-market").onchange = renderMarginCharts;

const COLOR_HOME = "#39ff88";
const COLOR_DRAW = "#ffd60a";
const COLOR_AWAY = "#ff9500";
const COLOR_LINE = "#bf5af2";

// Move shapes (see velocity_shape() in app/signals.py) and the line colour each
// one gets on the 1X2 fair-probability chart while it applies.
const MOVE_SHAPES = {
  steam: { color: "#ff2fa0", label: "Steam", desc: "fast move, mostly within the last few hours" },
  building: { color: "#38d6ff", label: "Building", desc: "move still in progress" },
  drift: { color: "#9b7bff", label: "Drift", desc: "older move that has gone quiet" },
  reversal: { color: "#ff3b3b", label: "Reversal", desc: "recently backing off the move" },
  swung_back: { color: "#f4f7ff", label: "Swung back", desc: "swung away from the opening line and came back" },
};

// Points inside a move's time span get that shape's colour; the segment ending
// at a point takes the point's colour, so a span (from, to] colours exactly the
// stretch from the moment the shape appeared until it stopped. Everything else
// keeps the line's normal colour.
function moveColoredData(rows, field, side, timeline) {
  const data = toSeriesData(rows, field).map((d) => ({ ...d, value: d.value * 100 }));
  const spans = (timeline || [])
    .filter((g) => g.side === side && MOVE_SHAPES[g.label])
    .map((g) => ({ from: toUnixSeconds(g.from), to: toUnixSeconds(g.to), color: MOVE_SHAPES[g.label].color }));
  if (!spans.length) return data;
  for (const d of data) {
    const span = spans.find((g) => d.time > g.from && d.time <= g.to);
    if (span) d.color = span.color;
  }
  return data;
}

function renderMoveKey(timeline, detail) {
  const key = document.getElementById("key-1x2-moves");
  const notes = document.getElementById("notes-1x2-moves");
  if (!key) return;
  const present = new Set((timeline || []).map((g) => g.label));
  key.innerHTML =
    Object.entries(MOVE_SHAPES)
      .map(
        ([name, m]) =>
          `<div class="move-key-item${present.has(name) ? " seen" : ""}"><span class="move-key-line" style="background:${m.color}"></span><span><strong>${m.label}</strong> <span class="dim">${m.desc}</span></span></div>`
      )
      .join("") +
    `<div class="move-key-item"><span class="move-key-line move-key-default"></span><span><strong>Normal colour</strong> <span class="dim">no move in progress</span></span></div>`;
  const sideName = { home: detail.matchup.home_team, draw: "Draw", away: detail.matchup.away_team };
  const fmt = (iso) => new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  const spans = timeline || [];
  notes.innerHTML = spans.length
    ? `<details><summary>${spans.length} move${spans.length === 1 ? "" : "s"} in this match (shape when each stopped)</summary><ul class="move-list">` +
      spans
        .map(
          (g) =>
            `<li><span class="move-key-line" style="background:${MOVE_SHAPES[g.label].color}"></span><strong>${MOVE_SHAPES[g.label].label}</strong> on ${escapeHtml(sideName[g.side])} <span class="dim">${fmtPp(g.change_pp)} · ${fmt(g.from)} → ${fmt(g.to)}</span></li>`
        )
        .join("") +
      "</ul></details>"
    : `<span class="dim">No move of 0.8pp or more detected on any line yet.</span>`;
}

function renderCharts(detail) {
  const warningEl = document.getElementById("chart-lib-warning");
  if (typeof LightweightCharts === "undefined") {
    warningEl.textContent =
      "Chart library failed to load from unpkg.com (CDN blocked or unreachable) - charts can't render, but the raw snapshot table below still has all the data.";
    warningEl.classList.remove("hidden");
    return;
  }
  warningEl.classList.add("hidden");
  destroyCharts();
  const ml = detail.series.moneyline_main;
  const sp = detail.series.spread_main;
  const tot = detail.series.total_main;
  const home = detail.matchup.home_team;
  const away = detail.matchup.away_team;
  const cutoffs = detail.betslip_cutoffs;
  renderCutoffNote(cutoffs);
  const pctFmt = (v) => `${(v * 100).toFixed(1)}%`;
  const numFmt = (v) => Number(v).toFixed(2);

  const timeline = detail.move_spans || [];
  const c1 = makeChart("chart-1x2-prob");
  const s1h = lineOn(c1, moveColoredData(ml, "fair_home_prob", "home", timeline), COLOR_HOME);
  lineOn(c1, moveColoredData(ml, "fair_draw_prob", "draw", timeline), COLOR_DRAW);
  lineOn(c1, moveColoredData(ml, "fair_away_prob", "away", timeline), COLOR_AWAY);
  renderMoveKey(timeline, detail);
  s1h.setMarkers(cutoffMarkers(ml, "fair_home_prob", cutoffs, pctFmt));
  setLegend("legend-1x2-prob", [
    { color: COLOR_HOME, label: `${home} (Home)` },
    { color: COLOR_DRAW, label: "Draw" },
    { color: COLOR_AWAY, label: `${away} (Away)` },
  ]);

  const c2 = makeChart("chart-1x2-odds");
  const s2h = lineOn(c2, toSeriesData(ml, "home_price"), COLOR_HOME);
  lineOn(c2, toSeriesData(ml, "draw_price"), COLOR_DRAW);
  lineOn(c2, toSeriesData(ml, "away_price"), COLOR_AWAY);
  s2h.setMarkers(cutoffMarkers(ml, "home_price", cutoffs, numFmt));
  setLegend("legend-1x2-odds", [
    { color: COLOR_HOME, label: `${home} (Home)` },
    { color: COLOR_DRAW, label: "Draw" },
    { color: COLOR_AWAY, label: `${away} (Away)` },
  ]);

  const c3 = makeChart("chart-1x2-limit");
  const s3 = lineOn(c3, toSeriesData(ml, "limit_amount"), COLOR_HOME);
  s3.setMarkers(cutoffMarkers(ml, "limit_amount", cutoffs, (v) => Math.round(v)));
  setLegend("legend-1x2-limit", [{ color: COLOR_HOME, label: "1X2 market limit ($)" }]);

  const c4 = makeChart("chart-ah-line");
  const s4 = lineOn(c4, toSeriesData(sp, "home_points"), COLOR_LINE);
  s4.setMarkers(cutoffMarkers(sp, "home_points", cutoffs, numFmt));
  setLegend("legend-ah-line", [{ color: COLOR_LINE, label: `${home} handicap (points)` }]);

  const c5 = makeChart("chart-ah-prob");
  const s5h = lineOn(c5, toSeriesData(sp, "fair_home_prob").map((d) => ({ ...d, value: d.value * 100 })), COLOR_HOME);
  lineOn(c5, toSeriesData(sp, "fair_away_prob").map((d) => ({ ...d, value: d.value * 100 })), COLOR_AWAY);
  s5h.setMarkers(cutoffMarkers(sp, "fair_home_prob", cutoffs, pctFmt));
  setLegend("legend-ah-prob", [
    { color: COLOR_HOME, label: `${home} (Home)` },
    { color: COLOR_AWAY, label: `${away} (Away)` },
  ]);

  const c6 = makeChart("chart-ah-limit");
  const s6 = lineOn(c6, toSeriesData(sp, "limit_amount"), COLOR_LINE);
  s6.setMarkers(cutoffMarkers(sp, "limit_amount", cutoffs, (v) => Math.round(v)));
  setLegend("legend-ah-limit", [{ color: COLOR_LINE, label: "AH market limit ($)" }]);

  const c7 = makeChart("chart-total");
  const s7line = lineOn(c7, toSeriesData(tot, "home_points"), COLOR_LINE, { priceScaleId: "left" });
  c7.priceScale("left").applyOptions({ visible: true });
  lineOn(c7, toSeriesData(tot, "home_price"), COLOR_HOME); // "home" slot = Over, see ingest.py normalize_market
  lineOn(c7, toSeriesData(tot, "away_price"), COLOR_AWAY); // "away" slot = Under
  s7line.setMarkers(cutoffMarkers(tot, "home_points", cutoffs, numFmt));
  setLegend("legend-total", [
    { color: COLOR_LINE, label: "Goal total line (left axis)" },
    { color: COLOR_HOME, label: "Over odds (right axis)" },
    { color: COLOR_AWAY, label: "Under odds (right axis)" },
  ]);

  const c7b = makeChart("chart-total-prob");
  const s7bh = lineOn(c7b, toSeriesData(tot, "fair_home_prob").map((d) => ({ ...d, value: d.value * 100 })), COLOR_HOME);
  lineOn(c7b, toSeriesData(tot, "fair_away_prob").map((d) => ({ ...d, value: d.value * 100 })), COLOR_AWAY);
  s7bh.setMarkers(cutoffMarkers(tot, "fair_home_prob", cutoffs, pctFmt));
  setLegend("legend-total-prob", [
    { color: COLOR_HOME, label: "Over (de-vigged %)" },
    { color: COLOR_AWAY, label: "Under (de-vigged %)" },
  ]);

  marginDetail = detail;
  renderMarginCharts();
}

async function openDrilldown(matchupId) {
  currentDrilldownId = matchupId;
  const detail = await api(`/matches/${matchupId}/detail`);
  const { home_score, away_score } = detail.matchup;
  const resultSuffix = home_score !== null && away_score !== null ? ` (${home_score}-${away_score})` : "";
  document.getElementById("dd-title").textContent = `${detail.matchup.home_team} vs ${detail.matchup.away_team}${resultSuffix}`;
  const ddCountdown = document.getElementById("dd-countdown");
  ddCountdown.dataset.start = detail.matchup.start_time;
  tickCountdowns();
  try {
    renderCards(detail);
    renderRawTable(detail.raw_snapshots);
  } catch (err) {
    console.error("Failed to render match cards/table", err);
  }
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
  await loadRounds(currentRound);
  loadSummary();
};
document.getElementById("dd-remove-from-round").onclick = async () => {
  if (!currentDrilldownId) return;
  if (!confirm("Remove this match from its round? It stays monitored and keeps all its data - it just moves to the (unlabeled) bucket.")) return;
  await api(`/matches/${currentDrilldownId}/remove-from-round`, { method: "PATCH" });
  document.getElementById("dd-close").click();
  await loadRounds(currentRound);
  loadSummary();
};

// ---------------------------------------------------------------------------
// Force poll all / websocket
// ---------------------------------------------------------------------------

document.getElementById("btn-force-all").onclick = async () => {
  const rows = await api("/matches/summary");
  await Promise.all(rows.map((r) => api(`/poll/force/${r.id}`, { method: "POST" })));
};

document.getElementById("btn-start-new-round").onclick = async () => {
  const rows = await api("/matches/summary"); // always the live set, regardless of viewed round
  if (!rows.length) return;
  if (!confirm(`Stop tracking all ${rows.length} currently live matches? This round stays available in the Round dropdown to review - use Discovery to add the new round.`)) {
    return;
  }
  const endedRound = currentRound;
  await Promise.all(rows.map((r) => api(`/matches/${r.id}?is_monitored=false`, { method: "PATCH" })));
  await loadRounds(endedRound); // keep viewing the round just ended, now shown as archived
  loadSummary();
};

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}${API}/ws`);
  const status = document.getElementById("ws-status");
  let ping = null;
  let notice = null;
  ws.onopen = () => {
    clearTimeout(notice);
    status.textContent = "live";
    status.className = "pill pill-ok";
    // Idle sockets get dropped by proxies, which made the status flip to
    // "reconnecting" over and over; a small ping keeps the connection open.
    ping = setInterval(() => ws.readyState === WebSocket.OPEN && ws.send("ping"), 25000);
  };
  ws.onclose = () => {
    clearInterval(ping);
    // Reconnect quietly; only show "reconnecting" if it takes more than a few seconds.
    notice = setTimeout(() => {
      status.textContent = "reconnecting…";
      status.className = "pill pill-err";
    }, 4000);
    setTimeout(connectWs, 1500);
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "storage_paused" || msg.type === "storage_resumed") {
      refreshStorageBanner();
    } else if (msg.type === "match_update" || msg.type === "error") {
      scheduleSummaryRefresh();
      // Rebuilding the drill-down redraws every chart, so only do it when new prices arrived.
      if (msg.type === "match_update" && msg.changed && currentDrilldownId === msg.matchup_id) {
        openDrilldown(msg.matchup_id);
      }
    } else if (msg.type === "auto_unmonitored") {
      loadRounds(currentRound).then(loadSummary);
      if (currentDrilldownId === msg.matchup_id) {
        document.getElementById("dd-countdown").textContent = `Auto-removed from monitoring: ${msg.reason}`;
      }
    }
  };
}

// ---------------------------------------------------------------------------
// Interactive polish: click ripple on buttons, cursor-follow light on buttons/cards
// ---------------------------------------------------------------------------

document.addEventListener("pointerdown", (e) => {
  const btn = e.target.closest(".btn");
  if (!btn || btn.disabled) return;
  const rect = btn.getBoundingClientRect();
  const ripple = document.createElement("span");
  ripple.className = "ripple";
  ripple.style.left = `${e.clientX - rect.left}px`;
  ripple.style.top = `${e.clientY - rect.top}px`;
  btn.appendChild(ripple);
  ripple.addEventListener("animationend", () => ripple.remove());
});

let lightFrame = null;
document.addEventListener("pointermove", (e) => {
  const el = e.target.closest && e.target.closest(".btn, .card");
  if (!el || lightFrame) return;
  lightFrame = requestAnimationFrame(() => {
    lightFrame = null;
    const rect = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${e.clientX - rect.left}px`);
    el.style.setProperty("--my", `${e.clientY - rect.top}px`);
  });
});

async function init() {
  await loadRounds();
  await loadSummary();
  await loadDownloadRounds();
  connectWs();
  refreshStorageBanner();
  setInterval(refreshStorageBanner, 60000);
  setInterval(() => {
    if (!document.hidden) loadSummary().catch(() => {});
  }, 30000);
  setInterval(tickCountdowns, 1000);
}
init();
