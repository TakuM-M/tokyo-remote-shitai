# data — データ加工パイプライン

```
原データ ──(ingest)──▶ raw/ ────(normalize, spatial_join)──────▶ interim/ ──(score)──▶ processed/municipalities.json
```

## セットアップ

```bash
uv sync
```

## 実行

```bash
make ingest         # 原データを raw/ に取得
make normalize      # 文字コード変換・自治体コード付与・単位統一 → interim/
make spatial-join   # 点/線/面を自治体ポリゴンに集約 → interim/indicators/
make score          # ウィンザライズ → min-max → 軸スコア → processed/municipalities.json
make all            # 上を順に実行

make demo           # ダミーデータで processed/municipalities.sample.json を生成
make datasets       # 全8データセットの定義と取得状況
make test lint
```

```bash
make inventory      # raw/ の棚卸し。manifest.json との突き合わせ
make missing        # 指標×自治体の欠損レポート → analysis/missing_report.html, missing_matrix.csv
make stats          # 指標ごとの分布・外れ値・ウィンザライズの影響
make validate       # 出力JSONの検証。エラーがあれば終了コード1
make report         # 上記をまとめて可視化 → analysis/report.html
```

```bash
export PYTHONPATH=src
uv run python -m pipeline.01-ingest --only D-workspace-01 D-cost-01
uv run python -m pipeline.01-ingest --heavy       # 大容量ファイルもあわせて取得
uv run python -m pipeline.02-normalize --only D-cost-01   # 1データセットだけ正規化
uv run python -m pipeline.03-spatial_join --boundaries     # 行政区域ポリゴンの整備だけ
uv run python -m pipeline.score --demo

uv run python -m analysis.missing_report --open          # 欠損レポートを作ってブラウザで開く
uv run python -m analysis.raw_inventory --verify         # SHA256 を再計算して照合
uv run python -m analysis.indicator_stats --indicator npo_count   # 1指標の内訳
uv run python -m analysis.validate_output --demo         # ダミーデータの出力を検証
```

## 出力スキーマ（`processed/municipalities.json`）

```jsonc
{
  "meta": {
    "generated_at": "2026-08-12",
    "version": "0.2",
    "axes": [                          // 軸と指標の定義。画面の説明表示に使う
      { "key": "quiet", "label": "しずけさ", "description": "…",
        "indicators": [
          { "key": "pm25_recent_avg", "label": "PM2.5", "unit": "μg/m3",
            "direction": "lower_is_better", "definition": "…",
            "source": "D-quiet-01", "reference_only": false }
        ] }
    ],
    "default_weights": { "quiet": 1.0, "…": 1.0 },
    "presets": [                       // 重みのワンタップ切替
      { "key": "full_remote", "label": "フルリモート集中型",
        "weights": { "quiet": 2.0, "…": 0.5 } }
    ],
    "sources": [                       // 出典。画面から原典へ辿るためのリンク元
      { "id": "D-workspace-01", "name": "…", "org": "…", "url": "https://…",
        "license": "CC BY 4.0（東京都オープンデータ利用規約）",
        "updated_at": null,              // データ側の年次。「令和8年地価公示」のような和暦表記
        "notes": "…" }
    ]
  },
  "municipalities": [
    {
      "code": "13104", "name": "新宿区", "kind": "区", "region": "区部",
      "area_km2": 18.22, "population": 349000,
      "scores": { "quiet": 28.4, "refresh": 51.2, "workspace": 94.7,
                  "cost": 12.5, "community": 76.3 },
      "indicators": {
        "satellite_office_count": { "value": 55, "per_10k": 1.58, "unit": "件",
                                    "score": 96.2, "source": "D-workspace-01", "status": "ok" },
        "park_area":              { "value": 1181952, "per_capita": 3.27, "unit": "m2",
                                    "score": 22.6, "source": "D-refresh-01", "status": "ok" }
      }
    }
  ]
}
```