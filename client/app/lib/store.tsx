'use client';

import React, { createContext, useContext, useReducer, useCallback, useEffect } from 'react';
import type { MunicipalityData, Municipality, Weights, AxisKey, ScoreResult } from './types';
import { calculateTotalScore, calculateRanking, calculateAverageScores } from './scoring';

interface AppState {
  data: MunicipalityData | null;
  loading: boolean;
  error: string | null;
  weights: Weights;
  selectedCode: string | null;
  fillMode: 'total' | AxisKey;
}

type Action =
  | { type: 'SET_DATA'; payload: MunicipalityData }
  | { type: 'SET_ERROR'; payload: string }
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_WEIGHTS'; payload: Weights }
  | { type: 'SET_WEIGHT'; payload: { key: AxisKey; value: number } }
  | { type: 'SET_SELECTED'; payload: string | null }
  | { type: 'SET_FILL_MODE'; payload: 'total' | AxisKey }
  | { type: 'APPLY_PRESET'; payload: Weights };

const initialState: AppState = {
  data: null,
  loading: true,
  error: null,
  weights: { quiet: 1, refresh: 1, workspace: 1, commute: 1, cost: 1, community: 1 },
  selectedCode: null,
  fillMode: 'total',
};

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'SET_DATA':
      return {
        ...state,
        data: action.payload,
        weights: { ...action.payload.meta.default_weights },
        loading: false,
        error: null,
      };
    case 'SET_ERROR':
      return { ...state, error: action.payload, loading: false };
    case 'SET_LOADING':
      return { ...state, loading: action.payload };
    case 'SET_WEIGHTS':
      return { ...state, weights: action.payload };
    case 'SET_WEIGHT':
      return {
        ...state,
        weights: { ...state.weights, [action.payload.key]: action.payload.value },
      };
    case 'SET_SELECTED':
      return { ...state, selectedCode: action.payload };
    case 'SET_FILL_MODE':
      return { ...state, fillMode: action.payload };
    case 'APPLY_PRESET':
      return { ...state, weights: { ...action.payload } };
    default:
      return state;
  }
}

interface AppContextValue {
  state: AppState;
  dispatch: React.Dispatch<Action>;
  selectedMunicipality: Municipality | null;
  ranking: ReturnType<typeof calculateRanking>;
  averageScores: Record<AxisKey, number | null>;
  getScore: (municipality: Municipality) => ScoreResult;
  getFillValue: (municipality: Municipality) => number | null;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  // Load data on mount
  useEffect(() => {
    async function loadData() {
      try {
        const res = await fetch('/data/municipalities.json');
        if (!res.ok) throw new Error(`Failed to load data: ${res.status}`);
        const data: MunicipalityData = await res.json();
        dispatch({ type: 'SET_DATA', payload: data });
      } catch (e) {
        dispatch({ type: 'SET_ERROR', payload: (e as Error).message });
      }
    }
    loadData();
  }, []);

  const selectedMunicipality = state.data?.municipalities.find(
    (m) => m.code === state.selectedCode
  ) ?? null;

  const ranking = state.data
    ? calculateRanking(state.data.municipalities, state.weights)
    : [];

  const averageScores = state.data
    ? calculateAverageScores(state.data.municipalities)
    : ({ quiet: null, refresh: null, workspace: null, commute: null, cost: null, community: null } as Record<AxisKey, number | null>);

  const getScore = useCallback(
    (municipality: Municipality) => calculateTotalScore(municipality, state.weights),
    [state.weights]
  );

  const getFillValue = useCallback(
    (municipality: Municipality): number | null => {
      if (state.fillMode === 'total') {
        return calculateTotalScore(municipality, state.weights).score;
      }
      return municipality.scores[state.fillMode] ?? null;
    },
    [state.weights, state.fillMode]
  );

  const value: AppContextValue = {
    state,
    dispatch,
    selectedMunicipality,
    ranking,
    averageScores,
    getScore,
    getFillValue,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const context = useContext(AppContext);
  if (!context) throw new Error('useApp must be used within AppProvider');
  return context;
}
