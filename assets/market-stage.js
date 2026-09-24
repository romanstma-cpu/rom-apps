const stage = document.querySelector('.terminal-stage');
document.querySelector('#replay-preview')?.addEventListener('click', () => {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  stage.classList.add('replaying');
  requestAnimationFrame(() => requestAnimationFrame(() => stage.classList.remove('replaying')));
});

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
