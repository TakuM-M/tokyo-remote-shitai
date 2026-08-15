// Types matching municipalities.json structure

export interface IndicatorMeta {
  key: string;
  label: string;
  unit: string;
  direction: 'lower_is_better' | 'higher_is_better';
  definition: string;
  source: string;
  reference_only: boolean;
}

export interface AxisMeta {
  key: AxisKey;
  label: string;
  description: string;
  indicators: IndicatorMeta[];
}

export type AxisKey = 'quiet' | 'refresh' | 'workspace' | 'commute' | 'cost' | 'community';

export const AXIS_KEYS: AxisKey[] = ['quiet', 'refresh', 'workspace', 'commute', 'cost', 'community'];

export const AXIS_ICONS: Record<AxisKey, string> = {
  quiet: '🤫',
  refresh: '🌿',
  workspace: '💻',
  commute: '🚃',
  cost: '🏠',
  community: '🤝',
};

export interface SourceMeta {
  id: string;
  name: string;
  org: string;
  url: string;
  license: string;
  updated_at?: string;
  notes?: string;
}

export interface PresetMeta {
  key: string;
  label: string;
  weights: Weights;
}

export type Weights = Record<AxisKey, number>;

export interface DataMeta {
  generated_at: string;
  version: string;
  axes: AxisMeta[];
  default_weights: Weights;
  presets: PresetMeta[];
  sources: SourceMeta[];
  demo?: boolean;
}

export interface IndicatorValue {
  value: number | null;
  score: number | null;
  source: string;
  unit: string;
  status: 'ok' | 'no_data';
  per_10k?: number | null;
  per_km2?: number | null;
}

export interface Municipality {
  code: string;
  name: string;
  kind: string;
  region: string;
  area_km2: number;
  population: number;
  scores: Record<AxisKey, number | null>;
  indicators: Record<string, IndicatorValue>;
}

export interface MunicipalityData {
  meta: DataMeta;
  municipalities: Municipality[];
}

// Computed score result
export interface ScoreResult {
  score: number | null;
  used: number;
}
