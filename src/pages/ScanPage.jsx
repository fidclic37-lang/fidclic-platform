import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { ownerAPI } from '../lib/api';
import { ScanLine, CheckCircle2, AlertCircle, Euro, Camera, Building2, Gift, BellRing, X } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
// The dashboard's blue palette — every account (owner, manager, employé)
// works in the same colours.
const C_SCAN = {
  sky: '#2F6BFF', lavender: '#7C3AED', inkDeep: '#0B1C3F', inkMute: '#475569',
  ochre: '#2F6BFF', amber: '#4F7BFF', terracotta: '#7C3AED',
};
import { useBranch } from '../contexts/BranchContext';

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

function NotificationEnablePrompt({ customerName, barcodeId }) {
  const [showQR, setShowQR] = useState(false);
  const firstName = (customerName || '').split(' ')[0] || 'votre client';
  // Public URL that opens the wallet card with the notification prompt
  // auto-trigger. MyWalletCardPage reads ?notify=1 and shows the prompt
  // banner the moment the page loads.
  const cardUrl = `${window.location.origin}/card/${(barcodeId || '').toUpperCase()}?notify=1`;

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
  const [mode, setMode] = useState('manual'); // 'manual' or 'camera'
  const [barcode, setBarcode] = useState('');
  const [amountPaid, setAmountPaid] = useState('');
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
  const [pickerOpen, setPickerOpen] = useState(true);
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

  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
      });

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        streamRef.current = stream;
        setCameraActive(true);
        setStatus(null);

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

  const handleAmountPaidChange = (e) => {
    const value = e.target.value;
    setAmountPaid(value);

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

  const handleScan = async (e) => {
    e.preventDefault();
    if (!barcode.trim()) return;

    const parsedAmount = amountPaid.trim() === '' ? 0.0 : parseFloat(amountPaid);
    if (isNaN(parsedAmount) || parsedAmount < 0) {
        setStatus({ type: 'error', message: t('scan.error_invalid_amount') });
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

      setScanResult({
        customer_id: customerData.id,
        barcode_id: customerData.barcode_id,
        customer_name: customerData.name,
        points_earned: pointsEarned,
        stamps_current: stampsCurrent,
        stamps_required: stampsRequired,
        reward_unlocked: canRedeem,
        // Backend now returns these so the cashier sees tier-up celebrations.
        tier: customerData.tier || null,
        previous_tier: customerData.previous_tier || null,
        tier_upgraded: !!customerData.tier_upgraded,
        branch_id: branchId || customerData.branch_id || null,
        // Notification subscription status — drives the "encourage enable
        // notifications" prompt staff sees post-scan. Customers without
        // push subscriptions get a QR code they can scan to enable.
        notification_status: customerData.notification_status || 'unknown',
      });
      setStatus({ type: 'success', message: t('scan.success') });
      setBarcode('');
      setAmountPaid('');
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

  return (
    <div className="sc space-y-6 max-w-2xl mx-auto">
      {/* Hero — single focused action surface for staff */}
      <div className="relative text-center pt-4 pb-2">
        <div
          aria-hidden="true"
          className="absolute -top-4 left-1/2 -translate-x-1/2 w-72 h-72 rounded-full blur-3xl opacity-30 pointer-events-none"
          style={{ background: `radial-gradient(circle, ${C_SCAN.sky} 0%, transparent 70%)` }}
        />
        <div
          className="relative inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-[0.2em] mb-4"
          style={{
            background: `linear-gradient(135deg, ${C_SCAN.sky}1A, ${C_SCAN.lavender}1A)`,
            color: C_SCAN.sky,
            border: `1px solid ${C_SCAN.sky}33`,
          }}
        >
          <ScanLine size={12} /> {t('scan.staff_workspace')}
        </div>
        <h1
          className="relative font-['Inter'] font-bold leading-[1.1]"
          style={{ color: C_SCAN.inkDeep, fontSize: 44 }}
        >
          {t('scan.hero_title')}
        </h1>
        <p className="relative mt-3 text-base max-w-md mx-auto" style={{ color: C_SCAN.inkMute }}>
          {t('scan.hero_subtitle')}
        </p>

        {/* Tenant identity banner — gives the staff a clear "you are at X" so
            they immediately notice if they're logged into the wrong account. */}
        {tenantInfo && (
          <div
            className="relative mx-auto mt-4 inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs"
            style={{ background: 'color-mix(in srgb, #2F6BFF 12%, #FFFFFF)', border: '1px solid color-mix(in srgb, #2F6BFF 33%, transparent)', color: '#1D4ED8' }}
          >
            <Building2 size={12} />
            {t('scan.you_are_at')} <b>{tenantInfo.name || t('scan.no_business_name')}</b>
            <span className="font-mono opacity-70">·  /join/{tenantInfo.slug}</span>
          </div>
        )}

        {/* Build fingerprint — verifies which JS bundle is running so we can
            tell if the page is stale-cached. If you see "build 2026-05-07b"
            on screen, the latest scan-error fix is live. */}
        <div className="text-[10px] mt-2 opacity-50" style={{ color: '#64748B' }}>
          build 2026-05-07d · jsQR camera
        </div>
      </div>

      {branches.length > 0 && (
        <div
          className="w-full rounded-2xl p-4 flex items-center gap-3"
          style={{ background: '#FFFFFF', border: `1px solid ${C_SCAN.hairline}`, boxShadow: '0 1px 2px rgba(28,25,23,0.04)' }}
        >
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: `${C_SCAN.sky}1A`, color: C_SCAN.sky, border: `1px solid ${C_SCAN.sky}33` }}
          >
            <Building2 size={18} />
          </div>
          <div className="flex-1 min-w-0">
            <label className="block text-[10px] font-bold uppercase tracking-[0.18em]" style={{ color: C_SCAN.inkMute }}>
              {t('scan.scanning_at_branch')}
            </label>
            <select
              value={branchId}
              onChange={(e) => setBranchId(e.target.value)}
              className="w-full mt-1 px-2 py-1 text-sm rounded-lg outline-none"
              style={{ border: `1px solid ${C_SCAN.hairline}`, background: '#FFFFFF' }}
            >
              <option value="">{t('scan.branch_not_tagged')}</option>
              {branches.map((b) => (
                <option key={b.id} value={b.id}>{b.name || b.id}</option>
              ))}
            </select>
          </div>
        </div>
      )}

      {/* Mode tabs — pill switcher */}
      <div
        className="w-full p-1.5 rounded-full flex"
        style={{ background: '#FFFFFF', border: `1px solid ${C_SCAN.hairline}` }}
      >
        {[
          { key: 'manual', label: t('scan.mode_manual'), icon: ScanLine },
          { key: 'camera', label: t('scan.mode_camera'), icon: Camera },
        ].map((tab) => {
          const isActive = mode === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => {
                setMode(tab.key);
                if (tab.key === 'manual') stopCamera();
                else if (!cameraActive) startCamera();
              }}
              className="flex-1 inline-flex items-center justify-center gap-2 py-2.5 px-4 rounded-full text-xs font-bold uppercase tracking-wider transition-all"
              style={{
                background: isActive ? `linear-gradient(135deg, ${C_SCAN.sky}, ${C_SCAN.lavender})` : 'transparent',
                color: isActive ? 'white' : C_SCAN.inkMute,
                boxShadow: isActive ? '0 4px 14px rgba(74,144,226,0.25)' : 'none',
              }}
            >
              <tab.icon className="w-4 h-4" />
              {tab.label}
            </button>
          );
        })}
      </div>

      <div
        className="bg-white w-full p-8 md:p-10 rounded-3xl shadow-md border relative overflow-hidden"
        style={{ borderColor: C_SCAN.hairline }}
      >
        {/* Decorative gradient orbs */}
        <div
          aria-hidden="true"
          className="absolute -top-24 -right-24 w-56 h-56 rounded-full blur-3xl opacity-25 pointer-events-none"
          style={{ background: C_SCAN.sky }}
        />
        <div
          aria-hidden="true"
          className="absolute -bottom-24 -left-24 w-56 h-56 rounded-full blur-3xl opacity-15 pointer-events-none"
          style={{ background: C_SCAN.lavender }}
        />

        {/* Camera Mode */}
        {mode === 'camera' && (
          <div className="relative z-10 space-y-4">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              className="w-full rounded-xl border-2 border-[#E6EEFB] bg-[#0B1C3F]"
              style={{ maxHeight: '400px', objectFit: 'cover' }}
            />

            {/* Inline amount field — fill BEFORE scanning so we capture the visit value */}
            <div className="rounded-xl border-2 p-4 space-y-3"
                 style={{ borderColor: '#E3A86955', background: 'linear-gradient(135deg, #EAF1FF 0%, #FFFFFF 100%)' }}>
              <div className="flex items-start gap-2">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                     style={{ background: '#E3A869', color: 'white' }}>
                  <Euro size={16} />
                </div>
                <div className="flex-1">
                  <p className="text-xs font-bold uppercase tracking-widest" style={{ color: '#1D4ED8' }}>
                    {t('scan.amount_in_advance')}
                  </p>
                  <p className="text-[10px] mt-0.5" style={{ color: '#475569' }}>
                    {t('scan.amount_in_advance_hint')}
                  </p>
                </div>
              </div>
              <div className="relative">
                <Euro className="w-5 h-5 absolute left-4 top-1/2 -translate-y-1/2 text-[#94A3B8] pointer-events-none" />
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  inputMode="decimal"
                  value={amountPaid}
                  onChange={handleAmountPaidChange}
                  placeholder="0,00"
                  className="w-full pl-14 pr-4 py-3 rounded-lg border-2 outline-none text-lg font-bold font-['Inter'] transition-colors"
                  style={{ borderColor: '#E6EEFB', background: '#FFFFFF' }}
                  onFocus={(e) => (e.target.style.borderColor = '#2F6BFF')}
                  onBlur={(e) => (e.target.style.borderColor = '#E6EEFB')}
                />
              </div>
              {!cashback && amountPaid && parseFloat(amountPaid) > 0 && (
                <p className="text-[11px] font-semibold" style={{ color: '#0F8B58' }}>
                  ✓ {t('scan.points_will_credit', { count: computeAutoPoints(amountPaid) })}
                </p>
              )}
            </div>

            {cameraActive && (
              <button
                onClick={stopCamera}
                className="w-full py-3 rounded-xl text-white font-bold bg-[#2F6BFF] hover:bg-[#2559DB] transition-all"
              >
                {t('scan.stop_camera')}
              </button>
            )}

            {/* Photo upload fallback — works on EVERY browser. On mobile,
                capture="environment" pops the rear camera straight from the
                file picker, even on browsers that block getUserMedia (old
                Android Chrome, Firefox without permission). On desktop, the
                staff can pick any photo of the customer's QR. This is the
                safety net that means scanning always works. */}
            <div className="rounded-xl border-2 border-dashed p-3"
                 style={{ borderColor: '#E6EEFB', background: '#FFFFFF' }}>
              <p className="text-[11px] font-semibold mb-2 text-[#475569] uppercase tracking-wider">
                {t('scan.camera_blocked')}
              </p>
              <label className="flex items-center justify-center gap-2 w-full py-2.5 rounded-lg cursor-pointer text-sm font-semibold border-2 transition-colors"
                     style={{ borderColor: '#4A90E2', color: '#4A90E2', background: '#FFFFFF' }}>
                <Camera size={16} />
                {t('scan.import_photo')}
                <input
                  type="file"
                  accept="image/*"
                  capture="environment"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) decodeImageFile(f);
                    e.target.value = ''; // allow re-picking same file
                  }}
                />
              </label>
              <p className="text-[10px] text-[#64748B] mt-2 text-center">
                {t('scan.import_photo_compat')}
              </p>
            </div>
          </div>
        )}

        {/* Manual Entry Form */}
        {mode === 'manual' && (
          <form onSubmit={handleScan} className="space-y-6 relative z-10">
            <div>
              <label className="block text-sm font-bold text-[#0B1C3F] mb-2 uppercase tracking-wide">{t('scan.barcode_label')}</label>
              <div className="relative">
                {/* 20px icon (w-5) at left-4 (16px) → icon occupies 16-36px.
                    pl-14 (56px) leaves a clean ~20px gap before the
                    placeholder text begins. pointer-events-none so the
                    icon doesn't eat clicks on the first few pixels. */}
                <ScanLine className="w-5 h-5 absolute left-4 top-1/2 -translate-y-1/2 text-[#94A3B8] pointer-events-none" />
                <input
                  type="text"
                  value={barcode}
                  onChange={e => setBarcode(barcodeFrom(e.target.value) || e.target.value.toUpperCase())}
                  placeholder={t('scan.barcode_placeholder')}
                  className="w-full pl-14 pr-4 py-4 rounded-xl border-2 border-[#E6EEFB] focus:border-[#2F6BFF] focus:ring-0 outline-none text-lg font-mono tracking-widest transition-colors uppercase"
                  disabled={loading}
                />
              </div>
              <p className="text-xs text-[#475569] mt-2">{t('scan.barcode_hint')}</p>
            </div>

            {/* ──────────────────────────────────────────────────────────
                CATALOG ITEM PICKER — only renders when the owner has
                added items in Settings → Catalogue. Cashier taps items
                with +/- to build the basket; the total auto-fills the
                Amount Paid field below. The server is the source of
                truth for prices, so what the cashier sees here is what
                gets stored.
                ────────────────────────────────────────────────────── */}
            {catalog.length > 0 && (
              <div>
                <label className="flex items-center justify-between text-sm font-bold text-[#0B1C3F] mb-2 uppercase tracking-wide">
                  <span>{t('scan.catalog_label')}</span>
                  {pickedItems.length > 0 && (
                    <button
                      type="button"
                      onClick={clearPicker}
                      className="text-xs font-normal normal-case tracking-normal text-[#2F6BFF] underline"
                    >
                      {t('scan.catalog_clear')}
                    </button>
                  )}
                </label>
                <div
                  className="rounded-xl border-2 border-[#E6EEFB]"
                  style={{ background: '#FFFFFF' }}
                >
                  <button
                    type="button"
                    onClick={() => setPickerOpen((v) => !v)}
                    className="w-full flex items-center justify-between px-4 py-3 text-left"
                    style={{ font: 'inherit', background: 'transparent', border: 'none', cursor: 'pointer' }}
                  >
                    <span className="text-sm text-[#0B1C3F]">
                      {pickedItems.length === 0
                        ? t('scan.catalog_no_selection_summary', { count: catalog.length })
                        : t('scan.catalog_total_selected', { count: pickedItems.reduce((s, r) => s + r.qty, 0), total: pickerTotal.toFixed(2) })}
                    </span>
                    <span className="text-xs text-[#64748B]">{pickerOpen ? t('scan.catalog_close') : t('scan.catalog_open')}</span>
                  </button>
                  {pickerOpen && (
                    <div className="border-t border-[#E6EEFB] max-h-80 overflow-y-auto">
                      {catalog.map((it) => {
                        const qty = Number(pickerQty[it.id]) || 0;
                        return (
                          <div
                            key={it.id}
                            className="flex items-center gap-3 px-4 py-2.5 border-b border-[#F4F7FC] last:border-b-0"
                          >
                            <div className="flex-1 min-w-0">
                              <div className="text-sm text-[#0B1C3F] truncate">{it.name}</div>
                              {it.category && (
                                <div className="text-[10.5px] uppercase tracking-wider text-[#64748B]">{it.category}</div>
                              )}
                            </div>
                            <div className="text-sm font-mono text-[#475569] w-16 text-right" style={{ fontVariantNumeric: 'tabular-nums' }}>
                              {Number(it.price).toFixed(2)} €
                            </div>
                            <div className="flex items-center gap-1">
                              <button
                                type="button"
                                onClick={() => bumpQty(it.id, -1)}
                                aria-label={t('scan.qty_minus')}
                                className="w-8 h-8 rounded-lg border border-[#E6EEFB] text-[#2F6BFF] font-bold"
                                style={{ background: '#FFFFFF', font: 'inherit', cursor: 'pointer' }}
                              >
                                −
                              </button>
                              <span className="w-8 text-center text-sm font-bold" style={{ fontVariantNumeric: 'tabular-nums' }}>
                                {qty}
                              </span>
                              <button
                                type="button"
                                onClick={() => bumpQty(it.id, +1)}
                                aria-label={t('scan.qty_plus')}
                                className="w-8 h-8 rounded-lg border border-[#E6EEFB] text-[#10A36B] font-bold"
                                style={{ background: '#FFFFFF', font: 'inherit', cursor: 'pointer' }}
                              >
                                +
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
                <p className="text-xs text-[#475569] mt-2">
                  {t('scan.catalog_no_items_hint')}
                </p>
              </div>
            )}

            <div>
              <label className="block text-sm font-bold text-[#0B1C3F] mb-2 uppercase tracking-wide">
                {t('scan.amount_label')}
                {pickedItems.length > 0 && (
                  <span className="ml-2 normal-case text-xs font-normal text-[#10A36B]">
                    {t('scan.catalog_auto_filled')}
                  </span>
                )}
              </label>
              <div className="relative">
                <Euro className="w-5 h-5 absolute left-4 top-1/2 -translate-y-1/2 text-[#94A3B8] pointer-events-none" />
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={amountPaid}
                  onChange={handleAmountPaidChange}
                  placeholder="0.00"
                  className={`w-full pl-14 pr-4 py-4 rounded-xl border-2 focus:ring-0 outline-none text-lg font-bold font-['Inter'] transition-colors ${
                    pickedItems.length > 0
                      ? 'border-[#E3A869] bg-[#F6F9FF] focus:border-[#E3A869]'
                      : 'border-[#E6EEFB] focus:border-[#2F6BFF]'
                  }`}
                  disabled={loading || pickedItems.length > 0}
                  readOnly={pickedItems.length > 0}
                />
              </div>
              <p className="text-xs text-[#475569] mt-2">{
                pickedItems.length > 0
                  ? t('scan.amount_hint_picker')
                  : pointsMode === 'per_euro'
                    ? t('scan.amount_hint_per_euro')
                    : t('scan.amount_hint_per_visit')
              }</p>
            </div>

            {/* No points field (user, 2026-10-04): the server adds them from the
                card's own rules (per visit, per euro or cashback) and the
                customer's Wallet card updates by itself. A typed number used
                to override those rules — and a cashback card got 10 « points »
                instead of its euros. */}
            <p className="flex items-start gap-2 rounded-xl bg-[#F4F7FC] px-4 py-3 text-[13px] text-[#334155]">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[#2F6BFF]" />
              <span>{t('scan.points_auto')}</span>
            </p>

            <button
              type="submit"
              disabled={loading || !barcode.trim()}
              className="w-full py-4 rounded-xl text-white font-bold text-lg bg-[#2F6BFF] hover:bg-[#2559DB] disabled:opacity-50 transition-all shadow-md mt-4"
            >
              {loading ? t('scan.submitting') : t('scan.submit')}
            </button>
          </form>
        )}

        {status && (
          <div className={`mt-8 rounded-2xl border animation-fadeIn ${status.type === 'success' ? 'bg-[#F6F9FF] border-[#E3A869]/50 p-8' : status.type === 'error' ? 'bg-red-50 border-red-200 p-6' : 'bg-[#F4F7FC] border-[#E6EEFB] p-6'}`}>
            {status.type === 'success' && scanResult ? (
              <>
                <div className="flex items-center justify-center gap-3 mb-6">
                  <CheckCircle2 className="w-10 h-10 text-[#E3A869]" />
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
                    <p className="text-3xl font-bold text-[#0F8B58]">+1</p>
                    <p className="text-sm text-[#475569]">{t('scan.label_stamp')}</p>
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

                {/* Reward Unlocked Banner — now with a live "Mark as redeemed" action */}
                {scanResult.reward_unlocked && (
                  <div className="bg-[#0F8B58] text-white p-6 rounded-lg mb-6">
                    <div className="text-center mb-4">
                      <p className="text-2xl font-bold mb-1">{t('scan.reward_unlocked')}</p>
                      <p className="text-sm opacity-90">
                        {t('scan.reward_subtitle', { name: scanResult.customer_name || t('scan.this_customer') })}
                      </p>
                    </div>
                    {redeemDone ? (
                      <div className="bg-white/10 rounded-lg p-3 text-center">
                        <p className="font-bold flex items-center justify-center gap-2">
                          <CheckCircle2 size={18} /> {t('scan.reward_redeemed')}
                        </p>
                      </div>
                    ) : (
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
                            setRedeemDone(true);
                          } catch (e) {
                            alert('Failed to redeem: ' + (e?.response?.data?.detail || e.message));
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
                    <p className="text-xs text-white/80 text-center mt-3">
                      {t('scan.redeem_hint')}
                    </p>
                  </div>
                )}

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
      </div>
    </div>
  );
};

export default ScanPage;
