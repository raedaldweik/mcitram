import { useEffect, useMemo, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

/*
 * MapCard — renders a TomTom render-map spec as an interactive MapLibre map,
 * themed to match the SAS UI (pearl/glass chrome, SAS blue overlays).
 *
 * Data source: the `tomtom-render-map` MCP tool. The spec carries region
 * defaults from the server; this component only draws it.
 *
 * Basemap: by default a light TomTom raster basemap (reliable, needs only an
 * API key). Set VITE_MAP_STYLE_URL to a TomTom vector style for 3D buildings /
 * full theming. Configure VITE_TOMTOM_API_KEY for tiles + traffic.
 */

const TOMTOM_KEY = import.meta.env.VITE_TOMTOM_API_KEY || '';
const VECTOR_STYLE_URL = import.meta.env.VITE_MAP_STYLE_URL || '';
// Set VITE_MAP_RASTER=true to force the flat raster basemap (no 3D buildings).
const USE_RASTER = String(import.meta.env.VITE_MAP_RASTER || '').toLowerCase() === 'true';

// SAS palette (mirrors src/index.css tokens).
const SAS_BLUE = '#BC3B33';
const SAS_BLUE_HI = '#D08479';
const TEAL = '#B07A2A';
const INK = '#1C1913';

const SEVERITY_COLOR = {
  major: '#BC3B33',
  moderate: '#ea580c',
  minor: '#ca8a04',
  unknown: '#8B8676',
};

// Light TomTom raster basemap as a MapLibre style object (flat — no 3D).
// Used when VITE_MAP_RASTER=true, or as a fallback when no key is available.
function rasterStyle(key) {
  return {
    version: 8,
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: {
      'tomtom-basic': {
        type: 'raster',
        tiles: [`https://api.tomtom.com/map/1/tile/basic/main/{z}/{x}/{y}.png?key=${key}`],
        tileSize: 256,
        attribution: '© TomTom',
      },
    },
    layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': '#EFEBE0' } },
      { id: 'tomtom-basic', type: 'raster', source: 'tomtom-basic' },
    ],
  };
}

// TomTom Orbis VECTOR style — ships 3D building (fill-extrusion) layers, so it
// supports the tilted 3D view. This is the same style URL TomTom's own Maps SDK
// builds. `map=basic_street-light` matches the UI's light/pearl theme.
const ORBIS_STYLE_VERSION = '0.6.0-0';
function orbisVectorStyleUrl(key, variant = 'basic_street-light') {
  return `https://api.tomtom.com/maps/orbis/assets/styles/${ORBIS_STYLE_VERSION}/style.json` +
    `?apiVersion=1&map=${variant}&key=${key}`;
}

function circleToPolygon(centerLngLat, radiusMeters, points = 64) {
  const [lng, lat] = centerLngLat;
  const coords = [];
  const dx = radiusMeters / (111320 * Math.cos((lat * Math.PI) / 180));
  const dy = radiusMeters / 110540;
  for (let i = 0; i <= points; i++) {
    const t = (i / points) * 2 * Math.PI;
    coords.push([lng + dx * Math.cos(t), lat + dy * Math.sin(t)]);
  }
  return coords;
}

function fmtDistance(m) {
  if (m == null) return null;
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
}
function fmtDuration(s) {
  if (s == null) return null;
  const min = Math.round(s / 60);
  if (min < 60) return `${min} min`;
  return `${Math.floor(min / 60)} h ${min % 60} min`;
}

function popupHtml(title, rows) {
  const body = rows.filter(Boolean).map((r) => `<div class="mc-pop-row">${r}</div>`).join('');
  return `<div class="mc-pop"><div class="mc-pop-title">${title || 'Location'}</div>${body}</div>`;
}

