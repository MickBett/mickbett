const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

// ------------------------------------------------------ team/player media --
// Missing/broken images just fold away (onerror) rather than showing a
// broken-image icon -- not every player has a photo on file.
function teamLogo(url, alt = "") {
  if (!url) return "";
  return `<img class="team-logo" src="${url}" alt="${alt}" loading="lazy" onerror="this.remove()">`;
}
function playerAvatar(url, alt = "", extraClass = "") {
  if (!url) return "";
  return `<img class="player-avatar${extraClass ? " " + extraClass : ""}" src="${url}" alt="${alt}" loading="lazy" onerror="this.remove()">`;
}
function nameCell(logoOrAvatarHtml, name) {
  return `<div class="name-cell">${logoOrAvatarHtml}<span>${name}</span></div>`;
}
// Grammatically correct possessive for a team/player name -- "Sea Bears'"
// not "Sea Bears's" for names already ending in s.
function possessive(name) {
  return name.endsWith("s") ? `${name}'` : `${name}'s`;
}

const css = getComputedStyle(document.documentElement);
const COLOR = {
  s1: css.getPropertyValue("--series-1").trim(),
  s2: css.getPropertyValue("--series-2").trim(),
  good: css.getPropertyValue("--good").trim(),
  critical: css.getPropertyValue("--critical").trim(),
  text: css.getPropertyValue("--text-secondary").trim(),
  border: css.getPropertyValue("--border").trim(),
  surface: css.getPropertyValue("--surface-1").trim(),
};

Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif";
Chart.defaults.color = COLOR.text;
Chart.defaults.borderColor = COLOR.border;

// ---------------------------------------------------------------- tabs ---
$$(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});
function activateTab(tab) {
  if (!document.getElementById(`tab-${tab}`)) return; // guard against stray .tab-btn elements
  $$(".tab-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".tab-panel").forEach(p => p.classList.toggle("active", p.id === `tab-${tab}`));
  if (tab === "standings") loadStandings();
  if (tab === "leaderboards") loadLeaderboards();
  if (tab === "rankings") loadRankings();
  if (tab === "shotcharts") loadShotChartOptions();
  if (tab === "fivemin") loadFiveMinOptions();
  if (tab === "lineups") loadLineupOptions();
  if (tab === "games") loadGames();
  if (tab === "strengths") loadStrengthsOptions();
  if (tab === "matchup") loadMatchupOptions();
}

async function refreshSummary() {
  const s = await (await fetch("/api/summary")).json();
  $("#summary-pill").textContent = `${s.games} games · ${s.teams} teams · ${s.players} players imported`;
}
refreshSummary();

// -------------------------------------------------------------- import ---
const dz = $("#dropzone");
const fileInput = $("#file-input");
dz.addEventListener("click", () => fileInput.click());
["dragenter", "dragover"].forEach(ev =>
  dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("drag-over"); })
);
["dragleave", "drop"].forEach(ev =>
  dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("drag-over"); })
);
dz.addEventListener("drop", e => handleFiles(e.dataTransfer.files));
fileInput.addEventListener("change", e => handleFiles(e.target.files));

$("#game-date").valueAsDate = new Date();

async function handleFiles(fileList) {
  for (const file of fileList) {
    await importOne(file);
  }
  refreshSummary();
}

$("#url-import-btn").addEventListener("click", importFromUrl);
$("#url-input").addEventListener("keydown", e => { if (e.key === "Enter") importFromUrl(); });

async function importFromUrl() {
  const input = $("#url-input");
  const url = input.value.trim();
  if (!url) return;
  const log = $("#import-log");
  const row = document.createElement("div");
  row.className = "import-row";
  row.textContent = `Fetching ${url}…`;
  log.prepend(row);

  const gameDate = $("#game-date").value;
  try {
    const res = await fetch("/api/import-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, game_date: gameDate || null }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Import failed");
    row.className = "import-row ok";
    row.textContent = `✓ ${data.team1} vs ${data.team2} (${data.score})`;
    input.value = "";
    refreshSummary();
  } catch (err) {
    row.className = "import-row err";
    row.textContent = `✗ ${err.message}`;
  }
}

