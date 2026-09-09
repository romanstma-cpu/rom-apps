import { useEffect, useRef, useState } from 'react';
import { X, Swords } from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import spriteUrl from '../assets/rom-mark.png';

const MIL = [10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000];
const NAMES = [
  'Slimeling', 'Gnawbat', 'Penny Wraith', 'Bench Golem', 'Margin Imp',
  'Bull Reaper', 'Drawdown Fiend', 'Vol Behemoth', 'Liquidity Kraken', 'THE WHALE',
];
const COLORS = [
  '#22C55E', '#14B8A6', '#3B82F6', '#6366F1', '#8B5CF6',
  '#A855F7', '#D946EF', '#EF4444', '#F97316', '#F59E0B',
];
const ARCHE: Record<string, number[]> = {
  slime: [1, 3, 4, 5, 5, 6, 6, 6, 6, 6],
  round: [2, 4, 5, 6, 6, 6, 6, 5, 4, 2],
  ghost: [2, 4, 5, 6, 6, 6, 6, 6, 6, 6],
  spiky: [1, 2, 4, 5, 6, 6, 6, 6, 5, 4],
};
const ARCH_BY_TIER = ['slime', 'round', 'ghost', 'spiky', 'round', 'slime', 'spiky', 'ghost', 'round', 'spiky'];

function shade(hex: string, f: number): string {
  const n = parseInt(hex.slice(1), 16);
  const r = Math.min(255, ((n >> 16) & 255) * f) | 0;
  const g = Math.min(255, ((n >> 8) & 255) * f) | 0;
  const b = Math.min(255, (n & 255) * f) | 0;
  return `rgb(${r},${g},${b})`;
}
function px(ctx: CanvasRenderingContext2D, x: number, y: number, s: number, col: string): void {
  ctx.fillStyle = col;
  ctx.fillRect(Math.round(x), Math.round(y), Math.ceil(s), Math.ceil(s));
}
function roundFill(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.fill();
}

function drawBoss(ctx: CanvasRenderingContext2D, cx: number, cy: number, p: number, idx: number, t: number): void {
  const col = COLORS[idx], dark = shade(col, 0.55), light = shade(col, 1.3);
  const sil = ARCHE[ARCH_BY_TIER[idx]] || ARCHE.round;
  const rows = sil.length;
  const eyes = Math.min(3, 1 + Math.floor(idx / 3));
  const spikes = Math.min(7, Math.max(0, idx - 1));
  const aura = idx >= 4;
  const bob = Math.sin(t / 350 + idx) * 1.3;
  const oy = cy + bob * p;
  const topY = oy - (rows / 2) * p;
  ctx.imageSmoothingEnabled = false;

  if (aura) {
    const g = ctx.createRadialGradient(cx, oy, p, cx, oy, p * 8);
    g.addColorStop(0, col + '55'); g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g; ctx.fillRect(cx - p * 8, oy - p * 8, p * 16, p * 16);
  }
  for (let i = 0; i < spikes; i++) {
    const sx = cx + (i - (spikes - 1) / 2) * (p * (sil[0] * 2.2) / Math.max(1, spikes));
    for (let h = 0; h < 3; h++) { const w = 3 - h; px(ctx, sx - (w * p) / 2, topY - (h + 1) * p, p * w, dark); }
  }
  for (let r = 0; r < rows; r++) {
    const hw = sil[r];
    if (ARCH_BY_TIER[idx] === 'ghost' && r === rows - 1) {
      for (let gx = -hw; gx <= hw; gx++) { if ((gx + hw) % 3 === 1) continue; px(ctx, cx + gx * p - p / 2, topY + r * p, p, col); }
      continue;
    }
    for (let gx = -hw; gx <= hw; gx++) {
      const edge = gx === -hw || gx === hw || r === 0;
      px(ctx, cx + gx * p - p / 2, topY + r * p, p, edge ? dark : col);
    }
  }
  for (let r = 2; r < 5; r++) for (let gx = -1; gx <= 1; gx++) px(ctx, cx + gx * p - p / 2, topY + r * p, p, light);
  const eyeY = topY + 2 * p;
  ctx.save(); ctx.shadowColor = col; ctx.shadowBlur = p * 2;
  for (let e = 0; e < eyes; e++) {
    const ex = cx + (e - (eyes - 1) / 2) * 2.4 * p;
    px(ctx, ex - p, eyeY, p * 2, '#FFFFFF'); px(ctx, ex - p / 2, eyeY + p * 0.4, p, '#0A0A0F');
  }
  ctx.restore();
  if (idx >= 3) { const my = topY + (rows - 3) * p; for (let gx = -3; gx <= 3; gx++) if (gx % 2 === 0) px(ctx, cx + gx * p - p / 2, my, p, '#0A0A0F'); }
}

