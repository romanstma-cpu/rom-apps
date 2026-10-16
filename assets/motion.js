// ROM Apps motion layer: word-by-word headings, pointer depth on product frames, a cursor spotlight,
// and two living backgrounds (the homepage signal field and the Recoil HUD). It only decorates a page
// that already works without it. Reduced-motion visitors get none of it, pointer effects need a real
// mouse, and the canvases draw only while they are on screen and the tab is visible.
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');

// ------------------------------------------------------------------ header: glass + reading progress
const header = document.querySelector('.site-header');
if (header) {
  let queued = false;
  const update = () => {
    queued = false;
    const max = document.documentElement.scrollHeight - window.innerHeight;
    header.classList.toggle('is-scrolled', window.scrollY > 8);
    header.style.setProperty('--progress', max > 0 ? Math.min(1, window.scrollY / max).toFixed(4) : '0');
  };
  window.addEventListener('scroll', () => { if (!queued) { queued = true; requestAnimationFrame(update); } }, {passive: true});
  window.addEventListener('resize', update);
  update();
}

if (!reduce.matches) {
  splitHeadings();
  if (finePointer.matches) {
    tiltFrames();
    spotlight();
    magnetic();
  }
  const hero = document.querySelector('.hero');
  if (hero) signalField(hero);
  const hud = document.querySelector('.rc-visual');
  if (hud) hudField(hud);
}

// ------------------------------------------------------------------ headings rise in word by word
function splitHeadings() {
  const heads = [...document.querySelectorAll('[data-split]')];
  if (!heads.length || !('IntersectionObserver' in window)) return;
  for (const head of heads) {
    // Screen readers get the sentence once, from the label; the word pieces are hidden from them.
    head.setAttribute('aria-label', head.textContent.replace(/\s+/g, ' ').trim());
    let index = 0;
    const walk = (node) => {
      for (const child of [...node.childNodes]) {
        if (child.nodeType === Node.TEXT_NODE) {
          const frag = document.createDocumentFragment();
          for (const part of child.textContent.split(/(\s+)/)) {
            if (!part) continue;
            if (/^\s+$/.test(part)) { frag.append(document.createTextNode(part)); continue; }
            const outer = document.createElement('span');
            outer.className = 'split-word';
            outer.setAttribute('aria-hidden', 'true');
            const inner = document.createElement('span');
            inner.textContent = part;
            inner.style.setProperty('--i', String(index++));
            outer.append(inner);
            frag.append(outer);
          }
          child.replaceWith(frag);
        } else if (child.nodeType === Node.ELEMENT_NODE && child.tagName !== 'BR') {
          walk(child);
        }
      }
    };
    walk(head);
  }
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add('is-revealed');
      observer.unobserve(entry.target);
    }
  }, {threshold: 0.15, rootMargin: '0px 0px -6% 0px'});
  // A moment later, so the hidden starting position is painted before the first reveal.
  setTimeout(() => heads.forEach((h) => observer.observe(h)), 60);
  // Safety net: whatever is already on screen (or above it) shows after a short wait even if the
  // observer never reports, and everything shows for printing. A heading must never stay hidden.
  const showPassed = () => {
    for (const h of heads) if (h.getBoundingClientRect().top < window.innerHeight) h.classList.add('is-revealed');
  };
  setTimeout(showPassed, 2500);
  window.addEventListener('scroll', () => setTimeout(showPassed, 1200), {passive: true});
  window.addEventListener('beforeprint', () => heads.forEach((h) => h.classList.add('is-revealed')));
}