export default function MapCard({ spec }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const [trafficOn, setTrafficOn] = useState(!!spec?.showTraffic);
  const [missingKey] = useState(!TOMTOM_KEY && !VECTOR_STYLE_URL);

  // Rebuild the map only when the spec's *content* changes — not on every
  // re-render — so polling the next query doesn't flicker/reload the map.
  const specKey = useMemo(() => JSON.stringify(spec), [spec]);

  useEffect(() => {
    if (!containerRef.current || missingKey) return undefined;

    // Basemap precedence: explicit custom style → forced raster → Orbis vector
    // (default; supports 3D buildings) → raster fallback when no key.
    let style;
    if (VECTOR_STYLE_URL) {
      style = VECTOR_STYLE_URL.includes('key=') || !TOMTOM_KEY
        ? VECTOR_STYLE_URL
        : `${VECTOR_STYLE_URL}${VECTOR_STYLE_URL.includes('?') ? '&' : '?'}key=${TOMTOM_KEY}`;
    } else if (USE_RASTER || !TOMTOM_KEY) {
      style = rasterStyle(TOMTOM_KEY);
    } else {
      style = orbisVectorStyleUrl(TOMTOM_KEY);
    }
    const isVector = Boolean(VECTOR_STYLE_URL) || (!USE_RASTER && Boolean(TOMTOM_KEY));

    const center = [spec.center?.lon ?? 55.2708, spec.center?.lat ?? 25.2048];
    const map = new maplibregl.Map({
      container: containerRef.current,
      style,
      center,
      zoom: spec.zoom ?? 11,
      pitch: spec.pitch ?? 45,
      bearing: spec.bearing ?? 0,
      maxBounds: spec.maxBounds
        ? [[spec.maxBounds[0], spec.maxBounds[1]], [spec.maxBounds[2], spec.maxBounds[3]]]
        : undefined,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');

    const allCoords = [];
    const pushCoord = (lng, lat) => { if (Number.isFinite(lng) && Number.isFinite(lat)) allCoords.push([lng, lat]); };

    map.on('load', () => {
      // 3D buildings: vector styles (e.g. TomTom Orbis) ship fill-extrusion
      // building layers — make sure they're visible and themed to the UI.
      if (isVector) {
        try {
          for (const l of map.getStyle().layers || []) {
            if (l.type === 'fill-extrusion' && /building/i.test(l.id)) {
              map.setLayoutProperty(l.id, 'visibility', 'visible');
              map.setPaintProperty(l.id, 'fill-extrusion-color', '#e7dfd3');
              map.setPaintProperty(l.id, 'fill-extrusion-opacity', 0.92);
            }
          }
        } catch { /* style without building layers — stay 2D */ }
      }

      // ---- Areas (isochrones / circles) ----
      (spec.areas || []).forEach((area, i) => {
        let ring = null;
        if (area.type === 'circle' && area.center && area.radiusMeters) {
          ring = circleToPolygon([area.center.lon, area.center.lat], area.radiusMeters);
        } else if (area.coordinates?.length >= 3) {
          ring = area.coordinates.map((c) => [c.lon, c.lat]);
          if (ring.length) ring.push(ring[0]);
        }
        if (!ring) return;
        ring.forEach(([lng, lat]) => pushCoord(lng, lat));
        const id = `area-${i}`;
        const color = area.color || TEAL;
        map.addSource(id, { type: 'geojson', data: { type: 'Feature', geometry: { type: 'Polygon', coordinates: [ring] }, properties: {} } });
        map.addLayer({ id: `${id}-fill`, type: 'fill', source: id, paint: { 'fill-color': color, 'fill-opacity': 0.14 } });
        map.addLayer({ id: `${id}-line`, type: 'line', source: id, paint: { 'line-color': color, 'line-width': 2, 'line-opacity': 0.7 } });
      });

      // ---- Routes ----
      (spec.routes || []).forEach((route, i) => {
        const pts = (route.points || []).map((p) => [p.lon, p.lat]).filter(([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat));
        if (pts.length < 2) return;
        pts.forEach(([lng, lat]) => pushCoord(lng, lat));
        const id = `route-${i}`;
        const color = route.color || SAS_BLUE;
        map.addSource(id, { type: 'geojson', data: { type: 'Feature', geometry: { type: 'LineString', coordinates: pts }, properties: {} } });
        // casing under the main line for a polished look
        map.addLayer({ id: `${id}-casing`, type: 'line', source: id, layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#ffffff', 'line-width': 8, 'line-opacity': 0.9 } });
        map.addLayer({ id: `${id}-line`, type: 'line', source: id, layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': color, 'line-width': 5 } });

        const dist = fmtDistance(route.distanceMeters);
        const dur = fmtDuration(route.travelTimeSeconds);
        if (route.label || dist || dur) {
          const html = popupHtml(route.label || 'Route', [
            dist && `<span class="mc-k">Distance</span> ${dist}`,
            dur && `<span class="mc-k">Time</span> ${dur}`,
          ]);
          map.on('click', `${id}-line`, (e) => {
            new maplibregl.Popup({ closeButton: true, className: 'mc-popup' })
              .setLngLat(e.lngLat).setHTML(html).addTo(map);
          });
          map.on('mouseenter', `${id}-line`, () => { map.getCanvas().style.cursor = 'pointer'; });
          map.on('mouseleave', `${id}-line`, () => { map.getCanvas().style.cursor = ''; });
        }
      });

      // ---- Markers ----
      (spec.markers || []).forEach((m) => {
        if (!Number.isFinite(m.lon) || !Number.isFinite(m.lat)) return;
        pushCoord(m.lon, m.lat);
        const el = document.createElement('div');
        if (m.category) {
          el.className = 'mc-dot';
          el.style.background = m.color || SAS_BLUE_HI;
        } else {
          el.className = 'mc-pin';
          el.style.color = m.color || SAS_BLUE;
          el.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C8.1 2 5 5.1 5 9c0 5.2 7 13 7 13s7-7.8 7-13c0-3.9-3.1-7-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z"/></svg>';
        }
        const marker = new maplibregl.Marker({ element: el, anchor: m.category ? 'center' : 'bottom' })
          .setLngLat([m.lon, m.lat]).addTo(map);
        if (m.label || m.description || m.category) {
          const html = popupHtml(m.label, [
            m.category && `<span class="mc-k">${m.category}</span>`,
            m.description,
          ]);
          marker.setPopup(new maplibregl.Popup({ offset: 24, className: 'mc-popup' }).setHTML(html));
        }
      });

      // ---- Incidents ----
      (spec.incidents || []).forEach((inc) => {
        if (!Number.isFinite(inc.lon) || !Number.isFinite(inc.lat)) return;
        pushCoord(inc.lon, inc.lat);
        const el = document.createElement('div');
        el.className = 'mc-incident';
        el.style.background = SEVERITY_COLOR[inc.severity] || SEVERITY_COLOR.unknown;
        el.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="#fff"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>';
        const marker = new maplibregl.Marker({ element: el, anchor: 'center' }).setLngLat([inc.lon, inc.lat]).addTo(map);
        if (inc.type || inc.description) {
          marker.setPopup(new maplibregl.Popup({ offset: 14, className: 'mc-popup' })
            .setHTML(popupHtml(inc.type || 'Incident', [inc.severity && `<span class="mc-k">${inc.severity}</span>`, inc.description])));
        }
      });

      // ---- Traffic flow overlay (toggleable) ----
      if (TOMTOM_KEY) {
        map.addSource('tomtom-traffic', {
          type: 'raster',
          tiles: [`https://api.tomtom.com/traffic/map/4/tile/flow/relative0/{z}/{x}/{y}.png?key=${TOMTOM_KEY}`],
          tileSize: 256,
        });
        map.addLayer({ id: 'tomtom-traffic', type: 'raster', source: 'tomtom-traffic', layout: { visibility: trafficOn ? 'visible' : 'none' } });
      }

      // ---- Camera ----
      if ((spec.autoFit ?? true) && allCoords.length >= 2) {
        const bounds = allCoords.reduce((b, c) => b.extend(c), new maplibregl.LngLatBounds(allCoords[0], allCoords[0]));
        map.fitBounds(bounds, { padding: 56, maxZoom: 16, duration: 700, pitch: spec.pitch ?? 45 });
      } else if (allCoords.length === 1) {
        map.easeTo({ center: allCoords[0], zoom: Math.max(spec.zoom ?? 13, 13), duration: 600 });
      }
    });

    return () => { map.remove(); mapRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [specKey, missingKey]);

  // React to traffic toggle without rebuilding the map.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getLayer || !map.getLayer('tomtom-traffic')) return;
    map.setLayoutProperty('tomtom-traffic', 'visibility', trafficOn ? 'visible' : 'none');
  }, [trafficOn]);

  if (missingKey) {
    return (
      <div className="mc-frame mc-empty" style={{ height: 200 }}>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, textAlign: 'center', padding: 16 }}>
          🗺️ Map ready — set <code>VITE_TOMTOM_API_KEY</code> (or <code>VITE_MAP_STYLE_URL</code>) in the
          frontend env to render it.
        </div>
      </div>
    );
  }

  return (
    <div className="mc-wrap">
      {spec.title && <div className="mc-title">{spec.title}</div>}
      <div className="mc-frame">
        <div ref={containerRef} className="mc-map" />
        {TOMTOM_KEY && (
          <button
            className="mc-traffic-btn"
            onClick={() => setTrafficOn((v) => !v)}
            style={{ borderColor: trafficOn ? SAS_BLUE : 'rgba(28,25,19,0.12)', color: trafficOn ? SAS_BLUE : INK }}
            title="Toggle live traffic"
          >
            <span className="mc-traffic-dot" style={{ background: trafficOn ? SAS_BLUE : '#8B8676' }} />
            Traffic
          </button>
        )}
      </div>
    </div>
  );
}
