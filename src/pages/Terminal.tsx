import { useEffect, useMemo, useRef, useState } from 'react';
import { useApp } from '../state/AppStateProvider';
import type {
  Crypto15mSnapshot, Crypto15mStatus, Crypto15mAsset,
  BotPosition, PnlPoint,
} from '@shared/types';

let cachedSnap: Crypto15mSnapshot | null = null;
let cachedStatus: Crypto15mStatus | null = null;
let cachedPnl: PnlPoint[] = [];
const modelHist: number[] = [];
const bookHist: number[] = [];

let histMode: 'model' | 'spot' | null = null;
let histAsset: string | null = null;

const TICKER_ASSETS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'];
const fmtSpot = (v: number) =>
  v >= 1000 ? v.toLocaleString('en-US', { maximumFractionDigits: 0 })
  : v >= 1 ? v.toFixed(2) : v.toFixed(4);
const fmtMoney = (v: number | null | undefined) =>
  v == null ? '—' : (v < 0 ? '-' : '+') + '$' + Math.abs(v).toFixed(2);
const two = (n: number) => String(n).padStart(2, '0');
const clamp = (v: number, a: number, b: number) => (v < a ? a : v > b ? b : v);
const conf01 = (c: number) => (c <= 1 ? c : c / 100);
const intervalLabel = (iv?: string) => (iv === 'hourly' ? '1h' : iv || '15m');
const dpr = () => Math.min(2, window.devicePixelRatio || 1);

interface Orb {
  x: number; y: number; kind: 'asset' | 'whale' | 'mom';
  tx: number; ty: number; ph: number; r: number;
  orbR?: number; orbA?: number; orbT?: number;
  win?: boolean; a?: number; settled?: boolean; nodeX?: number; nodeY?: number;
}

