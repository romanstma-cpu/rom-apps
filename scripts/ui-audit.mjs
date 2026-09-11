// Design-system audit: drives the real app, measures what actually renders.
// SHOTS=<dir> node scripts/ui-audit.mjs -- screenshots every page and reports
// contrast, type scale, spacing scale, hit targets and unnamed controls.
import {_electron as electron} from 'playwright-core';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const OUT = process.env.SHOTS;
fs.mkdirSync(OUT, {recursive: true});
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rom-uiaudit-'));
for (const d of ['Roaming', 'Local']) fs.mkdirSync(path.join(root, d));

const app = await electron.launch({
  executablePath: path.resolve('node_modules/electron/dist/electron.exe'),
  args: [process.cwd(), `--user-data-dir=${root}/profile`],
  env: {...process.env, APPDATA: path.join(root, 'Roaming'), LOCALAPPDATA: path.join(root, 'Local')},
});

const setSize = (w, h) => app.evaluate(({BrowserWindow}, [w, h]) => {
  BrowserWindow.getAllWindows()[0].setSize(w, h);
}, [w, h]);

// The measurement runs in the page. Everything here is computed style, not source.
const PROBE = () => {
  const SPACING = new Set([0, 1, 2, 4, 6, 8, 10, 12, 16, 20, 24, 28, 32, 40, 48, 56, 64, 80, 96]);
  const TYPE = new Set([10, 11, 12, 13, 14, 16, 18, 20, 24, 30, 36, 48]);
  const RADIUS = new Set([0, 2, 4, 6, 8, 12, 16, 9999]);

  const parseRGB = (s) => {
    const m = String(s).match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x.trim()));
    return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1};
  };
  const over = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1,
  });
  // Real backdrop: composite every non-transparent ancestor background.
  const backdrop = (el) => {
    const stack = [];
    for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
      const c = parseRGB(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) stack.push(c);
      if (c && c.a === 1) break;
    }
    let base = {r: 11, g: 16, b: 25, a: 1};
    for (let i = stack.length - 1; i >= 0; i--) base = over(stack[i], base);
    return base;
  };
  const lum = (c) => {
    const f = (v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const ratio = (a, b) => {
    const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m);
    return (x + 0.05) / (y + 0.05);
  };

  const out = {
    overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    contrast: [], tinyText: [], offScaleType: [], offScaleSpace: [],
    offScaleRadius: [], unlabeled: [], truncationRisk: [], focusless: [],
  };
  const seen = new Set();
  const main = document.querySelector('main') || document.body;

  for (const el of main.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;

    const text = (el.textContent || '').trim();
    const leaf = el.children.length === 0 && text;

    if (leaf) {
      const fs = parseFloat(cs.fontSize);
      if (fs < 11) out.tinyText.push(`${text.slice(0, 30)} @${fs}px`);
      if (!TYPE.has(Math.round(fs))) {
        const k = 'T' + fs;
        if (!seen.has(k)) { seen.add(k); out.offScaleType.push(`${fs}px  e.g. "${text.slice(0, 24)}"`); }
      }
      const fg = parseRGB(cs.color);
      if (fg) {
        const composited = fg.a < 1 ? over(fg, backdrop(el)) : fg;
        const r = ratio(composited, backdrop(el));
        const big = fs >= 18 || (fs >= 14 && parseInt(cs.fontWeight, 10) >= 700);
        const need = big ? 3.0 : 4.5;
        if (r < need) {
          out.contrast.push(`${r.toFixed(2)}:1 (need ${need}) ${fs}px "${text.slice(0, 30)}"`);
        }
      }
      // A fixed-height single-line box holding text that overflows it.
      if (el.scrollWidth > el.clientWidth + 2 && cs.overflow !== 'visible' && cs.textOverflow !== 'ellipsis') {
        out.truncationRisk.push(text.slice(0, 30));
      }
    }

    for (const prop of ['paddingTop', 'paddingBottom', 'paddingLeft', 'paddingRight', 'gap']) {
      const v = parseFloat(cs[prop]);
      if (!isNaN(v) && v > 0 && !SPACING.has(Math.round(v))) {
        const k = 'S' + prop + v;
        if (!seen.has(k)) { seen.add(k); out.offScaleSpace.push(`${prop}:${v}px`); }
      }
    }
    const br = parseFloat(cs.borderTopLeftRadius);
    const pctRadius = cs.borderTopLeftRadius.includes('%') || br * 2 >= Math.min(rect.width, rect.height);
    if (!isNaN(br) && br > 0 && !pctRadius && !RADIUS.has(Math.round(br)) && br < 500) {
      const k = 'R' + br;
      if (!seen.has(k)) { seen.add(k); out.offScaleRadius.push(`${br}px`); }
    }
  }

  for (const b of main.querySelectorAll('button,[role="switch"],a,input,select,textarea')) {
    const r = b.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    // An <input> has no textContent -- a wrapping or htmlFor <label> is what
    // names it. Checking text alone reports every labelled field as broken.
    const labelled = !!(b.labels && b.labels.length &&
      [...b.labels].some(l => (l.textContent || '').trim()));
    const name = String(
      (labelled ? [...b.labels].map(l => l.textContent).join(' ') : '') ||
      (b.textContent || '').trim() || b.getAttribute('aria-label') ||
      b.getAttribute('title') || b.getAttribute('placeholder') || '').trim();
    if (!name) out.unlabeled.push(b.tagName + '.' + String(b.className).slice(0, 50));
    // Interactive targets under 24px in either axis are hard to hit.
    if ((r.height < 24 || r.width < 24) && b.tagName !== 'A') {
      out.focusless.push(`${b.tagName} ${Math.round(r.width)}x${Math.round(r.height)} "${name.slice(0, 20)}"`);
    }
  }
  return out;
};

