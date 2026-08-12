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
make datasets       # D1〜D18 の定義と取得状況
make test lint
```

`make ingest` は 100MB を超えるファイル（土地利用現況調査GIS、緑のオープンデータの樹林地）を既定では取得しない。
必要になったら `--heavy` を渡すか、`--only` でIDを指定する。

各スクリプトは直接叩いてもよい（`--only` などの引数を渡すときはこちら）。

```bash
uv run python src/ingest.py --only D8 D11
uv run python src/ingest.py --heavy          # 大容量ファイルもあわせて取得
uv run python src/normalize.py --status
uv run python src/spatial_join.py --boundaries
uv run python src/score.py --demo
```

## ディレクトリ

| パス | 中身 | Git |
|---|---|---|
| `src/` | パイプライン本体（`.py` をフラットに配置） | 追跡 |
| `raw/<データセットID>/` | 取得した原データそのまま。zipは同名ディレクトリに展開済み | 除外 |
| `raw/manifest.json` | ファイルごとの取得元URL・取得日時・SHA256 | 除外 |
| `interim/` | 正規化済みの中間データ | 除外 |
| `interim/indicators/<指標キー>.csv` | 指標ごとの `code,value` | 除外 |
| `interim/municipal_base.csv` | 面積・人口（全指標の分母） | 除外 |
| `processed/municipalities.json` | 最終成果物 | 追跡 |

## モジュール

| ファイル | 役割 |
|---|---|
| `config.py` | パス・座標系・ログ設定 |
| `municipalities.py` | 53自治体マスタ。表記ゆれ・旧市名・住所文字列からコードを解決 |
| `datasets.py` | D1〜D18 の出典定義とダウンロードURL。ここがそのまま JSON の `meta.sources` になる |
| `indicators.py` | 6軸と指標の定義（向き・分母・単位）、プリセット重み |
| `io_utils.py` | 文字コード自動判定、数値パース、JSON/CSV入出力 |
| `ingest.py` | ダウンロードと取得履歴の記録 |
| `normalize.py` | データセット別の読み取りハンドラ |
| `spatial_join.py` | GeoPandas による点/線/面 → 自治体の集約 |
| `score.py` | 正規化とスコア算出、JSON出力 |

## 出力スキーマ（`processed/municipalities.json`）

```jsonc
{
  "meta": {
    "generated_at": "2026-08-12",
    "version": "0.2",
    "axes": [                          // 軸と指標の定義。画面の説明表示に使う
      { "key": "quiet", "label": "しずけさ", "description": "…",
        "indicators": [
          { "key": "pm25_annual_avg", "label": "PM2.5", "unit": "μg/m3",
            "direction": "lower_is_better", "definition": "…",
            "source": "D1", "reference_only": false }
        ] }
    ],
    "default_weights": { "quiet": 1.0, "…": 1.0 },
    "presets": [                       // 仕様書4.4のワンタップ切替
      { "key": "full_remote", "label": "フルリモート集中型",
        "weights": { "quiet": 2.0, "…": 0.2 } }
    ],
    "sources": [                       // 出典。画面から原典へ辿るためのリンク元
      { "id": "D8", "name": "…", "org": "…", "url": "https://…",
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
                  "commute": 98.1, "cost": 12.5, "community": 76.3 },
      "indicators": {
        "satellite_office_count": { "value": 55, "per_10k": 1.58, "unit": "件",
                                    "score": 96.2, "source": "D8", "status": "ok" },
        "park_count":             { "value": null, "score": null,
                                    "source": "D7", "status": "no_data" }
      }
    }
  ]
}
```

- `scores` は各軸 0〜100。指標が全欠損の軸は `null`。
- `reference_only: true` の指標（昼夜間人口比率）は軸スコアに算入していない。数値表示のみ。
- `per_10k` / `per_km2` は「◯◯あたり」に換算した後の値。スコアはこの値から計算される。