async function importOne(file) {
  const log = $("#import-log");
  const row = document.createElement("div");
  row.className = "import-row";
  row.textContent = `Importing ${file.name}…`;
  log.prepend(row);

  const fd = new FormData();
  fd.append("file", file);
  const gameDate = $("#game-date").value;
  if (gameDate) fd.append("game_date", gameDate);

  try {
    const res = await fetch("/api/import", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Import failed");
    row.className = "import-row ok";
    row.textContent = `✓ ${file.name} — ${data.team1} vs ${data.team2} (${data.score})`;
  } catch (err) {
    row.className = "import-row err";
    row.textContent = `✗ ${file.name} — ${err.message}`;
  }
}

// ----------------------------------------------------------- standings ---
async function loadStandings() {
  const rows = await (await fetch("/api/standings")).json();
  const el = $("#standings-table");
  if (!rows.length) { el.innerHTML = "<p class='muted'>No games imported yet.</p>"; return; }
  el.innerHTML = `
    <table>
      <thead><tr>
        <th>Team</th><th class="num">W</th><th class="num">L</th><th class="num">Win%</th>
        <th class="num">PPG</th><th class="num">Opp PPG</th><th class="num">Diff</th>
      </tr></thead>
      <tbody>
        ${rows.map(r => `
          <tr>
            <td>${nameCell(teamLogo(r.logo_url, r.name), r.name)}</td>
            <td class="num">${r.wins}</td>
            <td class="num">${r.losses}</td>
            <td class="num">${(r.win_pct * 100).toFixed(1)}%</td>
            <td class="num">${r.ppg}</td>
            <td class="num">${r.papg}</td>
            <td class="num">${r.diff > 0 ? "+" : ""}${r.diff}</td>
          </tr>`).join("")}
      </tbody>
    </table>`;
}

// --------------------------------------------------------- leaderboards --
let lbData = [];
$("#lb-sort").addEventListener("change", renderLeaderboard);
async function loadLeaderboards() {
  lbData = await (await fetch("/api/players")).json();
  renderLeaderboard();
}
function renderLeaderboard() {
  const key = $("#lb-sort").value;
  const rows = [...lbData].sort((a, b) => (b[key] ?? -1) - (a[key] ?? -1));
  const el = $("#leaderboard-table");
  if (!rows.length) { el.innerHTML = "<p class='muted'>No players yet.</p>"; return; }
  el.innerHTML = `
    <table>
      <thead><tr>
        <th>Player</th><th>Team</th><th class="num">GP</th><th class="num">MPG</th>
        <th class="num">PPG</th><th class="num">RPG</th><th class="num">APG</th>
        <th class="num">SPG</th><th class="num">BPG</th>
        <th class="num">FG%</th><th class="num">3P%</th><th class="num">FT%</th>
      </tr></thead>
      <tbody>
        ${rows.map(r => `
          <tr>
            <td>${nameCell(playerAvatar(r.photo_url, r.name), r.name)}</td>
            <td>${nameCell(teamLogo(r.team_logo_url, r.team), r.team)}</td>
            <td class="num">${r.gp}</td><td class="num">${r.mpg}</td>
            <td class="num">${r.ppg}</td><td class="num">${r.rpg}</td><td class="num">${r.apg}</td>
            <td class="num">${r.spg}</td><td class="num">${r.bpg}</td>
            <td class="num">${r.fg_pct ?? "—"}</td><td class="num">${r.tp_pct ?? "—"}</td><td class="num">${r.ft_pct ?? "—"}</td>
          </tr>`).join("")}
      </tbody>
    </table>`;
}

// -------------------------------------------------------------- rankings -
let metricsMenu = null;
let rkTeamsLoaded = false;
function updateRkFilterVisibility() {
  const isPlayers = $("#rk-mode").value === "players";
  const isPointsSplit = isPlayers && $("#rk-metric").value === "trad:ppg";
  $("#rk-mingames-wrap").style.display = isPlayers ? "" : "none";
  $("#rk-team-wrap").style.display = isPlayers ? "" : "none";
  $("#rk-scope-wrap").style.display = isPointsSplit ? "" : "none";
}
$("#rk-mode").addEventListener("change", () => {
  updateRkFilterVisibility();
  loadRankingsTable();
});
$("#rk-metric").addEventListener("change", () => {
  updateRkFilterVisibility();
  loadRankingsTable();
});
$("#rk-mingames").addEventListener("change", loadRankingsTable);
$("#rk-team").addEventListener("change", loadRankingsTable);
$("#rk-scope").addEventListener("change", () => {
  // Last 3 Games caps everyone's GP at 3, so the default "5+" min-games
  // filter would silently show nobody -- drop it to 1+ automatically.
  if ($("#rk-scope").value === "last3" && Number($("#rk-mingames").value) > 3) {
    $("#rk-mingames").value = "1";
  }
  loadRankingsTable();
});

async function loadRankings() {
  if (!metricsMenu) {
    metricsMenu = await (await fetch("/api/rankings/metrics")).json();
    const sel = $("#rk-metric");
    sel.innerHTML = metricsMenu.map(g => `
      <optgroup label="${g.group}">
        ${g.items.map(i => `<option value="${i.key}">${i.label}</option>`).join("")}
      </optgroup>`).join("");
  }
  if (!rkTeamsLoaded) {
    rkTeamsLoaded = true;
    const rkTeams = await (await fetch("/api/teams")).json();
    $("#rk-team").insertAdjacentHTML("beforeend",
      rkTeams.map(t => `<option value="${t.name}">${t.name}</option>`).join(""));
  }
  updateRkFilterVisibility();
  loadRankingsTable();
}

async function loadRankingsTable() {
  const mode = $("#rk-mode").value;
  const metric = $("#rk-metric").value;
  if (!metric) return;
  const el = $("#rankings-table");
  el.innerHTML = "<p class='muted'>Loading…</p>";

  // Ranking players by Points gets a fuller shooting breakdown instead of
  // a single Value column -- PPG plus makes/attempts/% for each of 2PT,
  // 3PT and FT, since scoring volume alone doesn't say how it was scored --
  // plus a Season/Last 3 Games scope, since recent form off the season
  // total doesn't show up otherwise.
  const isPointsSplit = mode === "players" && metric === "trad:ppg";
  let url = `/api/rankings/${mode}?metric=${encodeURIComponent(metric)}`;
  if (mode === "players") url += `&min_games=${$("#rk-mingames").value}`;
  if (isPointsSplit) url += `&scope=${$("#rk-scope").value}`;
  const data = await (await fetch(url)).json();
  // Rank is computed league-wide server-side; the team filter below only
  // narrows which rows are shown -- it never renumbers "#", so a player's
  // rank still reflects where they stand against the whole league, not
  // just their own team.
  const teamFilter = mode === "players" ? $("#rk-team").value : "";
  const rows = teamFilter ? data.rows.filter(r => r.team === teamFilter) : data.rows;

  if (!rows.length) {
    el.innerHTML = teamFilter
      ? "<p class='muted'>No one on this team qualifies yet for this category (try lowering the min-games filter).</p>"
      : "<p class='muted'>No one qualifies yet for this category (try lowering the min-games filter).</p>";
    return;
  }

  const isClock = metric.startsWith("clock:");
  el.innerHTML = `
    <table>
      <thead><tr>
        <th class="num">#</th><th>${mode === "players" ? "Player" : "Team"}</th>
        ${mode === "players" ? "<th>Team</th>" : ""}
        <th class="num">GP</th>
        ${isPointsSplit ? `
          <th class="num">PPG</th>
          <th class="num">2PM</th><th class="num">2PA</th><th class="num">2P%</th>
          <th class="num">3PM</th><th class="num">3PA</th><th class="num">3P%</th>
          <th class="num">FTM</th><th class="num">FTA</th><th class="num">FT%</th>
        ` : `<th class="num">Value</th>`}
      </tr></thead>
      <tbody>
        ${rows.map(r => `
          <tr>
            <td class="num">${r.rank}</td>
            <td>${nameCell(mode === "players" ? playerAvatar(r.photo_url, r.name) : teamLogo(r.team_logo_url, r.name), r.name)}</td>
            ${mode === "players" ? `<td class="rk-team-cell" title="${r.team}">${teamLogo(r.team_logo_url, r.team)}</td>` : ""}
            <td class="num">${r.gp}</td>
            ${isPointsSplit ? `
              <td class="num"><strong>${r.ppg}</strong></td>
              <td class="num">${r.fg2_m}</td><td class="num">${r.fg2_a}</td><td class="num">${r.fg2_pct ?? "—"}</td>
              <td class="num">${r.fg3_m}</td><td class="num">${r.fg3_a}</td><td class="num">${r.tp_pct ?? "—"}</td>
              <td class="num">${r.ft_m}</td><td class="num">${r.ft_a}</td><td class="num">${r.ft_pct ?? "—"}</td>
            ` : `<td class="num">${isClock ? (r.a !== null && r.m !== null ? `${r.value} (${r.m}/${r.a})` : r.value) : r.value ?? r[metric.split(":")[1]] ?? "—"}</td>`}
          </tr>`).join("")}
      </tbody>
    </table>`;
}

// ----------------------------------------------------------- shot charts -
let teams = [], players = [];
$("#sc-mode").addEventListener("change", onScModeChange);
$("#sc-team-filter").addEventListener("change", onScTeamFilterChange);
$("#sc-select").addEventListener("change", updateShotChart);

async function loadShotChartOptions() {
  teams = await (await fetch("/api/teams")).json();
  players = await (await fetch("/api/players")).json();
  $("#sc-team-filter").innerHTML = teams.map(t => `<option value="${t.id}">${t.name}</option>`).join("");
  onScModeChange();
}

// Player mode is scoped to whichever team is selected in "Team" -- narrows
// a 200+-player dropdown down to one roster instead of listing everyone.
function populateScPlayerSelect() {
  const teamId = $("#sc-team-filter").value;
  const sel = $("#sc-select");
  const prevValue = sel.value;
  const roster = players.filter(p => String(p.team_id) === String(teamId));
  sel.innerHTML = roster.map(p => `<option value="${p.player_id}">${p.name}</option>`).join("");
  // keep the same player selected across a mode toggle if they're on this roster
  if (roster.some(p => String(p.player_id) === prevValue)) sel.value = prevValue;
}

function onScModeChange() {
  const mode = $("#sc-mode").value;
  $("#sc-player-wrap").style.display = mode === "player" ? "" : "none";
  if (mode === "player") populateScPlayerSelect();
  updateShotChart();
}

function onScTeamFilterChange() {
  if ($("#sc-mode").value === "player") populateScPlayerSelect();
  updateShotChart();
}
function fmtMA(cell, isMax = false) {
  // cell: {m, a, pct} -> "12/20 (60%)", the highest-volume cell in bold red
  if (!cell || !cell.a) return "0/0 (—)";
  const text = `${cell.m}/${cell.a} (${cell.pct}%)`;
  return isMax ? `<span class="vol-max">${text}</span>` : text;
}

let scStandings = null;
async function getStandings() {
  if (!scStandings) scStandings = await (await fetch("/api/standings")).json();
  return scStandings;
}

async function renderScProfile(mode, id) {
  const el = $("#sc-profile");
  if (mode === "team") {
    const t = teams.find(x => String(x.id) === String(id));
    if (!t) { el.innerHTML = ""; return; }
    const [standings, trend] = await Promise.all([
      getStandings(),
      (await fetch(`/api/teams/${id}/trend`)).json(),
    ]);
    const row = standings.find(s => String(s.team_id) === String(id));
    const last3 = trend.slice(-3).reverse().map(g => {
      const win = g.pts > g.opp_pts;
      const title = `${win ? "W" : "L"} ${g.pts}-${g.opp_pts} vs ${g.opponent} (${g.game_date})`;
      return `<span class="result ${win ? "win" : "loss"}" title="${title}">${win ? "W" : "L"}</span>`;
    }).join("") || "<span class='muted'>—</span>";
    el.innerHTML = `
      <div class="team-summary card">
        ${teamLogo(t.logo_url, t.name)}
        <div>
          <div class="ts-name">${t.name}</div>
          <div class="ts-record">${row ? `${row.wins}-${row.losses} record · ${(row.win_pct * 100).toFixed(1)}% win rate` : "—"}</div>
        </div>
        <div class="ts-stats">
          <div class="stat"><div class="v">${row ? row.ppg : "—"}</div><div class="l">PPG For</div></div>
          <div class="stat"><div class="v">${row ? row.papg : "—"}</div><div class="l">PPG Against</div></div>
          <div class="stat"><div class="v">${row ? (row.diff > 0 ? "+" : "") + row.diff : "—"}</div><div class="l">Diff</div></div>
        </div>
        <div class="ts-last3"><span class="l">Last 3</span>${last3}</div>
      </div>`;
  } else {
    const p = players.find(x => String(x.player_id) === String(id));
    if (!p) { el.innerHTML = ""; return; }
    const trend = await (await fetch(`/api/players/${id}/trend`)).json();
    const last5 = trend.slice(-5).reverse();
    const sum = (arr, key) => arr.reduce((a, g) => a + (g[key] || 0), 0);
    const l5 = last5.length ? {
      ppg: (sum(last5, "pts") / last5.length).toFixed(1),
      rpg: (sum(last5, "reb") / last5.length).toFixed(1),
      apg: (sum(last5, "ast") / last5.length).toFixed(1),
      spg: (sum(last5, "stl") / last5.length).toFixed(1),
      bpg: (sum(last5, "blk") / last5.length).toFixed(1),
      fg_pct: sum(last5, "fga") ? (sum(last5, "fgm") / sum(last5, "fga") * 100).toFixed(1) : null,
      tp_pct: sum(last5, "tpa") ? (sum(last5, "tpm") / sum(last5, "tpa") * 100).toFixed(1) : null,
      ft_pct: sum(last5, "fta") ? (sum(last5, "ftm") / sum(last5, "fta") * 100).toFixed(1) : null,
    } : null;
    el.innerHTML = `
      <div class="player-summary card">
        <div class="ps-header">
          ${playerAvatar(p.photo_url, p.name)}
          ${teamLogo(p.team_logo_url, p.team)}
          <div><div class="profile-name">${p.name}</div><div class="profile-sub">${p.team}</div></div>
        </div>
        <div class="ps-body">
          <div>
            <div class="ps-section-title">Season averages · ${p.gp} GP</div>
            <div class="ps-stats">
              <div class="stat"><div class="v">${p.ppg}</div><div class="l">PPG</div></div>
              <div class="stat"><div class="v">${p.rpg}</div><div class="l">RPG</div></div>
              <div class="stat"><div class="v">${p.apg}</div><div class="l">APG</div></div>
              <div class="stat"><div class="v">${p.spg}</div><div class="l">SPG</div></div>
              <div class="stat"><div class="v">${p.bpg}</div><div class="l">BPG</div></div>
              <div class="stat"><div class="v">${p.fg_pct ?? "—"}</div><div class="l">FG%</div></div>
              <div class="stat"><div class="v">${p.tp_pct ?? "—"}</div><div class="l">3P%</div></div>
              <div class="stat"><div class="v">${p.ft_pct ?? "—"}</div><div class="l">FT%</div></div>
            </div>
            <div class="ps-section-title ps-section-title-red">Last 5 games averages</div>
            <div class="ps-stats ps-stats-sub">
              ${l5 ? `
                <div class="stat"><div class="v">${l5.ppg}</div><div class="l">PPG</div></div>
                <div class="stat"><div class="v">${l5.rpg}</div><div class="l">RPG</div></div>
                <div class="stat"><div class="v">${l5.apg}</div><div class="l">APG</div></div>
                <div class="stat"><div class="v">${l5.spg}</div><div class="l">SPG</div></div>
                <div class="stat"><div class="v">${l5.bpg}</div><div class="l">BPG</div></div>
                <div class="stat"><div class="v">${l5.fg_pct ?? "—"}</div><div class="l">FG%</div></div>
                <div class="stat"><div class="v">${l5.tp_pct ?? "—"}</div><div class="l">3P%</div></div>
                <div class="stat"><div class="v">${l5.ft_pct ?? "—"}</div><div class="l">FT%</div></div>
              ` : `<span class="muted">No games yet</span>`}
            </div>
          </div>
          <div class="ps-last5">
            <div class="ps-section-title">Last 5 games</div>
            <table>
              <thead><tr>
                <th>Date</th><th>Opp</th><th class="num">Pts</th><th class="num">Reb</th>
                <th class="num">Ast</th><th class="num">FG</th>
              </tr></thead>
              <tbody>
                ${last5.length ? last5.map(g => `
                  <tr>
                    <td>${g.game_date}</td>
                    <td>${g.opponent}</td>
                    <td class="num">${g.pts}</td>
                    <td class="num">${g.reb}</td>
                    <td class="num">${g.ast}</td>
                    <td class="num">${g.fgm}/${g.fga}</td>
                  </tr>`).join("") : `<tr><td colspan="6" class="muted">No games yet</td></tr>`}
              </tbody>
            </table>
          </div>
          <div class="ps-clockchart">
            <div class="ps-section-title">Scoring by shot clock</div>
            <div class="donut-wrap">
              <canvas id="sc-clock-chart" width="140" height="140"></canvas>
              ${playerAvatar(p.photo_url, p.name, "donut-avatar")}
            </div>
            <div id="sc-clock-chart-legend" class="ps-clockchart-legend"></div>
          </div>
        </div>
      </div>`;
  }
}

let scClockChart;
const CLOCK_BUCKET_COLORS = ["#1b6b44", "#d6a431", "#7c8a7e"]; // 0-8s / 8-18s / 18+s

// "Which part of the shot clock they score in" -- points scored (not just
// makes: 2s/3s/1s weighted) in each bucket, as a doughnut, with the
// player's own photo filling the hole in the middle. Only rendered in
// player mode, where the canvas from renderScProfile exists.
function renderScClockChart(buckets, gp) {
  const canvas = document.getElementById("sc-clock-chart");
  const legendEl = document.getElementById("sc-clock-chart-legend");
  if (scClockChart) { scClockChart.destroy(); scClockChart = null; }
  if (!canvas) return;
  const labels = buckets.map(b => `${b.label}s`);
  const pts = buckets.map(b => (b.fg2.m || 0) * 2 + (b.fg3.m || 0) * 3 + (b.ft.m || 0));
  const total = pts.reduce((a, b) => a + b, 0);
  const avgLabels = pts.map(v => gp ? `${(v / gp).toFixed(1)}/gm` : "");

  // Draws the per-game average straight onto each ring segment (not just
  // in the legend text) -- centered on that segment's own arc.
  const avgLabelPlugin = {
    id: "clockAvgLabels",
    afterDraw(chart) {
      const meta = chart.getDatasetMeta(0);
      const ctx = chart.ctx;
      meta.data.forEach((arc, i) => {
        if (!pts[i] || !avgLabels[i]) return;
        const { startAngle, endAngle, innerRadius, outerRadius, x, y } =
          arc.getProps(["startAngle", "endAngle", "innerRadius", "outerRadius", "x", "y"], true);
        const midAngle = (startAngle + endAngle) / 2;
        const r = (innerRadius + outerRadius) / 2;
        const lx = x + Math.cos(midAngle) * r;
        const ly = y + Math.sin(midAngle) * r;

        ctx.save();
        ctx.font = "700 11px -apple-system, BlinkMacSystemFont, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";

        // small pill behind the text -- the segment colours (especially the
        // gold/gray ones) don't give white text alone enough contrast.
        const padX = 5, padY = 3;
        const textWidth = ctx.measureText(avgLabels[i]).width;
        const boxW = textWidth + padX * 2, boxH = 13 + padY * 2;
        ctx.fillStyle = "rgba(0, 0, 0, 0.4)";
        ctx.beginPath();
        ctx.roundRect(lx - boxW / 2, ly - boxH / 2, boxW, boxH, boxH / 2);
        ctx.fill();

        ctx.fillStyle = "#ffffff";
        ctx.fillText(avgLabels[i], lx, ly);
        ctx.restore();
      });
    },
  };

  scClockChart = new Chart(canvas, {
    type: "doughnut",
    data: { labels, datasets: [{ data: pts, backgroundColor: CLOCK_BUCKET_COLORS, borderWidth: 0 }] },
    options: { plugins: { legend: { display: false } }, cutout: "62%" },
    plugins: [avgLabelPlugin],
  });
  if (legendEl) {
    legendEl.innerHTML = labels.map((l, i) => `
      <span><span class="sw" style="background:${CLOCK_BUCKET_COLORS[i]}"></span>${l}: ${pts[i]} pts${total ? ` (${Math.round(pts[i] / total * 100)}%)` : ""}${gp ? ` · ${(pts[i] / gp).toFixed(1)}/game` : ""}</span>
    `).join("");
  }
}

// For each shot type (2PT/3PT/FT) separately, which shot-clock section has
// the highest volume of attempts -- flagged in bold red. Each stat gets
// its own highlighted bucket, independent of the other two.
function renderClockTable(elId, buckets) {
  const bestBucketIdx = (stat) => {
    let best = 0, idx = -1;
    buckets.forEach((b, i) => { if (b[stat] && b[stat].a > best) { best = b[stat].a; idx = i; } });
    return idx;
  };
  const maxIdx = { fg2: bestBucketIdx("fg2"), fg3: bestBucketIdx("fg3"), ft: bestBucketIdx("ft") };
  $(elId).innerHTML = `
    <table>
      <thead><tr>
        <th>Shot clock</th><th class="num">2PT</th><th class="num">3PT</th><th class="num">FT</th>
        <th class="num" title="Offensive rebounds off a missed 2PT shot">OR2</th>
        <th class="num" title="Offensive rebounds off a missed 3PT shot">OR3</th>
        <th class="num" title="Fouls committed">Fouls</th>
        <th class="num" title="Fouls drawn (foulon)">Fouled</th>
        <th class="num">TO</th>
      </tr></thead>
      <tbody>
        ${buckets.map((b, i) => `
          <tr>
            <td>${b.label}s</td>
            <td class="num">${fmtMA(b.fg2, i === maxIdx.fg2)}</td>
            <td class="num">${fmtMA(b.fg3, i === maxIdx.fg3)}</td>
            <td class="num">${fmtMA(b.ft, i === maxIdx.ft)}</td>
            <td class="num">${b.oreb_2pt}</td>
            <td class="num">${b.oreb_3pt}</td>
            <td class="num">${b.fouls}</td>
            <td class="num">${b.fouled}</td>
            <td class="num">${b.tov}</td>
          </tr>`).join("")}
      </tbody>
    </table>`;
}

// For each position/zone separately, which shot-clock section has the
// highest volume of attempts -- flagged in bold red, same idea as the
// shot-clock table but per row instead of per column. The Overall column
// is never highlighted.
function renderZoneTable(elId, zoneRows) {
  const bestBucketKey = (z) => {
    let best = 0, key = null;
    ["0-8", "8-18", "18+"].forEach(k => { if (z[k] && z[k].a > best) { best = z[k].a; key = k; } });
    return key;
  };
  $(elId).innerHTML = `
    <table>
      <thead><tr>
        <th>Zone</th><th class="num">Overall</th>
        <th class="num">0-8s</th><th class="num">8-18s</th><th class="num">18+s</th>
      </tr></thead>
      <tbody>
        ${zoneRows.map(z => {
          const bestKey = bestBucketKey(z);
          return `
          <tr>
            <td>${z.label}</td>
            <td class="num">${fmtMA(z.overall)}</td>
            <td class="num">${fmtMA(z["0-8"], bestKey === "0-8")}</td>
            <td class="num">${fmtMA(z["8-18"], bestKey === "8-18")}</td>
            <td class="num">${fmtMA(z["18+"], bestKey === "18+")}</td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>`;
}

async function updateShotChart() {
  const mode = $("#sc-mode").value;
  const id = mode === "team" ? $("#sc-team-filter").value : $("#sc-select").value;
  if (!id) return;
  const base = mode === "team" ? "teams" : "players";
  await renderScProfile(mode, id);
  $("#sc-image").src = `/api/${base}/${id}/shotchart.png?t=${Date.now()}`;

  const buckets = await (await fetch(`/api/${base}/${id}/clock-breakdown`)).json();
  if (mode === "player") {
    const p = players.find(x => String(x.player_id) === String(id));
    renderScClockChart(buckets, p ? p.gp : null);
  } else if (scClockChart) {
    scClockChart.destroy();
    scClockChart = null;
  }
  renderClockTable("#sc-clock-table", buckets);

  $("#zone-image").src = `/api/${base}/${id}/zonemap.png?t=${Date.now()}`;
  const zoneRows = await (await fetch(`/api/${base}/${id}/zone-breakdown`)).json();
  renderZoneTable("#zone-table", zoneRows);

  // Defense ("shots allowed") is a team-only concept -- shown as a second,
  // identical set of charts/tables below, only when a team is selected.
  $("#sc-defense-section").style.display = mode === "team" ? "" : "none";
  if (mode === "team") {
    $("#sc-image-def").src = `/api/teams/${id}/shotchart-against.png?t=${Date.now()}`;
    $("#zone-image-def").src = `/api/teams/${id}/zonemap-against.png?t=${Date.now()}`;
    const [bucketsDef, zoneRowsDef] = await Promise.all([
      (await fetch(`/api/teams/${id}/clock-breakdown-against`)).json(),
      (await fetch(`/api/teams/${id}/zone-breakdown-against`)).json(),
    ]);
    renderClockTable("#sc-clock-table-def", bucketsDef);
    renderZoneTable("#zone-table-def", zoneRowsDef);
  }
}

// --------------------------------------------------------------- games ---
async function loadGames() {
  const rows = await (await fetch("/api/games")).json();
  const el = $("#games-list");
  if (!rows.length) { el.innerHTML = "<p class='muted'>No games imported yet.</p>"; return; }
  el.innerHTML = `
    <table>
      <thead><tr><th>Date</th><th>Matchup</th><th class="num">Score</th></tr></thead>
      <tbody>
        ${rows.map(r => `
          <tr class="game-row" data-id="${r.id}">
            <td>${r.game_date}</td>
            <td><div class="matchup-cell">${teamLogo(r.team1_logo_url, r.team1)}${r.team1} vs ${teamLogo(r.team2_logo_url, r.team2)}${r.team2}</div></td>
            <td class="num">${r.team1_score} – ${r.team2_score}</td>
          </tr>`).join("")}
      </tbody>
    </table>`;
  $$(".game-row", el).forEach(row => row.addEventListener("click", () => showGame(row.dataset.id)));
}

// Game detail is a popup modal (not an inline block at the bottom of the
// page) -- clicking a game should show its box score instantly, no
// scrolling required.
const gameModal = $("#game-modal");
let gdChart, gdClockChart1, gdClockChart2;

function openGameModal() {
  document.body.classList.add("modal-open");
  gameModal.classList.add("open");
}
function closeGameModal() {
  document.body.classList.remove("modal-open");
  gameModal.classList.remove("open");
  if (gdChart) { gdChart.destroy(); gdChart = null; }
  if (gdClockChart1) { gdClockChart1.destroy(); gdClockChart1 = null; }
  if (gdClockChart2) { gdClockChart2.destroy(); gdClockChart2 = null; }
}
$("#game-modal-close").addEventListener("click", closeGameModal);
gameModal.addEventListener("click", e => { if (e.target === gameModal) closeGameModal(); });
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && gameModal.classList.contains("open")) closeGameModal();
});

async function showGame(id) {
  $("#game-detail").innerHTML = "<p class='muted'>Loading…</p>";
  openGameModal();

  const [g, scoring, clockScoring, earlyClockScorers] = await Promise.all([
    fetch(`/api/games/${id}`).then(r => r.json()),
    fetch(`/api/games/${id}/five-minute-scoring`).then(r => r.json()),
    fetch(`/api/games/${id}/shot-clock-scoring`).then(r => r.json()),
    fetch(`/api/games/${id}/shot-clock-top-scorers?bucket=0-8&limit=8`).then(r => r.json()),
  ]);

  const boxTable = (rows) => `
    <table>
      <thead><tr>
        <th>Player</th><th class="num">Min</th><th class="num">Pts</th><th class="num">Reb</th>
        <th class="num">Ast</th><th class="num">Stl</th><th class="num">Blk</th><th class="num">TO</th>
      </tr></thead>
      <tbody>
        ${rows.map(p => `
          <tr>
            <td><div class="box-player-cell">${playerAvatar(p.photo_url, p.name)}<span>${p.name}</span></div></td>
            <td class="num">${Math.round((p.minutes_sec||0)/60)}</td>
            <td class="num">${p.pts}</td><td class="num">${p.reb}</td><td class="num">${p.ast}</td>
            <td class="num">${p.stl}</td><td class="num">${p.blk}</td><td class="num">${p.tov}</td>
          </tr>`).join("")}
      </tbody>
    </table>`;

  // Compact table under each team's shot-clock chart -- 2PT/3PT/FT makes-
  // attempts-% plus offensive rebounds off a 2PT/3PT miss, per region
  // (the fuller clock table elsewhere also has fouls/TO columns, which
  // aren't wanted here). Transposed: shot-clock regions are the column
  // headers, the stat rows are the row labels.
  const gdClockTable = (buckets) => `
    <table>
      <thead><tr><th></th>${buckets.map(b => `<th class="num">${b.label}s</th>`).join("")}</tr></thead>
      <tbody>
        <tr><td>2PT</td>${buckets.map(b => `<td class="num">${fmtMA(b.fg2)}</td>`).join("")}</tr>
        <tr><td>3PT</td>${buckets.map(b => `<td class="num">${fmtMA(b.fg3)}</td>`).join("")}</tr>
        <tr><td>FT</td>${buckets.map(b => `<td class="num">${fmtMA(b.ft)}</td>`).join("")}</tr>
        <tr><td title="Offensive rebounds off a missed 2PT shot">OR2</td>${buckets.map(b => `<td class="num">${b.oreb_2pt}</td>`).join("")}</tr>
        <tr><td title="Offensive rebounds off a missed 3PT shot">OR3</td>${buckets.map(b => `<td class="num">${b.oreb_3pt}</td>`).join("")}</tr>
      </tbody>
    </table>`;

  // Top scorers in just the 0-8s shot-clock window -- who this game's
  // early-clock/transition scoring came from, grouped by team (team1's
  // group first, then team2's) so it reads like the shot-clock section
  // above it rather than one intermixed list.
  const earlyScorersGroup = (teamName, teamLogoUrl) => {
    const players = earlyClockScorers.filter(p => p.team_name === teamName);
    if (!players.length) return "";
    return `
      <div class="gd-clock-team">
        <h4 class="matchup-cell">${teamLogo(teamLogoUrl, teamName)}${teamName}</h4>
        <table class="gd-compact-table">
          <thead><tr>
            <th>Player</th><th class="num">Pts</th><th class="num">2PT</th><th class="num">3PT</th><th class="num">FT</th>
          </tr></thead>
          <tbody>
            ${players.map(p => `
              <tr>
                <td><div class="name-cell">${playerAvatar(p.photo_url, p.name)}<span>${p.name}</span></div></td>
                <td class="num">${p.pts}</td>
                <td class="num">${fmtMA(p.fg2)}</td>
                <td class="num">${fmtMA(p.fg3)}</td>
                <td class="num">${fmtMA(p.ft)}</td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>`;
  };
  const earlyScorersTable = earlyClockScorers.length
    ? earlyScorersGroup(g.team1, g.team1_logo_url) + earlyScorersGroup(g.team2, g.team2_logo_url)
    : `<p class="muted">No scoring in the 0-8s window.</p>`;

  $("#game-detail").innerHTML = `
    <h3 class="matchup-cell gd-scoreline">${teamLogo(g.team1_logo_url, g.team1)}${g.team1} ${g.team1_score} – ${g.team2_score} ${g.team2}${teamLogo(g.team2_logo_url, g.team2)} (${g.game_date})</h3>
    <div class="shotchart-grid">
      <div class="card">
        <h3>Scoring by 5-minute segment</h3>
        <canvas id="gd-scoring-chart"></canvas>
        <h3 class="gd-subsection">Top scorers — 0-8s shot clock <span class="hint" title="Both teams combined, ranked by points scored specifically in the 0-8 second shot-clock window (early clock / transition).">ⓘ</span></h3>
        ${earlyScorersTable}
      </div>
      <div class="card">
        <h3>Points by shot-clock region <span class="hint" title="Each team's own total points, split 100% across the 3 shot-clock regions -- segment width is that region's share of THIS team's scoring (0-8s = early clock, 18+s = late clock).">ⓘ</span></h3>
        <div class="gd-clock-team">
          <h4 class="matchup-cell">${teamLogo(g.team1_logo_url, g.team1)}${g.team1}</h4>
          <canvas id="gd-clock-chart-1" class="gd-clock-canvas"></canvas>
          ${gdClockTable(clockScoring.team1_buckets)}
        </div>
        <div class="gd-clock-team">
          <h4 class="matchup-cell">${teamLogo(g.team2_logo_url, g.team2)}${g.team2}</h4>
          <canvas id="gd-clock-chart-2" class="gd-clock-canvas"></canvas>
          ${gdClockTable(clockScoring.team2_buckets)}
        </div>
      </div>
    </div>
    <div class="shotchart-grid">
      <div><h3 class="matchup-cell">${teamLogo(g.team1_logo_url, g.team1)}${g.team1}</h3>${boxTable(g.box.team1)}</div>
      <div><h3 class="matchup-cell">${teamLogo(g.team2_logo_url, g.team2)}${g.team2}</h3>${boxTable(g.box.team2)}</div>
    </div>`;

  if (gdChart) { gdChart.destroy(); gdChart = null; }
  gdChart = new Chart($("#gd-scoring-chart"), {
    type: "bar",
    data: {
      labels: scoring.labels.map(l => `${l}m`),
      datasets: [
        { label: g.team1, data: scoring.team1_points, backgroundColor: COLOR.s1, borderRadius: 4 },
        { label: g.team2, data: scoring.team2_points, backgroundColor: COLOR.s2, borderRadius: 4 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: true, position: "top", labels: { boxWidth: 12 } } },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true, grid: { color: COLOR.border } },
      },
    },
  });

  if (gdClockChart1) { gdClockChart1.destroy(); gdClockChart1 = null; }
  if (gdClockChart2) { gdClockChart2.destroy(); gdClockChart2 = null; }
  gdClockChart1 = renderGdClockChart("#gd-clock-chart-1", clockScoring.team1_buckets);
  gdClockChart2 = renderGdClockChart("#gd-clock-chart-2", clockScoring.team2_buckets);
}

