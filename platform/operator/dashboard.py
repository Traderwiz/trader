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
            <h2 class="section-title">Recent Audit</h2>
            <div class="section-note">Last 20 events</div>
          </div>
          <div class="feed" id="audit-feed"></div>
        </section>
      </div>

      <div class="stack">
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
    const auditFeed = document.getElementById("audit-feed");
    const runnerLog = document.getElementById("runner-log");
    const runnerNote = document.getElementById("runner-note");
    const refreshNote = document.getElementById("refresh-note");
    const notes = document.getElementById("notes");

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
              <div class="kv"><div class="kv-label">RSI(2)</div><div class="kv-value">${fmt(runtime.current_rsi_2)}</div></div>
              <div class="kv"><div class="kv-label">ADX(14)</div><div class="kv-value">${fmt(runtime.current_adx_14)}</div></div>
              <div class="kv"><div class="kv-label">SMA(100)</div><div class="kv-value">${fmt(runtime.current_sma_100)}</div></div>
            </div>
          </article>
        `;
      }).join("") || '<div class="feed-row">No strategies found.</div>';
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

    async function load() {
      refreshNote.textContent = "Refreshing";
      try {
        const response = await fetch("/dashboard", { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        renderPulse(data);
        renderStrategies(data);
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
