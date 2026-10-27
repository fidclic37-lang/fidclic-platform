# BUILD: Fidélité dual theme — Éclat (light) / Minuit Doré (dark)

> Naye session ke liye: ye file padho, phir seedha Phase 1 se kaam shuru.
> History: is spec ke peeche 3 prototype iterations hain; final approved look
> `public/fidelite-v31.html` mein live hai (fidelitour-deploy.vercel.app/fidelite-v31.html).

## RULE #1 — jo pichli baar toota

**Dono modes ka STRUCTURE identical hai.** Same layout, same sections, same
components — sirf palette flip hoti hai. Aur: **aadha dark ship mat karo.**
Ek page poora dark hone tak `FLC_DARK_READY` flag (DashboardLayout.jsx) OFF
rahega. User ko beech ka aadha state kabhi mat dikhao — page complete hone par
hi screenshot bhejo.

## Approved palettes (prototype se pixel-same rakhna)

### Éclat (light, default)
- paper `#FBFAF8` · card `#FFFFFF` · paper2 `#F4F1EC` · line `#ECE8E2`
- ink `#191410` / `#3A332B` / muted `#524A40`
- accent flame `#C73E2C`, deep `#A82843`, hot `#E8703A` — CTAs = gradient(135deg, #E8703A → #C73E2C → #A82843)
- ok `#0F8B58` · info `#3568B8`
- Hero: flame-plum mesh —
  `radial(115% 140% at 88% 12%, rgba(255,178,94,.85)→t 46%), radial(95% 130% at 8% 95%, rgba(224,53,107,.75)→t 58%), linear(135deg, #2B1028, #7A1E3F 44%, #C73E2C 82%, #E8703A)`

### Minuit Doré (dark)
- paper `#0D0B09` · card `#141110` · paper2 `#1C1815` · line `rgba(212,175,110,.16)`
- ink `#F5F1E8` / `#C9C2B4` / muted `#8D8578`
- accent gold `#D4AF6E`, hi `#EBD5A0`, deep `#A8823D` — CTAs = gradient(#EBD5A0→#A8823D), text `#141110`
- ok `#8FCDA8` · risk `#E2938A`
- Hero: espresso + gold hairline (v31 nuit jaisa)
- Serif display (Cormorant/Georgia) numbers + greetings pe — DONO modes mein

## Kya already bana hai (chhedna nahi)

- `src/components/PageShell.jsx` — C tokens ab CSS vars padhte hain (`--flc-*`)
- `src/index.css` end mein — `.flc` (light vars) + `.flc-nuit` (dark vars) + Tailwind-arbitrary overrides + legacy var remaps (`--surface-card`, `--fd-*`)
- `src/pages/DashboardLayout.jsx` — theme state + toggle (`FLC_DARK_READY=false` se gated), ink-pill active nav
- Éclat light already live hai dashboard pe (flame CTA, semantic KPI chips)

## Kya toota tha (root causes — inhi ko component-level fix karna hai)

1. **Recharts/SVG charts** — colors JS props mein hain, CSS se nahi palt-te.
   Fix: chart components mein colors ko `getComputedStyle`-based ya ek
   `useTheme()` hook se do (ek chhota `src/lib/theme.js` banao jo `flc-nuit`
   class observe kare aur palette object de).
2. **AnalyticsPageV2 ka `.av2-light-skin`** — apne `!important` styles se sab
   override karta hai. Fix: us skin file ko dono themes ke vars pe le jao.
3. **`bg-white/70`, inline `rgba(255,255,255,…)`** — sidebar/panels. Fix:
   grep `bg-white/` + `rgba(255, 255, 255` across src/pages src/components,
   replace with `var(--flc-card)` / `color-mix`.
4. **AmbientBackdrop (PageShell)** — light gradients hardcoded; nuit version chahiye.

## Phase plan (ek phase = ek verify cycle; beech mein user ko mat dikhao)

- **P1 Dashboard** (OwnerDashboard + DashboardLayout + uske components):
  bg-white/rgba sweep → charts hook → prototype ke 4 data-viz KPI cards
  (sparkline+annotation / segmented 312-400 / split QR-vs-parrainage / hot-week
  bars — code `public/fidelite-v31.html` mein ready hai, copy-adapt karo) →
  flame/gold hero band → dono modes screenshot verify → tab hi aage.
- **P2 Analytics** (AnalyticsPage + V2 + av2 skin) — purple poora hatana.
- **P3 Customers + Campaigns + AIAssistant + History**
- **P4 CardDesigner + Settings + Map + MyWalletCard + Scan**
- **P5** `FLC_DARK_READY=true`, toggle wapas, full walkthrough dono modes,
  phir sidebar photo-cover card + join-page photo hero (v31 mein design ready).

## Deploy workflow (har phase ke baad)

```
cd fidelitour-deploy && npx vite build --outDir /tmp/fb --emptyOutDir   # green?
# /tmp/fdep2 clone already hai; warna: git clone --depth 1 <origin> /tmp/fdep2
rsync -a src/ /tmp/fdep2/src/ && cd /tmp/fdep2 && git add -A && git commit && git push
# ~90s Vercel; then log in with a test account → /dashboard
```

## Parallel sessions ka rule

Ye file jis session mein padhi ja rahi hai wo **sirf fidelity design** kare.
Cabinet/backend/docs doosri chat mein. Same repo, alag files — conflict nahi.
