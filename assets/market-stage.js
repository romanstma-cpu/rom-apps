const stage = document.querySelector('.terminal-stage');
document.querySelector('#replay-preview')?.addEventListener('click', () => {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  stage.classList.add('replaying');
  requestAnimationFrame(() => requestAnimationFrame(() => stage.classList.remove('replaying')));
});