// A single thin 100%-stacked horizontal bar (one bar, one team) split into
// the 3 shot-clock regions -- segment width is that region's share of this
// team's own total points. Each segment is labelled directly on the chart
// with "<points> (<pct>%)", hand-drawn (no datalabels plugin dependency),
// same technique as the 5-minute-splits bar labels.
function renderGdClockChart(canvasId, buckets) {
  const total = buckets.reduce((sum, b) => sum + b.pts, 0);
  const pct = (pts) => total ? Math.round(pts / total * 1000) / 10 : 0;

  const segmentLabelPlugin = {
    id: "gdClockSegmentLabels",
    afterDatasetsDraw(chart) {
      const ctx = chart.ctx;
      ctx.save();
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      chart.data.datasets.forEach((ds, dsIndex) => {
        const bar = chart.getDatasetMeta(dsIndex).data[0];
        if (!bar) return;
        const { x, base, y } = bar.getProps(["x", "base", "y"], true);
        const width = Math.abs(x - base);
        if (width < 24 || !ds.rawPoints[0]) return; // too narrow to label cleanly
        const midX = (x + base) / 2;
        const label = `${ds.rawPoints[0]} (${ds.data[0]}%)`;
        const size = fmFitFontSize(ctx, label, width - 6, 12, 7);
        ctx.font = `700 ${size}px -apple-system, BlinkMacSystemFont, sans-serif`;
        ctx.fillStyle = "#fff";
        ctx.fillText(label, midX, y);
      });
      ctx.restore();
    },
  };

  return new Chart($(canvasId), {
    type: "bar",
    data: {
      labels: [""],
      datasets: buckets.map((b, i) => ({
        label: `${b.label}s`,
        data: [pct(b.pts)],
        rawPoints: [b.pts],
        backgroundColor: CLOCK_BUCKET_COLORS[i],
        barThickness: 26,
      })),
    },
    options: {
      indexAxis: "y",
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: true, position: "top", labels: { boxWidth: 12 } },
        tooltip: {
          callbacks: {
            label(ctx) {
              return `${ctx.dataset.label}: ${ctx.dataset.rawPoints[0]} pts (${ctx.raw}%)`;
            },
          },
        },
      },
      scales: {
        x: { stacked: true, min: 0, max: 100, ticks: { callback: v => `${v}%` }, grid: { color: COLOR.border } },
        y: { stacked: true, grid: { display: false }, ticks: { display: false } },
      },
    },
    plugins: [segmentLabelPlugin],
  });
}

