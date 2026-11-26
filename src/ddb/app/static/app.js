/* dolla-dolla-bills dashboard.
 * Point-in-time rule: every row carries `k` (when it became public). The "as of"
 * control hides rows with k > as-of, so each view shows only what a model could
 * have known at that moment. Outcome labels appear only with "hindsight labels" on.
 * Works live (fetches /api/...), as a one-file snapshot (window.DDB_SNAPSHOT), or as a
 * published page: core data inline + per-view JSON files under window.DDB_FILES.
 */
(() => {
  "use strict";
  const SNAP = window.DDB_SNAPSHOT || null;
  const FILES = window.DDB_FILES || null;   // base URL of per-view JSON files (published page)
  const fileFor = path => path.slice(1).replace(/[^A-Za-z0-9/_-]/g, "_") + ".json";
  const MIN_DATE = "2010-01-01";
  const state = {
    tab: "month", lab: "monthly", asOf: Date.now(), hindsight: false, context: false, industry: "nuclear", sig: null, candFilter: "",
    stSig: null, stFilter: "", itf: null,
    cik: null, run: null, ddate: null, did: null, exclFilter: "",
  };
  const INDUSTRY_LABEL = {
    tech: "Tech", energy: "Energy", nuclear: "Nuclear", quantum: "Quantum", space: "Space",
    crypto_adj: "Crypto", ev_battery: "EV & batteries", gene_biotech: "Biotech", robotics_ai: "Robotics & AI",
  };
  const SIGNALS = ["development", "bottleneck", "stagnation"];      // fixed slot order 1,2,3

  // ------------------------------------------------------------------ data
  const cache = new Map();
  function get(path) {
    if (!cache.has(path)) {
      cache.set(path, SNAP
        ? (path in SNAP ? Promise.resolve(SNAP[path])
           : FILES ? fetch(FILES + fileFor(path)).then(r => { if (!r.ok) throw new Error("Not included in this snapshot"); return r.json(); })
           : Promise.reject(new Error("Not included in this snapshot")))
        : fetch("/api" + path).then(r => { if (!r.ok) throw new Error(r.status + " " + r.statusText); return r.json(); }));
    }
    return cache.get(path);
  }
  const ms = s => (s ? Date.parse(s) : NaN);
  const known = (rows, key = "k") => (rows || []).filter(r => !r[key] || ms(r[key]) <= state.asOf);
  const validAt = (r, t = state.asOf) => ms(r.valid_from) <= t && (!r.valid_to || ms(r.valid_to) > t);

  // ------------------------------------------------------------------ format
  const nf = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
  function compact(v) {
    if (v == null || isNaN(v)) return "–";
    const a = Math.abs(v);
    if (a >= 1e12) return nf.format(v / 1e12) + "T";
    if (a >= 1e9) return nf.format(v / 1e9) + "B";
    if (a >= 1e6) return nf.format(v / 1e6) + "M";
    if (a >= 1e3) return nf.format(v / 1e3) + "K";
    return nf.format(v);
  }
  const money = v => (v == null || isNaN(v) ? "–" : (v < 0 ? "−$" : "$") + compact(Math.abs(v)));
  const pct = (v, d = 0) => (v == null || isNaN(v) ? "–" : (v * 100).toFixed(d) + "%");
  const day = s => (s ? String(s).slice(0, 10) : "–");
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const series = i => css(`--series-${i + 1}`);
  const statusChip = s => `<span class="chip st-${esc(s)}"><span class="dot"></span>${esc(s)}</span>`;
  const edgarUrl = (cik, acc, doc) => acc ? `https://www.sec.gov/Archives/edgar/data/${cik}/${String(acc).replace(/-/g, "")}/${doc ? encodeURIComponent(doc) : ""}` : null;

  // ------------------------------------------------------------------ charts
  let charts = [];
  function disposeCharts() { charts.forEach(c => c.dispose()); charts = []; }
  window.addEventListener("resize", () => charts.forEach(c => c.resize()));

  function baseOption(extra = {}) {
    const ink2 = css("--text-secondary"), muted = css("--text-muted"), grid = css("--grid"), axis = css("--axis");
    return Object.assign({
      animation: false,
      textStyle: { fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif", color: ink2 },
      grid: { left: 52, right: 16, top: 30, bottom: 28, containLabel: false },
      tooltip: {
        trigger: "axis", backgroundColor: css("--surface-1"), borderColor: css("--border"),
        textStyle: { color: css("--text-primary"), fontSize: 12 }, axisPointer: { lineStyle: { color: axis } },
      },
      xAxis: { type: "time", axisLine: { lineStyle: { color: axis } }, axisLabel: { color: muted, hideOverlap: true },
               splitLine: { show: false } },
      yAxis: { type: "value", axisLabel: { color: muted, formatter: v => compact(v) }, splitLine: { lineStyle: { color: grid } } },
    }, extra);
  }
  function mount(el, option) {
    if (!el) return null;
    const c = echarts.init(el, null, { renderer: "svg" });
    c.setOption(option);
    charts.push(c);
    return c;
  }
  function emptyIf(el, cond, msg = "No data known as of this date") {
    if (cond) { el.innerHTML = `<div class="empty">${msg}</div>`; return true; }
    return false;
  }
  // series: [{name, data:[[t, v], ...], color}]
  function lineChart(el, sers, o = {}) {
    if (emptyIf(el, !sers.some(s => s.data.length))) return;
    // Direct end labels only for 2-4 series whose last values are far enough apart not to collide.
    const lasts = sers.map(s => (s.data.at(-1) || [0, 0])[1]).filter(v => v != null).sort((a, b) => a - b);
    const span = Math.max(...sers.flatMap(s => s.data.map(d => d[1] ?? 0))) - Math.min(0, ...sers.flatMap(s => s.data.map(d => d[1] ?? 0))) || 1;
    const showEnd = sers.length > 1 && sers.length <= 4 && lasts.every((v, i) => i === 0 || (v - lasts[i - 1]) / span > 0.06);
    const opt = baseOption({
      legend: sers.length > 1 ? { top: 0, left: 0, textStyle: { color: css("--text-secondary") }, icon: "roundRect", itemWidth: 10, itemHeight: 10 } : undefined,
      series: sers.map((s, i) => ({
        name: s.name, type: "line", data: s.data, showSymbol: false, step: o.step ? "end" : false,
        lineStyle: { width: 2, color: s.color || series(i) }, itemStyle: { color: s.color || series(i) },
        endLabel: showEnd ? { show: true, formatter: () => s.name, color: css("--text-secondary"), fontSize: 11 } : undefined,
        markLine: s.markLine ? { symbol: "none", silent: true, label: { formatter: s.markLine.label, position: "insideEndTop", color: css("--text-secondary") },
                                 lineStyle: { color: css("--critical"), type: "dashed", width: 1 }, data: [{ yAxis: s.markLine.y }] } : undefined,
      })),
    });
    if (showEnd) opt.grid.right = 90;
    if (o.yFmt) { opt.yAxis.axisLabel.formatter = o.yFmt; opt.tooltip.valueFormatter = o.yFmt; }
    else opt.tooltip.valueFormatter = v => compact(v);
    if (o.yMin != null) opt.yAxis.min = o.yMin;
    if (o.log) opt.yAxis.type = "log";
    mount(el, opt);
  }
  function barChart(el, sers, o = {}) {
    if (emptyIf(el, !sers.some(s => s.data.length))) return;
    const surf = css("--surface-1");
    const opt = baseOption({
      legend: sers.length > 1 ? { top: 0, left: 0, textStyle: { color: css("--text-secondary") }, icon: "roundRect", itemWidth: 10, itemHeight: 10 } : undefined,
      series: sers.map((s, i) => ({
        name: s.name, type: "bar", data: s.data, stack: o.stack ? "s" : undefined, barMaxWidth: 16,
        itemStyle: { color: s.color || series(i), borderRadius: o.stack ? 0 : [4, 4, 0, 0], borderColor: surf, borderWidth: o.stack ? 1 : 0 },
      })),
    });
    opt.tooltip.valueFormatter = o.yFmt || (v => compact(v));
    if (o.yFmt) opt.yAxis.axisLabel.formatter = o.yFmt;
    if (sers.length > 4) opt.grid.top = 52;          // legend wraps to two rows
    if (o.category) { opt.xAxis = { type: "category", data: o.category, axisLabel: { color: css("--text-muted") }, axisLine: { lineStyle: { color: css("--axis") } } }; }
    mount(el, opt);
  }

  // ------------------------------------------------------------------ as-of control
  const range = document.getElementById("asof-range"), dateIn = document.getElementById("asof-date");
  const minMs = Date.parse(MIN_DATE), maxMs = Date.now();
  range.max = Math.round((maxMs - minMs) / 864e5);
  function setAsOf(t, from) {
    state.asOf = Math.min(Math.max(t, minMs), maxMs);
    if (from !== "range") range.value = Math.round((state.asOf - minMs) / 864e5);
    if (from !== "date") dateIn.value = new Date(state.asOf).toISOString().slice(0, 10);
    renderBanner();
  }
  let timer = null;
  const rerender = () => { clearTimeout(timer); timer = setTimeout(render, 160); };
  range.addEventListener("input", () => { setAsOf(minMs + range.value * 864e5, "range"); rerender(); });
  dateIn.addEventListener("change", () => { if (dateIn.value) { setAsOf(Date.parse(dateIn.value + "T23:59:59Z"), "date"); rerender(); } });
  document.getElementById("hindsight").addEventListener("change", e => { state.hindsight = e.target.checked; render(); });
  document.getElementById("context").addEventListener("change", e => { state.context = e.target.checked; render(); });
  document.getElementById("theme").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const dark = cur ? cur === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.setAttribute("data-theme", dark ? "light" : "dark");
    render();
  });
  document.querySelectorAll("nav.tabs button").forEach(b => b.addEventListener("click", () => {
    state.tab = b.dataset.tab;
    document.querySelectorAll("nav.tabs button").forEach(x => x.setAttribute("aria-selected", x === b));
    render();
  }));
  function renderBanner() {
    const d = new Date(state.asOf).toISOString().slice(0, 10);
    document.getElementById("banner").innerHTML =
      `Showing only information that was <strong>public by ${d}</strong>. Move the as-of control to see exactly what a model could see on any date.` +
      (SNAP ? ` <span class="muted">Snapshot of the database taken ${esc(SNAP._built || "")}.</span>` : "");
  }

  // ------------------------------------------------------------------ views
  const view = document.getElementById("view");
  let renderSeq = 0;
  // Each render gets a sequence number; a view whose data arrives after a newer
  // render started must not draw (prevents a slow response overwriting the page).
  const staleCheck = () => { const mine = renderSeq; return () => mine !== renderSeq; };
  async function render() {
    renderSeq++;
    const seq = renderSeq;
    disposeCharts();
    // Show a placeholder if the view takes a moment (avoids showing the previous tab's content).
    const before = view.firstElementChild;   // only show "Loading…" if the view hasn't drawn anything yet
    const loading = setTimeout(() => {
      if (seq === renderSeq && view.firstElementChild === before) view.innerHTML = `<div class="card"><div class="empty">Loading…</div></div>`;
    }, 250);
    try {
      await ({ month: vMonth, today: vToday, lab: vLab, industry: vIndustry, company: vCompany, decisions: vDecisions })[state.tab]();
      clearTimeout(loading);
      await applyContext();
    } catch (e) {
      clearTimeout(loading);
      view.innerHTML = `<div class="card"><div class="empty">Could not load: ${esc(e.message)}</div></div>`;
    }
  }

  async function vOverview(host = view) {
    const stale = staleCheck();
    const o = await get("/overview");
    if (stale()) return;
    const by = Object.fromEntries(o.sources.map(s => [s.table, s]));
    const tiles = [["companies", "companies, incl. failed & delisted"], ["filings", "SEC filings"], ["fundamentals", "financial fact versions"],
                   ["prices", "daily price bars"], ["insider_transactions", "insider trades"], ["politician_trades", "congressional trades"],
                   ["gov_contracts", "federal contract transactions"], ["news_events", "news articles kept"]];
    host.innerHTML = `
      <div class="grid tiles">${tiles.map(([t, l]) => `<div class="card tile"><div class="v">${compact(by[t]?.rows)}</div><div class="l">${l}</div></div>`).join("")}</div>
      <div class="card" style="margin-top:14px"><h2>Data sources</h2>
        <p class="sub">Every row has a public-release timestamp; "first/last" are the earliest and latest of those. Coverage counts are not as-of filtered.</p>
        <div class="scroll"><table><thead><tr><th>Dataset</th><th>Source</th><th class="num">Rows</th><th>First public</th><th>Last public</th></tr></thead>
        <tbody>${o.sources.map(s => `<tr><td>${esc(s.label)}</td><td class="secondary">${esc(s.source)}</td><td class="num">${(s.rows || 0).toLocaleString()}</td><td>${day(s.first)}</td><td>${day(s.last)}</td></tr>`).join("")}</tbody></table></div>
      </div>`;
  }

  async function vUniverse(host = view) {
    const stale = staleCheck();
    const [uni, scr] = await Promise.all([get("/universe"), get("/screens")]);
    if (stale()) return;
    const inds = Object.keys(uni).sort((a, b) => (uni[b].at(-1)?.active || 0) - (uni[a].at(-1)?.active || 0));
    const counts = {};
    scr.counts.forEach(c => { (counts[c.screen] ||= {})[c.status] = c.n; });
    const fin = Object.fromEntries(scr.financial_now.map(r => [r.status, r.n]));
    const ex = scr.excluded.filter(r => !state.exclFilter || `${r.name} ${r.ticker} ${r.reasons} ${r.screen}`.toLowerCase().includes(state.exclFilter.toLowerCase()));
    host.innerHTML = `
      <div class="card"><h2>Companies per industry over time</h2>
        <p class="sub"><b>Active</b> = tagged to the industry and filing with the SEC in the prior 18 months. <b>Tradable</b> = active and passing every investment screen (not Israeli, not weapons, Sharia-compliant business and ratios), using only information known at each month end.</p>
        <div class="grid g3" id="mults"></div></div>
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h2>Screen results (companies listed today)</h2>
          <p class="sub">Current status, not as-of filtered. Ratio screen = most recent quarter.</p>
          <table><thead><tr><th>Screen</th><th class="num">Pass</th><th class="num">Fail</th><th class="num">Review</th><th class="num">Unknown</th></tr></thead><tbody>
          ${Object.entries(counts).map(([s, c]) => `<tr><td>${esc(s)}</td><td class="num">${c.pass || 0}</td><td class="num">${c.fail || 0}</td><td class="num">${c.review || 0}</td><td class="num">–</td></tr>`).join("")}
          <tr><td>sharia_financial (latest quarter)</td><td class="num">${fin.pass || 0}</td><td class="num">${fin.fail || 0}</td><td class="num">${fin.review || 0}</td><td class="num">${fin.unknown || 0}</td></tr>
          </tbody></table>
          <p class="sub" style="margin-top:10px">Ratio limits: debt ≤ ${pct(scr.thresholds.max_debt_to_market_cap)}, cash + interest-bearing securities ≤ ${pct(scr.thresholds.max_cash_and_interest_securities_to_market_cap)} of ${scr.thresholds.market_cap_window_months}-month average market cap, interest income ≤ ${pct(scr.thresholds.max_impermissible_income_share)} of income.</p>
          <dl class="kv">${Object.entries(scr.decisions).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
        </div>
        <div class="card"><h2>Excluded or under review</h2>
          <div class="row"><input type="search" id="exf" placeholder="Filter by name, ticker, reason…" value="${esc(state.exclFilter)}"><span class="muted">${ex.length} companies</span></div>
          <div class="scroll" style="margin-top:8px"><table><thead><tr><th>Ticker</th><th>Company</th><th>Screen</th><th>Status</th><th>Reason</th></tr></thead><tbody>
          ${ex.slice(0, 400).map(r => `<tr class="clickable" data-cik="${r.cik}"><td>${esc(r.ticker)}</td><td>${esc(r.name)}</td><td>${esc(r.screen)}</td><td>${statusChip(r.status)}</td><td class="secondary">${esc(r.reasons)}</td></tr>`).join("")}
          </tbody></table></div></div>
      </div>
      <div class="card" style="margin-top:14px"><h2>Monitored, never traded (${scr.monitored.length})</h2>
        <p class="sub">Weapons-excluded companies kept in training: their contracts, filings and insider/congressional trades inform the model about suppliers, competitors and demand.</p>
        <div class="row">${scr.monitored.map(m => `<span class="chip clickable" data-cik="${m.cik}" title="${esc(m.reasons)}">${esc(m.ticker || m.name)}</span>`).join(" ")}</div></div>`;
    const mults = document.getElementById("mults");
    inds.forEach(ind => {
      const pts = known(uni[ind]);
      const last = pts.at(-1) || {};
      const card = document.createElement("div");
      card.innerHTML = `<h3>${esc(INDUSTRY_LABEL[ind] || ind)}</h3><p class="sub">${last.active ?? 0} active · ${last.tradable ?? 0} tradable</p><div class="chart short"></div>`;
      mults.appendChild(card);
      lineChart(card.querySelector(".chart"), [
        { name: "active", data: pts.map(p => [ms(p.d), p.active]) },
        { name: "tradable", data: pts.map(p => [ms(p.d), p.tradable]) },
      ]);
    });
    document.getElementById("exf").addEventListener("input", e => { state.exclFilter = e.target.value; const pos = e.target.selectionStart; render().then(() => { const f = document.getElementById("exf"); f.focus(); f.setSelectionRange(pos, pos); }); });
    host.querySelectorAll("[data-cik]").forEach(el => el.addEventListener("click", () => openCompany(+el.dataset.cik)));
  }

  async function vIndustry() {
    const stale = staleCheck();
    const [uni, d0] = await Promise.all([get("/universe"), get(`/industry/${state.industry}`).catch(() => null)]);
    const inds = Object.keys(uni);
    if (!inds.includes(state.industry)) state.industry = inds[0];
    const d = d0 && d0.industry === state.industry ? d0 : await get(`/industry/${state.industry}`);
    const info = await sigInfo();
    const month = latestKnown(info.months || [], 0.9 * 864e5);
    const sm = month ? await get(`/signal_month/${month}`).catch(() => null) : null;
    if (stale()) return;
    const byInd = {};
    (sm?.rows || []).forEach(r => { (byInd[r.industry] ||= []).push(r); });
    const med = a => { const v = a.filter(x => x != null).sort((x, y) => x - y); return v.length ? v[Math.floor(v.length / 2)] : null; };
    const summary = inds.map(i => { const r = byInd[i] || []; return { i, n: r.length, buy: r.filter(x => x.verdict === "buy candidate"), avoid: r.filter(x => x.verdict === "avoid").length,
      med: med(r.map(x => x.composite_pct)), trend: med(r.map(x => (x.questions || {}).trend)) }; }).sort((a, b) => (b.med ?? -1) - (a.med ?? -1));
    const here = (byInd[state.industry] || []).slice().sort((a, b) => (b.composite_pct ?? -1) - (a.composite_pct ?? -1));
    const sel = `<select id="indsel">${inds.map(i => `<option value="${i}" ${i === state.industry ? "selected" : ""}>${esc(INDUSTRY_LABEL[i] || i)}</option>`).join("")}</select>`;
    const comm = (d.committees || []).filter(r => validAt(r) && (!r.k || ms(r.k) <= state.asOf));
    view.innerHTML = `
      <div class="card"><h2>Industries at ${day(month)}</h2><p class="sub">Screened companies per industry, how many are buy candidates or red-flagged, and the median composite score (100 = most favorable) and trend score. Click an industry to see its companies.</p>
        <div class="scroll"><table><thead><tr><th>Industry</th><th class="num">Companies</th><th class="num">Buy candidates</th><th class="num">Avoid</th><th class="num">Median score</th><th class="num">Median trend</th><th>Top names</th></tr></thead><tbody>
        ${summary.map(x => `<tr class="clickable ${x.i === state.industry ? "selected" : ""}" data-ind="${x.i}"><td><b>${esc(INDUSTRY_LABEL[x.i] || x.i)}</b></td><td class="num">${x.n}</td><td class="num">${x.buy.length}</td><td class="num">${x.avoid}</td>
          ${pctCell(x.med)}${pctCell(x.trend)}<td class="secondary">${x.buy.slice(0, 5).map(r => esc(r.ticker || "")).join(", ")}</td></tr>`).join("") || `<tr><td colspan="7" class="muted">No month-end ranking known as of this date</td></tr>`}
        </tbody></table></div></div>
      <div class="card" style="margin-top:14px"><div class="row" style="justify-content:space-between"><h2>${esc(INDUSTRY_LABEL[state.industry] || state.industry)}: companies by score</h2>${sel}</div>
        <div class="scroll"><table><thead><tr><th>Ticker</th><th>Company</th><th>Verdict</th><th class="num">Score</th><th>Why</th><th>Red flags</th></tr></thead><tbody>
        ${here.map(r => `<tr class="clickable" data-cik="${r.cik}"><td><b>${esc(r.ticker || "")}</b></td><td>${esc(r.name || "")}</td><td>${verdictChip(r.verdict)}</td>${pctCell(r.composite_pct)}
          <td class="secondary">${(r.drivers || []).map(x => esc(x.label)).join(" · ")}</td><td>${(r.flags || []).map(f => `<span class="chip st-fail"><span class="dot"></span>${esc(f)}</span>`).join(" ")}</td></tr>`).join("") || `<tr><td colspan="6" class="muted">No screened companies in this industry on this date</td></tr>`}
        </tbody></table></div></div>
      <details class="bg" id="indbg"><summary>Background data for this industry: filings language, news, research, attention, insiders, exits, regulation, contracts, Congress (most did not predict returns in our tests)</summary>
      <div class="grid g2">
        <div class="card"><h2>Companies</h2><p class="sub">Active vs tradable after screens</p><div class="chart" id="c-uni"></div></div>
        <div class="card" data-sig="bottleneck_1y"><h2>What filings say</h2><p class="sub">Filings per quarter using bottleneck, development or stagnation language (EDGAR full-text search)</p><div class="chart" id="c-fil"></div></div>
        <div class="card" data-sig="news_volume"><h2>What the news says</h2><p class="sub">Articles per week carrying each signal (GDELT; backfill in progress)</p><div class="chart" id="c-news"></div></div>
        <div class="card" data-sig="news_tone"><h2>News tone</h2><p class="sub">Average article tone per week (negative = critical coverage)</p><div class="chart" id="c-tone"></div></div>
        <div class="card" data-sig="none"><h2>Research activity</h2><p class="sub">arXiv papers per month</p><div class="chart" id="c-arx"></div></div>
        <div class="card" data-sig="wiki_attention"><h2>Public attention</h2><p class="sub">Weekly Wikipedia views of industry topics</p><div class="chart" id="c-wiki"></div></div>
        <div class="card" data-sig="insider_opp_net"><h2>Insider money</h2><p class="sub">Open-market insider buys (up) and sales (down) per month, by disclosure date</p><div class="chart" id="c-ins"></div></div>
        <div class="card"><h2>How companies left</h2><p class="sub">Exits per year, counted once public</p><div class="chart" id="c-exit"></div></div>
        <div class="card" data-sig="none"><h2>Regulation</h2><p class="sub">Federal Register documents per month from agencies shaping this industry</p><div class="chart" id="c-reg"></div></div>
        <div class="card" data-sig="contracts_rev"><h2>Government money</h2><p class="sub">Federal contract obligations per quarter (DoD counted 90 days late, as published)</p><div class="chart" id="c-con"></div></div>
        <div class="card" data-sig="congress_net"><h2>Congressional trades</h2><p class="sub">Disclosed trades in this industry's stocks per quarter</p><div class="chart" id="c-pol"></div></div>
        <div class="card" data-sig="congress_net"><h2>Who oversees it</h2><p class="sub">Committee leaders as of this date</p><div class="scroll"><table><thead><tr><th>Committee</th><th>Member</th><th>Role</th><th>Party</th><th>Since</th></tr></thead><tbody>
          ${comm.map(r => `<tr><td>${esc(r.committee_name)}</td><td>${esc(r.member)}</td><td>${esc(r.title)}</td><td>${esc(r.party)}</td><td>${day(r.valid_from)}</td></tr>`).join("") || `<tr><td colspan="5" class="muted">No data for this date</td></tr>`}
          </tbody></table></div></div>
      </div></details>`;
    document.getElementById("indsel").addEventListener("change", e => { state.industry = e.target.value; render(); });
    view.querySelectorAll("[data-ind]").forEach(el => el.addEventListener("click", () => { state.industry = el.dataset.ind; render(); }));
    clickCompanies(view);
    const bg = document.getElementById("indbg");
    if (state.indBg) bg.open = true;
    bg.addEventListener("toggle", () => { state.indBg = bg.open; charts.forEach(c => c.resize()); });
    const U = known(d.universe);
    lineChart(document.getElementById("c-uni"), [{ name: "active", data: U.map(p => [ms(p.d), p.active]) }, { name: "tradable", data: U.map(p => [ms(p.d), p.tradable]) }]);
    const F = known(d.filing_signals);
    lineChart(document.getElementById("c-fil"), SIGNALS.map((s, i) => ({ name: s, color: series(i), data: F.filter(r => r.signal === s).map(r => [ms(r.q), r.n]) })));
    const N = known(d.news_signals);
    lineChart(document.getElementById("c-news"), SIGNALS.map((s, i) => ({ name: s, color: series(i), data: N.map(r => [ms(r.w), r[s]]) })));
    lineChart(document.getElementById("c-tone"), [{ name: "tone", data: N.map(r => [ms(r.w), r.tone]) }], { yFmt: v => (v ?? 0).toFixed(1) });
    const A = known(d.arxiv), topics = [...new Set(A.map(r => r.topic))];
    lineChart(document.getElementById("c-arx"), topics.map((t, i) => ({ name: t, data: A.filter(r => r.topic === t).map(r => [ms(r.month), r.papers]) })));
    const W = known(d.wiki_topics), tot = {};
    W.forEach(r => { tot[r.article] = (tot[r.article] || 0) + r.views; });
    const arts = Object.keys(tot).sort((a, b) => tot[b] - tot[a]).slice(0, 4);
    lineChart(document.getElementById("c-wiki"), arts.map(a => ({ name: a.replace(/_/g, " "), data: W.filter(r => r.article === a).map(r => [ms(r.w), r.views]) })));
    const I = known(d.insider_net);
    barChart(document.getElementById("c-ins"), [
      { name: "buys", color: css("--div-pos"), data: I.map(r => [ms(r.m), r.buys]) },
      { name: "sales", color: css("--div-neg"), data: I.map(r => [ms(r.m), -r.sales]) }], { stack: true, yFmt: money });
    const E = known(d.exits), years = [...new Set(E.map(r => r.year))].sort();
    const outs = ["bankrupt", "delisted_exchange", "deregistered", "acquired", "went_private"];
    barChart(document.getElementById("c-exit"), outs.map(o => ({ name: o.replace("_", " "), data: years.map(y => (E.find(r => r.year === y && r.outcome === o) || {}).n || 0) })),
      { stack: true, category: years.map(String) });
    const R = known(d.regulatory), types = ["Rule", "Proposed Rule", "Notice", "Presidential Document"];
    lineChart(document.getElementById("c-reg"), types.map(t => ({ name: t, data: R.filter(r => r.type === t).map(r => [ms(r.m), r.n]) })).filter(s => s.data.length));
    const C = known(d.contracts);
    barChart(document.getElementById("c-con"), [{ name: "obligations", data: C.map(r => [ms(r.q), r.amount]) }], { yFmt: money });
    const P = known(d.politicians), ptype = ["buy", "sell", "sell_partial"];
    barChart(document.getElementById("c-pol"), ptype.map(t => ({ name: t.replace("_", " "), data: P.filter(r => r.transaction_type === t).map(r => [ms(r.q), r.n]) })).filter(s => s.data.length), { stack: true });
  }

  function openCompany(cik) {
    state.cik = cik; state.tab = "company";
    document.querySelectorAll("nav.tabs button").forEach(x => x.setAttribute("aria-selected", x.dataset.tab === "company"));
    render();
  }

  async function searchCompanies(q) {
    if (SNAP) {
      const idx = SNAP["/search_index"] || [];
      const s = q.toLowerCase();
      return idx.filter(r => (r.name || "").toLowerCase().includes(s) || (r.ticker || "").toLowerCase() === s).slice(0, 25);
    }
    return (await fetch("/api/search?q=" + encodeURIComponent(q))).json();
  }

  async function vCompany() {
    view.innerHTML = `<div class="card"><div class="row"><input type="search" id="cq" placeholder="Search a company or ticker (e.g. RKLB, Oklo, First Solar)…" style="min-width:320px">
      ${SNAP ? `<span class="muted">Snapshot includes ${(SNAP["/search_index"] || []).length} companies.</span>` : ""}</div><div class="results" id="cres"></div></div><div id="cbody"></div>`;
    const cq = document.getElementById("cq"), cres = document.getElementById("cres");
    let t = null;
    cq.addEventListener("input", () => { clearTimeout(t); t = setTimeout(async () => {
      const rows = cq.value.trim() ? await searchCompanies(cq.value.trim()) : [];
      cres.innerHTML = rows.length ? `<table><tbody>${rows.map(r => `<tr class="clickable" data-cik="${r.cik}"><td><b>${esc(r.ticker || "")}</b></td><td>${esc(r.name)}</td><td class="secondary">${esc(r.industries || "")}</td><td class="muted">${r.listed ? "listed" : "delisted / gone · last filing " + day(r.last_filing)}</td></tr>`).join("")}</tbody></table>` : "";
      cres.querySelectorAll("[data-cik]").forEach(el => el.addEventListener("click", () => { cres.innerHTML = ""; cq.value = ""; state.cik = +el.dataset.cik; renderCompanyBody(); }));
    }, 200); });
    if (!state.cik && SNAP) state.cik = (SNAP["/search_index"] || [])[0]?.cik;
    if (state.cik) await renderCompanyBody();
    else document.getElementById("cbody").innerHTML = `<div class="card" style="margin-top:14px"><div class="empty">Pick a company to see everything known about it on the as-of date.</div></div>`;
  }

  async function renderCompanyBody() {
    const stale = staleCheck();
    const c = await get(`/company/${state.cik}`);
    if (stale()) return;
    disposeCharts();
    const body = document.getElementById("cbody");
    if (!body) return;
    const p = c.profile, t = state.asOf;
    const nameNow = (c.names.filter(n => ms(n.valid_from) <= t).at(-1) || {}).name || p.name;
    const inds = c.industries.filter(r => validAt(r) && (!r.k || ms(r.k) <= t));
    const scr = known(c.screens);
    const fin = known(c.sharia).at(-1);
    const parts = scr.map(s => ({ name: s.screen, status: s.status, why: s.reasons }));
    parts.push({ name: "sharia_ratios", status: fin ? fin.status : "unknown",
      why: fin ? `as of ${day(fin.as_of)}: debt ${pct(fin.debt_ratio)}, cash ${pct(fin.cash_ratio)}, interest ${pct(fin.impermissible_share, 1)}` : "no ratio data known yet" });
    const tradable = parts.every(x => x.status === "pass");
    const labels = c.labels || [];
    body.innerHTML = `
      <div class="card" style="margin-top:14px">
        <div class="row" style="justify-content:space-between"><div><h2 style="font-size:20px">${esc(nameNow)} ${c.primary_ticker ? `<span class="secondary">(${esc(c.primary_ticker)})</span>` : ""}</h2>
          <p class="sub">CIK ${p.cik} · filings ${day(p.first_filing)} → ${day(p.last_filing)} · ${p.is_current_listed ? "listed today" : "no longer listed"}${c.names.length > 1 ? " · formerly " + esc(c.names.filter(n => n.name !== nameNow).map(n => n.name).join(", ")) : ""}</p></div>
          <div class="chip ${tradable ? "st-pass" : "st-fail"}" style="font-size:13px;padding:4px 10px"><span class="dot"></span>${tradable ? "Tradable" : "Not tradable"} as of ${day(new Date(t).toISOString())}</div></div>
        <div class="row" style="margin:6px 0 10px">${inds.map(i => `<span class="chip" title="${esc(i.method)} · ${esc(i.matched || "")}">${esc(INDUSTRY_LABEL[i.industry] || i.industry)} · ${esc(i.sub_industry || "")} <span class="muted">(${esc(i.confidence)})</span></span>`).join("") || `<span class="muted">Not in a tracked industry on this date</span>`}</div>
        <table><thead><tr><th>Screen</th><th>Status</th><th>Why</th></tr></thead><tbody>${parts.map(x => `<tr><td>${esc(x.name)}</td><td>${statusChip(x.status)}</td><td class="secondary">${esc(x.why || "")}</td></tr>`).join("")}</tbody></table>
      </div>
      <div class="card" style="margin-top:14px" id="k-verdict"></div>
      <div class="card" style="margin-top:14px" id="k-short"></div>
      ${state.hindsight ? `<div class="card hindsight" style="margin-top:14px"><h2>Hindsight: how this listing ended</h2><p class="sub">Outcome labels are training targets only. A model never sees these as inputs.</p>
        ${labels.length ? `<table><thead><tr><th>Outcome</th><th>Exit date</th><th>Source</th><th>Confidence</th><th>Details</th></tr></thead><tbody>${labels.map(l => `<tr><td>${esc(l.outcome)}</td><td>${day(l.exit_date)}</td><td>${esc(l.method)}</td><td>${esc(l.confidence)}</td><td class="secondary">${esc(l.consideration || "")} ${l.source_url ? `<a href="${esc(l.source_url)}" target="_blank" rel="noopener">source</a>` : ""}</td></tr>`).join("")}</tbody></table>` : `<div class="empty">No label</div>`}</div>` : ""}
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h2>Price</h2><p class="sub">Weekly close. As traded = the actual price that day; split-adjusted = comparable across splits</p><div class="chart tall" id="k-px"></div></div>
        <div class="card"><h2>Filing events</h2><p class="sub">Distress, dilution and corporate events by public date</p><div class="chart tall" id="k-ev"></div></div>
        <div class="card"><h2>Sharia ratios</h2><p class="sub">Quarterly, from figures known at each date; dashed line = limit</p><div class="grid g3" id="k-sh"></div></div>
        <div class="card"><h2>Financials (as reported at the time)</h2><p class="sub">Revenue (annual), cash + short-term investments, debt, average market cap</p><div class="grid g3" id="k-fin"></div></div>
        <div class="card" data-sig="insider_opp_net"><h2>Insider trades</h2><p class="sub">Open-market buys (up) and sales (down) per month, by disclosure date</p><div class="chart" id="k-ins"></div></div>
        <div class="card" data-sig="news_volume"><h2>News coverage</h2><p class="sub">Articles per week naming the company (GDELT; backfill in progress)</p><div class="chart" id="k-news"></div></div>
        <div class="card" data-sig="wiki_attention"><h2>Public attention</h2><p class="sub">Weekly Wikipedia views</p><div class="chart" id="k-wiki"></div></div>
        <div class="card" data-sig="contracts_rev"><h2>Government contracts</h2><p class="sub">Obligations per quarter, by public date</p><div class="chart" id="k-con"></div></div>
      </div>
      <div class="grid g2" style="margin-top:14px">
        <div class="card" data-sig="insider_opp_net"><h2>Recent insider trades</h2><div class="scroll"><table><thead><tr><th>Traded</th><th>Disclosed</th><th class="num">Lag</th><th>Who</th><th>Type</th><th class="num">Value</th></tr></thead><tbody id="k-inst"></tbody></table></div></div>
        <div class="card" data-sig="congress_net"><h2>Congressional trades</h2><div class="scroll"><table><thead><tr><th>Traded</th><th>Disclosed</th><th>Member</th><th>Type</th><th class="num">Amount</th></tr></thead><tbody id="k-pol"></tbody></table></div></div>
        <div class="card" data-sig="bottleneck_1y"><h2>What its filings said</h2><p class="sub">Bottleneck / development / stagnation phrases</p><div class="scroll"><table><thead><tr><th>Filed</th><th>Form</th><th>Signal</th><th>Phrase</th></tr></thead><tbody id="k-fs"></tbody></table></div></div>
        <div class="card" data-sig="news_tone"><h2>Headlines</h2><div class="scroll"><table><thead><tr><th>Published</th><th>Source</th><th class="num">Tone</th><th>Signals</th></tr></thead><tbody id="k-hl"></tbody></table></div></div>
      </div>`;
    await renderVerdict(c);
    renderShortTerm(c);
    const PX = known(c.prices);
    lineChart(document.getElementById("k-px"), [
      { name: "as traded", data: PX.map(r => [ms(r.w), r.close_raw]) },
      { name: "split-adjusted", data: PX.map(r => [ms(r.w), r.close]) }], { yFmt: v => "$" + compact(v) });
    const EV = known(c.events), cats = [...new Set(EV.map(e => e.event_type))];
    const evEl = document.getElementById("k-ev");
    if (!emptyIf(evEl, !EV.length)) {
      const opt = baseOption({ grid: { left: 170, right: 16, top: 10, bottom: 28 } });
      opt.yAxis = { type: "category", data: cats, axisLabel: { color: css("--text-secondary"), fontSize: 11 }, axisLine: { show: false }, splitLine: { show: true, lineStyle: { color: css("--grid") } } };
      opt.tooltip = { trigger: "item", backgroundColor: css("--surface-1"), borderColor: css("--border"), textStyle: { color: css("--text-primary") },
                      formatter: q => `${esc(q.data[1])}<br>${day(new Date(q.data[0]).toISOString())} · ${esc(q.data[2])}` };
      opt.series = [{ type: "scatter", symbolSize: 8, itemStyle: { color: series(0), borderColor: css("--surface-1"), borderWidth: 2 },
                      data: EV.map(e => [ms(e.k), e.event_type, e.form]) }];
      mount(evEl, opt);
    }
    const SH = known(c.sharia), th = { debt_ratio: 0.3, cash_ratio: 0.3, impermissible_share: 0.05 };
    const shEl = document.getElementById("k-sh");
    [["debt_ratio", "Debt / market cap"], ["cash_ratio", "Cash + securities / market cap"], ["impermissible_share", "Interest / income"]].forEach(([key, lab]) => {
      const d = document.createElement("div"); d.innerHTML = `<h3>${lab}</h3><div class="chart short"></div>`; shEl.appendChild(d);
      lineChart(d.querySelector(".chart"), [{ name: lab, data: SH.filter(r => r[key] != null && r[key] < 5).map(r => [ms(r.as_of), r[key]]), markLine: { y: th[key], label: "limit" } }], { yFmt: v => pct(v), yMin: 0 });
    });
    const finEl = document.getElementById("k-fin");
    [["revenue", "Revenue"], ["cash_securities", "Cash + securities"], ["debt", "Debt"], ["market_cap_avg", "Avg market cap"]].forEach(([key, lab]) => {
      const d = document.createElement("div"); d.innerHTML = `<h3>${lab}</h3><div class="chart short"></div>`; finEl.appendChild(d);
      lineChart(d.querySelector(".chart"), [{ name: lab, data: SH.filter(r => r[key] != null).map(r => [ms(r.as_of), r[key]]) }], { yFmt: money });
    });
    const IN = known(c.insider), byM = {};
    IN.forEach(r => { const m = r.k.slice(0, 7); (byM[m] ||= { b: 0, s: 0 }); if (r.trans_code === "P") byM[m].b += r.value || 0; else byM[m].s += r.value || 0; });
    const months = Object.keys(byM).sort();
    barChart(document.getElementById("k-ins"), [
      { name: "buys", color: css("--div-pos"), data: months.map(m => [ms(m + "-01"), byM[m].b]) },
      { name: "sales", color: css("--div-neg"), data: months.map(m => [ms(m + "-01"), -byM[m].s]) }], { stack: true, yFmt: money });
    const NW = known(c.news_weekly);
    barChart(document.getElementById("k-news"), [{ name: "articles", data: NW.map(r => [ms(r.w), r.n]) }]);
    const WK = known(c.wiki);
    lineChart(document.getElementById("k-wiki"), [{ name: "views", data: WK.map(r => [ms(r.w), r.views]) }]);
    const CO = known(c.contracts);
    barChart(document.getElementById("k-con"), [
      { name: "Defense Dept", data: CO.filter(r => r.dod).map(r => [ms(r.q), r.amount]) },
      { name: "other agencies", data: CO.filter(r => !r.dod).map(r => [ms(r.q), r.amount]) }].filter(s => s.data.length), { stack: true, yFmt: money });
    document.getElementById("k-inst").innerHTML = IN.slice(0, 200).map(r => `<tr><td>${day(r.trans_date)}</td><td>${day(r.k)}</td><td class="num">${r.filing_lag_days ?? "–"}d</td><td>${esc(r.owner_name)}<div class="muted">${esc(r.role || "")}</div></td><td>${r.trans_code === "P" ? "buy" : "sale"}${r.is_10b5_1_plan ? ' <span class="muted">(10b5-1 plan)</span>' : ""}</td><td class="num">${money(r.value)}</td></tr>`).join("") || `<tr><td colspan="6" class="muted">None known</td></tr>`;
    document.getElementById("k-pol").innerHTML = known(c.politicians).slice(0, 200).map(r => `<tr><td>${day(r.trans_date)}</td><td>${day(r.filing_date)} <span class="muted">(${r.disclosure_lag_days ?? "?"}d)</span></td><td>${esc(r.member)} <span class="muted">${esc(r.chamber)}</span></td><td>${esc(r.transaction_type)}</td><td class="num">${money(r.amount_min)}–${money(r.amount_max)}${r.source_url ? ` <a href="${esc(r.source_url)}" target="_blank" rel="noopener">↗</a>` : ""}</td></tr>`).join("") || `<tr><td colspan="5" class="muted">None known</td></tr>`;
    document.getElementById("k-fs").innerHTML = known(c.filing_signals).slice(0, 200).map(r => { const u = edgarUrl(p.cik, r.accession, r.document); return `<tr><td>${day(r.file_date)}</td><td>${esc(r.form)}</td><td>${esc(r.signal)}</td><td>${u ? `<a href="${u}" target="_blank" rel="noopener">${esc(r.phrase)}</a>` : esc(r.phrase)}</td></tr>`; }).join("") || `<tr><td colspan="4" class="muted">None known</td></tr>`;
    document.getElementById("k-hl").innerHTML = known(c.headlines).map(r => `<tr><td>${day(r.published)}</td><td><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.source)}</a></td><td class="num">${r.tone == null ? "–" : r.tone.toFixed(1)}</td><td class="secondary">${esc((r.signals || []).join(", "))}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">None known</td></tr>`;
  }



  // Company: the decision first. Monthly verdict organized by question, then the short-term picture.
  async function renderVerdict(c) {
    const el = document.getElementById("k-verdict");
    const info = await sigInfo();
    const SG = known(c.signals || []);
    const last = SG.at(-1), prev = SG.at(-2);
    if (!last) { el.innerHTML = `<h2>Monthly verdict</h2><div class="empty">Not in the liquid universe at any month-end before this date</div>`; return; }
    const Q = info.questions || {}, used = (info.composite_signals_by_month || {})[last.d] || [];
    const sig = k => (info.signals || []).find(x => x.signal === k) || {};
    const cp = last.pct.composite;
    const tile = q => {
      const ks = used.filter(k => sig(k).question === q);
      const vals = ks.map(k => last.pct[k]).filter(v => v != null);
      const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
      if (Q[q].kind === "risk") {   // percentiles are sign-adjusted: low = risky; red when any is in the worst decile
        const hot = ks.some(k => last.pct[k] != null && last.pct[k] <= 10);
        return `<div class="q ${hot ? "risk-on" : ""}"><div class="ql">${esc(Q[q].label)} <span class="muted">(low = risky)</span></div>
          <div class="qv">${!ks.length ? `<span class="muted" style="font-size:14px">no proven signal</span>` : avg == null ? "–" : Math.round(avg)}</div>
          <div class="sub">${ks.map(k => `${esc(sig(k).label)} <b>${last.pct[k] == null ? "–" : Math.round(last.pct[k])}</b>`).join(" · ")}</div></div>`;
      }
      return `<div class="q"><div class="ql">${esc(Q[q].label)}</div>
        <div class="qv" style="${heat(avg)}; display:inline-block; padding:0 6px; border-radius:6px">${avg == null ? `<span class="muted" style="font-size:14px">no proven signal</span>` : Math.round(avg)}</div>
        <div class="sub">${ks.map(k => `${esc(sig(k).label)} <b>${last.pct[k] == null ? "–" : Math.round(last.pct[k])}</b>`).join(" · ") || "Nothing that answers this has predicted returns yet"}</div></div>`;
    };
    el.innerHTML = `
      <div class="row" style="justify-content:space-between"><div><h2>Monthly verdict · ${day(last.d)}</h2>
        <p class="sub">Percentiles within the liquid universe (100 = most favorable), using only the signals the composite had proven by then. Red flags come from signals that predicted losers.</p></div>
        <div class="row">${verdictChip(last.verdict)}<span class="secondary">score <b>${cp == null ? "–" : Math.round(cp)}</b>${prev && prev.pct.composite != null && cp != null ? ` (was ${Math.round(prev.pct.composite)})` : ""}</span></div></div>
      ${(last.flags || []).length ? `<div class="row" style="margin:4px 0 2px">${last.flags.map(f => `<span class="chip st-fail"><span class="dot"></span>${esc(f)}</span>`).join(" ")}</div>` : ""}
      <div class="qgrid">${Object.keys(Q).map(tile).join("")}</div>
      <h3 style="margin-top:12px">Score over time</h3><div class="chart short" id="k-sigline"></div>`;
    lineChart(document.getElementById("k-sigline"), [{ name: "composite percentile", data: SG.filter(p => p.pct.composite != null).map(p => [ms(p.d), p.pct.composite]) }], { yFmt: v => Math.round(v), yMin: 0 });
  }

  function renderShortTerm(c) {
    const el = document.getElementById("k-short");
    const st = c.short_term || {};
    const D = known(st.daily || []);
    const last = D.at(-1);
    const H = known(st.intraday?.["1Hour"] || st.intraday?.["15Min"] || []);
    if (!last && !H.length) { el.innerHTML = `<h2>Short term</h2><div class="empty">No short-term scores near this date (kept for the last ~2 years; run python -m ddb.features.daily)</div>`; return; }
    el.innerHTML = `
      <div class="row" style="justify-content:space-between"><div><h2>Short term${last ? " · " + day(last.d) : ""}</h2>
        <p class="sub">Next-day composite (enter at the next open) and what happened in the last few days. Daily range = typical one-day move; a stop inside it is mostly noise. Cost = round-trip spread estimate.</p></div>
        ${last ? `<div class="row"><span class="secondary">short-term score <b>${last.composite_pct == null ? "–" : Math.round(last.composite_pct)}</b></span><span class="secondary">daily range <b>${pct(last.atr_pct, 1)}</b></span><span class="secondary">cost <b>${last.cost_bps == null ? "–" : last.cost_bps.toFixed(0) + " bp"}</b></span></div>` : ""}</div>
      ${last && last.alerts.length ? `<div class="row" style="margin-bottom:8px">${last.alerts.map(a => `<span class="chip st-unknown"><span class="dot"></span>${esc(a)}</span>`).join(" ")}</div>` : ""}
      <div class="grid g2"><div><h3>Short-term score, last 6 months</h3><div class="chart short" id="k-stline"></div></div>
        <div><h3>${st.intraday?.["1Hour"] ? "Hourly" : "15-minute"} bars, recent sessions</h3><div class="chart short" id="k-intra"></div></div></div>`;
    lineChart(document.getElementById("k-stline"), [{ name: "short-term percentile", data: D.slice(-126).filter(p => p.composite_pct != null).map(p => [ms(p.d), p.composite_pct]) }], { yFmt: v => Math.round(v), yMin: 0 });
    const iel = document.getElementById("k-intra");
    if (!emptyIf(iel, !H.length, "No intraday bars for this company (python -m ddb.db.build_intraday)")) {
      const opt = baseOption({ grid: { left: 52, right: 16, top: 24, bottom: 40 } });
      opt.xAxis = { type: "category", data: H.map(b => b.ts.slice(5).replace("T", " ")), axisLabel: { color: css("--text-muted"), fontSize: 10, hideOverlap: true } };
      opt.yAxis.scale = true;
      opt.yAxis.axisLabel.formatter = v => "$" + compact(v);
      opt.tooltip.valueFormatter = v => "$" + (v ?? 0).toFixed(2);
      opt.series = [{ type: "line", name: "close", data: H.map(b => b.close), showSymbol: false, lineStyle: { width: 2, color: series(0) }, itemStyle: { color: series(0) } }];
      mount(iel, opt);
    }
  }

  // ------------------------------------------------------------------ validated vs context data
  const GOOD = new Set(["predictive", "moderate"]);
  let sigCache = null;
  async function sigInfo() {
    if (!sigCache) { try { sigCache = await get("/signals"); } catch (e) { sigCache = {}; } }
    return sigCache;
  }
  function statusOf(info, key) { return ((info.signals || []).find(x => x.signal === key) || {}).status || "untested"; }
  // Panels tagged data-sig show only when that signal predicted returns in our tests (or "unvalidated context" is on).
  async function applyContext() {
    const info = await sigInfo();
    const cards = [...view.querySelectorAll("[data-sig]")];
    let hidden = 0;
    cards.forEach(el => {
      const st = el.dataset.sig === "none" ? "untested" : statusOf(info, el.dataset.sig);
      const ok = GOOD.has(st);
      el.hidden = !ok && !state.context;
      if (!ok) hidden += 1;
      if (!ok && state.context && !el.querySelector(".ctx-note")) {
        const n = document.createElement("p"); n.className = "sub ctx-note";
        n.innerHTML = `<span class="chip st-review"><span class="dot"></span>context only</span> this data did not predict returns in our tests (${esc(st)}).`;
        el.insertBefore(n, el.children[1] || null);
      }
    });
    view.querySelector(".ctx-banner")?.remove();
    if (hidden && !state.context) {
      const b = document.createElement("div"); b.className = "banner ctx-banner";
      b.innerHTML = `${hidden} panel${hidden > 1 ? "s" : ""} hidden: their data did not predict returns in our tests. Turn on <strong>unvalidated context</strong> to see them.`;
      view.prepend(b);
    }
    charts.forEach(c => c.resize());
  }

  // ------------------------------------------------------------------ Signals (decision view)
  const heat = v => v == null ? "" : `background: color-mix(in oklab, var(--series-1) ${Math.round(Math.max(0, v - 50) * 1.4)}%, transparent)`;
  const pctCell = v => `<td class="num heat" style="${heat(v)}">${v == null ? "–" : Math.round(v)}</td>`;
  const STATUS_ORDER = ["predictive", "moderate", "weak", "not predictive", "wrong sign", "insufficient data"];
  const statusChip2 = st => `<span class="chip st-${GOOD.has(st) ? "pass" : st === "weak" ? "review" : st === "wrong sign" ? "fail" : "unknown"}"><span class="dot"></span>${esc(st)}</span>`;

  async function vLabMonthly(host) {
    const stale = staleCheck();
    const info = await sigInfo();
    if (stale()) return;
    if (!info.signals) { host.innerHTML = `<div class="card"><div class="empty">Signal validation hasn't been run yet (python -m ddb.features.validate).</div></div>`; return; }
    // stats from months whose results were public by the as-of date
    const statsAsOf = key => {
      const pts = known(info.ic_series[key] || []).filter(p => p.ic != null);
      if (pts.length < 6) return null;
      const x = pts.map(p => p.ic), n = x.length, m = x.reduce((a, b) => a + b, 0) / n;
      const sd = Math.sqrt(x.reduce((a, b) => a + (b - m) ** 2, 0) / n);
      return { ic: m, t: sd > 0 ? m / sd * Math.sqrt(n) : null, hit: x.filter(v => v > 0).length / n, n };
    };
    const months = (info.months || []).filter(d => ms(d) + 0.9 * 864e5 <= state.asOf);
    const month = months.at(-1);
    const used = month ? (info.composite_signals_by_month[month] || []) : [];
    const comp = known(info.composite_series || []);
    const cs = (() => {
      const pts = comp.filter(p => p.ic != null);
      if (!pts.length) return null;
      const x = pts.map(p => p.ic), n = x.length, m = x.reduce((a, b) => a + b, 0) / n;
      const sd = Math.sqrt(x.reduce((a, b) => a + (b - m) ** 2, 0) / n);
      const q5 = comp.map(p => p.q5); const q5m = q5.reduce((a, b) => a + b, 0) / q5.length;
      return { ic: m, t: m / sd * Math.sqrt(n), hit: x.filter(v => v > 0).length / n, q5: q5m, n };
    })();
    const rowsSig = info.signals.slice().sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) || (b.t_stat || 0) - (a.t_stat || 0));
    if (!state.sig) state.sig = (rowsSig.find(r => GOOD.has(r.status)) || rowsSig[0]).signal;
    const sel = info.signals.find(x => x.signal === state.sig) || rowsSig[0];
    const label = k => (info.signals.find(x => x.signal === k) || {}).label || k;
    host.innerHTML = `
      <div class="grid tiles">
        <div class="card tile"><div class="v">${cs ? cs.ic.toFixed(3) : "–"}</div><div class="l">composite rank IC, out-of-sample (${cs ? cs.n : 0} months; t = ${cs && cs.t ? cs.t.toFixed(1) : "–"})</div></div>
        <div class="card tile"><div class="v">${cs ? pct(cs.hit) : "–"}</div><div class="l">months the composite ranked returns correctly</div></div>
        <div class="card tile"><div class="v">${cs ? (cs.q5 >= 0 ? "+" : "") + (cs.q5 * 100).toFixed(2) + "%" : "–"}</div><div class="l">top quintile vs universe, per month, before costs</div></div>
        <div class="card tile"><div class="v">${used.length}</div><div class="l">signals proven before ${day(month)} and in use</div></div>
      </div>
      <div class="card" style="margin-top:14px"><h2>Signal scorecard</h2>
        <p class="sub">Tested on our point-in-time data (${esc(info.universe_rule)}; monthly, next-month returns, failures kept). IC = rank correlation between the signal and next month's return; |t| ≥ 3 is the bar for a new signal. Long leg = top quintile minus universe average, per month: what a long-only account can capture. Stats use only months public by the as-of date; quintile returns are full-sample.</p>
        <div class="scroll" style="max-height:560px"><table><thead><tr><th>Signal</th><th>Role</th><th>Answers</th><th>Our test</th><th class="num">Rank IC</th><th class="num">t</th><th class="num">Hit rate</th><th class="num">Long leg /mo</th><th class="num">IC 2012–19</th><th class="num">IC 2020+</th><th class="num">Turnover</th><th>Published evidence</th></tr></thead><tbody>
        ${rowsSig.map(r => { const a = statsAsOf(r.signal); return `<tr class="clickable ${r.signal === state.sig ? "selected" : ""}" data-sig-row="${r.signal}">
          <td><b>${esc(r.label)}</b><div class="muted">${esc(r.desc || "")}</div></td><td>${esc(r.role || "")}</td><td class="secondary">${esc((info.questions || {})[r.question]?.label || "")}</td><td>${statusChip2(r.status)}</td>
          <td class="num">${a ? a.ic.toFixed(3) : "–"}</td><td class="num">${a && a.t != null ? a.t.toFixed(1) : "–"}</td><td class="num">${a ? pct(a.hit) : "–"}</td>
          <td class="num">${r.long_leg == null ? "–" : (r.long_leg * 100).toFixed(2) + "%"}</td>
          <td class="num">${r.ic_2012_2019 == null ? "–" : r.ic_2012_2019.toFixed(3)}</td><td class="num">${r.ic_2020_on == null ? "–" : r.ic_2020_on.toFixed(3)}</td>
          <td class="num">${r.rank_autocorr == null ? "–" : pct(1 - r.rank_autocorr)}</td><td class="secondary">${esc(r.prior || "")}</td></tr>`; }).join("")}
        </tbody></table></div></div>
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h2>${esc(sel.label)}: does it keep working?</h2><p class="sub">Monthly rank IC and its 12-month average. Above zero = the signal ranked next month's returns correctly.</p><div class="chart tall" id="s-ic"></div></div>
        <div class="card"><h2>${esc(sel.label)}: return by quintile</h2><p class="sub">Average next-month return vs the universe, from least (Q1) to most favorable (Q5)</p><div class="chart tall" id="s-q"></div></div>
        <div class="card"><h2>Composite track record (out-of-sample)</h2><p class="sub">Cumulative excess return of the top quintile, and of top minus bottom quintile, before costs</p><div class="chart tall" id="s-comp"></div></div>
        <div class="card"><h2>How the proven signals overlap</h2><p class="sub">Average monthly rank correlation. Highly correlated signals add little to each other.</p><div class="chart" id="s-corr" style="height:520px"></div></div>
      </div>
      <div class="banner" style="margin-top:14px"><strong>Read with care:</strong> results are before trading costs (about 0.5% per round trip in small caps); delisted companies are only partly covered before 2016; and many of our industries have few companies, so a single month's ranking is noisy. Prefer signals that work in both periods and on the long leg.</div>`;
    host.querySelectorAll("[data-sig-row]").forEach(el => el.addEventListener("click", () => { state.sig = el.dataset.sigRow; render(); }));
    const ic = known(info.ic_series[sel.signal] || []);
    lineChart(document.getElementById("s-ic"), [
      { name: "monthly IC", data: ic.map(p => [ms(p.d), p.ic]), color: css("--axis") },
      { name: "12-month average", data: ic.map(p => [ms(p.d), p.roll12]) }], { yFmt: v => (v ?? 0).toFixed(2) });
    const qs = info.quintiles[sel.signal] || [];
    const qEl = document.getElementById("s-q");
    if (!emptyIf(qEl, !qs.length)) {
      const opt = baseOption();
      opt.xAxis = { type: "category", data: ["Q1", "Q2", "Q3", "Q4", "Q5"], axisLabel: { color: css("--text-muted") }, axisLine: { lineStyle: { color: css("--axis") } } };
      opt.yAxis.axisLabel.formatter = v => (v * 100).toFixed(1) + "%";
      opt.tooltip = { trigger: "axis", backgroundColor: css("--surface-1"), borderColor: css("--border"), textStyle: { color: css("--text-primary") }, valueFormatter: v => (v * 100).toFixed(2) + "%/mo" };
      opt.series = [{ type: "bar", barMaxWidth: 36, data: qs.map(v => ({ value: v, itemStyle: { color: v >= 0 ? css("--div-pos") : css("--div-neg"), borderRadius: v >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4] } })),
                      label: { show: true, position: "top", color: css("--text-secondary"), formatter: q => (q.value * 100).toFixed(2) + "%" } }];
      mount(qEl, opt);
    }
    lineChart(document.getElementById("s-comp"), [
      { name: "top quintile", data: comp.map(p => [ms(p.d), p.cum_q5]) },
      { name: "top − bottom", data: comp.map(p => [ms(p.d), p.cum_spread]) }], { yFmt: v => (v * 100).toFixed(0) + "%" });
    const cEl = document.getElementById("s-corr"), corr = info.correlation || {};
    if (!emptyIf(cEl, !(corr.signals || []).length, "Fewer than two proven signals")) {
      const labs = corr.signals.map(k => label(k));
      const opt = baseOption({ grid: { left: 170, right: 20, top: 10, bottom: 130 } });
      opt.xAxis = { type: "category", data: labs, axisLabel: { color: css("--text-muted"), rotate: 45, fontSize: 10, interval: 0 } };
      opt.yAxis = { type: "category", data: labs, axisLabel: { color: css("--text-secondary"), fontSize: 10, interval: 0 } };
      opt.tooltip = { trigger: "item", backgroundColor: css("--surface-1"), borderColor: css("--border"), textStyle: { color: css("--text-primary") },
                      formatter: q => `${esc(labs[q.data[0]])} × ${esc(labs[q.data[1]])}: ${q.data[2].toFixed(2)}` };
      opt.visualMap = { min: -1, max: 1, show: false, inRange: { color: [css("--div-neg"), css("--div-mid"), css("--div-pos")] } };
      const data = [];
      corr.matrix.forEach((row, i) => row.forEach((v, j) => data.push([j, i, v])));
      opt.series = [{ type: "heatmap", data, label: { show: labs.length <= 8, color: css("--text-primary"), fontSize: 10, formatter: q => q.data[2].toFixed(1) },
                      itemStyle: { borderColor: css("--surface-1"), borderWidth: 2 } }];
      mount(cEl, opt);
    }
  }


  // ------------------------------------------------------------------ shared decision helpers
  const VERDICT = { "buy candidate": "st-pass", avoid: "st-fail", hold: "st-review", weak: "st-unknown" };
  const verdictChip = v => `<span class="chip ${VERDICT[v] || "st-unknown"}"><span class="dot"></span>${esc(v || "–")}</span>`;
  const TONE = { good: "st-pass", bad: "st-fail", info: "st-unknown" };
  const alertChip = a => `<span class="chip ${TONE[a.tone] || "st-unknown"} ${GOOD.has(a.status) ? "" : "unproven"}" title="${esc(GOOD.has(a.status)
      ? `This data point predicted returns in our tests (${a.status})${a.pays ? " and paid after costs" : ", but not after costs"}`
      : `Not proven in our tests (${a.status || "untested"}): context only`)}"><span class="dot"></span>${esc(a.text)}</span>`;
  const signedPct = (v, d = 1) => (v == null || isNaN(v) ? "–" : (v >= 0 ? "+" : "") + (v * 100).toFixed(d) + "%");
  const bp = v => (v == null || isNaN(v) ? "–" : (v >= 0 ? "+" : "") + (v * 1e4).toFixed(1) + " bp");
  const latestKnown = (dates, lagMs) => dates.filter(d => ms(d) + lagMs <= state.asOf).at(-1);
  // a filter box that re-renders its view and keeps the cursor
  function bindFilter(id, key, fn) {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("input", e => { state[key] = e.target.value; const pos = e.target.selectionStart;
      fn().then(() => { const f = document.getElementById(id); if (f) { f.focus(); f.setSelectionRange(pos, pos); } }); });
  }
  const clickCompanies = root => root.querySelectorAll("[data-cik]").forEach(el => el.addEventListener("click", () => openCompany(+el.dataset.cik)));

  // ------------------------------------------------------------------ This month (decision view)
  async function vMonth() {
    const stale = staleCheck();
    const info = await sigInfo();
    if (stale()) return;
    if (!info.signals) { view.innerHTML = `<div class="card"><div class="empty">Signals haven't been built yet: python -m ddb.features.panel, then python -m ddb.features.validate.</div></div>`; return; }
    const month = latestKnown(info.months || [], 0.9 * 864e5);
    if (!month) { view.innerHTML = `<div class="card"><div class="empty">No month-end ranking known as of this date.</div></div>`; return; }
    const m = await get(`/signal_month/${month}`);
    if (stale()) return;
    const Q = m.questions || info.questions || {};
    const goodQ = Object.keys(Q).filter(q => Q[q].kind === "good");
    const riskQ = Object.keys(Q).filter(q => Q[q].kind === "risk");
    const rows = m.rows || [];
    const buys = rows.filter(r => r.verdict === "buy candidate");
    const avoid = rows.filter(r => r.verdict === "avoid").sort((a, b) => (b.new_flags || []).length - (a.new_flags || []).length || (b.flags || []).length - (a.flags || []).length);
    const ch = m.changes || {};
    const lab = k => (info.signals.find(x => x.signal === k) || {}).label || k;
    const qSigs = q => (m.question_signals || {})[q] || [];
    const comp = known(info.composite_series || []);
    const q5m = comp.length ? comp.reduce((a, p) => a + p.q5, 0) / comp.length : null;
    const why = r => (r.drivers || []).map(d => esc(d.label)).join(" · ") || `<span class="muted">no single standout</span>`;
    const filt = rows.filter(r => !state.candFilter || `${r.ticker} ${r.name} ${r.industry} ${r.verdict}`.toLowerCase().includes(state.candFilter.toLowerCase()));
    const qCell = (r, q) => { const v = (r.questions || {})[q]; return `<td class="num heat" style="${heat(v)}" title="${esc(Q[q].label)}${qSigs(q).length ? "" : " (no proven signal answers this yet)"}">${v == null ? "–" : Math.round(v)}</td>`; };
    const riskCell = r => `<td>${(r.flags || []).map(f => `<span class="chip st-fail"><span class="dot"></span>${esc(f)}${(r.new_flags || []).includes(f) ? " <b>new</b>" : ""}</span>`).join(" ") || `<span class="muted">none</span>`}</td>`;
    view.innerHTML = `
      <div class="grid tiles">
        <div class="card tile"><div class="v">${buys.length}</div><div class="l">buy candidates: pass every screen, top 20% on the composite, no red flags</div></div>
        <div class="card tile"><div class="v">${avoid.length}</div><div class="l">to avoid: red flags from signals that predicted losers</div></div>
        <div class="card tile"><div class="v">+${(ch.entered || []).length} / −${(ch.left || []).length}</div><div class="l">entered / left the top 20% since ${day(ch.prev_month)}</div></div>
        <div class="card tile"><div class="v">${q5m == null ? "–" : signedPct(q5m, 2)}</div><div class="l">top 20% vs the average name per month in past tests (out-of-sample, before costs)</div></div>
      </div>
      <div class="banner" style="margin-top:14px">Month-end <strong>${day(month)}</strong>: ${m.tradable_n} companies pass the investment screens (of ${m.universe_n} liquid names). The composite uses ${m.used.length} signals that predicted returns on earlier data. Signals are grouped by the question they answer: ${goodQ.map(q => `<strong>${esc(Q[q].label)}</strong> (${qSigs(q).map(lab).map(esc).join(", ") || "nothing proven yet"})`).join("; ")}. Red flags answer ${riskQ.map(q => `<strong>${esc(Q[q].label)}</strong>`).join(" and ")}.</div>
      <div class="grid g2">
        <div class="card"><h2>Buy candidates</h2><p class="sub">Ranked by the composite. "Why" lists the signals pushing each name up the most.</p>
          <div class="scroll"><table><thead><tr><th>Ticker</th><th>Company</th><th class="num">Score</th><th>Why</th></tr></thead><tbody>
          ${buys.slice(0, 40).map(r => `<tr class="clickable" data-cik="${r.cik}"><td><b>${esc(r.ticker || "")}</b></td><td>${esc(r.name || "")}<div class="muted">${esc(INDUSTRY_LABEL[r.industry] || r.industry || "")}</div></td><td class="num heat" style="${heat(r.composite_pct)}">${Math.round(r.composite_pct)}</td><td class="secondary">${why(r)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">None this month</td></tr>`}
          </tbody></table></div></div>
        <div class="card"><h2>Avoid</h2><p class="sub">Worst 10% on a signal that predicted losers (5% for distress filings). Most of the measured edge comes from staying out of these.</p>
          <div class="scroll"><table><thead><tr><th>Ticker</th><th>Company</th><th>Red flags</th><th class="num">Score</th></tr></thead><tbody>
          ${avoid.slice(0, 60).map(r => `<tr class="clickable" data-cik="${r.cik}"><td><b>${esc(r.ticker || "")}</b></td><td>${esc(r.name || "")}</td>${riskCell(r)}<td class="num">${r.composite_pct == null ? "–" : Math.round(r.composite_pct)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">No red flags this month</td></tr>`}
          </tbody></table></div></div>
      </div>
      <div class="card" style="margin-top:14px"><h2>What changed since ${day(ch.prev_month)}</h2><p class="sub">The names to act on this month.</p>
        <div class="grid g3">
          <div><h3>Entered the top 20%</h3><table><tbody>${(ch.entered || []).map(r => `<tr class="clickable" data-cik="${r.cik}"><td><b>${esc(r.ticker || "")}</b></td><td class="num">${Math.round(r.prev_pct ?? 0)} → ${Math.round(r.composite_pct)}</td><td class="secondary">${why(r)}</td></tr>`).join("") || `<tr><td class="muted">None</td></tr>`}</tbody></table></div>
          <div><h3>Left the top 20%</h3><table><tbody>${(ch.left || []).map(r => `<tr class="clickable" data-cik="${r.cik}"><td><b>${esc(r.ticker || "")}</b></td><td class="num">${Math.round(r.prev_pct ?? 0)} → ${r.composite_pct == null ? "–" : Math.round(r.composite_pct)}</td><td class="secondary">${esc(r.why)}</td></tr>`).join("") || `<tr><td class="muted">None</td></tr>`}</tbody></table></div>
          <div><h3>New red flags</h3><table><tbody>${(ch.new_flags || []).map(r => `<tr class="clickable" data-cik="${r.cik}"><td><b>${esc(r.ticker || "")}</b></td><td>${r.new_flags.map(f => `<span class="chip st-fail"><span class="dot"></span>${esc(f)}</span>`).join(" ")}</td></tr>`).join("") || `<tr><td class="muted">None</td></tr>`}</tbody></table></div>
        </div></div>
      <div class="card" style="margin-top:14px">
        <div class="row" style="justify-content:space-between"><div><h2>Every screened company</h2>
          <p class="sub">Question columns are the average percentile (100 = most favorable) of that question's proven signals; "–" means no proven signal answers it yet. Click a company for the full picture.</p></div>
          <input type="search" id="cf" placeholder="Filter ticker, name, industry, verdict…" value="${esc(state.candFilter)}"></div>
        <div class="scroll" style="max-height:560px"><table><thead><tr><th>#</th><th>Ticker</th><th>Company</th><th>Verdict</th><th class="num">Score</th>
          ${goodQ.map(q => `<th class="num" title="${esc(Q[q].label)}">${esc(Q[q].short || q)}</th>`).join("")}<th>Red flags</th><th>Change</th><th class="num">Price</th><th class="num">$ volume/day</th></tr></thead><tbody>
          ${filt.slice(0, 250).map((r, i) => `<tr class="clickable" data-cik="${r.cik}"><td class="muted">${i + 1}</td><td><b>${esc(r.ticker || "")}</b></td><td>${esc(r.name || "")}<div class="muted">${esc(INDUSTRY_LABEL[r.industry] || r.industry || "")}</div></td>
            <td>${verdictChip(r.verdict)}</td>${pctCell(r.composite_pct)}${goodQ.map(q => qCell(r, q)).join("")}${riskCell(r)}
            <td class="secondary">${esc(r.change && r.change !== "new in universe" ? r.change : "")}</td>
            <td class="num">$${r.price == null ? "–" : r.price.toFixed(2)}</td><td class="num">${money(r.dollar_vol)}</td></tr>`).join("") || `<tr><td colspan="${9 + goodQ.length}" class="muted">No companies</td></tr>`}
          </tbody></table></div></div>
      <div class="banner" style="margin-top:14px"><strong>Read with care:</strong> results are before trading costs (about 0.5% per round trip in small caps); delisted companies are only partly covered before 2016; small industries make a single month's ranking noisy. How each signal was tested is in <em>Model lab</em>.</div>`;
    bindFilter("cf", "candFilter", vMonth);
    clickCompanies(view);
  }

  // ------------------------------------------------------------------ Today (short-term decision view)
  let stCache = null;
  async function stInfo() {
    if (!stCache) { try { stCache = await get("/short_term"); } catch (e) { stCache = {}; } }
    return stCache;
  }
  async function vToday() {
    const stale = staleCheck();
    const st = await stInfo();
    if (stale()) return;
    const D = st.daily || {};
    if (!D.signals) { view.innerHTML = `<div class="card"><div class="empty">Short-term data points haven't been built yet: python -m ddb.features.daily</div></div>`; return; }
    const dayStr = latestKnown(D.days || [], 21.5 * 36e5);
    if (!dayStr) { view.innerHTML = `<div class="card"><div class="empty">No trading day known as of this date (short-term scores are kept for the last ~2 years).</div></div>`; return; }
    const t = await get(`/short_term_day/${dayStr}`);
    if (stale()) return;
    const prim = D.primary_horizon, comp = (D.composite || {})[prim] || {};
    const sigs = D.signals || [];
    const paying = sigs.filter(x => GOOD.has(x.status) && x.pays_after_costs);
    const rows = t.rows || [];
    const setups = rows.filter(r => !r.avoid && (r.composite_pct ?? 0) >= 80);
    const alerts = rows.filter(r => (r.alerts || []).length).sort((a, b) => b.alerts.length - a.alerts.length);
    const costs = rows.map(r => r.cost_bps).filter(v => v != null).sort((a, b) => a - b);
    const medCost = costs.length ? costs[Math.floor(costs.length / 2)] : null;
    const mono = r => r.monthly ? `${r.monthly.flags?.length ? `<span class="chip st-fail"><span class="dot"></span>${esc(r.monthly.flags[0])}</span>` : r.monthly.pct == null ? "–" : Math.round(r.monthly.pct)}` : `<span class="muted">–</span>`;
    const filt = rows.filter(r => !state.stFilter || `${r.ticker} ${r.name} ${r.industry}`.toLowerCase().includes(state.stFilter.toLowerCase()));
    const v = (r, k) => (r.values || {})[k];
    const I = st.intraday || {};
    const tfs = Object.keys(I);
    view.innerHTML = `
      <div class="banner"><strong>Short-term trading reality check.</strong> Short-horizon edges are small and trading costs are not: a round trip costs about <strong>${medCost == null ? "–" : medCost.toFixed(0) + " bp"}</strong> for the median name here. A data point only counts if it paid <em>after</em> those costs in our tests. In a cash account each sale settles the next trading day (T+1), so the full balance can be traded about once a day without a good-faith violation.</div>
      <div class="grid tiles">
        <div class="card tile"><div class="v">${bp(comp.edge_net)}</div><div class="l">short-term composite: top 20% vs the average name per ${esc(prim === "fwd_1d" ? "day" : prim)}, after costs (out-of-sample)</div></div>
        <div class="card tile"><div class="v">${paying.length} / ${sigs.length}</div><div class="l">daily data points that predicted returns and paid after costs</div></div>
        <div class="card tile"><div class="v">${setups.length}</div><div class="l">setups for the next open (top 20%, no bad alert, no monthly red flag)</div></div>
        <div class="card tile"><div class="v">${alerts.length}</div><div class="l">names with an alert on ${day(t.day)}</div></div>
      </div>
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h2>Setups for the next open · ${day(t.day)}</h2>
          ${comp.pays_after_costs && GOOD.has(comp.status) ? "" : `<div class="banner" style="border-color:var(--critical);margin:6px 0 8px"><strong>Not a trade list yet.</strong> In our out-of-sample tests the short-term composite ${GOOD.has(comp.status) ? `ranked next-day returns but lost ${bp(comp.edge_net)} per trade after costs` : `did not predict next-day returns (${esc(comp.status || "untested")})`}. Treat these as a ranking to watch, not as entries.</div>`}
          <p class="sub">Ranked by the short-term composite (enter at the next day's open). Daily range = typical move in a day: a stop closer than that is usually hit by noise. Monthly = the slower model's score, or its red flag.</p>
          <div class="scroll"><table><thead><tr><th>Ticker</th><th class="num">Short-term</th><th class="num">Monthly</th><th>Alerts</th><th class="num">Daily range</th><th class="num">Cost</th></tr></thead><tbody>
          ${setups.slice(0, 40).map(r => `<tr class="clickable" data-cik="${r.cik}"><td><b>${esc(r.ticker || "")}</b><div class="muted">${esc(r.name || "")}</div></td><td class="num heat" style="${heat(r.composite_pct)}">${Math.round(r.composite_pct)}</td><td class="num">${mono(r)}</td><td>${(r.alerts || []).map(alertChip).join(" ")}</td><td class="num">${pct(r.atr_pct, 1)}</td><td class="num">${r.cost_bps == null ? "–" : r.cost_bps.toFixed(0) + " bp"}</td></tr>`).join("") || `<tr><td colspan="6" class="muted">No setups: no short-term data point is proven yet, or every top name has a red flag</td></tr>`}
          </tbody></table></div></div>
        <div class="card"><h2>Alerts · ${day(t.day)}</h2><p class="sub">What happened to each name in the last ${D.fresh_days || 5} trading days. Faded chips are context: that data point did not predict returns in our tests.</p>
          <div class="scroll"><table><thead><tr><th>Ticker</th><th>Alerts</th><th class="num">Short-term</th><th class="num">Monthly</th></tr></thead><tbody>
          ${alerts.slice(0, 80).map(r => `<tr class="clickable" data-cik="${r.cik}"><td><b>${esc(r.ticker || "")}</b></td><td>${r.alerts.map(alertChip).join(" ")}</td><td class="num">${r.composite_pct == null ? "–" : Math.round(r.composite_pct)}</td><td class="num">${mono(r)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">No alerts</td></tr>`}
          </tbody></table></div></div>
      </div>
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h2>Which daily data points pay after costs</h2><p class="sub">Next-day and 5-day tests on our universe (enter at the next open). Edge = top 20% minus the average name, minus the round-trip cost; for avoid signals, how far the flagged names lag (avoiding costs nothing). Full detail in <em>Model lab</em>.</p>
          <div class="scroll"><table><thead><tr><th>Data point</th><th>Our test</th>${Object.keys(D.horizons || {}).map(h => `<th class="num">Edge ${esc(h.replace("fwd_", ""))}</th>`).join("")}<th class="num">Top-20% turnover</th></tr></thead><tbody>
          ${sigs.slice().sort((a, b) => (b.edge_net ?? -9) - (a.edge_net ?? -9)).map(x => `<tr><td><b>${esc(x.label)}</b><div class="muted">${esc(x.role)} · ${esc(x.prior || "")}</div></td><td>${statusChip2(x.status)}</td>
            ${Object.keys(D.horizons || {}).map(h => { const e = (x.horizons || {})[h]?.edge_net; return `<td class="num ${e > 0 && GOOD.has((x.horizons || {})[h]?.status) ? "check-ok" : ""}">${bp(e)}</td>`; }).join("")}
            <td class="num">${x.turnover == null ? "–" : pct(x.turnover)}</td></tr>`).join("")}
          </tbody></table></div></div>
        <div class="card"><h2>Intraday (minute and hour bars)</h2>
          ${tfs.length ? `<p class="sub">Tested on ${tfs.map(esc).join(", ")} bars: enter at the next bar's open, out by the close. Best hour = when during the day the data point worked best.</p>
          <div class="row" style="margin-bottom:8px">${tfs.map(tf => `<button class="iconbtn ${tf === (state.itf || tfs[0]) ? "on" : ""}" data-itf="${tf}">${esc(tf)}</button>`).join("")}</div>
          ${(() => { const tf = tfs.includes(state.itf) ? state.itf : tfs[0]; const iv = I[tf]; const ph = iv.primary_horizon; return `<div class="scroll"><table><thead><tr><th>Data point</th><th>Our test</th><th class="num">t</th><th class="num">Edge after costs</th><th>Best time</th></tr></thead><tbody>
            ${(iv.signals || []).slice().sort((a, b) => (b.t_stat ?? -99) - (a.t_stat ?? -99)).map(x => { const bt = Object.entries(x.by_time || {}).sort((a, b) => b[1] - a[1])[0];
              return `<tr><td><b>${esc(x.label)}</b><div class="muted">${esc(x.desc || "")}</div></td><td>${statusChip2(x.status)}</td><td class="num">${x.t_stat == null ? "–" : x.t_stat.toFixed(1)}</td><td class="num">${bp(x.horizons?.[ph]?.edge_net)}</td><td class="secondary">${bt ? `${esc(bt[0])} (IC ${bt[1].toFixed(3)})` : "–"}</td></tr>`; }).join("")}
            </tbody></table></div><p class="sub" style="margin-top:6px">Composite (${esc(ph)}): ${statusChip2(iv.composite?.[ph]?.status || "insufficient data")} edge after costs ${bp(iv.composite?.[ph]?.edge_net)} per trade · ${esc(iv.universe_rule || "")}</p>`; })()}`
          : `<div class="empty">No intraday bars yet. Download 1-minute bars (free Alpaca key): <code>python -m ddb.db.build_intraday --max-symbols 100</code>, then test them: <code>python -m ddb.features.intraday</code>.</div>`}
        </div>
      </div>
      <div class="card" style="margin-top:14px">
        <div class="row" style="justify-content:space-between"><div><h2>Every screened name · ${day(t.day)}</h2><p class="sub">${t.tradable_n} names pass the investment screens (of ${t.universe_n} liquid names in tracked industries).</p></div>
          <input type="search" id="sf" placeholder="Filter ticker, name, industry…" value="${esc(state.stFilter)}"></div>
        <div class="scroll" style="max-height:520px"><table><thead><tr><th>Ticker</th><th class="num">Short-term</th><th class="num">Today</th><th class="num">5 days</th><th class="num">Gap</th><th class="num">Volume ×</th><th class="num">Close in range</th><th class="num">Daily range</th><th>Alerts</th></tr></thead><tbody>
          ${filt.slice(0, 300).map(r => `<tr class="clickable" data-cik="${r.cik}"><td><b>${esc(r.ticker || "")}</b><div class="muted">${esc(r.name || "")}</div></td>${pctCell(r.composite_pct)}
            <td class="num">${signedPct(v(r, "ret_1d"))}</td><td class="num">${signedPct(v(r, "ret_5d"))}</td><td class="num">${signedPct(v(r, "gap"))}</td>
            <td class="num">${v(r, "rel_volume") == null ? "–" : v(r, "rel_volume").toFixed(1)}</td><td class="num">${pct(v(r, "close_loc"))}</td><td class="num">${pct(r.atr_pct, 1)}</td>
            <td>${(r.alerts || []).map(alertChip).join(" ")}</td></tr>`).join("") || `<tr><td colspan="9" class="muted">No names</td></tr>`}
          </tbody></table></div></div>`;
    bindFilter("sf", "stFilter", vToday);
    view.querySelectorAll("[data-itf]").forEach(b => b.addEventListener("click", () => { state.itf = b.dataset.itf; render(); }));
    clickCompanies(view);
  }

  // ------------------------------------------------------------------ Model lab
  const LAB = [["monthly", "Monthly signals"], ["short", "Daily short-term"], ["intraday", "Intraday"], ["universe", "Universe & screens"], ["sources", "Data sources"]];
  async function vLab() {
    view.innerHTML = `<div class="row seg" style="margin-bottom:12px">${LAB.map(([k, l]) => `<button class="iconbtn ${k === state.lab ? "on" : ""}" data-lab="${k}">${l}</button>`).join("")}</div><div id="labbody"></div>`;
    view.querySelectorAll("[data-lab]").forEach(b => b.addEventListener("click", () => { state.lab = b.dataset.lab; render(); }));
    const host = document.getElementById("labbody");
    const fn = { monthly: vLabMonthly, short: vLabShort, intraday: vLabIntraday, universe: vUniverse, sources: vOverview }[state.lab] || vLabMonthly;
    try { await fn(host); }   // keep the lab's sub-navigation if one panel fails
    catch (e) { host.innerHTML = `<div class="card"><div class="empty">Could not load: ${esc(e.message)}</div></div>`; }
  }

  function scoreTable(sigs, horizons, selKey, attr) {
    const hs = Object.keys(horizons || {});
    return `<div class="scroll" style="max-height:560px"><table><thead><tr><th>Data point</th><th>Role</th><th>Our test</th><th class="num">Rank IC</th><th class="num">t</th><th class="num">Hit rate</th>
      ${hs.map(h => `<th class="num" title="top 20% minus average, before costs">Long leg ${esc(h.replace("fwd_", ""))}</th><th class="num">Cost</th><th class="num" title="after costs; avoid signals: how far flagged names lag">Edge ${esc(h.replace("fwd_", ""))}</th>`).join("")}
      <th class="num">1st / 2nd half IC</th><th>Published evidence</th></tr></thead><tbody>
      ${sigs.map(r => { const p = (r.horizons || {})[hs[0]] || {}; return `<tr class="clickable ${r.signal === selKey ? "selected" : ""}" ${attr}="${r.signal}">
        <td><b>${esc(r.label)}</b><div class="muted">${esc(r.desc || "")}</div></td><td>${esc(r.role || "")}</td><td>${statusChip2(r.status)}</td>
        <td class="num">${p.ic_mean == null ? "–" : p.ic_mean.toFixed(3)}</td><td class="num">${p.t_stat == null ? "–" : p.t_stat.toFixed(1)}</td><td class="num">${pct(p.hit_rate)}</td>
        ${hs.map(h => { const x = (r.horizons || {})[h] || {}; return `<td class="num">${bp(x.long_leg)}</td><td class="num">${x.cost == null ? "–" : (x.cost * 1e4).toFixed(0) + " bp"}</td><td class="num ${x.pays_after_costs && GOOD.has(x.status) ? "check-ok" : ""}">${bp(x.edge_net)}</td>`; }).join("")}
        <td class="num">${p.ic_first_half == null ? "–" : p.ic_first_half.toFixed(3)} / ${p.ic_second_half == null ? "–" : p.ic_second_half.toFixed(3)}</td><td class="secondary">${esc(r.prior || "")}</td></tr>`; }).join("")}
      </tbody></table></div>`;
  }
  const bySignalStrength = a => a.slice().sort((x, y) => STATUS_ORDER.indexOf(x.status) - STATUS_ORDER.indexOf(y.status) || (y.t_stat || 0) - (x.t_stat || 0));

  async function vLabShort(host) {
    const stale = staleCheck();
    const st = await stInfo();
    if (stale()) return;
    const D = st.daily || {};
    if (!D.signals) { host.innerHTML = `<div class="card"><div class="empty">Run python -m ddb.features.daily first.</div></div>`; return; }
    const rows = bySignalStrength(D.signals);
    if (!state.stSig || !rows.find(r => r.signal === state.stSig)) state.stSig = rows[0].signal;
    const sel = rows.find(r => r.signal === state.stSig);
    const hs = Object.keys(D.horizons || {});
    host.innerHTML = `
      <div class="grid tiles">${hs.map(h => { const c = (D.composite || {})[h] || {}; return `
        <div class="card tile"><div class="v">${bp(c.edge_net)}</div><div class="l">composite edge per ${esc(h.replace("fwd_", ""))} trade after costs (IC ${c.ic_mean == null ? "–" : c.ic_mean.toFixed(3)}, t ${c.t_stat == null ? "–" : c.t_stat.toFixed(1)}, ${c.days || 0} days)</div></div>`; }).join("")}
      </div>
      <div class="card" style="margin-top:14px"><h2>Daily data points</h2>
        <p class="sub">${esc(D.universe_rule || "")}. IC = rank correlation with the forward return, averaged per day; t uses Newey-West for overlapping 5-day windows; |t| ≥ 3 and a positive IC in both halves of the sample = predictive. Cost = average round-trip spread of the top 20% (sim.yaml tiers, wider at the open).</p>
        ${scoreTable(rows, D.horizons, state.stSig, "data-st-row")}</div>
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h2>${esc(sel.label)}: does it keep working?</h2><p class="sub">Average daily IC per month, ${esc(hs[0])}</p><div class="chart tall" id="ls-ic"></div></div>
        <div class="card"><h2>${esc(sel.label)}: return by quintile (${esc(hs[0])})</h2><p class="sub">Average return vs the average name, from least (Q1) to most favorable (Q5), before costs; the dashed line is the round-trip cost.</p><div class="chart tall" id="ls-q"></div></div>
        <div class="card"><h2>Short-term composite: before and after costs</h2><p class="sub">Cumulative return of the top 20% minus the average name, one trade per holding period, out-of-sample</p><div class="chart tall" id="ls-comp"></div></div>
      </div>`;
    host.querySelectorAll("[data-st-row]").forEach(el => el.addEventListener("click", () => { state.stSig = el.dataset.stRow; render(); }));
    const ic = known((D.ic_series[sel.signal] || {})[hs[0]] || []);
    lineChart(document.getElementById("ls-ic"), [{ name: "monthly average of daily IC", data: ic.map(p => [ms(p.m), p.ic]) }], { yFmt: v => (v ?? 0).toFixed(3) });
    const h0 = (sel.horizons || {})[hs[0]] || {}, qs = h0.quintiles || [];
    const qEl = document.getElementById("ls-q");
    if (!emptyIf(qEl, !qs.length)) {
      const opt = baseOption();
      opt.xAxis = { type: "category", data: ["Q1", "Q2", "Q3", "Q4", "Q5"], axisLabel: { color: css("--text-muted") }, axisLine: { lineStyle: { color: css("--axis") } } };
      opt.yAxis.axisLabel.formatter = v => (v * 1e4).toFixed(0) + " bp";
      opt.tooltip = { trigger: "axis", backgroundColor: css("--surface-1"), borderColor: css("--border"), textStyle: { color: css("--text-primary") }, valueFormatter: v => (v * 1e4).toFixed(1) + " bp" };
      opt.series = [{ type: "bar", barMaxWidth: 36, data: qs.map(v => ({ value: v, itemStyle: { color: v >= 0 ? css("--div-pos") : css("--div-neg") } })),
                      markLine: h0.cost ? { symbol: "none", silent: true, label: { formatter: "cost", color: css("--text-secondary") }, lineStyle: { color: css("--critical"), type: "dashed" }, data: [{ yAxis: h0.cost }] } : undefined }];
      mount(qEl, opt);
    }
    const cs = (D.composite_series || {})[hs[0]] || [];
    lineChart(document.getElementById("ls-comp"), [
      { name: "before costs", data: known(cs).map(p => [ms(p.d), p.cum_gross]) },
      { name: "after costs", data: known(cs).map(p => [ms(p.d), p.cum_net]) }], { yFmt: v => (v * 100).toFixed(0) + "%" });
  }

  async function vLabIntraday(host) {
    const stale = staleCheck();
    const st = await stInfo();
    if (stale()) return;
    const I = st.intraday || {}, tfs = Object.keys(I);
    if (!tfs.length) { host.innerHTML = `<div class="card"><h2>Intraday data</h2><div class="empty">No intraday bars yet.<br>1. Free Alpaca key in ~/.config/ddb/alpaca.env<br>2. <code>python -m ddb.db.build_intraday --max-symbols 100</code> (about 1 minute per symbol-year)<br>3. <code>python -m ddb.features.intraday</code></div></div>`; return; }
    const tf = tfs.includes(state.itf) ? state.itf : tfs[0];
    const iv = I[tf], rows = bySignalStrength(iv.signals || []);
    const times = [...new Set(rows.flatMap(r => Object.keys(r.by_time || {})))].sort();
    host.innerHTML = `
      <div class="row" style="margin-bottom:12px">${tfs.map(x => `<button class="iconbtn ${x === tf ? "on" : ""}" data-itf="${x}">${esc(x)} bars</button>`).join("")}</div>
      <div class="card"><h2>${esc(tf)} data points</h2><p class="sub">${esc(iv.universe_rule || "")}. Each bar is public when it closes; a decision at a bar's close fills at the next bar's open. Statistics average each trading day first, then across days (${(iv.signals?.[0]?.horizons?.[iv.primary_horizon]?.days) || 0} days).</p>
        ${scoreTable(rows, iv.horizons, null, "data-x")}</div>
      <div class="card" style="margin-top:14px"><h2>When during the day does it work?</h2><p class="sub">Average rank IC by bar end time (New York), ${esc(iv.primary_horizon)}. Blue = the data point ranked the next bar's returns correctly at that time of day.</p>
        <div class="chart" id="li-tod" style="height:${Math.max(220, 28 * rows.length + 60)}px"></div></div>
      <div class="banner" style="margin-top:14px">The model can learn on these bars directly: <code>ddb.features.intraday.load_pricedata(symbols, "${esc(tf)}", start, end)</code> feeds the backtester with <code>SimSettings(intraday=True)</code> (same costs, T+1 settlement by trading day, good-faith rule; <code>view.bars_left_in_session()</code> to be flat by the close).</div>`;
    host.querySelectorAll("[data-itf]").forEach(b => b.addEventListener("click", () => { state.itf = b.dataset.itf; render(); }));
    const el = document.getElementById("li-tod");
    if (!emptyIf(el, !times.length)) {
      const opt = baseOption({ grid: { left: 190, right: 20, top: 10, bottom: 40 } });
      opt.xAxis = { type: "category", data: times, axisLabel: { color: css("--text-muted"), fontSize: 10 } };
      opt.yAxis = { type: "category", inverse: true, data: rows.map(r => r.label), axisLabel: { color: css("--text-secondary"), fontSize: 11 } };
      const data = [];
      rows.forEach((r, i) => times.forEach((tm, j) => { const v = (r.by_time || {})[tm]; if (v != null) data.push([j, i, v]); }));
      const mx = Math.max(0.02, ...data.map(d => Math.abs(d[2])));
      opt.visualMap = { min: -mx, max: mx, show: false, inRange: { color: [css("--div-neg"), css("--div-mid"), css("--div-pos")] } };
      opt.tooltip = { trigger: "item", backgroundColor: css("--surface-1"), borderColor: css("--border"), textStyle: { color: css("--text-primary") },
                      formatter: q => `${esc(rows[q.data[1]].label)} at ${esc(times[q.data[0]])}: IC ${q.data[2].toFixed(3)}` };
      opt.series = [{ type: "heatmap", data, itemStyle: { borderColor: css("--surface-1"), borderWidth: 2 } }];
      mount(el, opt);
    }
  }

  async function vDecisions() {
    const stale = staleCheck();
    const runs = await get("/runs");
    if (!runs.length) { view.innerHTML = `<div class="card"><div class="empty">No model runs recorded yet.</div></div>`; return; }
    if (!state.run || !runs.find(r => r.run_id === state.run)) state.run = runs[0].run_id;
    const run = runs.find(r => r.run_id === state.run);
    const data = await get(`/decisions/${state.run}`);
    if (stale()) return;
    const decs = data.decisions.filter(d => ms(d.as_of) <= state.asOf);
    const dates = [...new Set(decs.map(d => d.as_of))].sort();
    if (!state.ddate || !dates.includes(state.ddate)) state.ddate = dates.at(-1);
    const today = decs.filter(d => d.as_of === state.ddate);
    if (!state.did || !today.find(d => d.decision_id === state.did)) state.did = (today.find(d => d.action !== "hold") || today[0])?.decision_id;
    const sel = today.find(d => d.decision_id === state.did);
    const facs = data.factors.filter(f => f.decision_id === state.did);
    view.innerHTML = `
      <div class="card"><div class="row"><label class="secondary">Model run</label>
        <select id="runsel">${runs.map(r => `<option value="${esc(r.run_id)}" ${r.run_id === state.run ? "selected" : ""}>${esc(r.model)} (${r.n_decisions} decisions)</option>`).join("")}</select>
        <label class="secondary">Decision date</label>
        <select id="datesel">${dates.slice().reverse().map(d => `<option value="${esc(d)}" ${d === state.ddate ? "selected" : ""}>${day(d)}</option>`).join("")}</select></div>
        <p class="sub" style="margin-top:8px">${esc(run.description || "")} <span class="muted">Parameters: ${esc(run.params)}</span></p></div>
      ${!dates.length ? `<div class="card" style="margin-top:14px"><div class="empty">No decisions made by this date.</div></div>` : `
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h2>Decisions on ${day(state.ddate)}</h2><p class="sub">Click a decision to see why it was made</p>
          <div class="scroll"><table><thead><tr><th>Ticker</th><th>Company</th><th>Action</th><th class="num">Weight</th><th class="num">Score</th><th>Evidence</th></tr></thead><tbody>
          ${today.map(d => `<tr class="clickable ${d.decision_id === state.did ? "selected" : ""}" data-did="${d.decision_id}"><td><b>${esc(d.ticker)}</b></td><td>${esc(d.name || "")}</td><td class="act-${esc(d.action)}">${esc(d.action)}</td><td class="num">${pct(d.prev_weight)} → ${pct(d.target_weight)}</td><td class="num">${d.score == null ? "–" : d.score.toFixed(2)}</td><td>${d.evidence_ok ? '<span class="check-ok">✓ prior</span>' : '<span class="check-bad">✗ late</span>'}</td></tr>`).join("")}
          </tbody></table></div></div>
        <div class="card"><h2>Why: ${esc(sel?.ticker || "")} ${esc(sel?.action || "")}</h2><p class="sub">${esc(sel?.rationale || "")}</p>
          <div class="chart" id="d-contrib"></div>
          <p class="${sel?.evidence_ok ? "check-ok" : "check-bad"}">${sel?.evidence_ok ? `✓ All ${facs.length} pieces of evidence were public before this decision (latest: ${day(sel?.latest_evidence)}).` : "✗ Some evidence was not yet public at decision time."}</p></div>
      </div>
      <div class="card" style="margin-top:14px"><h2>Evidence behind this decision</h2>
        <p class="sub">Contribution = how much each factor pushed toward buying (+) or selling (−) in this model's units. Zero-contribution rows are context the model saw but does not use.</p>
        <div class="scroll"><table><thead><tr><th>Factor</th><th>Group</th><th>What the model saw</th><th class="num">Contribution</th><th>Source</th><th>Public since</th><th class="num">Days before decision</th></tr></thead><tbody>
        ${facs.sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution)).map(f => `<tr><td>${esc(f.factor)}<div class="muted">${esc(f.description || "")}</div></td><td>${esc(f.factor_group)}</td><td>${esc(f.value_text ?? compact(f.value))}</td><td class="num">${(f.contribution || 0).toFixed(2)}</td><td class="secondary">${esc(f.source_table || "")}${f.source_ref ? " · " + esc(f.source_ref) : ""}</td><td>${day(f.k)}</td><td class="num">${f.k ? Math.floor((ms(sel.as_of) - ms(f.k)) / 864e5) : "–"}</td></tr>`).join("")}
        </tbody></table></div></div>
      <div class="card" style="margin-top:14px"><h2>${esc(sel?.ticker || "")} position over time in this run</h2><div class="chart short" id="d-pos"></div></div>`}`;
    document.getElementById("runsel").addEventListener("change", e => { state.run = e.target.value; state.ddate = null; render(); });
    document.getElementById("datesel")?.addEventListener("change", e => { state.ddate = e.target.value; state.did = null; render(); });
    view.querySelectorAll("[data-did]").forEach(el => el.addEventListener("click", () => { state.did = el.dataset.did; render(); }));
    if (!sel) return;
    const nz = facs.filter(f => f.contribution).sort((a, b) => a.contribution - b.contribution);
    const cEl = document.getElementById("d-contrib");
    if (!emptyIf(cEl, !nz.length, "This decision has no scored factors")) {
      const opt = baseOption({ grid: { left: 150, right: 30, top: 10, bottom: 28 } });
      opt.xAxis = { type: "value", axisLabel: { color: css("--text-muted") }, splitLine: { lineStyle: { color: css("--grid") } } };
      opt.yAxis = { type: "category", data: nz.map(f => f.factor), axisLabel: { color: css("--text-secondary") }, axisLine: { lineStyle: { color: css("--axis") } } };
      opt.tooltip = { trigger: "item", backgroundColor: css("--surface-1"), borderColor: css("--border"), textStyle: { color: css("--text-primary") },
                      formatter: q => `${esc(q.name)}: ${q.value.toFixed(2)}` };
      opt.series = [{ type: "bar", barMaxWidth: 18, data: nz.map(f => ({ value: f.contribution, itemStyle: { color: f.contribution >= 0 ? css("--div-pos") : css("--div-neg"), borderRadius: f.contribution >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4] } })),
                      label: { show: true, position: "right", color: css("--text-secondary"), formatter: q => q.value.toFixed(2) } }];
      mount(cEl, opt);
    }
    const hist = data.decisions.filter(d => d.cik === sel.cik && ms(d.as_of) <= state.asOf).sort((a, b) => ms(a.as_of) - ms(b.as_of));
    const posEl = document.getElementById("d-pos");
    if (!emptyIf(posEl, hist.length < 2, `Only one decision on ${esc(sel.ticker)} so far in this run`))
      lineChart(posEl, [{ name: "target weight", data: hist.map(d => [ms(d.as_of), d.target_weight]) }], { step: true, yFmt: v => pct(v), yMin: 0 });
  }

  // ------------------------------------------------------------------ boot
  setAsOf(Date.now());
  render();
})();
