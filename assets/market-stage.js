const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const stage = document.querySelector('.terminal-stage');
document.documentElement.classList.add('js-ready');

const previewViews = {
  overview: {
    image: 'assets/rom-polybot-overview-2.35.11.webp',
    fullSize: 'assets/rom-polybot-overview-2.35.11.png',
    label: 'Workspace',
    kicker: '01 / WORKSPACE',
    title: 'The whole picture. One place.',
    description: 'Your account, strategy, and latest decisions at a glance. Trading starts paused.',
    alt: 'ROM Polybot Overview showing its paused strategy, decision cycle, and account metrics',
  },
  practice: {
    image: 'assets/polybot-practice-2.35.11.webp',
    fullSize: 'assets/polybot-practice-2.35.11.png',
    label: 'Practice and risk',
    kicker: '02 / PRACTICE & RISK',
    title: 'Set the limits. Then explore.',
    description: 'Choose risk settings and start Practice with simulated funds before committing real money.',
    alt: 'ROM Polybot Strategy setup showing risk settings and separate Start practice and Start live controls',
  },
  evidence: {
    image: 'assets/polybot-evidence-2.35.11.webp',
    fullSize: 'assets/polybot-evidence-2.35.11.png',
    label: 'Evidence',
    kicker: '03 / EVIDENCE',
    title: 'See what backs the decision.',
    description: 'Inspect recorded results and data limits. This screen shows the initial state, before settled samples.',
    alt: 'ROM Polybot Evidence screen in its initial state with zero settled samples and account diagnostics',
  },
};

const previewButtons = [...document.querySelectorAll('[data-preview]')];
const previewImage = document.querySelector('#preview-image');
const previewLink = document.querySelector('#preview-image-link');
const previewStatus = document.querySelector('#preview-status');
let activePreview = 'overview';
let previewRequest = 0;

async function selectPreview(key) {
  const view = previewViews[key];
  if (!view) return;
  const request = ++previewRequest;
  previewStatus.textContent = '';
  previewStatus.removeAttribute('data-loading');
  previewLink.removeAttribute('aria-busy');
  if (key === activePreview) return;

  previewLink.setAttribute('aria-busy', 'true');
  previewStatus.setAttribute('data-loading', '');
  previewStatus.textContent = `Loading ${view.label} preview…`;
  try {
    // Load offscreen first so a slow or missing image never blanks the current view.
    const nextImage = new Image();
    nextImage.src = view.image;
    await nextImage.decode();
    if (request !== previewRequest) return;

    previewImage.src = view.image;
    previewImage.alt = view.alt;
    previewLink.href = view.fullSize;
    previewLink.setAttribute('aria-label', `View full-size ${view.label} screenshot (opens in a new tab)`);
    document.querySelector('#preview-full-size').href = view.fullSize;
    document.querySelector('#preview-kicker').textContent = view.kicker;
    document.querySelector('#preview-title').textContent = view.title;
    document.querySelector('#preview-description').textContent = view.description;
    for (const button of previewButtons) {
      button.setAttribute('aria-pressed', String(button.dataset.preview === key));
    }
    activePreview = key;
    previewLink.classList.remove('switching');
    if (!reducedMotion.matches) {
      void previewImage.offsetWidth;
      previewLink.classList.add('switching');
    }
    previewStatus.textContent = '';
  } catch {
    if (request !== previewRequest) return;
    previewStatus.textContent = 'This preview could not load. Your current view is still available. Try again.';
  } finally {
    if (request === previewRequest) {
      previewLink.removeAttribute('aria-busy');
      previewStatus.removeAttribute('data-loading');
    }
  }
}

if (previewImage && previewLink && previewStatus && previewButtons.length) {
  previewButtons.forEach((button) => {
    button.addEventListener('click', () => selectPreview(button.dataset.preview));
  });
  // Each native button stays in the tab order; Enter/Space selects a screen.
  stage?.classList.add('preview-ready');
}

const theater = document.querySelector('.product-theater');
const precisePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
let glowFrame = 0;
theater?.addEventListener('pointermove', (event) => {
  if (reducedMotion.matches || !precisePointer.matches || event.pointerType === 'touch') return;
  cancelAnimationFrame(glowFrame);
  glowFrame = requestAnimationFrame(() => {
    const bounds = theater.getBoundingClientRect();
    theater.style.setProperty('--glow-x', `${((event.clientX - bounds.left) / bounds.width - .5) * 48}px`);
    theater.style.setProperty('--glow-y', `${((event.clientY - bounds.top) / bounds.height - .5) * 32}px`);
  });
});
theater?.addEventListener('pointerleave', () => {
  cancelAnimationFrame(glowFrame);
  theater.style.removeProperty('--glow-x');
  theater.style.removeProperty('--glow-y');
});

document.querySelector('#replay-preview')?.addEventListener('click', () => {
  if (!stage || reducedMotion.matches) return;
  stage.classList.remove('replaying');
  // Restart the short entrance and light sweep without adding a looping effect.
  void stage.offsetWidth;
  stage.classList.add('replaying');
});

if ('IntersectionObserver' in window && !reducedMotion.matches) {
  const sections = document.querySelectorAll('[data-reveal]');
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add('is-visible');
      observer.unobserve(entry.target);
    }
  }, {rootMargin: '0px 0px -30px 0px', threshold: 0.08});
  document.documentElement.classList.add('motion-ready');
  sections.forEach((section) => observer.observe(section));
}

document.querySelector('#share-download')?.addEventListener('click', async () => {
  const status = document.querySelector('#share-status');
  const url = 'https://romapps.xyz/#download-polybot';
  try {
    if (navigator.share) {
      await navigator.share({title: 'ROM Polybot download', url});
      status.textContent = 'Page shared. Open it on your computer to download Polybot.';
    } else if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url);
      status.textContent = 'Link copied. Send it to your computer to download Polybot.';
    } else {
      status.textContent = 'Copy the address shown below to open this page on your computer.';
    }
  } catch (error) {
    if (error?.name !== 'AbortError') {
      status.textContent = 'Use your browser’s Share button or copy the address shown below.';
    }
  }
});
