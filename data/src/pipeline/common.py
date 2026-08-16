"""パイプライン各段で共有する入出力（入力ファイルの解決・指標CSVの書き出し・補完ログの形式）。

正規化と空間結合のどちらも同じ形の指標CSVを吐くため、実体をここに置く。
実行モジュール（`02-normalize` など）は名前にハイフンを含み import できないので、
共有するものは必ずこちら側に置くこと。
"""

from __future__ import annotations

import logging
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import IO

import pandas as pd

from core.config import INDICATOR_DIR, RAW_DIR, indicator_csv
from core.io_utils import write_interim_csv
from defs import datasets
from defs.indicators import INDICATOR_BY_KEY

logger = logging.getLogger(__name__)

# ハンドラの戻り値: {指標キー: DataFrame[code, value]}
IndicatorFrames = dict[str, pd.DataFrame]


# ---------------------------------------------------------------- 入力ファイルの解決


def raw_path(dataset_id: str, key: str) -> Path:
    """raw/<ID>/<保存名> を返す。"""
    resources = {r.key: r for r in datasets.get(dataset_id).resources}
    if key not in resources:
        raise KeyError(f"{dataset_id} に key={key} のファイル定義がありません: {list(resources)}")
    path = RAW_DIR / dataset_id / resources[key].filename
    if not path.exists():
        raise FileNotFoundError(f"{path} がありません。先に ingest を実行してください。")
    return path


def extracted_dir(dataset_id: str, key: str) -> Path:
    """zip配布ファイルの展開先を返す（ingest が zip と同じ場所に stem 名で作る）。"""
    out = raw_path(dataset_id, key).with_suffix("")
    if not out.is_dir():
        raise FileNotFoundError(f"{out} がありません。先に ingest を実行してください。")
    return out


def iter_zip_members(dataset_id: str, key: str, suffix: str = ".csv") -> Iterator[IO[bytes]]:
    """展開せずに置いている zip（`Resource.extract=False`）の中身を1件ずつ開く。

    使う列がごく一部で、展開すると桁違いに嵩むデータ向け。読む順を安定させるため
    格納名でソートして返す。
    """
    path = raw_path(dataset_id, key)
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if n.lower().endswith(suffix))
        if not names:
            raise FileNotFoundError(f"{path} に {suffix} が入っていません。")
        for name in names:
            logger.debug("zip内を読む: %s!%s", path.name, name)
            with z.open(name) as fh:
                yield fh


# ---------------------------------------------------------------- 出力


def write_indicators(dataset_id: str, frames: IndicatorFrames) -> None:
    """指標ごとに interim/indicators/<データセットID>_<指標キー>.csv を書く。

    先頭2列は必ず code,value に揃える。road_noise_leq の参照年度のような補足列は
    その後ろに残す（score 側は列名で読むので余分な列があっても困らない）。
    """
    INDICATOR_DIR.mkdir(parents=True, exist_ok=True)
    for key, frame in frames.items():
        if key not in INDICATOR_BY_KEY:
            logger.warning("indicators.py に定義の無い指標キーを書き出している: %s", key)
        extra = [c for c in frame.columns if c not in ("code", "value")]
        out = frame.loc[:, ["code", "value", *extra]].copy()
        out["code"] = out["code"].astype(str)
        # 欠損行は書かない。score 側で「値が無い＝no_data」として扱う（0で埋めない）。
        out = out.dropna(subset=["value"])
        write_interim_csv(out, indicator_csv(dataset_id, key))


# ---------------------------------------------------------------- 補完ログの形式

# 04-impute が書き、05-score が読む1行=1セルの記録。両者で列と区切りを揃えるため、
# 形式だけをここに置く（互いを import できないため）。
IMPUTATION_LOG_COLUMNS: tuple[str, ...] = ("indicator", "code", "value", "method", "reference")

# 参照自治体は複数ありうるが、CSVの1セルに収めたいのでカンマ以外で区切る
REFERENCE_SEPARATOR = "|"


def join_references(codes: Iterable[str]) -> str:
    return REFERENCE_SEPARATOR.join(codes)


def split_references(text: object) -> list[str]:
    return [c for c in str(text or "").split(REFERENCE_SEPARATOR) if c]
