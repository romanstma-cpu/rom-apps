"""Local desktop dashboard: runs the engine in a background thread and
serves a single-page UI at http://127.0.0.1:8543 (stdlib only, so the
packaged Windows exe needs no extra dependencies)."""
from __future__ import annotations

import json
import logging
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
</header>
<main>
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
  ).join('');
}
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
        mid = hist[-1].mid if hist else p.entry_price
        positions.append({
            "side": p.side, "strategy": p.strategy, "entry": p.entry_price,
            "mark": round(p.held_token_price(mid), 4),
            "pnl": round(p.pnl(mid), 2), "question": p.market.question,
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
    return {
        "mode": engine.cfg.mode, "paused": engine.paused,
        "cash": round(engine.portfolio.cash, 2),
        "open_pnl": round(sum(p["pnl"] for p in positions), 2),
        "realized_pnl": round(sum(c["pnl"]
                                  for c in list(engine.portfolio.closed)), 2),
        "positions": positions, "markets": markets,
        "events": list(engine.events),
    }


def serve(engine: Engine, port: int = DEFAULT_PORT,
          open_browser: bool = True) -> None:
    worker = threading.Thread(target=engine.run, daemon=True, name="engine")
    worker.start()

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

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    log.info("dashboard at %s", url)
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        engine.portfolio.save()
        server.shutdown()


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