// ------------------------------------------------------- scouting report -
$("#ts-team").addEventListener("change", updateStrengths);
let tsCharts = [];

async function loadStrengthsOptions() {
  if (!teams.length) teams = await (await fetch("/api/teams")).json();
  const sel = $("#ts-team");
  if (!sel.options.length) {
    sel.innerHTML = teams.map(t => `<option value="${t.id}">${t.name}</option>`).join("");
  }
  updateStrengths();
}

function tsDestroyAll() {
  tsCharts.forEach(c => c && c.destroy());
  tsCharts = [];
}

async function updateStrengths() {
  const id = $("#ts-team").value;
  if (!id) return;
  const el = $("#ts-content");
  el.innerHTML = "<p class='muted'>Loading…</p>";
  tsDestroyAll();

  const data = await (await fetch(`/api/teams/${id}/scouting-report`)).json();

  if (!data.statements.length) {
    el.innerHTML = "<p class='muted'>Not enough games imported yet to build a scouting report.</p>";
    return;
  }

  el.innerHTML = data.statements.map((s, i) => `
    <div class="card strength-card">
      <div class="strength-header">
        <span class="strength-num">${i + 1}</span>
        <div class="strength-header-text">
          <div class="strength-category">${s.category} <span class="strength-rank">Season #${s.season_rank} of ${s.season_pool} · Last 5 #${s.last5_rank} of ${s.last5_pool}</span></div>
          <p class="strength-text">${s.text}</p>
        </div>
      </div>
      <div class="strength-chart-wrap strength-chart-${s.chart.type}">
        <canvas id="ts-chart-${i}"></canvas>
      </div>
    </div>`).join("");

  data.statements.forEach((s, i) => {
    const canvasId = `#ts-chart-${i}`;
    if (s.chart.type === "segment_line") tsCharts.push(renderWeaknessSegmentLine(canvasId, s));
    else tsCharts.push(renderWeaknessCompare(canvasId, s));
  });
}