// ------------------------------------------------------------------ product frames tilt toward the pointer
function tiltFrames() {
  for (const frame of document.querySelectorAll('.terminal-stage, .nova-visual, .hud-frame')) {
    const glare = document.createElement('span');
    glare.className = 'glare';
    glare.setAttribute('aria-hidden', 'true');
    frame.append(glare);
    frame.classList.add('tilt');
    let pending = 0;
    let px = 0.5;
    let py = 0.5;
    frame.addEventListener('pointermove', (event) => {
      const box = frame.getBoundingClientRect();
      px = (event.clientX - box.left) / box.width;
      py = (event.clientY - box.top) / box.height;
      frame.classList.add('is-tilting');
      if (pending) return;
      pending = requestAnimationFrame(() => {
        pending = 0;
        // Rotate about the axis perpendicular to the pointer's offset: the side under it dips away.
        const ax = -(py - 0.5);
        const ay = px - 0.5;
        const size = Math.hypot(ax, ay);
        frame.style.rotate = size ? `${(ax / size).toFixed(3)} ${(ay / size).toFixed(3)} 0 ${(size * 9).toFixed(2)}deg` : '';
        frame.style.setProperty('--gx', `${(px * 100).toFixed(1)}%`);
        frame.style.setProperty('--gy', `${(py * 100).toFixed(1)}%`);
      });
    });
    frame.addEventListener('pointerleave', () => {
      cancelAnimationFrame(pending);
      pending = 0;
      frame.classList.remove('is-tilting');
      frame.style.rotate = '';
    });
  }
}

// ------------------------------------------------------------------ cursor spotlight on cards and rows
function spotlight() {
  const items = document.querySelectorAll('.capability-list li, .platform-card, .rc-panel, .spec-strip > div, .faq details');
  items.forEach((el) => el.classList.add('spot'));
  document.addEventListener('pointermove', (event) => {
    const el = event.target instanceof Element ? event.target.closest('.spot') : null;
    if (!el) return;
    const box = el.getBoundingClientRect();
    el.style.setProperty('--mx', `${(event.clientX - box.left).toFixed(0)}px`);
    el.style.setProperty('--my', `${(event.clientY - box.top).toFixed(0)}px`);
  }, {passive: true});
}

// ------------------------------------------------------------------ primary buttons lean toward the pointer
function magnetic() {
  for (const button of document.querySelectorAll('.button-primary, .nav-cta')) {
    button.addEventListener('pointermove', (event) => {
      const box = button.getBoundingClientRect();
      const dx = event.clientX - (box.left + box.width / 2);
      const dy = event.clientY - (box.top + box.height / 2);
      button.style.translate = `${(dx * 0.16).toFixed(1)}px ${(dy * 0.26).toFixed(1)}px`;
    });
    button.addEventListener('pointerleave', () => { button.style.translate = ''; });
  }
}

