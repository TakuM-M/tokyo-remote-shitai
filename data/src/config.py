"""パス・座標系・ログの共通設定。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

# data/src/config.py → data/
DATA_ROOT = Path(os.environ.get("REMOTELIFE_DATA_ROOT", Path(__file__).resolve().parents[1]))

RAW_DIR = DATA_ROOT / "raw"
INTERIM_DIR = DATA_ROOT / "interim"
PROCESSED_DIR = DATA_ROOT / "processed"

# 指標ごとに1ファイル（code,value の2列）。score.py がこれを集めて読む。
INDICATOR_DIR = INTERIM_DIR / "indicators"

# 面積・人口など「◯◯あたり」の分母になる基礎データ
BASE_CSV = INTERIM_DIR / "municipal_base.csv"

# 空間結合の基準になる行政区域ポリゴン（D19 を正規化したもの）
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


def ensure_dirs() -> None:
    """出力先ディレクトリを作る。"""
    for d in (RAW_DIR, INTERIM_DIR, PROCESSED_DIR, INDICATOR_DIR):
        d.mkdir(parents=True, exist_ok=True)


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
