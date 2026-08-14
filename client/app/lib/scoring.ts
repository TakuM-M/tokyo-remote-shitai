import type { Municipality, Weights, ScoreResult, AxisKey } from './types';
import { AXIS_KEYS } from './types';

/**
 * 加重平均による総合スコア算出
 * 欠損軸は重みの分母からも除外し、全軸欠損なら null を返す
 */
export function calculateTotalScore(
  municipality: Municipality,
  weights: Weights
): ScoreResult {
  let numerator = 0;
  let denominator = 0;
  let used = 0;

  for (const key of AXIS_KEYS) {
    const score = municipality.scores[key];
    const weight = weights[key];
    if (score === null || score === undefined || !weight) continue;
    numerator += score * weight;
    denominator += weight;
    used += 1;
  }

  return {
    score: denominator > 0 ? Math.round((numerator / denominator) * 10) / 10 : null,
    used,
  };
}

/**
 * 全自治体のスコアを計算してソートしたランキングを返す
 */
export function calculateRanking(
  municipalities: Municipality[],
  weights: Weights
): Array<{ municipality: Municipality; score: number | null; used: number; rank: number }> {
  const scored = municipalities.map((m) => {
    const result = calculateTotalScore(m, weights);
    return { municipality: m, ...result };
  });

  scored.sort((a, b) => (b.score ?? -1) - (a.score ?? -1));

  return scored.map((item, index) => ({
    ...item,
    rank: item.score !== null ? index + 1 : 0,
  }));
}

/**
 * 全自治体の平均スコアを軸ごとに算出
 */
export function calculateAverageScores(
  municipalities: Municipality[]
): Record<AxisKey, number | null> {
  const result = {} as Record<AxisKey, number | null>;
  for (const key of AXIS_KEYS) {
    const values = municipalities
      .map((m) => m.scores[key])
      .filter((v): v is number => v !== null && v !== undefined);
    result[key] = values.length > 0
      ? Math.round((values.reduce((a, b) => a + b, 0) / values.length) * 10) / 10
      : null;
  }
  return result;
}

/**
 * コロプレス地図用のカラースケール（5段階）
 * YlGnBu風カラーランプ
 */
export const COLOR_RAMP = ['#ffffd9', '#c7e9b4', '#41b6c4', '#2c7fb8', '#253494'];
export const NO_DATA_COLOR = '#e5e7eb';

/**
 * 軸ごとのテーマカラー
 */
export const AXIS_COLORS: Record<AxisKey, string> = {
  quiet: '#6366f1',     // indigo
  refresh: '#22c55e',   // green
  workspace: '#f59e0b', // amber
  commute: '#3b82f6',   // blue
  cost: '#ef4444',      // red
  community: '#a855f7', // purple
};

export function scoreToColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return NO_DATA_COLOR;
  const index = Math.min(4, Math.floor(score / 20));
  return COLOR_RAMP[index];
}

/**
 * スコアを 0-100 の範囲でフォーマット
 */
export function formatScore(score: number | null | undefined, decimals = 1): string {
  if (score === null || score === undefined) return '—';
  return score.toFixed(decimals);
}

export function formatNumber(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined) return '—';
  return Number(value).toLocaleString('ja-JP', { maximumFractionDigits: decimals });
}
