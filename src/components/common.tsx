import { ReactNode, useEffect, useRef, useState } from 'react';
import { Share2 } from 'lucide-react';
import { cls } from '../utils/format';
import { shareToX, X_PROFILE } from '../utils/share';
import type { RuleCondition, TraderConfig } from '@shared/types';

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

export function NameDialog({
  open, title, label, initialValue = '', placeholder, confirmLabel = 'Save',
  onSubmit, onClose,
}: {
  open: boolean;
  title: string;
  label?: string;
  initialValue?: string;
  placeholder?: string;
  confirmLabel?: string;
  onSubmit: (value: string) => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState(initialValue);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  useFocusTrap(open, containerRef);

  useEffect(() => {
    if (!open) return;
    setValue(initialValue);
    const t = setTimeout(() => inputRef.current?.select(), 30);
    return () => clearTimeout(t);
  }, [open, initialValue]);

  if (!open) return null;

  const submit = (): void => {
    const v = value.trim();
    if (!v) return;
    onSubmit(v);
  };

  return (
      <div
        className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={onClose}
      >
        <div
          ref={containerRef}
          className="w-full max-w-sm rounded-xl border border-rom-border bg-rom-surface p-5 shadow-rom-soft"
          onMouseDown={(e) => e.stopPropagation()}
        >
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        {label && <p className="mt-1 text-xs text-rom-muted">{label}</p>}
        <input
          ref={inputRef}
          autoFocus
          value={value}
          placeholder={placeholder}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); submit(); }
            else if (e.key === 'Escape') { e.preventDefault(); onClose(); }
          }}
          className="rom-input mt-3 w-full"
        />
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="rom-btn-default">Cancel</button>
          <button onClick={submit} disabled={!value.trim()} className="rom-btn-primary">
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function Page({
  title, subtitle, actions, children,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-4 px-8 py-7">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-white">{title}</h2>
          {subtitle && (
            <p className="mt-1 text-sm text-rom-muted">{subtitle}</p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-8 pb-8">{children}</div>
    </div>
  );
}

export function Card({
  className, children, header, footer,
}: {
  className?: string;
  children: ReactNode;
  header?: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className={cls('rom-card', className)}>
      {header && (
        <div className="-mx-5 -mt-5 mb-4 border-b border-rom-border bg-rom-surface2/60 px-5 py-3">
          {header}
        </div>
      )}
      {children}
      {footer && (
        <div className="-mx-5 -mb-5 mt-4 border-t border-rom-border bg-rom-surface2/60 px-5 py-3">
          {footer}
        </div>
      )}
    </div>
  );
}

export function StatCard({
  label, value, hint, accent, className,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  accent?: 'good' | 'bad' | 'warn' | 'neutral';
  className?: string;
}) {
  const ring =
    accent === 'good' ? 'border-rom-win/20' :
    accent === 'bad' ? 'border-rom-loss/20' :
    accent === 'warn' ? 'border-rom-warn/20' :
    '';
  return (
    <div className={cls('rom-card', ring, className)}>
      <div className="text-[11px] uppercase tracking-wider text-rom-muted">{label}</div>
      <div className="mt-3 font-sans text-3xl font-semibold tracking-tight tabular-nums text-white">{value}</div>
      {hint && <div className="mt-1 text-xs text-rom-dim">{hint}</div>}
    </div>
  );
}

export function ShareableStat({
  label, value, hint, accent, className, shareText,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  accent?: 'good' | 'bad' | 'warn' | 'neutral';
  className?: string;
  shareText: string;
}) {
  return (
    <div className={cls('relative', className)}>
      <StatCard label={label} value={value} hint={hint} accent={accent} />
      <ShareButton text={shareText} className="absolute right-3 top-3" />
    </div>
  );
}

export function ShareButton({
  text, className, size = 'sm',
}: {
  text: string;
  className?: string;
  size?: 'sm' | 'xs';
}) {
  const sz = size === 'xs' ? 'h-6 w-6' : 'h-7 w-7';
  const ic = size === 'xs' ? 'h-3 w-3' : 'h-3.5 w-3.5';
  return (
    <button
      onClick={() => void shareToX(text)}
      title={`Share to ${X_PROFILE}`}
      className={cls(
        'grid place-items-center rounded-md border border-rom-border bg-rom-surface2 text-rom-muted transition-colors hover:border-rom-purple/40 hover:bg-rom-purple/10 hover:text-white',
        sz,
        className,
      )}
    >
      <Share2 className={ic} />
    </button>
  );
}

export function Empty({
  title, description, action,
}: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="grid place-items-center rounded-xl border border-dashed border-rom-border p-10 text-center">
      <div>
        <div className="text-base font-medium text-white">{title}</div>
        {description && <p className="mt-1 max-w-md text-sm text-rom-muted">{description}</p>}
        {action && <div className="mt-4">{action}</div>}
      </div>
    </div>
  );
}

export function Switch({
  checked, onChange, label, description, disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label?: string;
  description?: string;
  disabled?: boolean;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cls(
        'flex w-full items-start justify-between gap-4 rounded-lg border border-rom-border bg-rom-surface2 p-3 text-left transition-colors hover:border-rom-borderHi',
        disabled && 'opacity-50',
      )}
    >
      <div className="flex-1">
        {label && <div className="text-sm text-white">{label}</div>}
        {description && (
          <div className="mt-0.5 text-xs text-rom-muted">{description}</div>
        )}
      </div>
      <div
        className={cls(
          'relative h-5 w-9 shrink-0 rounded-full transition-colors',
          checked ? 'bg-rom-glow' : 'bg-rom-border',
        )}
      >
        <div
          className={cls(
            'absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all',
            checked ? 'left-4' : 'left-0.5',
          )}
        />
      </div>
    </button>
  );
}