// Season vs Last-5-Games, side by side -- the "comparative evidence" bar
// every non-5-minute weakness uses. Season bar solid red (the headline
// number), last-5 bar muted (recent-form context); both bars get their
// value + league rank labelled directly on the bar.
function renderWeaknessCompare(canvasId, s) {
  const c = s.chart;
  const ranks = [c.season_rank, c.last5_rank];
  const values = [c.season_value, c.last5_value];

  const labelPlugin = {
    id: "wCompareLabels",
    afterDatasetsDraw(chart) {
      const meta = chart.getDatasetMeta(0);
      const ctx = chart.ctx;
      ctx.save();
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      meta.data.forEach((bar, i) => {
        ctx.font = "800 13px -apple-system, BlinkMacSystemFont, sans-serif";
        ctx.fillStyle = COLOR.critical;
        ctx.fillText(`${values[i]}${c.unit === "%" ? "%" : ""}`, bar.x, bar.y - 16);
        ctx.font = "600 10px -apple-system, BlinkMacSystemFont, sans-serif";
        ctx.fillStyle = COLOR.text;
        ctx.fillText(`#${ranks[i]} of ${c.pool}`, bar.x, bar.y - 2);
      });
      ctx.restore();
    },
  };

  return new Chart($(canvasId), {
    type: "bar",
    data: {
      labels: ["Season", "Last 5 Games"],
      datasets: [{ data: values, backgroundColor: [COLOR.critical, COLOR.border], borderRadius: 4 }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      layout: { padding: { top: 34 } },
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { font: { weight: "700" } } },
        y: { beginAtZero: true, grid: { color: COLOR.border } },
      },
    },
    plugins: [labelPlugin],
  });
}

