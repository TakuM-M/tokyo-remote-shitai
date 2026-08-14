'use client';

import { useApp } from '@/lib/store';
import { Button } from '@/components/ui/button';
import type { AxisKey } from '@/lib/types';
import { AXIS_ICONS } from '@/lib/types';

export default function FillModeSelector() {
  const { state, dispatch } = useApp();
  const { data, fillMode } = state;

  if (!data) return null;

  return (
    <div>
      <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-3">
        マップ表示
      </h3>
      <div className="flex flex-wrap gap-2">
        <Button
          variant={fillMode === 'total' ? 'default' : 'outline'}
          size="sm"
          className={`text-xs h-8 rounded-full transition-all ${fillMode === 'total' ? 'shadow-md' : 'hover:bg-muted'}`}
          onClick={() => dispatch({ type: 'SET_FILL_MODE', payload: 'total' })}
        >
          🏆 総合スコア
        </Button>
        {data.meta.axes.map((axis) => {
          const key = axis.key as AxisKey;
          const isActive = fillMode === key;
          return (
            <Button
              key={key}
              variant={isActive ? 'default' : 'outline'}
              size="sm"
              className={`text-xs h-8 rounded-full transition-all ${isActive ? 'shadow-md' : 'hover:bg-muted'}`}
              onClick={() => dispatch({ type: 'SET_FILL_MODE', payload: key })}
            >
              {AXIS_ICONS[key]} {axis.label}
            </Button>
          );
        })}
      </div>
    </div>
  );
}
