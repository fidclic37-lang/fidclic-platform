import React, { useEffect, useRef, useState } from 'react';
import { Plus, Minus, Eye, EyeOff } from 'lucide-react';

/**
 * The « Zone de détection » map (géolocalisation mockups, 2026-10-11).
 * Leaflet + OSM (loaded in index.html, as GeoCatchmentMap). Draws the real
 * establishments, the shop's one radius around each, and — real data only —
 * the clients detected near them in the last seven days (their card opened
 * inside the zone; positions rounded to ~50 m), each with its count. The
 * owner hides them with one click.
 */
const PIN = '<svg xmlns="http://www.w3.org/2000/svg" width="34" height="34" viewBox="0 0 34 34"><circle cx="17" cy="17" r="15" fill="#1463FF" stroke="#fff" stroke-width="3"/><path d="M10 15.5h14l-1.4-4.2a1.5 1.5 0 0 0-1.4-1h-8.4a1.5 1.5 0 0 0-1.4 1zm1 0v7a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-7m-8 8v-4h4v4" fill="none" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
const WALKER = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#1463FF" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="13" cy="4" r="2"/><path d="m9 20 3-6 3 3v4M6 12l3-4 4 1 3 3h3"/></svg>';

export default function GeoZoneMap({ anchors = [], radius = 200, points = [], height = 270, interactive = true, showPeople: showProp }) {
  const box = useRef(null);
  const mapRef = useRef(null);
  const layer = useRef(null);
  const [ready, setReady] = useState(typeof window !== 'undefined' && !!window.L);
  const [failed, setFailed] = useState(false);
  const [people, setPeople] = useState(showProp !== false);
  const spots = anchors.filter((a) => a.lat != null && a.lng != null);

  useEffect(() => {
    if (ready) return undefined;
    let tries = 0;
    const id = setInterval(() => {
      tries += 1;
      if (window.L) { setReady(true); clearInterval(id); } else if (tries > 60) { setFailed(true); clearInterval(id); }
    }, 250);
    return () => clearInterval(id);
  }, [ready]);

  useEffect(() => {
    if (!ready || !box.current || mapRef.current || !spots.length) return;
    const L = window.L;
    const map = L.map(box.current, {
      center: [spots[0].lat, spots[0].lng], zoom: 16, zoomControl: false, attributionControl: false,
      scrollWheelZoom: false, dragging: interactive, doubleClickZoom: interactive, touchZoom: interactive, keyboard: interactive,
    });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);
    L.control.attribution({ position: 'topleft', prefix: false }).addAttribution('© OpenStreetMap').addTo(map);
    mapRef.current = map;
    layer.current = L.layerGroup().addTo(map);
    setTimeout(() => map.invalidateSize(), 60);
  }, [ready, spots.length, interactive]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => { mapRef.current?.remove(); mapRef.current = null; }, []);

  const key = JSON.stringify([spots.map((a) => [a.id, a.lat, a.lng]), radius, points, people]);
  useEffect(() => {
    const L = window.L;
    const map = mapRef.current;
    if (!L || !map) return;
    const g = layer.current;
    g.clearLayers();
    const bounds = [];
    spots.forEach((a) => {
      const c = L.circle([a.lat, a.lng], { radius, color: '#2F6BFF', weight: 1.5, dashArray: '5 5', fillColor: '#2F6BFF', fillOpacity: 0.14 }).addTo(g);
      bounds.push(c.getBounds());
      L.marker([a.lat, a.lng], { icon: L.divIcon({ html: PIN, className: '', iconSize: [34, 34], iconAnchor: [17, 17] }), title: a.name }).addTo(g);
      if (interactive) {
        // the radius, on the circle's top edge
        L.marker([a.lat + radius / 111320, a.lng], { interactive: false, icon: L.divIcon({ className: '', iconSize: [0, 0],
          html: `<span style="position:absolute;transform:translate(-50%,-50%);white-space:nowrap;border-radius:999px;background:#1463FF;color:#fff;font:600 11px Inter,sans-serif;padding:2px 8px">${radius} m</span>` }) }).addTo(g);
      }
    });
    if (people) {
      points.forEach((p) => {
        const html = `<span style="position:relative;display:flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:999px;background:#fff;box-shadow:0 2px 6px rgba(11,28,63,.25)">${WALKER}${p.count > 1 ? `<b style="position:absolute;top:-6px;right:-8px;min-width:16px;height:16px;border-radius:999px;background:#0B1C3F;color:#fff;font:700 10px Inter,sans-serif;display:flex;align-items:center;justify-content:center;padding:0 3px">${p.count}</b>` : ''}</span>`;
        L.marker([p.lat, p.lng], { icon: L.divIcon({ html, className: '', iconSize: [26, 26], iconAnchor: [13, 13] }),
          title: `${p.count} détection${p.count > 1 ? 's' : ''} · ${p.clients} client${p.clients > 1 ? 's' : ''}` }).addTo(g);
      });
    }
    if (bounds.length) {
      let all = bounds[0];
      bounds.slice(1).forEach((b) => { all = all.extend(b); });
      map.fitBounds(all.pad(0.25), { maxZoom: 17, animate: false });
    }
  }, [key, ready]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!spots.length) {
    return (
      <div className="flex items-center justify-center rounded-2xl border border-dashed border-[#BFD3FF] bg-[#F5F8FF] p-4 text-center text-[12.5px] text-[#475569]" style={{ height }}>
        La position de votre établissement est inconnue : placez-le sur la carte dans Paramètres › Établissement.
      </div>
    );
  }
  return (
    <div className="relative overflow-hidden rounded-2xl border border-[#E6EEFB]" style={{ height }}>
      <div ref={box} className="absolute inset-0" />
      {failed && <p className="absolute inset-0 flex items-center justify-center bg-[#F5F8FF] text-[12.5px] text-[#475569]">La carte n'a pas pu se charger.</p>}
      {interactive && (
        <>
          <div className="absolute right-2 top-2 z-[500] flex flex-col overflow-hidden rounded-lg border border-[#E2E8F0] bg-white shadow">
            <button type="button" aria-label="Zoomer" onClick={() => mapRef.current?.zoomIn()} className="p-1.5 text-[#0B1C3F] hover:bg-[#F1F5F9]"><Plus size={15} /></button>
            <button type="button" aria-label="Dézoomer" onClick={() => mapRef.current?.zoomOut()} className="border-t border-[#E2E8F0] p-1.5 text-[#0B1C3F] hover:bg-[#F1F5F9]"><Minus size={15} /></button>
          </div>
          <div className="absolute inset-x-0 bottom-0 z-[500] flex flex-wrap items-center gap-x-4 gap-y-1 bg-white/95 px-3 py-1.5 text-[11px] text-[#475569]">
            <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-full border border-dashed border-[#2F6BFF] bg-[#2F6BFF]/20" /> Zone de détection ({radius} m)</span>
            <button type="button" onClick={() => setPeople((v) => !v)} aria-pressed={people}
                    className="flex items-center gap-1.5 font-semibold text-[#1463FF]">
              {people ? <Eye size={13} /> : <EyeOff size={13} />} Clients détectés · 7 jours ({points.reduce((n, p) => n + p.count, 0)})
            </button>
          </div>
        </>
      )}
    </div>
  );
}