// ------------------------------------------------------------------ shared canvas plumbing
function liveCanvas(host, className, draw) {
  if (!('IntersectionObserver' in window) || !('ResizeObserver' in window)) return null; // the static art stays
  const canvas = document.createElement('canvas');
  canvas.className = className;
  canvas.setAttribute('aria-hidden', 'true');
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  host.prepend(canvas);
  const state = {w: 0, h: 0, pointerX: 0.5, pointerY: 0.5, aimX: 0.5, aimY: 0.5};
  let frame = 0;
  let onScreen = false;

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const box = canvas.getBoundingClientRect();
    state.w = box.width;
    state.h = box.height;
    canvas.width = Math.round(box.width * dpr);
    canvas.height = Math.round(box.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  const tick = (now) => {
    frame = 0;
    if (!onScreen || document.hidden) return;
    // Ease toward the pointer so the parallax glides instead of jumping.
    state.pointerX += (state.aimX - state.pointerX) * 0.05;
    state.pointerY += (state.aimY - state.pointerY) * 0.05;
    ctx.clearRect(0, 0, state.w, state.h);
    draw(ctx, state, now);
    frame = requestAnimationFrame(tick);
  };
  const start = () => { if (!frame && onScreen && !document.hidden) frame = requestAnimationFrame(tick); };

  new ResizeObserver(resize).observe(canvas);
  new IntersectionObserver(([entry]) => { onScreen = entry.isIntersecting; start(); }).observe(host);
  document.addEventListener('visibilitychange', start);
  if (finePointer.matches) {
    host.addEventListener('pointermove', (event) => {
      const box = host.getBoundingClientRect();
      state.aimX = (event.clientX - box.left) / box.width;
      state.aimY = (event.clientY - box.top) / box.height;
    });
    host.addEventListener('pointerleave', () => { state.aimX = 0.5; state.aimY = 0.5; });
  }
  resize();
  requestAnimationFrame(() => canvas.classList.add('is-live'));
  return canvas;
}

// ------------------------------------------------------------------ homepage: the signal field
// The static hero arcs, brought to life: the curves breathe, bend a little toward the pointer, and
// short pulses of light travel along them. Decoration only; nothing here is market data.
function signalField(hero) {
  const lines = Array.from({length: 16}, (_, i) => ({i, phase: Math.random() * Math.PI * 2, speed: 0.00016 + Math.random() * 0.0001}));
  const pulses = Array.from({length: 11}, () => ({line: Math.floor(Math.random() * lines.length), t: Math.random(), speed: 0.00005 + Math.random() * 0.00006}));
  let last = performance.now();

  const point = (line, s, now, state) => {
    const {w, h} = state;
    const k = line.i / (lines.length - 1);
    const sway = Math.sin(now * line.speed + line.phase) * h * 0.035;
    const lean = (state.pointerX - 0.5) * w * 0.05;
    const lift = (state.pointerY - 0.5) * h * 0.04;
    const x0 = w * (0.2 + k * 0.3), y0 = h * 1.08;
    const x3 = w * (0.9 + k * 0.16), y3 = -h * 0.16;
    const c1x = x0 + lean, c1y = h * (0.42 - k * 0.12) + sway + lift;
    const c2x = x3 - w * 0.34 + lean * 1.6, c2y = h * (0.86 - k * 0.22) - sway;
    const u = 1 - s;
    return [
      u * u * u * x0 + 3 * u * u * s * c1x + 3 * u * s * s * c2x + s * s * s * x3,
      u * u * u * y0 + 3 * u * u * s * c1y + 3 * u * s * s * c2y + s * s * s * y3,
    ];
  };

  const canvas = liveCanvas(hero, 'field-canvas', (ctx, state, now) => {
    const dt = Math.min(64, now - last);
    last = now;
    ctx.lineWidth = 1.2;
    for (const line of lines) {
      ctx.beginPath();
      for (let s = 0; s <= 1.0001; s += 1 / 48) {
        const [x, y] = point(line, s, now, state);
        if (s === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = line.i % 2 ? 'rgba(163, 217, 255, 0.20)' : 'rgba(99, 169, 255, 0.26)';
      ctx.stroke();
    }
    for (const pulse of pulses) {
      pulse.t += pulse.speed * dt;
      if (pulse.t > 1) { pulse.t = 0; pulse.line = Math.floor(Math.random() * lines.length); }
      const line = lines[pulse.line];
      // A short comet: a bright head with a fading tail behind it.
      for (let k = 0; k < 10; k++) {
        const s = pulse.t - k * 0.006;
        if (s < 0) break;
        const [x, y] = point(line, s, now, state);
        ctx.fillStyle = `rgba(190, 228, 255, ${(0.85 * (1 - k / 10)).toFixed(3)})`;
        ctx.beginPath();
        ctx.arc(x, y, k === 0 ? 2.2 : 1.6 * (1 - k / 12), 0, Math.PI * 2);
        ctx.fill();
      }
    }
  });
  if (canvas) hero.classList.add('has-field');
}

// ------------------------------------------------------------------ Recoil page: the HUD behind the screenshot
// Rings turning at different speeds, a radar sweep and a few contacts that light up as it passes.
// Purely decorative; it does not show what the app does in a game.
function hudField(holder) {
  const contacts = Array.from({length: 7}, () => ({angle: Math.random() * Math.PI * 2, r: 0.42 + Math.random() * 0.46, glow: 0}));
  let sweep = -Math.PI / 2;
  let last = performance.now();
  const azure = (a) => `rgba(59, 158, 255, ${a})`;
  const cyan = (a) => `rgba(99, 240, 255, ${a})`;

  const canvas = liveCanvas(holder, 'hud-canvas', (ctx, state, now) => {
    const dt = Math.min(64, now - last);
    last = now;
    const cx = state.w / 2 + (state.pointerX - 0.5) * 18;
    const cy = state.h / 2 + (state.pointerY - 0.5) * 18;
    const R = Math.min(state.w, state.h) * 0.48;
    const time = now / 1000;

    // Rings and tick marks.
    ctx.lineWidth = 1;
    for (const [f, a] of [[1, 0.26], [0.82, 0.16], [0.58, 0.12]]) {
      ctx.strokeStyle = azure(a);
      ctx.beginPath();
      ctx.arc(cx, cy, R * f, 0, Math.PI * 2);
      ctx.stroke();
    }
    for (let i = 0; i < 120; i++) {
      const a = (i / 120) * Math.PI * 2 + time * 0.03;
      const long = i % 10 === 0;
      const r0 = R * (long ? 0.94 : 0.97);
      ctx.strokeStyle = azure(long ? 0.5 : 0.22);
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0);
      ctx.lineTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R);
      ctx.stroke();
    }
    // Two arc segments counter-rotating on the middle ring.
    ctx.lineWidth = 2.4;
    ctx.lineCap = 'round';
    for (const [start, len, dir] of [[0, 0.9, 1], [Math.PI, 0.6, 1], [0.6, 0.4, -1]]) {
      const a = start + time * 0.18 * dir;
      ctx.strokeStyle = cyan(0.55);
      ctx.beginPath();
      ctx.arc(cx, cy, R * 0.82, a, a + len);
      ctx.stroke();
    }

    // Radar sweep with a fading wedge behind it.
    sweep += dt * 0.0011;
    const wedge = 0.9;
    if (ctx.createConicGradient) {
      const g = ctx.createConicGradient(sweep - wedge, cx, cy);
      g.addColorStop(0, cyan(0));
      g.addColorStop(wedge / (Math.PI * 2), cyan(0.16));
      g.addColorStop(wedge / (Math.PI * 2) + 0.0001, cyan(0));
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, R * 0.97, sweep - wedge, sweep);
      ctx.closePath();
      ctx.fill();
    }
    ctx.strokeStyle = cyan(0.5);
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(sweep) * R * 0.97, cy + Math.sin(sweep) * R * 0.97);
    ctx.stroke();

    // Contacts glow when the sweep passes over them, then fade.
    for (const c of contacts) {
      const behind = ((sweep - c.angle) % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2);
      if (behind < 0.06) c.glow = 1;
      c.glow = Math.max(0, c.glow - dt * 0.0006);
      if (c.glow <= 0) continue;
      const x = cx + Math.cos(c.angle) * R * c.r;
      const y = cy + Math.sin(c.angle) * R * c.r;
      ctx.fillStyle = cyan(0.75 * c.glow);
      ctx.beginPath();
      ctx.arc(x, y, 2.6, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = cyan(0.35 * c.glow);
      ctx.beginPath();
      ctx.arc(x, y, 7 + (1 - c.glow) * 10, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Crosshair ticks at the four points of the compass, inside the ring so they never reach the text.
    ctx.strokeStyle = azure(0.55);
    ctx.lineWidth = 1.6;
    for (let q = 0; q < 4; q++) {
      const a = (q * Math.PI) / 2;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * R * 0.86, cy + Math.sin(a) * R * 0.86);
      ctx.lineTo(cx + Math.cos(a) * R * 0.92, cy + Math.sin(a) * R * 0.92);
      ctx.stroke();
    }
  });
  if (canvas) holder.classList.add('has-field');
}
