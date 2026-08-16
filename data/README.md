# data — データ加工パイプライン

```
原データ ──(01-ingest)──▶ raw/ ──(02-normalize, 03-spatial_join, 04-impute)──▶ interim/ ──(05-score)──▶ processed/municipalities.json
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
make impute         # 規則にもとづく欠損補完 → interim/indicators_imputed/, interim/imputation_log.csv
make score          # 分母換算 → パーセンタイル順位 → 軸スコア → processed/municipalities.json
make all            # 上を順に実行

make demo           # ダミーデータで processed/municipalities.sample.json を生成
make test lint
```

```bash
make missing        # 指標×自治体の欠損レポート → analysis/missing_report.html, missing_matrix.csv
```

```bash
export PYTHONPATH=src
uv run python -m pipeline.01-ingest --only D-workspace-01 D-cost-01   # データセットを指定して取得
uv run python -m pipeline.01-ingest --heavy       # 大容量ファイルもあわせて取得
uv run python -m pipeline.05-score --demo

uv run python -m analysis.missing_report --open          # 欠損レポートを作ってブラウザで開く
```

## 出力スキーマ（`processed/municipalities.json`）

```jsonc
{
  "meta": {
    "generated_at": "2026-08-12",
    "version": "0.2",
    "axes": [                          // 軸と指標の定義。画面の説明表示に使う
      { "key": "refresh", "label": "いきぬき", "description": "…",
        "indicators": [                // weight は軸スコアを平均するときの重み
          { "key": "green_coverage_ratio", "label": "緑・水辺率", "unit": "%",
            "direction": "higher_is_better", "definition": "…",
            "source": "D-refresh-02", "weight": 0.5, "reference_only": false }
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
        "satellite_office_count": { "value": 55, "per_km2": 4.7, "unit": "件",
                                    "score": 96.2, "source": "D-workspace-01", "status": "ok" },
        "park_area":              { "value": 1181952, "per_km2": 64871.1, "unit": "m2",
                                    "score": 22.6, "source": "D-refresh-01", "status": "ok" },
        "green_coverage_ratio":   { "value": 3.15, "unit": "%",
                                    "score": 14.8, "source": "D-refresh-02", "status": "ok" }
      }
    }
  ]
}
```

`status` は `ok` / `imputed` / `no_data` の3値。`imputed` は原データに調査地点が無い自治体を
近隣自治体の値で埋めたもので、参照元の自治体コードを `imputed_from` に持つ
（例: 檜原村の地価 `{ "value": 93675.0, "status": "imputed", "imputed_from": ["13205", "13305"] }`）。
補完の規則は `src/defs/imputation.py`、実行は `make impute`。