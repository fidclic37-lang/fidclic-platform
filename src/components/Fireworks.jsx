import React, { useEffect, useRef } from 'react';

/**
 * Fireworks over the whole screen for a few seconds (the « Félicitations ! »
 * page after a customer joins, 2026-10-09). Plain canvas, no library: rockets
 * rise from the bottom, burst into sparks that fall and fade. Clicks go
 * through (pointer-events: none). Nothing runs when the phone asks for
 * reduced motion.
 */
const GRAVITY = 0.16;
const COLORS = ['#EAB308', '#FF5A5F', '#2F6BFF', '#22C55E', '#F59E0B', '#C084FC', '#FF8FD1', '#38BDF8'];

export default function Fireworks({ duration = 6000, colors = COLORS }) {
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return undefined;
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return undefined;
    const ctx = canvas.getContext('2d');
    if (!ctx) return undefined;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let w = 0; let h = 0;
    const size = () => {
      w = window.innerWidth; h = window.innerHeight;
      canvas.width = w * dpr; canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    size();
    window.addEventListener('resize', size);

    const rand = (a, b) => a + Math.random() * (b - a);
    const pick = () => colors[Math.floor(Math.random() * colors.length)];
    const rockets = [];
    const sparks = [];
    const start = performance.now();
    let nextLaunch = 0;
    let frame = 0;
    let last = start;

    const launch = () => {
      // aim each burst at the top half of the screen, whatever its height
      const rise = h + 10 - rand(h * 0.12, h * 0.45);
      rockets.push({
        x: rand(w * 0.15, w * 0.85), y: h + 10,
        vx: rand(-0.6, 0.6), vy: -Math.sqrt(2 * GRAVITY * rise),
        color: pick(), trail: [],
      });
    };

    const burst = (r) => {
      const n = Math.round(rand(64, 90));
      const ring = Math.random() < 0.3;              // now and then a clean ring
      const second = Math.random() < 0.45 ? pick() : r.color;
      for (let i = 0; i < n; i += 1) {
        const a = (Math.PI * 2 * i) / n + rand(-0.05, 0.05);
        const speed = ring ? 5.6 : rand(1.5, 7);
        sparks.push({
          x: r.x, y: r.y, vx: Math.cos(a) * speed, vy: Math.sin(a) * speed,
          life: 1, decay: rand(0.011, 0.02), color: i % 2 ? second : r.color, size: rand(1.2, 2.1),
        });
      }
    };

    const tick = (now) => {
      const t = now - start;
      // same speed on a 60 Hz phone, a 120 Hz iPhone or a slow one
      const k = Math.min(now - last, 50) / 16.67;
      last = now;
      if (t < duration - 1200 && t >= nextLaunch) {
        launch();
        if (Math.random() < 0.35) launch();
        nextLaunch = t + rand(260, 520);
      }

      ctx.clearRect(0, 0, w, h);

      for (let i = rockets.length - 1; i >= 0; i -= 1) {
        const r = rockets[i];
        r.trail.push([r.x, r.y]);
        if (r.trail.length > 8) r.trail.shift();
        r.x += r.vx * k; r.y += r.vy * k; r.vy += GRAVITY * k;
        ctx.strokeStyle = r.color; ctx.lineWidth = 2; ctx.globalAlpha = 0.8;
        ctx.beginPath();
        r.trail.forEach(([x, y], k) => (k ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
        ctx.lineTo(r.x, r.y); ctx.stroke();
        if (r.vy >= -0.4) { burst(r); rockets.splice(i, 1); }
      }

      for (let i = sparks.length - 1; i >= 0; i -= 1) {
        const s = sparks[i];
        const drag = 0.975 ** k;
        s.vx *= drag; s.vy = s.vy * drag + 0.06 * k;
        s.x += s.vx * k; s.y += s.vy * k; s.life -= s.decay * k;
        if (s.life <= 0) { sparks.splice(i, 1); continue; }
        // a short bright streak along the spark's path, with a faint glow
        const alpha = Math.max(0, s.life) * (Math.random() < 0.12 ? 0.5 : 1);   // twinkle
        ctx.strokeStyle = s.color; ctx.lineCap = 'round';
        ctx.globalAlpha = alpha * 0.18; ctx.lineWidth = s.size * 3.2;
        ctx.beginPath(); ctx.moveTo(s.x - s.vx * 2.4, s.y - s.vy * 2.4); ctx.lineTo(s.x, s.y); ctx.stroke();
        ctx.globalAlpha = alpha; ctx.lineWidth = s.size;
        ctx.beginPath(); ctx.moveTo(s.x - s.vx * 2.4, s.y - s.vy * 2.4); ctx.lineTo(s.x, s.y); ctx.stroke();
      }

      ctx.globalAlpha = 1;
      if (t < duration || rockets.length || sparks.length) frame = requestAnimationFrame(tick);
      else ctx.clearRect(0, 0, w, h);
    };
    for (let i = 0; i < 3; i += 1) launch();       // an opening volley
    nextLaunch = 350;
    frame = requestAnimationFrame(tick);

    return () => { cancelAnimationFrame(frame); window.removeEventListener('resize', size); };
  }, [duration, colors]);

  return <canvas ref={ref} aria-hidden="true" className="pointer-events-none fixed inset-0 z-50 h-full w-full" />;
}
