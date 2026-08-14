'use client';

import dynamic from 'next/dynamic';
import { AppProvider, useApp } from '@/lib/store';
import WeightSliders from '@/components/WeightSliders';
import FillModeSelector from '@/components/FillModeSelector';
import RankingList from '@/components/RankingList';
import DetailPanel from '@/components/DetailPanel';

// MapLibre must be loaded client-side only (no SSR)
const MapView = dynamic(() => import('@/components/MapView'), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full bg-muted/30 rounded-lg">
      <div className="text-sm text-muted-foreground animate-pulse">
        地図を読み込み中…
      </div>
    </div>
  ),
});

function AppContent() {
  const { state } = useApp();

  if (state.loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center space-y-3">
          <div className="text-4xl animate-bounce">🏠</div>
          <p className="text-sm text-muted-foreground animate-pulse">
            データを読み込み中…
          </p>
        </div>
      </div>
    );
  }

  if (state.error) {
    return (
      <div className="flex items-center justify-center h-screen p-8">
        <div className="max-w-md text-center space-y-4">
          <div className="text-4xl">⚠️</div>
          <h2 className="text-lg font-semibold">データの読み込みに失敗しました</h2>
          <p className="text-sm text-muted-foreground">{state.error}</p>
          <div className="text-xs text-muted-foreground bg-muted rounded-lg p-3 text-left">
            <p className="font-medium mb-1">解決方法:</p>
            <code className="text-[11px]">
              cd client/app && npm run dev
            </code>
            <p className="mt-1">
              <code>public/data/</code> に <code>municipalities.json</code> と{' '}
              <code>boundaries.geojson</code> が必要です。
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-background">
      {/* Header */}
      <header className="shrink-0 bg-card/80 backdrop-blur-md border-b border-border px-5 py-3 flex items-center gap-4 z-20 shadow-sm">
        <h1 className="text-xl font-extrabold tracking-tight flex items-center gap-2">
          <span>🏠</span>
          <span className="bg-gradient-to-r from-blue-600 to-emerald-500 bg-clip-text text-transparent">
            RemoteLife
          </span>
          <span className="text-foreground/90">Tokyo</span>
        </h1>
        <div className="hidden md:flex flex-col">
          <span className="text-xs text-muted-foreground font-medium">
            家で働く1日の質で、街を比べよう
          </span>
        </div>
        <div className="flex-1" />
        {state.data && (
          <div className="flex items-center gap-3">
            {state.data.meta.demo ? (
              <span className="bg-amber-50 text-amber-700 border border-amber-200 rounded-full px-2.5 py-0.5 text-[10px] font-semibold">
                ダミーデータ
              </span>
            ) : (
              <span className="bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full px-2.5 py-0.5 text-[10px] font-semibold">
                実データ
              </span>
            )}
            <span className="text-[11px] text-muted-foreground hidden sm:inline tabular-nums">
              v{state.data.meta.version}
            </span>
          </div>
        )}
      </header>

      {/* Main content */}
      <main className="flex-1 flex overflow-hidden">
        {/* Left sidebar - Controls */}
        <aside className="w-[280px] shrink-0 border-r border-border bg-card/50 backdrop-blur-xl overflow-y-auto hidden lg:block z-10">
          <div className="p-5 space-y-6">
            <WeightSliders />
            <div className="border-t border-border/50 pt-5">
              <FillModeSelector />
            </div>
          </div>
        </aside>

        {/* Map */}
        <div className="flex-1 relative bg-[#f8fafc]">
          <MapView />
        </div>

        {/* Right sidebar - Ranking & Detail */}
        <aside className="w-[340px] shrink-0 border-l border-border bg-card/50 backdrop-blur-xl overflow-y-auto hidden md:block z-10">
          <div className="p-5 space-y-6">
            <RankingList />
            <div className="border-t border-border/50 pt-5">
              <DetailPanel />
            </div>
          </div>
        </aside>
      </main>

      {/* Mobile bottom controls */}
      <div className="lg:hidden md:hidden border-t border-border bg-card z-20">
        <MobileDrawer />
      </div>
    </div>
  );
}

function MobileDrawer() {
  const { state } = useApp();
  if (!state.data) return null;

  return (
    <div className="p-4 space-y-4 max-h-[50vh] overflow-y-auto">
      <div className="flex gap-2 overflow-x-auto pb-2">
        <FillModeSelector />
      </div>
      <div className="space-y-4 border-t border-border/50 pt-4">
        <details className="group">
          <summary className="text-sm font-semibold text-foreground cursor-pointer">
            重み調整
          </summary>
          <div className="mt-3">
            <WeightSliders />
          </div>
        </details>
        <details className="group">
          <summary className="text-sm font-semibold text-foreground cursor-pointer">
            ランキング
          </summary>
          <div className="mt-3">
            <RankingList />
          </div>
        </details>
        <div className="border-t border-border/50 pt-4">
          <DetailPanel />
        </div>
      </div>
    </div>
  );
}

export default function Home() {
  return (
    <AppProvider>
      <AppContent />
    </AppProvider>
  );
}
