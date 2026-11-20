/**
 * « Ajouter à Apple Wallet » from any app (user, 2026-11-20).
 *
 * On an iPhone or an iPad, only Safari — and the Safari window apps open
 * links in, which says the very same thing — hands a pass to Wallet. Chrome,
 * Firefox, an app's own browser (Instagram, Facebook, TikTok…) download the
 * file instead. There the page is sent to Safari, through Safari's own
 * x-safari-https:// scheme (iOS 17 and later).
 */

// Anything that is not Safari itself, though built on the same engine.
const NOT_SAFARI = /CriOS|FxiOS|EdgiOS|OPiOS|OPT\/|YaBrowser|DuckDuckGo|Ddg\/|GSA\/|FBAN|FBAV|FB_IAB|FBIOS|Messenger|Instagram|musical_ly|Bytedance|TikTok|Snapchat|LinkedInApp|Twitter|Pinterest|WhatsApp|Line\/|KAKAOTALK|MicroMessenger|Telegram/i;

/** 'safari' (the pass opens Wallet), 'other' (an iPhone/iPad, but not Safari:
 *  send it to Safari) or 'none' (not an iPhone/iPad: nothing changes). */
export function appleWalletPlace(ua, touchPoints) {
  const s = String(ua || '');
  const iOS = /iPhone|iPad|iPod/.test(s) || (/Macintosh/.test(s) && Number(touchPoints || 0) > 1);   // iPadOS says « Macintosh »
  if (!iOS) return 'none';
  const safari = /Version\/[\d.]+.*Safari\//.test(s) && !NOT_SAFARI.test(s);
  return safari ? 'safari' : 'other';
}

/** This web page, opened in Safari: x-safari-https://… — a web page only. */
export function safariLink(href) {
  const s = String(href || '');
  return /^https?:\/\//i.test(s) ? `x-safari-${s}` : null;
}

export function here() {
  if (typeof navigator === 'undefined') return 'none';
  return appleWalletPlace(navigator.userAgent, navigator.maxTouchPoints);
}
