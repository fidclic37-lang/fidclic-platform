import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { ownerAPI } from '../lib/api';
import { ScanLine, CheckCircle2, AlertCircle, Euro, Camera, Building2, Gift, BellRing, X, Info, Zap, SwitchCamera, Package, ChevronDown, ChevronLeft, ArrowRight, Stamp, Keyboard, Link2, ImageUp } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
// The dashboard's blue palette — every account (owner, manager, employé)
// works in the same colours.
const C_SCAN = {
  sky: '#2F6BFF', lavender: '#7C3AED', inkDeep: '#0B1C3F', inkMute: '#475569',
  ochre: '#2F6BFF', amber: '#4F7BFF', terracotta: '#7C3AED',
};
import { useBranch } from '../contexts/BranchContext';
import { useAuth } from '../contexts/AuthContext';
import DecimalInput from '../components/DecimalInput';
import CardReaddModal from '../components/CardReaddModal';
import { canSwitchStore } from '../lib/storeSwitch';
import InstallPwaPrompt from '../components/InstallPwaPrompt';

const BRANCH_STORAGE_KEY = 'fidelitour_scan_branch_id';

/**
 * NotificationEnablePrompt — Strategy 3 (staff scan prompt).
 *
 * Shown to staff after scanning a customer whose phone has NO active push
 * subscription. Staff sees a friendly yellow prompt + can show the
 * customer a QR code that, when scanned, opens their wallet card with
 * an auto-trigger param (?notify=1) that immediately prompts for
 * notification permission.
 *
 * Why the QR approach: the customer's phone, not the staff tablet, must
 * trigger the browser permission dialog (browser security model). The QR
 * is the fastest way to hand the URL across.
 */
/**
 * The card id inside whatever the scanner read.
 *
 * The QR on a customer's card encodes the card's public URL, not the bare id:
 * a phone camera can open a URL, which is what lets a stranger who scans a
 * customer's card land on the signup page as their filleul. The till reads
 * the very same QR, so it pulls the id back out. A hand-typed "ft-ab12cd34"
 * still works, and so does an older card that still carries the bare id.
 */
const barcodeFrom = (scanned) => {
  const raw = String(scanned ?? '').trim();
  if (!raw) return '';
  const found = raw.match(/FT-[A-Z0-9]+/i);
  if (found) return found[0].toUpperCase();
  // EAN-13 / ITF / Codabar cards carry digits: « 20 » + the hex id in decimal
  const digits = raw.replace(/\s/g, '').match(/^[A-D]?(20\d{10})\d?[A-D]?$/i);
  if (digits) {
    const n = Number(digits[1].slice(2));
    if (n <= 0xFFFFFFFF) return `FT-${n.toString(16).toUpperCase().padStart(8, '0')}`;
  }
  return raw.replace(/\/+$/, '').split('/').pop().split('?')[0].trim().toUpperCase();
};

/*
 * A USB / Bluetooth barcode scanner (a « douchette ») is a keyboard: it types
 * what it read, very fast, then Enter. Most are set to a US keyboard, and on a
 * French (AZERTY) computer « FT-AB12CD34 » then arrives as « FT)QB&éCD"' ».
 * So each burst is read twice — the characters, and the physical keys as a US
 * keyboard has them — and whichever is a card code wins (user, 2026-10-14).
 */
const US_KEYS = { Minus: ['-', '_'], Equal: ['=', '+'], Slash: ['/', '?'], Period: ['.', '>'], Comma: [',', '<'],
  Semicolon: [';', ':'], Quote: ["'", '"'], Backslash: ['\\', '|'], BracketLeft: ['[', '{'], BracketRight: [']', '}'],
  Space: [' ', ' '], NumpadSubtract: ['-', '-'], NumpadDivide: ['/', '/'], NumpadDecimal: ['.', '.'] };
const usChar = (e) => {
  const c = e.code || '';
  if (/^Key[A-Z]$/.test(c)) return c.slice(3);
  if (/^(Digit|Numpad)\d$/.test(c)) return c.slice(-1);
  const k = US_KEYS[c];
  return k ? k[e.shiftKey ? 1 : 0] : '';
};
export const CARD_CODE = /^FT-[A-Z0-9]{8}$/;
export const codeFromBurst = (typed, physical) => {
  for (const raw of [typed, physical]) {
    const bc = barcodeFrom(raw);
    if (CARD_CODE.test(bc)) return bc;
  }
  const bc = barcodeFrom(typed);
  return bc && bc.length >= 4 ? bc : '';
};

