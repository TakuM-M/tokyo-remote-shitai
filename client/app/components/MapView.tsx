'use client';

import { useEffect, useRef, useState } from 'react';
import { useApp } from '@/lib/store';
import { scoreToColor, COLOR_RAMP } from '@/lib/scoring';

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

export default function MapView() {
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
    <div className="relative w-full h-full flex items-center justify-center p-4 min-h-[400px]" ref={wrapRef}>
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