export type RuleFieldSpec = { key: string; label: string; dflt: number };
const RULE_OPS: Array<RuleCondition['op']> = ['>=', '<=', '>', '<'];

function RuleValueInput({ value, onCommit }: { value: number; onCommit: (n: number) => void }) {
  const [text, setText] = useState(() => String(value));
  const focused = useRef(false);
  useEffect(() => { if (!focused.current) setText(String(value)); }, [value]);
  const commit = (): void => {
    const n = parseFloat(text);
    if (!Number.isFinite(n)) { setText(String(value)); return; }
    setText(String(n));
    if (n !== value) onCommit(n);
  };
  return (
    <input
      type="number"
      step="any"
      inputMode="decimal"
      value={text}
      onFocus={() => { focused.current = true; }}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => { focused.current = false; commit(); }}
      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
      className="rom-input w-24 font-mono"
    />
  );
}

export function RuleBuilder({
  config, fields, useRulesKey, rulesKey, label, description, tip,
}: {
  config?: TraderConfig | null;
  fields: RuleFieldSpec[];
  useRulesKey: keyof TraderConfig;
  rulesKey: keyof TraderConfig;
  label: string;
  description: string;
  tip?: ReactNode;
}) {
  const useRules = !!(config as Record<string, unknown> | null | undefined)?.[useRulesKey as string];
  const rules = (((config as Record<string, unknown> | null | undefined)?.[rulesKey as string]) ?? []) as RuleCondition[];
  const save = (patch: Partial<TraderConfig>) => void window.rom.config.update(patch);
  const setRules = (next: RuleCondition[]) => save({ [rulesKey]: next } as Partial<TraderConfig>);

  return (
    <div className="rounded-xl border border-rom-border bg-rom-surface p-3">
      <Switch
        checked={useRules}
        onChange={(v) => save({ [useRulesKey]: v } as Partial<TraderConfig>)}
        label={label}
        description={description}
      />
      {useRules && (
        <div className="mt-3 space-y-2">
          {rules.length === 0 && (
            <div className="text-[11px] text-rom-warn">
              No conditions yet — add at least one (an empty rule-set never trades).
            </div>
          )}
          {rules.map((r, i) => (
            <div key={i} className="flex items-center gap-2">
              <select
                value={r.field}
                onChange={(e) => setRules(rules.map((x, j) => (j === i ? { ...x, field: e.target.value } : x)))}
                className="rom-input flex-1"
              >
                {fields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
              </select>
              <select
                value={r.op}
                onChange={(e) => setRules(rules.map((x, j) => (j === i ? { ...x, op: e.target.value as RuleCondition['op'] } : x)))}
                className="rom-input w-16 text-center font-mono"
              >
                {RULE_OPS.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
              <RuleValueInput
                value={r.value}
                onCommit={(n) => setRules(rules.map((x, j) => (j === i ? { ...x, value: n } : x)))}
              />
              <button
                onClick={() => setRules(rules.filter((_, j) => j !== i))}
                className="px-1 text-rom-loss/80 hover:text-rom-loss"
                title="Remove condition"
              >✕</button>
            </div>
          ))}
          <button
            onClick={() => setRules([...rules, { field: fields[0].key, op: '>=', value: fields[0].dflt }])}
            className="rom-btn-default text-xs"
          >
            + Add condition
          </button>
          {tip && <div className="text-[10px] text-rom-dim">{tip}</div>}
        </div>
      )}
    </div>
  );
}

export function NumberInput({
  value, onChange, min, max, step, suffix, prefix, disabled,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
  prefix?: string;
  disabled?: boolean;
}) {
  const [text, setText] = useState(() => (Number.isFinite(value) ? String(value) : ''));
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setText(Number.isFinite(value) ? String(value) : '');
  }, [value]);

  const commit = (): void => {
    const n = parseFloat(text);
    if (!Number.isFinite(n)) {
      setText(Number.isFinite(value) ? String(value) : '');
      return;
    }
    let clamped = n;
    if (typeof min === 'number') clamped = Math.max(min, clamped);
    if (typeof max === 'number') clamped = Math.min(max, clamped);
    setText(String(clamped));
    if (clamped !== value) onChange(clamped);
  };

  return (
    <div className={cls('relative', disabled && 'opacity-50')}>
      {prefix && (
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-rom-dim">
          {prefix}
        </span>
      )}
      <input
        type="number"
        value={text}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onFocus={() => { focused.current = true; }}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => { focused.current = false; commit(); }}
        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
        className={cls(
          'rom-input font-mono',
          prefix && 'pl-7',
          suffix && 'pr-12',
          disabled && 'cursor-not-allowed',
        )}
      />
      {suffix && (
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-rom-dim">
          {suffix}
        </span>
      )}
    </div>
  );
}

export function Section({
  title, description, children,
}: { title: string; description?: string; children: ReactNode }) {
  return (
    <div className="mb-6">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-rom-muted">
          {title}
        </h3>
        {description && (
          <p className="ml-4 max-w-md text-right text-xs text-rom-dim">{description}</p>
        )}
      </div>
      {children}
    </div>
  );
}
