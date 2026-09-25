import { useEffect, useState } from 'react';
import { AlertTriangle, ArrowUpRight, CheckCircle2, Circle, Gift, KeyRound, LockKeyhole, Radio, ShieldCheck } from 'lucide-react';
import type { TradingStatus } from '@shared/types';
import { Card, Page } from '../components/common';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { POLYMARKET_REFERRAL_CODE, POLYMARKET_REFERRAL_URL } from '../utils/links';
import { cls, fmtUsd } from '../utils/format';

type Preflight = {
  ok: boolean;
  balanceUsd: number;
  issues: string[];
  execution: TradingStatus['executionHealth'] | null;
};

export function ApiKeysPage() {
  const { backend, refresh } = useApp();
  const toast = useToast();
  const [keyId, setKeyId] = useState('');
  const [secretKey, setSecretKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState('');
  const [preflight, setPreflight] = useState<Preflight | null>(null);

  useEffect(() => {
    if (backend.authError) setPreflight(null);
  }, [backend.authError]);

  const update = async () => {
    await refresh.credentials();
    await refresh.backend();
    await refresh.account();
  };
  const test = async () => {
    try {
      const result = await window.rom.credentials.test('mainnet');
      if (!result.ok) throw new Error(result.message || 'Connection failed');
      const status = await window.rom.trading.status().catch(() => null);
      const next: Preflight = {
        ok: result.data?.ready !== false,
        balanceUsd: result.data?.balanceUsd ?? 0,
        issues: result.data?.issues ?? [],
        execution: status?.executionHealth ?? null,
      };
      setPreflight(next);
      toast.success(`Connected to Polymarket US · buying power ${fmtUsd(next.balanceUsd)}`);
    } catch (error) {
      setPreflight({ ok: false, balanceUsd: 0, issues: [error instanceof Error ? error.message : 'Connection failed'], execution: null });
      throw error;
    }
  };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try { await fn(); }
    catch (error) { toast.error(error instanceof Error ? error.message : 'Request failed'); }
    finally {
      try { await update(); } catch { toast.error('Could not refresh connection status'); }
      finally { setBusy(false); }
    }
  };

  return <Page title="Polymarket US API" subtitle="One connection. Your entire trading workspace.">
    <div className="mb-6 flex items-center justify-between gap-4 rounded-xl border border-rom-border bg-rom-surface p-5">
      <div className="flex items-center gap-4"><div className="grid h-12 w-12 place-items-center rounded-xl bg-blue-500/10 text-blue-300"><KeyRound className="h-6 w-6" /></div><div><h3 className="font-semibold">Polymarket US</h3><p className="mt-1 text-xs text-rom-muted">Official exchange API connection</p></div></div>
      <span className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs ${backend.authOk ? 'border-rom-win/20 bg-rom-win/10 text-rom-win' : 'border-rom-border text-rom-muted'}`}>{backend.authOk ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Circle className="h-3 w-3" />}{backend.authOk ? 'Connected' : 'Not connected'}</span>
    </div>
    {!backend.authOk && backend.authError && <div role="alert" className="mb-6 rounded-xl border border-rom-warn/30 bg-rom-warn/[0.06] p-4 text-sm leading-6 text-rom-warn">{backend.authError}</div>}
    <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(260px,1fr)]">
      <Card>
        <div className="mb-7"><h3 className="text-base font-semibold">Connect your account</h3><p className="mt-2 text-sm leading-relaxed text-rom-muted">Enter the API credentials from your Polymarket US account.</p></div>
        <form noValidate className="space-y-5" onSubmit={(event) => {
          event.preventDefault();
          if (busy) return;
          if (!keyId.trim() || !secretKey.trim()) {
            setFormError('Enter both your Key ID and Secret Key.');
            event.currentTarget.querySelectorAll('input')[keyId.trim() ? 1 : 0]?.focus();
            return;
          }
          setFormError('');
          void run(async () => {
            const result = await window.rom.credentials.save({ keyId: keyId.trim(), secretKey: secretKey.trim(), env: 'mainnet' });
            if (!result.ok) throw new Error(result.message || 'Save failed');
            setSecretKey('');
            await test();
          });
        }}>
          <label className="block text-sm font-medium">Key ID<input className="rom-input mt-2" required aria-invalid={!!formError && !keyId.trim()} aria-describedby={formError ? 'api-form-error' : undefined} autoComplete="off" value={keyId} onChange={(event) => setKeyId(event.target.value)} placeholder="Enter your API Key ID" /></label>
          <label className="block text-sm font-medium">Secret Key<input className="rom-input mt-2" required aria-invalid={!!formError && !secretKey.trim()} aria-describedby={formError ? 'api-form-error' : undefined} type="password" autoComplete="new-password" value={secretKey} onChange={(event) => setSecretKey(event.target.value)} placeholder="Enter your Secret Key" /></label>
          {formError && <p id="api-form-error" role="alert" className="text-xs text-rom-lossText">{formError}</p>}
          <div className="flex items-start gap-2 rounded-lg bg-rom-void/50 p-3 text-xs leading-relaxed text-rom-muted"><LockKeyhole className="mt-0.5 h-4 w-4 shrink-0 text-rom-purple" />Credentials are stored locally and encrypted with a key protected by your operating system.</div>
          <div className="flex flex-wrap gap-2 border-t border-rom-border pt-5"><button disabled={busy} className="rom-btn-primary" type="submit">{busy ? 'Connecting…' : 'Save and connect'}</button><button disabled={busy} className="rom-btn-default" type="button" onClick={() => void run(test)}>Test saved credentials</button></div>
          <button disabled={busy} className="text-xs text-rom-dim hover:text-rom-lossText disabled:opacity-50" type="button" onClick={() => void run(async () => {
            const result = await window.rom.credentials.clear('mainnet');
            if (!result.ok) throw new Error(result.message);
            setSecretKey('');
            setPreflight(null);
            toast.success('Credentials removed');
          })}>Delete credentials</button>
        </form>
        {preflight && <ConnectionPreflight report={preflight} />}
      </Card>
      <div className="space-y-5">
        <div className="rounded-xl border border-blue-400/20 bg-gradient-to-br from-blue-500/10 to-rom-purple/5 p-5"><div className="flex items-start gap-3"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-blue-400/10 text-blue-300"><Gift className="h-5 w-5" /></div><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-300">New-user offer</p><h3 className="mt-1 font-semibold">See the current offer</h3></div></div><p className="mt-3 text-xs leading-relaxed text-rom-muted">Join Polymarket US with code <span className="font-semibold text-rom-text">{POLYMARKET_REFERRAL_CODE}</span> to see the amount, eligibility and qualifying steps set by Polymarket US.</p><button className="rom-btn-primary mt-4 w-full" type="button" onClick={() => void window.rom.app.openExternal(POLYMARKET_REFERRAL_URL)}>View current offer<ArrowUpRight className="h-4 w-4" /></button><p className="mt-3 text-[11px] leading-relaxed text-rom-dim">Eligibility and Polymarket terms apply. Offer may change or expire. ROM may also receive a referral reward.</p></div>
        <Card><h3 className="font-semibold">Get connected</h3><ol className="mt-5 space-y-5">{[['Verify your account', 'Complete account verification with Polymarket US.'], ['Create API credentials', 'Generate a Key ID and Secret Key in the developer portal.'], ['Connect and review', 'Save your credentials, then review your strategies and risk limits.']].map(([title, description], index) => <li key={title} className="flex gap-3"><span className="grid h-6 w-6 shrink-0 place-items-center rounded-full border border-rom-border text-[11px] text-rom-purple">{index + 1}</span><div><p className="text-sm font-medium">{title}</p><p className="mt-1 text-xs leading-relaxed text-rom-muted">{description}</p></div></li>)}</ol><button className="rom-btn-default mt-6 w-full" onClick={() => void window.rom.app.openExternal('https://polymarket.us/developer')}>Open developer portal<ArrowUpRight className="h-4 w-4" /></button></Card>
        <div className="flex gap-3 px-1 text-xs leading-relaxed text-rom-muted"><ShieldCheck className="h-5 w-5 shrink-0 text-rom-win" /><p>Connection tests are read-only. Trading is controlled separately in each engine.</p></div>
      </div>
    </div>
  </Page>;
}

function ConnectionPreflight({ report }: { report: Preflight }) {
  const executionBlocked = !!report.execution?.blocked;
  const checks = [
    ['Account read', report.ok ? 'Passed' : 'Needs attention', report.ok ? 'Authenticated balance endpoint responded.' : report.issues[0] || 'Connection could not be confirmed.'],
    ['Buying power', fmtUsd(report.balanceUsd), report.balanceUsd > 0 ? 'Available for sizing.' : 'No available USD buying power reported.'],
    ['Execution guard', executionBlocked ? 'Paused for safety' : 'Clear', executionBlocked ? report.execution?.reason || 'Review execution health.' : report.execution?.marketStream.connected ? 'Live price stream connected.' : 'REST fallback remains available while the stream reconnects.'],
  ];
  return <section className={cls('mt-6 rounded-xl border p-4', report.ok && !executionBlocked ? 'border-rom-win/25 bg-rom-win/[0.04]' : 'border-rom-warn/30 bg-rom-warn/[0.04]')} aria-labelledby="connection-preflight-title">
    <div className="flex items-start gap-3"><div className={cls('grid h-9 w-9 shrink-0 place-items-center rounded-lg', report.ok && !executionBlocked ? 'bg-rom-win/10 text-rom-win' : 'bg-rom-warn/10 text-rom-warn')}>{report.ok && !executionBlocked ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}</div><div><h3 id="connection-preflight-title" className="text-sm font-semibold">Connection preflight</h3><p className="mt-1 text-xs leading-5 text-rom-muted">Read-only account and local execution checks. No order was sent.</p></div></div>
    <dl className="mt-4 grid gap-4 border-t border-rom-border pt-4 sm:grid-cols-3">{checks.map(([label, value, detail]) => <div key={label}><dt className="text-[11px] uppercase tracking-wide text-rom-dim">{label}</dt><dd className="mt-1 text-sm font-semibold">{value}</dd><p className="mt-1 text-xs leading-4 text-rom-muted">{detail}</p></div>)}</dl>
    {report.issues.length > 0 && <p role="alert" className="mt-4 flex gap-2 border-t border-rom-border pt-3 text-xs leading-5 text-rom-warn"><Radio className="mt-0.5 h-3.5 w-3.5 shrink-0" />{report.issues.join(' ')}</p>}
  </section>;
}
