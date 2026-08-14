'use client';

import { useState } from 'react';
import { useApp } from '@/lib/store';
import { formatScore, scoreToColor } from '@/lib/scoring';

export default function RankingList() {
  const { state, dispatch, ranking } = useApp();
  const { selectedCode, data } = state;
  const [search, setSearch] = useState('');

  if (!data) return null;

  const totalAxes = data.meta.axes.length;
  const filtered = ranking.filter((r) =>
    r.municipality.name.includes(search)
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
          ランキング
        </h3>
        <span className="text-[11px] bg-muted px-2 py-0.5 rounded-full text-muted-foreground font-medium">
          全{ranking.length}自治体
        </span>
      </div>

      {/* Search */}
      <div className="mb-3">
        <input
          type="text"
          placeholder="自治体名で検索..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full h-8 text-xs bg-muted/50 border-none rounded-lg px-3 placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-ring/30"
        />
      </div>

      <div className="max-h-[420px] overflow-y-auto -mx-1 px-1 space-y-1">
        {filtered.map((item) => {
          const isSelected = item.municipality.code === selectedCode;
          const isThin = item.used < totalAxes;
          let medal = '';
          if (item.rank === 1) medal = '🥇';
          else if (item.rank === 2) medal = '🥈';
          else if (item.rank === 3) medal = '🥉';

          return (
            <div
              key={item.municipality.code}
              onClick={() =>
                dispatch({
                  type: 'SET_SELECTED',
                  payload: isSelected ? null : item.municipality.code,
                })
              }
              className={`
                flex items-center p-2 rounded-lg cursor-pointer transition-all duration-200
                ${isSelected ? 'bg-primary text-primary-foreground shadow-md scale-[1.02]' : 'hover:bg-muted/80'}
                ${isThin && !isSelected ? 'opacity-60' : ''}
              `}
            >
              <div className="w-8 text-center text-xs font-bold shrink-0">
                {medal ? (
                  <span className="text-sm">{medal}</span>
                ) : (
                  <span className={isSelected ? '' : 'text-muted-foreground'}>
                    {item.rank || '—'}
                  </span>
                )}
              </div>
              <div className="flex-1 min-w-0 ml-2">
                <div className="text-sm font-bold truncate">
                  {item.municipality.name}
                </div>
                <div className={`w-full h-1 rounded-full mt-1 overflow-hidden ${isSelected ? 'bg-primary-foreground/20' : 'bg-muted'}`}>
                  <div
                    className="h-full rounded-full transition-all duration-300"
                    style={{
                      width: `${item.score ?? 0}%`,
                      backgroundColor: isSelected ? '#ffffff' : scoreToColor(item.score),
                    }}
                  />
                </div>
              </div>
              <div className="text-right ml-3 shrink-0">
                <div className="text-lg font-bold tabular-nums leading-none">
                  {item.score !== null ? formatScore(item.score) : '—'}
                </div>
                <div
                  className={`text-[9px] mt-1 ${isSelected ? 'text-primary-foreground/70' : 'text-muted-foreground'}`}
                >
                  {item.used}/{totalAxes}軸
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