const NAV = ['Overview', 'Detailed analytics', 'Evidence', 'Strategy', 'Positions', 'Signals',
  'Crypto', 'Terminal', 'Copy Trading', 'Scripts', 'Backtest', 'History', 'Profiles',
  'Accounts', 'Settings', 'API', 'Logs', 'Guide', 'About'];

const report = [];
try {
  const p = await app.firstWindow();
  const errs = [];
  p.on('pageerror', e => errs.push('pageerror: ' + e.message));
  p.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });

  await setSize(1440, 900);
  await p.waitForTimeout(900);
  await p.screenshot({path: path.join(OUT, '00-onboarding.png')});
  report.push({page: 'Onboarding', shot: '00-onboarding.png', ...(await p.evaluate(PROBE))});

  await p.getByRole('button', {name: 'Continue to API setup'}).click();
  await p.waitForTimeout(700);
  await p.getByRole('button', {name: /Advanced tools/}).click();
  await p.waitForTimeout(300);

  let i = 1;
  for (const label of NAV) {
    const before = errs.length;
    try {
      await p.getByRole('navigation').getByRole('button', {name: label, exact: true}).click({timeout: 5000});
    } catch (e) {
      report.push({page: label, issue: 'NAV FAILED ' + String(e).split('\n')[0]});
      i++; continue;
    }
    await p.waitForTimeout(1500);
    const slug = String(i).padStart(2, '0') + '-' + label.toLowerCase().replace(/[^a-z0-9]+/g, '-');
    await p.screenshot({path: path.join(OUT, slug + '.png')});
    report.push({page: label, shot: slug + '.png', ...(await p.evaluate(PROBE)), errors: errs.slice(before)});
    i++;
  }

  await setSize(420, 900);
  await p.waitForTimeout(600);
  for (const label of ['Overview', 'Strategy', 'Positions', 'History', 'Settings']) {
    try {
      await p.getByRole('navigation').getByRole('button', {name: label, exact: true}).click({timeout: 4000});
    } catch { /* icon rail at narrow width */ }
    await p.waitForTimeout(900);
    const slug = 'narrow-' + label.toLowerCase().replace(/[^a-z0-9]+/g, '-');
    await p.screenshot({path: path.join(OUT, slug + '.png')});
    const a = await p.evaluate(PROBE);
    report.push({page: 'narrow:' + label, shot: slug + '.png', overflowX: a.overflowX, contrast: a.contrast});
  }
} finally {
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 1));
  await app.close();
}

// Console summary
const tally = {};
for (const r of report) {
  for (const k of ['contrast', 'tinyText', 'offScaleType', 'offScaleSpace', 'offScaleRadius', 'unlabeled', 'truncationRisk', 'focusless']) {
    if (r[k]?.length) (tally[k] ??= []).push(`${r.page}: ${r[k].length}`);
  }
  if (r.overflowX) (tally.overflowX ??= []).push(r.page);
  if (r.errors?.length) (tally.errors ??= []).push(`${r.page}: ${r.errors.join(' | ')}`);
  if (r.issue) (tally.navFailed ??= []).push(`${r.page}: ${r.issue}`);
}
for (const [k, v] of Object.entries(tally)) console.log(`\n## ${k}\n  ` + v.join('\n  '));
console.log('\nshots + report.json in ' + OUT);