function NotificationEnablePrompt({ customerName, barcodeId, cardKey }) {
  const [showQR, setShowQR] = useState(false);
  const firstName = (customerName || '').split(' ')[0] || 'votre client';
  // Public URL that opens the wallet card with the notification prompt
  // auto-trigger. MyWalletCardPage reads ?notify=1 and shows the prompt
  // banner the moment the page loads.
  // The customer opens it with their own phone: it carries the card's owner
  // key, so it opens their card, not the signup form (lib/myCards).
  const cardUrl = `${window.location.origin}/card/${(barcodeId || '').toUpperCase()}?notify=1${cardKey ? `&k=${encodeURIComponent(cardKey)}` : ''}`;

  return (
    <div
      style={{
        background: 'linear-gradient(135deg, hsl(42 78% 52% / .10), rgb(184 92 56 / .06))',
        border: '1px solid hsl(42 78% 52% / .35)',
        borderRadius: 12,
        padding: '14px 16px',
        marginTop: 14,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
        <div style={{
          flexShrink: 0, width: 36, height: 36, borderRadius: 10,
          background: 'hsl(42 78% 52% / .18)', color: 'hsl(32 80% 38%)',
          display: 'grid', placeItems: 'center',
        }}>
          <BellRing size={18} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{ margin: 0, fontSize: 13.5, fontWeight: 600, color: '#0B1C3F' }}>
            {firstName} ne reçoit pas vos offres
          </p>
          <p style={{ margin: '2px 0 8px', fontSize: 12, color: '#475569', lineHeight: 1.45 }}>
            Voulez-vous lui proposer d'activer les notifications ? 10 secondes, et il/elle ne ratera plus aucune campagne.
          </p>
          {!showQR ? (
            <button
              type="button"
              onClick={() => setShowQR(true)}
              style={{
                background: 'hsl(32 80% 48%)', color: '#FFFFFF',
                border: 'none', borderRadius: 8,
                padding: '7px 12px', fontSize: 12, fontWeight: 600,
                cursor: 'pointer', font: 'inherit',
              }}
            >
              Afficher le QR code à scanner
            </button>
          ) : null}
        </div>
      </div>

      {showQR && (
        <div style={{
          marginTop: 12, padding: 14, background: '#FFFFFF',
          borderRadius: 10, border: '1px solid #E6EEFB',
          display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap',
        }}>
          <div style={{ flexShrink: 0, padding: 8, background: '#FFFFFF', borderRadius: 6 }}>
            <QRCodeSVG value={cardUrl} size={120} level="M" />
          </div>
          <div style={{ flex: 1, minWidth: 180 }}>
            <p style={{ margin: 0, fontSize: 12.5, color: '#0B1C3F', fontWeight: 600, marginBottom: 4 }}>
              📱 {firstName}, scannez ce QR
            </p>
            <p style={{ margin: 0, fontSize: 11.5, color: '#475569', lineHeight: 1.5 }}>
              Votre carte s'ouvrira et vous demandera d'activer les notifications. Cliquez « Autoriser ».
            </p>
            <button
              type="button"
              onClick={() => setShowQR(false)}
              style={{
                marginTop: 8, background: 'transparent', border: 'none',
                color: '#64748B', fontSize: 11, cursor: 'pointer', font: 'inherit',
                display: 'inline-flex', alignItems: 'center', gap: 4,
              }}
            >
              <X size={11} /> Fermer
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Campagnes (2026-10-10): what the staff must not forget for this client —
// an offer valid right now (dates and happy hours) and a défi's reward won.
// The card's programme, as features/loyalty_card._programme reads it: a card
// saved before « programme » existed is a Tampons card unless it earns per euro.
const PROGRAMMES = ['points_euro', 'points_visit', 'stamps', 'cashback'];
export function programmeOf(tpl) {
  const p = String(tpl?.programme || '').trim().toLowerCase();
  const q = p === 'points' ? 'points_euro' : p;
  if (PROGRAMMES.includes(q)) return q;
  return tpl?.points_mode === 'per_euro' ? 'points_euro' : 'stamps';
}

function TillReminders({ offers = [], rewards = [], onRedeemed, customerId, branchId }) {
  const [busy, setBusy] = useState('');
  const [done, setDone] = useState({});
  const [used, setUsed] = useState({});
  const [err, setErr] = useState('');
  if (!offers.length && !rewards.length) return null;
  const give = async (r) => {
    setBusy(r.id); setErr('');
    try { await ownerAPI.redeemDefiReward(r.id); setDone((d) => ({ ...d, [r.id]: true })); onRedeemed && onRedeemed(r); }
    catch (e) { setErr(e?.response?.data?.detail || "La récompense n'a pas pu être remise."); }
    finally { setBusy(''); }
  };
  // « Offre utilisée » (Nouvelle automatisation › Après une action client, 2026-10-11): once per client
  const useIt = async (o) => {
    setBusy(o.id); setErr('');
    try { await ownerAPI.useOffer(o.id, { customer_id: customerId, branch_id: branchId || null }); setUsed((d) => ({ ...d, [o.id]: true })); }
    catch (e) {
      if (e?.response?.status === 409) setUsed((d) => ({ ...d, [o.id]: true }));
      setErr(e?.response?.data?.detail || "L'offre n'a pas pu être marquée comme utilisée.");
    } finally { setBusy(''); }
  };
  return (
    <div className="mt-3 space-y-2">
      {offers.map((o) => (
        <div key={o.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] px-3 py-2.5 text-[13.5px] text-[#92400E]">
          <span aria-hidden="true">%</span>
          <span className="min-w-0 flex-1"><b>Offre active{o.label ? ` : ${o.label}` : ''}</b> — {o.title}{o.terms ? ` (${o.terms})` : ''}.{o.used || used[o.id] ? ' Déjà utilisée par ce client.' : " Pensez à l'appliquer."}</span>
          {customerId && (o.used || used[o.id] ? <span className="font-semibold text-[#15803D]">Utilisée ✓</span> : (
            <button type="button" onClick={() => useIt(o)} disabled={busy === o.id}
                    className="rounded-lg bg-[#D97706] px-3 py-1.5 text-[13px] font-semibold text-white disabled:opacity-60">
              {busy === o.id ? '…' : 'Offre utilisée'}
            </button>
          ))}
        </div>
      ))}
      {rewards.map((r) => (
        <div key={r.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-[#BBF7D0] bg-[#F0FDF4] px-3 py-2.5 text-[13.5px] text-[#14532D]">
          <span className="flex-1">{r.kind === 'parrainage'
            ? <><b>🎁 Parrainage : {r.reward}</b> — à remettre au client.</>
            : <><b>🏆 Défi réussi : {r.reward}</b> — « {r.title} »{r.expires_at ? `, valable jusqu'au ${new Date(r.expires_at).toLocaleDateString('fr-FR')}` : ''}.</>}</span>
          {done[r.id] ? <span className="font-semibold text-[#15803D]">Remise ✓</span> : (
            <button type="button" onClick={() => give(r)} disabled={busy === r.id}
                    className="rounded-lg bg-[#16A34A] px-3 py-1.5 text-[13px] font-semibold text-white disabled:opacity-60">
              {busy === r.id ? '…' : 'Remettre'}
            </button>
          )}
        </div>
      ))}
      {err && <p role="alert" className="text-[12.5px] font-semibold text-[#DC2626]">{err}</p>}
    </div>
  );
}

const ScanPage = () => {
  const { t } = useTranslation();
  // 'camera' or 'manual'. A phone or tablet at the till opens on the camera
  // (2026-10-10 redesign); a computer on the typed form.
  const [mode, setMode] = useState(() => {
    try { return window.matchMedia('(pointer: coarse)').matches && navigator.mediaDevices?.getUserMedia ? 'camera' : 'manual'; }
    catch (_e) { return 'manual'; }
  });
  const [facing, setFacing] = useState('environment');   // « Retourner »
  const [torch, setTorch] = useState({ supported: false, on: false });   // « Flash »
  // Stamps of the customer's PAPER card, moved once onto the digital card
  // (user, 2026-10-10). The preview says whose card it is and how many it can take.
  const [paperStamps, setPaperStamps] = useState('');
  const [threshold, setThreshold] = useState(10);
  const [barcode, setBarcode] = useState('');
  const [amountPaid, setAmountPaid] = useState('');
  // an amount the till can't record — « -1 », … — is said under the field and
  // stops « Suivant », not only the final save (QA R7, 2026-10-18)
  const [amountErr, setAmountErr] = useState(null);
  // « -1 » is refused, said and kept on screen (QA F20) — nothing saves meanwhile
  const [amountError, setAmountError] = useState(null);
  // Live points rule from this tenant's card template.
  // Two modes: 'per_visit' (flat, default) or 'per_euro' (amount × rate).
  const [pointsMode, setPointsMode] = useState('per_visit');
  const [pointsPerEuro, setPointsPerEuro] = useState(10);
  const [pointsPerVisit, setPointsPerVisit] = useState(10);
  const [cashback, setCashback] = useState(false);
  // the card's programme, read as the server reads it (loyalty_card._programme):
  // a Tampons card gives tampons, never points (QA BUG-009)
  const [stampsProgramme, setStampsProgramme] = useState(false);
  // Tenant identity — shown as a banner so staff knows which shop they're in.
  const [tenantInfo, setTenantInfo] = useState(null);
  const [status, setStatus] = useState(null); // { type: 'success' | 'error' | 'info', message: '' }
  const [loading, setLoading] = useState(false);
  const [cameraActive, setCameraActive] = useState(false);
  const [scanResult, setScanResult] = useState(null); // Enhanced post-scan result
  // « Récupérer la carte » (user, 2026-10-09): { customerId } after a scan,
  // { find: true } from the button — staff find the client by phone
  const [readd, setReadd] = useState(null);
  const [redeemLoading, setRedeemLoading] = useState(false);
  const [redeemDone, setRedeemDone] = useState(false);
  // Catalog + picker state. When at least one item has qty > 0, the
  // amount_paid field becomes auto-filled (read-only) and the request
  // includes items[] so the server can recompute the total from prices
  // it controls.
  const [catalog, setCatalog] = useState([]);
  // Open by default: line items are what make the 'Top produits' analytics
  // real. When the picker starts collapsed the cashier types a bare amount and
  // the visit carries no items, so the product report stays empty forever.
  // a dropdown now (« Sélectionner un produit… », 2026-10-10): closed until tapped
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQty, setPickerQty] = useState({}); // { [item.id]: qty }
  // App-wide branch context (item #18). Picking a branch here also reflects on every other page.
  const { branchId: _branchIdRaw, setBranchId: _setBranchIdGlobal, branches: _branchesCtx, setBranches: _setBranchesCtx } = useBranch();
  // The establishment of the visit (user, 2026-10-12): the owner picks among
  // all, an administrateur among its own, a manager / employé has one and no
  // menu — the visit counts where it is scanned, never « non taguée ».
  const { user } = useAuth();
  const role = user?.role;
  const open = (Array.isArray(_branchesCtx) ? _branchesCtx : []).filter((b) => b && b.id && b.status !== 'closed');
  const mine = Array.isArray(user?.branch_ids) ? user.branch_ids : null;
  const branches = role === 'business_owner' || !mine ? open : open.filter((b) => mine.includes(b.id));
  const fixedStore = !canSwitchStore(user) || branches.length === 1;
  // « Cet appareil est la caisse » (user, 2026-10-14). A till is left on a
  // counter: marking it keeps its session alive for six months instead of one,
  // and names it in Paramètres › Sécurité so the owner can tell it from their
  // own phone — and cut it from there if it is lost.
  const canPair = role === 'business_owner' || role === 'administrateur';
  const [caisse, setCaisse] = useState(Boolean(user?.caisse));
  const [pairing, setPairing] = useState(false);
  const [pairErr, setPairErr] = useState('');
  // « Code de la caisse »: the server refuses to scan until it is typed here.
  const [locked, setLocked] = useState(false);
  const [code, setCode] = useState('');
  const [codeErr, setCodeErr] = useState('');
  useEffect(() => { setCaisse(Boolean(user?.caisse)); }, [user?.caisse]);

  const branchId = fixedStore ? (branches[0]?.id || '') : (branches.some((b) => b.id === _branchIdRaw) ? _branchIdRaw : '');
  const setBranchId = (id) => _setBranchIdGlobal(id || null);
  const needStore = branches.length > 1 && !branchId;   // several stores, none chosen yet

  useEffect(() => {
    (async () => {
      try {
        const r = await ownerAPI.getBranches();
        _setBranchesCtx(r.data || []);
      } catch (e) { /* no branches, plan doesn't support — fine */ }
    })();
    // Load the tenant catalog so the staff can pick items at scan time.
    (async () => {
      try {
        const c = await ownerAPI.getCatalog?.();
        // A product switched off on Catalogue produits is not offered at the till.
        setCatalog(Array.isArray(c?.data?.items) ? c.data.items.filter((i) => i.active !== false) : []);
      } catch (_e) { /* empty catalog is fine, picker hides itself */ }
    })();
    // Load the tenant's points rule from the card template.
    (async () => {
      try {
        const t = await ownerAPI.getCardTemplate();
        const m = (t.data?.points_mode || 'per_visit').toLowerCase();
        const rate = Number(t.data?.points_per_euro);
        const visit = Number(t.data?.points_per_visit);
        setPointsMode(m === 'per_euro' ? 'per_euro' : 'per_visit');
        setCashback((t.data?.programme || '').toLowerCase() === 'cashback');
        setStampsProgramme(programmeOf(t.data || {}) === 'stamps');
        if (rate && rate > 0) setPointsPerEuro(rate);
        if (visit && visit > 0) setPointsPerVisit(visit);
        const size = Number(t.data?.reward_threshold_stamps);
        if (size && size > 0) setThreshold(size);
      } catch (_e) { /* keep defaults */ }
    })();
    // Load tenant identity so the banner can show "you are at X".
    (async () => {
      try {
        const r = await ownerAPI.getTenant();
        setTenantInfo(r.data || null);
      } catch (_e) { /* silent */ }
    })();
  }, []);

  const videoRef = useRef(null);
  const streamFaceRef = useRef(null);       // which camera the open stream is (front / back)
  const readingRef = useRef(false);         // the detection loop runs (paused: the camera stays open)
  const streamRef = useRef(null);
  const detectorRef = useRef(null);
  const detectionLoopRef = useRef(null);

  // Initialize BarcodeDetector for 1D formats. We DO NOT rely on it for QR
  // because Chrome on macOS / Windows ships BarcodeDetector without QR
  // support — the wallet card's QR would never decode. We use jsQR (loaded
  // from CDN) for QR codes instead, and BarcodeDetector for 1D as a bonus.
  const nativeQrRef = useRef(false);
  useEffect(() => {
    if ('BarcodeDetector' in window) {
      // every 1D format a FidClic card can carry (iOS 27 adds Codabar and ITF)
      const oneD = ['code_128', 'ean_13', 'ean_8', 'code_39', 'upca', 'codabar', 'itf', 'pdf417', 'aztec'];
      const make = (formats) => {
        try { detectorRef.current = new window.BarcodeDetector({ formats }); } catch (error) {
          console.warn('BarcodeDetector not fully supported:', error);
        }
      };
      // Where the browser reads QR itself (Chrome on Android…), it reads it
      // first: much faster and from further away than jsQR (user, 2026-10-15:
      // « bahut paas le jaana padta hai »). macOS / Windows Chrome lack it.
      Promise.resolve(window.BarcodeDetector.getSupportedFormats?.() || [])
        .then((have) => {
          nativeQrRef.current = have.includes('qr_code');
          make(nativeQrRef.current ? ['qr_code', ...oneD.filter((f) => have.includes(f))] : oneD);
        })
        .catch(() => make(oneD));
    }
  }, []);

  // Lazy-load jsQR from cdnjs the first time we open the camera.
  // jsQR works in every modern browser by reading raw image data from
  // a canvas — no native API needed.
  const ensureJsQR = () => new Promise((resolve, reject) => {
    if (typeof window === 'undefined') return reject(new Error('no window'));
    if (window.jsQR) return resolve(window.jsQR);
    const SRC = 'https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.min.js';
    let s = document.querySelector('script[data-jsqr]');
    if (!s) {
      s = document.createElement('script');
      s.src = SRC;
      s.async = true;
      s.dataset.jsqr = '1';
      document.head.appendChild(s);
    }
    const t0 = Date.now();
    (function tick() {
      if (window.jsQR) return resolve(window.jsQR);
      if (Date.now() - t0 > 8000) return reject(new Error('jsQR load timeout'));
      setTimeout(tick, 80);
    })();
  });

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopCamera();
    };
  }, []);

  // the <video> appears a render after the camera tab is chosen
  const waitVideo = () => new Promise((resolve) => {
    let n = 0;
    const tick = () => { if (videoRef.current || n++ > 40) resolve(videoRef.current); else requestAnimationFrame(tick); };
    tick();
  });

  const startCamera = async (face = facing) => {
    try {
      // The camera stays open while the scanner page does (pauseCamera): the
      // next client reuses it. An installed iPhone app asks for the camera
      // again at every opening of it — once per launch now, not per client
      // (user, 2026-10-16).
      const live = streamRef.current?.getVideoTracks?.().some((tr) => tr.readyState === 'live');
      let stream = live && streamFaceRef.current === face ? streamRef.current : null;
      const fresh = !stream;
      if (fresh) {
        if (streamRef.current) stopCamera();
        // HD: at the default 640 × 480 a card a little away has too few pixels
        // for its QR to be read (user, 2026-10-15)
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: face, width: { ideal: 1920 }, height: { ideal: 1080 } },
        });
        streamRef.current = stream;              // kept even if the page is not drawn yet
        streamFaceRef.current = face;
        try {                                   // keep refocusing as the card moves
          const track = stream.getVideoTracks()[0];
          const modes = track?.getCapabilities?.().focusMode || [];
          if (modes.includes('continuous')) await track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] });
        } catch (_e) { /* the browser keeps its own focus */ }
      }

      const video = videoRef.current || await waitVideo();
      if (video) {
        if (video.srcObject !== stream) video.srcObject = stream;
        video.play?.()?.catch?.(() => {});
        setCameraActive(true);
        setStatus(null);
        // « Flash »: only where the camera has a torch (most Android phones)
        if (fresh) {
          try {
            const caps = stream.getVideoTracks()[0]?.getCapabilities?.() || {};
            setTorch({ supported: !!caps.torch, on: false });
          } catch (_e) { setTorch({ supported: false, on: false }); }
        }
        if (detectionLoopRef.current) { cancelAnimationFrame(detectionLoopRef.current); detectionLoopRef.current = null; }

        // Kick off detection. jsQR loads from CDN on first use; we don't
        // wait for it before showing the preview — the loop checks for
        // window.jsQR each frame and starts decoding as soon as it's ready.
        ensureJsQR().catch(() => { /* fall through; BarcodeDetector might still catch 1D */ });
        startDetectionLoop();
      }
    } catch (error) {
      // Old Android Chrome (<v83), Firefox without permission, or any browser
      // where the user tapped "Block". We don't dead-end here — the file/photo
      // upload path below works everywhere with a camera (iOS / Android can
      // even open the camera live from the file picker via capture="environment").
      const ua = navigator.userAgent || '';
      const hint = /Firefox/.test(ua)
        ? t('scan.error_camera_firefox')
        : /Android/.test(ua)
          ? t('scan.error_camera_android')
          : t('scan.error_camera_default');
      setStatus({
        type: 'error',
        message: t('scan.error_camera_full', { hint }),
      });
      setCameraActive(false);
    }
  };

  // Decode a QR/barcode from a still image (file upload or photo picker).
  // Lives next to startCamera() so it shares the same jsQR loader and the
  // same onHit handler. Used by the "Importer une photo" button which is
  // always visible — that's the safety net for old Android Chrome (< v83)
  // and Firefox installs that refuse getUserMedia.
  const [photoMsg, setPhotoMsg] = useState(null);
  const decodeImageFile = async (file) => {
    if (!file) return;
    // its answer sits next to its button (QA R7 F37: the page's message box
    // only shows once a card is found — a photo without a code said nothing)
    setPhotoMsg({ type: 'info', text: 'Lecture de la photo…' });
    try {
      const jsQR = await ensureJsQR();
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      const img = await new Promise((resolve, reject) => {
        const i = new Image();
        i.onload = () => resolve(i);
        i.onerror = reject;
        i.src = dataUrl;
      });
      // Draw onto a canvas, then run jsQR. Cap dimensions to prevent
      // multi-megabyte phone shots from blowing up mobile memory.
      const MAX = 1600;
      const scale = Math.min(1, MAX / Math.max(img.width, img.height));
      const w = Math.round(img.width * scale);
      const h = Math.round(img.height * scale);
      const canvas = document.createElement('canvas');
      canvas.width = w; canvas.height = h;
      const ctx = canvas.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(img, 0, 0, w, h);
      const data = ctx.getImageData(0, 0, w, h);
      const result = jsQR(data.data, data.width, data.height, { inversionAttempts: 'attemptBoth' });
      if (result?.data) {
        const cleaned = barcodeFrom(result.data);
        if (cleaned) {
          setBarcode(cleaned);
          setPhotoMsg({ type: 'success', text: `Code trouvé : ${cleaned}` });
          setMode('manual');
          return;
        }
      }
      // Fall back to native BarcodeDetector if available — handles 1D Code 128.
      if ('BarcodeDetector' in window) {
        try {
          const det = new window.BarcodeDetector({ formats: ['code_128', 'ean_13', 'qr_code', 'pdf417'] });
          const found = await det.detect(canvas);
          if (found?.length && found[0].rawValue) {
            const cleaned = barcodeFrom(found[0].rawValue);
            setBarcode(cleaned);
            setPhotoMsg({ type: 'success', text: `Code trouvé : ${cleaned}` });
            setMode('manual');
            return;
          }
        } catch (_e) { /* ignore */ }
      }
      setPhotoMsg({ type: 'error', text: 'Aucun QR code détecté sur cette photo. Essayez une photo plus nette, ou saisissez le code.' });
    } catch (e) {
      console.debug('decodeImageFile error:', e);
      setPhotoMsg({ type: 'error', text: 'Cette image ne peut pas être lue. Essayez une autre photo (JPG ou PNG), ou saisissez le code.' });
    }
  };

  // the scanner stops reading; the camera stays open for the next client
  const pauseCamera = () => {
    readingRef.current = false;
    if (detectionLoopRef.current) {
      cancelAnimationFrame(detectionLoopRef.current);
      detectionLoopRef.current = null;
    }
    setCameraActive(false);
  };

  const stopCamera = () => {
    readingRef.current = false;
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    if (detectionLoopRef.current) {
      cancelAnimationFrame(detectionLoopRef.current);
      detectionLoopRef.current = null;
    }
    setCameraActive(false);
  };

  const toggleTorch = async () => {
    const track = streamRef.current?.getVideoTracks?.()[0];
    if (!track || !torch.supported) return;
    try {
      await track.applyConstraints({ advanced: [{ torch: !torch.on }] });
      setTorch((t0) => ({ ...t0, on: !t0.on }));
    } catch (_e) { setTorch({ supported: false, on: false }); }
  };
  const flipCamera = () => {
    const next = facing === 'environment' ? 'user' : 'environment';
    setFacing(next);
    startCamera(next);
  };
  // the camera opens by itself when the page does on a phone or tablet — and
  // anywhere the browser already allowed it: no « Activer la caméra » each
  // time (user, 2026-10-15)
  useEffect(() => {
    if (mode === 'camera') { startCamera(); return; }
    try {
      navigator.permissions?.query({ name: 'camera' })
        .then((p) => { if (p.state === 'granted' && navigator.mediaDevices?.getUserMedia) { setMode('camera'); startCamera(); } })
        .catch(() => {});
    } catch (_e) { /* no Permissions API: the tab opens it */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startDetectionLoop = () => {
    readingRef.current = true;
    // Hidden canvas for jsQR — re-used across frames so we don't allocate per tick.
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d', { willReadFrequently: true });

    const onHit = (raw) => {
      if (!raw) return false;
      const cleaned = barcodeFrom(raw);
      if (!cleaned) return false;
      setBarcode(cleaned);
      setStatus({ type: 'success', message: t('scan.code_detected') });
      pauseCamera();                 // open for the next client (no new permission prompt)
      setMode('manual');
      return true;
    };

    // jsQR on the frame's centre (where the corners are drawn), at full
    // detail, with the fast setting; the whole frame, shrunk, every few
    // frames; the slow « both colours » pass now and then (user, 2026-10-15:
    // the QR had to be held very close)
    let frame = 0;
    let native = 0;
    const jsqrPass = (video) => {
      const vw = video.videoWidth;
      const vh = video.videoHeight;
      frame += 1;
      const whole = frame % 3 === 0;
      const side = whole ? null : Math.round(Math.min(vw, vh) * 0.8);
      const sx = whole ? 0 : Math.round((vw - side) / 2);
      const sy = whole ? 0 : Math.round((vh - side) / 2);
      const sw = whole ? vw : side;
      const sh = whole ? vh : side;
      const k = Math.min(1, (whole ? 960 : 800) / Math.max(sw, sh));
      canvas.width = Math.round(sw * k);
      canvas.height = Math.round(sh * k);
      ctx.drawImage(video, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
      const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
      return window.jsQR(img.data, img.width, img.height,
                         { inversionAttempts: frame % 8 === 0 ? 'attemptBoth' : 'dontInvert' });
    };

    const detect = async () => {
      const video = videoRef.current;
      // Don't check cameraActive — that's a state value captured by closure
      // and may be stale. Instead rely on stopCamera() cancelling the rAF.
      if (!video || !streamRef.current || !readingRef.current) return;
      const ready = video.readyState >= 2 && video.videoWidth > 0;

      if (ready) {
        // The browser's own reader first where it reads QR (fast, far)
        if (nativeQrRef.current && detectorRef.current) {
          try {
            const codes = await detectorRef.current.detect(video);
            if (codes.length > 0 && onHit(codes[0].rawValue)) return;
          } catch (e) {
            console.debug('BarcodeDetector error:', e);
          }
          // …and jsQR now and then, should the browser's reader miss it
          native += 1;
          if (window.jsQR && native % 6 === 0) {
            try {
              const result = jsqrPass(video);
              if (result?.data && onHit(result.data)) return;
            } catch (_e) { /* next frame */ }
          }
        } else if (window.jsQR) {
          try {
            const result = jsqrPass(video);
            if (result?.data && onHit(result.data)) return;
          } catch (e) {
            console.debug('jsQR detect error:', e);
          }
        }
        // Try native BarcodeDetector for 1D formats (Code 128, EAN, etc.).
        if (detectorRef.current && !nativeQrRef.current) {
          try {
            const barcodes = await detectorRef.current.detect(video);
            if (barcodes.length > 0 && onHit(barcodes[0].rawValue)) return;
          } catch (e) {
            console.debug('BarcodeDetector error:', e);
          }
        }
      }

      detectionLoopRef.current = requestAnimationFrame(detect);
    };

    detect();
  };

  // Preview of what the server will add — same rule, same rounding as
  // scan_visit() in server.py (the server decides; this is display only).
  const computeAutoPoints = (amount) => {
    if (pointsMode === 'per_euro') {
      const a = parseFloat(amount);
      if (!isNaN(a) && a > 0) return Math.round(a * pointsPerEuro);
      return pointsPerVisit; // no amount → fall back to flat
    }
    return pointsPerVisit; // per_visit mode → always flat
  };


  // Derived: which catalog items currently have a positive qty? + the
  // total (computed client-side for display; the server recomputes its
  // own total from prices it controls when items[] is sent).
  const pickedItems = React.useMemo(() => {
    if (!catalog?.length) return [];
    return catalog
      .map((it) => ({ item: it, qty: Number(pickerQty[it.id]) || 0 }))
      .filter((row) => row.qty > 0);
  }, [catalog, pickerQty]);
  const pickerTotal = pickedItems.reduce(
    (s, { item, qty }) => s + (Number(item.price) || 0) * qty, 0
  );
  const pickerLineItems = pickedItems.map(({ item, qty }) => ({ item_id: item.id, qty }));
  // When the picker has at least one selection, force amount_paid to the
  // picker total — the field is shown read-only in that mode so the
  // cashier can't accidentally type a different number. Every product taken
  // off again: the catalogue's total goes too (QA BUG-004: « − » down to 0
  // left « 10,00 € » in the field, editable again, read as a real amount).
  const amountFromPicker = React.useRef(false);
  React.useEffect(() => {
    if (pickedItems.length > 0) {
      setAmountPaid(pickerTotal.toFixed(2));
      setAmountError(null);                // the catalogue's total replaces what was typed
      amountFromPicker.current = true;
    } else if (amountFromPicker.current) {
      setAmountPaid('');
      amountFromPicker.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickerTotal, pickedItems.length]);

  const bumpQty = (id, delta) => {
    setPickerQty((prev) => {
      const next = { ...prev };
      const cur = Number(next[id]) || 0;
      const v = Math.max(0, cur + delta);
      if (v === 0) delete next[id]; else next[id] = v;
      return next;
    });
  };
  const clearPicker = () => setPickerQty({});

  // The paper-card field: digits only, 0 to what this card can still take.
  const catalogMissing = catalog.length > 0 && pickedItems.length === 0;

  const handleScan = async (e) => {
    e.preventDefault();
    if (!barcode.trim()) return;
    if (amountError) {
      setStatus({ type: 'error', message: amountError });
      return;
    }

    const parsedAmount = amountPaid.trim() === '' ? 0.0 : parseFloat(amountPaid);
    if (isNaN(parsedAmount) || parsedAmount < 0) {
        setStatus({ type: 'error', message: t('scan.error_invalid_amount') });
        return;
    }
    if (catalog.length > 0 && pickedItems.length === 0) {
      setStatus({ type: 'error', message: 'Choisissez au moins un produit du catalogue.' });
      return;
    }
    if (paperError) {
      setStatus({ type: 'error', message: paperError });
      return;
    }
    if (needStore) {
      setStatus({ type: 'error', message: "Choisissez l'établissement où a lieu le passage." });
      return;
    }

    setLoading(true);
    setStatus(null);
    setScanResult(null);
    try {
      const res = await ownerAPI.scanVisit({
        barcode_id: barcode.trim(),
        amount_paid: parsedAmount,
        branch_id: branchId || undefined,
        // When the cashier picked items from the catalog, send the list
        // so the server can recompute the authoritative total + store
        // the line items on the visit for analytics.
        items: pickerLineItems.length > 0 ? pickerLineItems : undefined,
        // stamps of the paper card, once per customer (the server checks it all again)
        paper_stamps: paperCount > 0 ? paperCount : undefined,
      });

      // Backend returns full customer object + cycle-aware stamp math.
      // We no longer derive stamps from `visits` directly — that field is
      // the LIFETIME counter and would falsely re-fire "Reward unlocked!"
      // every scan after a redemption (a customer at 12 lifetime visits
      // who already redeemed at 10 would show "12/10 → reward unlocked"
      // forever). The server now ships stamps_in_cycle + reward_threshold
      // + reward_unlocked computed from (visits - visits_at_last_redemption).
      const customerData = res.data;
      const pointsEarned = customerData.points_earned ?? 0;   // the server's own count
      const stampsCurrent = customerData.stamps_in_cycle ?? 0;
      const stampsRequired = customerData.reward_threshold ?? 10;
      const canRedeem = !!customerData.reward_unlocked;

      setRedeemDone(false);                     // a new receipt, a new customer
      setScanResult({
        customer_id: customerData.id,
        barcode_id: customerData.barcode_id,
        customer_name: customerData.name,
        points_earned: pointsEarned,
        stamps_current: stampsCurrent,
        stamps_required: stampsRequired,
        reward_unlocked: canRedeem,
        // full cards not yet handed over — still valid (user, 2026-10-09)
        rewards_pending: customerData.rewards_pending || 0,
        // the card left the client's phone (features/card_status)
        card_state: customerData.card_state || null,
        // Backend now returns these so the cashier sees tier-up celebrations.
        tier: customerData.tier || null,
        previous_tier: customerData.previous_tier || null,
        tier_upgraded: !!customerData.tier_upgraded,
        // where this visit was scanned (not the customer's home store)
        branch_id: customerData.visit_branch_id || branchId || null,
        // Notification subscription status — drives the "encourage enable
        // notifications" prompt staff sees post-scan. Customers without
        // push subscriptions get a QR code they can scan to enable.
        notification_status: customerData.notification_status || 'unknown',
        card_key: customerData.card_key || null,
        paper_stamps: customerData.paper_stamps || 0,
        defis_won: customerData.defis_won || [],
        defi_rewards: customerData.defi_rewards || [],
        offers_active: customerData.offers_active || [],
        // in the card's own unit (QA BUG-009)
        programme: customerData.programme || null,
        stamps_earned: customerData.stamps_earned ?? (1 + (customerData.paper_stamps || 0)),
        stamps_on_card: customerData.stamps_on_card,
        stamps_target: customerData.stamps_target,
        referral_reward: customerData.referral_reward || '',
      });
      setStatus({ type: 'success', message: t('scan.success') });
      setBarcode('');
      setAmountPaid('');
      setPaperStamps('');
      clearPicker();
      setPickerOpen(false);
    } catch (error) {
      // Verbose diagnostic so we stop guessing what the server actually said.
      console.error('Scan failed:', error);
      const status = error.response?.status;
      const detail = error.response?.data?.detail;
      // The till has a code and it has not been typed on this device today.
      // Ask for it here rather than showing the scan as failed (user, 2026-10-14).
      if (status === 423 || detail?.code === 'CAISSE_LOCKED') { setLocked(true); setLoading(false); return; }
      const rawBody = (() => {
        try {
          if (typeof error.response?.data === 'string') return error.response.data.slice(0, 200);
          if (error.response?.data) return JSON.stringify(error.response.data).slice(0, 200);
        } catch (_e) { /* ignore */ }
        return '';
      })();
      let msg;
      if (detail) {
        msg = detail;
      } else if (status) {
        msg = t('scan.error_http', { status, body: rawBody || t('scan.error_http_empty') });
      } else {
        msg = t('scan.error_network', { msg: error.message || t('scan.error_network_no_message') });
      }
      setStatus({ type: 'error', message: msg });
    } finally {
      setLoading(false);
    }
  };

  const inputBox = 'flex min-w-0 items-stretch overflow-hidden rounded-xl border border-[#E2E8F0] bg-white focus-within:border-[#2F6BFF] focus-within:ring-2 focus-within:ring-[#2F6BFF]/15';
  const iconCell = 'flex w-[52px] shrink-0 items-center justify-center border-r border-[#E2E8F0] text-[#64748B]';
  const fieldCls = 'min-w-0 flex-1 !border-0 !rounded-none bg-transparent !px-4 py-3.5 !text-[16px] text-[#0B1C3F] !shadow-none !outline-none !ring-0 placeholder:text-[#94A3B8]';
  const amountHint = pickedItems.length > 0
    ? 'Calculé à partir des produits choisis.'
    : cashback
      ? 'Cashback : un pourcentage du montant est crédité au client.'
      : pointsMode === 'per_euro'
        ? `${pointsPerEuro} point${pointsPerEuro > 1 ? 's' : ''} par euro dépensé.`
        : stampsProgramme
          ? 'Le montant ne change pas les tampons : ils se comptent par visite.'
          : 'Le montant ne change pas les points dans ce mode (forfait par visite). Le commerçant peut le modifier dans les réglages.';
  const switchMode = (key) => {
    setMode(key);
    if (status?.type === 'error') setStatus(null);      // a camera error does not follow to the form
    if (key === 'manual') pauseCamera();
    else if (!cameraActive) startCamera();
  };

  // ---------------------------------------------------------------------
  // V2 — the card scanned, then one form (user, 2026-10-13)
  // ---------------------------------------------------------------------
  // `card` is the whole client in one answer (features/scan_page): balance,
  // palier, everything applicable, the paper card — the till's one answer.
  const [card, setCard] = useState(null);
  const [cardErr, setCardErr] = useState('');
  const [picked, setPicked] = useState({});        // { catalogue item id: qty }
  const [apply, setApply] = useState('');          // ONE offer or reward, never several
  const [manual, setManual] = useState(false);     // the counter typed the final amount
  const [panel, setPanel] = useState(false);       // the catalogue drawer
  const [panelQ, setPanelQ] = useState('');
  const [panelCat, setPanelCat] = useState('Tous');
  const [paperOn, setPaperOn] = useState(false);

  // Everything the paper card needs comes from /scan/card (features/scan_page),
  // which already answers for this very client — asking /scan/preview for the
  // same card a second time cost a round trip per lookup and told us nothing new.
  const paperMax = card ? card.paper.max : threshold;
  const paperCount = paperStamps === '' ? 0 : parseInt(paperStamps, 10) || 0;
  const paperError = card?.paper?.done && paperCount > 0
    ? 'La carte papier de ce client a déjà été transférée.'
    : paperCount > paperMax
      ? (card && card.balance.value > 0
        ? `Cette carte a déjà ${card.balance.value} ${card.balance.unit} : ${paperMax} au maximum.`
        : `${paperMax} tampons au maximum (une carte complète).`)
      : null;

  const words = card?.wording || { one: 'produit', many: 'produits', picker: 'Choisir un produit',
    picker_sub: '', field: 'Produit du catalogue', catalogue: 'Catalogue produits', search: 'Rechercher…' };

  // The card is fetched for a complete code only — one request per client,
  // not one per keystroke.
  useEffect(() => {
    const bc = barcodeFrom(barcode);
    if (!bc || bc.length < 4) { setCard(null); setCardErr(''); return undefined; }
    let alive = true;
    const t = setTimeout(() => {
      ownerAPI.scanCard(bc)
        .then(({ data }) => {
          if (!alive) return;
          setCard(data); setCardErr('');
          // the client is found: the camera's complaint from before is old news
          setStatus((st) => (st && st.type === 'error' && /cam[ée]ra/i.test(st.message || '') ? null : st));
        })
        .catch((e) => { if (!alive) return; setCard(null); setCardErr(e?.response?.data?.detail || ''); });
    }, 250);
    return () => { alive = false; clearTimeout(t); };
  }, [barcode]);

  // What has been picked, in the order of the catalogue, with its price.
  const lines = React.useMemo(() => (catalog || [])
    .filter((it) => (Number(picked[it.id]) || 0) > 0)
    .map((it) => ({ id: it.id, name: it.name, price: Number(it.price) || 0, qty: Number(picked[it.id]) })),
  [catalog, picked]);
  const linesTotal = lines.reduce((s, l) => s + l.price * l.qty, 0);

  const chosen = (card?.applicables || []).find((a) => a.id === apply) || null;
  // The offer takes its discount off; the server does the same sum on the
  // real prices, so what is shown here is what will be recorded.
  const discount = (() => {
    if (!chosen || chosen.kind !== 'offer' || !chosen.discount_value) return 0;
    return chosen.discount_type === 'percent'
      ? linesTotal * Number(chosen.discount_value) / 100
      : Math.min(linesTotal, Number(chosen.discount_value));
  })();
  const autoAmount = Math.max(0, linesTotal - discount);
  // Nothing picked → 0,00 €, as the counter expects.
  const shownAmount = manual ? amountPaid : (linesTotal > 0 ? autoAmount.toFixed(2) : '');

  const bump = (id, d) => setPicked((prev) => {
    const next = { ...prev };
    const v = Math.max(0, (Number(next[id]) || 0) + d);
    if (v === 0) delete next[id]; else next[id] = v;
    return next;
  });

  const cats = React.useMemo(() => {
    const out = [];
    (catalog || []).forEach((it) => { const c = (it.category || '').trim(); if (c && !out.includes(c)) out.push(c); });
    return ['Tous', ...out];
  }, [catalog]);
  const panelItems = (catalog || []).filter((it) => {
    const okCat = panelCat === 'Tous' || (it.category || '').trim() === panelCat;
    const q = panelQ.trim().toLowerCase();
    return okCat && (!q || (it.name || '').toLowerCase().includes(q));
  });
  const panelTotal = lines.reduce((s, l) => s + l.price * l.qty, 0);

  const resetVisit = () => { setPicked({}); setApply(''); setManual(false); setAmountPaid(''); setAmountErr(null); setPaperStamps(''); setPaperOn(false); };
  const amountProblem = amountErr
    || (manual && amountPaid !== '' && !/^\d+(\.\d{1,2})?$/.test(amountPaid) ? 'Montant invalide : un nombre positif, par exemple 12,50.' : null);
  // The visit just recorded (user, 2026-10-13: « visit ek baar record ho gyi toh
  // waapis kyun de rhe ho option »): from then on the page is its summary —
  // no form, no second « Enregistrer la visite » for the same scan (it made a
  // second visit at 0 €). The next visit starts from a new scan or code.
  const [recorded, setRecorded] = useState(null);
  // Every scan is a new visit, in steps (user, 2026-10-14): 1. the products and
  // services, « Suivant » → 2. the récap, where the offer or reward is chosen,
  // « Enregistrer la visite » → 3. the summary. Even the same card scanned again
  // right away starts at step 1, like any visit.
  const [step, setStep] = useState('items');
  const scanAnother = () => { resetVisit(); setBarcode(''); setCard(null); setScanResult(null); setStatus(null); setRecorded(null); setStep('items'); };
  // « Autre » and the bottom bar's « Scanner » on this page: a clean page, the
  // camera back on where there is one (user, 2026-10-16: « scanner button
  // does not open the scanner » after a visit)
  const scanAgain = () => {
    scanAnother();
    if (navigator.mediaDevices?.getUserMedia) switchMode('camera');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };
  useEffect(() => {
    window.addEventListener('fc:scan-again', scanAgain);
    return () => window.removeEventListener('fc:scan-again', scanAgain);
  });
  // a new code read (camera, photo, typed): a new visit, not the last one's summary
  useEffect(() => { setRecorded(null); setStep('items'); }, [barcode]);

  // The scanner (douchette) works from anywhere on this page, no field to click
  // first: its burst opens the client, like the camera does — then the
  // products, the offer or reward, « Enregistrer la visite » (user, 2026-10-14).
  // A visit being filled in is never thrown away by a stray scan.
  const busyVisit = Boolean(card) && !recorded && (step !== 'items' || lines.length > 0 || manual || Boolean(apply));
  const scanState = useRef({});
  scanState.current = { card, busyVisit, mode };
  useEffect(() => {
    let typed = '', physical = '', last = 0, timer = null;
    const reset = () => { typed = ''; physical = ''; clearTimeout(timer); timer = null; };
    const finish = () => {
      const bc = typed.length >= 6 ? codeFromBurst(typed, physical) : '';
      reset();
      if (!bc) return false;
      const st = scanState.current;
      if (st.busyVisit) {
        setStatus({ type: 'info', message: 'Une visite est en cours : enregistrez-la ou annulez-la avant de scanner un autre client.' });
        return true;
      }
      if (st.mode === 'camera') { pauseCamera(); setMode('manual'); }
      if (st.card) {
        scanAnother();                         // a new client, or the same one again: a new visit
        setTimeout(() => setBarcode(bc), 0);
      } else {
        setBarcode(bc);
      }
      return true;
    };
    const onKey = (e) => {
      const el = e.target;
      const editable = el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
      if (editable && el.id !== 'scan-card-id') { reset(); return; }   // the amount, a search: theirs
      if (e.ctrlKey || e.metaKey || e.altKey) { reset(); return; }
      const now = performance.now();
      if (now - last > 60) reset();           // a person types slower than a scanner
      last = now;
      if (e.key === 'Enter' || e.key === 'Tab' || e.code === 'NumpadEnter') {
        if (typed.length >= 6 && finish()) { e.preventDefault(); e.stopPropagation(); }
        return;
      }
      if (e.key.length !== 1) return;          // Shift and the like
      typed += e.key;
      physical += usChar(e);
      clearTimeout(timer);
      timer = setTimeout(() => { if (typed.length >= 8) finish(); else reset(); }, 150);   // a scanner set without Enter
    };
    window.addEventListener('keydown', onKey, true);
    return () => { window.removeEventListener('keydown', onKey, true); clearTimeout(timer); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const paperTooMany = paperOn && parseInt(paperStamps || '0', 10) > (card?.paper?.max ?? 0);

  const registerVisit = async () => {
    if (!card) return;
    const amount = manual ? parseFloat(amountPaid || '0') : autoAmount;
    if (Number.isNaN(amount) || amount < 0) { setStatus({ type: 'error', message: 'Montant invalide.' }); return; }
    const paper = paperOn ? parseInt(paperStamps || '0', 10) || 0 : 0;
    setLoading(true); setStatus(null);
    try {
      const { data } = await ownerAPI.scanVisit({
        barcode_id: card.customer.barcode_id,
        amount_paid: Number(amount.toFixed ? amount.toFixed(2) : amount),
        amount_manual: manual,
        items: lines.length ? lines.map((l) => ({ item_id: l.id, qty: l.qty })) : undefined,
        apply: apply || undefined,
        paper_stamps: paper > 0 ? paper : undefined,
        branch_id: branchId || undefined,
      });
      setScanResult(data);
      setRecorded({ amount, lines, applied: chosen ? chosen.title : '', paper, data });
      const failed = data.applied && data.applied.ok === false;
      // the summary below says « Visite enregistrée »; a banner only when the offer could not apply
      setStatus(failed ? { type: 'info', message: `Offre non appliquée : ${data.applied.error}` } : null);
      resetVisit();
      setStep('items');
      // the card changed (stamps, reward used): read it again
      ownerAPI.scanCard(card.customer.barcode_id).then(({ data: d2 }) => setCard(d2)).catch(() => {});
    } catch (e) {
      setStatus({ type: 'error', message: e?.response?.data?.detail || "La visite n'a pas pu être enregistrée." });
    } finally { setLoading(false); }
  };

  const money = (n) => `${Number(n || 0).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
  // The owner's phone (user, 2026-10-15: « mobile mein ekdm easy, especially
  // for scanning »): the camera fits the screen, the client is one line, the
  // products are tiles under the thumb, and the next step stays at the bottom.
  const [phone, setPhone] = useState(() => typeof window !== 'undefined' && !!window.matchMedia?.('(max-width: 639px)').matches);
  useEffect(() => {
    const mq = window.matchMedia?.('(max-width: 639px)');
    if (!mq) return undefined;
    const on = () => setPhone(mq.matches);
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);
  const payNow = step === 'review' ? (manual ? parseFloat(amountPaid || '0') || 0 : autoAmount)
    : (manual ? parseFloat(amountPaid || '0') || 0 : (linesTotal > 0 ? autoAmount : 0));
  const dayFR = (iso) => { try { return new Date(iso).toLocaleDateString('fr-FR'); } catch { return ''; } };

  return (
    <div className={`sc mx-auto max-w-[1100px] space-y-5 ${card ? 'pb-40 sm:pb-10' : 'pb-10'}`}>
      <style>{`@keyframes scanline{0%{top:18%}50%{top:78%}100%{top:18%}}`}</style>

      {!card ? (
        <>
          <div className="pt-2 text-center">
            <h1 className="text-[24px] font-extrabold leading-tight tracking-tight text-[#0B1C3F] sm:text-[32px]">Enregistrer une visite</h1>
            <p className="mx-auto mt-2 hidden max-w-[560px] text-[15px] text-[#64748B] sm:block">
              Scannez le code de la carte client pour identifier le client.
            </p>
          </div>

          <div className="mx-auto flex w-fit gap-1 rounded-xl bg-[#F1F5F9] p-1">
            {[['camera', 'Caméra', Camera], ['manual', 'Saisir le code', Keyboard]].map(([k, l, I]) => (
              <button key={k} type="button" onClick={() => switchMode(k)}
                      aria-pressed={mode === k}
                      className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-[13px] font-semibold ${mode === k ? 'bg-white text-[#0B1C3F] shadow-sm' : 'text-[#64748B]'}`}>
                <I size={15} /> {l}
              </button>
            ))}
          </div>

          {mode === 'camera' && (
            <div className="relative mx-auto aspect-[3/4] w-full max-w-[760px] overflow-hidden rounded-[28px] bg-[#0B1220] shadow-[0_24px_60px_-30px_rgba(15,23,42,.7)] sm:aspect-video sm:min-h-[300px]">
              <video ref={videoRef} autoPlay playsInline muted className="absolute inset-0 h-full w-full object-cover" />
              <div aria-hidden="true" className="pointer-events-none absolute left-1/2 top-1/2 h-[52%] w-[72%] -translate-x-1/2 -translate-y-1/2 sm:h-[62%] sm:w-[min(46%,340px)]">
                {['left-0 top-0 border-l-4 border-t-4 rounded-tl-2xl', 'right-0 top-0 border-r-4 border-t-4 rounded-tr-2xl',
                  'left-0 bottom-0 border-l-4 border-b-4 rounded-bl-2xl', 'right-0 bottom-0 border-r-4 border-b-4 rounded-br-2xl'].map((c) => (
                  <span key={c} className={`absolute h-10 w-10 border-[#4F8BFF] [filter:drop-shadow(0_0_6px_rgba(79,139,255,.95))] ${c}`} />
                ))}
                {cameraActive && <span className="absolute left-2 right-2 h-[2px] rounded-full bg-[#7FB0FF] shadow-[0_0_14px_4px_rgba(79,139,255,.65)]" style={{ animation: 'scanline 2.4s ease-in-out infinite' }} />}
              </div>
              <div className="absolute right-4 top-4 flex flex-col items-center gap-1">
                <button type="button" onClick={toggleTorch} disabled={!torch.supported} aria-pressed={torch.on} title="Flash"
                        className={`flex h-12 w-12 items-center justify-center rounded-full border border-white/40 backdrop-blur transition disabled:opacity-40 ${torch.on ? 'bg-white text-[#0B1C3F]' : 'bg-black/35 text-white'}`}>
                  <Zap size={20} fill={torch.on ? 'currentColor' : 'none'} />
                </button>
              </div>
              <div className="absolute left-4 top-4 flex flex-col items-center gap-1">
                <button type="button" onClick={flipCamera} title="Changer de caméra"
                        className="flex h-12 w-12 items-center justify-center rounded-full border border-white/40 bg-black/35 text-white backdrop-blur">
                  <SwitchCamera size={20} />
                </button>
              </div>
              {cameraActive ? (
                <div className="absolute bottom-4 left-1/2 w-[min(92%,480px)] -translate-x-1/2 rounded-2xl border border-white/10 bg-[#0B1220]/85 px-4 py-3 text-center backdrop-blur">
                  <p className="text-[14px] font-semibold text-white">Placez le QR code de la carte dans le cadre</p>
                </div>
              ) : (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
                  <Camera size={34} className="text-white/80" />
                  <button type="button" onClick={() => startCamera()} className="rounded-full bg-[#1463FF] px-5 py-2.5 text-[14px] font-semibold text-white">Activer la caméra</button>
                </div>
              )}
            </div>
          )}

          {/* the typed code is « Saisir le code »'s; the camera tab is the camera
              only (user, 2026-10-15) — a douchette still works on either */}
          {mode === 'manual' && (
          <div className="mx-auto max-w-[520px]">
            <label className="block text-[13px] font-medium text-[#334155]">Code de la carte
              <input id="scan-card-id" value={barcode} onChange={(e) => setBarcode(e.target.value)} placeholder="FT-A1B2C3D4"
                     translate="no" className="notranslate mt-1 w-full rounded-xl border border-[#E2E8F0] px-4 py-3 text-[16px] uppercase text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />
            </label>
            <p className="mt-1.5 text-[12.5px] text-[#64748B]">Douchette USB ou Bluetooth : scannez directement, sans cliquer ici.</p>
            {cardErr && <p className="mt-2 text-[13px] text-[#C0392B]">{cardErr}</p>}
            <label className="mt-3 flex w-fit cursor-pointer items-center gap-2 text-[13px] font-semibold text-[#2F6BFF]">
              <ImageUp size={15} /> Importer une photo du code
              {/* the same photo can be chosen again after a miss */}
              <input type="file" accept="image/*" className="hidden" onChange={(e) => { decodeImageFile(e.target.files?.[0]); e.target.value = ''; }} />
            </label>
            {photoMsg && (
              <div role={photoMsg.type === 'error' ? 'alert' : 'status'} data-testid="photo-msg"
                   className={`mt-2 flex items-start justify-between gap-3 rounded-xl px-3.5 py-2.5 text-[13px] ${photoMsg.type === 'success' ? 'bg-[#E7F7EE] text-[#0F7A45]' : photoMsg.type === 'info' ? 'bg-[#FFF7E6] text-[#92400E]' : 'bg-[#FEF2F2] text-[#B91C1C]'}`}>
                <span>{photoMsg.text}</span>
                {photoMsg.type === 'error' && (
                  <label className="shrink-0 cursor-pointer font-semibold underline">
                    Réessayer
                    <input type="file" accept="image/*" className="hidden" onChange={(e) => { decodeImageFile(e.target.files?.[0]); e.target.value = ''; }} />
                  </label>
                )}
              </div>
            )}
          </div>
          )}
        </>
      ) : (
        <>
          {/* phone: the client in one line, « Autre carte » at hand */}
          <div className="flex items-center gap-3 rounded-2xl border border-[#E6EEFB] bg-white p-3 sm:hidden" data-testid="client-line">
            <CheckCircle2 size={22} className="shrink-0 text-[#10B981]" />
            <div className="min-w-0 flex-1">
              <p translate="no" className="notranslate truncate text-[16px] font-bold text-[#0B1C3F]">{card.customer.name || `Client ${card.customer.barcode_id}`}</p>
              <p className="truncate text-[12.5px] text-[#475569]">
                <b className="text-[#2F6BFF]">{card.balance.value}</b> {card.balance.unit}{card.balance.tier_label ? ` · ${card.balance.tier_label}` : ''}
              </p>
            </div>
            <button type="button" onClick={scanAgain} aria-label="Scanner une autre carte"
                    className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-xl border border-[#E2E8F0] px-3 text-[13px] font-semibold text-[#334155]">
              <ScanLine size={16} /> Autre
            </button>
          </div>
          <div className="hidden items-start justify-between gap-3 sm:flex">
            <div className="flex-1 text-center">
              <p className="inline-flex items-center gap-2 text-[28px] font-extrabold text-[#0B1C3F]">
                <CheckCircle2 size={28} className="text-[#10B981]" /> Client scanné
              </p>
              <p className="mt-1 text-[14px] text-[#64748B]">Les informations du client sont affichées ci-dessous.</p>
            </div>
            <button type="button" onClick={scanAnother}
                    className="inline-flex shrink-0 items-center gap-2 rounded-xl border border-[#E2E8F0] bg-white px-4 py-2.5 text-[13px] font-medium text-[#334155]">
              <ScanLine size={15} /> Scanner une autre carte
            </button>
          </div>

          {status && (
            <div className={`rounded-xl px-4 py-3 text-[13.5px] ${status.type === 'success' ? 'bg-[#E7F7EE] text-[#0F7A45]' : status.type === 'info' ? 'bg-[#FFF7E6] text-[#92400E]' : 'bg-[#FEF2F2] text-[#B91C1C]'}`}>
              {status.message}
            </div>
          )}

          {/* the client, and the one figure the card shows */}
          <div className="hidden gap-4 rounded-2xl border border-[#E6EEFB] bg-white p-5 sm:grid sm:grid-cols-2">
            <div className="flex items-center gap-4">
              <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-[#EAF1FF] text-[#2F6BFF]"><Building2 size={26} /></span>
              <div className="min-w-0">
                <p translate="no" className="notranslate truncate text-[20px] font-bold text-[#0B1C3F]">{card.customer.name || `Client ${card.customer.barcode_id}`}</p>
                {card.customer.phone && <p className="truncate text-[13.5px] text-[#475569]">{card.customer.phone}</p>}
                {card.customer.email && <p translate="no" className="notranslate truncate text-[13.5px] text-[#475569]">{card.customer.email}</p>}
                {card.customer.since && <p className="text-[13px] text-[#64748B]">Client depuis le {dayFR(card.customer.since)}</p>}
              </div>
            </div>
            <div className="sm:border-l sm:border-[#EEF3FB] sm:pl-5">
              <p className="text-[13.5px] font-semibold text-[#0B1C3F]">Carte de fidélité</p>
              <p className="mt-1 flex items-baseline gap-2">
                <span className="text-[34px] font-extrabold leading-none text-[#2F6BFF]">{card.balance.value}</span>
                <span className="text-[15px] text-[#475569]">{card.balance.unit}</span>
                {card.balance.tier_label && <span className="ml-auto rounded-full bg-[#FFF4DB] px-3 py-1 text-[12px] font-semibold text-[#92400E]">{card.balance.tier_label}</span>}
              </p>
              <span className="mt-2 block h-2 w-full overflow-hidden rounded-full bg-[#EEF3FB]">
                <span className="block h-full rounded-full bg-[#2F6BFF]" style={{ width: `${Math.min(100, card.balance.pct)}%` }} />
              </span>
              <p className="mt-1 text-[12.5px] text-[#64748B]">{card.balance.next_label}</p>
            </div>
          </div>

          <ol className="flex items-center justify-center gap-2 text-[12.5px] font-semibold" aria-label="Étapes de la visite">
            {[['items', `1. ${words.many.charAt(0).toUpperCase() + words.many.slice(1)}`], ['review', '2. Récapitulatif'], ['done', '3. Terminé']].map(([k, l], i) => {
              const at = recorded ? 'done' : step;
              const order = ['items', 'review', 'done'];
              const past = order.indexOf(k) < order.indexOf(at);
              return (
                <React.Fragment key={k}>
                  {i > 0 && <span className="h-px w-8 bg-[#CBD5E1]" />}
                  <li aria-current={k === at ? 'step' : undefined}
                      className={`rounded-full px-3 py-1 ${k === at ? 'bg-[#1463FF] text-white' : past ? 'bg-[#E7F7EE] text-[#0F7A45]' : 'bg-[#F1F5F9] text-[#64748B]'}`}>{l}</li>
                </React.Fragment>
              );
            })}
          </ol>

          {recorded && (
            <div className="rounded-2xl border border-[#BFE8D1] bg-white p-5" data-testid="visit-summary">
              <p className="flex items-center gap-2 text-[16px] font-bold text-[#0B1C3F]">
                <CheckCircle2 size={18} className="text-[#10B981]" /> Visite enregistrée
              </p>
              <dl className="mt-3 grid gap-x-6 gap-y-2 text-[13.5px] sm:grid-cols-2">
                <div className="flex justify-between gap-3 border-b border-[#F1F5F9] pb-2"><dt className="text-[#64748B]">Montant payé</dt><dd className="font-semibold text-[#0B1C3F]">{money(recorded.amount)}</dd></div>
                <div className="flex justify-between gap-3 border-b border-[#F1F5F9] pb-2"><dt className="text-[#64748B]">Cette visite</dt><dd className="font-semibold text-[#0F7A45]">{
                  recorded.data?.programme === 'stamps'
                    ? `+${recorded.data?.stamps_earned ?? 0} tampon${(recorded.data?.stamps_earned ?? 0) > 1 ? 's' : ''}${recorded.paper ? `, dont ${recorded.paper} de la carte papier` : ''}`
                    : recorded.data?.programme === 'cashback'
                      // a cagnotte credits euros (QA R7 F39: the receipt said « +100 points »)
                      ? `+${money((recorded.data?.points_earned ?? 0) / 100)} de cagnotte`
                      : `+${recorded.data?.points_earned ?? 0} point${(recorded.data?.points_earned ?? 0) > 1 ? 's' : ''}`}</dd></div>
                {recorded.lines.length > 0 && (
                  <div className="flex justify-between gap-3 border-b border-[#F1F5F9] pb-2 sm:col-span-2"><dt className="text-[#64748B]">{words.many.charAt(0).toUpperCase() + words.many.slice(1)}</dt>
                    <dd className="text-right text-[#0B1C3F]">{recorded.lines.map((l) => `${l.qty} × ${l.name}`).join(', ')}</dd></div>
                )}
                {recorded.applied && (
                  <div className="flex justify-between gap-3 border-b border-[#F1F5F9] pb-2 sm:col-span-2"><dt className="text-[#64748B]">Offre / Récompense</dt>
                    <dd className="text-right text-[#0B1C3F]">{recorded.applied}{recorded.data?.applied?.ok === false ? ' — non appliquée' : ''}</dd></div>
                )}
                {recorded.data?.referral_reward && (
                  <div className="flex justify-between gap-3 border-b border-[#F1F5F9] pb-2 sm:col-span-2"><dt className="text-[#64748B]">Parrainage</dt>
                    <dd className="text-right text-[#EA580C]">🎁 {recorded.data.referral_reward}</dd></div>
                )}
              </dl>
              <button type="button" onClick={scanAnother}
                      className="mt-5 hidden w-full items-center justify-center gap-2 rounded-xl bg-[#1463FF] py-3.5 text-[15px] font-semibold text-white sm:inline-flex">
                <ScanLine size={17} /> Scanner une autre carte
              </button>
            </div>
          )}

          {/* the visit itself — until it is recorded */}
          {!recorded && step === 'items' && (
          <div className="rounded-2xl border border-[#E6EEFB] bg-white p-5" data-testid="visit-items">
            <p className="mb-3 text-[16px] font-bold text-[#0B1C3F]">Enregistrer une visite</p>

            {phone && (catalog || []).length > 0 && (
              <div data-testid="product-tiles">
                <p className="mb-2 text-[13px] font-semibold text-[#334155]">Touchez pour ajouter</p>
                {(catalog || []).length > 8 && (
                  <input value={panelQ} onChange={(e) => setPanelQ(e.target.value)} placeholder={words.search}
                         className="mb-2 w-full rounded-xl border border-[#E2E8F0] px-3 py-2.5 text-[15px] outline-none focus:border-[#2F6BFF]" />
                )}
                {cats.length > 2 && (
                  <div className="-mx-1 mb-2 flex gap-1.5 overflow-x-auto px-1 pb-1">
                    {cats.map((c) => (
                      <button key={c} type="button" onClick={() => setPanelCat(c)} aria-pressed={panelCat === c}
                              className={`shrink-0 rounded-full px-3 py-1.5 text-[12.5px] font-semibold ${panelCat === c ? 'bg-[#1463FF] text-white' : 'bg-[#F1F5F9] text-[#475569]'}`}>{c}</button>
                    ))}
                  </div>
                )}
                <div className="grid grid-cols-2 gap-2">
                  {panelItems.map((it) => {
                    const q = Number(picked[it.id]) || 0;
                    return (
                      <div key={it.id} className={`relative rounded-xl border ${q > 0 ? 'border-[#2F6BFF] bg-[#F5F9FF]' : 'border-[#E6EEFB] bg-white'}`}>
                        <button type="button" onClick={() => bump(it.id, 1)} aria-label={`Ajouter ${it.name}`}
                                className="flex min-h-[72px] w-full flex-col items-start justify-between gap-1 p-3 text-left">
                          <span className="line-clamp-2 text-[13.5px] font-semibold leading-snug text-[#0B1C3F]">{it.name}</span>
                          <span className="text-[13px] text-[#475569]">{money(it.price)}</span>
                        </button>
                        {q > 0 && (
                          <span className="absolute bottom-2 right-2 flex items-center gap-1">
                            <button type="button" onClick={() => bump(it.id, -1)} aria-label={`Moins ${it.name}`}
                                    className="flex h-7 w-7 items-center justify-center rounded-full border border-[#C9DBFB] bg-white text-[15px] font-bold text-[#1463FF]">−</button>
                            <span className="flex h-7 min-w-[28px] items-center justify-center rounded-full bg-[#1463FF] px-1.5 text-[13px] font-bold text-white">{q}</span>
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            <div className={`flex-wrap items-center justify-between gap-2 ${phone && (catalog || []).length > 0 ? 'hidden' : 'flex'}`}>
              <p className="text-[13.5px] font-semibold text-[#334155]">{words.field}</p>
              <button type="button" onClick={() => setPanel(true)}
                      className="inline-flex items-center gap-2 rounded-xl border border-[#2F6BFF] px-4 py-2 text-[13px] font-medium text-[#2F6BFF]">
                <Package size={15} /> {words.picker} <ChevronDown size={14} />
              </button>
            </div>

            {phone && (catalog || []).length > 0 ? null : lines.length === 0 ? (
              <p className="mt-2 rounded-xl bg-[#F8FAFF] px-4 py-3 text-[13px] text-[#64748B]">
                Aucun {words.one} sélectionné — le montant reste à 0,00 €.
              </p>
            ) : (
              <ul className="mt-2 divide-y divide-[#F4F7FC] rounded-xl border border-[#EEF3FB]">
                {lines.map((l) => (
                  <li key={l.id} className="flex items-center gap-3 px-3 py-2.5">
                    <span className="min-w-0 flex-1 truncate text-[13.5px] text-[#0B1C3F]">{l.name}</span>
                    <span className="flex items-center gap-1">
                      <button type="button" aria-label="Moins" onClick={() => bump(l.id, -1)} className="h-7 w-7 rounded-lg border border-[#E2E8F0] text-[#334155]">−</button>
                      <span className="w-7 text-center text-[13px] font-semibold tabular-nums">{l.qty}</span>
                      <button type="button" aria-label="Plus" onClick={() => bump(l.id, 1)} className="h-7 w-7 rounded-lg border border-[#E2E8F0] text-[#334155]">+</button>
                    </span>
                    <span className="w-24 text-right text-[13.5px] font-semibold tabular-nums text-[#0B1C3F]">{money(l.price * l.qty)}</span>
                    <button type="button" aria-label={`Retirer ${l.name}`} onClick={() => setPicked((p0) => { const n = { ...p0 }; delete n[l.id]; return n; })}
                            className="text-[#94A3B8] hover:text-[#B91C1C]"><X size={15} /></button>
                  </li>
                ))}
              </ul>
            )}

            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <div>
                <p className="text-[13.5px] font-semibold text-[#334155]">Montant payé</p>
                <div className="mt-1 flex items-stretch overflow-hidden rounded-xl border border-[#E2E8F0]">
                  <span className="flex w-12 items-center justify-center border-r border-[#E2E8F0] text-[#64748B]"><Euro size={16} /></span>
                  {/* letters never get in; a minus stays on screen and is explained (DecimalInput) */}
                  <DecimalInput value={shownAmount} placeholder="0,00" aria-label="Montant payé"
                                aria-invalid={amountProblem ? 'true' : undefined}
                                onChange={(v) => { setManual(true); setAmountPaid(v); }} onInvalid={setAmountErr}
                                className="w-full px-4 py-3 text-[16px] font-semibold text-[#0B1C3F] outline-none" />
                </div>
                {amountProblem && <p className="mt-1 text-[12.5px] text-[#C0392B]" role="alert">{amountProblem}</p>}
                {discount > 0 && !manual && (
                  <p className="mt-1 text-[12.5px] text-[#0F7A45]">{money(linesTotal)} − {money(discount)} d'offre appliquée.</p>
                )}
                {manual && (
                  <button type="button" onClick={() => { setManual(false); setAmountPaid(''); setAmountErr(null); }}
                          className="mt-1 text-[12.5px] font-semibold text-[#2F6BFF]">Revenir au montant du catalogue</button>
                )}
              </div>

              <div>
                <p className="text-[13.5px] font-semibold text-[#334155]">Carte papier ?</p>
                {card.paper.done ? (
                  <p className="mt-1 rounded-xl bg-[#F8FAFF] px-3 py-2.5 text-[12.5px] text-[#64748B]">{card.paper.message || 'Déjà transférée pour ce client.'}</p>
                ) : card.paper.max === 0 ? (
                  <p className="mt-1 rounded-xl bg-[#F8FAFF] px-3 py-2.5 text-[12.5px] text-[#64748B]">La carte est pleine : aucun tampon à reporter.</p>
                ) : (
                  <div className="mt-1 flex items-center gap-3">
                    <button type="button" role="switch" aria-checked={paperOn} aria-label="Carte papier"
                            onClick={() => { setPaperOn((v) => !v); if (paperOn) setPaperStamps(''); }}
                            className={`h-7 w-12 shrink-0 rounded-full transition ${paperOn ? 'bg-[#2F6BFF]' : 'bg-[#CBD5E1]'}`}>
                      <span className={`block h-6 w-6 rounded-full bg-white transition ${paperOn ? 'translate-x-[22px]' : 'translate-x-[2px]'}`} />
                    </button>
                    {paperOn && (
                      <input value={paperStamps} inputMode="numeric" placeholder={`0 à ${card.paper.max}`}
                             onChange={(e) => setPaperStamps(e.target.value.replace(/\D/g, ''))}
                             className="w-28 rounded-xl border border-[#E2E8F0] px-3 py-2.5 text-[15px] text-[#0B1C3F] outline-none" />
                    )}
                  </div>
                )}
                {paperTooMany && (
                  <p className="mt-1 text-[12.5px] text-[#C0392B]">{card.paper.max} tampons au maximum.</p>
                )}
              </div>
            </div>

            <button type="button" disabled={paperTooMany || !!amountProblem}
                    onClick={() => { setStatus(null); setStep('review'); }}
                    className="mt-5 hidden w-full items-center justify-center gap-2 rounded-xl bg-[#1463FF] py-3.5 text-[15px] font-semibold text-white disabled:opacity-50 sm:inline-flex">
              Suivant <ArrowRight size={17} />
            </button>
          </div>
          )}

          {/* step 2: what is about to be written, and the one offer or reward */}
          {!recorded && step === 'review' && (
          <div className="rounded-2xl border border-[#E6EEFB] bg-white p-5" data-testid="visit-review">
            <p className="mb-3 text-[16px] font-bold text-[#0B1C3F]">Récapitulatif de la visite</p>
            <dl className="grid gap-y-2 text-[13.5px]">
              <div className="flex justify-between gap-3 border-b border-[#F1F5F9] pb-2"><dt className="text-[#64748B]">{words.many.charAt(0).toUpperCase() + words.many.slice(1)}</dt>
                <dd className="text-right text-[#0B1C3F]">{lines.length ? lines.map((l) => `${l.qty} × ${l.name}`).join(', ') : 'Aucun'}</dd></div>
              {paperOn && parseInt(paperStamps || '0', 10) > 0 && (
                <div className="flex justify-between gap-3 border-b border-[#F1F5F9] pb-2"><dt className="text-[#64748B]">Carte papier</dt>
                  <dd className="text-right text-[#0B1C3F]">{parseInt(paperStamps, 10)} tampon{parseInt(paperStamps, 10) > 1 ? 's' : ''} reporté{parseInt(paperStamps, 10) > 1 ? 's' : ''}</dd></div>
              )}
            </dl>

            <p className="mt-5 text-[14px] font-bold text-[#0B1C3F]">Offre / Récompense</p>
            {card.applicables.length > 0 ? (
              <>
                <p className="mb-3 text-[12.5px] text-[#64748B]">Une seule peut être appliquée à cette visite.</p>
                <div className="grid gap-2 md:grid-cols-2">
                  {card.applicables.map((a) => {
                    const on = apply === a.id;
                    const off = a.tone === 'offer';
                    return (
                      <button key={a.id} type="button" onClick={() => setApply(on ? '' : a.id)} aria-pressed={on}
                              className={`flex items-start gap-3 rounded-xl border p-3 text-left transition ${on ? 'border-[#2F6BFF] bg-[#F5F9FF] ring-2 ring-[#2F6BFF]/15' : 'border-[#E6EEFB] bg-white hover:border-[#BFD3FF]'}`}>
                        <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${off ? 'bg-[#E7F7EE] text-[#0F7A45]' : 'bg-[#F7EDFF] text-[#7C3AED]'}`}>
                          <Gift size={16} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-[13.5px] font-semibold text-[#0B1C3F]">{a.title}</span>
                          {a.sub && <span className="block text-[12.5px] text-[#64748B]">{a.sub}</span>}
                          {a.after_visit && <span className="mt-1 inline-block rounded-md bg-[#FFF4DB] px-2 py-0.5 text-[11.5px] font-semibold text-[#92400E]">Débloquée après cette visite</span>}
                        </span>
                        <span className={`mt-1 h-4 w-4 shrink-0 rounded-full border-2 ${on ? 'border-[#2F6BFF] bg-[#2F6BFF]' : 'border-[#CBD5E1]'}`} />
                      </button>
                    );
                  })}
                </div>
              </>
            ) : (
              <p className="mt-1 rounded-xl bg-[#F8FAFF] px-4 py-3 text-[13px] text-[#64748B]">Aucune offre ni récompense disponible pour ce client.</p>
            )}

            <div className="mt-5 flex items-baseline justify-between gap-3 rounded-xl bg-[#F8FAFF] px-4 py-3">
              <span className="text-[14px] font-semibold text-[#334155]">Montant payé</span>
              <span className="text-right">
                <span className="block text-[20px] font-extrabold tabular-nums text-[#0B1C3F]">{money(manual ? parseFloat(amountPaid || '0') || 0 : autoAmount)}</span>
                {discount > 0 && !manual && <span className="block text-[12.5px] text-[#0F7A45]">{money(linesTotal)} − {money(discount)} d'offre appliquée</span>}
              </span>
            </div>

            <div className="mt-5 hidden gap-3 sm:flex">
              <button type="button" onClick={() => { setStatus(null); setStep('items'); }} disabled={loading}
                      className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#E2E8F0] bg-white px-5 py-3.5 text-[15px] font-semibold text-[#334155] disabled:opacity-50">
                <ChevronLeft size={17} /> Retour
              </button>
              <button type="button" disabled={loading} onClick={registerVisit}
                      className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-[#1463FF] py-3.5 text-[15px] font-semibold text-white disabled:opacity-50">
                <Gift size={17} /> {loading ? 'Enregistrement…' : 'Enregistrer la visite'}
              </button>
            </div>
          </div>
          )}
        </>
      )}

      {/* phone: the next step always at the thumb, with what is owed */}
      {phone && card && (
        <div className="fixed inset-x-0 z-30 border-t border-[#E6EEFB] bg-white/95 px-3 py-2.5 backdrop-blur"
             style={{ bottom: 'var(--fc-bottom-nav, 0px)' }} data-testid="phone-action-bar">
          {recorded ? (
            <button type="button" onClick={scanAnother}
                    className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#1463FF] text-[15px] font-semibold text-white">
              <ScanLine size={18} /> Scanner une autre carte
            </button>
          ) : (
            <div className="flex items-center gap-3">
              {step === 'review' && (
                <button type="button" onClick={() => { setStatus(null); setStep('items'); }} disabled={loading} aria-label="Retour"
                        className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-[#E2E8F0] text-[#334155] disabled:opacity-50">
                  <ChevronLeft size={20} />
                </button>
              )}
              <div className="min-w-0">
                <p className="text-[11.5px] text-[#64748B]">Total</p>
                <p className="text-[18px] font-extrabold leading-tight tabular-nums text-[#0B1C3F]">{money(payNow)}</p>
              </div>
              {step === 'items' ? (
                <button type="button" disabled={paperTooMany || !!amountProblem} onClick={() => { setStatus(null); setStep('review'); }}
                        className="ml-auto flex h-12 flex-1 items-center justify-center gap-2 rounded-xl bg-[#1463FF] text-[15px] font-semibold text-white disabled:opacity-50">
                  Suivant <ArrowRight size={18} />
                </button>
              ) : (
                <button type="button" disabled={loading} onClick={registerVisit}
                        className="ml-auto flex h-12 flex-1 items-center justify-center gap-2 rounded-xl bg-[#1463FF] text-[15px] font-semibold text-white disabled:opacity-50">
                  <Gift size={18} /> {loading ? 'Enregistrement…' : 'Enregistrer'}
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* the catalogue, as a drawer */}
      {!(phone && card) && (
      <details open={!phone || undefined} className="group mx-auto max-w-[640px]">
      <summary className="mx-auto mt-4 w-fit cursor-pointer list-none rounded-full bg-[#F1F5F9] px-4 py-2 text-[12.5px] font-semibold text-[#475569] sm:hidden">
        Options de cet appareil
      </summary>
      {canPair && (
        <div className="mx-auto mt-6 flex max-w-[640px] flex-wrap items-center gap-3 rounded-2xl border border-[#E6EEFB] bg-white px-4 py-3">
          <div className="min-w-0 flex-1">
            <p className="text-[13.5px] font-semibold text-[#0B1C3F]">
              {caisse ? 'Cet appareil est la caisse' : 'Faire de cet appareil la caisse'}
            </p>
            <p className="text-[12.5px] text-[#64748B]">
              {caisse
                ? 'Il reste connecté et scanne sans redemander de mot de passe. Vous pouvez le déconnecter dans Paramètres › Sécurité.'
                : 'Il restera connecté pour scanner toute la journée, sans redemander de mot de passe.'}
            </p>
          </div>
          <button type="button" disabled={pairing}
                  onClick={async () => {
                    setPairing(true);
                    setPairErr('');
                    try {
                      if (caisse) { await ownerAPI.unmarkCaisse(); setCaisse(false); }
                      else { await ownerAPI.markCaisse(branchId || undefined); setCaisse(true); }
                    } catch (e) {
                      // silence here would leave the owner thinking it worked
                      setPairErr(e?.response?.data?.detail || "L'appareil n'a pas pu être enregistré.");
                    }
                    setPairing(false);
                  }}
                  className={`rounded-xl px-4 py-2 text-[13px] font-semibold disabled:opacity-50 ${
                    caisse ? 'border border-[#E1E8F5] text-[#475569]' : 'bg-[#1463FF] text-white'}`}>
            {caisse ? 'Ce n\u2019est plus la caisse' : 'Enregistrer cet appareil'}
          </button>
          {pairErr && <p className="w-full text-[12.5px] text-[#E11D48]">{pairErr}</p>}
        </div>
      )}

      {/* Put the scanner on the counter (user, 2026-10-14): installed from
          here, the icon opens straight on this page. The prompt shows itself
          only where it can install — Android and desktop Chrome natively, iOS
          with Safari's own « Sur l'écran d'accueil ». */}
      <div className="mx-auto mt-6 flex max-w-[640px] flex-wrap items-center gap-3 rounded-2xl border border-[#E6EEFB] bg-white px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] font-semibold text-[#0B1C3F]">Garder le scanner sous la main</p>
          <p className="text-[12.5px] text-[#64748B]">
            Ajoutez-le à l’écran d’accueil : une icône, et vous scannez — sans passer par le menu.
          </p>
        </div>
        <InstallPwaPrompt context="till" />
      </div>
      </details>
      )}

      {locked && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#0B1C3F]/60 p-4" role="dialog" aria-modal="true">
          <div className="w-full max-w-[320px] rounded-2xl bg-white p-5 text-center">
            <p className="text-[15px] font-bold text-[#0B1C3F]">Code de la caisse</p>
            <p className="mt-1 text-[12.5px] text-[#64748B]">Une fois saisi, cet appareil scanne pour la journée.</p>
            <input value={code} autoFocus inputMode="numeric"
                   onChange={(e) => { setCode(e.target.value.replace(/\D/g, '').slice(0, 8)); setCodeErr(''); }}
                   className="mt-4 w-full rounded-xl border border-[#E1E8F5] px-3 py-3 text-center text-[20px] tracking-[0.4em]" />
            {codeErr && <p className="mt-2 text-[12.5px] text-[#E11D48]">{codeErr}</p>}
            <button type="button" disabled={code.length < 4}
                    onClick={async () => {
                      try {
                        await ownerAPI.unlockCaisse(code);
                        setLocked(false); setCode(''); setCodeErr('');
                      } catch (e) {
                        setCodeErr(e?.response?.data?.detail || 'Code incorrect.');
                      }
                    }}
                    className="mt-4 w-full rounded-xl bg-[#1463FF] py-3 text-[15px] font-semibold text-white disabled:opacity-50">
              Déverrouiller
            </button>
          </div>
        </div>
      )}

      {panel && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={() => setPanel(false)}>
          <aside role="dialog" aria-modal="true" aria-label={words.picker} onClick={(e) => e.stopPropagation()}
                 className="flex h-full w-[min(420px,100%)] flex-col bg-white shadow-2xl">
            <header className="flex items-start gap-3 border-b border-[#EEF3FB] p-4">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><Package size={18} /></span>
              <div className="min-w-0 flex-1">
                <p className="text-[16px] font-bold text-[#0B1C3F]">{words.picker}</p>
                <p className="text-[12.5px] text-[#64748B]">{words.picker_sub}</p>
              </div>
              <button type="button" aria-label="Fermer" onClick={() => setPanel(false)} className="text-[#94A3B8]"><X size={18} /></button>
            </header>
            <div className="space-y-3 border-b border-[#EEF3FB] p-4">
              <input value={panelQ} onChange={(e) => setPanelQ(e.target.value)} placeholder={words.search}
                     className="w-full rounded-xl border border-[#E2E8F0] px-3 py-2.5 text-[14px] outline-none focus:border-[#2F6BFF]" />
              <div className="flex flex-wrap gap-1.5">
                {cats.map((c) => (
                  <button key={c} type="button" onClick={() => setPanelCat(c)} aria-pressed={panelCat === c}
                          className={`rounded-full px-3 py-1.5 text-[12.5px] font-semibold ${panelCat === c ? 'bg-[#1463FF] text-white' : 'bg-[#F1F5F9] text-[#475569]'}`}>{c}</button>
                ))}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-3">
              {panelItems.length === 0 ? (
                <p className="px-2 py-8 text-center text-[13px] text-[#64748B]">Aucun {words.one} ici.</p>
              ) : panelItems.map((it) => {
                const q = Number(picked[it.id]) || 0;
                return (
                  <div key={it.id} className={`mb-2 flex items-center gap-3 rounded-xl border p-3 ${q > 0 ? 'border-[#2F6BFF] bg-[#F5F9FF]' : 'border-[#EEF3FB]'}`}>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13.5px] font-semibold text-[#0B1C3F]">{it.name}</span>
                      <span className="block text-[13px] text-[#475569]">{money(it.price)}</span>
                    </span>
                    <span className="flex items-center gap-1">
                      <button type="button" aria-label={`Moins ${it.name}`} onClick={() => bump(it.id, -1)} disabled={q === 0}
                              className="h-8 w-8 rounded-lg border border-[#E2E8F0] text-[#334155] disabled:opacity-40">−</button>
                      <span className="w-7 text-center text-[13.5px] font-semibold tabular-nums">{q}</span>
                      <button type="button" aria-label={`Plus ${it.name}`} onClick={() => bump(it.id, 1)}
                              className="h-8 w-8 rounded-lg border border-[#E2E8F0] text-[#334155]">+</button>
                    </span>
                  </div>
                );
              })}
            </div>
            <footer className="border-t border-[#EEF3FB] p-4">
              <button type="button" onClick={() => setPanel(false)}
                      className="w-full rounded-xl bg-[#1463FF] py-3 text-[15px] font-semibold text-white">
                {lines.length === 0 ? 'Fermer' : `Ajouter ${money(panelTotal)}`}
              </button>
            </footer>
          </aside>
        </div>
      )}
    </div>
  );
};

export default ScanPage;
