'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useApp } from '@/lib/store';
import { scoreToColor, COLOR_RAMP, NO_DATA_COLOR } from '@/lib/scoring';
import { Map as MlMap, NavigationControl, Popup } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

interface GeoFeature {
  type: string;
  properties: { code: string; name: string };
  geometry: {
    type: string;
    coordinates: number[][][][] | number[][][];
  };
}

interface GeoData {
  type: string;
  features: GeoFeature[];
}

// ─── Helper: iterate polygon rings ───────────────────────────────
function eachRing(geom: GeoFeature['geometry'], fn: (ring: number[][]) => void) {
  const polys = geom.type === 'Polygon'
    ? [geom.coordinates as number[][][]]
    : (geom.coordinates as number[][][][]);
  for (const poly of polys) for (const ring of poly) fn(ring);
}

// ═══════════════════════════════════════════════════════════════════
//  SVG Map — index.html の方式をReactに移植（WebGL不要）
// ═══════════════════════════════════════════════════════════════════
function SvgMap() {
  const wrapRef = useRef<HTMLDivElement>(null);
  const { state, dispatch, getFillValue } = useApp();
  const [geoData, setGeoData] = useState<GeoData | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);

  useEffect(() => {
    fetch('/data/boundaries.geojson')
      .then((r) => { if (!r.ok) throw new Error('not found'); return r.json(); })
      .then(setGeoData)
      .catch(() => console.warn('boundaries.geojson not available'));
  }, []);

  if (!state.data || !geoData) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-sm text-muted-foreground animate-pulse">地図データを読み込み中…</p>
      </div>
    );
  }

  // Equirectangular projection with cos(lat) correction
  let minLon = 180, maxLon = -180, minLat = 90, maxLat = -90;
  for (const f of geoData.features) {
    eachRing(f.geometry, (ring) => {
      for (const [lon, lat] of ring) {
        if (lon < minLon) minLon = lon;
        if (lon > maxLon) maxLon = lon;
        if (lat < minLat) minLat = lat;
        if (lat > maxLat) maxLat = lat;
      }
    });
  }
  const kx = Math.cos(((minLat + maxLat) / 2) * Math.PI / 180);
  const SCALE = 1200;
  const px = (lon: number) => (lon - minLon) * kx * SCALE;
  const py = (lat: number) => (maxLat - lat) * SCALE;
  const W = px(maxLon);
  const H = py(minLat);

  const ringPath = (ring: number[][]) =>
    'M' + ring.map(([lon, lat]) => `${px(lon).toFixed(1)},${py(lat).toFixed(1)}`).join('L') + 'Z';

  const byCode = (code: string) => state.data!.municipalities.find((m) => m.code === code);
  const axisLabel = (key: string) => state.data!.meta.axes.find((a) => a.key === key)?.label ?? key;

  return (
    <div className="relative w-full h-full flex items-center justify-center p-4" ref={wrapRef}>
      <svg
        viewBox={`0 0 ${W.toFixed(1)} ${H.toFixed(1)}`}
        className="w-full h-full max-h-full"
        style={{ maxWidth: '100%' }}
      >
        <defs>
          <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="#f3f4f6" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="#9ca3af" strokeWidth="2" />
          </pattern>
        </defs>
        {geoData.features.map((f) => {
          const code = f.properties.code;
          let d = '';
          eachRing(f.geometry, (ring) => { d += ringPath(ring); });
          const muni = byCode(code);
          const score = muni ? getFillValue(muni) : null;
          const fill = score !== null ? scoreToColor(score) : 'url(#hatch)';
          const isSelected = state.selectedCode === code;

          return (
            <path
              key={code}
              d={d}
              fill={fill}
              stroke={isSelected ? '#000' : '#fff'}
              strokeWidth={isSelected ? 2 : 0.6}
              className="cursor-pointer transition-[stroke-width,stroke] duration-100 hover:stroke-[#333] hover:[stroke-width:1.4]"
              onClick={() => dispatch({ type: 'SET_SELECTED', payload: state.selectedCode === code ? null : code })}
              onMouseMove={(e) => {
                if (!wrapRef.current || !muni) return;
                const r = wrapRef.current.getBoundingClientRect();
                const label = state.fillMode === 'total' ? '総合' : axisLabel(state.fillMode);
                setTooltip({
                  x: e.clientX - r.left + 14,
                  y: e.clientY - r.top + 14,
                  text: `${muni.name}\n${label}: ${score === null ? 'データなし' : score.toFixed(1)}`,
                });
              }}
              onMouseLeave={() => setTooltip(null)}
            />
          );
        })}
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="pointer-events-none absolute z-20 whitespace-pre rounded-lg bg-gray-900/90 px-3 py-1.5 text-xs text-white shadow-lg backdrop-blur-sm"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          {tooltip.text}
        </div>
      )}

      {/* Legend */}
      <div className="absolute bottom-4 left-4 bg-white/80 backdrop-blur-xl rounded-xl p-3 shadow-lg border border-white/40">
        <div className="text-[11px] text-foreground font-bold mb-1.5">
          {state.fillMode === 'total' ? '総合スコア' : axisLabel(state.fillMode)}
        </div>
        <div className="flex items-center gap-0.5">
          <span className="text-[9px] text-muted-foreground mr-1">低</span>
          {COLOR_RAMP.map((c, i) => (
            <div key={i} className="w-6 h-2 first:rounded-l-full last:rounded-r-full" style={{ backgroundColor: c }} />
          ))}
          <span className="text-[9px] text-muted-foreground ml-1">高</span>
          <div className="w-px h-2.5 bg-gray-300 mx-1.5" />
          <div className="w-6 h-2 rounded" style={{ background: 'repeating-linear-gradient(45deg, #f3f4f6, #f3f4f6 2px, #9ca3af 2px, #9ca3af 3px)' }} />
          <span className="text-[9px] text-muted-foreground ml-1">欠損</span>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
