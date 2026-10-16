// ROM Recoil page: the tuning preview. It uses the app's own pull formula (RomRecoil/Core/RecoilEngine.cs):
// every 12 ms the app moves the mouse (slider / 10) x 0.55 x strength counts, on each axis.
// Without this script the section stays hidden; nothing else on the page depends on it.
const tuner = document.querySelector('[data-tuner]');

if (tuner) {
  const down = tuner.querySelector('#tune-down');
  const side = tuner.querySelector('#tune-side');
  const strength = tuner.querySelector('#tune-strength');
  const vector = tuner.querySelector('#scope-vector');
  const trail = [...tuner.querySelectorAll('#scope-trail circle')];
  const rate = tuner.querySelector('#tune-rate');
  const direction = tuner.querySelector('#tune-direction');

  const perSecond = (slider, s) => (slider / 10) * 0.55 * s * (1000 / 12);
  // Strongest pull the preview allows (vertical 100 at strength 10), for scaling the vector.
  const maxRate = perSecond(100, 10);
  const format = new Intl.NumberFormat('en-US', {maximumFractionDigits: 0});

  const sideText = (v) => (v === 0 ? 'Centered' : v > 0 ? `${v} right` : `${-v} left`);

  function describe(dx, dy) {
    if (dx === 0 && dy === 0) return 'no pull: raise vertical pull and strength';
    if (dx === 0) return 'straight down';
    if (dy === 0) return dx > 0 ? 'straight right' : 'straight left';
    const way = dx > 0 ? 'right' : 'left';
    const ratio = Math.abs(dx) / Math.abs(dy);
    return ratio < 0.15 ? `down, a little ${way}` : ratio <= 1.2 ? `down and ${way}` : `mostly ${way}`;
  }

  // The filled part of each track: from the left edge, or from the center for the sideways slider.
  function paint(input) {
    const min = Number(input.min);
    const max = Number(input.max);
    const pct = ((Number(input.value) - min) / (max - min)) * 100;
    const centered = min < 0;
    input.style.setProperty('--from', `${centered ? Math.min(50, pct) : 0}%`);
    input.style.setProperty('--to', `${centered ? Math.max(50, pct) : pct}%`);
  }

  function update() {
    const d = Number(down.value);
    const h = Number(side.value);
    const s = Number(strength.value);
    tuner.querySelector('#tune-down-out').value = String(d);
    tuner.querySelector('#tune-side-out').value = sideText(h);
    tuner.querySelector('#tune-strength-out').value = s.toFixed(1);
    side.setAttribute('aria-valuetext', sideText(h));
    [down, side, strength].forEach(paint);

    const dy = perSecond(d, s);
    const dx = perSecond(h, s);
    const total = Math.hypot(dx, dy);
    rate.textContent = `≈ ${format.format(total)} counts/s`;
    direction.textContent = describe(Math.round(dx), Math.round(dy));

    // Vector length grows with the square root, so light tunings are still visible.
    const length = total === 0 ? 0 : 96 * Math.sqrt(Math.min(1, total / maxRate));
    const ux = total === 0 ? 0 : dx / total;
    const uy = total === 0 ? 0 : dy / total;
    vector.setAttribute('x2', (ux * length).toFixed(2));
    vector.setAttribute('y2', (uy * length).toFixed(2));
    trail.forEach((dot, i) => {
      const t = (i + 1) / (trail.length + 1);
      dot.setAttribute('cx', (ux * length * t).toFixed(2));
      dot.setAttribute('cy', (uy * length * t).toFixed(2));
      dot.setAttribute('opacity', total === 0 ? '0' : String(0.25 + 0.15 * i));
    });
  }

  [down, side, strength].forEach((input) => input.addEventListener('input', update));
  update();
  tuner.hidden = false;
}
