'use client';

import { useApp } from '@/lib/store';
import { formatScore, formatNumber, AXIS_COLORS } from '@/lib/scoring';
import { AXIS_ICONS } from '@/lib/types';
import type { AxisKey } from '@/lib/types';
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  Radar,
  ResponsiveContainer,
  Legend,
} from 'recharts';

export default function DetailPanel() {
  const { state, selectedMunicipality, getScore, averageScores, ranking } = useApp();
  const { data, weights } = state;

  if (!data) return null;

  if (!selectedMunicipality) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <div className="text-4xl mb-4 opacity-40 grayscale">🏙️</div>
        <p className="text-sm text-muted-foreground font-medium">
          地図またはランキングから<br />自治体を選択してください
        </p>
      </div>
    );
  }

  const m = selectedMunicipality;
  const totalResult = getScore(m);
  const rankInfo = ranking.find((r) => r.municipality.code === m.code);
  const sources = Object.fromEntries(
    data.meta.sources.map((s) => [s.id, s])
  );

  // Radar chart data
  const radarData = data.meta.axes.map((axis) => {
    const key = axis.key as AxisKey;
    return {
      axis: axis.label,
      value: m.scores[key] ?? 0,
      average: averageScores[key] ?? 0,
      fullMark: 100,
    };
  });

  // Circular progress values
  const scoreForRing = totalResult.score ?? 0;
  const circumference = 2 * Math.PI * 28;
  const dashArray = `${(scoreForRing / 100) * circumference} ${circumference}`;

  return (
    <div className="space-y-5">
      {/* Header with circular score */}
      <div className="flex items-start justify-between bg-card p-4 rounded-xl border border-border shadow-sm">
        <div>
          <div className="text-[10px] font-bold text-muted-foreground tracking-wider">
            順位: #{rankInfo?.rank || '—'} / {ranking.length}
          </div>
          <h2 className="text-2xl font-black text-foreground">{m.name}</h2>
          <p className="text-xs text-muted-foreground mt-1 font-medium">
            {m.region} / {m.kind} ・ {formatNumber(m.area_km2, 1)} km² ・ 人口{' '}
            {formatNumber(m.population, 0)}
          </p>
        </div>

        {/* Circular progress ring */}
        <div className="relative w-16 h-16 flex items-center justify-center shrink-0">
          <svg className="absolute inset-0 w-full h-full transform -rotate-90" viewBox="0 0 64 64">
            <circle cx="32" cy="32" r="28" stroke="currentColor" strokeWidth="5" fill="none" className="text-muted" />
            <circle
              cx="32" cy="32" r="28" stroke="currentColor" strokeWidth="5" fill="none"
              className="text-primary transition-all duration-1000 ease-out"
              strokeDasharray={dashArray}
              strokeLinecap="round"
            />
          </svg>
          <div className="absolute flex flex-col items-center">
            <span className="text-xl font-black tabular-nums">
              {totalResult.score !== null ? formatScore(totalResult.score, 0) : '—'}
            </span>
          </div>
        </div>
      </div>

      {/* Radar Chart */}
      <div className="bg-card rounded-xl p-2 border border-border shadow-sm">
        <ResponsiveContainer width="100%" height={260}>
          <RadarChart data={radarData} cx="50%" cy="50%" outerRadius="75%">
            <PolarGrid stroke="#e5e7eb" />
            <PolarAngleAxis
              dataKey="axis"
              tick={{ fontSize: 11, fill: '#6b7280', fontWeight: 600 }}
            />
            <Radar
              name="都平均"
              dataKey="average"
              stroke="#9ca3af"
              fill="#9ca3af"
              fillOpacity={0.1}
              strokeDasharray="4 4"
              strokeWidth={1.5}
            />
            <Radar
              name={m.name}
              dataKey="value"
              stroke="#0ea5e9"
              fill="#0ea5e9"
              fillOpacity={0.25}
              strokeWidth={2.5}
            />
            <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
          </RadarChart>
        </ResponsiveContainer>
      </div>

      {/* Axis breakdown with colored accordions */}
      <div className="space-y-3">
        <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
          指標の内訳
        </h3>
        {data.meta.axes.map((axis) => {
          const key = axis.key as AxisKey;
          const score = m.scores[key];
          const axisColor = AXIS_COLORS[key] || '#cbd5e1';

          return (
            <details key={key} className="group bg-card rounded-xl border border-border overflow-hidden shadow-sm">
              <summary className="flex items-center justify-between p-3 cursor-pointer hover:bg-muted/50 transition-colors list-none [&::-webkit-details-marker]:hidden">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full flex items-center justify-center text-lg bg-muted shadow-sm border border-border">
                    {AXIS_ICONS[key]}
                  </div>
                  <div>
                    <div className="text-sm font-bold">{axis.label}</div>
                    <div className="text-[10px] text-muted-foreground font-medium">
                      重み: {weights[key].toFixed(1)}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {/* Score with colored bar */}
                  <div className="text-right">
                    <div className="text-lg font-black tabular-nums" style={{ color: score !== null ? axisColor : undefined }}>
                      {score !== null ? formatScore(score) : '—'}
                    </div>
                  </div>
                  <div className="w-5 h-5 rounded-full flex items-center justify-center text-muted-foreground group-open:rotate-180 transition-transform bg-muted text-[10px]">
                    ▼
                  </div>
                </div>
              </summary>

              {/* Score bar */}
              <div className="px-3 pb-1">
                <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${score ?? 0}%`,
                      backgroundColor: axisColor,
                    }}
                  />
                </div>
              </div>

              {/* Indicators table */}
              <div className="px-3 pb-3 pt-2 border-t border-border/50 bg-muted/20">
                <div className="space-y-1">
                  {axis.indicators.map((ind) => {
                    const v = m.indicators[ind.key] || {
                      status: 'no_data' as const,
                      value: null,
                      score: null,
                      source: ind.source,
                      unit: ind.unit,
                    };
                    const src = sources[ind.source];
                    const perUnit =
                      v.per_10k != null
                        ? `(${formatNumber(v.per_10k, 2)}/万人)`
                        : v.per_km2 != null
                          ? `(${formatNumber(v.per_km2, 2)}/km²)`
                          : '';

                    return (
                      <div
                        key={ind.key}
                        className="flex justify-between items-center text-xs py-2 border-b border-border/30 last:border-0"
                      >
                        <div className="flex-1 min-w-0">
                          <span className="text-muted-foreground">
                            {ind.label}
                            {ind.reference_only && (
                              <span className="text-[9px] ml-1 opacity-60">※参考</span>
                            )}
                          </span>
                        </div>
                        <div className="text-right ml-3 shrink-0">
                          {v.status === 'ok' ? (
                            <div>
                              <span className="font-bold tabular-nums">
                                {formatNumber(v.value, 2)} {ind.unit}
                              </span>
                              {perUnit && (
                                <span className="text-[9px] text-muted-foreground ml-1">
                                  {perUnit}
                                </span>
                              )}
                            </div>
                          ) : (
                            <span className="text-destructive text-[10px]">なし</span>
                          )}
                          <div className="text-[9px] text-muted-foreground">
                            Score: {v.score != null ? formatScore(v.score) : '—'}
                            {src && (
                              <>
                                {' '}
                                <a
                                  href={src.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-blue-600 hover:underline"
                                  title={src.name}
                                >
                                  {ind.source}
                                </a>
                              </>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </details>
          );
        })}
      </div>
    </div>
  );
}