//  MapLibre GL Map — WebGL2 accelerated
// ═══════════════════════════════════════════════════════════════════
function GlMap() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const { state, dispatch, getFillValue } = useApp();
  const sourceLoadedRef = useRef(false);

  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: {
        version: 8, sources: {},
        layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#f8fafc' } }],
        glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
      },
      center: [139.4, 35.69], zoom: 9.8,
      maxBounds: [[138.85, 35.48], [139.95, 35.92]],
      attributionControl: false, pitchWithRotate: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    mapRef.current = map;
    return () => { try { map.remove(); } catch { /* noop */ } mapRef.current = null; };
  }, []);

  const updateScores = useCallback(() => {
    const map = mapRef.current;
    if (!map || !state.data || !sourceLoadedRef.current) return;
    state.data.municipalities.forEach((m) => {
      const val = getFillValue(m);
      map.setFeatureState({ source: 'tk', id: m.code }, { score: val ?? -1, hasData: val !== null });
    });
  }, [state.data, state.weights, state.fillMode, getFillValue]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !state.data) return;
    const load = () => {
      if (map.getSource('tk')) return;
      fetch('/data/boundaries.geojson').then((r) => r.json()).then((geo: GeoData) => {
        map.addSource('tk', { type: 'geojson', data: geo as any, promoteId: 'code' });
        map.addLayer({
          id: 'fills', type: 'fill', source: 'tk',
          paint: {
            'fill-color': ['case', ['boolean', ['feature-state', 'hasData'], false],
              ['interpolate', ['linear'], ['coalesce', ['feature-state', 'score'], 50],
                0, COLOR_RAMP[0], 25, COLOR_RAMP[1], 50, COLOR_RAMP[2], 75, COLOR_RAMP[3], 100, COLOR_RAMP[4]],
              NO_DATA_COLOR],
            'fill-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.95, 0.78],
          },
        });
        map.addLayer({
          id: 'borders', type: 'line', source: 'tk',
          paint: {
            'line-color': ['case', ['boolean', ['feature-state', 'selected'], false], '#000', '#fff'],
            'line-width': ['case', ['boolean', ['feature-state', 'selected'], false], 2.5, ['boolean', ['feature-state', 'hover'], false], 1.5, 0.6],
          },
        });
        sourceLoadedRef.current = true;
        updateScores();
      }).catch(console.warn);
    };
    if (map.isStyleLoaded()) load(); else map.on('load', load);
  }, [state.data, updateScores]);

  useEffect(() => { updateScores(); }, [state.weights, state.fillMode, updateScores]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !state.data || !sourceLoadedRef.current) return;
    state.data.municipalities.forEach((m) => {
      map.setFeatureState({ source: 'tk', id: m.code }, { selected: m.code === state.selectedCode });
    });
  }, [state.selectedCode, state.data]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    let hc: string | null = null;
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 15 });
    popupRef.current = popup;
    const onMove = (e: any) => {
      if (!e.features?.length) return;
      const code = e.features[0].properties.code;
      if (hc && hc !== code) map.setFeatureState({ source: 'tk', id: hc }, { hover: false });
      hc = code; map.setFeatureState({ source: 'tk', id: code }, { hover: true });
      map.getCanvas().style.cursor = 'pointer';
      const muni = state.data?.municipalities.find((m) => m.code === code);
      if (muni) {
        const v = getFillValue(muni);
        const l = state.fillMode === 'total' ? '総合' : state.data?.meta.axes.find((a) => a.key === state.fillMode)?.label;
        popup.setLngLat(e.lngLat).setHTML(`<div style="font-family:system-ui;font-size:13px;line-height:1.5"><strong style="font-size:15px">${muni.name}</strong><br/><span style="color:#6b7280">${l}:</span> <strong>${v !== null ? v.toFixed(1) : '—'}</strong></div>`).addTo(map);
      }
    };
    const onLeave = () => { if (hc) map.setFeatureState({ source: 'tk', id: hc }, { hover: false }); hc = null; map.getCanvas().style.cursor = ''; popup.remove(); };
    const onClick = (e: any) => { if (!e.features?.length) return; const code = e.features[0].properties.code; dispatch({ type: 'SET_SELECTED', payload: state.selectedCode === code ? null : code }); };
    map.on('mousemove', 'fills', onMove); map.on('mouseleave', 'fills', onLeave); map.on('click', 'fills', onClick);
    return () => { map.off('mousemove', 'fills', onMove); map.off('mouseleave', 'fills', onLeave); map.off('click', 'fills', onClick); popup.remove(); };
  }, [state.data, state.selectedCode, state.fillMode, state.weights, dispatch, getFillValue]);

  return (
    <div className="relative w-full h-full min-h-[400px]">
      <div ref={mapContainer} className="absolute inset-0" />
      <div className="absolute bottom-6 left-6 bg-white/80 backdrop-blur-xl rounded-xl p-4 shadow-lg border border-white/40">
        <div className="text-xs text-foreground font-bold mb-2">
          {state.fillMode === 'total' ? '総合スコア' : state.data?.meta.axes.find((a) => a.key === state.fillMode)?.label}
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-muted-foreground font-medium mr-1">低</span>
          {COLOR_RAMP.map((c, i) => <div key={i} className="w-8 h-2.5 first:rounded-l-full last:rounded-r-full" style={{ backgroundColor: c }} />)}
          <span className="text-[10px] text-muted-foreground font-medium ml-1">高</span>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
//  Export: auto-detect WebGL2, use GL or SVG
// ═══════════════════════════════════════════════════════════════════
export default function MapView() {
  const [useGl, setUseGl] = useState<boolean | null>(null);

  useEffect(() => {
    try {
      const canvas = document.createElement('canvas');
      const gl = canvas.getContext('webgl2');
      setUseGl(!!gl);
    } catch {
      setUseGl(false);
    }
  }, []);

  if (useGl === null) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-sm text-muted-foreground animate-pulse">地図を準備中…</div>
      </div>
    );
  }

  return useGl ? <GlMap /> : <SvgMap />;
}
