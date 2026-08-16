'use client';

import { useApp } from '@/lib/store';
import { Slider } from '@/components/ui/slider';
import { Button } from '@/components/ui/button';
import { AXIS_ICONS } from '@/lib/types';
import type { AxisKey } from '@/lib/types';
import { AXIS_COLORS } from '@/lib/scoring';

export default function WeightSliders() {
  const { state, dispatch } = useApp();
  const { data, weights } = state;

  if (!data) return null;

  const handleWeightChange = (key: AxisKey, val: number | readonly number[]) => {
    const value = Array.isArray(val) ? val[0] : val;
    dispatch({ type: 'SET_WEIGHT', payload: { key, value } });
  };

  const applyPreset = (presetWeights: Record<AxisKey, number>) => {
    dispatch({ type: 'APPLY_PRESET', payload: presetWeights });
  };

  const totalWeight = Object.values(weights).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-6">
      {/* Presets */}
      <div>
        <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-3">
          重視するポイント
        </h3>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            size="sm"
            className="text-xs h-8 rounded-full transition-all hover:scale-105"
            onClick={() => applyPreset(data.meta.default_weights)}
          >
            ⚖️ 均等
          </Button>
          {data.meta.presets.map((preset) => (
            <Button
              key={preset.key}
              variant="outline"
              size="sm"
              className="text-xs h-8 rounded-full transition-all hover:scale-105"
              onClick={() => applyPreset(preset.weights)}
            >
              {preset.label}
            </Button>
          ))}
        </div>
      </div>

      {/* Sliders */}
      <div className="space-y-4">
        {data.meta.axes.map((axis) => {
          const key = axis.key as AxisKey;
          const hasData = data.municipalities.some(
            (m) => m.scores[key] !== null
          );
          const weightPct = totalWeight > 0 ? (weights[key] / totalWeight) * 100 : 0;
          const axisColor = AXIS_COLORS[key] || '#9ca3af';

          return (
            <div key={key} className={`space-y-2 ${!hasData ? 'opacity-40' : ''}`}>
              <div className="flex items-center justify-between">
                <label className="text-sm flex items-center gap-2">
                  <div className="flex items-center justify-center w-6 h-6 rounded-full bg-muted text-sm">
                    {AXIS_ICONS[key]}
                  </div>
                  <span className="font-medium text-foreground">{axis.label}</span>
                  {!hasData && (
                    <span className="text-[10px] text-destructive bg-destructive/10 px-1.5 rounded-sm">
                      データなし
                    </span>
                  )}
                </label>
                <div className="flex items-center gap-2">
                  <div className="w-12 h-1.5 bg-muted rounded-full overflow-hidden">
                    <div
                      className="h-full transition-all duration-300"
                      style={{ width: `${weightPct}%`, backgroundColor: axisColor }}
                    />
                  </div>
                  <span className="text-sm font-mono text-muted-foreground tabular-nums w-6 text-right">
                    {weights[key].toFixed(1)}
                  </span>
                </div>
              </div>
              <Slider
                value={[weights[key]]}
                min={0}
                max={2}
                step={0.1}
                onValueChange={(val) => handleWeightChange(key, val)}
                disabled={!hasData}
                className="w-full cursor-pointer"
              />
            </div>
          );
        })}
      </div>

      <p className="text-[11px] text-muted-foreground leading-relaxed">
        総合スコア = Σ(軸スコア×重み) / Σ(重み)。欠損軸は分母からも除外。
      </p>
    </div>
  );
}