export function TerminalPage() {
  const { account, positions, signals, logs, scannerStats, backend, config } = useApp();
  const [snap, setSnap] = useState<Crypto15mSnapshot | null>(cachedSnap);
  const [status, setStatus] = useState<Crypto15mStatus | null>(cachedStatus);
  const [pnl, setPnl] = useState<PnlPoint[]>(cachedPnl);
  const ivLabel = intervalLabel(config?.crypto15mInterval);
  const [chartInfo, setChartInfo] = useState<{ sym: string; nowStr: string; active: boolean }>(
    { sym: histAsset ?? '—', nowStr: '0.50', active: histMode === 'model' });

  useEffect(() => {
    let alive = true;

    let snapBusy = false, pnlBusy = false;
    async function loadSnap() {
      const api = window.rom?.crypto15m;
      if (!api || snapBusy) return;
      snapBusy = true;
      try {
        const [s, st] = await Promise.all([api.snapshot(), api.status()]);
        if (!alive) return;
        cachedSnap = s; cachedStatus = st; setSnap(s); setStatus(st);
      } catch {} finally { snapBusy = false; }
    }
    async function loadPnl() {
      if (pnlBusy) return;
      pnlBusy = true;
      try {
        const p = await window.rom?.data?.pnlSeries?.(24);
        if (alive && p) { cachedPnl = p; setPnl(p); }
      } catch {} finally { pnlBusy = false; }
    }
    void loadSnap(); void loadPnl();
    const t1 = window.setInterval(loadSnap, 2500);
    const t2 = window.setInterval(loadPnl, 30000);
    return () => { alive = false; clearInterval(t1); clearInterval(t2); };
  }, []);

  const assets: Crypto15mAsset[] = snap?.assets ?? [];
  const lead = useMemo(() => {
    const withProb = assets.filter(a => a.modelProb != null);
    if (!withProb.length) return null;
    return withProb.reduce((b, a) =>
      Math.abs((a.modelProb ?? .5) - .5) > Math.abs((b.modelProb ?? .5) - .5) ? a : b);
  }, [assets]);

  const gaugeInfo = useMemo(() => {
    if (lead?.modelProb != null)
      return { val: lead.modelProb as number | null, title: 'MODEL CONFIDENCE', tag: 'crypto15m.modelProb', sub: `${lead.asset} ${(lead.favorite ?? '').toUpperCase()}` };
    const s = signals[0];
    if (s) {
      const c = conf01(s.confidence);
      return { val: clamp(c, 0, 1) as number | null, title: 'SIGNAL CONFIDENCE', tag: s.source, sub: `${s.source} · ${(s.ticker || s.category || '').slice(0, 12)}` };
    }
    return { val: null as number | null, title: 'MODEL CONFIDENCE', tag: 'crypto15m.modelProb', sub: 'no live signal' };
  }, [lead, signals]);
  const gaugeValRef = useRef(gaugeInfo); gaugeValRef.current = gaugeInfo;

  const sessionPnl = account?.sessionPnlUsd ?? account?.realizedPnlUsd ?? 0;
  const todayPnl = account?.todayPnlUsd ?? null;
  const allPnl = account?.alltimePnlUsd ?? null;
  const winRate = account?.winRate;

  const now = Date.now();
  const signalsMin = useMemo(
    () => signals.filter(s => now - new Date(s.createdAt).getTime() < 60000).length,
    [signals, now]);
  const tradesHr = useMemo(() => {
    const a = positions.filter(p => now - new Date(p.createdAt).getTime() < 3600000).length;
    const b = (status?.recent ?? []).filter(p => now - new Date(p.createdAt).getTime() < 3600000).length;
    return a + b;
  }, [positions, status, now]);
  const marketsScanned = scannerStats?.marketsTracked ?? 0;

  const bookDelta = useMemo(() => {
    let mx = 0;
    for (const a of assets) {
      if (a.wsAsk == null || a.favorite == null) continue;
      const gAsk = a.favorite === 'up' ? a.upAsk : a.downAsk;
      if (gAsk == null) continue;
      const gCents = gAsk <= 1 ? gAsk * 100 : gAsk;
      mx = Math.max(mx, Math.abs(a.wsAsk - gCents));
    }
    return Math.round(mx);
  }, [assets]);

  const fills = useMemo(() => {
    const recent = (status?.recent ?? [])
      .filter(p => p.resolved && p.outcomeCorrect != null)
      .map(p => ({ t: p.resolvedAt ?? p.createdAt, w: p.outcomeCorrect === 1, label: `${p.asset} ${ivLabel}`, side: (p.side || p.direction || '').toUpperCase(), entry: p.avgEntryCents ?? p.entryLimitCents, pnl: p.pnlUsd }));
    const main = positions
      .filter(p => p.resolved && p.outcomeCorrect != null)
      .map(p => ({ t: p.resolvedAt ?? p.createdAt, w: p.outcomeCorrect === 1, label: (p.ticker || p.title || '—').slice(0, 14), side: p.direction.toUpperCase(), entry: p.avgFillPriceCents ?? p.limitPriceCents, pnl: p.pnlUsd }));
    return [...recent, ...main]
      .sort((x, y) => new Date(x.t).getTime() - new Date(y.t).getTime())
      .slice(-10);
  }, [status, positions, ivLabel]);

  const openRows = useMemo(() => {
    const rows: { key: string; label: string; side: string; entry: number; size: number; pnl: number | null }[] = [];
    for (const p of status?.open ?? []) {
      rows.push({
        key: 'c' + p.id, label: `${p.asset} ${ivLabel}`, side: p.side || p.direction || '',
        entry: Math.round(p.avgEntryCents ?? p.entryLimitCents), size: p.filledContracts || p.targetContracts,
        pnl: p.pnlUsd,
      });
    }
    for (const p of positions.filter((p: BotPosition) => !p.resolved && (p.status === 'filled' || p.status === 'partial'))) {
      rows.push({
        key: 'm' + p.id, label: (p.ticker || p.title || '—').slice(0, 12), side: p.direction,
        entry: Math.round(p.avgFillPriceCents ?? p.limitPriceCents), size: p.filledContracts,
        pnl: p.livePnlUsd,
      });
    }
    return rows.slice(0, 7);
  }, [status, positions, ivLabel]);

  const isLive = backend.status === 'running';

  const fieldRef = useRef<HTMLCanvasElement>(null);
  const orbsRef = useRef<Orb[]>([]);
  const nodesRef = useRef<{ kind: 'asset' | 'whale' | 'mom'; label: string; a?: Crypto15mAsset; x: number; y: number; ang: number }[]>([]);
  const dataRef = useRef({ assets, fills });
  dataRef.current = { assets, fills };
  const lastSigId = useRef<number>(-1);

  useEffect(() => {
    if (!signals.length) return;
    const newest = signals[0].id;
    if (lastSigId.current < 0) { lastSigId.current = newest; return; }
    const fresh = signals.filter(s => s.id > lastSigId.current);
    lastSigId.current = newest;
    for (const s of fresh.slice(0, 8)) {
      orbsRef.current.push(makeOrb(fieldRef.current,
        s.source === 'whale' ? 'whale' : s.source === 'momentum' ? 'mom' : 'asset', nodesRef.current));
    }
  }, [signals]);

  useEffect(() => {
    const cv = fieldRef.current; if (!cv) return;
    let raf = 0; let hiddenTimer = 0; let coreP = 0;
    const orbs = orbsRef.current;
    function layout(w: number, h: number) {
      const list = dataRef.current.assets.slice(0, 7);

      const base: { kind: 'asset' | 'whale' | 'mom'; label: string; a?: Crypto15mAsset }[] =
        (list.length ? list.map(a => ({ kind: 'asset' as const, label: a.asset ?? '·', a }))
          : Array.from({ length: 7 }, () => ({ kind: 'asset' as const, label: '·' })));
      base.push({ kind: 'whale', label: 'WHALE' }, { kind: 'mom', label: 'MOMENTUM' });
      nodesRef.current = base.map((n, i) => {
        const ang = -Math.PI / 2 + i / base.length * Math.PI * 2;
        return { ...n, x: w / 2 + Math.cos(ang) * Math.min(w, h) * .34, y: h / 2 + Math.sin(ang) * Math.min(w, h) * .31, ang };
      });
    }
    function frame(t: number) {
      if (document.hidden) { hiddenTimer = window.setTimeout(() => { raf = requestAnimationFrame(frame); }, 500); return; }
      const cv = fieldRef.current; if (!cv) { raf = requestAnimationFrame(frame); return; }
      const w = cv.clientWidth, h = cv.clientHeight, d = dpr();
      if (cv.width !== w * d || cv.height !== h * d) { cv.width = w * d; cv.height = h * d; layout(w, h); }
      if (!nodesRef.current.length) layout(w, h);
      const c = cv.getContext('2d')!; c.setTransform(d, 0, 0, d, 0, 0); c.clearRect(0, 0, w, h);
      c.strokeStyle = 'rgba(22,35,63,.35)'; c.lineWidth = 1;
      for (let x = 0; x < w; x += 34) { c.beginPath(); c.moveTo(x, 0); c.lineTo(x, h); c.stroke(); }
      for (let y = 0; y < h; y += 34) { c.beginPath(); c.moveTo(0, y); c.lineTo(w, y); c.stroke(); }
      const cx = w / 2, cy = h / 2; coreP += .04;
      const nodes = nodesRef.current;

      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const n1 = nodes[i], n2 = nodes[j];
        if (Math.hypot(n1.x - n2.x, n1.y - n2.y) > Math.min(w, h) * .72) continue;
        const al = .05 + .05 * Math.sin(coreP * 1.3 + i * 1.7 + j);
        c.beginPath(); c.moveTo(n1.x, n1.y); c.lineTo(n2.x, n2.y); c.strokeStyle = `rgba(56,189,248,${al})`; c.lineWidth = 1; c.stroke();
        const tp = ((t / 900) + (i * .13 + j * .07)) % 1;
        c.beginPath(); c.arc(n1.x + (n2.x - n1.x) * tp, n1.y + (n2.y - n1.y) * tp, 1.5, 0, 7); c.fillStyle = `rgba(140,205,255,${.3 + al})`; c.fill();
      }

      nodes.forEach(n => {
        c.beginPath(); c.moveTo(cx, cy); c.lineTo(n.x, n.y);
        c.strokeStyle = `rgba(47,129,247,${.10 + .06 * Math.sin(coreP + n.ang)})`; c.lineWidth = 1;
        c.setLineDash([2, 6]); c.lineDashOffset = -t / 60; c.stroke(); c.setLineDash([]);
        const tp = (t / 1400 + n.ang) % 1; c.beginPath(); c.arc(cx + (n.x - cx) * tp, cy + (n.y - cy) * tp, 1.6, 0, 7); c.fillStyle = 'rgba(120,190,255,.5)'; c.fill();
        if (n.kind === 'asset') {
          const prob = n.a?.modelProb ?? .5; const rr = 5 + prob * 4;
          c.beginPath(); c.arc(n.x, n.y, rr, 0, 7); c.fillStyle = '#0a1324'; c.strokeStyle = '#2f81f7'; c.lineWidth = 1.5;
          c.shadowColor = '#2f81f7'; c.shadowBlur = 8 + prob * 10; c.fill(); c.stroke(); c.shadowBlur = 0;
          c.fillStyle = '#cfe0ff'; c.font = '700 9px ui-monospace,monospace'; c.textAlign = 'center'; c.textBaseline = 'middle';
          c.fillText(n.label, n.x, n.y);
          c.fillStyle = '#4a5d84'; c.font = '8px ui-monospace,monospace';
          c.fillText(n.a?.modelProb != null ? n.a.modelProb.toFixed(2) : '—', n.x, n.y + rr + 7);
        } else {
          const col = n.kind === 'whale' ? '#fbbf24' : '#7dd3fc'; const rr = 8.5;
          c.beginPath(); c.arc(n.x, n.y, rr, 0, 7); c.fillStyle = '#0a1324'; c.strokeStyle = col; c.lineWidth = 1.8;
          c.shadowColor = col; c.shadowBlur = 13; c.fill(); c.stroke(); c.shadowBlur = 0;
          c.fillStyle = '#eaf2ff'; c.font = '700 9px ui-monospace,monospace'; c.textAlign = 'center'; c.textBaseline = 'middle';
          c.fillText(n.kind === 'whale' ? 'W' : 'M', n.x, n.y);
          c.fillStyle = col; c.font = '7.5px ui-monospace,monospace';
          c.fillText(n.label, n.x, n.y + rr + 7);
        }
      });

      const cg = c.createRadialGradient(cx, cy, 0, cx, cy, 26 + Math.sin(coreP) * 4);
      cg.addColorStop(0, 'rgba(120,200,255,.9)'); cg.addColorStop(.4, 'rgba(47,129,247,.5)'); cg.addColorStop(1, 'rgba(47,129,247,0)');
      c.beginPath(); c.arc(cx, cy, 26 + Math.sin(coreP) * 4, 0, 7); c.fillStyle = cg; c.fill();
      c.beginPath(); c.arc(cx, cy, 5, 0, 7); c.fillStyle = '#eaf2ff'; c.shadowColor = '#38bdf8'; c.shadowBlur = 16; c.fill(); c.shadowBlur = 0;

      const COL: Record<string, string> = { asset: '#2f81f7', whale: '#fbbf24', mom: '#7dd3fc', fill: '#34d399' };
      for (let i = orbs.length - 1; i >= 0; i--) {
        const o = orbs[i];
        if (o.ph === 0) {
          o.x += (o.tx - o.x) * .045; o.y += (o.ty - o.y) * .045;
          if (Math.hypot(o.tx - o.x, o.ty - o.y) < 6) { o.ph = 1; o.tx = cx; o.ty = cy; }
        } else if (o.ph === 1) {
          o.x += (o.tx - o.x) * .05; o.y += (o.ty - o.y) * .05;
          if (Math.hypot(cx - o.x, cy - o.y) < 10) { o.ph = 2; o.orbR = 16 + Math.random() * 14; o.orbA = Math.random() * 7; o.orbT = 40 + Math.random() * 50; }
        } else if (o.ph === 2) {
          o.orbA! += .09; o.orbT! -= 1; o.x = cx + Math.cos(o.orbA!) * o.orbR!; o.y = cy + Math.sin(o.orbA!) * o.orbR!;
          if (o.orbT! <= 0) { o.ph = 3; o.win = Math.random() > .46; o.tx = cx + (Math.random() - .5) * 60; o.ty = o.win ? -20 : h + 20; }
        } else {
          o.x += (o.tx - o.x) * .06; o.y += (o.ty - o.y) * .06; o.a = (o.a ?? 1) - .02;
          if (o.a <= 0) { orbs.splice(i, 1); continue; }
        }
        const col = o.ph >= 3 ? (o.win ? COL.fill : '#fb7185') : COL[o.kind] || COL.asset;
        c.globalAlpha = o.a ?? 1; c.beginPath(); c.arc(o.x, o.y, o.r, 0, 7); c.fillStyle = col; c.shadowColor = col; c.shadowBlur = 10; c.fill(); c.shadowBlur = 0; c.globalAlpha = 1;
      }
      if (orbs.length > 60) orbs.splice(0, orbs.length - 60);
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); clearTimeout(hiddenTimer); };
  }, []);

  const eqRef = useRef<HTMLCanvasElement>(null);
  const gaugeRef = useRef<HTMLCanvasElement>(null);
  const modelRef = useRef<HTMLCanvasElement>(null);
  const gaugeV = useRef(.5);

  useEffect(() => {
    const list = snap?.assets ?? [];
    if (!list.length) return;
    const withProb = list.filter(a => a.modelProb != null);
    const reset = (mode: 'model' | 'spot', asset: string | null) => {
      if (histMode !== mode || histAsset !== asset) { modelHist.length = 0; bookHist.length = 0; }
      histMode = mode; histAsset = asset;
    };
    if (withProb.length) {
      const L = withProb.reduce((b, a) => Math.abs((a.modelProb ?? .5) - .5) > Math.abs((b.modelProb ?? .5) - .5) ? a : b);
      reset('model', L.asset);
      const mv = L.modelProb ?? .5;
      const bk = L.wsAsk != null ? clamp(L.wsAsk / 100, 0, 1) : (L.favoritePrice ?? .5);
      modelHist.push(mv); bookHist.push(bk);
      if (modelHist.length > 120) { modelHist.shift(); bookHist.shift(); }
      setChartInfo({ sym: L.asset, nowStr: mv.toFixed(2), active: true });
    } else {
      const M = list.reduce((b, a) => Math.abs(a.deltaSignedPct ?? 0) > Math.abs(b.deltaSignedPct ?? 0) ? a : b, list[0]);
      reset('spot', M.asset ?? null);
      if (M.spotUsd) {
        modelHist.push(M.spotUsd);
        if (modelHist.length > 120) modelHist.shift();
      }
      setChartInfo({ sym: M.asset ?? '—', nowStr: M.spotUsd != null ? fmtSpot(M.spotUsd) : '—', active: false });
    }
  }, [snap]);

  useEffect(() => {
    let raf = 0; let stopped = false;
    function fit(cv: HTMLCanvasElement, h: number) {
      const w = cv.clientWidth; const d = dpr();

      const cw = Math.round(w * d), ch = Math.round(h * d);
      if (cv.width !== cw || cv.height !== ch) { cv.width = cw; cv.height = ch; }
      const c = cv.getContext('2d')!; c.setTransform(d, 0, 0, d, 0, 0); return { c, w, h };
    }
    function draw() {
      if (document.hidden) {
        if (stopped) return;
        raf = window.setTimeout(() => { if (!stopped) requestAnimationFrame(draw); }, 500) as unknown as number;
        return;
      }

      const eq = eqRef.current;
      if (eq) {
        const { c, w, h } = fit(eq, 60);
        const pts = cachedPnl.length ? cachedPnl.map(p => p.totalUsd) : [0, 0];
        const mn = Math.min(...pts), mx = Math.max(...pts), rg = (mx - mn) || 1;
        const X = (i: number) => i / (pts.length - 1 || 1) * w, Y = (v: number) => h - 6 - ((v - mn) / rg) * (h - 12);
        c.clearRect(0, 0, w, h);
        c.beginPath(); c.moveTo(0, h); pts.forEach((v, i) => c.lineTo(X(i), Y(v))); c.lineTo(w, h); c.closePath();
        const g = c.createLinearGradient(0, 0, 0, h); g.addColorStop(0, 'rgba(47,129,247,.28)'); g.addColorStop(1, 'rgba(47,129,247,0)'); c.fillStyle = g; c.fill();
        c.beginPath(); pts.forEach((v, i) => i ? c.lineTo(X(i), Y(v)) : c.moveTo(X(i), Y(v)));
        c.strokeStyle = '#38bdf8'; c.lineWidth = 1.5; c.shadowColor = '#2f81f7'; c.shadowBlur = 8; c.stroke(); c.shadowBlur = 0;
        c.beginPath(); c.arc(w - 1, Y(pts[pts.length - 1]), 2.4, 0, 7); c.fillStyle = '#eaf2ff'; c.fill();
      }

      const gc = gaugeRef.current;
      if (gc) {
        const gv = gaugeValRef.current.val;
        gaugeV.current += ((gv ?? .5) - gaugeV.current) * .12;
        const { c } = fit(gc, 88); const cx = 44, cy = 48, r = 34, a0 = Math.PI * .8, a1 = Math.PI * 2.2;
        c.clearRect(0, 0, 88, 88);
        c.beginPath(); c.arc(cx, cy, r, a0, a1); c.strokeStyle = '#12203a'; c.lineWidth = 8; c.lineCap = 'round'; c.stroke();
        if (gv != null) {
          const a = a0 + (a1 - a0) * gaugeV.current; const g = c.createLinearGradient(0, 0, 88, 0); g.addColorStop(0, '#2f81f7'); g.addColorStop(1, '#38bdf8');
          c.beginPath(); c.arc(cx, cy, r, a0, a); c.strokeStyle = g; c.lineWidth = 8; c.shadowColor = '#2f81f7'; c.shadowBlur = 12; c.stroke(); c.shadowBlur = 0;
          c.beginPath(); c.arc(cx + Math.cos(a) * r, cy + Math.sin(a) * r, 3.2, 0, 7); c.fillStyle = '#eaf2ff'; c.fill();
        }
      }

      const mcv = modelRef.current;
      if (mcv) {
        const { c, w, h } = fit(mcv, 128); c.clearRect(0, 0, w, h);
        for (let i = 0; i <= 4; i++) { const y = 8 + i / 4 * (h - 16); c.beginPath(); c.moveTo(0, y); c.lineTo(w, y); c.strokeStyle = 'rgba(31,51,88,.4)'; c.lineWidth = 1; c.stroke(); }
        const y5 = 8 + (h - 16) * .5; c.beginPath(); c.moveTo(0, y5); c.lineTo(w, y5); c.strokeStyle = 'rgba(74,93,132,.5)'; c.setLineDash([4, 5]); c.stroke(); c.setLineDash([]);
        const isModel = histMode === 'model';
        const raw = modelHist.length ? modelHist : [.5, .5];

        let src: number[];
        if (isModel) src = raw;
        else { const mn = Math.min(...raw), mx = Math.max(...raw), rg = (mx - mn) || 1; src = raw.map(v => (v - mn) / rg * .9 + .05); }
        const X = (i: number, n: number) => i / (n - 1 || 1) * w, Y = (v: number) => 8 + (1 - v) * (h - 16);
        if (isModel) {
          const b = bookHist.length ? bookHist : [.5, .5];
          c.beginPath(); b.forEach((v, i) => i ? c.lineTo(X(i, b.length), Y(v)) : c.moveTo(X(i, b.length), Y(v)));
          c.strokeStyle = 'rgba(90,176,255,.55)'; c.lineWidth = 1.2; c.setLineDash([3, 4]); c.stroke(); c.setLineDash([]);
        }
        c.beginPath(); c.moveTo(0, h); src.forEach((v, i) => c.lineTo(X(i, src.length), Y(v))); c.lineTo(w, h); c.closePath();
        const g = c.createLinearGradient(0, 0, 0, h); g.addColorStop(0, 'rgba(56,189,248,.24)'); g.addColorStop(1, 'rgba(56,189,248,0)'); c.fillStyle = g; c.fill();
        c.beginPath(); src.forEach((v, i) => i ? c.lineTo(X(i, src.length), Y(v)) : c.moveTo(X(i, src.length), Y(v)));
        c.strokeStyle = '#38bdf8'; c.lineWidth = 1.9; c.shadowColor = '#2f81f7'; c.shadowBlur = 8; c.stroke(); c.shadowBlur = 0;
        c.beginPath(); c.arc(w - 2, Y(src[src.length - 1]), 3.2, 0, 7); c.fillStyle = '#eaf2ff'; c.shadowColor = '#38bdf8'; c.shadowBlur = 12; c.fill(); c.shadowBlur = 0;
        c.fillStyle = 'rgba(90,176,255,.7)'; c.font = '8px ui-monospace,monospace'; c.textAlign = 'left'; c.fillText(isModel ? '— model  --- book' : '— spot (normalised)', 6, 14);
      }
      if (stopped) return;
      raf = window.setTimeout(() => { if (!stopped) requestAnimationFrame(draw); }, 70) as unknown as number;
    }
    draw();
    return () => { stopped = true; clearTimeout(raf); };
  }, []);

  const logColor: Record<string, string> = {
    whale: '#fbbf24', momentum: '#7dd3fc', trader: '#a9c7ff', backend: '#38bdf8', discord: '#c4b5fd', main: '#8098c4',
  };
  const uptime = (() => {
    const t = account?.sessionStartedAt ? now - new Date(account.sessionStartedAt).getTime() : 0;
    const s = Math.max(0, (t / 1000) | 0); return `${two((s / 3600) | 0)}:${two(((s / 60) % 60) | 0)}:${two(s % 60)}`;
  })();

  return (
    <div className="kt-root">
      <style>{KT_CSS}</style>
      <div className="kt-app">
        <div className="kt-ticker">
          <div className="kt-brand">
            <div>
              <h1>ROM&nbsp;TERMINAL</h1>
              <div className="kt-sub">SETTLEMENT ENGINE · POLYGON · LIVE FEED</div>
            </div>
          </div>
          <div className={'kt-live' + (isLive ? '' : ' off')}>
            <span className="kt-dot" />{isLive ? 'LIVE' : 'OFFLINE'}
          </div>
          <div className="kt-spots">
            {TICKER_ASSETS.map(sym => {
              const a = assets.find(x => x.asset === sym);

              const d = a?.deltaSignedPct ?? a?.deltaPct ?? null;
              const mh = a?.macdHist ?? (a?.macd != null && a?.macdSignal != null ? a.macd - a.macdSignal : null);
              return (
                <div className="kt-spot" key={sym}>
                  <div className="s">{sym}/USD</div>
                  <div className="v kt-num">{a?.spotUsd != null ? fmtSpot(a.spotUsd) : '—'}</div>
                  <div className="kt-drow">
                    <span className={'kt-num ' + (d == null ? '' : d >= 0 ? 'up' : 'down')}>
                      {d == null ? '—' : (d >= 0 ? '▲' : '▼') + (Math.abs(d) * 100).toFixed(2) + '%'}
                    </span>
                    {mh != null && (
                      <span className={'kt-macd ' + (mh >= 0 ? 'up' : 'down')} title="MACD histogram (Hyperliquid closes)">
                        MACD {mh >= 0 ? '▲' : '▼'}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="kt-clock">
            <div className="t kt-num">{lead ? `${lead.asset} ${(lead.favorite ?? '').toUpperCase()}` : '—'}</div>
            <div className="u">SESSION <span>{uptime}</span></div>
          </div>
        </div>

        <div className="kt-col kt-left">
          <div className="kt-panel">
            <div className="kt-lbl"><b>◈</b> SESSION P&amp;L <span className="tag">WALLET Δ</span></div>
            <div className="kt-pnl-top">
              <div>
                <div className="kt-pnl-big kt-num" style={{ color: sessionPnl >= 0 ? 'var(--win)' : 'var(--loss)' }}>{fmtMoney(sessionPnl)}</div>
                <div className="kt-pnl-sub">REALIZED + MARK-TO-MARKET</div>
              </div>
            </div>
            <canvas ref={eqRef} height={60} />
            <div className="kt-chips">
              <div className="kt-chip"><div className="k">TODAY</div><div className={'v kt-num ' + ((todayPnl ?? 0) >= 0 ? 'g-win' : 'g-loss')}>{fmtMoney(todayPnl)}</div></div>
              <div className="kt-chip"><div className="k">ALL-TIME</div><div className={'v kt-num ' + ((allPnl ?? 0) >= 0 ? 'g-win' : 'g-loss')}>{fmtMoney(allPnl)}</div></div>
              <div className="kt-chip"><div className="k">WIN RATE</div><div className="v kt-num">{winRate != null ? Math.round(winRate * (winRate <= 1 ? 100 : 1)) + '%' : '—'}</div></div>
            </div>
          </div>

          <div className="kt-panel">
            <div className="kt-lbl"><b>◈</b> {gaugeInfo.title} <span className="tag">{gaugeInfo.tag}</span></div>
            <div className="kt-gauge-wrap">
              <canvas ref={gaugeRef} width={150} height={150} style={{ width: 88, height: 88 }} />
              <div className="kt-gauge-meta">
                <div className="g1 kt-num">{gaugeInfo.val != null ? gaugeInfo.val.toFixed(2) : '—'}</div>
                <div className="g2"><span style={{ color: 'var(--pri2)' }}>{gaugeInfo.sub}</span></div>
                <div className="g3">Live {ivLabel} model when a window is open;<br />else the strongest scanner signal.</div>
              </div>
            </div>
          </div>

          <div className="kt-panel">
            <div className="kt-lbl"><b>◈</b> LAST 10 FILLS <span className="tag">SETTLED</span></div>
            <div className="kt-fills">
              {Array.from({ length: 10 }).map((_, i) => {
                const f = fills[fills.length - 10 + i];
                const tip = f ? `${f.label} ${f.side} · entry ${Math.round(f.entry)}c · ${f.pnl != null ? fmtMoney(f.pnl) : 'n/a'} · ${f.w ? 'WON' : 'LOST'}` : 'no fill yet';
                return <div key={i} title={tip} className={'kt-cell' + (f === undefined ? '' : f.w ? ' w' : ' l')} />;
              })}
            </div>
          </div>

          <div className="kt-panel">
            <div className="kt-lbl"><b>◈</b> FEED HEALTH <span className="tag">SOURCES</span></div>
            <div className="kt-feeds">
              {[
                ['coinbase.ws', snap?.spotOk],
                ['rtds.chainlink', snap?.spotSource === 'rtds' || snap?.spotOk],
                ['clob.ws', assets.some(a => a.priceSource === 'ws')],
                ['gamma.rest', assets.some(a => a.hasMarket)],
                ['whale.scan', !!scannerStats?.lastWhaleScanAt],
                ['momentum', !!scannerStats?.lastMomentumScanAt],
                ['account.snap', !!account],
              ].map(([name, ok]) => (
                <div className="kt-feed-row" key={name as string}>
                  <span className="fn">{name}</span>
                  <span className="bar"><i style={{ width: ok ? '100%' : '18%' }} /></span>
                  <span className={'st ' + (ok ? 'on' : 'off')}>{ok ? 'LIVE' : '—'}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="kt-col kt-center">
          <div className="kt-panel kt-field">
            <canvas ref={fieldRef} />
            <div className="kt-title kt-lbl"><b>◈</b> CONVERGENCE FIELD — LIVE SIGNAL FLOW</div>
            <div className="kt-ov a"><div className="k">SIGNALS / MIN</div><div className="v kt-num" style={{ color: 'var(--pri2)' }}>{signalsMin}</div></div>
            <div className="kt-ov b"><div className="k">MARKETS SCANNED</div><div className="v kt-num" style={{ color: 'var(--pri2)' }}>{marketsScanned.toLocaleString()}</div></div>
            <div className="kt-ov c"><div className="k">TRADES / HR</div><div className="v kt-num" style={{ color: 'var(--hot)' }}>{tradesHr}</div></div>
            <div className="kt-ov d"><div className="k">BOOK Δ GAMMA</div><div className="v kt-num" style={{ color: 'var(--hot)' }}>{bookDelta}c</div></div>
            <div className="kt-legend">
              <span><i style={{ background: 'var(--pri2)' }} />ASSET</span>
              <span><i style={{ background: 'var(--warn)' }} />WHALE</span>
              <span><i style={{ background: '#7dd3fc' }} />MOMENTUM</span>
              <span><i style={{ background: 'var(--win)' }} />FILLED</span>
            </div>
          </div>
          <div className="kt-panel">
            <div className="kt-chart-head">
              <div className="kt-lbl"><b>◈</b> {chartInfo.active ? 'MODEL PROB × REAL-BOOK' : 'SPOT MOMENTUM'} — <span style={{ color: 'var(--pri2)' }}>{chartInfo.sym}</span> {chartInfo.active ? `${ivLabel.toUpperCase()} WINDOW` : `· ${ivLabel} idle`}</div>
              <div className="kt-now kt-num">{chartInfo.nowStr}</div>
            </div>
            <canvas ref={modelRef} height={128} />
          </div>
        </div>

        <div className="kt-col kt-right">
          <div className="kt-panel">
            <div className="kt-lbl"><b>◈</b> OPEN POSITIONS <span className="tag">{openRows.length}</span></div>
            <table className="kt-table">
              <thead><tr><th>MKT</th><th>SIDE</th><th>ENTRY</th><th>SZ</th><th>P&amp;L</th></tr></thead>
              <tbody>
                {openRows.length === 0 && <tr><td colSpan={5} style={{ color: 'var(--dim)', textAlign: 'center', padding: '14px 0' }}>no open positions</td></tr>}
                {openRows.map(r => {
                  const up = r.side === 'up' || r.side === 'yes';
                  return (
                    <tr key={r.key}>
                      <td><span className="sym">{r.label}</span></td>
                      <td><span className={'kt-side ' + (up ? 'up' : 'dn')}>{(r.side || '—').toUpperCase()}</span></td>
                      <td>{Number.isFinite(r.entry) ? r.entry + 'c' : '—'}</td>
                      <td>{r.size}</td>
                      <td className={(r.pnl ?? 0) >= 0 ? 'g-win' : 'g-loss'}>{fmtMoney(r.pnl)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="kt-panel kt-term">
            <div className="kt-lbl"><b>◈</b> TRADE LOG — LIVE STREAM <span className="tag">logs:append</span></div>
            <div className="kt-log">
              {logs.slice(-22).map((l, i) => (
                <div className="ln" key={l.ts + i}>
                  <span className="t">{new Date(l.ts).toLocaleTimeString('en-GB')}</span>{' '}
                  <span style={{ color: l.level === 'ERROR' || l.level === 'CRITICAL' ? 'var(--loss)' : l.level === 'WARN' ? 'var(--warn)' : logColor[l.source] || 'var(--mut)' }}>
                    [{l.source}]
                  </span>{' '}
                  <span style={{ color: l.level === 'ERROR' || l.level === 'CRITICAL' ? 'var(--loss)' : 'var(--mut)' }}>{l.msg}</span>
                </div>
              ))}
              {logs.length === 0 && <div className="ln" style={{ color: 'var(--dim)' }}>awaiting backend log stream…</div>}
            </div>
          </div>
          <div className="kt-panel">
            <div className="kt-lbl"><b>◈</b> DECISION TRACE <span className="tag">signal → gate → exec</span></div>
            <div className="kt-tracev">
              {signals.slice(0, 5).map(s => (
                <div className="kt-tchip" key={s.id}>
                  <b>{(s.ticker || s.category || s.source).slice(0, 10)}</b><span className="arw">▸</span>
                  {s.source}<span className="arw">▸</span>conf {(conf01(s.confidence) * 100).toFixed(0)}<span className="arw">▸</span>
                  {s.traded ? <span className="g-win">placed</span> : <span style={{ color: 'var(--dim)' }}>skip</span>}
                </div>
              ))}
              {signals.length === 0 && <div className="kt-tchip" style={{ color: 'var(--dim)' }}>no signals yet — scanners warming up</div>}
            </div>
            <div className="kt-spread-hl">
              <span style={{ color: 'var(--dim)', letterSpacing: '.14em' }}>REAL-BOOK EDGE</span>
              <span className="big kt-num">{bookDelta}c</span>
              <span style={{ color: 'var(--mut)' }}>CLOB ask vs Gamma — the lag is the edge</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function makeOrb(cv: HTMLCanvasElement | null, kind: Orb['kind'], nodes: { x: number; y: number; kind?: string }[]): Orb {
  const w = cv?.clientWidth ?? 600, h = cv?.clientHeight ?? 400;
  const edge = (Math.random() * 4) | 0; let x = 0, y = 0;
  if (edge === 0) { x = Math.random() * w; y = -10; }
  else if (edge === 1) { x = w + 10; y = Math.random() * h; }
  else if (edge === 2) { x = Math.random() * w; y = h + 10; }
  else { x = -10; y = Math.random() * h; }

  let tgt = (kind === 'whale' || kind === 'mom') ? nodes.find(n => n.kind === kind) : undefined;
  if (!tgt) { const a = nodes.filter(n => !n.kind || n.kind === 'asset'); tgt = a.length ? a[(Math.random() * a.length) | 0] : nodes[0]; }
  if (!tgt) tgt = { x: w / 2, y: h / 2 };
  return { x, y, kind, tx: tgt.x, ty: tgt.y, ph: 0, r: kind === 'whale' ? 3 + Math.random() * 2.5 : 1.8 + Math.random() * 1.4 };
}

const KT_CSS = `
.kt-root{--ground:#04070e;--panel:#080f1e;--panel2:#0a1324;--line:#16233f;--line2:#1f3358;
  --pri:#2f81f7;--pri2:#38bdf8;--hot:#5ab0ff;--win:#34d399;--loss:#fb7185;--warn:#fbbf24;
  --tx:#dbe8ff;--mut:#8098c4;--dim:#4a5d84;--dimmer:#33456a;
  --mono:ui-monospace,"Cascadia Code","SF Mono",Menlo,Consolas,monospace;
  height:100%;width:100%;overflow:auto;padding:12px;font-family:var(--mono);color:var(--tx);
  background:radial-gradient(1200px 600px at 50% -8%,rgba(47,129,247,.10),transparent 60%),linear-gradient(180deg,#04070e,#03060d)}
.kt-app{max-width:1520px;margin:0 auto;display:grid;gap:10px;grid-template-columns:262px minmax(0,1fr) 352px;
  grid-template-areas:"ticker ticker ticker" "left center right";grid-template-rows:auto auto;align-items:start}
@media (max-width:1180px){.kt-app{grid-template-columns:1fr;grid-template-areas:"ticker" "center" "left" "right";grid-template-rows:auto}}
.kt-num{font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.kt-panel{position:relative;background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);
  border-radius:9px;padding:11px 12px;overflow:hidden;box-shadow:inset 0 1px 0 rgba(120,170,255,.05),0 8px 26px rgba(0,0,0,.45)}
.kt-lbl{font-size:9.5px;letter-spacing:.22em;text-transform:uppercase;color:var(--dim);display:flex;align-items:center;gap:7px}
.kt-lbl b{color:var(--pri2);font-weight:600}
.kt-lbl .tag{margin-left:auto;color:var(--dimmer);letter-spacing:.14em}
.kt-ticker{grid-area:ticker;display:flex;align-items:center;gap:16px;background:linear-gradient(180deg,#0a1428,#070d1c);
  border:1px solid var(--line);border-radius:9px;padding:9px 14px}
.kt-brand h1{font-size:15px;letter-spacing:.30em;font-weight:700;color:#eaf2ff}
.kt-brand .kt-sub{font-size:8.5px;letter-spacing:.26em;color:var(--dim);margin-top:2px}
.kt-live{display:flex;align-items:center;gap:7px;font-size:10px;letter-spacing:.2em;color:var(--pri2);padding:4px 10px;
  border:1px solid rgba(56,189,248,.3);border-radius:20px;background:rgba(47,129,247,.08);min-width:max-content}
.kt-live.off{color:var(--warn);border-color:rgba(251,191,36,.3);background:rgba(251,191,36,.06)}
.kt-live .kt-dot{width:7px;height:7px;border-radius:50%;background:currentColor;box-shadow:0 0 10px currentColor;animation:ktblink 1.5s infinite}
@keyframes ktblink{0%,100%{opacity:1}50%{opacity:.25}}
.kt-spots{display:flex;gap:9px;flex:1;overflow:hidden;margin-left:4px}
.kt-spot{flex:1;min-width:0;border-left:1px solid var(--line);padding-left:9px}
.kt-spot .s{font-size:9px;letter-spacing:.14em;color:var(--dim)}
.kt-spot .v{font-size:14px;font-weight:600;color:#eaf2ff}
.kt-drow{display:flex;align-items:center;gap:6px;font-size:9.5px;margin-top:1px}
.kt-macd{font-size:8px;letter-spacing:.03em;color:var(--dim)}
.kt-macd.up{color:var(--win)}.kt-macd.down{color:var(--loss)}
.kt-cell[title]{cursor:help}
.up{color:var(--win)!important}.down{color:var(--loss)!important}
.kt-clock{text-align:right;min-width:max-content}
.kt-clock .t{font-size:13px;font-weight:600;color:#eaf2ff}
.kt-clock .u{font-size:8.5px;letter-spacing:.18em;color:var(--dim)}
.kt-col{display:flex;flex-direction:column;gap:10px;min-width:0}
.kt-left{grid-area:left}.kt-center{grid-area:center}.kt-right{grid-area:right}
.kt-center .kt-panel:first-child{height:clamp(300px,40vh,440px)}
.kt-pnl-top{display:flex;align-items:flex-end;justify-content:space-between;margin-top:9px}
.kt-pnl-big{font-size:31px;font-weight:700;line-height:1;letter-spacing:-.03em}
.kt-pnl-sub{font-size:9.5px;color:var(--dim);letter-spacing:.12em;margin-top:6px}
.kt-chips{display:flex;gap:6px;margin-top:9px}
.kt-chip{flex:1;background:var(--ground);border:1px solid var(--line);border-radius:6px;padding:6px 7px;text-align:center}
.kt-chip .k{font-size:8px;letter-spacing:.14em;color:var(--dim)}
.kt-chip .v{font-size:13px;font-weight:600;margin-top:2px}
.g-win{color:var(--win)}.g-loss{color:var(--loss)}
.kt-root canvas{display:block;width:100%}
.kt-gauge-wrap{display:flex;align-items:center;gap:12px;margin-top:6px}
.kt-gauge-wrap canvas{width:88px!important;flex:none}
.kt-gauge-meta .g1{font-size:25px;font-weight:700;letter-spacing:-.02em;color:var(--pri2)}
.kt-gauge-meta .g2{font-size:9px;letter-spacing:.12em;color:var(--dim);margin-top:2px}
.kt-gauge-meta .g3{font-size:9px;color:var(--mut);margin-top:6px;line-height:1.5}
.kt-fills{display:grid;grid-template-columns:repeat(10,1fr);gap:5px;margin-top:9px}
.kt-cell{aspect-ratio:1;border-radius:3px;background:var(--dimmer);transition:background .3s}
.kt-cell.w{background:var(--win);box-shadow:0 0 8px rgba(52,211,153,.55)}
.kt-cell.l{background:var(--loss);box-shadow:0 0 8px rgba(251,113,133,.5)}
.kt-feeds{display:flex;flex-direction:column;gap:5px;margin-top:9px}
.kt-feed-row{display:flex;align-items:center;gap:8px;font-size:10px}
.kt-feed-row .fn{color:var(--mut);width:86px}
.kt-feed-row .bar{flex:1;height:4px;background:var(--ground);border-radius:3px;overflow:hidden}
.kt-feed-row .bar i{display:block;height:100%;background:linear-gradient(90deg,var(--pri),var(--pri2))}
.kt-feed-row .st{width:32px;text-align:right;font-size:9px;letter-spacing:.1em}
.kt-feed-row .st.on{color:var(--pri2)}.kt-feed-row .st.off{color:var(--dimmer)}
.kt-field{position:relative}
.kt-field canvas{position:absolute;inset:0;width:100%!important;height:100%!important}
.kt-ov{position:absolute;z-index:3;pointer-events:none}
.kt-ov .k{font-size:8.5px;letter-spacing:.18em;color:var(--dim)}
.kt-ov .v{font-size:22px;font-weight:700;letter-spacing:-.02em;line-height:1;text-shadow:0 0 18px rgba(47,129,247,.55)}
.kt-ov.a{top:12px;left:14px}.kt-ov.b{top:12px;right:14px;text-align:right}
.kt-ov.c{bottom:12px;left:14px}.kt-ov.d{bottom:12px;right:14px;text-align:right}
.kt-field .kt-title{position:absolute;top:11px;left:50%;transform:translateX(-50%);z-index:3}
.kt-legend{position:absolute;bottom:11px;left:50%;transform:translateX(-50%);z-index:3;display:flex;gap:14px;font-size:8.5px;letter-spacing:.12em;color:var(--dim)}
.kt-legend i{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px;vertical-align:middle}
.kt-chart-head{display:flex;justify-content:space-between;align-items:baseline}
.kt-chart-head .kt-now{font-size:11px;color:var(--pri2)}
.kt-table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
.kt-table th{font-size:8.5px;letter-spacing:.12em;color:var(--dim);text-align:right;padding:7px 6px 6px;font-weight:500;border-bottom:1px solid var(--line)}
.kt-table th:first-child,.kt-table td:first-child{text-align:left}
.kt-table td{font-size:11px;padding:6px;border-bottom:1px solid rgba(22,35,63,.5);color:var(--mut);text-align:right}
.kt-table td .sym{color:#eaf2ff;font-weight:600}
.kt-side{font-size:8.5px;letter-spacing:.08em;padding:1px 5px;border-radius:4px}
.kt-side.up{background:rgba(52,211,153,.13);color:var(--win)}
.kt-side.dn{background:rgba(251,113,133,.13);color:var(--loss)}
.kt-term{display:flex;flex-direction:column}
.kt-log{height:270px;overflow:hidden;margin-top:8px;font-size:10.5px;line-height:1.62;display:flex;flex-direction:column;justify-content:flex-end;
  -webkit-mask-image:linear-gradient(180deg,transparent,#000 22px)}
.kt-tracev{display:flex;flex-direction:column;gap:5px;margin-top:8px}
.kt-tracev .kt-tchip{white-space:normal;font-size:10px}
.kt-log .ln{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kt-log .t{color:var(--dimmer)}
.kt-tchip{display:flex;align-items:center;gap:7px;font-size:10px;color:var(--mut);border:1px solid var(--line);border-radius:6px;
  padding:4px 9px;white-space:nowrap;background:var(--ground)}
.kt-tchip b{color:var(--pri2);font-weight:600}
.kt-tchip .arw{color:var(--dimmer)}
.kt-spread-hl{margin-top:9px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:9.5px;padding:7px 10px;
  border:1px solid rgba(56,189,248,.22);border-radius:7px;background:linear-gradient(90deg,rgba(47,129,247,.10),transparent)}
.kt-spread-hl .big{font-size:15px;font-weight:700;color:var(--pri2)}
@media (prefers-reduced-motion:reduce){.kt-live .kt-dot{animation:none}}
`;
