"""パス・座標系・ログの共通設定。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

# data/src/core/config.py → data/
DATA_ROOT = Path(os.environ.get("REMOTELIFE_DATA_ROOT", Path(__file__).resolve().parents[2]))

RAW_DIR = DATA_ROOT / "raw"
INTERIM_DIR = DATA_ROOT / "interim"
PROCESSED_DIR = DATA_ROOT / "processed"

# 調査結果の書き出し先（成果物ではないので ensure_dirs では作らない）
ANALYSIS_DIR = DATA_ROOT / "analysis"

# 指標ごとに1ファイル（code,value の2列）。normalize / spatial_join が書く。
INDICATOR_DIR = INTERIM_DIR / "indicators"

# 上を欠損補完したもの。補完の無い指標もそのまま複製されるので、score 側は
# こちらのディレクトリだけを見れば全指標が揃う。
IMPUTED_INDICATOR_DIR = INTERIM_DIR / "indicators_imputed"

# どのセルを、どの参照自治体の値から埋めたかの記録。score 側が status: "imputed" を
# 付けるのに使う（補完値を通常値と見分けられなくしないため）。
IMPUTATION_LOG_CSV = INTERIM_DIR / "imputation_log.csv"

# 面積・人口など「◯◯あたり」の分母になる基礎データ
BASE_CSV = INTERIM_DIR / "municipal_base.csv"

# 空間結合の基準になる行政区域ポリゴン（D-common-02 を正規化したもの）
BOUNDARY_GEOJSON = INTERIM_DIR / "boundaries.geojson"

# ingest が書くダウンロード履歴
MANIFEST_JSON = RAW_DIR / "manifest.json"

OUTPUT_JSON = PROCESSED_DIR / "municipalities.json"
DEMO_JSON = PROCESSED_DIR / "municipalities.sample.json"

# 緯度経度。オープンデータの入力はほぼこれ
CRS_WGS84 = "EPSG:4326"
# 平面直角座標系 第IX系（東京都本土）。長さ・面積の計算はこちらで行う
CRS_PLANE = "EPSG:6677"

# 出力JSONのスキーマバージョン
SCHEMA_VERSION = "0.2"


def indicator_csv(dataset_id: str, indicator_key: str, *, imputed: bool = False) -> Path:
    """指標CSVの出力先。ファイル名の接頭語に出典データセットIDを付ける。

    どの原データから出た値かをファイル名だけで追えるようにするため
    （例: interim/indicators/D-cost-01_land_price_residential.csv）。
    補完後のファイルは同じ名前で indicators_imputed/ に置く（`imputed=True`）。
    """
    directory = IMPUTED_INDICATOR_DIR if imputed else INDICATOR_DIR
    return directory / f"{dataset_id}_{indicator_key}.csv"


def ensure_dirs() -> None:
    """出力先ディレクトリを作る。"""
    for d in (RAW_DIR, INTERIM_DIR, PROCESSED_DIR, INDICATOR_DIR, IMPUTED_INDICATOR_DIR):
        d.mkdir(parents=True, exist_ok=True)


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
