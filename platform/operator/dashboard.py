"""Local-only operator dashboard HTML."""

from __future__ import annotations


def render_dashboard_html() -> str:
    return '''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>traderd Console</title>
  <style>
    :root {
      --bg: #f3efe5;
      --panel: rgba(255, 252, 245, 0.92);
      --ink: #182026;
      --muted: #5e6a72;
      --line: rgba(24, 32, 38, 0.12);
      --accent: #0a7f5a;
      --warn: #c17d10;
      --danger: #b33a3a;
      --shadow: 0 18px 60px rgba(52, 62, 72, 0.14);
      --radius: 22px;
      --mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      --sans: "Segoe UI", "Helvetica Neue", Helvetica, Arial, sans-serif;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--sans);
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(10, 127, 90, 0.12), transparent 28%),
        radial-gradient(circle at top right, rgba(193, 125, 16, 0.12), transparent 24%),
        linear-gradient(180deg, #f7f4ec 0%, #efe8da 100%);
      min-height: 100vh;
    }

    .shell {
      width: min(1380px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 28px 0 40px;
    }

    .hero {
      display: grid;
      grid-template-columns: 1.3fr 0.7fr;
      gap: 18px;
      margin-bottom: 18px;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }

    .headline {
      padding: 26px 28px;
    }

    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      color: var(--muted);
      margin-bottom: 12px;
    }

    h1 {
      margin: 0;
      font-size: clamp(34px, 5vw, 58px);
      line-height: 0.94;
      letter-spacing: -0.04em;
    }

    .subhead {
      margin-top: 14px;
      max-width: 58ch;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.55;
    }

    .pulse-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 12px;
      padding: 18px;
    }

    .metric {
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255,255,255,0.58);
      min-height: 112px;
    }

    .metric-label {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--muted);
      margin-bottom: 8px;
    }

    .metric-value {
      font-size: 29px;
      font-weight: 700;
      letter-spacing: -0.04em;
      line-height: 1.05;
    }

    .metric-meta {
      margin-top: 9px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }

    .layout {
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 18px;
      align-items: start;
    }

    .stack {
      display: grid;
      gap: 18px;
    }

    .section {
      padding: 20px;
    }

    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 16px;
      margin-bottom: 16px;
    }

    .section-title {
      margin: 0;
      font-size: 20px;
      letter-spacing: -0.03em;
    }

    .section-note {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }

    .strategy-grid {
      display: grid;
      gap: 14px;
    }

    .strategy-card {
      border: 1px solid var(--line);
      border-radius: 18px;
      overflow: hidden;
      background: rgba(255,255,255,0.6);
    }

    .strategy-top {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 18px 12px;
      border-bottom: 1px solid var(--line);
    }

    .strategy-name {
      font-size: 20px;
      font-weight: 700;
      letter-spacing: -0.03em;
    }

    .strategy-sub {
      margin-top: 5px;
      color: var(--muted);
      font-size: 13px;
    }

    .badges {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    .badge {
      border-radius: 999px;
      padding: 7px 11px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      background: rgba(24, 32, 38, 0.08);
      color: var(--ink);
    }

    .badge.ok { background: rgba(10, 127, 90, 0.12); color: var(--accent); }
    .badge.warn { background: rgba(193, 125, 16, 0.16); color: var(--warn); }
    .badge.danger { background: rgba(179, 58, 58, 0.16); color: var(--danger); }

    .kv-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      padding: 16px 18px 18px;
    }

    .kv {
      padding: 12px 13px;
      background: rgba(245, 240, 230, 0.88);
      border-radius: 14px;
      min-height: 74px;
    }

    .kv-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
      margin-bottom: 7px;
    }

    .kv-value {
      font-size: 18px;
      font-weight: 700;
      letter-spacing: -0.03em;
      word-break: break-word;
    }

    .feed {
      display: grid;
      gap: 10px;
      max-height: 620px;
      overflow: auto;
      padding-right: 2px;
    }

    .feed-row {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 13px 14px;
      background: rgba(255,255,255,0.56);
    }

    .feed-top {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 7px;
      font-family: var(--mono);
      font-size: 12px;
    }

    .feed-type {
      font-weight: 700;
      color: var(--accent);
    }

    .feed-body {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .activity-summary {
      font-size: 15px;
      line-height: 1.5;
      color: var(--ink);
      margin-bottom: 6px;
    }

    .activity-detail {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }

    details.audit-raw {
      border-top: 1px solid var(--line);
      margin-top: 14px;
      padding-top: 14px;
    }

    details.audit-raw > summary {
      cursor: pointer;
      list-style: none;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
      margin-bottom: 12px;
    }

    details.audit-raw > summary::-webkit-details-marker {
      display: none;
    }

    .trigger-box {
      margin: 0 18px 18px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(255,255,255,0.52);
    }

    .trigger-title {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
    }

    .trigger-summary {
      font-size: 15px;
      line-height: 1.45;
      margin-bottom: 12px;
    }

    .trigger-list { display: grid; gap: 8px; }

    .trigger-item {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 12px;
      border-radius: 12px;
      background: rgba(245, 240, 230, 0.88);
      font-size: 13px;
      line-height: 1.4;
    }

    .trigger-state { font-weight: 700; }
    .trigger-state.ok { color: var(--accent); }
    .trigger-state.warn { color: var(--warn); }

    .runner {
      font-family: var(--mono);
      font-size: 12px;
      line-height: 1.55;
      white-space: pre-wrap;
      word-break: break-word;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      background: rgba(24, 32, 38, 0.92);
      color: #e9f4ef;
      min-height: 120px;
    }

    .actions-grid { display: grid; gap: 12px; }
    .action-card {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      background: rgba(255,255,255,0.56);
      display: grid;
      gap: 10px;
    }

    .action-title {
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
    }

    .field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .field-grid.single { grid-template-columns: 1fr; }
    .field-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--muted);
      margin-bottom: 5px;
      display: block;
    }

    input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 11px;
      font: inherit;
      background: rgba(245, 240, 230, 0.88);
      color: var(--ink);
    }

    button {
      border: 0;
      border-radius: 12px;
      padding: 11px 14px;
      font: inherit;
      font-weight: 700;
      background: var(--ink);
      color: white;
      cursor: pointer;
    }

    button.secondary { background: #4d5a64; }
    button.warn { background: var(--warn); }
    button.danger { background: var(--danger); }
    button:disabled { opacity: 0.6; cursor: wait; }

    .action-status {
      min-height: 18px;
      font-size: 12px;
      color: var(--muted);
      line-height: 1.4;
      white-space: pre-wrap;
    }

    .footer-note {
      margin-top: 12px;
      color: var(--muted);
      font-size: 12px;
    }

    .error {
      color: var(--danger);
      font-weight: 700;
    }

    @media (max-width: 1080px) {
      .hero, .layout { grid-template-columns: 1fr; }
      .kv-grid { grid-template-columns: repeat(2, 1fr); }
      .field-grid { grid-template-columns: 1fr; }
    }

    @media (max-width: 700px) {
      .shell { width: min(100vw - 20px, 100%); padding-top: 16px; }
      .headline { padding: 20px; }
      .pulse-grid, .section { padding: 16px; }
      .kv-grid { grid-template-columns: 1fr; }
      .metric-value { font-size: 24px; }
      h1 { font-size: 36px; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="panel headline">
        <div class="eyebrow">Traderd Operator Console</div>
        <h1>Paper Runtime<br />At A Glance</h1>
        <div class="subhead">
          Local-only monitoring console for traderd. This surface is read-only and reflects the authoritative operator API state, strategy runtime state, recent audit entries, and the latest daily runner result.
        </div>
      </div>
      <div class="panel pulse-grid" id="pulse-grid"></div>
    </section>

    <section class="layout">
      <div class="stack">
        <section class="panel section">
          <div class="section-head">
            <h2 class="section-title">Strategies</h2>
            <div class="section-note" id="refresh-note">Loading</div>
          </div>
          <div class="strategy-grid" id="strategy-grid"></div>
        </section>

        <section class="panel section">
          <div class="section-head">
            <h2 class="section-title">Recent Activity</h2>
            <div class="section-note">Operator view</div>
          </div>
          <div class="feed" id="activity-feed"></div>
          <details class="audit-raw">
            <summary>Raw Audit Events</summary>
            <div class="feed" id="audit-feed"></div>
          </details>
        </section>
      </div>

      <div class="stack">
        <section class="panel section">
          <div class="section-head">
            <h2 class="section-title">Operator Actions</h2>
            <div class="section-note">Uses existing API</div>
          </div>
          <div class="actions-grid">
            <div class="action-card">
              <div class="action-title">Common Operator Identity</div>
              <div class="field-grid single">
                <label><span class="field-label">Issued By</span><input id="issued-by" value="operator-ui" /></label>
              </div>
            </div>
            <div class="action-card">
              <div class="action-title">Health Checks</div>
              <div class="field-grid single">
                <button class="secondary" id="send-test-alert">Send Test Alert</button>
                <button id="run-daily-bars">Run Daily Bars</button>
              </div>
            </div>
            <div class="action-card">
              <div class="action-title">Emergency Halt</div>
              <div class="field-grid">
                <label><span class="field-label">Reason Code</span><input id="halt-code" value="OPERATOR_HALT" /></label>
                <label><span class="field-label">Reason Text</span><input id="halt-text" value="Manual operator halt from dashboard" /></label>
              </div>
              <button class="danger" id="halt-runtime">Halt Runtime</button>
            </div>
            <div class="action-card">
              <div class="action-title">Clear Halt</div>
              <div class="field-grid single">
                <label><span class="field-label">Reason Text</span><input id="clear-text" value="Dashboard clear halt after operator review" /></label>
                <label><span class="field-label">Reconciliation Token</span><input id="clear-token" placeholder="Paste reconciliation token" /></label>
              </div>
              <button class="warn" id="clear-halt">Clear Halt</button>
            </div>
            <div class="action-status" id="action-status"></div>
          </div>
        </section>

        <section class="panel section">
          <div class="section-head">
            <h2 class="section-title">Daily Runner</h2>
            <div class="section-note" id="runner-note">Most recent line</div>
          </div>
          <div class="runner" id="runner-log"></div>
          <div class="footer-note">Source: <span style="font-family:var(--mono)">var/logs/daily_runner.log</span></div>
        </section>

        <section class="panel section">
          <div class="section-head">
            <h2 class="section-title">System Notes</h2>
            <div class="section-note">Read only</div>
          </div>
          <div class="feed" id="notes"></div>
        </section>
      </div>
    </section>
  </div>

  <script>
    const pulseGrid = document.getElementById("pulse-grid");
    const strategyGrid = document.getElementById("strategy-grid");
    const activityFeed = document.getElementById("activity-feed");
    const auditFeed = document.getElementById("audit-feed");
    const runnerLog = document.getElementById("runner-log");
    const runnerNote = document.getElementById("runner-note");
    const refreshNote = document.getElementById("refresh-note");
    const notes = document.getElementById("notes");
    const actionStatus = document.getElementById("action-status");

    function fmt(value) {
      if (value === null || value === undefined || value === "") return "—";
      if (typeof value === "number") {
        if (Math.abs(value) >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
        return value.toFixed(2).replace(/\.00$/, "");
      }
      if (typeof value === "object") return JSON.stringify(value);
      return String(value);
    }

    function fmtTs(value) {
      if (!value) return "—";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return date.toLocaleString();
    }

    function relativeTime(value) {
      if (!value) return "—";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      const diffMs = Date.now() - date.getTime();
      const diffMinutes = Math.max(0, Math.floor(diffMs / 60000));
      if (diffMinutes < 1) return "just now";
      if (diffMinutes < 60) return `${diffMinutes}m ago`;
      const diffHours = Math.floor(diffMinutes / 60);
      if (diffHours < 24) return `${diffHours}h ago`;
      return `${Math.floor(diffHours / 24)}d ago`;
    }

    function badge(label, kind = "") {
      return `<span class="badge ${kind}">${label}</span>`;
    }

    function statusKind(value) {
      const raw = String(value || "").toUpperCase();
      if (["READY", "PAPER", "LIVE", "CONNECTED", "RUNNING", "SMS"].includes(raw)) return "ok";
      if (["HALTED", "DISCONNECTED", "UNAVAILABLE"].includes(raw)) return "danger";
      return "warn";
    }

    function stateWord(passed) {
      return passed ? "Met" : "Waiting";
    }

    function stateKind(passed) {
      return passed ? "ok" : "warn";
    }

    function latestClose(data, strategy) {
      const runtime = strategy.runtime_status || {};
      if (runtime.last_close !== null && runtime.last_close !== undefined) return Number(runtime.last_close);
      const result = data.daily_runner && data.daily_runner.last_result ? data.daily_runner.last_result : null;
      const deliveries = result && Array.isArray(result.deliveries) ? result.deliveries : [];
      const match = deliveries.find((item) => item.instrument_id === strategy.allowed_instruments[0]);
      return match ? Number(match.close) : Number(runtime.last_close);
    }

    function getReadiness(strategy, data) {
      const runtime = strategy.runtime_status || {};
      const params = strategy.parameters || {};
      const lastClose = latestClose(data, strategy);
      const sma = Number(runtime.current_sma_100);
      const adx = Number(runtime.current_adx_14);
      const rsi = Number(runtime.current_rsi_2);
      const daysHeld = Number(runtime.days_held || 0);
      const entryPrice = Number(runtime.entry_price);
      const adxMin = Number(params.adx_min || 20);
      const rsiEntry = Number(params.rsi_entry || 25);
      const rsiExit = Number(params.rsi_exit || 75);
      const maxHoldDays = Number(params.max_hold_days || 10);
      const stopLossPct = Number(params.stop_loss_pct || 0.01);

      if ((runtime.current_position || "flat") === "long") {
        const stopPrice = Number.isFinite(entryPrice) ? entryPrice * (1 - stopLossPct) : NaN;
        const checks = [
          { label: `RSI(2) > ${fmt(rsiExit)}`, detail: `Current ${fmt(rsi)} · gap ${fmt(rsiExit - rsi)}`, passed: Number.isFinite(rsi) && rsi > rsiExit },
          { label: `Days held >= ${fmt(maxHoldDays)}`, detail: `Current ${fmt(daysHeld)} · remaining ${fmt(maxHoldDays - daysHeld)}`, passed: daysHeld >= maxHoldDays },
          { label: `Close > stop ${fmt(stopPrice)}`, detail: `Current close ${fmt(lastClose)} · cushion ${fmt(lastClose - stopPrice)}`, passed: Number.isFinite(lastClose) && Number.isFinite(stopPrice) && lastClose > stopPrice },
        ];
        return {
          headline: checks.some((item) => item.passed) ? "An exit trigger is close or active." : "No exit trigger is active yet.",
          badge: checks.some((item) => item.passed) ? "Exit Watch" : "In Position",
          badgeKind: checks.some((item) => item.passed) ? "warn" : "ok",
          checks,
        };
      }

      const checks = [
        { label: `ADX(14) >= ${fmt(adxMin)}`, detail: `Current ${fmt(adx)} · gap ${fmt(adxMin - adx)}`, passed: Number.isFinite(adx) && adx >= adxMin },
        { label: `Close > SMA(100)`, detail: `Close ${fmt(lastClose)} vs SMA ${fmt(sma)} · gap ${fmt(lastClose - sma)}`, passed: Number.isFinite(lastClose) && Number.isFinite(sma) && lastClose > sma },
        { label: `RSI(2) < ${fmt(rsiEntry)}`, detail: `Current ${fmt(rsi)} · gap ${fmt(rsi - rsiEntry)}`, passed: Number.isFinite(rsi) && rsi < rsiEntry },
      ];
      const met = checks.filter((item) => item.passed).length;
      return {
        headline: `Entry setup: ${met}/3 conditions met.`,
        badge: met === 3 ? "Entry Ready" : "Entry Watch",
        badgeKind: met === 3 ? "ok" : "warn",
        checks,
      };
    }

    function renderPulse(data) {
      const gateway = data.gateway || {};
      const lastRunStatus = data.daily_runner.last_result ? String(data.daily_runner.last_result.status || "unknown") : "none";
      const cards = [
        {
          label: "Runtime",
          value: data.runtime.runtime_state,
          meta: `Uptime ${fmt(data.runtime.uptime_seconds)}s`,
        },
        {
          label: "Mode",
          value: data.mode.mode,
          meta: `Run ${data.runtime.run_id}`,
        },
        {
          label: "IBKR Gateway",
          value: data.broker.connected ? "Connected" : "Disconnected",
          meta: `${data.mode.ibkr.host}:${data.mode.ibkr.port} · ${gateway.container || "gateway"}`,
        },
        {
          label: "Gateway Uptime",
          value: gateway.running ? relativeTime(gateway.started_at) : fmt(gateway.status),
          meta: `Restarts ${fmt(gateway.restart_count)} · ${fmtTs(gateway.started_at)}`,
        },
        {
          label: "Last Daily Run",
          value: relativeTime(data.daily_runner.last_success_at || data.daily_runner.last_updated_at),
          meta: `${lastRunStatus.toUpperCase()} · ${fmtTs(data.daily_runner.last_updated_at)}`,
        },
        {
          label: "Active Strategies",
          value: data.summary.active_strategy_count,
          meta: `${data.summary.paper_strategy_count} paper / ${data.summary.live_strategy_count} live`,
        },
      ];
      pulseGrid.innerHTML = cards.map((card) => `
        <div class="metric">
          <div class="metric-label">${card.label}</div>
          <div class="metric-value">${fmt(card.value)}</div>
          <div class="metric-meta">${card.meta}</div>
        </div>
      `).join("");
    }

    function renderStrategies(data) {
      strategyGrid.innerHTML = data.strategies.map((strategy) => {
        const runtime = strategy.runtime_status || {};
        const tradeCount = (strategy.trades && strategy.trades.trades) ? strategy.trades.trades.length : 0;
        const lastSignal = runtime.last_signal ? `${runtime.last_signal.reason || "signal"} / ${runtime.last_signal.side || ""}` : "none";
        const readiness = getReadiness(strategy, data);
        const displayClose = latestClose(data, strategy);
        return `
          <article class="strategy-card">
            <div class="strategy-top">
              <div>
                <div class="strategy-name">${strategy.strategy_id}</div>
                <div class="strategy-sub">v${strategy.version} · ${strategy.description || "No description"}</div>
              </div>
              <div class="badges">
                ${badge(strategy.current_stage, statusKind(strategy.current_stage))}
                ${badge(runtime.current_position || "unknown", runtime.current_position === "long" ? "warn" : "ok")}
                ${badge(`${tradeCount} trades`)}
              </div>
            </div>
            <div class="kv-grid">
              <div class="kv"><div class="kv-label">Last Bar</div><div class="kv-value">${fmt(runtime.last_bar_processed)}</div></div>
              <div class="kv"><div class="kv-label">Days Held</div><div class="kv-value">${fmt(runtime.days_held)}</div></div>
              <div class="kv"><div class="kv-label">Last Signal</div><div class="kv-value">${fmt(lastSignal)}</div></div>
              <div class="kv"><div class="kv-label">Close</div><div class="kv-value">${fmt(displayClose)}</div></div>
              <div class="kv"><div class="kv-label">RSI(2)</div><div class="kv-value">${fmt(runtime.current_rsi_2)}</div></div>
              <div class="kv"><div class="kv-label">ADX(14)</div><div class="kv-value">${fmt(runtime.current_adx_14)}</div></div>
              <div class="kv"><div class="kv-label">SMA(100)</div><div class="kv-value">${fmt(runtime.current_sma_100)}</div></div>
              <div class="kv"><div class="kv-label">Entry Price</div><div class="kv-value">${fmt(runtime.entry_price)}</div></div>
              <div class="kv"><div class="kv-label">Pending Exit</div><div class="kv-value">${fmt(runtime.pending_exit_reason || "none")}</div></div>
            </div>
            <div class="trigger-box">
              <div class="trigger-title">
                <span>Strategy Readiness</span>
                ${badge(readiness.badge, readiness.badgeKind)}
              </div>
              <div class="trigger-summary">${readiness.headline}</div>
              <div class="trigger-list">
                ${readiness.checks.map((item) => `
                  <div class="trigger-item">
                    <div><strong>${item.label}</strong><br />${item.detail}</div>
                    <div class="trigger-state ${stateKind(item.passed)}">${stateWord(item.passed)}</div>
                  </div>
                `).join("")}
              </div>
            </div>
          </article>
        `;
      }).join("") || '<div class="feed-row">No strategies found.</div>';
    }

    function describeAuditEntry(entry) {
      const payload = entry.payload || {};
      switch (entry.event_type) {
        case "operator.alert": {
          const alert = payload.alert || {};
          const sinks = payload.sinks || {};
          if (alert.event_type === "session.start") {
            const sms = sinks.sms && sinks.sms.sent ? "SMS sent" : "SMS not sent";
            return {
              title: "Traderd startup alert",
              summary: `Traderd entered ${alert.payload && alert.payload.mode ? String(alert.payload.mode).toUpperCase() : "paper"} mode and ${sms}.`,
              detail: alert.message || "Startup alert dispatched.",
            };
          }
          if (alert.event_type === "broker.connect_failed") {
            return {
              title: "Broker connection failed",
              summary: "Traderd could not connect to the IBKR gateway during startup.",
              detail: alert.message || "Broker connection failed.",
            };
          }
          return {
            title: "Operator alert",
            summary: alert.message || entry.event_type,
            detail: `Severity: ${fmt(alert.severity)} · Sinks: ${Object.keys(sinks).join(", ") || "none"}`,
          };
        }
        case "operator.alert_sms":
          return {
            title: "SMS alert delivery",
            summary: payload.result && payload.result.sent ? "An SMS alert was delivered successfully." : "An SMS alert failed to deliver.",
            detail: payload.result && payload.result.message ? payload.result.message : `Severity: ${fmt(payload.severity)}`,
          };
        case "runtime.state_transition":
          return {
            title: "Runtime state changed",
            summary: `Runtime moved from ${fmt(payload.from_state)} to ${fmt(payload.to_state)}.`,
            detail: payload.reason_text || "No reason recorded.",
          };
        case "reconciliation.result":
          return {
            title: "Startup reconciliation",
            summary: `Reconciliation finished with status ${fmt(payload.status)}.`,
            detail: Array.isArray(payload.reasons) && payload.reasons.length ? payload.reasons.join(", ") : "No issues recorded.",
          };
        case "reconciliation.corrected":
          return {
            title: "Broker state refreshed",
            summary: "Local broker state was refreshed from IBKR.",
            detail: `Positions ${fmt(payload.positions)} · Open orders ${fmt(payload.open_orders)} · Executions ${fmt(payload.executions)}`,
          };
        case "runtime.mode":
          return {
            title: "Runtime target",
            summary: `Traderd is pointed at ${fmt(payload.host)}:${fmt(payload.port)} in ${fmt(payload.mode)} mode.`,
            detail: payload.account ? `Account ${fmt(payload.account)}` : "Paper account identifier not set.",
          };
        case "strategy.bar_processed":
          return {
            title: "Strategy processed bar",
            summary: `${fmt(entry.strategy_id)} processed a new bar.`,
            detail: `Instrument ${fmt(entry.instrument_id)} · ${fmt(payload.bar_ts)}`,
          };
        case "strategy.signal": {
          const reason = payload.reason ? String(payload.reason).replaceAll("_", " ") : "signal";
          return {
            title: "Strategy signal generated",
            summary: `${fmt(entry.strategy_id)} generated a ${reason} signal.`,
            detail: `Reference price ${fmt(payload.reference_price)} · Stage ${fmt(payload.stage)}`,
          };
        }
        case "daily_bar_runner.completed":
          return {
            title: "Daily bar run completed",
            summary: `Daily runner completed with ${fmt(payload.status)} status.`,
            detail: `Deliveries ${fmt(payload.deliveries_count)} · Issued by ${fmt(payload.issued_by)}`,
          };
        case "halt.set":
          return {
            title: "Runtime halted",
            summary: `Traderd was halted for ${fmt(payload.reason_code)}.`,
            detail: payload.reason_text || "No halt reason text recorded.",
          };
        default:
          return {
            title: entry.event_type,
            summary: entry.component || "System event",
            detail: JSON.stringify(payload),
          };
      }
    }

    function renderActivity(data) {
      activityFeed.innerHTML = data.audit.entries.map((entry) => {
        const view = describeAuditEntry(entry);
        return `
          <div class="feed-row">
            <div class="feed-top">
              <span class="feed-type">${view.title}</span>
              <span>${fmtTs(entry.ts_utc)}</span>
            </div>
            <div class="activity-summary">${view.summary}</div>
            <div class="activity-detail">${view.detail}</div>
          </div>
        `;
      }).join("") || '<div class="feed-row">No recent activity.</div>';
    }

    function renderAudit(data) {
      auditFeed.innerHTML = data.audit.entries.map((entry) => `
        <div class="feed-row">
          <div class="feed-top">
            <span class="feed-type">${entry.event_type}</span>
            <span>${entry.ts_utc}</span>
          </div>
          <div class="feed-body">${entry.component}${entry.strategy_id ? ` · ${entry.strategy_id}` : ""}${entry.instrument_id ? ` · ${entry.instrument_id}` : ""}\n${JSON.stringify(entry.payload)}</div>
        </div>
      `).join("") || '<div class="feed-row">No audit entries.</div>';
    }

    function renderDailyRunner(data) {
      const result = data.daily_runner.last_result;
      runnerNote.textContent = data.daily_runner.last_updated_at ? `Updated ${fmtTs(data.daily_runner.last_updated_at)}` : "Most recent line";
      if (!result) {
        runnerLog.textContent = data.daily_runner.last_line || "No daily runner log entries.";
        return;
      }
      const deliveries = Array.isArray(result.deliveries) ? result.deliveries : [];
      const delivery = deliveries[0] || null;
      const strategy = delivery && Array.isArray(delivery.strategies) ? delivery.strategies[0] || null : null;
      const lines = [
        `Status: ${fmt(result.status)}`,
        `Issued By: ${fmt(result.issued_by)}`,
        `Reconciliation: ${fmt(result.reconciliation_status)}`,
        `Updated At: ${fmtTs(data.daily_runner.last_updated_at)}`,
        `Last Success: ${fmtTs(data.daily_runner.last_success_at)}`,
        `Deliveries: ${deliveries.length}`,
      ];
      if (delivery) {
        lines.push(`Instrument: ${fmt(delivery.instrument_id)}`);
        lines.push(`Bar Time: ${fmt(delivery.bar_ts)}`);
        lines.push(`OHLC: ${fmt(delivery.open)} / ${fmt(delivery.high)} / ${fmt(delivery.low)} / ${fmt(delivery.close)}`);
        lines.push(`Volume: ${fmt(delivery.volume)}`);
      }
      if (strategy) {
        lines.push(`Strategy: ${fmt(strategy.strategy_id)} v${fmt(strategy.version)}`);
        lines.push(`Signals: ${Array.isArray(strategy.signals) ? strategy.signals.length : 0}`);
        lines.push(`Orders Submitted: ${Array.isArray(strategy.submitted_orders) ? strategy.submitted_orders.length : 0}`);
      }
      runnerLog.textContent = lines.join("\\n");
    }

    function renderNotes(data) {
      const alertBody = data.alerts.sms_enabled
        ? `SMS alerts active via Telus email gateway${data.alerts.telegram_enabled ? "; Telegram also enabled." : "; Telegram disabled."}`
        : "No operator alert sink is active.";
      const gateway = data.gateway || {};
      const items = [
        { title: "Broker Link", body: data.broker.connected ? "traderd reports an active broker connection." : "Broker adapter is disconnected from IBKR." },
        { title: "Gateway Health", body: `${fmt(gateway.status)} · restarts ${fmt(gateway.restart_count)} · started ${fmtTs(gateway.started_at)}` },
        { title: "Alerts", body: alertBody },
        { title: "Halt State", body: data.runtime.halt_state.is_halted ? `HALTED: ${data.runtime.halt_state.halt_reason_code || ""} ${data.runtime.halt_state.halt_reason_text || ""}` : "No halt is active." },
      ];
      notes.innerHTML = items.map((item) => `
        <div class="feed-row">
          <div class="feed-top"><span class="feed-type">${item.title}</span></div>
          <div class="feed-body">${item.body}</div>
        </div>
      `).join("");
    }

    function issuedBy() {
      return document.getElementById("issued-by").value.trim() || "operator-ui";
    }

    function setActionStatus(message, isError = false) {
      actionStatus.textContent = message;
      actionStatus.className = `action-status${isError ? ' error' : ''}`;
    }

    async function postAction(path, body, button) {
      const original = button.textContent;
      button.disabled = true;
      setActionStatus(`Running ${path} ...`);
      try {
        const response = await fetch(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
        setActionStatus(`${path} completed.
${JSON.stringify(payload, null, 2)}`);
        await load();
      } catch (error) {
        setActionStatus(String(error), true);
      } finally {
        button.disabled = false;
        button.textContent = original;
      }
    }

    document.getElementById("send-test-alert").addEventListener("click", async (event) => {
      await postAction("/alerts/test", { message: "Dashboard operator test alert" }, event.currentTarget);
    });

    document.getElementById("run-daily-bars").addEventListener("click", async (event) => {
      await postAction("/daily-bars/run", { issued_by: issuedBy() }, event.currentTarget);
    });

    document.getElementById("halt-runtime").addEventListener("click", async (event) => {
      await postAction("/halt", {
        issued_by: issuedBy(),
        reason_code: document.getElementById("halt-code").value.trim() || "OPERATOR_HALT",
        reason_text: document.getElementById("halt-text").value.trim() || "Manual operator halt from dashboard",
      }, event.currentTarget);
    });

    document.getElementById("clear-halt").addEventListener("click", async (event) => {
      await postAction("/clear-halt", {
        issued_by: issuedBy(),
        reason_text: document.getElementById("clear-text").value.trim() || "Dashboard clear halt after operator review",
        reconciliation_token: document.getElementById("clear-token").value.trim(),
      }, event.currentTarget);
    });

    async function load() {
      refreshNote.textContent = "Refreshing";
      try {
        const response = await fetch("/dashboard", { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        renderPulse(data);
        renderStrategies(data);
        renderActivity(data);
        renderAudit(data);
        renderNotes(data);
        renderDailyRunner(data);
        refreshNote.textContent = `Updated ${new Date().toLocaleTimeString()}`;
      } catch (error) {
        pulseGrid.innerHTML = `<div class="metric"><div class="metric-label">Console Error</div><div class="metric-value error">Unavailable</div><div class="metric-meta">${String(error)}</div></div>`;
        refreshNote.textContent = "Refresh failed";
      }
    }

    load();
    setInterval(load, 10000);
  </script>
</body>
</html>
'''
