import { useEffect, useRef, useState } from 'react';
import { X, Download, Copy } from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import spriteUrl from '../assets/rom-mark.png';

const W = 1080;
const H = 1350;
const FRAMES = 8;
const FRAME_PX = 48;
const SITE_URL = 'polymarket.us';

interface Stats { pnl: number; volume: number; trades: number; }

function money(n: number, dp = 0): string {
  return n.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function drawStat(ctx: CanvasRenderingContext2D, x: number, label: string, value: string) {
  ctx.textAlign = 'center';
  ctx.font = '600 32px "Chakra Petch", sans-serif';
  ctx.fillStyle = 'rgba(161,161,170,0.95)';
  ctx.fillText(label, x, 1000);
  ctx.font = '700 66px "JetBrains Mono", monospace';
  ctx.fillStyle = '#FFFFFF';
  ctx.fillText(value, x, 1072);
}

function drawCard(ctx: CanvasRenderingContext2D, sprite: HTMLImageElement, frame: number, s: Stats) {
  ctx.fillStyle = '#0A0A0F';
  ctx.fillRect(0, 0, W, H);
  let g = ctx.createRadialGradient(W / 2, H * 0.30, 60, W / 2, H * 0.30, W * 0.85);
  g.addColorStop(0, 'rgba(59,130,246,0.30)');
  g.addColorStop(1, 'rgba(10,10,15,0)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  g = ctx.createRadialGradient(W / 2, H * 0.95, 40, W / 2, H * 0.95, W * 0.7);
  g.addColorStop(0, 'rgba(56,189,248,0.12)');
  g.addColorStop(1, 'rgba(10,10,15,0)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);

  ctx.save();
  ctx.shadowColor = 'rgba(59,130,246,0.45)'; ctx.shadowBlur = 30;
  ctx.lineWidth = 5; ctx.strokeStyle = 'rgba(99,140,246,0.45)';
  roundRect(ctx, 26, 26, W - 52, H - 52, 40); ctx.stroke();
  ctx.restore();

  ctx.textAlign = 'center';
  ctx.fillStyle = 'rgba(255,255,255,0.95)';
  ctx.font = '34px "Press Start 2P", monospace';
  ctx.fillText('ROM POLYBOT', W / 2, 140);
  ctx.font = '500 30px "Chakra Petch", sans-serif';
  ctx.fillStyle = 'rgba(161,161,170,0.9)';
  ctx.fillText('A U T O - T R A D E R   S T A T S', W / 2, 192);

  const size = 300;
  g = ctx.createRadialGradient(W / 2, 560, 10, W / 2, 560, 230);
  g.addColorStop(0, 'rgba(56,189,248,0.32)');
  g.addColorStop(1, 'rgba(10,10,15,0)');
  ctx.fillStyle = g; ctx.beginPath(); ctx.ellipse(W / 2, 560, 230, 80, 0, 0, Math.PI * 2); ctx.fill();
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(sprite, (frame % FRAMES) * FRAME_PX, 0, FRAME_PX, FRAME_PX, W / 2 - size / 2, 270, size, size);
  ctx.imageSmoothingEnabled = true;

  const pos = s.pnl >= 0;
  const col = pos ? '#22C55E' : '#EF4444';
  ctx.font = '600 34px "Chakra Petch", sans-serif';
  ctx.fillStyle = 'rgba(161,161,170,0.95)';
  ctx.fillText('PROFIT / LOSS', W / 2, 700);
  ctx.save();
  ctx.shadowColor = col; ctx.shadowBlur = 45;
  ctx.fillStyle = col;
  ctx.font = '700 118px "JetBrains Mono", monospace';
  ctx.fillText(`${pos ? '+' : '-'}$${money(Math.abs(s.pnl), 2)}`, W / 2, 815);
  ctx.restore();

  drawStat(ctx, W * 0.30, 'VOLUME', `$${money(s.volume)}`);
  drawStat(ctx, W * 0.70, 'TRADES', `${money(s.trades)}`);
  ctx.strokeStyle = 'rgba(255,255,255,0.10)'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(W / 2, 952); ctx.lineTo(W / 2, 1052); ctx.stroke();

  ctx.save();
  ctx.shadowColor = 'rgba(56,189,248,0.6)'; ctx.shadowBlur = 18;
  ctx.font = '600 40px "Chakra Petch", sans-serif';
  ctx.fillStyle = '#38BDF8';
  ctx.fillText(SITE_URL, W / 2, H - 110);
  ctx.restore();
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
function useFocusTrap(open: boolean, containerRef: React.RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    if (!open || !containerRef.current) return;

    const el = containerRef.current;
    const prevFocus = document.activeElement as HTMLElement | null;

    // Focus first focusable element in the dialog on open
    const first = el.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();

    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // Let the caller handle close via onClose
        return;
      }
      if (e.key !== 'Tab') return;

      const nodes = el.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener('keydown', handler);

    // Disable scroll behind the dialog
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', handler);
      document.body.style.overflow = '';
      prevFocus?.focus();
    };
  }, [open, containerRef]);
}

  export function FlexStatsCard({ onClose }: { onClose: () => void }) {

  const { account, positions } = useApp();
  const cardRef = useRef<HTMLDivElement>(null);


  const toast = useToast();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [sprite, setSprite] = useState<HTMLImageElement | null>(null);

  const stats: Stats = {
    pnl: account?.alltimePnlUsd ?? account?.realizedPnlUsd ?? 0,
    volume: positions.reduce((acc, p) => acc + (p.costUsd || 0), 0),
    trades: account?.totalOpened ?? positions.filter((p) => (p.filledContracts || 0) > 0).length,
  };
  const statsRef = useRef(stats);
  statsRef.current = stats;

  useEffect(() => {
    const img = new Image();
    img.onload = () => setSprite(img);
    img.src = spriteUrl;
  }, []);

  useEffect(() => {
    if (!sprite) return;
    const ctx = canvasRef.current?.getContext('2d');
    if (!ctx) return;
    let raf = 0; let last = 0; let cancelled = false;
    let frame = 0;
    const loop = (t: number) => {
      if (cancelled) return;
      if (t - last > 110) { frame = (frame + 1) % FRAMES; last = t; }
      drawCard(ctx, sprite, frame, statsRef.current);
      raf = requestAnimationFrame(loop);
    };
    const start = () => { if (!cancelled) raf = requestAnimationFrame(loop); };

    if (document.fonts?.ready) document.fonts.ready.then(start).catch(start);
    else start();
    return () => { cancelled = true; cancelAnimationFrame(raf); };
  }, [sprite]);

  const save = (): void => {
    canvasRef.current?.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'rom-stats.png'; a.click();
      URL.revokeObjectURL(url);
      toast.success('Saved rom-stats.png');
    }, 'image/png');
  };

  const copy = (): void => {
    canvasRef.current?.toBlob(async (blob) => {
      if (!blob) return;
      try {
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
        toast.success('Copied to clipboard');
      } catch {
        toast.error('Copy failed — use Save instead');
      }
    }, 'image/png');
  };

  useFocusTrap(true, cardRef);

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/75 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Shareable stats"
      onMouseDown={onClose}
    >
      <div ref={cardRef} className="flex flex-col items-center gap-4" onMouseDown={(e) => e.stopPropagation()}>
        <canvas
          ref={canvasRef}
          width={W}
          height={H}
          className="rounded-2xl border border-rom-border shadow-rom-strong"
          style={{ width: 312, height: 390 }}
        />
        <div className="flex items-center gap-2">
          <button onClick={save} className="rom-btn-primary">
            <Download className="h-4 w-4" /> Save Image
          </button>
          <button onClick={copy} className="rom-btn-default">
            <Copy className="h-4 w-4" /> Copy
          </button>
          <button onClick={onClose} className="rom-btn-ghost" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
