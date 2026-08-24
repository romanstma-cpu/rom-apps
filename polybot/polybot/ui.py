"""Local desktop dashboard: runs the engine in a background thread and
serves a single-page UI at http://127.0.0.1:8543 (stdlib only, so the
packaged Windows exe needs no extra dependencies)."""
from __future__ import annotations

import csv
import io
import json
import logging
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .branding import APP_NAME, LOGO_URI
from .engine import Engine

log = logging.getLogger(__name__)
DEFAULT_PORT = 8543

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>__APP_NAME__</title>
<link rel="icon" type="image/png" href="__LOGO__">
<style>
  :root { color-scheme: dark; }
  body { margin:0; font:14px/1.5 system-ui,Segoe UI,sans-serif;
         background:#0d1117; color:#e6edf3; }
  header { display:flex; align-items:center; gap:16px; padding:12px 20px;
           background:#161b22; border-bottom:1px solid #30363d; }
  h1 { font-size:16px; margin:0; display:flex; align-items:center; gap:10px;
       letter-spacing:.04em; }
  h1 img { width:28px; height:28px; border-radius:6px; }
  h1 .sub { color:#8b949e; font-weight:400; }
  .stat { background:#161b22; border:1px solid #30363d; border-radius:8px;
          padding:10px 16px; min-width:120px; }
  .stat b { display:block; font-size:18px; }
  .green { color:#3fb950; } .red { color:#f85149; }
  main { display:grid; grid-template-columns: 1fr 1fr; gap:16px; padding:16px 20px; }
  section { background:#161b22; border:1px solid #30363d; border-radius:8px;
            padding:12px 16px; overflow-x:auto; }
  section.wide { grid-column: 1 / -1; }
  h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em;
       color:#8b949e; margin:0 0 8px; }
  table { border-collapse:collapse; width:100%; font-size:13px; }
  th,td { text-align:left; padding:4px 10px 4px 0; border-bottom:1px solid #21262d;
          white-space:nowrap; }
  td.q { white-space:normal; }
  button { background:#238636; color:#fff; border:0; border-radius:6px;
           padding:8px 14px; font-weight:600; cursor:pointer; }
  button.paused { background:#da3633; }
  #events div { padding:2px 0; color:#8b949e; }
  #events .enter { color:#3fb950; } #events .exit { color:#d29922; }
  .mode { font-size:12px; padding:2px 8px; border-radius:10px;
          background:#1f6feb33; border:1px solid #1f6feb; }
  .ver { color:#6e7681; font-size:12px; margin-left:auto; }
  .curve-wrap { position:relative; }
  #curve { width:100%; height:150px; display:block; }
  #curve .grid { stroke:#21262d; stroke-width:1; }
  #curve .line { fill:none; stroke:#d63ac4; stroke-width:2;
                 stroke-linejoin:round; stroke-linecap:round; }
  #curve .base { stroke:#484f58; stroke-width:1; stroke-dasharray:3 3; }
  #curve .axis { fill:#8b949e; font-size:11px; }
  #curve .cross { stroke:#8b949e; stroke-width:1; }
  #curve .dot { fill:#d63ac4; stroke:#161b22; stroke-width:2; }
  .tip { position:absolute; pointer-events:none; background:#0d1117;
         border:1px solid #30363d; border-radius:6px; padding:4px 8px;
         font-size:12px; white-space:nowrap; display:none; }
  .stats { display:flex; gap:20px; flex-wrap:wrap; margin-top:10px;
           font-size:13px; color:#8b949e; }
  .stats b { color:#e6edf3; font-weight:600; }
  .empty { color:#6e7681; font-size:13px; padding:8px 0; }
  a.export { color:#8b949e; font-size:12px; text-decoration:none;
             border:1px solid #30363d; border-radius:6px; padding:3px 8px; }
  a.export:hover { color:#e6edf3; border-color:#8b949e; }
  h2 .row-right { float:right; text-transform:none; letter-spacing:0; }
</style></head><body>
<header>
  <h1><img src="__LOGO__" alt="ROM logo"><span>ROM</span>
      <span class="sub">POLYBOT</span></h1>
  <span class="mode" id="mode"></span>
  <div class="stat">cash <b id="cash"></b></div>
  <div class="stat">open P&amp;L <b id="openpnl"></b></div>
  <div class="stat">realized P&amp;L <b id="realized"></b></div>
  <div class="stat">markets <b id="nmarkets"></b></div>
  <button id="pause" onclick="togglePause()"></button>
  <span class="ver" id="ver"></span>
</header>
<main>
  <section class="wide"><h2>Equity
      <span class="row-right"><a class="export" href="/trades.csv"
        download>Export trades (CSV)</a></span></h2>
    <div class="curve-wrap">
      <svg id="curve" viewBox="0 0 900 150" preserveAspectRatio="none"
           role="img" aria-label="Account equity over this session"></svg>
      <div class="tip" id="tip"></div>
    </div>
    <div class="stats" id="stats"></div>
  </section>

  <section class="wide"><h2>Open positions</h2>
    <table id="positions"><thead><tr><th>side</th><th>strategy</th><th>entry</th>
    <th>mark</th><th>P&amp;L</th><th>market</th></tr></thead><tbody></tbody></table>
  </section>
  <section><h2>Watched markets</h2>
    <table id="markets"><thead><tr><th>cat</th><th>mid</th><th>spread</th>
    <th>24h vol</th><th>question</th></tr></thead><tbody></tbody></table>
  </section>
  <section><h2>Activity</h2><div id="events"></div></section>
</main>
<script>
let paused = false;
function fmt(x){ return (x>=0?'+$':'-$') + Math.abs(x).toFixed(2); }
function esc(s){ const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }
async function refresh(){
  const r = await fetch('/api/state'); const s = await r.json();
  paused = s.paused;
  document.getElementById('mode').textContent = s.mode + ' mode';
  document.getElementById('cash').textContent = '$' + s.cash.toFixed(2);
  const op = document.getElementById('openpnl');
  op.textContent = fmt(s.open_pnl); op.className = s.open_pnl>=0?'green':'red';
  const rp = document.getElementById('realized');
  rp.textContent = fmt(s.realized_pnl); rp.className = s.realized_pnl>=0?'green':'red';
  document.getElementById('nmarkets').textContent = s.markets.length;
  const btn = document.getElementById('pause');
  btn.textContent = paused ? 'Resume entries' : 'Pause entries';
  btn.className = paused ? 'paused' : '';
  document.querySelector('#positions tbody').innerHTML = s.positions.map(p =>
    `<tr><td>${p.side}</td><td>${p.strategy}</td><td>${p.entry.toFixed(3)}</td>
     <td>${p.mark.toFixed(3)}</td><td class="${p.pnl>=0?'green':'red'}">${fmt(p.pnl)}</td>
     <td class="q">${esc(p.question)}</td></tr>`).join('') ||
    '<tr><td colspan=6>none</td></tr>';
  document.querySelector('#markets tbody').innerHTML = s.markets.map(m =>
    `<tr><td>${esc(m.category)}</td><td>${m.mid?m.mid.toFixed(3):'—'}</td>
     <td>${m.spread?m.spread.toFixed(3):'—'}</td>
     <td>${Math.round(m.volume_24h).toLocaleString()}</td>
     <td class="q">${esc(m.question)}</td></tr>`).join('') ||
    '<tr><td colspan=5>discovering…</td></tr>';
  document.getElementById('events').innerHTML = s.events.slice().reverse().map(e =>
    `<div class="${e.kind}">${new Date(e.ts*1000).toLocaleTimeString()} ${esc(e.text)}</div>`
  ).join('') || '<div class="empty">nothing yet — the bot logs entries and exits here</div>';
  document.getElementById('ver').textContent = 'v' + s.version;
  drawCurve(s.equity);
  drawStats(s);
}

function drawStats(s){
  const el = document.getElementById('stats');
  if (!s.trades) { el.innerHTML = '<span class="empty">no closed trades yet</span>'; return; }
  el.innerHTML =
    `<span>closed trades <b>${s.trades}</b></span>` +
    `<span>win rate <b>${s.win_rate}%</b></span>` +
    `<span>best <b class="green">${fmt(s.best)}</b></span>` +
    `<span>worst <b class="red">${fmt(s.worst)}</b></span>`;
}

let curvePts = [];
function drawCurve(eq){
  const svg = document.getElementById('curve');
  const W = 900, H = 150, PAD = 8, LEFT = 52, BOT = 18;
  if (!eq || eq.length < 2) {
    svg.innerHTML = `<text class="axis" x="${LEFT}" y="${H/2}">collecting equity data…</text>`;
    curvePts = []; return;
  }
  const vs = eq.map(p => p.v);
  let lo = Math.min(...vs), hi = Math.max(...vs);
  if (hi - lo < 0.01) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.12; lo -= pad; hi += pad;
  const x = i => LEFT + (W - LEFT - PAD) * (i / (eq.length - 1));
  const y = v => PAD + (H - PAD - BOT) * (1 - (v - lo) / (hi - lo));
  curvePts = eq.map((p, i) => ({ x: x(i), y: y(p.v), v: p.v, ts: p.ts }));

  const path = curvePts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join('');
  const start = eq[0].v, last = eq[eq.length - 1].v;
  const ticks = [hi - pad, (hi + lo) / 2, lo + pad];
  svg.innerHTML =
    ticks.map(t => `<line class="grid" x1="${LEFT}" y1="${y(t).toFixed(1)}" x2="${W - PAD}" y2="${y(t).toFixed(1)}"/>` +
                   `<text class="axis" x="0" y="${(y(t) + 4).toFixed(1)}">$${t.toFixed(0)}</text>`).join('') +
    `<line class="base" x1="${LEFT}" y1="${y(start).toFixed(1)}" x2="${W - PAD}" y2="${y(start).toFixed(1)}"/>` +
    `<path class="line" d="${path}"/>` +
    `<circle class="dot" cx="${curvePts[curvePts.length-1].x.toFixed(1)}" cy="${curvePts[curvePts.length-1].y.toFixed(1)}" r="4"/>` +
    `<text class="axis" x="${(W - PAD).toFixed(1)}" y="${Math.max(12, y(last) - 10).toFixed(1)}" text-anchor="end" style="fill:#e6edf3">$${last.toFixed(2)}</text>` +
    `<g id="hover"></g>`;
}

// crosshair + tooltip on the equity line
(function(){
  const svg = document.getElementById('curve'), tip = document.getElementById('tip');
  svg.addEventListener('mousemove', ev => {
    if (!curvePts.length) return;
    const r = svg.getBoundingClientRect();
    const sx = (ev.clientX - r.left) / r.width * 900;
    let best = curvePts[0];
    for (const p of curvePts) if (Math.abs(p.x - sx) < Math.abs(best.x - sx)) best = p;
    const g = svg.querySelector('#hover');
    if (g) g.innerHTML = `<line class="cross" x1="${best.x}" y1="8" x2="${best.x}" y2="132"/>` +
                         `<circle class="dot" cx="${best.x}" cy="${best.y}" r="4"/>`;
    tip.style.display = 'block';
    tip.style.left = Math.min(r.width - 130, best.x / 900 * r.width + 8) + 'px';
    tip.style.top = (best.y / 150 * r.height - 8) + 'px';
    tip.textContent = `$${best.v.toFixed(2)} · ${new Date(best.ts*1000).toLocaleTimeString()}`;
  });
  svg.addEventListener('mouseleave', () => {
    tip.style.display = 'none';
    const g = svg.querySelector('#hover'); if (g) g.innerHTML = '';
  });
})();
async function togglePause(){
  await fetch('/api/pause', {method:'POST',
    body: JSON.stringify({paused: !paused})});
  refresh();
}
refresh(); setInterval(refresh, 5000);
</script></body></html>"""
PAGE = PAGE.replace("__APP_NAME__", APP_NAME).replace("__LOGO__", LOGO_URI)


def _state(engine: Engine) -> dict:
    positions = []
    for p in list(engine.portfolio.positions):  # engine thread mutates these
        hist = engine.history.get(p.market.condition_id)
        # With no snapshot yet, mark AT entry — feeding entry_price in as a YES
        # mid would invent P&L on long-NO positions (held price = 1 - mid).
        mark = p.held_token_price(hist[-1].mid) if hist else p.entry_price
        positions.append({
            "side": p.side, "strategy": p.strategy, "entry": p.entry_price,
            "mark": round(mark, 4),
            "pnl": round((mark - p.entry_price) * p.shares, 2),
            "question": p.market.question,
        })
    markets = []
    for m in list(engine.markets):
        hist = engine.history.get(m.condition_id)
        last = hist[-1] if hist else None
        markets.append({
            "category": m.category, "question": m.question,
            "volume_24h": m.volume_24h,
            "mid": last.mid if last else None,
            "spread": last.spread if last else None,
        })
    closed = list(engine.portfolio.closed)
    wins = [c for c in closed if c["pnl"] > 0]
    equity = [{"ts": ts, "v": v} for ts, v in list(engine.equity)]
    return {
        "mode": engine.cfg.mode, "paused": engine.paused,
        "version": __version__,
        "cash": round(engine.portfolio.cash, 2),
        "open_pnl": round(sum(p["pnl"] for p in positions), 2),
        "realized_pnl": round(sum(c["pnl"] for c in closed), 2),
        "trades": len(closed),
        "win_rate": round(100 * len(wins) / len(closed)) if closed else None,
        "best": round(max((c["pnl"] for c in closed), default=0), 2),
        "worst": round(min((c["pnl"] for c in closed), default=0), 2),
        "equity": equity,
        "positions": positions, "markets": markets,
        "events": list(engine.events),
    }


def _trades_csv(engine: Engine) -> str:
    """Closed trades as CSV, for a spreadsheet or your own analysis."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["closed_at", "strategy", "side", "entry", "exit", "shares",
                "pnl", "reason", "market"])
    for c in list(engine.portfolio.closed):
        ts = c.get("closed_ts")
        w.writerow([
            datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else "",
            c.get("strategy", ""), c.get("side", ""), c.get("entry", ""),
            c.get("exit", ""), c.get("shares", ""), c.get("pnl", ""),
            c.get("reason", ""), c.get("question", ""),
        ])
    return buf.getvalue()


def serve(engine: Engine, port: int = DEFAULT_PORT,
          open_browser: bool = True) -> None:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self._send(PAGE.encode(), "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._send(json.dumps(_state(engine)).encode(),
                           "application/json")
            elif self.path == "/trades.csv":
                self._send(_trades_csv(engine).encode(),
                           "text/csv; charset=utf-8")
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path == "/api/pause":
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    body = {}
                engine.paused = bool(body.get("paused"))
                self._send(b'{"ok": true}', "application/json")
            else:
                self.send_error(404)

        def log_message(self, *args):  # quiet the request log
            pass

    # Bind BEFORE starting the engine: if the port is taken, fail with a clear
    # message instead of leaving a second engine trading in the background.
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        raise RuntimeError(
            f"cannot start the dashboard on port {port} ({exc}). "
            f"ROM Polybot may already be running — close it, or pass a "
            f"different port.") from exc

    worker = threading.Thread(target=engine.run, daemon=True, name="engine")
    worker.start()
    url = f"http://127.0.0.1:{port}"
    log.info("dashboard at %s", url)
    if open_browser:
        opener = threading.Timer(1.0, lambda: webbrowser.open(url))
        opener.daemon = True   # never hold up shutdown
        opener.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down…")
    finally:
        server.shutdown()
        server.server_close()
        engine.stop()          # let the engine finish its tick and save
        worker.join(timeout=20)


def main_windows() -> None:
    """Entry point for the packaged Windows exe: paper mode, bundled
    example config if the user has not created config.yaml yet."""
    import sys
    from pathlib import Path

    from .config import Config

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))
    user_cfg = Path("config.yaml")
    cfg_path = user_cfg if user_cfg.exists() else base / "config.example.yaml"
    serve(Engine(Config.load(str(cfg_path))))
