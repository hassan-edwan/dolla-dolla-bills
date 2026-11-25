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
    tab: "overview", asOf: Date.now(), hindsight: false, industry: "nuclear",
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
    const loading = setTimeout(() => { if (seq === renderSeq) view.innerHTML = `<div class="card"><div class="empty">Loading…</div></div>`; }, 250);
    try {
      await ({ overview: vOverview, universe: vUniverse, industry: vIndustry, company: vCompany, decisions: vDecisions })[state.tab]();
      clearTimeout(loading);
    } catch (e) {
      clearTimeout(loading);
      view.innerHTML = `<div class="card"><div class="empty">Could not load: ${esc(e.message)}</div></div>`;
    }
  }

  async function vOverview() {
    const stale = staleCheck();
    const o = await get("/overview");
    if (stale()) return;
    const by = Object.fromEntries(o.sources.map(s => [s.table, s]));
    const tiles = [["companies", "companies, incl. failed & delisted"], ["filings", "SEC filings"], ["fundamentals", "financial fact versions"],
                   ["prices", "daily price bars"], ["insider_transactions", "insider trades"], ["politician_trades", "congressional trades"],
                   ["gov_contracts", "federal contract transactions"], ["news_events", "news articles kept"]];
    view.innerHTML = `
      <div class="grid tiles">${tiles.map(([t, l]) => `<div class="card tile"><div class="v">${compact(by[t]?.rows)}</div><div class="l">${l}</div></div>`).join("")}</div>
      <div class="card" style="margin-top:14px"><h2>Data sources</h2>
        <p class="sub">Every row has a public-release timestamp; "first/last" are the earliest and latest of those. Coverage counts are not as-of filtered.</p>
        <div class="scroll"><table><thead><tr><th>Dataset</th><th>Source</th><th class="num">Rows</th><th>First public</th><th>Last public</th></tr></thead>
        <tbody>${o.sources.map(s => `<tr><td>${esc(s.label)}</td><td class="secondary">${esc(s.source)}</td><td class="num">${(s.rows || 0).toLocaleString()}</td><td>${day(s.first)}</td><td>${day(s.last)}</td></tr>`).join("")}</tbody></table></div>
      </div>`;
  }

  async function vUniverse() {
    const stale = staleCheck();
    const [uni, scr] = await Promise.all([get("/universe"), get("/screens")]);
    if (stale()) return;
    const inds = Object.keys(uni).sort((a, b) => (uni[b].at(-1)?.active || 0) - (uni[a].at(-1)?.active || 0));
    const counts = {};
    scr.counts.forEach(c => { (counts[c.screen] ||= {})[c.status] = c.n; });
    const fin = Object.fromEntries(scr.financial_now.map(r => [r.status, r.n]));
    const ex = scr.excluded.filter(r => !state.exclFilter || `${r.name} ${r.ticker} ${r.reasons} ${r.screen}`.toLowerCase().includes(state.exclFilter.toLowerCase()));
    view.innerHTML = `
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
    document.getElementById("exf").addEventListener("input", e => { state.exclFilter = e.target.value; const pos = e.target.selectionStart; vUniverse().then(() => { const f = document.getElementById("exf"); f.focus(); f.setSelectionRange(pos, pos); }); });
    view.querySelectorAll("[data-cik]").forEach(el => el.addEventListener("click", () => openCompany(+el.dataset.cik)));
  }

  async function vIndustry() {
    const stale = staleCheck();
    const [uni, d0] = await Promise.all([get("/universe"), get(`/industry/${state.industry}`).catch(() => null)]);
    const inds = Object.keys(uni);
    if (!inds.includes(state.industry)) state.industry = inds[0];
    const d = d0 && d0.industry === state.industry ? d0 : await get(`/industry/${state.industry}`);
    if (stale()) return;
    const sel = `<select id="indsel">${inds.map(i => `<option value="${i}" ${i === state.industry ? "selected" : ""}>${esc(INDUSTRY_LABEL[i] || i)}</option>`).join("")}</select>`;
    const comm = (d.committees || []).filter(r => validAt(r) && (!r.k || ms(r.k) <= state.asOf));
    view.innerHTML = `
      <div class="row" style="margin-bottom:12px">${sel}<span class="secondary">Signals for companies in this industry and news tagged to it.</span></div>
      <div class="grid g2">
        <div class="card"><h2>Companies</h2><p class="sub">Active vs tradable after screens</p><div class="chart" id="c-uni"></div></div>
        <div class="card"><h2>What filings say</h2><p class="sub">Filings per quarter using bottleneck, development or stagnation language (EDGAR full-text search)</p><div class="chart" id="c-fil"></div></div>
        <div class="card"><h2>What the news says</h2><p class="sub">Articles per week carrying each signal (GDELT; backfill in progress)</p><div class="chart" id="c-news"></div></div>
        <div class="card"><h2>News tone</h2><p class="sub">Average article tone per week (negative = critical coverage)</p><div class="chart" id="c-tone"></div></div>
        <div class="card"><h2>Research activity</h2><p class="sub">arXiv papers per month</p><div class="chart" id="c-arx"></div></div>
        <div class="card"><h2>Public attention</h2><p class="sub">Weekly Wikipedia views of industry topics</p><div class="chart" id="c-wiki"></div></div>
        <div class="card"><h2>Insider money</h2><p class="sub">Open-market insider buys (up) and sales (down) per month, by disclosure date</p><div class="chart" id="c-ins"></div></div>
        <div class="card"><h2>How companies left</h2><p class="sub">Exits per year, counted once public</p><div class="chart" id="c-exit"></div></div>
        <div class="card"><h2>Regulation</h2><p class="sub">Federal Register documents per month from agencies shaping this industry</p><div class="chart" id="c-reg"></div></div>
        <div class="card"><h2>Government money</h2><p class="sub">Federal contract obligations per quarter (DoD counted 90 days late, as published)</p><div class="chart" id="c-con"></div></div>
        <div class="card"><h2>Congressional trades</h2><p class="sub">Disclosed trades in this industry's stocks per quarter</p><div class="chart" id="c-pol"></div></div>
        <div class="card"><h2>Who oversees it</h2><p class="sub">Committee leaders as of this date</p><div class="scroll"><table><thead><tr><th>Committee</th><th>Member</th><th>Role</th><th>Party</th><th>Since</th></tr></thead><tbody>
          ${comm.map(r => `<tr><td>${esc(r.committee_name)}</td><td>${esc(r.member)}</td><td>${esc(r.title)}</td><td>${esc(r.party)}</td><td>${day(r.valid_from)}</td></tr>`).join("") || `<tr><td colspan="5" class="muted">No data for this date</td></tr>`}
          </tbody></table></div></div>
      </div>`;
    document.getElementById("indsel").addEventListener("change", e => { state.industry = e.target.value; render(); });
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
      ${state.hindsight ? `<div class="card hindsight" style="margin-top:14px"><h2>Hindsight: how this listing ended</h2><p class="sub">Outcome labels are training targets only. A model never sees these as inputs.</p>
        ${labels.length ? `<table><thead><tr><th>Outcome</th><th>Exit date</th><th>Source</th><th>Confidence</th><th>Details</th></tr></thead><tbody>${labels.map(l => `<tr><td>${esc(l.outcome)}</td><td>${day(l.exit_date)}</td><td>${esc(l.method)}</td><td>${esc(l.confidence)}</td><td class="secondary">${esc(l.consideration || "")} ${l.source_url ? `<a href="${esc(l.source_url)}" target="_blank" rel="noopener">source</a>` : ""}</td></tr>`).join("")}</tbody></table>` : `<div class="empty">No label</div>`}</div>` : ""}
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h2>Price</h2><p class="sub">Weekly close. As traded = the actual price that day; split-adjusted = comparable across splits</p><div class="chart tall" id="k-px"></div></div>
        <div class="card"><h2>Filing events</h2><p class="sub">Distress, dilution and corporate events by public date</p><div class="chart tall" id="k-ev"></div></div>
        <div class="card"><h2>Sharia ratios</h2><p class="sub">Quarterly, from figures known at each date; dashed line = limit</p><div class="grid g3" id="k-sh"></div></div>
        <div class="card"><h2>Financials (as reported at the time)</h2><p class="sub">Revenue (annual), cash + short-term investments, debt, average market cap</p><div class="grid g3" id="k-fin"></div></div>
        <div class="card"><h2>Insider trades</h2><p class="sub">Open-market buys (up) and sales (down) per month, by disclosure date</p><div class="chart" id="k-ins"></div></div>
        <div class="card"><h2>News coverage</h2><p class="sub">Articles per week naming the company (GDELT; backfill in progress)</p><div class="chart" id="k-news"></div></div>
        <div class="card"><h2>Public attention</h2><p class="sub">Weekly Wikipedia views</p><div class="chart" id="k-wiki"></div></div>
        <div class="card"><h2>Government contracts</h2><p class="sub">Obligations per quarter, by public date</p><div class="chart" id="k-con"></div></div>
      </div>
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h2>Recent insider trades</h2><div class="scroll"><table><thead><tr><th>Traded</th><th>Disclosed</th><th class="num">Lag</th><th>Who</th><th>Type</th><th class="num">Value</th></tr></thead><tbody id="k-inst"></tbody></table></div></div>
        <div class="card"><h2>Congressional trades</h2><div class="scroll"><table><thead><tr><th>Traded</th><th>Disclosed</th><th>Member</th><th>Type</th><th class="num">Amount</th></tr></thead><tbody id="k-pol"></tbody></table></div></div>
        <div class="card"><h2>What its filings said</h2><p class="sub">Bottleneck / development / stagnation phrases</p><div class="scroll"><table><thead><tr><th>Filed</th><th>Form</th><th>Signal</th><th>Phrase</th></tr></thead><tbody id="k-fs"></tbody></table></div></div>
        <div class="card"><h2>Headlines</h2><div class="scroll"><table><thead><tr><th>Published</th><th>Source</th><th class="num">Tone</th><th>Signals</th></tr></thead><tbody id="k-hl"></tbody></table></div></div>
      </div>`;
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