function drawBluey(ctx: CanvasRenderingContext2D, sprite: HTMLImageElement, x: number, y: number, size: number, frame: number): void {
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(sprite, (frame % 8) * 48, 0, 48, 48, x, y, size, size);
}

interface Game { idx: number; hp: number; defeated: number; won: boolean; }
function gameState(pnl: number): Game {
  let idx = MIL.findIndex((m) => pnl < m);
  const won = idx === -1;
  if (won) idx = MIL.length - 1;
  const prev = idx > 0 ? MIL[idx - 1] : 0;
  const hp = won ? 0 : Math.max(0, Math.min(1, (MIL[idx] - pnl) / (MIL[idx] - prev)));
  const defeated = MIL.filter((m) => pnl >= m).length;
  return { idx, hp, defeated, won };
}

function drawScene(ctx: CanvasRenderingContext2D, w: number, h: number, sprite: HTMLImageElement, frame: number, g: Game, t: number, compact = false): void {
  ctx.clearRect(0, 0, w, h);
  const bluS = h * 0.8, bluX = h * 0.05;
  drawBluey(ctx, sprite, bluX, (h - bluS) / 2 + h * 0.04, bluS, frame);
  const p = Math.max(2, Math.round(h / 20));
  const bcx = w - h * 0.42, bcy = h * 0.40;
  if (!g.won) drawBoss(ctx, bcx, bcy, p, g.idx, t);
  else {
    drawBoss(ctx, bcx, bcy, p, g.idx, t);
    ctx.save(); ctx.globalAlpha = 0.25; ctx.fillStyle = '#0A0A0F'; ctx.fillRect(bcx - p * 9, bcy - p * 9, p * 18, p * 18); ctx.restore();
  }
  const x0 = bluX + bluS + h * 0.12, x1 = bcx - p * 7, bw = Math.max(20, x1 - x0);
  const mid = (x0 + x1) / 2, col = COLORS[g.idx];
  const by = h * 0.82, bh = h * 0.1;
  if (compact) {
    ctx.textAlign = 'center';
    ctx.save(); ctx.shadowColor = col; ctx.shadowBlur = h * 0.06; ctx.fillStyle = '#fff';
    ctx.font = `700 ${Math.round(h * 0.36)}px "Chakra Petch", sans-serif`;
    ctx.fillText(g.won ? 'WON' : `$${MIL[g.idx].toLocaleString()}`, mid, h * 0.47);
    ctx.restore();
    ctx.fillStyle = 'rgba(161,161,170,0.95)';
    ctx.font = `600 ${Math.round(h * 0.16)}px "Chakra Petch", sans-serif`;
    ctx.fillText(g.won ? 'CHAMPION' : 'PROFIT', mid, h * 0.67);
  } else {
    ctx.textAlign = 'center'; ctx.fillStyle = '#fff';
    ctx.font = `700 ${Math.round(h * 0.15)}px "Chakra Petch", sans-serif`;
    ctx.fillText(g.won ? 'CHAMPION' : `$${MIL[g.idx].toLocaleString()}`, mid, by - h * 0.08);
  }
  ctx.fillStyle = 'rgba(255,255,255,0.10)'; roundFill(ctx, x0, by, bw, bh, bh / 2);
  ctx.save(); ctx.shadowColor = col; ctx.shadowBlur = h * 0.05; ctx.fillStyle = col;
  roundFill(ctx, x0, by, Math.max(bh, bw * g.hp), bh, bh / 2); ctx.restore();
}

const WW = 420, WH = 92;

