"""指標の欠損レポート

interim/indicators/ の各指標について、53自治体のうち値が欠けている数と割合、
どの自治体が欠けているかを集計する。
"""

from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd

from analysis._report import format_pct, heading, join_names, print_list, print_table, truncate
from core import municipalities as muni
from core.config import INDICATOR_DIR, setup_logging
from defs.indicators import AXES, INDICATOR_BY_KEY, INDICATORS
from pipeline import score

logger = logging.getLogger(__name__)

TOTAL = len(muni.CODES)


def load_frame(verbose: bool = False) -> pd.DataFrame:
    """自治体 × 全指標 の表を作る。

    読み込みは score.py と同じ経路を通す（レポートと成果物で欠損の判定がずれないよう、
    自前で CSV を読み直さない）。指標ごとの読み込みログはこのレポートと内容が重複するため、
    -v のときだけ出す。
    """
    logging.getLogger(score.__name__).setLevel(logging.DEBUG if verbose else logging.WARNING)
    values = score.load_indicator_values().reindex(muni.CODES)
    frame = pd.DataFrame(index=pd.Index(muni.CODES, name="code"))
    for ind in INDICATORS:
        frame[ind.key] = values[ind.key] if ind.key in values.columns else np.nan
    return frame


def generated_keys() -> set[str]:
    """interim/indicators/ に実ファイルがある指標キー。"""
    if not INDICATOR_DIR.exists():
        return set()
    return {p.stem for p in INDICATOR_DIR.glob("*.csv")}


def missing_codes(frame: pd.DataFrame, key: str) -> list[str]:
    return [c for c in muni.CODES if pd.isna(frame.at[c, key])]


def region_count(codes: list[str], region: str) -> int:
    return sum(1 for c in codes if muni.BY_CODE[c].region == region)


def print_by_indicator(frame: pd.DataFrame, generated: set[str], limit: int) -> None:
    heading("指標ごとの欠損")
    rows = []
    for ind in INDICATORS:
        missing = missing_codes(frame, ind.key)
        mark = "" if ind.include_in_axis else "*"
        mark += "" if ind.key in generated else "†"
        rows.append(
            [
                truncate(ind.key + mark, 30),
                ind.axis,
                f"{TOTAL - len(missing)}/{TOTAL}",
                format_pct(len(missing) / TOTAL),
                str(region_count(missing, "区部")),
                str(region_count(missing, "多摩")),
                join_names([muni.BY_CODE[c].name for c in missing], limit),
            ]
        )
    print_table(
        ["指標", "軸", "充足", "欠損率", "区部", "多摩", "欠けている自治体"],
        rows,
        aligns=["left", "left", "right", "right", "right", "right", "left"],
    )
    print("  * 参考指標（軸スコアには算入しない）　† interim/indicators/ にファイルが無い")


def print_ungenerated(generated: set[str]) -> None:
    heading("ファイルが無い指標（未生成）")
    print_list(
        f"{ind.key}  ({ind.dataset_id} / {ind.label})"
        for ind in INDICATORS
        if ind.key not in generated
    )

    unknown = sorted(generated - set(INDICATOR_BY_KEY))
    if unknown:
        heading("indicators.py に定義の無いCSV（score.py では無視される）")
        print_list(f"{key}.csv" for key in unknown)


def print_by_municipality(frame: pd.DataFrame, full: bool, limit: int) -> None:
    counts = frame.isna().sum(axis=1).sort_values(ascending=False)
    rows = []
    for code, n in counts.items():
        if n == 0:
            continue
        m = muni.BY_CODE[code]
        keys = [k for k in frame.columns if pd.isna(frame.at[code, k])]
        # 指標キーは自治体名より長いので、並べる数を半分に抑えて表の幅を保つ
        rows.append(
            [
                m.name,
                m.region,
                f"{int(n)}/{len(frame.columns)}",
                join_names(keys, max(limit // 2, 2)),
            ]
        )
    heading(f"自治体ごとの欠損（欠損の多い順 / 全{len(rows)}自治体）")
    shown = rows if full else rows[:15]
    print_table(
        ["自治体", "区分", "欠損数", "欠けている指標"],
        shown,
        aligns=["left", "left", "right", "left"],
        empty="欠損なし",
    )
    if len(rows) > len(shown):
        print(f"  … ほか {len(rows) - len(shown)} 自治体（--full で全件表示）")


def print_by_axis(frame: pd.DataFrame, limit: int) -> None:
    """軸スコアは軸内の指標が全欠損だと算出できない。その自治体を洗い出す。"""
    heading("軸スコアを算出できない自治体")
    rows = []
    for axis in AXES:
        keys = [i.key for i in INDICATORS if i.axis == axis.key and i.include_in_axis]
        blank = [c for c in muni.CODES if frame.loc[c, keys].isna().all()]
        rows.append(
            [
                axis.key,
                axis.label,
                str(len(keys)),
                f"{TOTAL - len(blank)}/{TOTAL}",
                join_names([muni.BY_CODE[c].name for c in blank], limit),
            ]
        )
    print_table(
        ["軸", "名称", "算入指標", "算出できた", "算出できない自治体"],
        rows,
        aligns=["left", "left", "right", "right", "left"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="指標×自治体の欠損を集計する")
    parser.add_argument("--full", action="store_true", help="自治体ごとの欠損を全件表示する")
    parser.add_argument("--names", type=int, default=6, help="1行に並べる名前の数（既定6）")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    if not INDICATOR_DIR.exists():
        logger.error(
            "%s がありません。先に make normalize / make spatial-join を実行してください。",
            INDICATOR_DIR,
        )
        return 1

    frame = load_frame(args.verbose)
    generated = generated_keys()

    filled = int(frame.notna().sum().sum())
    cells = TOTAL * len(INDICATORS)
    print(f"欠損レポート: {TOTAL}自治体 × {len(INDICATORS)}指標 = {cells} セル")
    print(f"うち値あり {filled} セル（充足率 {format_pct(filled / cells)}）")
    print(f"指標ファイル: {len(generated & set(INDICATOR_BY_KEY))}/{len(INDICATORS)} 生成済み")

    print_by_indicator(frame, generated, args.names)
    print_ungenerated(generated)
    print_by_municipality(frame, args.full, args.names)
    print_by_axis(frame, args.names)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
