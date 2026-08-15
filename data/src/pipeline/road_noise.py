"""D-quiet-02（自動車交通騒音調査結果）→ 指標 road_noise_leq

平成20〜25年度の6年分のCSVを読み、自治体ごとの昼間等価騒音レベルを出す。

調査地点は年度ごとに入れ替わるため、単年では測定のない自治体が出る
（平成25年度は檜原村、平成21〜24年度は練馬区が欠測）。6年分を合わせると
53自治体すべてが埋まるので、以下の手順で埋める:

    1. 年度ごとに、測定地点を住所から自治体に割り当てて昼間Leqを平均する
    2. 自治体ごとに、値のある最も新しい年度の平均値を採る
    3. どの年度にも値が無い自治体は欠損のまま残す（0では埋めない）

出力は interim/indicators/road_noise_leq.csv。参照した年度と地点数も並べて書き、
古い年度で埋めた自治体を後から追えるようにする。

    PYTHONPATH=src uv run python -m pipeline.road_noise
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from core import municipalities as muni
from core.config import INDICATOR_DIR, RAW_DIR, ensure_dirs, setup_logging
from core.io_utils import parse_number, read_csv, write_interim_csv
from defs import datasets

logger = logging.getLogger(__name__)

DATASET_ID = "D-quiet-02"
INDICATOR_KEY = "road_noise_leq"

# 年度によって列名が揺れる（「測定地点の住所」/「測定地点住所」、
# 「昼間等価騒音レベル(Leq)(dB)」/「昼間等価騒音レベル(dB)」）ため部分一致で拾う。
ADDRESS_HINT = "住所"
DAY_HINT = "昼間"
NIGHT_HINT = "夜間"


def pick_column(df: pd.DataFrame, hint: str) -> str:
    """名前に `hint` を含む列を1つ選ぶ。"""
    for col in df.columns:
        if hint in str(col):
            return str(col)
    raise KeyError(f"『{hint}』を含む列がありません: {list(df.columns)}")


def read_year(path: Path, year: int) -> pd.DataFrame:
    """1年度分のCSVを 自治体コード × 昼間Leq の地点表にする。

    昼間の値が数値の行だけを採る（「欠測」「-」の行は落とす）。
    夜間が「-」の地点は昼間しか測っていないだけなので残す。
    """
    df = read_csv(path)
    address = pick_column(df, ADDRESS_HINT)
    day = pick_column(df, DAY_HINT)
    night = pick_column(df, NIGHT_HINT)

    points = muni.attach_code(df, name_col=address)
    points["leq_day"] = points[day].map(parse_number)

    # 列が1つ足りない行が混じる（平成25年度に2件）。pandas が末尾を空で埋めるため、
    # 昼間・夜間の値が1列ずれて入り、夜間の欄だけが空になる。昼間の値も信用できない。
    # 夜間を「-」と書いた地点は空欄ではないので、この条件では落ちない。
    shifted = points[night].fillna("").astype(str).str.strip() == ""
    valid = points.loc[~shifted].dropna(subset=["leq_day"])
    logger.info(
        "[%s] %d年度: 地点 %d件（うち有効 %d件） / %d自治体",
        DATASET_ID,
        year,
        len(points),
        len(valid),
        valid["code"].nunique(),
    )
    return valid.loc[:, ["code", "leq_day"]].assign(year=year)


def load_points() -> pd.DataFrame:
    """取得済みの年度をすべて読んで1つの地点表にする。"""
    resources = sorted(datasets.get(DATASET_ID).resources, key=lambda r: r.year or 0, reverse=True)
    frames = []
    for res in resources:
        path = RAW_DIR / DATASET_ID / res.filename
        if not path.exists():
            logger.warning("[%s] 未取得のためスキップ: %s", DATASET_ID, res.filename)
            continue
        frames.append(read_year(path, int(res.year)))
    if not frames:
        raise FileNotFoundError(
            f"{RAW_DIR / DATASET_ID} にCSVがありません。先に ingest を実行してください。"
        )
    return pd.concat(frames, ignore_index=True)


def aggregate(points: pd.DataFrame) -> pd.DataFrame:
    """自治体ごとに、値のある最も新しい年度の平均を採る。

    dB は対数量なので、音響的には地点をエネルギー合成するのが正しい。ただしそれだと
    自治体内で最も大きい1地点にほぼ支配される。ここで見たいのは「幹線道路沿いの地点は
    平均してどのくらいうるさいか」なので、地点を等しく扱う算術平均にする。
    """
    per_year = (
        points.groupby(["code", "year"])["leq_day"].agg(value="mean", points="size").reset_index()
    )
    latest = (
        per_year.sort_values(["code", "year"], ascending=[True, False])
        .drop_duplicates("code", keep="first")
        .reset_index(drop=True)
    )
    latest["value"] = latest["value"].round(1)
    return latest.loc[:, ["code", "value", "year", "points"]]


def log_fallbacks(points: pd.DataFrame, result: pd.DataFrame) -> None:
    """古い年度で埋めた自治体をログに残す（黙って混ぜない）。"""
    newest = int(points["year"].max())
    older = result[result["year"] != newest]
    logger.info(
        "[%s] %d/53 自治体。うち %d 自治体は %d年度に測定が無く過去の年度で補完",
        DATASET_ID,
        len(result),
        len(older),
        newest,
    )
    for row in older.itertuples():
        logger.info("  %s ← %d年度（%d地点）", muni.BY_CODE[row.code].name, row.year, row.points)
    muni.check_coverage(result["code"], INDICATOR_KEY)


def run() -> pd.DataFrame:
    points = load_points()
    result = aggregate(points)
    log_fallbacks(points, result)
    write_interim_csv(result, INDICATOR_DIR / f"{INDICATOR_KEY}.csv")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="自動車交通騒音調査結果を自治体別に集計する")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    ensure_dirs()
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
