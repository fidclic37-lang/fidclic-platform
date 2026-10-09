import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { ownerAPI } from '../lib/api';
import { ScanLine, CheckCircle2, AlertCircle, Euro, Camera, Building2, Gift, BellRing, X, Info, Zap, SwitchCamera, Package, ChevronDown, ArrowRight, Stamp, Keyboard, Link2, ImageUp } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
// The dashboard's blue palette — every account (owner, manager, employé)
// works in the same colours.
const C_SCAN = {
  sky: '#2F6BFF', lavender: '#7C3AED', inkDeep: '#0B1C3F', inkMute: '#475569',
  ochre: '#2F6BFF', amber: '#4F7BFF', terracotta: '#7C3AED',
};
import { useBranch } from '../contexts/BranchContext';
import DecimalInput from '../components/DecimalInput';
import CardReaddModal from '../components/CardReaddModal';

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
  const [preview, setPreview] = useState(null);       // { name, stamps, threshold, paper_max, paper_done, paper_message }
  const [previewErr, setPreviewErr] = useState('');
  const [threshold, setThreshold] = useState(10);
  const [barcode, setBarcode] = useState('');
  const [amountPaid, setAmountPaid] = useState('');
  // « -1 » is refused, said and kept on screen (QA F20) — nothing saves meanwhile
  const [amountError, setAmountError] = useState(null);
  // Live points rule from this tenant's card template.
  // Two modes: 'per_visit' (flat, default) or 'per_euro' (amount × rate).
  const [pointsMode, setPointsMode] = useState('per_visit');
  const [pointsPerEuro, setPointsPerEuro] = useState(10);
  const [pointsPerVisit, setPointsPerVisit] = useState(10);
  const [cashback, setCashback] = useState(false);
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
  const branches = _branchesCtx;
  const branchId = _branchIdRaw || '';
  const setBranchId = (id) => _setBranchIdGlobal(id || null);

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
  const streamRef = useRef(null);
  const detectorRef = useRef(null);
  const detectionLoopRef = useRef(null);

  // Initialize BarcodeDetector for 1D formats. We DO NOT rely on it for QR
  // because Chrome on macOS / Windows ships BarcodeDetector without QR
  // support — the wallet card's QR would never decode. We use jsQR (loaded
  // from CDN) for QR codes instead, and BarcodeDetector for 1D as a bonus.
  useEffect(() => {
    if ('BarcodeDetector' in window) {
      try {
        detectorRef.current = new window.BarcodeDetector({
          // every 1D format a FidClic card can carry (iOS 27 adds Codabar and ITF)
          formats: ['code_128', 'ean_13', 'ean_8', 'code_39', 'upca', 'codabar', 'itf', 'pdf417', 'aztec'],
        });
      } catch (error) {
        console.warn('BarcodeDetector not fully supported:', error);
      }
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

  const startCamera = async (face = facing) => {
    try {
      if (streamRef.current) stopCamera();
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: face },
      });

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        streamRef.current = stream;
        setCameraActive(true);
        setStatus(null);
        // « Flash »: only where the camera has a torch (most Android phones)
        try {
          const caps = stream.getVideoTracks()[0]?.getCapabilities?.() || {};
          setTorch({ supported: !!caps.torch, on: false });
        } catch (_e) { setTorch({ supported: false, on: false }); }

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
  const decodeImageFile = async (file) => {
    if (!file) return;
    setStatus({ type: 'info', message: t('scan.image_reading') });
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
          setStatus({ type: 'success', message: t('scan.code_detected_image') });
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
            setStatus({ type: 'success', message: t('scan.code_detected_image') });
            setMode('manual');
            return;
          }
        } catch (_e) { /* ignore */ }
      }
      setStatus({
        type: 'error',
        message: t('scan.image_no_code'),
      });
    } catch (e) {
      console.debug('decodeImageFile error:', e);
      setStatus({
        type: 'error',
        message: t('scan.image_unreadable'),
      });
    }
  };

  const stopCamera = () => {
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
  // the camera opens by itself when the page does on a phone or tablet
  useEffect(() => {
    if (mode === 'camera') startCamera();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Whose card is it? Once a full card id is there (typed or scanned), the
  // till shows the customer, their stamps and the paper stamps it can take.
  useEffect(() => {
    setPreview(null);
    setPreviewErr('');
    const bc = barcodeFrom(barcode);
    if (!/^FT-[A-Z0-9]{8}$/.test(bc)) return undefined;
    let alive = true;
    const t0 = setTimeout(() => {
      ownerAPI.scanPreview(bc)
        .then(({ data }) => { if (alive) setPreview(data); })
        .catch((e) => { if (alive) setPreviewErr(e?.response?.status === 404 ? 'Aucun client trouvé avec ce code.' : ''); });
    }, 300);
    return () => { alive = false; clearTimeout(t0); };
  }, [barcode]);

  const startDetectionLoop = () => {
    // Hidden canvas for jsQR — re-used across frames so we don't allocate per tick.
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d', { willReadFrequently: true });

    const onHit = (raw) => {
      if (!raw) return false;
      const cleaned = barcodeFrom(raw);
      if (!cleaned) return false;
      setBarcode(cleaned);
      setStatus({ type: 'success', message: t('scan.code_detected') });
      stopCamera();
      setMode('manual');
      return true;
    };

    const detect = async () => {
      const video = videoRef.current;
      // Don't check cameraActive — that's a state value captured by closure
      // and may be stale. Instead rely on stopCamera() cancelling the rAF.
      if (!video || !streamRef.current) return;
      const ready = video.readyState >= 2 && video.videoWidth > 0;

      if (ready) {
        // Try jsQR first — handles QR codes on every browser.
        if (window.jsQR) {
          try {
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
            const result = window.jsQR(img.data, img.width, img.height, {
              inversionAttempts: 'attemptBoth',
            });
            if (result?.data && onHit(result.data)) return;
          } catch (e) {
            console.debug('jsQR detect error:', e);
          }
        }
        // Try native BarcodeDetector for 1D formats (Code 128, EAN, etc.).
        if (detectorRef.current) {
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
  // cashier can't accidentally type a different number.
  React.useEffect(() => {
    if (pickedItems.length > 0) {
      setAmountPaid(pickerTotal.toFixed(2));
      setAmountError(null);                // the catalogue's total replaces what was typed
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
  const paperMax = preview ? preview.paper_max : threshold;
  const paperCount = paperStamps === '' ? 0 : parseInt(paperStamps, 10) || 0;
  const paperError = preview?.paper_done && paperCount > 0
    ? 'La carte papier de ce client a déjà été transférée.'
    : paperCount > paperMax
      ? (preview && preview.stamps > 0
        ? `Cette carte a déjà ${preview.stamps} tampon${preview.stamps > 1 ? 's' : ''} : ${paperMax} au maximum.`
        : `${paperMax} tampons au maximum (une carte complète).`)
      : null;
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
        branch_id: branchId || customerData.branch_id || null,
        // Notification subscription status — drives the "encourage enable
        // notifications" prompt staff sees post-scan. Customers without
        // push subscriptions get a QR code they can scan to enable.
        notification_status: customerData.notification_status || 'unknown',
        card_key: customerData.card_key || null,
        paper_stamps: customerData.paper_stamps || 0,
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
        : 'Le montant ne change pas les points dans ce mode (forfait par visite). Le commerçant peut le modifier dans les réglages.';
  const switchMode = (key) => {
    setMode(key);
    if (status?.type === 'error') setStatus(null);      // a camera error does not follow to the form
    if (key === 'manual') stopCamera();
    else if (!cameraActive) startCamera();
  };

  return (
    <div className="sc mx-auto max-w-[860px] space-y-6 pb-10">
      <style>{`@keyframes scanline{0%{top:18%}50%{top:78%}100%{top:18%}}`}</style>
      {/* Hero */}
      <div className="pt-2 text-center">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-[#BFD3FF] bg-[#EEF4FF] px-3.5 py-1 text-[11px] font-bold uppercase tracking-[0.12em] text-[#2F6BFF]">
          <Link2 size={13} /> Enregistrer une visite
        </span>
        <h1 className="mt-4 text-[34px] font-extrabold leading-tight tracking-tight text-[#0B1C3F] sm:text-[40px]">Enregistrer une visite</h1>
        <p className="mx-auto mt-2 max-w-[520px] text-[15.5px] leading-relaxed text-[#64748B]">
          Scannez le code de la carte client ou saisissez-le manuellement pour créditer les points de fidélité.
        </p>
      </div>

      {/* Establishment and « give a card back » — only what the shop needs */}
      {(
        <div className="flex flex-wrap items-center justify-between gap-2">
          {branches.length > 0 ? (
            <label className="inline-flex items-center gap-2 rounded-full border border-[#E2E8F0] bg-white px-3 py-1.5 text-[12.5px] text-[#334155]">
              <Building2 size={14} className="text-[#2F6BFF]" />
              <span className="font-semibold">{t('scan.scanning_at_branch')}</span>
              <select value={branchId} onChange={(e) => setBranchId(e.target.value)}
                      className="max-w-[180px] !border-0 bg-transparent !p-0 text-[12.5px] font-semibold text-[#0B1C3F] !outline-none">
                <option value="">{t('scan.branch_not_tagged')}</option>
                {branches.map((b) => <option key={b.id} value={b.id}>{b.name || b.id}</option>)}
              </select>
            </label>
          ) : <span />}
          <button type="button" onClick={() => setReadd({ find: true })}
                  className="inline-flex items-center gap-1.5 rounded-full border border-[#E2E8F0] bg-white px-3.5 py-1.5 text-[12px] font-semibold text-[#334155] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
            <Gift size={13} /> Rendre sa carte à un client
          </button>
        </div>
      )}

      {/* Mode tabs */}
      <div role="tablist" className="mx-auto grid max-w-[740px] grid-cols-2 gap-1 rounded-full bg-white p-1.5 shadow-[0_6px_20px_-14px_rgba(15,23,42,.35)]">
        {[['camera', 'Scanner avec la caméra', Camera, 'Caméra'], ['manual', 'Saisie manuelle', Keyboard, 'Saisie manuelle']].map(([key, label, Icon, short]) => (
          <button key={key} type="button" role="tab" aria-selected={mode === key} onClick={() => switchMode(key)}
                  className={`inline-flex items-center justify-center gap-2 rounded-full px-3 py-3 text-[14px] font-semibold transition ${
                    mode === key ? 'bg-[#1463FF] text-white shadow-[0_10px_24px_-12px_rgba(20,99,255,.9)]' : 'text-[#0B1C3F] hover:bg-[#F4F7FC]'}`}>
            <Icon size={18} /> <span className="truncate sm:hidden">{short}</span><span className="hidden truncate sm:inline">{label}</span>
          </button>
        ))}
      </div>

      {/* Camera */}
      {mode === 'camera' && (
        <div className="space-y-4">
          <div className="relative overflow-hidden rounded-[28px] bg-[#0B1220] shadow-[0_24px_60px_-30px_rgba(15,23,42,.7)]" style={{ aspectRatio: '16 / 9', minHeight: 300 }}>
            <video ref={videoRef} autoPlay playsInline muted className="absolute inset-0 h-full w-full object-cover" />
            {/* the frame the code goes in */}
            <div aria-hidden="true" className="pointer-events-none absolute left-1/2 top-1/2 h-[62%] w-[min(46%,340px)] -translate-x-1/2 -translate-y-1/2">
              {['left-0 top-0 border-l-4 border-t-4 rounded-tl-2xl', 'right-0 top-0 border-r-4 border-t-4 rounded-tr-2xl',
                'left-0 bottom-0 border-l-4 border-b-4 rounded-bl-2xl', 'right-0 bottom-0 border-r-4 border-b-4 rounded-br-2xl'].map((c) => (
                <span key={c} className={`absolute h-10 w-10 border-[#4F8BFF] [filter:drop-shadow(0_0_6px_rgba(79,139,255,.95))] ${c}`} />
              ))}
              {cameraActive && (
                <span className="absolute left-2 right-2 h-[2px] rounded-full bg-[#7FB0FF] shadow-[0_0_14px_4px_rgba(79,139,255,.65)]"
                      style={{ animation: 'scanline 2.4s ease-in-out infinite' }} />
              )}
            </div>
            {/* Flash and Retourner */}
            <div className="absolute left-4 top-4 flex flex-col items-center gap-1">
              <button type="button" onClick={toggleTorch} disabled={!torch.supported} aria-pressed={torch.on}
                      title={torch.supported ? 'Flash' : 'Flash indisponible sur cette caméra'}
                      className={`flex h-12 w-12 items-center justify-center rounded-full border border-white/40 backdrop-blur transition disabled:opacity-40 ${torch.on ? 'bg-white text-[#0B1C3F]' : 'bg-black/35 text-white'}`}>
                <Zap size={20} fill={torch.on ? 'currentColor' : 'none'} />
              </button>
              <span className="text-[11.5px] font-medium text-white drop-shadow">Flash</span>
            </div>
            <div className="absolute right-4 top-4 flex flex-col items-center gap-1">
              <button type="button" onClick={flipCamera} title="Changer de caméra"
                      className="flex h-12 w-12 items-center justify-center rounded-full border border-white/40 bg-black/35 text-white backdrop-blur">
                <SwitchCamera size={20} />
              </button>
              <span className="text-[11.5px] font-medium text-white drop-shadow">Retourner</span>
            </div>
            {/* hint, or the way to switch the camera on */}
            {cameraActive ? (
              <div className="absolute bottom-4 left-1/2 flex w-[min(92%,480px)] -translate-x-1/2 items-center gap-3 rounded-2xl border border-white/10 bg-[#0B1220]/80 px-4 py-3 backdrop-blur">
                <ScanLine size={26} className="shrink-0 text-white" />
                <div className="min-w-0">
                  <p className="text-[14px] font-semibold text-white">Placez le code de la carte client dans le cadre</p>
                  <p className="text-[12px] text-white/75">Le scan se fait automatiquement</p>
                </div>
              </div>
            ) : (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
                <Camera size={34} className="text-white/80" />
                <button type="button" onClick={() => startCamera()}
                        className="rounded-full bg-[#1463FF] px-5 py-2.5 text-[14px] font-semibold text-white">Activer la caméra</button>
              </div>
            )}
          </div>
          {/* Camera refused or missing: a photo of the code works everywhere */}
          <label className="mx-auto flex w-fit cursor-pointer items-center gap-2 text-[13px] font-semibold text-[#2F6BFF]">
            <ImageUp size={16} /> Caméra indisponible ? Importer une photo du code
            <input type="file" accept="image/*" capture="environment" className="hidden"
                   onChange={(e) => { const f = e.target.files?.[0]; if (f) decodeImageFile(f); e.target.value = ''; }} />
          </label>
          <p className="mx-auto flex max-w-[600px] items-start gap-3 rounded-2xl bg-[#EEF4FF] px-5 py-3.5 text-[14px] leading-relaxed text-[#1D4ED8]">
            <Info size={20} className="mt-0.5 shrink-0" />
            <span>Les points sont ajoutés automatiquement selon les règles de votre carte. La carte du client (Apple Wallet comprise) se met à jour toute seule.</span>
          </p>
        </div>
      )}

      {/* Typed form — also where a scanned code lands, to add the amount and products */}
      {mode === 'manual' && (
        <form onSubmit={handleScan} noValidate
              className="mx-auto max-w-[800px] space-y-5 rounded-[24px] bg-white p-5 shadow-[0_10px_34px_-24px_rgba(15,23,42,.45)] sm:p-6">
          <div>
            <label htmlFor="scan-card-id" className="mb-2 block text-[15px] font-bold text-[#0B1C3F]">ID de la carte client <span className="text-[#E11D48]">*</span></label>
            <div className={inputBox}>
              <span className={iconCell}><ScanLine size={20} /></span>
              <input id="scan-card-id" type="text" value={barcode} autoComplete="off" autoCapitalize="characters"
                     onChange={(e) => setBarcode(barcodeFrom(e.target.value) || e.target.value.toUpperCase())}
                     placeholder="Saisissez l’ID de la carte client (ex : FT-A1B2C3D4)"
                     className={`${fieldCls} font-mono tracking-wider`} disabled={loading} />
            </div>
            {preview && (
              <p className="mt-2 flex items-center gap-1.5 text-[13px] text-[#0F8B58]">
                <CheckCircle2 size={15} /> <b>{preview.name || 'Client'}</b> · {preview.stamps}/{preview.threshold} tampons sur sa carte
              </p>
            )}
            {previewErr && <p role="alert" className="mt-2 text-[13px] font-semibold text-[#DC2626]">{previewErr}</p>}
          </div>

          <div>
            <label htmlFor="scan-amount" className="mb-2 block text-[15px] font-bold text-[#0B1C3F]">Montant payé (€)</label>
            <div className={`${inputBox} ${amountError ? '!border-[#DC2626]' : ''} ${pickedItems.length > 0 ? 'bg-[#F6F9FF]' : ''}`}>
              <span className={iconCell}><Euro size={20} /></span>
              {/* « 1,25 » is 1,25 € — never 125 (QA F12) */}
              <DecimalInput id="scan-amount" value={amountPaid} onChange={setAmountPaid} onInvalid={setAmountError}
                            aria-invalid={amountError ? 'true' : undefined} placeholder="0,00"
                            className={`${fieldCls} font-semibold`} disabled={loading || pickedItems.length > 0} readOnly={pickedItems.length > 0} />
            </div>
            {amountError
              ? <p role="alert" className="mt-2 text-[12.5px] font-semibold text-[#DC2626]">{amountError}</p>
              : <p className="mt-2 text-[12.5px] text-[#64748B]">{amountHint}</p>}
            {!cashback && pointsMode === 'per_euro' && amountPaid && parseFloat(amountPaid) > 0 && (
              <p className="mt-1 text-[12px] font-semibold text-[#0F8B58]">✓ {t('scan.points_will_credit', { count: computeAutoPoints(amountPaid) })}</p>
            )}
          </div>

          {catalog.length > 0 && (
            <div>
              <div className="mb-2 flex items-center justify-between">
                <span className="text-[15px] font-bold text-[#0B1C3F]">Catalogue produits <span className="text-[#E11D48]">*</span></span>
                {pickedItems.length > 0 && (
                  <button type="button" onClick={clearPicker} className="text-[12.5px] font-medium text-[#2F6BFF] underline">{t('scan.catalog_clear')}</button>
                )}
              </div>
              <div className={`${inputBox} flex-col`}>
                <button type="button" onClick={() => setPickerOpen((v) => !v)} aria-expanded={pickerOpen}
                        className="flex w-full items-stretch text-left">
                  <span className={iconCell}><Package size={20} /></span>
                  <span className={`flex min-w-0 flex-1 items-center px-4 py-3.5 text-[15px] ${pickedItems.length ? 'text-[#0B1C3F]' : 'text-[#94A3B8]'}`}>
                    <span className="truncate">
                      {pickedItems.length
                        ? `${pickedItems.map(({ item, qty }) => `${qty} × ${item.name}`).join(', ')} — ${pickerTotal.toFixed(2).replace('.', ',')} €`
                        : 'Sélectionner un produit…'}
                    </span>
                  </span>
                  <span className="flex items-center pr-4 text-[#0B1C3F]"><ChevronDown size={18} className={pickerOpen ? 'rotate-180' : ''} /></span>
                </button>
                {pickerOpen && (
                  <div className="max-h-72 overflow-y-auto border-t border-[#E2E8F0]">
                    {catalog.map((it) => {
                      const qty = Number(pickerQty[it.id]) || 0;
                      return (
                        <div key={it.id} className="flex items-center gap-3 border-b border-[#F1F5F9] px-4 py-2.5 last:border-b-0">
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-[14px] text-[#0B1C3F]">{it.name}</div>
                            {it.category && <div className="text-[11px] uppercase tracking-wider text-[#64748B]">{it.category}</div>}
                          </div>
                          <div className="w-16 text-right font-mono text-[13.5px] text-[#475569]">{Number(it.price).toFixed(2).replace('.', ',')} €</div>
                          <div className="flex items-center gap-1">
                            <button type="button" onClick={() => bumpQty(it.id, -1)} aria-label={t('scan.qty_minus')}
                                    className="h-9 w-9 rounded-lg border border-[#E2E8F0] font-bold text-[#2F6BFF]">−</button>
                            <span className="w-7 text-center text-[14px] font-bold tabular-nums">{qty}</span>
                            <button type="button" onClick={() => bumpQty(it.id, +1)} aria-label={t('scan.qty_plus')}
                                    className="h-9 w-9 rounded-lg border border-[#E2E8F0] font-bold text-[#10A36B]">+</button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Stamps of a paper loyalty card, moved once onto the digital card */}
          <div>
            <label htmlFor="scan-paper" className="mb-2 block text-[15px] font-bold text-[#0B1C3F]">
              Tampons de la carte papier <span className="font-normal text-[#64748B]">(optionnel)</span>
            </label>
            <div className={`${inputBox} ${paperError ? '!border-[#DC2626]' : ''} ${preview?.paper_done ? 'bg-[#F8FAFC]' : ''}`}>
              <span className={iconCell}><Stamp size={20} /></span>
              <input id="scan-paper" type="text" inputMode="numeric" maxLength={2} data-keep-zeros
                     value={paperStamps} disabled={loading || !!preview?.paper_done}
                     onChange={(e) => setPaperStamps(e.target.value.replace(/\D/g, '').slice(0, 2))}
                     placeholder={preview?.paper_done ? 'Déjà transférée' : `0 à ${paperMax}`}
                     aria-invalid={paperError ? 'true' : undefined} aria-describedby="scan-paper-hint"
                     className={fieldCls} />
              <span className="flex items-center pr-4 text-[13px] text-[#64748B]">/ {preview?.threshold || threshold}</span>
            </div>
            {paperError ? (
              <p id="scan-paper-hint" role="alert" className="mt-2 text-[12.5px] font-semibold text-[#DC2626]">{paperError}</p>
            ) : preview?.paper_done ? (
              <p id="scan-paper-hint" className="mt-2 text-[12.5px] text-[#64748B]">{preview.paper_message}</p>
            ) : (
              <p id="scan-paper-hint" className="mt-2 text-[12.5px] text-[#64748B]">
                Le client a une carte de fidélité papier ? Saisissez ses tampons : ils s’ajoutent à sa carte digitale, en plus de la visite d’aujourd’hui. Une seule fois par client.
              </p>
            )}
          </div>

          {catalogMissing && barcode.trim() && (
            <p className="text-[12.5px] font-semibold text-[#B45309]">Choisissez au moins un produit du catalogue.</p>
          )}
          <button type="submit" disabled={loading || !barcode.trim() || !!amountError || !!paperError || catalogMissing}
                  className="flex h-14 w-full items-center justify-center gap-3 rounded-2xl bg-[#1463FF] px-4 text-[16px] font-semibold text-white shadow-[0_14px_30px_-14px_rgba(20,99,255,.8)] transition hover:bg-[#0F54E0] disabled:opacity-50">
            <Gift size={20} /> {loading ? t('scan.submitting') : 'Enregistrer la visite et ajouter les points'} {!loading && <ArrowRight size={20} />}
          </button>
        </form>
      )}

      {status && (
          <div role={status.type === 'error' ? 'alert' : 'status'}
               className={`mx-auto max-w-[800px] rounded-[24px] border animation-fadeIn shadow-[0_10px_34px_-24px_rgba(15,23,42,.45)] ${status.type === 'success' ? 'border-[#DCE7FF] bg-white p-6 sm:p-8' : status.type === 'error' ? 'border-red-200 bg-red-50 p-6' : 'border-[#E6EEFB] bg-[#F4F7FC] p-6'}`}>
            {status.type === 'success' && scanResult ? (
              <>
                <div className="flex items-center justify-center gap-3 mb-6">
                  <CheckCircle2 className="w-10 h-10 shrink-0 text-[#0F8B58]" />
                  <h3 className="text-2xl font-bold font-['Inter'] text-[#0B1C3F]">
                    {t('scan.visit_recorded_for', { name: scanResult.customer_name || t('scan.customer_fallback') })}
                  </h3>
                </div>

                {/* Points & Stamps Summary */}
                <div className="grid grid-cols-2 gap-4 mb-6 text-center">
                  <div className="bg-white p-4 rounded-lg">
                    <p className="text-3xl font-bold text-[#2F6BFF]">+{scanResult.points_earned || 0}</p>
                    <p className="text-sm text-[#475569]">{t('scan.label_points')}</p>
                  </div>
                  <div className="bg-white p-4 rounded-lg">
                    <p className="text-3xl font-bold text-[#0F8B58]">+{1 + (scanResult.paper_stamps || 0)}</p>
                    <p className="text-sm text-[#475569]">
                      {scanResult.paper_stamps > 0
                        ? `tampons, dont ${scanResult.paper_stamps} de la carte papier`
                        : t('scan.label_stamp')}
                    </p>
                  </div>
                </div>

                {/* Progress Bar */}
                {scanResult.stamps_current !== undefined && scanResult.stamps_required !== undefined && (
                  <div className="mb-6">
                    <div className="flex justify-between items-center mb-2">
                      <p className="text-sm font-semibold text-[#0B1C3F]">{t('scan.progress_to_reward')}</p>
                      <p className="text-sm font-bold text-[#2F6BFF]">{scanResult.stamps_current} / {scanResult.stamps_required}</p>
                    </div>
                    <div className="w-full h-3 bg-[#E6EEFB] rounded-full overflow-hidden">
                      <div
                        className="h-full bg-[#2F6BFF] rounded-full transition-all"
                        style={{ width: `${Math.min((scanResult.stamps_current / scanResult.stamps_required) * 100, 100)}%` }}
                      />
                    </div>
                    <p className="text-xs text-[#64748B] mt-2">
                      {t('scan.stamps_until_reward', { count: scanResult.stamps_required - scanResult.stamps_current })}
                    </p>
                  </div>
                )}

                {/* Rewards to hand over: the card just completed (10/10) and
                    any earlier full card not yet claimed — the meter restarts
                    on the next visit, the reward stays valid (user, 2026-10-09). */}
                {scanResult.card_state && scanResult.card_state.state !== 'active' && (
                  <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[#FCA5A5] bg-[#FEF2F2] p-4">
                    <p className="text-sm text-[#7F1D1D]">
                      <strong>{scanResult.card_state.state === 'deleted' ? 'Carte supprimée' : 'Carte retirée d’Apple Wallet'}.</strong>{' '}
                      {scanResult.customer_name || t('scan.this_customer')} n’a plus sa carte sur son téléphone.
                    </p>
                    <button type="button" onClick={() => setReadd({ customerId: scanResult.customer_id })}
                            className="rounded-lg bg-white px-3 py-2 text-sm font-bold text-[#B91C1C] border border-[#FCA5A5] hover:bg-[#FFF5F5]">
                      Lui rendre sa carte
                    </button>
                  </div>
                )}

                {(scanResult.reward_unlocked || scanResult.rewards_pending > 0 || redeemDone) && (() => {
                  const toGive = (scanResult.reward_unlocked ? 1 : 0) + (scanResult.rewards_pending || 0);
                  return (
                  <div className="bg-[#0F8B58] text-white p-6 rounded-lg mb-6">
                    <div className="text-center mb-4">
                      <p className="text-2xl font-bold mb-1">
                        {scanResult.reward_unlocked ? t('scan.reward_unlocked')
                          : toGive > 1 ? `🎁 ${toGive} récompenses en attente` : '🎁 Récompense en attente'}
                      </p>
                      <p className="text-sm opacity-90">
                        {scanResult.reward_unlocked
                          ? t('scan.reward_subtitle', { name: scanResult.customer_name || t('scan.this_customer') })
                          : toGive > 0
                            ? `${scanResult.customer_name || t('scan.this_customer')} a complété une carte sans récupérer sa récompense. Elle reste valable ; la nouvelle carte continue (${scanResult.stamps_current}/${scanResult.stamps_required}).`
                            : ''}
                      </p>
                    </div>
                    {redeemDone && (
                      <div className="bg-white/10 rounded-lg p-3 text-center mb-3">
                        <p className="font-bold flex items-center justify-center gap-2">
                          <CheckCircle2 size={18} /> Récompense remise et enregistrée.
                        </p>
                      </div>
                    )}
                    {toGive > 0 && (
                      <button
                        type="button"
                        onClick={async () => {
                          try {
                            setRedeemLoading(true);
                            await ownerAPI.redeemReward({
                              customer_id: scanResult.customer_id,
                              barcode_id: scanResult.barcode_id,
                              reward_name: 'Loyalty reward',
                              branch_id: scanResult.branch_id || undefined,
                            });
                            // the server hands over the oldest waiting card first
                            setScanResult((r) => (r.rewards_pending > 0
                              ? { ...r, rewards_pending: r.rewards_pending - 1 }
                              : { ...r, reward_unlocked: false }));
                            setRedeemDone(true);
                          } catch (e) {
                            alert('Échec : ' + (e?.response?.data?.detail || e.message));
                          } finally {
                            setRedeemLoading(false);
                          }
                        }}
                        disabled={redeemLoading}
                        className="w-full py-3 rounded-lg bg-white text-[#0F8B58] font-bold hover:bg-[#F4F7FC] transition flex items-center justify-center gap-2 disabled:opacity-60"
                      >
                        <Gift size={18} />
                        {redeemLoading ? t('scan.redeeming') : t('scan.give_reward')}
                      </button>
                    )}
                    {toGive > 0 && (
                      <p className="text-xs text-white/80 text-center mt-3">
                        {scanResult.rewards_pending > 0
                          ? 'Enregistre la remise. La carte en cours garde ses tampons.'
                          : t('scan.redeem_hint')}
                      </p>
                    )}
                  </div>
                  );
                })()}

                {/* Tier Upgrade Celebration — fires when scan_visit returns tier_upgraded:true */}
                {scanResult.tier_upgraded && scanResult.tier && (
                  <div
                    className="relative p-5 rounded-2xl mb-6 text-center overflow-hidden"
                    style={{
                      background: `linear-gradient(135deg, ${C_SCAN.ochre} 0%, ${C_SCAN.amber} 60%, ${C_SCAN.terracotta} 100%)`,
                      color: 'white',
                      boxShadow: '0 8px 24px rgba(212,165,116,0.35)',
                    }}
                  >
                    <div aria-hidden="true" className="absolute -top-10 -right-10 w-32 h-32 rounded-full blur-2xl opacity-50"
                         style={{ background: 'rgba(255,255,255,0.4)' }} />
                    <p className="relative text-2xl font-['Inter'] font-bold leading-tight">
                      {t('scan.tier_upgraded', { name: scanResult.customer_name?.split(' ')[0] || '', tier: String(scanResult.tier).toUpperCase() })}
                    </p>
                    <p className="relative text-sm mt-1 text-white/85">
                      {t('scan.tier_subtitle', { previous: scanResult.previous_tier ? String(scanResult.previous_tier).toUpperCase() : t('scan.previous_tier_fallback') })}
                    </p>
                  </div>
                )}

                {/* ─── NOTIFICATION ENABLE PROMPT — Strategy 3 ─────────────
                    When the just-scanned customer doesn't have an active
                    push subscription, show staff a friendly prompt + a QR
                    code the customer can scan to enable notifications on
                    the spot. Highest-conversion recovery path (70-85%). */}
                {scanResult.notification_status === 'not_subscribed' && (
                  <NotificationEnablePrompt
                    customerName={scanResult.customer_name}
                    barcodeId={scanResult.barcode_id}
                    cardKey={scanResult.card_key}
                  />
                )}

                <button
                  onClick={() => {
                    setScanResult(null);
                    setStatus(null);
                    setRedeemDone(false);
                    setRedeemLoading(false);
                  }}
                  className="w-full py-4 rounded-lg bg-[#2F6BFF] text-white font-bold hover:bg-[#2559DB] transition"
                >
                  {t('scan.scan_next')}
                </button>
              </>
            ) : status.type === 'error' ? (
              <>
                <AlertCircle className="w-12 h-12 text-red-500 mb-4" />
                <p className="text-[#475569] font-medium">{status.message}</p>
              </>
            ) : (
              <p className="text-[#475569] font-medium">{status.message}</p>
            )}
          </div>
      )}
      {readd && (
        <CardReaddModal customerId={readd.customerId || null} findByPhone={!!readd.find}
                        onClose={() => setReadd(null)} />
      )}
    </div>
  );
};

export default ScanPage;