// Season vs Last-5-Games across all 8 five-minute segments -- two lines,
// with a dashed vertical marker on the specific segment the weakness is
// about (the team's worst-ranked stretch this season).
function renderWeaknessSegmentLine(canvasId, s) {
  const c = s.chart;
  const highlightPlugin = {
    id: "wSegHighlight",
    afterDatasetsDraw(chart) {
      const point = chart.getDatasetMeta(0).data[c.highlight_index];
      if (!point) return;
      const ctx = chart.ctx;
      const area = chart.chartArea;
      ctx.save();
      ctx.strokeStyle = COLOR.critical;
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(point.x, area.top);
      ctx.lineTo(point.x, area.bottom);
      ctx.stroke();
      ctx.restore();
    },
  };

  return new Chart($(canvasId), {
    type: "line",
    data: {
      labels: c.labels,
      datasets: [
        { label: "Season", data: c.season_values, borderColor: COLOR.critical, backgroundColor: COLOR.critical, tension: 0.25, pointRadius: 3 },
        { label: "Last 5 Games", data: c.last5_values, borderColor: COLOR.s2, backgroundColor: COLOR.s2, tension: 0.25, pointRadius: 3, borderDash: [4, 3] },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: true, position: "top", labels: { boxWidth: 12 } } },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true, grid: { color: COLOR.border } },
      },
    },
    plugins: [highlightPlugin],
  });
}

// ---------------------------------------------------------- 5 minute splits
$("#fm-team").addEventListener("change", updateFiveMin);
$("#fm-scope").addEventListener("change", updateFiveMin);
let fmCharts = {};

async function loadFiveMinOptions() {
  if (!teams.length) teams = await (await fetch("/api/teams")).json();
  const sel = $("#fm-team");
  if (!sel.options.length) {
    sel.innerHTML = teams.map(t => `<option value="${t.id}">${t.name}</option>`).join("");
  }
  updateFiveMin();
}

function fmDestroy(key) {
  if (fmCharts[key]) { fmCharts[key].destroy(); fmCharts[key] = null; }
}

const ROYAL_BLUE = "#4169e1";

// Same league-wide rank (by whatever the chart plots) that colours the
// x-axis label for a segment, turned into a colour/weight/box spec for a
// value label: top 2 bold royal blue (rank #1 boxed too), bottom 3 red
// (league-worst boxed), everyone else plain.
function fmRankStyle(r) {
  if (!r || !r.rank) return { color: COLOR.text, weight: "700", boxed: false };
  if (r.rank <= 2) return { color: ROYAL_BLUE, weight: "800", boxed: r.rank === 1 };
  if (r.rank > r.pool - 3) return { color: COLOR.critical, weight: "800", boxed: r.rank === r.pool };
  return { color: COLOR.text, weight: "700", boxed: false };
}

function fmDrawBoxedText(ctx, text, x, y, size, weight, color, boxed) {
  ctx.font = `${weight} ${size}px -apple-system, BlinkMacSystemFont, sans-serif`;
  if (boxed) {
    const w = ctx.measureText(text).width;
    const padX = 4, padY = 3;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.strokeRect(x - w / 2 - padX, y - size - padY, w + padX * 2, size + padY * 2);
  }
  ctx.fillStyle = color;
  ctx.fillText(text, x, y);
}

// Draws a text label above each bar (the average value) -- Chart.js has no
// built-in data-label support, so this is a small inline plugin, same
// technique as the shot-clock donut labels. Coloured/boxed by rank, same as
// the shooting charts: top 2 bold royal blue (#1 boxed), bottom 3 red
// (league-worst boxed).
function fmBarLabelPlugin(labels, ranks) {
  return {
    id: "fmBarLabels",
    afterDatasetsDraw(chart) {
      const meta = chart.getDatasetMeta(0);
      const ctx = chart.ctx;
      ctx.save();
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      meta.data.forEach((bar, i) => {
        if (!labels[i]) return;
        const maxWidth = Math.max(10, bar.width - 4);
        const size = fmFitFontSize(ctx, labels[i], maxWidth, 12, 7);
        const { color, weight, boxed } = fmRankStyle(ranks[i]);
        fmDrawBoxedText(ctx, labels[i], bar.x, bar.y - 4, size, weight, color, boxed);
      });
      ctx.restore();
    },
  };
}

// Largest font size (in px, stepping down) that keeps `text` within
// `maxWidth` on the given context -- so labels never spill past a narrow bar.
function fmFitFontSize(ctx, text, maxWidth, maxSize = 11, minSize = 6) {
  let size = maxSize;
  while (size > minSize) {
    ctx.font = `700 ${size}px -apple-system, BlinkMacSystemFont, sans-serif`;
    if (ctx.measureText(text).width <= maxWidth) break;
    size -= 0.5;
  }
  return size;
}

// Two-line label for the shooting bars -- a small muted line on top, and a
// bigger line below it (right above the bar) styled by the SAME league-wide
// rank that colours the x-axis label for that segment -- top 2 bold royal
// blue (#1 boxed too), bottom 3 red (league-worst boxed), so the bar and
// its axis label always agree. Which value is "primary" (bold/coloured,
// matching whatever the chart is actually ranked by) vs "secondary" (small,
// muted, just for reference) is passed in, since FT ranks by volume while
// 2PT/3PT rank by %.
function fmShootingPctLabelPlugin(primaryLabels, secondaryLabels, ranks) {
  return {
    id: "fmShootingPctLabels",
    afterDatasetsDraw(chart) {
      const meta = chart.getDatasetMeta(0);
      const ctx = chart.ctx;
      meta.data.forEach((bar, i) => {
        const primaryText = primaryLabels[i];
        const secondaryText = secondaryLabels[i];
        const maxWidth = Math.max(10, bar.width - 4);
        const { color, weight, boxed } = fmRankStyle(ranks[i]);

        ctx.save();
        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";

        const primarySize = fmFitFontSize(ctx, primaryText, maxWidth, 13, 7);
        const secondarySize = fmFitFontSize(ctx, secondaryText, maxWidth, 9, 6);

        // small, muted reference line sitting above the primary line.
        ctx.font = `600 ${secondarySize}px -apple-system, BlinkMacSystemFont, sans-serif`;
        ctx.fillStyle = COLOR.text;
        ctx.fillText(secondaryText, bar.x, bar.y - 4 - (primarySize + 5));

        // the ranked value, styled by rank.
        fmDrawBoxedText(ctx, primaryText, bar.x, bar.y - 4, primarySize, weight, color, boxed);
        ctx.restore();
      });
    },
  };
}

// Colours each x-axis tick royal blue (top 2 in the league for that
// segment) or red (bottom 3), based on this team's rank -- everyone else
// stays the default axis colour.
function fmTickColor(ranks) {
  return (ctx) => {
    const r = ranks[ctx.index];
    if (!r || !r.rank) return COLOR.text;
    if (r.rank <= 2) return ROYAL_BLUE;
    if (r.rank > r.pool - 3) return COLOR.critical;
    return COLOR.text;
  };
}

// Same blue/red thresholds as the axis-tick/bar-label colouring (top 2 =
// royal blue, bottom 3 = red), applied to the AVERAGE rank across all 8
// segments so the reference line reads consistently with everything else
// on the chart.
function fmAvgRankColor(avgRank, pool) {
  if (avgRank <= 2) return ROYAL_BLUE;
  if (avgRank > pool - 3) return COLOR.critical;
  return COLOR.text;
}

