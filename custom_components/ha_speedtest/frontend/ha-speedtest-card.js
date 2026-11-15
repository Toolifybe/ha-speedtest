/* Speedtest card v1.1.0 — meter + chart, follows the Home Assistant theme */
const CARD_VERSION = "1.1.0";

const T = {
  nl: {
    title: "Speedtest", chart: "Grafiek", gauge: "Meter", run: "Nu testen", again: "Opnieuw testen",
    busy: "Bezig…", ping: "Ping", jitter: "Jitter", download: "Download", upload: "Upload",
    idle: "Klaar", p_ping: "Ping meten", p_download: "Download meten", p_upload: "Upload meten",
    thisTest: "Deze test", days: (n) => `${n} dagen`, seconds: "s", noData: "Nog geen metingen. Druk op “Nu testen”.",
    noHist: "Nog geen metingen in deze periode.", light: "lichte test", full: "volledige test",
    server: "Cloudflare-server", ago: "geleden", now: "zonet", auto: (h) => h ? `automatisch om de ${h} u` : "alleen op vraag",
    notLoaded: "De integratie Speedtest is niet ingesteld (Instellingen → Apparaten & diensten).",
    failed: "Test mislukt", used: "gebruikt",
  },
  en: {
    title: "Speedtest", chart: "Chart", gauge: "Gauge", run: "Run test", again: "Run again",
    busy: "Running…", ping: "Ping", jitter: "Jitter", download: "Download", upload: "Upload",
    idle: "Done", p_ping: "Measuring ping", p_download: "Measuring download", p_upload: "Measuring upload",
    thisTest: "This test", days: (n) => `${n} days`, seconds: "s", noData: "No results yet. Press “Run test”.",
    noHist: "No results in this period.", light: "light test", full: "full test",
    server: "Cloudflare server", ago: "ago", now: "just now", auto: (h) => h ? `automatic every ${h} h` : "on request only",
    notLoaded: "The Speedtest integration is not set up (Settings → Devices & services).",
    failed: "Test failed", used: "used",
  },
};

// Series colours (validated categorical pair: blue, orange), stepped per mode
const COLORS = {
  light: { download: "#2a78d6", upload: "#eb6834", done: "#0f9d6e" },
  dark: { download: "#3987e5", upload: "#d95926", done: "#1fbf86" },
};
const NICE = [50, 100, 250, 500, 1000, 2500, 5000, 10000];
const svg = (tag, attrs = {}) => {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
};

class HaSpeedtestCard extends HTMLElement {
  static getStubConfig() { return { days: 7 }; }
  static getConfigForm() {
    return {
      schema: [
        { name: "title", selector: { text: {} } },
        { name: "days", selector: { number: { min: 1, max: 90, mode: "box" } } },
        { name: "max", selector: { number: { min: 10, max: 10000, step: 10, mode: "box", unit_of_measurement: "Mbit/s" } } },
        { name: "view", selector: { select: { options: [{ value: "gauge", label: "Meter / Gauge" }, { value: "chart", label: "Grafiek / Chart" }] } } },
      ],
      computeLabel: (s) => ({ title: "Titel / Title", days: "Dagen in de grafiek / Days in chart",
        max: "Maximum van de meter (leeg = automatisch) / Gauge maximum (empty = auto)", view: "Begin met / Start with" }[s.name]),
    };
  }

  setConfig(config) {
    this._config = { days: 7, view: "gauge", ...config };
    this._view = this._view || this._config.view;
    this._range = this._range || "days";
    if (this._built) this._renderAll();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const dark = !!(hass.themes && hass.themes.darkMode);
    if (first || dark !== this._dark) { this._dark = dark; if (this._built) this._renderAll(); }
    if (first) this._build();
    if (!this._unsub && this.isConnected) this._subscribe();
  }

  connectedCallback() { if (this._hass && !this._unsub) this._subscribe(); }
  disconnectedCallback() {
    if (this._unsub) { this._unsub.then((u) => u && u()).catch(() => {}); this._unsub = null; }
    if (this._ro) this._ro.disconnect();
  }
  getCardSize() { return 7; }
  getGridOptions() { return { columns: 12, min_columns: 6, rows: "auto" }; }

