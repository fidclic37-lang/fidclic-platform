/**
 * LoadingDistraction — a friendly interactive while heavy data loads.
 *
 * Shows a "tap the coffee beans" mini-game. Beans drift around a soft
 * canvas; tapping one earns a point. Score persists in component state
 * only. After 5 seconds the score also fades into a "did you know…"
 * tip about FidClic to make the wait feel learn-y instead of empty.
 *
 * Tunable via props:
 *   - title:   string (default "Chargement de votre tableau de bord")
 *   - message: string (default "On prépare vos chiffres en direct…")
 *   - height:  number (default 280)
 *
 * Replaces a plain "Loading…" line with no extra dependencies.
 */
import React, { useEffect, useRef, useState } from 'react';

const TIPS_FR = [
  "Le saviez-vous ? Une carte FidClic s'ajoute au wallet en 5 secondes.",
  "Astuce : 22% des clients reviennent quand on souhaite leur anniversaire.",
  "Vos clients endormis restent endormis… jusqu'à ce qu'on les réveille.",
  "Le mardi est souvent le jour le plus calme. Idéal pour une promo ciblée.",
  "Les notifications push coûtent 0 €. C'est votre canal le plus puissant.",
  "Vos VIP représentent typiquement 40% de votre chiffre. Connaissez-les.",
  "Une carte mobile ne se perd jamais — contrairement aux cartes papier.",
];

const COLORS = ['#B85C38', '#E3A869', '#D77FA0', '#B85C38', '#6FA89C', '#6BA4D9'];

const LoadingDistraction = ({
  title = 'Chargement de votre tableau de bord',
  message = "On prépare vos chiffres en direct — ça prend une seconde.",
  height = 280,
}) => {
  const containerRef = useRef(null);
  const [beans, setBeans] = useState([]);
  const [score, setScore] = useState(0);
  const [tipIdx, setTipIdx] = useState(() => Math.floor(Math.random() * TIPS_FR.length));

  // Spawn 6 beans with random positions and motion
  useEffect(() => {
    const seeded = Array.from({ length: 6 }, (_, i) => ({
      id: i,
      x: 10 + Math.random() * 80,         // %
      y: 15 + Math.random() * 70,         // %
      dx: (Math.random() - 0.5) * 0.4,
      dy: (Math.random() - 0.5) * 0.4,
      color: COLORS[i % COLORS.length],
      size: 28 + Math.random() * 14,
      caught: false,
    }));
    setBeans(seeded);
  }, []);

  // Drift beans every 50ms (gentle, no jitter)
  useEffect(() => {
    const id = setInterval(() => {
      setBeans((curr) => curr.map((b) => {
        if (b.caught) return b;
        let nx = b.x + b.dx;
        let ny = b.y + b.dy;
        let ndx = b.dx;
        let ndy = b.dy;
        if (nx < 4 || nx > 92) ndx = -ndx;
        if (ny < 8 || ny > 88) ndy = -ndy;
        return { ...b, x: Math.max(4, Math.min(92, nx)), y: Math.max(8, Math.min(88, ny)), dx: ndx, dy: ndy };
      }));
    }, 50);
    return () => clearInterval(id);
  }, []);

  // Cycle tips every 4s
  useEffect(() => {
    const id = setInterval(() => setTipIdx((i) => (i + 1) % TIPS_FR.length), 4000);
    return () => clearInterval(id);
  }, []);

  const catchBean = (id) => {
    setBeans((curr) => curr.map((b) => (b.id === id ? { ...b, caught: true } : b)));
    setScore((s) => s + 1);
    // Respawn after 800ms in a new random spot
    setTimeout(() => {
      setBeans((curr) => curr.map((b) => (b.id === id ? {
        ...b,
        caught: false,
        x: 10 + Math.random() * 80,
        y: 15 + Math.random() * 70,
        color: COLORS[Math.floor(Math.random() * COLORS.length)],
      } : b)));
    }, 800);
  };

  return (
    <div className="relative w-full max-w-2xl mx-auto rounded-3xl overflow-hidden border"
         style={{
           height,
           background: `radial-gradient(circle at 20% 20%, #FCE3DC 0%, transparent 50%),
                        radial-gradient(circle at 80% 80%, #DDEBF6 0%, transparent 60%),
                        linear-gradient(135deg, #FAFAF8 0%, #F5EFE5 100%)`,
           borderColor: '#EFE9E0',
         }}
         ref={containerRef}
    >
      {/* Floating beans */}
      {beans.map((b) => (
        <button
          key={b.id}
          type="button"
          onClick={() => !b.caught && catchBean(b.id)}
          aria-label="Catch the bean"
          className="absolute rounded-full transition-all duration-200 ease-out"
          style={{
            left: `${b.x}%`,
            top: `${b.y}%`,
            width: b.size,
            height: b.size,
            background: b.caught ? 'transparent' : `radial-gradient(circle at 30% 30%, ${b.color}EE, ${b.color}88)`,
            boxShadow: b.caught ? 'none' : `0 6px 14px ${b.color}55`,
            opacity: b.caught ? 0 : 1,
            transform: b.caught ? 'scale(1.6)' : 'scale(1)',
            border: b.caught ? 'none' : '2px solid rgba(255,255,255,0.4)',
            cursor: 'pointer',
          }}
        />
      ))}

      {/* Header bar */}
      <div className="absolute top-3 left-4 right-4 flex items-center justify-between text-xs font-bold uppercase tracking-widest pointer-events-none">
        <span style={{ color: '#171412' }}>{title}</span>
        <span className="px-2 py-0.5 rounded-full text-white"
              style={{ background: 'linear-gradient(135deg, #B85C38, #D77FA0)' }}>
          ☕ {score}
        </span>
      </div>

      {/* Bottom message + tip */}
      <div className="absolute bottom-3 left-4 right-4 pointer-events-none">
        <p className="text-xs font-medium" style={{ color: '#3D2820' }}>{message}</p>
        <p className="text-[11px] italic mt-1" style={{ color: '#57504A' }}>
          💡 {TIPS_FR[tipIdx]}
        </p>
        <p className="text-[10px] mt-1" style={{ color: '#8D857D' }}>
          (En attendant — attrapez les grains de café !)
        </p>
      </div>
    </div>
  );
};

export default LoadingDistraction;