// Writes "Avg rank X.X of Y" into the small badge that sits level with the
// card's <h3> title (id = `${canvasId without "#"}-avgrank`), rather than
// drawing it inside the canvas -- one glance right next to the title, no
// extra space taken from the plot area.
function fmAvgRankBadge(canvasId, avgRank, pool) {
  const el = document.getElementById(`${canvasId.replace(/^#/, "")}-avgrank`);
  if (!el) return;
  if (avgRank == null) {
    el.textContent = "";
    el.style.display = "none";
    return;
  }
  el.style.display = "";
  el.textContent = `Avg rank ${avgRank.toFixed(1)} of ${pool}`;
  const c = fmAvgRankColor(avgRank, pool);
  el.style.color = c;
  el.style.borderColor = c;
}

function fmChart(key, canvasId, labels, data, ranks, color, plugin, maxHeadroom = 1.25, topPadding = 16, yMax = null) {
  fmDestroy(key);
  const dataMax = Math.max(1, ...data.filter(v => v != null));

  const validRanks = ranks.filter(r => r && r.rank != null);
  const pool = validRanks.length ? validRanks[0].pool : null;
  const avgRank = validRanks.length ? validRanks.reduce((sum, r) => sum + r.rank, 0) / validRanks.length : null;
  fmAvgRankBadge(canvasId, avgRank, pool);

  fmCharts[key] = new Chart($(canvasId), {
    type: "bar",
    data: { labels, datasets: [{ data, backgroundColor: color, borderRadius: 4 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      layout: { padding: { top: topPadding } },
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { color: fmTickColor(ranks), font: { weight: "700" } } },
        y: {
          beginAtZero: true,
          ...(yMax ? { max: yMax } : { suggestedMax: dataMax * maxHeadroom }),
          grid: { color: COLOR.border },
        },
      },
    },
    plugins: [plugin],
  });
}

// Static bar-fill colour for the 4 counting stats where "more/less is good"
// has an obvious sign (fouls/turnovers = red on offense, fouled/steals =
// green on offense). Defense reframes the same action types as what the
// OPPONENT did, which flips which side benefits -- opponent fouls/turnovers
// are good for us (green), opponent-fouled-us/opponent-steals are bad for
// us (red) -- so the colour has to flip with it, independent of the
// per-segment rank coloring (which already reads correctly either way).
function fmAvgBarColor(key, against) {
  if (key === "fouls" || key === "tov") return against ? COLOR.good : COLOR.critical;
  if (key === "fouled" || key === "stl") return against ? COLOR.critical : COLOR.good;
  return COLOR.s1;
}

// Renders the full 10-chart set into canvases `#fm-<stat><suffix>` -- shared
// by the offense charts (suffix "", against=false) and the defense/
// "opponent stats" charts (suffix "-def", against=true), which differ in
// which endpoint's rows they came from (each already carries correctly-
// flipped rank direction from the backend for defense) and in which way
// the fouls/fouled/tov/stl bar-fill colours point.
function renderFiveMinSet(rows, suffix, against) {
  const labels = rows.map(r => `${r.label}m`);

  // Every average chart's value label is coloured/boxed the same way as the
  // shooting % and the axis ticks -- top 2 bold royal blue (#1 boxed),
  // bottom 3 red (league-worst boxed) -- all driven by the same rank data
  // already used for that chart's axis colouring.
  const avgPlugin = (statKey) => fmBarLabelPlugin(rows.map(r => r[statKey].value.toFixed(1)), rows.map(r => r[statKey]));
  fmChart(`pts${suffix}`, `#fm-pts${suffix}`, labels, rows.map(r => r.pts.value), rows.map(r => r.pts), COLOR.s2, avgPlugin("pts"));
  fmChart(`oreb${suffix}`, `#fm-oreb${suffix}`, labels, rows.map(r => r.oreb.value), rows.map(r => r.oreb), COLOR.s1, avgPlugin("oreb"));
  fmChart(`dreb${suffix}`, `#fm-dreb${suffix}`, labels, rows.map(r => r.dreb.value), rows.map(r => r.dreb), COLOR.s1, avgPlugin("dreb"));
  fmChart(`fouls${suffix}`, `#fm-fouls${suffix}`, labels, rows.map(r => r.fouls.value), rows.map(r => r.fouls), fmAvgBarColor("fouls", against), avgPlugin("fouls"));
  fmChart(`fouled${suffix}`, `#fm-fouled${suffix}`, labels, rows.map(r => r.fouled.value), rows.map(r => r.fouled), fmAvgBarColor("fouled", against), avgPlugin("fouled"));
  fmChart(`tov${suffix}`, `#fm-tov${suffix}`, labels, rows.map(r => r.tov.value), rows.map(r => r.tov), fmAvgBarColor("tov", against), avgPlugin("tov"));
  fmChart(`stl${suffix}`, `#fm-stl${suffix}`, labels, rows.map(r => r.stl.value), rows.map(r => r.stl), fmAvgBarColor("stl", against), avgPlugin("stl"));

  // Shooting: x-axis stays chronological (progression through the game).
  // 2PT/3PT: bar height is shooting %, ranked (and coloured) by %.
  ["fg2", "fg3"].forEach(key => {
    const maLabels = rows.map(r => `${r[key].m}/${r[key].a}`);
    const pctLabels = rows.map(r => r[key].pct === null ? "—" : `${r[key].pct}%`);
    const pctValues = rows.map(r => r[key].pct);
    const ranks = rows.map(r => r[key]);
    fmChart(`${key}${suffix}`, `#fm-${key}${suffix}`, labels, pctValues, ranks, COLOR.s1,
      fmShootingPctLabelPlugin(pctLabels, maLabels, ranks), 1.3, 34, 100);
  });

  // FT: bar height is total free throws ATTEMPTED (not %), ranked (and
  // coloured) by that same attempt volume -- getting to the line more (or,
  // on defense, allowing fewer trips) is a better signal than FT% off a
  // small sample.
  const ftMaLabels = rows.map(r => `${r.ft.m}/${r.ft.a}`);
  const ftPctLabels = rows.map(r => r.ft.pct === null ? "—" : `${r.ft.pct}%`);
  const ftAttempts = rows.map(r => r.ft.a);
  const ftRanks = rows.map(r => r.ft);
  fmChart(`ft${suffix}`, `#fm-ft${suffix}`, labels, ftAttempts, ftRanks, COLOR.s1,
    fmShootingPctLabelPlugin(ftMaLabels, ftPctLabels, ftRanks), 1.3, 34);
}

// Rank -> Strong (#1-3) / Middle of the road (#4-7) / Weak (#8-10) -- the
// stored rank is already oriented so #1 is always "best" for that stat
// (turnovers/fouls already rank fewest-is-best), so this one scale applies
// everywhere without per-stat direction flips.
function fmTier(rank) {
  if (rank == null) return { label: "—", cls: "" };
  if (rank < 4) return { label: "Strong", cls: "tier-strong" };
  if (rank <= 7) return { label: "Middle", cls: "tier-middle" };
  return { label: "Weak", cls: "tier-weak" };
}
function fmTierCell(rank) {
  const t = fmTier(rank);
  return `<td class="num ${t.cls}">${t.label}${rank != null ? ` (${rank})` : ""}</td>`;
}

// A quick per-segment strong/middle/weak read across points, all 3
// shooting splits, turnovers, and fouls -- the "where does this team
// actually win/lose stretches of the game" table. FT is ranked by
// attempts (volume), same convention as its bar chart, not shooting %.
// "Avg Rank" is that segment's own average across all 6 tracked ranks --
// one overall read for the whole row, tiered the same way as each stat.
function renderFiveMinReadTable(rows, tableSel = "#fm-read-table") {
  $(tableSel).innerHTML = `
    <table>
      <thead><tr>
        <th>Segment</th><th class="num">Avg Rank</th><th class="num">Points</th><th class="num">2PT%</th><th class="num">3PT%</th>
        <th class="num">FT Attempted</th><th class="num">Turnovers</th><th class="num">Fouls</th>
      </tr></thead>
      <tbody>
        ${rows.map(r => {
          const ranks = [r.pts.rank, r.fg2.rank, r.fg3.rank, r.ft.rank, r.tov.rank, r.fouls.rank];
          const avgRank = ranks.reduce((sum, v) => sum + v, 0) / ranks.length;
          return `
          <tr>
            <td class="fm-segment-cell">${r.label}m</td>
            ${fmTierCell(Math.round(avgRank * 10) / 10)}
            ${fmTierCell(r.pts.rank)}
            ${fmTierCell(r.fg2.rank)}
            ${fmTierCell(r.fg3.rank)}
            ${fmTierCell(r.ft.rank)}
            ${fmTierCell(r.tov.rank)}
            ${fmTierCell(r.fouls.rank)}
          </tr>`;
        }).join("")}
      </tbody>
    </table>`;
}

