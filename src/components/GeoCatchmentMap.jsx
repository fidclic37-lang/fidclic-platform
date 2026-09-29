import React, { useEffect, useRef, useState } from 'react';
import { Plus, Minus, Car, Bike, Footprints } from 'lucide-react';

/**
 * GeoCatchmentMap — the map on the Géolocalisation page.
 *
 * Leaflet + OSM tiles (the library is already loaded from the CDN in
 * index.html, same as the France map). Draws, over the real street map:
 *
 *   • the shop, at its real position
 *   • the catchment rings, filled — 0–5 / 5–15 / 15–30 km
 *   • the travel-time bands, dashed — 5 / 15 / 25 / 35 min at the mode's
 *     average speed, so the two readings can be told apart at a glance when
 *     both are switched on
 *   • one dot per client, coloured by the ring they fall in
 *   • a label on each of the top communes, at that commune's own coordinates
 *
 * The zoom buttons and the legend are React overlays rather than Leaflet
 * controls, so they sit exactly where the design puts them.
 */
const TONE_HEX = {
  rose:   '#F43F5E',
  amber:  '#F59E0B',
  blue:   '#3B82F6',
  violet: '#8B5CF6',
};
const MODE_ICON = { car: Car, bike: Bike, walk: Footprints };

export default function GeoCatchmentMap({
  data, showCatchment, showIsochrones, mode = 'car', height = 430,
}) {
  const boxRef = useRef(null);
  const mapRef = useRef(null);
  const layerRef = useRef(null);
  const [ready, setReady] = useState(typeof window !== 'undefined' && !!window.L);
  const [failed, setFailed] = useState(false);

  // Leaflet arrives from the CDN; wait for it rather than assuming.
  useEffect(() => {
    if (ready) return undefined;
    let tries = 0;
    const id = setInterval(() => {
      tries += 1;
      if (window.L) { setReady(true); clearInterval(id); }
      else if (tries > 60) { setFailed(true); clearInterval(id); }
    }, 250);
    return () => clearInterval(id);
  }, [ready]);

  const shop = data?.shop;

  useEffect(() => {
    if (!ready || !boxRef.current || mapRef.current || !shop?.lat) return;
    const L = window.L;
    const map = L.map(boxRef.current, {
      center: [shop.lat, shop.lng], zoom: 11,
      zoomControl: false, scrollWheelZoom: true, attributionControl: false,
    });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18, attribution: '© OpenStreetMap',
    }).addTo(map);
    L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);
    L.control.attribution({ position: 'bottomright', prefix: false })
      .addAttribution('© OpenStreetMap').addTo(map);
    mapRef.current = map;
    layerRef.current = L.layerGroup().addTo(map);
    // The container is sized by CSS after mount; without this the tiles come
    // back as a quarter-rendered grid.
    setTimeout(() => map.invalidateSize(), 60);
  }, [ready, shop?.lat, shop?.lng]);

  useEffect(() => () => { mapRef.current?.remove(); mapRef.current = null; }, []);

  // Redraw everything whenever the toggles, the mode or the data change.
  useEffect(() => {
    const L = window.L;
    const map = mapRef.current;
    if (!L || !map || !data?.positioned) return;
    const layer = layerRef.current;
    if (!layer) return;
    layer.clearLayers();

    const { lat, lng } = data.shop;
    const zones = data.catchment?.zones || [];
    const bands = data.isochrones?.bands || [];

    // Rings are drawn largest first so the smaller, hotter ones stay on top.
    if (showCatchment) {
      [...zones].reverse().forEach((z) => {
        L.circle([lat, lng], {
          radius: z.to_km * 1000,
          color: TONE_HEX[z.tone], weight: 1.5, opacity: 0.55,
          fillColor: TONE_HEX[z.tone], fillOpacity: 0.16, interactive: false,
        }).addTo(layer);
      });
    }
    if (showIsochrones) {
      [...bands].reverse().forEach((b) => {
        L.circle([lat, lng], {
          radius: b.radius_km * 1000,
          color: TONE_HEX[b.tone], weight: 2, opacity: 0.9,
          dashArray: '6 5',
          // Filled only when it is the sole reading; over the catchment rings a
          // second set of fills would just muddy both.
          fill: !showCatchment, fillColor: TONE_HEX[b.tone], fillOpacity: 0.15,
          interactive: false,
        }).addTo(layer);
      });
    }

    // One dot per client, at their own position.
    (data.points || []).forEach((p) => {
      const tone = showCatchment
        ? zones.find((z) => z.key === p.zone)?.tone
        : bands.find((b) => b.minutes === p.band)?.tone;
      if (!tone) return;
      L.circleMarker([p.lat, p.lng], {
        radius: 2.6, color: TONE_HEX[tone], weight: 0,
        fillColor: TONE_HEX[tone], fillOpacity: p.precise ? 0.85 : 0.45,
      }).addTo(layer);
    });

    // Commune labels, on the communes the clients actually live in.
    (data.commune_pins || []).forEach((c) => {
      L.marker([c.lat, c.lng], {
        icon: L.divIcon({
          className: '',
          html: `<span class="geo-pin">${c.name}<b>${c.clients}</b></span>`,
          iconSize: [0, 0],
        }),
        interactive: false,
      }).addTo(layer);
    });

    // The shop itself, last, so nothing covers it.
    L.marker([lat, lng], {
      icon: L.divIcon({
        className: '',
        html: `<span class="geo-shop"><i></i><b>${escapeHtml(data.shop.name)}</b>${
          data.shop.city ? `<u>${escapeHtml(data.shop.city)}</u>` : ''}</span>`,
        iconSize: [0, 0],
      }),
      zIndexOffset: 1000, interactive: false,
    }).addTo(layer);

    // Frame whichever reading is showing, so the rings always fill the panel.
    // L.latLng().toBounds() is pure arithmetic; a throwaway L.circle would need
    // to be on a map before getBounds() can project it, and asking it cold
    // crashes the page.
    const outer = Math.max(
      showCatchment ? Math.max(...zones.map((z) => z.to_km), 0) : 0,
      showIsochrones ? Math.max(...bands.map((b) => b.radius_km), 0) : 0,
    ) || 5;
    const box = map.getContainer();
    if (box.clientWidth && box.clientHeight) {
      map.fitBounds(L.latLng(lat, lng).toBounds(outer * 2200), { padding: [20, 20] });
    }
  }, [data, showCatchment, showIsochrones]);

  const ModeIcon = MODE_ICON[mode] || Car;
  const legendRows = [];
  if (showCatchment) {
    legendRows.push({
      title: 'Zone de chalandise (clients)',
      items: (data?.catchment?.zones || []).map((z) => ({
        tone: z.tone, label: z.label, dashed: false,
      })),
    });
  }
  if (showIsochrones) {
    legendRows.push({
      title: 'Isochrones (temps de trajet estimé)',
      items: (data?.isochrones?.bands || []).map((b) => ({
        tone: b.tone, label: `${b.minutes} minutes`, dashed: showCatchment,
      })),
    });
  }

  if (failed || (!shop?.lat && data?.positioned === false)) {
    return (
      <div className="flex items-center justify-center rounded-2xl border border-[#D9E4F7] bg-[#F8FAFF] px-6 text-center"
           style={{ height }}>
        <p className="max-w-sm text-[13px] text-[#475569]">
          {failed
            ? "La carte n'a pas pu se charger. Les chiffres ci-contre restent exacts."
            : "Ajoutez l'adresse de votre établissement dans Paramètres pour afficher la carte."}
        </p>
      </div>
    );
  }

  return (
    <div className="relative overflow-hidden rounded-2xl border border-[#E6EEFB]" style={{ height }}>
      <div ref={boxRef} className="h-full w-full" />

      {/* legend + zoom, stacked at the top-left as in the design */}
      <div className="pointer-events-none absolute left-3 top-3 z-[500] flex flex-col gap-2">
        {legendRows.map((row) => (
          <div key={row.title}
               className="pointer-events-auto rounded-xl border border-[#E6EEFB] bg-white/95 px-3 py-2.5 shadow-[0_10px_30px_-18px_rgba(11,28,63,.6)] backdrop-blur">
            <p className="mb-1.5 flex items-center gap-1.5 text-[12px] font-bold text-[#0B1C3F]">
              <ModeIcon size={13} className="text-[#2F6BFF]" /> {row.title}
            </p>
            {row.items.map((it) => (
              <p key={it.label} className="flex items-center gap-2 py-0.5 text-[12px] text-[#334155]">
                {it.dashed ? (
                  <span className="inline-block h-0 w-4 shrink-0"
                        style={{ borderTop: `2px dashed ${TONE_HEX[it.tone]}` }} />
                ) : (
                  <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                        style={{ background: TONE_HEX[it.tone] }} />
                )}
                {it.label}
              </p>
            ))}
          </div>
        ))}
        <div className="pointer-events-auto flex w-fit flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white shadow-[0_10px_30px_-18px_rgba(11,28,63,.6)]">
          <button type="button" aria-label="Zoomer" onClick={() => mapRef.current?.zoomIn()}
                  className="flex h-8 w-8 items-center justify-center text-[#334155] transition hover:bg-[#F4F7FC]">
            <Plus size={15} />
          </button>
          <span className="h-px bg-[#E6EEFB]" />
          <button type="button" aria-label="Dézoomer" onClick={() => mapRef.current?.zoomOut()}
                  className="flex h-8 w-8 items-center justify-center text-[#334155] transition hover:bg-[#F4F7FC]">
            <Minus size={15} />
          </button>
        </div>
      </div>
    </div>
  );
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
