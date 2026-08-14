'use client';

import 'maplibre-gl/dist/maplibre-gl.css';
import { useEffect, useRef, useCallback } from 'react';
import { Map, NavigationControl, Popup } from 'maplibre-gl';
import type { ExpressionSpecification } from 'maplibre-gl';
import { useApp } from '@/lib/store';
import { scoreToColor, NO_DATA_COLOR, COLOR_RAMP } from '@/lib/scoring';

const TOKYO_CENTER: [number, number] = [139.4, 35.69];
const TOKYO_BOUNDS: [[number, number], [number, number]] = [
  [138.9, 35.5],
  [139.95, 35.9],
];

export default function MapView() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const popupRef = useRef<Popup | null>(null);
  const { state, dispatch, getFillValue } = useApp();
  const prevFillRef = useRef<string>('');
  const sourceLoadedRef = useRef(false);

  // Initialize map
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;

    const map = new Map({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {},
        layers: [
          {
            id: 'background',
            type: 'background',
            paint: { 'background-color': '#ffffff' },
          },
        ],
        glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
      },
      center: TOKYO_CENTER,
      zoom: 9.8,
      maxBounds: TOKYO_BOUNDS,
      attributionControl: false,
      pitchWithRotate: false,
    });

    map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Update colors when weights or fill mode change
  const updateColors = useCallback(() => {
    const map = mapRef.current;
    if (!map || !state.data || !sourceLoadedRef.current) return;

    state.data.municipalities.forEach((m) => {
      const fillVal = getFillValue(m);
      const color = scoreToColor(fillVal);
      map.setFeatureState(
        { source: 'tokyo-municipalities', id: m.code },
        { fillColor: color }
      );
    });
  }, [state.data, state.weights, state.fillMode, getFillValue]);

  // Load GeoJSON data once available
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !state.data) return;

    const loadSource = () => {
      if (map.getSource('tokyo-municipalities')) return;

      fetch('/data/boundaries.geojson')
        .then((res) => {
          if (!res.ok) throw new Error('GeoJSON not found');
          return res.json();
        })
        .then((geojson) => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          geojson.features.forEach((f: any) => {
            f.id = parseInt(f.properties.code, 10);
          });

          map.addSource('tokyo-municipalities', {
            type: 'geojson',
            data: geojson,
            promoteId: 'code',
          });

          // Fill layer
          map.addLayer({
            id: 'municipality-fills',
            type: 'fill',
            source: 'tokyo-municipalities',
            paint: {
              'fill-color': [
                'coalesce',
                ['feature-state', 'fillColor'],
                NO_DATA_COLOR,
              ] as unknown as ExpressionSpecification,
              'fill-opacity': [
                'case',
                ['boolean', ['feature-state', 'hover'], false],
                0.95,
                0.8,
              ],
            },
          });

          // Outline layer
          map.addLayer({
            id: 'municipality-borders',
            type: 'line',
            source: 'tokyo-municipalities',
            paint: {
              'line-color': [
                'case',
                ['boolean', ['feature-state', 'selected'], false],
                '#000000',
                '#ffffff',
              ],
              'line-width': [
                'case',
                ['boolean', ['feature-state', 'selected'], false],
                2.5,
                ['boolean', ['feature-state', 'hover'], false],
                1.5,
                0.5,
              ],
            },
          });

          sourceLoadedRef.current = true;
          updateColors();
        })
        .catch(() => {
          console.warn('GeoJSON boundaries not available');
        });
    };

    if (map.isStyleLoaded()) {
      loadSource();
    } else {
      map.on('load', loadSource);
    }
  }, [state.data, updateColors]);

  useEffect(() => {
    const key = `${JSON.stringify(state.weights)}-${state.fillMode}`;
    if (key === prevFillRef.current) return;
    prevFillRef.current = key;
    updateColors();
  }, [state.weights, state.fillMode, updateColors]);

  // Selected state
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !state.data || !sourceLoadedRef.current) return;

    state.data.municipalities.forEach((m) => {
      map.setFeatureState(
        { source: 'tokyo-municipalities', id: m.code },
        { selected: m.code === state.selectedCode }
      );
    });
  }, [state.selectedCode, state.data]);

  // Hover and click interactions
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    let hoveredCode: string | null = null;

    const popup = new Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 15,
    });
    popupRef.current = popup;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const onMouseMove = (e: any) => {
      if (!e.features?.length) return;
      const code = e.features[0].properties?.code as string;

      if (hoveredCode && hoveredCode !== code) {
        map.setFeatureState(
          { source: 'tokyo-municipalities', id: hoveredCode },
          { hover: false }
        );
      }

      hoveredCode = code;
      map.setFeatureState(
        { source: 'tokyo-municipalities', id: code },
        { hover: true }
      );

      map.getCanvas().style.cursor = 'pointer';

      const muni = state.data?.municipalities.find((m) => m.code === code);
      if (muni) {
        const fillVal = getFillValue(muni);
        const labelKey = state.fillMode === 'total'
          ? '総合'
          : (state.data?.meta.axes.find((a) => a.key === state.fillMode)?.label ?? '');
        popup
          .setLngLat(e.lngLat)
          .setHTML(
            `<div style="font-family:var(--font-sans),system-ui,sans-serif;font-size:13px;line-height:1.5;">
              <strong style="font-size:15px;">${muni.name}</strong><br/>
              <span style="color:#6b7280;font-size:12px;">${labelKey}:</span>
              <strong style="font-variant-numeric:tabular-nums;">${fillVal !== null ? fillVal.toFixed(1) : 'データなし'}</strong>
            </div>`
          )
          .addTo(map);
      }
    };

    const onMouseLeave = () => {
      if (hoveredCode) {
        map.setFeatureState(
          { source: 'tokyo-municipalities', id: hoveredCode },
          { hover: false }
        );
        hoveredCode = null;
      }
      map.getCanvas().style.cursor = '';
      popup.remove();
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const onClick = (e: any) => {
      if (!e.features?.length) return;
      const code = e.features[0].properties?.code as string;
      dispatch({
        type: 'SET_SELECTED',
        payload: state.selectedCode === code ? null : code,
      });
    };

    map.on('mousemove', 'municipality-fills', onMouseMove);
    map.on('mouseleave', 'municipality-fills', onMouseLeave);
    map.on('click', 'municipality-fills', onClick);

    return () => {
      map.off('mousemove', 'municipality-fills', onMouseMove);
      map.off('mouseleave', 'municipality-fills', onMouseLeave);
      map.off('click', 'municipality-fills', onClick);
      popup.remove();
    };
  }, [state.data, state.selectedCode, state.fillMode, state.weights, dispatch, getFillValue]);

  return (
    <div className="relative w-full h-full min-h-[400px]">
      <div ref={mapContainer} className="absolute inset-0" />

      {/* Legend - frosted glass */}
      <div className="absolute bottom-6 left-6 bg-white/80 backdrop-blur-xl rounded-xl p-4 shadow-lg border border-white/40">
        <div className="text-xs text-foreground font-bold mb-2">
          {state.fillMode === 'total'
            ? '総合スコア'
            : state.data?.meta.axes.find((a) => a.key === state.fillMode)?.label}
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-muted-foreground font-medium mr-1">低</span>
          {COLOR_RAMP.map((color, i) => (
            <div
              key={i}
              className="w-8 h-2.5 first:rounded-l-full last:rounded-r-full"
              style={{ backgroundColor: color }}
            />
          ))}
          <span className="text-[10px] text-muted-foreground font-medium ml-1">高</span>
        </div>
      </div>
    </div>
  );
}