async function updateFiveMin() {
  const id = $("#fm-team").value;
  if (!id) return;
  const scope = $("#fm-scope").value;
  const [rows, rowsDef] = await Promise.all([
    fetch(`/api/teams/${id}/five-minute-splits?scope=${scope}`).then(r => r.json()),
    fetch(`/api/teams/${id}/five-minute-splits-against?scope=${scope}`).then(r => r.json()),
  ]);
  renderFiveMinReadTable(rows, "#fm-read-table");
  renderFiveMinReadTable(rowsDef, "#fm-read-table-def");
  renderFiveMinSet(rows, "", false);
  renderFiveMinSet(rowsDef, "-def", true);
}

// ------------------------------------------------------------- line ups --
$("#lu-team").addEventListener("change", updateLineups);

async function loadLineupOptions() {
  if (!teams.length) teams = await (await fetch("/api/teams")).json();
  const sel = $("#lu-team");
  if (!sel.options.length) {
    sel.innerHTML = teams.map(t => `<option value="${t.id}">${t.name}</option>`).join("");
  }
  updateLineups();
}

// A player row inside a lineup card -- no individual stat, just who's in
// the 5 (the card's combined production is what matters here).
function luPlayerRow(p) {
  return `
    <div class="lineup-player-row">
      ${nameCell(playerAvatar(p.photo_url, p.name), p.name)}
    </div>`;
}

// Compact "who" cell shared by the ranking table and (implicitly) the
// cards -- comma-joined names, since a 5-name row doesn't fit a table
// column with full name-cells.
function luNamesCell(players) {
  return players.map(p => p.name).join(", ");
}

async function updateLineups() {
  const id = $("#lu-team").value;
  if (!id) return;
  const el = $("#lu-content");
  el.innerHTML = "<p class='muted'>Loading…</p>";

  const data = await (await fetch(`/api/teams/${id}/lineups`)).json();

  if (!data.lineups.length) {
    el.innerHTML = `<p class="muted">Not enough play-by-play data (starters + substitutions) for this team yet to reconstruct actual on-court lineups.</p>`;
    return;
  }

  const summaryTable = `
    <div class="card lu-depth-chart">
      <h3>Most-used lineups <span class="hint" title="Every distinct 5-man on-court unit this team has actually used, reconstructed from each game's starters and substitution log -- ranked by an estimated possessions-together count (shots attempted + 0.44×FT attempts + turnovers − offensive rebounds, all from this exact combo's own on-court production). The top 3 (highlighted) are broken out in full below.">ⓘ</span></h3>
      <table>
        <thead><tr><th class="num">#</th><th>Lineup</th><th class="num">Games together</th><th class="num">Possessions (est.)</th></tr></thead>
        <tbody>
          ${data.summary.map((s, i) => `
            <tr>
              <td class="num${i < 3 ? " core" : ""}">${i + 1}</td>
              <td>${luNamesCell(s.players)}</td>
              <td class="num">${s.games_together}</td>
              <td class="num">${s.possessions}</td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>`;

  const lineupCards = data.lineups.map(lu => `
    <div class="card lineup-card">
      <h3>${lu.label}<span class="lu-meta">${lu.games_together} games together · ${lu.possessions} poss.</span></h3>
      ${lu.players.map(p => luPlayerRow(p)).join("")}
      ${luStatsBlock(lu.stats)}
    </div>`).join("");

  el.innerHTML = `${summaryTable}<div class="lineup-grid">${lineupCards}</div>`;
}

// The 5-man group's combined per-game production, if these 5 players all
// played together every game -- counting stats are the sum of each
// player's own per-game average (over the team's last 5 games); shooting %
// is derived from the summed makes/attempts, not an average of percentages.
function luStatsBlock(s) {
  if (!s) return "";
  const shoot = (label, cell) => `
    <div class="ls-row"><span class="ls-label">${label}</span><span class="ls-ma">${cell.m}/${cell.a}</span><span class="ls-pct">${cell.pct === null ? "—" : cell.pct + "%"}</span></div>`;
  return `
    <div class="lineup-stats">
      <div class="stat"><div class="v">${s.pts}</div><div class="l">PTS</div></div>
      <div class="stat"><div class="v">${s.reb}</div><div class="l">REB</div></div>
      <div class="stat"><div class="v">${s.ast}</div><div class="l">AST</div></div>
      <div class="stat"><div class="v">${s.stl}</div><div class="l">STL</div></div>
      <div class="stat"><div class="v">${s.blk}</div><div class="l">BLK</div></div>
      <div class="stat"><div class="v">${s.tov}</div><div class="l">TOV</div></div>
      <div class="stat"><div class="v">${s.pf}</div><div class="l">PF</div></div>
    </div>
    <div class="lineup-shooting">
      ${shoot("2PT", s.fg2)}
      ${shoot("3PT", s.fg3)}
      ${shoot("FT", s.ft)}
    </div>`;
}


// -------------------------------------------------------- matchup scout --
$("#mu-team").addEventListener("change", updateMatchup);

async function loadMatchupOptions() {
  if (!teams.length) teams = await (await fetch("/api/teams")).json();
  const teamSel = $("#mu-team");
  if (!teamSel.options.length) {
    teamSel.innerHTML = teams.map(t => `<option value="${t.id}">${t.name}</option>`).join("");
  }
  updateMatchup();
}

// Blue for top-3 league rank, red for bottom-3, plain for the middle --
// same tier boundary as everywhere else in the app.
function muTierClass(rank, pool) {
  if (rank <= 3) return "tier-top";
  if (rank > pool - 3) return "tier-bottom";
  return "";
}

function muStatTile(s, cls) {
  return `
    <div class="${cls} ${muTierClass(s.rank, s.pool)}">
      <div class="mu-stat-label">${s.label}</div>
      <div class="mu-stat-value">${s.value}</div>
      <div class="mu-stat-rank">#${s.rank} of ${s.pool}</div>
    </div>`;
}

// Rank shown inline in a distinct (monospace) font from the value, so it
// reads as metadata rather than part of the number itself.
function muRankSpan(rank, pool) {
  return `<span class="mu-shotclock-rank">#${rank} of ${pool}</span>`;
}
function muClockPctCell(c) {
  return c ? `${c.value}% ${muRankSpan(c.rank, c.pool)}` : "—";
}
function muClockPtsCell(row) {
  if (!row.pts) return "—";
  const pctPart = row.pct_of_total_pts != null ? ` (${row.pct_of_total_pts}%)` : "";
  return `${row.pts.value}${pctPart} ${muRankSpan(row.pts.rank, row.pts.pool)}`;
}

function muShotClockTableHtml(clockData) {
  if (!clockData || !clockData.rows.length) return "";
  return `
    <h3 style="margin-top:22px">Offense by shot clock</h3>
    <table class="mu-shotclock-table">
      <thead><tr><th>Shot clock</th><th class="num">Points</th><th class="num">2PT%</th><th class="num">3PT%</th></tr></thead>
      <tbody>
        ${clockData.rows.map(r => `
          <tr>
            <td>${r.label}</td>
            <td class="num">${muClockPtsCell(r)}</td>
            <td class="num">${muClockPctCell(r.fg2_pct)}</td>
            <td class="num">${muClockPctCell(r.fg3_pct)}</td>
          </tr>`).join("")}
      </tbody>
    </table>`;
}

async function updateMatchup() {
  const teamId = $("#mu-team").value;
  if (!teamId) return;
  const el = $("#mu-content");
  el.innerHTML = "<p class='muted'>Loading…</p>";
  const [data, clockData] = await Promise.all([
    fetch(`/api/teams/${teamId}/top-row`).then(r => r.json()),
    fetch(`/api/teams/${teamId}/shot-clock-offense`).then(r => r.json()),
  ]);

  el.innerHTML = `
    <div class="card">
      <div class="mu-toprow">
        <img class="mu-toprow-logo" src="${data.team.logo_url || ""}" alt="${data.team.name}" onerror="this.remove()">
        <span class="mu-toprow-record">${data.record}</span>
        <span class="mu-toprow-team">${data.team.name} · ${data.gp} games</span>
      </div>
      <div class="mu-stat-row">
        ${data.big.map(s => muStatTile(s, "mu-stat")).join("")}
      </div>
      <div class="mu-stat-row mu-stat-row-end">
        ${data.small.map(s => muStatTile(s, "mu-stat-small")).join("")}
      </div>
      ${muShotClockTableHtml(clockData)}
    </div>`;
}