export function BossWidget() {
  const [open, setOpen] = useState(false);
  const [sprite, setSprite] = useState<HTMLImageElement | null>(null);
  useEffect(() => { const i = new Image(); i.onload = () => setSprite(i); i.src = spriteUrl; }, []);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title="Open the profit milestone arena"
        className="hidden rounded-lg border border-rom-border px-3 py-2 text-xs text-rom-muted hover:border-rom-purple/50 hover:text-white xl:block"
      >Milestones
      </button>
      {open && <BossArena onClose={() => setOpen(false)} sprite={sprite} />}
    </>
  );
}

const AW = 880, AH = 380;

function BossArena({ onClose, sprite }: { onClose: () => void; sprite: HTMLImageElement | null }) {
  const { account } = useApp();
  const pnl = account?.alltimePnlUsd ?? account?.realizedPnlUsd ?? 0;
  const g = gameState(pnl);
  const gRef = useRef(g); gRef.current = g;
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!sprite) return;
    const ctx = canvasRef.current?.getContext('2d'); if (!ctx) return;
    let raf = 0, last = 0, frame = 0, cancelled = false;
    const loop = (t: number) => {
      if (cancelled) return;
      if (document.hidden) { window.setTimeout(() => { if (!cancelled) raf = requestAnimationFrame(loop); }, 500); return; }
      if (t - last > 110) { frame = (frame + 1) % 8; last = t; }
      drawScene(ctx, AW, AH, sprite, frame, gRef.current, t);
      raf = requestAnimationFrame(loop);
    };
    const start = () => { if (!cancelled) raf = requestAnimationFrame(loop); };
    if (document.fonts?.ready) document.fonts.ready.then(start).catch(start); else start();
    return () => { cancelled = true; cancelAnimationFrame(raf); };
  }, [sprite]);

  const next = g.won ? null : MIL[g.idx];
  const toGo = next == null ? 0 : Math.max(0, next - pnl);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/75 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div
        className="w-full max-w-2xl rounded-2xl border border-rom-border bg-rom-surface p-5 shadow-rom-strong"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center gap-2">
          <Swords className="h-5 w-5 text-rom-purple" />
          <h3 className="font-pixel text-[11px] uppercase tracking-[0.18em] text-white">Boss Fight</h3>
          <button onClick={onClose} className="rom-btn-ghost ml-auto" aria-label="Close"><X className="h-4 w-4" /></button>
        </div>

        <div className="rounded-xl border border-rom-border bg-rom-void/60 bg-rom-radial">
          <canvas ref={canvasRef} width={AW} height={AH} className="w-full" style={{ aspectRatio: `${AW}/${AH}` }} />
        </div>

        <div className="mt-4 flex items-end justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-rom-muted">
              {g.won ? 'Final boss' : `Boss ${g.idx + 1} of ${MIL.length}`}
            </div>
            <div className="text-lg font-semibold text-white" style={{ color: COLORS[g.idx] }}>{NAMES[g.idx]}</div>
          </div>
          <div className="text-right">
            <div className="text-[11px] uppercase tracking-wider text-rom-muted">
              {g.won ? 'You beat them all' : 'Profit to defeat'}
            </div>
            <div className="font-mono text-lg text-white">
              {g.won ? '🏆 CHAMPION' : `$${toGo.toLocaleString('en-US', { maximumFractionDigits: 2 })} to go`}
            </div>
          </div>
        </div>

        <div className="mt-4 flex items-center justify-between gap-1">
          {MIL.map((m, i) => {
            const beaten = g.defeated > i;
            const current = !g.won && i === g.idx;
            return (
              <div key={m} className="flex flex-1 flex-col items-center gap-1" title={`${NAMES[i]} · $${m.toLocaleString()}`}>
                <span
                  className="h-3 w-3 rounded-full transition-all"
                  style={{
                    background: beaten || current ? COLORS[i] : 'rgba(255,255,255,0.12)',
                    boxShadow: current ? `0 0 10px ${COLORS[i]}` : 'none',
                    opacity: beaten ? 1 : current ? 1 : 0.5,
                  }}
                />
                <span className={`text-[9px] ${current ? 'text-white' : 'text-rom-dim'}`}>
                  {m >= 1000 ? `${m / 1000}k` : m}
                </span>
              </div>
            );
          })}
        </div>
        <p className="mt-3 text-center text-[11px] text-rom-dim">
          Your all-time profit is the damage. Keep trading green to take down {g.won ? 'no one left!' : NAMES[g.idx]}.
        </p>
      </div>
    </div>
  );
}