  get _t() { const l = (this._hass && this._hass.locale && this._hass.locale.language) || "en"; return l.startsWith("nl") ? T.nl : T.en; }
  get _c() { return COLORS[this._dark ? "dark" : "light"]; }
  get _lang() { return (this._hass && this._hass.locale && this._hass.locale.language) || "en"; }

  _subscribe() {
    this._unsub = this._hass.connection.subscribeMessage((d) => this._onData(d),
      { type: "ha_speedtest/subscribe", days: Math.min(90, Math.max(1, Number(this._config.days) || 7)) });
    this._unsub.catch(() => { this._unsub = null; this._error = this._t.notLoaded; this._renderAll(); });
  }

  _onData(d) {
    const was = this._data && this._data.phase;
    this._data = d; this._error = null;
    if (d.phase !== "idle" && was === "idle") this._range = "test";   // follow the running test in the chart
    this._renderAll();
  }

  // ── skeleton ───────────────────────────────────────────────────────
  _build() {
    this._built = true;
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { --st-mono: ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace; }
        ha-card { display: block; padding: 20px 20px 16px; overflow: hidden; container-type: inline-size; }
        .top { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
        .kicker { font-family: var(--st-mono); font-size: 13px; font-weight: 700; letter-spacing: .18em; text-transform: uppercase; color: var(--st-accent); flex: 1; }
        .kicker::before { content: "// "; opacity: .7; }
        .toggle { font: 600 12px var(--st-mono); letter-spacing: .1em; text-transform: uppercase; color: var(--st-accent);
          background: color-mix(in srgb, var(--st-accent) 8%, transparent); border: 1px solid color-mix(in srgb, var(--st-accent) 35%, transparent);
          border-radius: 10px; padding: 7px 12px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
        .toggle:hover { background: color-mix(in srgb, var(--st-accent) 15%, transparent); }
        .toggle ha-icon { --mdc-icon-size: 16px; }
        .stage { position: relative; min-height: 236px; display: flex; flex-direction: column; align-items: center; justify-content: center; }
        .gauge { width: min(320px, 100%); }
        .gauge svg { width: 100%; display: block; overflow: visible; }
        .g-val { font: 800 64px/1 var(--paper-font-common-base_-_font-family, system-ui); fill: var(--st-live); font-variant-numeric: tabular-nums; }
        .g-unit { font: 600 12px var(--st-mono); letter-spacing: .2em; fill: var(--secondary-text-color); }
        .g-tick { font: 12px var(--st-mono); fill: var(--secondary-text-color); }
        .phase { margin-top: 2px; font: 700 13px var(--st-mono); letter-spacing: .2em; text-transform: uppercase; color: var(--st-done); min-height: 18px; }
        .phase.busy { color: var(--st-live); animation: pulse 1.2s ease-in-out infinite; }
        .phase.err { color: var(--error-color, #db4437); letter-spacing: .05em; text-transform: none; font-weight: 600; }
        @keyframes pulse { 50% { opacity: .45; } }
        .chart { width: 100%; margin-bottom: 8px; }
        .chart-head { display: flex; align-items: center; gap: 14px; font: 600 13px var(--st-mono); margin-bottom: 4px; flex-wrap: wrap; }
        .leg { display: inline-flex; align-items: center; gap: 6px; color: var(--primary-text-color); }
        .leg i { width: 14px; height: 3px; border-radius: 2px; display: inline-block; }
        .unit { margin-left: auto; color: var(--secondary-text-color); font-weight: 400; }
        .seg { display: inline-flex; border: 1px solid var(--divider-color); border-radius: 9px; overflow: hidden; }
        .seg button { font: 600 12px var(--st-mono); border: 0; background: none; color: var(--secondary-text-color); padding: 5px 10px; cursor: pointer; }
        .seg button.on { background: color-mix(in srgb, var(--st-accent) 14%, transparent); color: var(--st-accent); }
        .plot { position: relative; }
        .plot svg { width: 100%; height: 200px; display: block; overflow: visible; }
        .plot text { font: 11px var(--st-mono); fill: var(--secondary-text-color); }
        .grid { stroke: var(--divider-color); stroke-width: 1; }
        .tip { position: absolute; pointer-events: none; background: var(--card-background-color, #fff); color: var(--primary-text-color);
          border: 1px solid var(--divider-color); border-radius: 10px; padding: 8px 10px; font-size: 12px; line-height: 1.5;
          box-shadow: 0 4px 16px rgba(0,0,0,.12); white-space: nowrap; transform: translate(-50%, -100%); display: none; z-index: 2; }
        .tip b { font-variant-numeric: tabular-nums; }
        .tip .sw { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
        .empty { color: var(--secondary-text-color); font-size: 14px; text-align: center; padding: 40px 0; }
        .tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 14px; }
        @container (max-width: 420px) { .tiles { grid-template-columns: repeat(2, 1fr); } .g-val { font-size: 56px; } }
        .tile { border: 1px solid var(--divider-color); border-radius: 14px; padding: 12px 14px; background: color-mix(in srgb, var(--primary-text-color) 2.5%, transparent); }
        .tile .lbl { font: 700 11px var(--st-mono); letter-spacing: .14em; text-transform: uppercase; color: var(--secondary-text-color); display: flex; align-items: center; gap: 6px; }
        .tile .lbl i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
        .tile .num { font-size: 26px; font-weight: 750; margin: 8px 0 2px; color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
        .tile .u { font: 12px var(--st-mono); color: var(--secondary-text-color); }
        .tile.live .num { color: var(--st-live); }
        .go { display: block; margin: 18px auto 10px; border: 0; border-radius: 999px; padding: 13px 34px; font-size: 16px; font-weight: 700;
          color: #fff; background: var(--st-accent); cursor: pointer; letter-spacing: .02em;
          box-shadow: 0 6px 20px color-mix(in srgb, var(--st-accent) 40%, transparent); transition: transform .15s, box-shadow .15s; }
        .go:hover:not([disabled]) { transform: translateY(-1px); box-shadow: 0 8px 26px color-mix(in srgb, var(--st-accent) 50%, transparent); }
        .go[disabled] { opacity: .65; cursor: default; box-shadow: none; }
        .foot { text-align: center; font: 12px var(--st-mono); color: var(--secondary-text-color); line-height: 1.6; }
        .msg { color: var(--secondary-text-color); padding: 16px 0; }
      </style>
      <ha-card>
        <div class="top"><div class="kicker"></div><button class="toggle" type="button"><ha-icon icon="mdi:swap-horizontal"></ha-icon><span></span></button></div>
        <div class="stage"></div>
        <div class="tiles"></div>
        <button class="go" type="button"></button>
        <div class="foot"></div>
      </ha-card>`;
    this._$ = (s) => root.querySelector(s);
    this._$(".toggle").addEventListener("click", () => { this._view = this._view === "gauge" ? "chart" : "gauge"; this._renderAll(); });
    this._$(".go").addEventListener("click", () => this._run());
    this._ro = new ResizeObserver(() => { if (this._view === "chart") this._renderStage(); });
    this._ro.observe(this._$(".stage"));
    this._renderAll();
  }

  async _run() {
    try { await this._hass.callWS({ type: "ha_speedtest/run", kind: "full" }); }
    catch (e) { this._error = e.message || String(e); this._renderAll(); }
  }

  // ── rendering ──────────────────────────────────────────────────────
  _renderAll() {
    if (!this._built) return;
    const t = this._t, c = this._c, card = this._$("ha-card");
    const d = this._data;
    const phase = d ? d.phase : "idle";
    card.style.setProperty("--st-accent", c.download);
    card.style.setProperty("--st-done", c.done);
    card.style.setProperty("--st-live", phase === "upload" ? c.upload : c.download);
    this._$(".kicker").textContent = this._config.title || t.title;
    this._$(".toggle span").textContent = this._view === "gauge" ? t.chart : t.gauge;
    const go = this._$(".go");
    go.disabled = !d || phase !== "idle";
    go.textContent = phase !== "idle" ? t.busy : (d && d.last ? t.again : t.run);
    this._renderStage();
    this._renderTiles();
    this._renderFoot();
  }

  _renderStage() {
    const st = this._$(".stage"), t = this._t;
    if (this._error && !this._data) { st.replaceChildren(Object.assign(document.createElement("div"), { className: "msg", textContent: this._error })); return; }
    if (!this._data) { st.replaceChildren(); return; }
    if (this._view === "gauge") this._renderGauge(st); else this._renderChart(st);
    const ph = document.createElement("div");
    const d = this._data;
    ph.className = "phase" + (d.phase !== "idle" ? " busy" : "") + (d.phase === "idle" && (d.error || this._error) ? " err" : "");
    ph.textContent = d.phase !== "idle" ? t["p_" + d.phase] : (d.error || this._error) ? `${t.failed}: ${d.error || this._error}` : d.last ? t.idle : "";
    st.append(ph);
  }

  _gaugeMax() {
    if (this._config.max) return Number(this._config.max);
    const d = this._data, vals = [...(d.history || []).map((h) => h.download), d.last ? d.last.download : 0, d.live || 0];
    const top = Math.max(...vals, 1) * 1.15;
    return NICE.find((n) => n >= top) || NICE[NICE.length - 1];
  }

  _renderGauge(st) {
    const d = this._data, c = this._c, max = this._gaugeMax();
    const live = d.phase === "download" || d.phase === "upload";
    const value = live ? (d.live || 0) : d.last ? d.last.download : 0;
    const color = live ? (d.phase === "upload" ? c.upload : c.download) : d.last ? c.done : c.download;
    // 240° arc, centre (150,150), radius 120
    const A0 = 150, A1 = 390, R = 120, cx = 150, cy = 150;
    const pt = (deg) => [cx + R * Math.cos((deg * Math.PI) / 180), cy + R * Math.sin((deg * Math.PI) / 180)];
    const arc = (a, b) => { const [x0, y0] = pt(a), [x1, y1] = pt(b); return `M${x0} ${y0} A${R} ${R} 0 ${b - a > 180 ? 1 : 0} 1 ${x1} ${y1}`; };
    let wrap = st.querySelector(".gauge");
    if (!wrap) {
      wrap = document.createElement("div"); wrap.className = "gauge";
      const s = svg("svg", { viewBox: "0 0 300 262", role: "img" });
      const defs = svg("defs"); const f = svg("filter", { id: "glow", x: "-30%", y: "-30%", width: "160%", height: "160%" });
      f.append(svg("feGaussianBlur", { stdDeviation: this._dark ? 6 : 4, result: "b" }));
      const m = svg("feMerge"); m.append(svg("feMergeNode", { in: "b" }), svg("feMergeNode", { in: "SourceGraphic" })); f.append(m); defs.append(f);
      s.append(defs,
        svg("path", { d: arc(A0, A1), fill: "none", stroke: "var(--divider-color)", "stroke-width": 18, "stroke-linecap": "round", class: "g-track" }),
        svg("path", { fill: "none", "stroke-width": 18, "stroke-linecap": "round", filter: "url(#glow)", class: "g-bar" }),
        svg("text", { x: 150, y: 165, "text-anchor": "middle", class: "g-val" }),
        svg("text", { x: 150, y: 192, "text-anchor": "middle", class: "g-unit" }),
        svg("text", { x: pt(A0)[0], y: pt(A0)[1] + 30, "text-anchor": "middle", class: "g-tick t0" }),
        svg("text", { x: 150, y: 16, "text-anchor": "middle", class: "g-tick tm" }),
        svg("text", { x: pt(A1)[0], y: pt(A1)[1] + 30, "text-anchor": "middle", class: "g-tick t1" }));
      wrap.append(s);
      st.replaceChildren(wrap);
      this._shown = 0;
    } else {
      st.replaceChildren(wrap);
    }
    const nf = new Intl.NumberFormat(this._lang);
    wrap.querySelector(".t0").textContent = "0";
    wrap.querySelector(".tm").textContent = nf.format(max / 2);
    wrap.querySelector(".t1").textContent = nf.format(max);
    wrap.querySelector(".g-unit").textContent = "MBIT/S";
    const bar = wrap.querySelector(".g-bar");
    bar.setAttribute("stroke", color);
    wrap.querySelector(".g-val").style.fill = color;
    // animate from the shown value to the new one
    const from = this._shown || 0, to = value, t0 = performance.now();
    cancelAnimationFrame(this._raf);
    const stepFn = (now) => {
      const k = Math.min(1, (now - t0) / 700), e = 1 - Math.pow(1 - k, 3), v = from + (to - from) * e;
      this._shown = v;
      const frac = Math.max(0, Math.min(1, v / max));
      if (frac > 0.002) { bar.setAttribute("d", arc(A0, A0 + (A1 - A0) * frac)); bar.style.display = ""; } else bar.style.display = "none";
      wrap.querySelector(".g-val").textContent = (live || d.last) ? nf.format(Math.round(v)) : "–";
      if (k < 1) this._raf = requestAnimationFrame(stepFn);
    };
    this._raf = requestAnimationFrame(stepFn);
  }

  _renderChart(st) {
    const t = this._t, c = this._c, d = this._data, days = Number(this._config.days) || 7;
    const box = document.createElement("div"); box.className = "chart";
    const head = document.createElement("div"); head.className = "chart-head";
    const seg = document.createElement("div"); seg.className = "seg";
    for (const [k, label] of [["test", t.thisTest], ["days", t.days(days)]]) {
      const b = document.createElement("button"); b.type = "button"; b.textContent = label; if (this._range === k) b.className = "on";
      b.addEventListener("click", () => { this._range = k; this._renderAll(); });
      seg.append(b);
    }
    const leg = (name, col) => { const s = document.createElement("span"); s.className = "leg"; s.innerHTML = `<i style="background:${col}"></i>`; s.append(name); return s; };
    const unit = document.createElement("span"); unit.className = "unit"; unit.textContent = "Mbit/s";
    head.append(seg, leg((this._range === "test" ? "↓ " : "") + t.download, c.download), leg((this._range === "test" ? "↑ " : "") + t.upload, c.upload), unit);
    box.append(head);
    const plot = document.createElement("div"); plot.className = "plot"; box.append(plot);
    st.replaceChildren(box);

    let series, xFmt, xMin, xMax, tipFmt;
    const nf = new Intl.NumberFormat(this._lang, { maximumFractionDigits: 0 });
    if (this._range === "test") {
      const running = d.phase !== "idle";
      const curve = running ? { download: d.live_curve.filter((p) => p[0] === "download").map((p) => [p[1], p[2]]),
                                upload: d.live_curve.filter((p) => p[0] === "upload").map((p) => [p[1], p[2]]) }
                            : (d.last && d.last.curve) || { download: [], upload: [] };
      series = [{ key: "download", pts: curve.download }, { key: "upload", pts: curve.upload }];
      xMin = 0; xMax = Math.max(10, ...series.flatMap((s) => s.pts.map((p) => p[0])));
      xFmt = (x) => `${nf.format(x)} ${t.seconds}`;
      tipFmt = (x) => `${new Intl.NumberFormat(this._lang, { maximumFractionDigits: 1 }).format(x)} ${t.seconds}`;
    } else {
      const hist = d.history || [];
      const now = Date.now();
      series = [{ key: "download", pts: hist.map((h) => [Date.parse(h.time), h.download, h]) },
                { key: "upload", pts: hist.map((h) => [Date.parse(h.time), h.upload, h]) }];
      xMax = now; xMin = now - days * 864e5;
      const df = new Intl.DateTimeFormat(this._lang, days > 10 ? { day: "numeric", month: "short" } : { weekday: "short", day: "numeric" });
      xFmt = (x) => df.format(x);
      const tf = new Intl.DateTimeFormat(this._lang, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
      tipFmt = (x) => tf.format(x);
    }
    if (!series.some((s) => s.pts.length)) {
      plot.innerHTML = `<div class="empty"></div>`;
      plot.firstChild.textContent = this._range === "test" ? (d.phase !== "idle" ? t["p_" + d.phase] + "…" : t.noData) : (d.last ? t.noHist : t.noData);
      return;
    }
    const W = Math.max(260, plot.clientWidth || st.clientWidth || 400), H = 200, L = 44, Rt = 10, Tp = 10, B = 24;
    const yTop = (() => { const m = Math.max(...series.flatMap((s) => s.pts.map((p) => p[1])), 1); const step = [1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10].map((f) => f * Math.pow(10, Math.floor(Math.log10(m / 4)))).find((s) => s * 4 >= m); return step * 4; })();
    const X = (x) => L + ((x - xMin) / (xMax - xMin || 1)) * (W - L - Rt);
    const Y = (y) => Tp + (1 - y / yTop) * (H - Tp - B);
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", style: `height:${H}px` });
    for (let i = 0; i <= 4; i++) {
      const v = (yTop / 4) * i;
      s.append(svg("line", { x1: L, x2: W - Rt, y1: Y(v), y2: Y(v), class: "grid", "stroke-dasharray": i ? "3 4" : "" }));
      const tx = svg("text", { x: L - 8, y: Y(v) + 4, "text-anchor": "end" }); tx.textContent = nf.format(v); s.append(tx);
    }
    // x labels
    const ticks = [];
    if (this._range === "test") { const st5 = xMax > 20 ? 10 : 5; for (let x = 0; x <= xMax; x += st5) ticks.push(x); }
    else { const day = new Date(xMin); day.setHours(0, 0, 0, 0); const every = Math.ceil(days / 7); for (let x = day.getTime() + 864e5, i = 0; x <= xMax; x += 864e5, i++) if (i % every === 0) ticks.push(x); }
    for (const x of ticks) { const tx = svg("text", { x: X(x), y: H - 6, "text-anchor": "middle" }); tx.textContent = xFmt(x); s.append(tx); }
    for (const se of series) {
      if (!se.pts.length) continue;
      const pts = [...se.pts].sort((a, b) => a[0] - b[0]);
      s.append(svg("path", { d: pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)} ${Y(p[1]).toFixed(1)}`).join(""), fill: "none",
        stroke: c[se.key], "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
      if (this._range === "days" && pts.length <= 120) for (const p of pts) s.append(svg("circle", { cx: X(p[0]), cy: Y(p[1]), r: 3,
        fill: p[2] && p[2].kind === "light" ? "var(--card-background-color, #fff)" : c[se.key], stroke: c[se.key], "stroke-width": 1.5 }));
    }
    // hover: crosshair + tooltip
    const cross = svg("line", { y1: Tp, y2: H - B, stroke: "var(--secondary-text-color)", "stroke-width": 1, "stroke-dasharray": "2 3", style: "display:none" });
    const dots = series.map((se) => svg("circle", { r: 5, fill: c[se.key], stroke: "var(--card-background-color, #fff)", "stroke-width": 2, style: "display:none" }));
    s.append(cross, ...dots);
    const tip = document.createElement("div"); tip.className = "tip";
    plot.append(s, tip);
    const allX = [...new Set(series.flatMap((se) => se.pts.map((p) => p[0])))].sort((a, b) => a - b);
    const move = (ev) => {
      const r = s.getBoundingClientRect(), px = ((ev.clientX - r.left) / r.width) * W;
      let best = allX[0]; for (const x of allX) if (Math.abs(X(x) - px) < Math.abs(X(best) - px)) best = x;
      cross.setAttribute("x1", X(best)); cross.setAttribute("x2", X(best)); cross.style.display = "";
      const lines = [`<div>${tipFmt(best)}</div>`]; let topY = H;
      series.forEach((se, i) => {
        const p = se.pts.reduce((a, q) => (Math.abs(q[0] - best) < Math.abs(a[0] - best) ? q : a), se.pts[0] || [Infinity]);
        if (!p || !isFinite(p[0]) || Math.abs(X(p[0]) - X(best)) > 6) { dots[i].style.display = "none"; return; }
        dots[i].setAttribute("cx", X(p[0])); dots[i].setAttribute("cy", Y(p[1])); dots[i].style.display = "";
        topY = Math.min(topY, Y(p[1]));
        lines.push(`<div><span class="sw" style="background:${c[se.key]}"></span>${se.key === "download" ? t.download : t.upload} <b>${nf.format(p[1])}</b> Mbit/s</div>`);
        if (se.key === "upload" && p[2]) lines.push(`<div style="opacity:.75">${t.ping} ${nf.format(p[2].ping)} ms · ${p[2].kind === "light" ? t.light : t.full}</div>`);
      });
      tip.innerHTML = lines.join("");
      tip.style.display = "block";
      const scale = r.width / W;
      tip.style.left = `${Math.min(Math.max(X(best) * scale, 90), r.width - 90)}px`;
      tip.style.top = `${Math.max(topY * scale - 10, 40)}px`;
    };
    const leave = () => { cross.style.display = "none"; dots.forEach((x) => (x.style.display = "none")); tip.style.display = "none"; };
    s.addEventListener("pointermove", move); s.addEventListener("pointerdown", move); s.addEventListener("pointerleave", leave);
  }

  _renderTiles() {
    const t = this._t, c = this._c, d = this._data || {}, last = d.last || {};
    const nf0 = new Intl.NumberFormat(this._lang, { maximumFractionDigits: 0 }), nf1 = new Intl.NumberFormat(this._lang, { maximumFractionDigits: 1 });
    const running = d.phase && d.phase !== "idle";
    const val = (k) => {
      if (running) {
        if (d.phase === k && d.live != null) return { v: nf0.format(d.live), live: true };
        return { v: "–" };
      }
      const v = last[k]; if (v == null) return { v: "–" };
      return { v: k === "jitter" ? nf1.format(v) : nf0.format(v) };
    };
    const tiles = [["ping", "ms", null], ["jitter", "ms", null], ["download", "Mbit/s", c.download], ["upload", "Mbit/s", c.upload]];
    this._$(".tiles").innerHTML = tiles.map(([k, u, col]) => {
      const x = val(k);
      return `<div class="tile${x.live ? " live" : ""}"><div class="lbl">${col ? `<i style="background:${col}"></i>` : ""}${t[k]}</div><div class="num">${x.v}</div><div class="u">${u}</div></div>`;
    }).join("");
  }

  _renderFoot() {
    const t = this._t, d = this._data, f = this._$(".foot");
    if (!d) { f.textContent = this._error || ""; return; }
    const parts = [];
    if (d.last) {
      const ms = Date.now() - Date.parse(d.last.time);
      const rtf = new Intl.RelativeTimeFormat(this._lang, { numeric: "auto" });
      const rel = ms < 60e3 ? t.now : ms < 3600e3 ? rtf.format(-Math.round(ms / 60e3), "minute") : ms < 864e5 ? rtf.format(-Math.round(ms / 3600e3), "hour") : rtf.format(-Math.round(ms / 864e5), "day");
      parts.push(`${rel} · ${d.last.kind === "light" ? t.light : t.full}${d.last.bytes_mb ? ` (±${d.last.bytes_mb} MB ${t.used})` : ""}`);
      if (d.last.server) parts.push(`${t.server} ${d.last.server}${d.last.isp ? " · " + d.last.isp : ""}`);
    }
    parts.push(t.auto(d.interval));
    f.innerHTML = parts.map((p) => `<div></div>`).join("");
    [...f.children].forEach((el, i) => (el.textContent = parts[i]));
  }
}

customElements.define("ha-speedtest-card", HaSpeedtestCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "ha-speedtest-card", name: "Speedtest", description: "Internet speed (Cloudflare) with gauge and chart", preview: true, documentationURL: "https://github.com/Toolifybe/ha-speedtest" });
console.info(`%c HA-SPEEDTEST-CARD %c v${CARD_VERSION} `, "color:#fff;background:#2a78d6;font-weight:700", "color:#2a78d6;background:#fff");
