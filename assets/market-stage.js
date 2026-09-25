const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const stage = document.querySelector('.terminal-stage');
document.documentElement.classList.add('js-ready');

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
