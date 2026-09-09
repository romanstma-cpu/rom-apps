export const X_PROFILE = 'ROM Polybot';
export const X_PROFILE_URL = 'https://polymarket.us';

export async function shareToX(text: string): Promise<void> {
  const url = `https://x.com/intent/post?text=${encodeURIComponent(text)}`;
  try {
    await window.rom.app.openExternal(url);
  } catch {
    try { window.open(url, '_blank'); } catch {}
  }
}

export async function openPolymarketUS(): Promise<void> {
  try {
    await window.rom.app.openExternal(X_PROFILE_URL);
  } catch {
    try { window.open(X_PROFILE_URL, '_blank'); } catch {}
  }
}
